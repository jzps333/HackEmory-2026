"""form_fill / form_submit with Playwright (sync API), in a VISIBLE Chromium window.

The page stays open (keyed by the form_fill job id) for up to 10 minutes so a later
form_submit (sent only after the caller said "yes, submit") can finish it.
"""
from __future__ import annotations

import os
import re
import socket
import ipaddress
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

from . import fields

SESSION_TTL = 600.0       # keep a filled page open this long
FRAME_INTERVAL = 1 / 3    # ~3 frames per second
TAIL_SECONDS = 3.0        # keep streaming this long after filling / submitting
MAX_FRAME = 400_000

_CHROME_URL_CMD = ["osascript", "-e",
                   'tell application "Google Chrome" to get URL of active tab of front window']


class JobError(Exception):
    """A polite, short, personal-data-free failure code for the job result."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code[:200]


DEFAULT_SITES = ("api.scansafe.nyc",)    # our demo permit form


def approved_sites() -> set:
    """Sites the person approved ON THIS COMPUTER for filling: ~/.toolstone/allowed_sites
    (one hostname per line). The demo form's host is always allowed."""
    from . import config
    sites = set(DEFAULT_SITES)
    try:
        for line in (config.home() / "allowed_sites").read_text().splitlines():
            line = line.strip().lower()
            if line and not line.startswith("#"):
                sites.add(line)
    except OSError:
        pass
    return sites


def _private_host(host: str) -> bool:
    """Loopback, private, link-local or reserved address, or a name that resolves to one, or a
    single-label / .local name. TOOLSTONE_ALLOW_LOCAL=1 lifts this (tests, local dev only)."""
    if os.getenv("TOOLSTONE_ALLOW_LOCAL") == "1":
        return False
    host = (host or "").strip("[]").lower()
    if not host or "." not in host or host.endswith((".local", ".localhost", ".internal")) or host == "localhost":
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return True
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return True
    return False


def allowed_url(url: str) -> bool:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return False
    return (parts.scheme in ("http", "https") and bool(parts.hostname) and len(url) <= 2048
            and not parts.username and not parts.password)


def site_ok(url: str) -> tuple[bool, str]:
    """(ok, reason): an approved site on this computer and not a local/private address."""
    host = (urlsplit(url).hostname or "").lower()
    if os.getenv("TOOLSTONE_ALLOW_LOCAL") != "1" and host not in approved_sites():
        return False, "site_not_approved"
    if _private_host(host):
        return False, "private_address"
    return True, ""


def public_url(url: str) -> str:
    """The URL without query/fragment (those can carry tokens) for the result."""
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def active_chrome_url() -> str:
    """URL of the active Google Chrome tab (macOS only; the one fixed osascript command)."""
    if sys.platform != "darwin":
        raise JobError("no_url:active_tab_needs_macos")
    try:
        out = subprocess.run(_CHROME_URL_CMD, capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.SubprocessError):
        raise JobError("no_url:chrome_not_reachable") from None
    url = (out.stdout or "").strip()
    if out.returncode != 0 or not url:
        raise JobError("no_url:no_chrome_tab")
    return url


_COLLECT_JS = r"""
() => {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim().slice(0, 160);
  const labelText = (el) => {
    let parts = [];
    if (el.labels && el.labels.length) {
      for (const l of el.labels) {
        const c = l.cloneNode(true);
        c.querySelectorAll('input,select,textarea,option').forEach(n => n.remove());
        parts.push(c.textContent);
      }
    }
    const by = el.getAttribute('aria-labelledby');
    if (!parts.length && by) {
      for (const id of by.split(/\s+/)) {
        const n = document.getElementById(id); if (n) parts.push(n.textContent);
      }
    }
    return clean(parts.join(' '));
  };
  const out = [];
  document.querySelectorAll('input, select, textarea').forEach((el, i) => {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    const type = (el.getAttribute('type') || '').toLowerCase();
    const visible = r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
    if (!visible) return;
    if (el.disabled || el.readOnly) return;
    el.setAttribute('data-toolstone-idx', String(i));
    out.push({
      idx: i, tag: el.tagName.toLowerCase(), type,
      name: el.getAttribute('name') || '', id: el.id || '',
      autocomplete: el.getAttribute('autocomplete') || '',
      label: labelText(el), aria_label: el.getAttribute('aria-label') || '',
      placeholder: el.getAttribute('placeholder') || '',
      options: el.tagName === 'SELECT'
        ? Array.from(el.options).slice(0, 200).map(o => ({value: o.value, label: clean(o.label || o.text)}))
        : [],
      form: el.form ? Array.from(document.forms).indexOf(el.form) : -1,
    });
  });
  return out;
}
"""

