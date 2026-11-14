"""Operator mode: pure rules (no Playwright here), used by server.py and run_scan.py --operate.

Operator mode is NOT scam scanning. It drives one known page, the (made-up) official Dogwood
Parking app on our own demo site, for a person who linked their Dogwood account in ScanSafe:

    install page -> tap Install -> tap Open -> app page -> type the plate -> tap hours-N
    -> tap "Pay with linked ScanSafe account" -> watch until the receipt shows (or 120 s)

It is tightly fenced, separately from scanning (scanning still never types anything):
  - Only https://scansafe-demo-sites.vercel.app/dogwood/... is accepted (exact host, no port,
    no credentials, no dot segments). server.py refuses anything else with 400, and the
    container checks it again.
  - Inside the browser, top-level pages must stay on that host under /dogwood/; other requests
    may only go to that host (its scripts) or the ScanSafe API host the app polls. The usual
    network guard (public addresses only) still runs on every request.
  - It only clicks fixed data-testid selectors on that page and only types the plate, which is
    checked here first (letters, digits, space, dash; at most 10).
  - "Pay with linked ScanSafe account" on that page never pays: the person approves the payment
    in the ScanSafe app. This mode can't move money.
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

OPERATE_HOST = "scansafe-demo-sites.vercel.app"
OPERATE_PATH_PREFIX = "/dogwood/"
INSTALL_PATH = "/dogwood/install"
APP_PATH = "/dogwood/app"
# Hosts the app page may fetch besides its own: the ScanSafe API (app-state polling).
OPERATE_API_HOSTS = frozenset({"api.scansafe.nyc"})
MAX_URL_LEN = 2048
MIN_HOURS, MAX_HOURS = 1, 4
PLATE_RE = re.compile(r"^[A-Z0-9][A-Z0-9 -]{0,9}$")

# Fixed selectors on the Dogwood pages (websites/dogwood/ in the demo-site repo).
SEL = {
    "install": '[data-testid="install"]',
    "open": '[data-testid="open"]',
    "plate": '[data-testid="plate"]',
    "pay": '[data-testid="pay"]',
    "waiting": '[data-testid="waiting"]',
    "change": '[data-testid="change"]',      # "Change hours" on the waiting screen
    "receipt": '[data-testid="receipt"]',
    "no_session": '[data-testid="no-session"]',
}


def hours_selector(hours: int) -> str:
    return f'[data-testid="hours-{int(hours)}"]'


def _dogwood_path(path: str) -> bool:
    if not path.startswith(OPERATE_PATH_PREFIX):
        return False
    # No dot segments or encoded tricks: /dogwood/../websites, /dogwood/%2e%2e/, //, backslash.
    raw = unquote(unquote(path))
    if "\\" in raw or "//" in raw or "\x00" in raw:
        return False
    return not any(seg in (".", "..") for seg in raw.split("/"))


def operate_url_allowed(url: object) -> tuple[bool, str]:
    """Is ``url`` a page operator mode may open? Exactly https://scansafe-demo-sites.vercel.app
    with a path under /dogwood/. Everything else: (False, reason)."""
    if not isinstance(url, str) or not url or len(url) > MAX_URL_LEN:
        return False, "url missing or too long"
    if any(c.isspace() or ord(c) < 32 for c in url):
        return False, "url has spaces or control characters"
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False, "malformed url"
    if parts.scheme != "https":
        return False, "only https"
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        return False, "credentials in url"
    if port is not None or parts.netloc.lower() != OPERATE_HOST:
        return False, f"host must be exactly {OPERATE_HOST}"
    if not _dogwood_path(parts.path):
        return False, f"path must start with {OPERATE_PATH_PREFIX}"
    return True, "ok"


def operate_request_allowed(url: str, top_nav: bool) -> tuple[bool, str]:
    """Inside the operate browser, before the network guard: top-level pages stay on the Dogwood
    pages; other requests only reach the demo site itself or the ScanSafe API."""
    if url.startswith(("data:", "blob:")):
        return True, "in-memory"
    if top_nav:
        return operate_url_allowed(url)
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False, "malformed url"
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or port is not None or parts.username or parts.password:
        return False, "only plain https"
    if host == OPERATE_HOST or host in OPERATE_API_HOSTS:
        return True, "ok"
    return False, f"operator mode does not load {host or 'that'}"


def clean_plate(plate: object) -> str | None:
    """'ga 4821k ' -> 'GA 4821K'. None unless it's 1-10 letters/digits/spaces/dashes."""
    if not isinstance(plate, str):
        return None
    p = re.sub(r"\s+", " ", plate).strip().upper()
    return p if PLATE_RE.fullmatch(p) else None


