"""Runs INSIDE a throwaway Docker container. Opens one URL, records what happened, prints JSON.

Usage (inside the container): python run_scan.py <url>
No keys, no logins, no personal data live here. Downloads are blocked, never opened.
"""
from __future__ import annotations

import base64
import json
import sys
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

MAX_TEXT = 4000
TIMEOUT_MS = 20000


def scan(url: str) -> dict:
    out = {"url": url, "final_url": None, "domain": None, "redirect_chain": [], "page_title": None,
           "page_text": "", "form_fields": [], "downloads": [], "screenshots": [], "error": None}
    if not url.startswith(("http://", "https://")):
        out["error"] = "not a web link"
        return out

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(accept_downloads=False, java_script_enabled=True,
                                      viewport={"width": 390, "height": 844})  # phone-sized
        page = context.new_page()

        # Record every main-frame navigation (the redirect chain) and any download attempt.
        page.on("framenavigated",
                lambda f: f == page.main_frame and out["redirect_chain"].append(f.url))
        page.on("download", lambda d: out["downloads"].append(d.suggested_filename))

        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            if resp:
                req = resp.request
                chain = []
                while req:                       # HTTP redirects (301/302) before the page
                    chain.insert(0, req.url)
                    req = req.redirected_from
                out["redirect_chain"] = chain + [u for u in out["redirect_chain"] if u not in chain]
            page.wait_for_timeout(2500)          # let JavaScript redirects / popups happen
        except Exception as e:                   # timeouts, DNS failures, blocked downloads
            out["error"] = str(e)[:300]

        out["final_url"] = page.url
        out["domain"] = urlparse(page.url).hostname
        try:
            out["page_title"] = page.title()
            out["page_text"] = page.inner_text("body")[:MAX_TEXT]
            out["form_fields"] = page.eval_on_selector_all(
                "input, select, textarea",
                "els => els.slice(0, 40).map(e => ({type: e.type || e.tagName.toLowerCase(), "
                "name: e.name || '', placeholder: e.placeholder || ''}))")
            shot = page.screenshot(full_page=False)
            out["screenshots"].append("data:image/png;base64," + base64.b64encode(shot).decode())
        except Exception as e:
            out["error"] = out["error"] or str(e)[:300]

        browser.close()
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: run_scan.py <url>"}))
        sys.exit(1)
    print(json.dumps(scan(sys.argv[1])))