_SUBMIT_JS = r"""
(formIndex) => {
  const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const textOf = (el) => (el.innerText || el.value || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
  document.querySelectorAll('[data-toolstone-submit]').forEach(n => n.removeAttribute('data-toolstone-submit'));
  const roots = [];
  if (formIndex >= 0 && document.forms[formIndex]) roots.push(document.forms[formIndex]);
  roots.push(document);
  for (const root of roots) {
    const typed = Array.from(root.querySelectorAll('button[type=submit], input[type=submit]')).filter(visible);
    const implicit = root === document ? [] :
      Array.from(root.querySelectorAll('button:not([type])')).filter(visible);
    const worded = Array.from(root.querySelectorAll('button, input[type=button], [role=button]'))
      .filter(visible).filter(b => /^(submit( .*)?|apply( now)?|send( application| form)?)$/i.test(textOf(b)));
    const pick = typed[0] || implicit[0] || worded[0];
    if (pick) { pick.setAttribute('data-toolstone-submit', '1'); return true; }
  }
  return false;
}
"""

_CHECKBOXES_JS = r"""
() => {
  const out = [];
  document.querySelectorAll('input[type=checkbox]').forEach((el, i) => {
    if (el.disabled || el.checked) return;
    let t = '';
    if (el.labels && el.labels.length) t = Array.from(el.labels).map(l => l.textContent).join(' ');
    t = (t || el.getAttribute('aria-label') || el.name || el.id || '').replace(/\s+/g, ' ').trim();
    el.setAttribute('data-toolstone-cb', String(i));
    out.push({idx: i, label: t.slice(0, 200)});
  });
  return out;
}
"""


class FormSession:
    def __init__(self, page: Any, url: str, form_index: int, profile: Dict[str, str]):
        self.page = page
        self.url = url
        self.form_index = form_index
        self.profile = profile        # only to scrub the person's info out of result text
        self.created = time.monotonic()
        self.submitted = False