def valid_hours(hours: object) -> int | None:
    if isinstance(hours, bool) or not isinstance(hours, int):
        return None
    return hours if MIN_HOURS <= hours <= MAX_HOURS else None


def check_operate_request(url: object, plate: object, hours: object) -> tuple[bool, str]:
    """server.py: the whole /operate request, before any container starts."""
    ok, why = operate_url_allowed(url)
    if not ok:
        return False, f"url not allowed: {why}"
    if clean_plate(plate) is None:
        return False, "plate must be 1 to 10 letters, digits, spaces or dashes"
    if valid_hours(hours) is None:
        return False, f"hours must be a whole number from {MIN_HOURS} to {MAX_HOURS}"
    return True, "ok"


# --- step logic ----------------------------------------------------------------------------------

STEPS_FROM_INSTALL = ("open", "install", "open_app", "plate", "hours", "pay", "wait")
STEPS_FROM_APP = ("open", "plate", "hours", "pay", "wait")


def plan_steps(url: str) -> tuple[str, ...]:
    """Which steps a run takes, from where it starts: the install page or the app itself."""
    path = urlsplit(url).path.rstrip("/")
    if path == INSTALL_PATH:
        return STEPS_FROM_INSTALL
    if path == APP_PATH:
        return STEPS_FROM_APP
    return ()


def step_text(step: str, plate: str = "", hours: int = 0) -> str:
    """The short line streamed for each step ({"type": "step", "text": ...})."""
    h = f"{hours} hour" if hours == 1 else f"{hours} hours"
    return {
        "open": "Opening Dogwood Parking",
        "install": "Tapping Install",
        "open_app": "Opening the app",
        "plate": f"Typing your plate {plate}".rstrip(),
        "hours": f"Choosing {h}",
        "pay": "Tapping Pay with linked ScanSafe account",
        "wait": "Waiting for your approval in ScanSafe",
        "paid": "Paid. Receipt on screen",
    }.get(step, step)


# DOM facts for page_phase(): which Dogwood test ids are visible right now.
PHASE_JS = r"""
() => {
  const ids = ['install', 'installing', 'open', 'plate', 'pay', 'waiting', 'receipt', 'no-session'];
  const out = {};
  for (const id of ids) {
    const el = document.querySelector(`[data-testid="${id}"]`);
    out[id.replace('-', '_')] = !!el && !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  }
  return out;
}
"""


def page_phase(flags: object) -> str:
    """Where the Dogwood page is, from PHASE_JS facts: paid / waiting / no_session / app /
    ready_to_open / installing / install / unknown. The receipt wins over everything."""
    if not isinstance(flags, dict):
        return "unknown"
    f = {k: bool(v) for k, v in flags.items()}
    if f.get("receipt"):
        return "paid"
    if f.get("no_session"):
        return "no_session"
    if f.get("waiting"):
        return "waiting"
    if f.get("plate") or f.get("pay"):
        return "app"
    if f.get("open"):
        return "ready_to_open"
    if f.get("installing"):
        return "installing"
    if f.get("install"):
        return "install"
    return "unknown"


def operate_status(done_steps: list[str], phase: str, error: str | None) -> str:
    """Final status for the result: paid / waiting (Pay tapped, not approved before the time
    ran out) / failed."""
    if phase == "paid":
        return "paid"
    if error:
        return "failed"
    return "waiting" if "pay" in done_steps else "failed"
