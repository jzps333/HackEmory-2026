"""Runs INSIDE a throwaway Docker container. Opens one URL, records what happened, prints JSON.

Usage (inside the container): python run_scan.py <url>
No keys, no logins, no personal data live here. Downloads are blocked, never opened.

Network guard: every request the browser makes (first URL, each redirect hop, subresources,
popups, iframes) goes through context.route(); its hostname is resolved and the request is
aborted unless EVERY resolved address is public (see netguard.py). Blocked requests are listed
in `blocked_requests`. Service workers and WebSockets are blocked so nothing bypasses routing.
The host firewall on the sandbox VM is the second layer (see README.md).
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from netguard import CachingGuard, is_public_ip

MAX_TEXT = 4000            # page_text characters
MAX_HIDDEN = 1500          # hidden_text characters
MAX_FIELDS = 25            # form fields
MAX_FIELD_STR = 80         # characters per form-field attribute
MAX_BLOCKED = 30           # blocked_requests entries
MAX_HOPS = 10              # main-frame navigations before we stop following
MAX_REQUESTS = 300         # total requests per scan before we abort the rest
TIMEOUT_MS = 20000
SETTLE_MS = 2500           # wait for JS redirects / popups
SHOT_QUALITY = 60

# Best-effort hidden-text finder for prompt-injection evidence. Text the user can't see but a
# model reading the DOM could: display:none, visibility:hidden, opacity 0, tiny font,
# off-screen, clipped to nothing, text colour == background colour, plus HTML comments.
HIDDEN_TEXT_JS = r"""
(maxChars) => {
  const out = []; let total = 0;
  const push = (reason, text) => {
    text = (text || '').replace(/\s+/g, ' ').trim();
    if (!text || total >= maxChars) return;
    text = text.slice(0, maxChars - total); total += text.length;
    out.push({reason, text});
  };
  const parseRGB = (c) => { const m = (c || '').match(/[\d.]+/g); return m ? m.map(Number) : null; };
  const bgOf = (el) => {
    for (let e = el; e; e = e.parentElement) {
      const c = parseRGB(getComputedStyle(e).backgroundColor);
      if (c && (c.length < 4 || c[3] > 0)) return c;
    }
    return [255, 255, 255];
  };
  const close = (a, b) => a && b && Math.abs(a[0]-b[0]) + Math.abs(a[1]-b[1]) + Math.abs(a[2]-b[2]) < 30;
  const reasonFor = (el) => {
    for (let e = el; e && e !== document.documentElement; e = e.parentElement) {
      const s = getComputedStyle(e);
      if (s.display === 'none') return 'display_none';
      if (parseFloat(s.opacity) === 0) return 'opacity_0';
    }
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.visibility === 'collapse') return 'visibility_hidden';
    if (parseFloat(s.fontSize) < 2) return 'tiny_font';
    const r = el.getBoundingClientRect();
    const W = Math.max(document.documentElement.scrollWidth, innerWidth);
    const H = Math.max(document.documentElement.scrollHeight, innerHeight);
    if (r.right < 0 || r.bottom < 0 || r.left > W || r.top > H) return 'off_screen';
    if ((r.width < 2 || r.height < 2) && (s.overflow === 'hidden' || s.clip !== 'auto' || s.clipPath !== 'none')) return 'clipped';
    if ((s.clipPath && s.clipPath.includes('inset(50%')) || s.clip === 'rect(0px, 0px, 0px, 0px)') return 'clipped';
    const fg = parseRGB(s.color);
    if (fg && fg.length >= 4 && fg[3] === 0) return 'transparent_text';
    if (close(fg, bgOf(el))) return 'same_color_as_background';
    return null;
  };
  const skip = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'SVG', 'HEAD', 'TITLE']);
  const walker = document.createTreeWalker(document.documentElement,
      NodeFilter.SHOW_TEXT | NodeFilter.SHOW_COMMENT);
  const seen = new Map(); const texts = new Set();
  const push1 = (reason, text) => { const k = (text || '').trim(); if (k && !texts.has(k)) { texts.add(k); push(reason, k); } };
  for (let n = walker.nextNode(); n && total < maxChars; n = walker.nextNode()) {
    if (n.nodeType === Node.COMMENT_NODE) { push1('html_comment', n.data); continue; }
    const el = n.parentElement;
    if (!el || skip.has(el.tagName.toUpperCase()) || !n.data.trim()) continue;
    if (!seen.has(el)) seen.set(el, reasonFor(el));
    const reason = seen.get(el);
    if (reason) push1(reason, n.data);
  }
  for (const m of document.querySelectorAll('meta[name=description], meta[name=keywords], [title]')) {
    const t = m.getAttribute('content') || m.getAttribute('title');
    if (t && t.length > 40) push1('attribute', t);
  }
  return out;
}
"""


def _now_ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def scan(url: str) -> dict:
    t0 = time.monotonic()
    out = {"url": url, "final_url": None, "domain": None, "redirect_chain": [],
           "status_codes": [], "page_title": None, "page_text": "", "hidden_text": "",
           "hidden_text_items": [], "form_fields": [], "downloads": [], "popups": [],
           "blocked_requests": [], "screenshots": [], "timings": {}, "error": None}
    guard = CachingGuard()

    ok, reason = guard.check(url)
    if not ok:
        out["error"] = f"blocked: {reason}"
        out["blocked_requests"].append({"url": url[:300], "reason": reason, "type": "document"})
        out["timings"]["total_ms"] = _now_ms(t0)
        return out

    counters = {"requests": 0, "nav": 0}

    def block(route, req_url: str, why: str, stay: bool = False) -> None:
        if len(out["blocked_requests"]) < MAX_BLOCKED:
            out["blocked_requests"].append({"url": req_url[:300], "reason": why,
                                            "type": route.request.resource_type})
        if stay:
            # A 204 to a navigation means "don't navigate": the browser stays on the page
            # that tried to redirect somewhere internal, so we keep its evidence instead of
            # ending up on chrome-error://.
            route.fulfill(status=204, body="")
        else:
            route.abort("blockedbyclient")

    def on_route(route) -> None:
        req = route.request
        counters["requests"] += 1
        if counters["requests"] > MAX_REQUESTS:
            return block(route, req.url, "request budget exceeded")
        if req.url.startswith(("data:", "blob:")):
            return route.continue_()      # in-memory, no network
        try:
            top_nav = req.is_navigation_request() and req.frame.parent_frame is None
        except Exception:                 # e.g. worker requests have no frame
            top_nav = False
        if top_nav:
            counters["nav"] += 1
            if counters["nav"] > MAX_HOPS:
                return block(route, req.url, "too many redirects", stay=True)
        allowed, why = guard.check(req.url)
        if not allowed:
            return block(route, req.url, why, stay=top_nav and counters["nav"] > 1)
        route.continue_()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            chromium_sandbox=os.environ.get("CHROMIUM_SANDBOX") == "1",
            executable_path=os.environ.get("CHROMIUM_PATH") or None,   # local testing only
            args=["--disable-dev-shm-usage", "--dns-prefetch-disable",
                  "--disable-background-networking", "--no-pings",
                  "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                  "--webrtc-ip-handling-policy=disable_non_proxied_udp"])
        context = browser.new_context(
            accept_downloads=False, java_script_enabled=True, service_workers="block",
            viewport={"width": 390, "height": 844}, device_scale_factor=1,  # phone-sized
            is_mobile=True, has_touch=True)
        context.route("**/*", on_route)   # context-wide: also covers popups and iframes
        try:
            context.route_web_socket("**/*", lambda ws: ws.close())
        except AttributeError:            # older Playwright: no WebSocket routing
            pass
        page = context.new_page()
        out["timings"]["browser_ready_ms"] = _now_ms(t0)

        def on_nav(frame) -> None:
            if frame == page.main_frame and frame.url != "about:blank":
                out["redirect_chain"].append(frame.url)

        def on_response(resp) -> None:
            req = resp.request
            if req.is_navigation_request() and req.frame == page.main_frame:
                hop = {"url": resp.url[:300], "status": resp.status}
                try:
                    addr = resp.server_addr()
                    if addr:
                        hop["ip"] = addr["ipAddress"]
                except Exception:
                    pass
                out["status_codes"].append(hop)

        page.on("framenavigated", on_nav)
        page.on("response", on_response)
        def on_download(d) -> None:      # record, never save or open
            out["downloads"].append((d.suggested_filename or "")[:200])
            try:
                d.cancel()
            except Exception:
                pass

        def on_popup(pg) -> None:        # record, then close; route() still guarded it
            out["popups"].append(pg.url[:300])
            try:
                pg.close()
            except Exception:
                pass

        page.on("download", on_download)
        page.on("popup", on_popup)

        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            out["timings"]["first_load_ms"] = _now_ms(t0)
            if resp:
                req, chain = resp.request, []
                while req:                       # HTTP redirects (301/302) before the page
                    chain.insert(0, req.url)
                    req = req.redirected_from
                out["redirect_chain"] = chain + [u for u in out["redirect_chain"] if u not in chain]
            page.wait_for_timeout(SETTLE_MS)
            out["timings"]["settled_ms"] = _now_ms(t0)
        except Exception as e:                   # timeouts, DNS failures, blocked requests
            out["error"] = str(e).splitlines()[0][:300]

        out["final_url"] = page.url
        out["domain"] = urlparse(page.url).hostname
        try:
            out["page_title"] = (page.title() or "")[:200]
            out["page_text"] = page.inner_text("body", timeout=3000)[:MAX_TEXT]
            out["form_fields"] = page.eval_on_selector_all(
                "input, select, textarea",
                f"""els => els.slice(0, {MAX_FIELDS}).map(e => ({{
                    type: (e.type || e.tagName.toLowerCase()).slice(0, 30),
                    name: (e.name || '').slice(0, {MAX_FIELD_STR}),
                    placeholder: (e.placeholder || '').slice(0, {MAX_FIELD_STR}),
                    autocomplete: (e.autocomplete || '').slice(0, 40),
                    label: ((e.labels && e.labels[0] && e.labels[0].innerText) || '')
                           .slice(0, {MAX_FIELD_STR}),
                    form_action: (e.form && e.form.getAttribute('action') || '').slice(0, 200)
                }}))""")
            items = page.evaluate(HIDDEN_TEXT_JS, MAX_HIDDEN)
            out["hidden_text_items"] = items
            out["hidden_text"] = " | ".join(f"[{i['reason']}] {i['text']}" for i in items)[:MAX_HIDDEN]
            shot = page.screenshot(full_page=False, type="jpeg", quality=SHOT_QUALITY,
                                   timeout=5000)
            out["screenshots"].append("data:image/jpeg;base64," + base64.b64encode(shot).decode())
        except Exception as e:
            out["error"] = out["error"] or str(e).splitlines()[0][:300]
        out["timings"]["collected_ms"] = _now_ms(t0)

        browser.close()
    # Any hop served from a non-public IP means a check was bypassed (e.g. DNS rebinding);
    # flag it so the backend never shows a favourable verdict for this scan.
    for hop in out["status_codes"]:
        if hop.get("ip") and not is_public_ip(hop["ip"]):
            out["error"] = f"blocked: page was served from non-public address {hop['ip']}"
    out["timings"]["total_ms"] = _now_ms(t0)
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: run_scan.py <url>"}))
        sys.exit(1)
    print(json.dumps(scan(sys.argv[1])))