class Frames:
    """Rate-limited JPEG screenshots to the reporter (~3/s)."""

    def __init__(self, page: Any, reporter: Any):
        self.page = page
        self.reporter = reporter
        self.last = 0.0
        self.mask: list = []        # filled fields: blacked out, so saved info never leaves the computer

    def shot(self) -> None:
        self.last = time.monotonic()   # also on failure (mid-navigation), so no busy loop
        try:
            jpeg = self.page.screenshot(type="jpeg", quality=60, timeout=5000, mask=self.mask,
                                        mask_color="#1f2a44")
            if len(jpeg) > MAX_FRAME:
                jpeg = self.page.screenshot(type="jpeg", quality=30, timeout=5000, mask=self.mask,
                                            mask_color="#1f2a44")
        except Exception:
            return
        if len(jpeg) <= MAX_FRAME:
            self.reporter.frame(jpeg)

    def tick(self) -> None:
        if time.monotonic() - self.last >= FRAME_INTERVAL:
            self.shot()

    def stream_for(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.shot()
            wait = FRAME_INTERVAL - (time.monotonic() - self.last)
            if wait > 0:
                try:
                    self.page.wait_for_timeout(int(wait * 1000))
                except Exception:
                    time.sleep(wait)


class FormRunner:
    """Owns the Playwright browser and the open pages. Single-threaded (the run loop)."""

    def __init__(self, headless: Optional[bool] = None):
        if headless is None:
            headless = os.environ.get("TOOLSTONE_HEADLESS", "").strip() in ("1", "true", "yes")
        self.headless = headless
        self.fill_delay = float(os.environ.get("TOOLSTONE_FILL_DELAY", "0.25"))
        self._pw = None
        self._browser = None
        self.sessions: Dict[str, FormSession] = {}

    # -- browser lifecycle ----------------------------------------------------------------
    def _ensure_browser(self) -> Any:
        if self._browser is not None and self._browser.is_connected():
            return self._browser
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise JobError("playwright_missing: pip install playwright==1.55.0 && "
                           "python3 -m playwright install chromium") from None
        if self._pw is None:
            self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(headless=self.headless)
        except Exception as e:
            msg = str(e)
            if "Executable doesn't exist" in msg or "playwright install" in msg:
                raise JobError("chromium_missing: python3 -m playwright install chromium") from None
            raise JobError(f"browser_launch_failed:{type(e).__name__}") from None
        return self._browser

    def expire(self, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        for job_id in [j for j, s in self.sessions.items() if now - s.created > SESSION_TTL]:
            s = self.sessions.pop(job_id)
            try:
                s.page.context.close()
            except Exception:
                pass
        if not self.sessions and self._browser is not None:
            self.close()

    def close(self) -> None:
        for s in self.sessions.values():
            try:
                s.page.context.close()
            except Exception:
                pass
        self.sessions.clear()
        try:
            if self._browser is not None:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:
            pass
        self._browser = None
        self._pw = None

    # -- jobs -----------------------------------------------------------------------------
    def fill(self, job_id: str, args: dict, profile: Dict[str, str], reporter: Any) -> dict:
        url = str(args.get("url") or "").strip()
        if not url:
            url = active_chrome_url()
        if not allowed_url(url):
            raise JobError("bad_url:only_http_https")
        ok, why = site_ok(url)
        if not ok:   # approve a site by adding its hostname to ~/.toolstone/allowed_sites
            raise JobError(why)
        browser = self._ensure_browser()
        reporter.progress("Opening the form in a browser window on your computer")
        context = browser.new_context(viewport={"width": 1200, "height": 800})
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            try:
                context.close()
            except Exception:
                pass
            m = re.search(r"net::ERR_[A-Z_]+", str(e))
            raise JobError("page_load_failed" + (f":{m.group(0)}" if m else "")) from None
        try:
            page.wait_for_load_state("networkidle", timeout=4000)
        except Exception:
            pass
        if not site_ok(page.url)[0]:      # a redirect left the approved site: stop before filling
            try:
                context.close()
            except Exception:
                pass
            raise JobError("site_not_approved")
        frames = Frames(page, reporter)
        frames.shot()

        descs = page.evaluate(_COLLECT_JS) or []
        plan = fields.plan_fill(descs, profile)
        reporter.progress(f"Found {len(descs)} fields; filling {len(plan['fill'])} from your saved info")

        filled: List[dict] = []
        missing = list(plan["missing"])
        form_votes: Dict[int, int] = {}
        for desc, key in plan["fill"]:
            loc = page.locator(f'[data-toolstone-idx="{int(desc["idx"])}"]')
            value = profile[key]
            try:
                if desc.get("tag") == "select":
                    opt = fields.choose_option(key, value, desc.get("options") or [])
                    if opt is None:
                        missing.append(fields.label_of(desc))
                        continue
                    loc.select_option(value=opt, timeout=3000)
                else:
                    loc.fill(value, timeout=3000)
            except Exception:
                missing.append(fields.label_of(desc))
                continue
            filled.append({"label": fields.label_of(desc), "key": key})
            frames.mask.append(loc)                 # screenshots black this field out from now on
            form_votes[int(desc.get("form", -1))] = form_votes.get(int(desc.get("form", -1)), 0) + 1
            if self.fill_delay > 0:
                try:
                    page.wait_for_timeout(int(self.fill_delay * 1000))
                except Exception:
                    pass
            frames.tick()

        form_index = max(form_votes, key=form_votes.get) if form_votes else -1
        try:
            submit_found = bool(page.evaluate(_SUBMIT_JS, form_index))
        except Exception:
            submit_found = False
        reporter.progress(f"Filled {len(filled)} fields. Nothing submitted; waiting for your go-ahead")
        frames.stream_for(TAIL_SECONDS)

        self.sessions[job_id] = FormSession(page, url, form_index, profile)
        try:
            title = page.title()
        except Exception:
            title = ""
        return {"url": public_url(page.url if allowed_url(page.url) else url),
                "title": fields.scrub(title, profile)[:200],
                "filled": filled, "missing": missing, "skipped": plan["skipped"],
                "submit_found": submit_found}

    def submit(self, args: dict, reporter: Any) -> dict:
        fill_job = str(args.get("fill_job") or "")
        s = self.sessions.get(fill_job)
        if s is None:
            raise JobError("form_not_open")
        if s.submitted:
            raise JobError("already_submitted")
        page = s.page
        if page.is_closed():
            self.sessions.pop(fill_job, None)
            raise JobError("form_closed")
        frames = Frames(page, reporter)
        try:
            before = page.inner_text("body", timeout=3000)
        except Exception:
            before = ""
        ticked = 0
        try:
            for cb in page.evaluate(_CHECKBOXES_JS) or []:
                if fields.should_tick(cb.get("label") or ""):
                    page.locator(f'[data-toolstone-cb="{int(cb["idx"])}"]').check(timeout=3000)
                    ticked += 1
        except Exception:
            pass
        if not page.evaluate(_SUBMIT_JS, s.form_index):
            raise JobError("no_submit_button")
        reporter.progress("Submitting the form" + (" (ticked the certify box)" if ticked else ""))
        frames.shot()
        try:
            page.locator('[data-toolstone-submit="1"]').first.click(timeout=5000)
        except Exception:
            raise JobError("submit_click_failed") from None
        s.submitted = True
        try:   # confirmations usually appear next to the button: keep it in the video frame
            page.evaluate("() => { const b = document.querySelector('[data-toolstone-submit]');"
                          " if (b) b.scrollIntoView({block: 'center'}); }")
        except Exception:
            pass
        frames.stream_for(TAIL_SECONDS)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
            after = page.inner_text("body", timeout=3000)
        except Exception:
            after = ""
        message = fields.scrub(fields.text_change(before, after, 400), s.profile)[:200]
        return {"submitted": True, "message": message}
