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

import json
import re
from urllib.parse import parse_qs, unquote, urlsplit

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


# === ParkMobile (adapter "parkmobile"): the REAL official web app, stops before payment =========
#
# A second operator-mode adapter for https://app.parkmobile.io, ParkMobile's own web app. Unlike
# Dogwood it is a real payments site, so it is fenced harder and NEVER reaches payment:
#   - Entry host is exactly app.parkmobile.io (https, no port, no credentials, no dot segments);
#     top-level pages must stay on that host. Other requests only reach *.parkmobile.io and the
#     static/CDN hosts its pages actually load (fonts, images, map tiles, feature flags, and the
#     invisible reCAPTCHA script, which is never touched). Analytics, ads, cookie banners and
#     Google sign-in are blocked. The usual network guard still runs on every request.
#   - The runner only types the checked zone number and the checked plate, and only into fields
#     that don't look like card / password / email / phone / address fields (pm_type_refused).
#   - It refuses to click anything labelled like pay / purchase / checkout / buy / confirm /
#     start parking / submit order / agree / sign in (pm_click_refused).
#   - It stops as soon as a sign-in, contact-details (email), verification-code, payment-method,
#     review/price or robot-check screen shows, or the only way on is a pay-like button (refused),
#     and reports what it saw. Nothing is ever paid; it never signs in or types an email or code.
#   - Optional: a saved, signed-in session of the person's own account (see "saved session"
#     below) so the run gets past the guest "Add email" screen to the price.
# What the real guest flow looked like on 2026-11-14 (390x844 phone, see run_scan.py):
#   /v2/parking (search box) -> zone result -> /v2/parking/zone-details?areaNo=... ("Park here")
#   -> /v2/parking/guest-registration ("Add email" + Terms checkbox). Duration, plate and price
#   come only after that screen, so a guest run stops there with status "needs_sign_in".

PM_HOST = "app.parkmobile.io"
PM_ENTRY_URL = "https://app.parkmobile.io/v2/parking"
PM_ENTRY_PREFIXES = ("/v2/parking", "/zone", "/search")
PM_ZONE_DETAILS_PATH = "/v2/parking/zone-details"
# Third-party hosts the ParkMobile pages need to render (seen in a real run); all else is blocked.
PM_STATIC_HOSTS = frozenset({
    "fonts.googleapis.com", "fonts.gstatic.com", "use.typekit.net", "p.typekit.net",
    "res.cloudinary.com", "api.mapbox.com", "maps.googleapis.com", "maps.gstatic.com",
    "app.launchdarkly.com", "clientstream.launchdarkly.com",
})
# reCAPTCHA Enterprise (invisible, score-only) script and frame: allowed so the app's own API calls
# work; never clicked or solved. A VISIBLE challenge stops the run with status "robot_check".
PM_RECAPTCHA_HOSTS = frozenset({"www.google.com", "www.gstatic.com", "www.recaptcha.net"})
PM_STATUSES = ("ready_to_pay", "needs_sign_in", "needs_verification", "robot_check", "failed")
PM_MIN_MINUTES, PM_MAX_MINUTES = 15, 720
ZONE_RE = re.compile(r"^\d{3,7}$")
AREA_RE = re.compile(r"^\d{3,12}$")

PM_SEL = {
    "search": '[data-testid="search-input"]:visible',
    "continue": 'button[data-testid="zone-details-continue-button"]:visible',
    "email": '[data-testid="guest-registration-email-input"]',
}


def pm_result_selector(zone: str) -> str:
    return f'[data-testid="search-result-{zone}"]:visible'


def _plain_https(parts) -> bool:
    try:
        port = parts.port
    except ValueError:
        return False
    return (parts.scheme == "https" and port is None and parts.username is None
            and parts.password is None and "@" not in parts.netloc)


def _clean_path(path: str) -> bool:
    raw = unquote(unquote(path))
    if "\\" in raw or "//" in raw or "\x00" in raw:
        return False
    return not any(seg in (".", "..") for seg in raw.split("/"))


def parkmobile_url_allowed(url: object, entry: bool = True) -> tuple[bool, str]:
    """Exactly https://app.parkmobile.io. ``entry``: the first page must also be under /v2/parking,
    /zone or /search (pages inside the flow may be any path on that host)."""
    if not isinstance(url, str) or not url or len(url) > MAX_URL_LEN:
        return False, "url missing or too long"
    if any(c.isspace() or ord(c) < 32 for c in url):
        return False, "url has spaces or control characters"
    try:
        parts = urlsplit(url)
    except ValueError:
        return False, "malformed url"
    if not _plain_https(parts):
        return False, "only plain https"
    if parts.netloc.lower() != PM_HOST:
        return False, f"host must be exactly {PM_HOST}"
    if not _clean_path(parts.path or "/"):
        return False, "bad path"
    if entry and not any(parts.path == p or parts.path.startswith(p + "/") or parts.path.startswith(p + "?")
                         for p in PM_ENTRY_PREFIXES):
        return False, "path must start with " + ", ".join(PM_ENTRY_PREFIXES)
    return True, "ok"


def parkmobile_request_allowed(url: str, top_nav: bool) -> tuple[bool, str]:
    """Inside the ParkMobile browser, before the network guard."""
    if url.startswith(("data:", "blob:")):
        return True, "in-memory"
    if top_nav:
        return parkmobile_url_allowed(url, entry=False)
    try:
        parts = urlsplit(url)
    except ValueError:
        return False, "malformed url"
    if not _plain_https(parts):
        return False, "only plain https"
    host = (parts.hostname or "").lower()
    if host == "parkmobile.io" or host.endswith(".parkmobile.io") or host in PM_STATIC_HOSTS:
        return True, "ok"
    if host in PM_RECAPTCHA_HOSTS and parts.path.startswith("/recaptcha/"):
        return True, "ok"
    return False, f"parkmobile mode does not load {host or 'that'}"


def clean_zone(zone: object) -> str | None:
    """'91987' / 91987 / ' 919 87 ' -> '91987'. None unless 3-7 digits."""
    if isinstance(zone, bool):
        return None
    if isinstance(zone, int):
        zone = str(zone)
    if not isinstance(zone, str):
        return None
    z = re.sub(r"\s+", "", zone)
    return z if ZONE_RE.fullmatch(z) else None


def pm_area_from_url(url: object) -> str | None:
    """areaNo from https://app.parkmobile.io/v2/parking/zone-details?areaNo=10891987, else None."""
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.path.rstrip("/") != PM_ZONE_DETAILS_PATH:
        return None
    area = parse_qs(parts.query).get("areaNo", [""])[0]
    return area if AREA_RE.fullmatch(area) else None


def pm_minutes(hours: object = None, minutes: object = None) -> int | None:
    """Duration in minutes from whole hours or minutes; None unless 15..720."""
    for v, mult in ((minutes, 1), (hours, 60)):
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, int):
            return None
        m = v * mult
        return m if PM_MIN_MINUTES <= m <= PM_MAX_MINUTES else None
    return None


def check_parkmobile_request(url: object, zone: object, plate: object,
                             hours: object = None, minutes: object = None) -> tuple[bool, str]:
    """server.py: a whole ParkMobile request, before any container starts. A zone (3-7 digits) is
    needed unless the url is a zone-details page (?areaNo=...)."""
    ok, why = parkmobile_url_allowed(url)
    if not ok:
        return False, f"url not allowed: {why}"
    if zone not in (None, "", "-") and clean_zone(zone) is None:
        return False, "zone must be 3 to 7 digits"
    if clean_zone(zone) is None and pm_area_from_url(url) is None:
        return False, "a zone number (3 to 7 digits) or a zone-details url is needed"
    if clean_plate(plate) is None:
        return False, "plate must be 1 to 10 letters, digits, spaces or dashes"
    if pm_minutes(hours, minutes) is None:
        return False, f"duration must be {PM_MIN_MINUTES} to {PM_MAX_MINUTES} minutes"
    return True, "ok"


# --- hard guards for the click and type helpers (run_scan.py calls these before EVERY action) ---

PM_CLICK_REFUSED = re.compile(
    r"\b(pay|paying|payment|paypal|purchase|checkout|check[\s-]?out|buy|order|confirm|"
    r"start[\s-]?(parking|session)|park[\s-]?now|place order|submit|agree|accept|card|wallet|"
    r"sign[\s-]?(in|up)|log[\s-]?in|register|create account|subscribe|download)\b"
    r"|apple\s?pay|google\s?pay|g\s?pay", re.I)
PM_TYPE_REFUSED = re.compile(
    r"card|\bcc|cvv|cvc|\bcsc\b|security code|expir|\bexp\b|password|passcode|\bpin\b|e-?mail"
    r"|\btel|phone|mobile|\bsms\b|otp|one[\s-]?time|verification|\bzip|postal|billing|street"
    r"|first[\s_-]?name|last[\s_-]?name|full[\s_-]?name|given|family|account|routing|iban|ssn"
    r"|social security|birth|\bdob\b", re.I)
PM_TYPE_REFUSED_TYPES = frozenset({"password", "email", "tel", "hidden", "file"})


def pm_click_refused(label: object) -> bool:
    """True for anything that could pay, accept terms, sign in or submit: never clicked."""
    text = re.sub(r"\s+", " ", str(label or "")).strip()
    return bool(PM_CLICK_REFUSED.search(text))


def pm_type_refused(attrs: object) -> bool:
    """True unless the field is clearly not a card / password / email / phone / personal field.
    ``attrs``: {"type","name","id","autocomplete","aria","placeholder","label","testid"}."""
    if not isinstance(attrs, dict):
        return True
    if str(attrs.get("type") or "").lower() in PM_TYPE_REFUSED_TYPES:
        return True
    ac = str(attrs.get("autocomplete") or "").lower()
    if ac.startswith("cc-") or ac in ("email", "tel", "username", "current-password", "new-password",
                                     "one-time-code", "name", "given-name", "family-name",
                                     "street-address", "postal-code", "bday"):
        return True
    blob = " ".join(str(attrs.get(k) or "") for k in
                    ("type", "name", "id", "aria", "placeholder", "label", "testid"))
    return bool(PM_TYPE_REFUSED.search(blob))


def pm_type_value_ok(value: object, zone: str | None, plate: str | None) -> bool:
    """Only the checked zone number or the checked plate is ever typed."""
    return isinstance(value, str) and bool(value) and value in {v for v in (zone, plate) if v}


# --- screens -----------------------------------------------------------------------------------

PM_PRICE_RE = re.compile(r"\$\s?\d{1,4}(?:[.,]\d{2})?")
PM_PAYMENT_TEXT = re.compile(r"payment method|add (a )?(credit |debit )?card|card number|apple pay"
                             r"|google pay|paypal|billing", re.I)
# Informational, not a payment step: the signed-in zone screen lists "Accepted payment methods"
# (card brand logos). Removed from the page text before any payment / saved-card check.
PM_INFO_TEXT = re.compile(r"accepted payment methods?|payment methods? accepted", re.I)


def pm_scrub(text: object) -> str:
    return PM_INFO_TEXT.sub(" ", str(text or ""))


PM_REVIEW_TEXT = re.compile(r"\b(total|subtotal|review|summary|parking fee|transaction fee"
                            r"|service fee|convenience fee|parking cost)\b", re.I)
PM_AUTH_PATH = re.compile(r"guest-registration|login|log-in|signin|sign-in|signup|sign-up|register"
                          r"|/auth|/account|verify", re.I)

# Facts for pm_screen(). "top" = really on screen: in the viewport and the topmost element at its
# center (ParkMobile keeps closed sheets in the DOM, so plain visibility checks lie).
PM_FACTS_JS = r"""
() => {
  const top = el => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || r.bottom <= 0 || r.top >= innerHeight || r.right <= 0 || r.left >= innerWidth) return false;
    const x = Math.min(Math.max(r.left + r.width / 2, 1), innerWidth - 2);
    const y = Math.min(Math.max(r.top + r.height / 2, 1), innerHeight - 2);
    const hit = document.elementFromPoint(x, y);
    return !!hit && (hit === el || el.contains(hit) || hit.contains(el) || hit.tagName === 'LABEL');
  };
  const q = s => [...document.querySelectorAll(s)];
  const any = s => q(s).some(top);
  const inputs = q('input, textarea, select').filter(top).slice(0, 30).map(e => ({
    type: (e.getAttribute('type') || '').toLowerCase(), name: e.getAttribute('name') || '',
    id: e.id || '', autocomplete: (e.getAttribute('autocomplete') || '').toLowerCase(),
    aria: e.getAttribute('aria-label') || '', placeholder: e.getAttribute('placeholder') || '',
    testid: e.getAttribute('data-testid') || '',
    label: ((e.labels && e.labels[0] && e.labels[0].innerText) || '').slice(0, 60)}));
  const payFrames = q('iframe').filter(f => /stripe|braintree|adyen|paypal|cardinal|spreedly|checkout|payment/i.test(f.src || '')).length;
  const text = (document.body ? document.body.innerText : '').replace(/[ \t]+/g, ' ');
  return {path: location.pathname, title: document.title.slice(0, 120), text: text.slice(0, 3000),
          lines: text.split('\n').map(s => s.trim()).filter(Boolean).slice(0, 80).map(s => s.slice(0, 120)),
          inputs, pay_frames: payFrames,
          search: any('[data-testid="search-input"]'),
          zone_details: any('[data-testid="zone-details-continue-button"]'),
          unsupported: any('[data-testid="location-unsupported-overlay-download-button"]'),
          space_number: any('[data-testid="space-number-input"]'),
          error_sheet: any('[data-testid="error-overlay-close-button"]')};
}
"""

PLATE_FIELD = re.compile(r"plate|licen[cs]e|vehicle|\blpn\b", re.I)
DURATION_TEXT = re.compile(r"\b(duration|how long|select (a )?time|parking time|hours?|minutes?)\b", re.I)


def _field_blob(f: dict) -> str:
    return " ".join(str(f.get(k) or "") for k in ("name", "id", "aria", "placeholder", "label", "testid"))


def pm_has_card_fields(facts: object) -> bool:
    """A card form is on screen (card-like inputs or a payment provider's frame)."""
    if not isinstance(facts, dict):
        return False
    inputs = [f for f in facts.get("inputs") or [] if isinstance(f, dict)]
    return (int(facts.get("pay_frames") or 0) > 0
            or any(str(f.get("autocomplete", "")).startswith("cc-")
                   or re.search(r"card|cvv|cvc|expir", _field_blob(f), re.I) for f in inputs))


def pm_screen(facts: object, robot: bool = False) -> str:
    """Where the ParkMobile page is: robot_check / payment / review / verification / sign_in /
    unsupported / space_number / plate / zone_details / duration / search / unknown."""
    if robot:
        return "robot_check"
    if not isinstance(facts, dict):
        return "unknown"
    inputs = [f for f in facts.get("inputs") or [] if isinstance(f, dict)]
    text = pm_scrub(facts.get("text"))
    has_price = bool(PM_PRICE_RE.search(text))
    if pm_has_card_fields(facts) or PM_PAYMENT_TEXT.search(text):
        return "payment"
    if has_price and PM_REVIEW_TEXT.search(text):
        return "review"
    path = str(facts.get("path") or "")
    otp = any(str(f.get("autocomplete") or "") == "one-time-code" or _OTP_FIELD.search(_field_blob(f))
              or (PM_AUTH_PATH.search(path) and re.search(r"\bcode\b", _field_blob(f), re.I))
              for f in inputs)
    if otp or (PM_AUTH_PATH.search(path) and PM_VERIFY_TEXT.search(text)):
        return "verification"
    contact = any(f.get("type") in ("email", "password", "tel")
                  or re.search(r"e-?mail|password|phone|mobile", _field_blob(f), re.I) for f in inputs)
    if contact or PM_AUTH_PATH.search(str(facts.get("path") or "")):
        return "sign_in"
    if facts.get("unsupported"):
        return "unsupported"
    if facts.get("space_number"):
        return "space_number"
    if any(PLATE_FIELD.search(_field_blob(f)) for f in inputs):
        return "plate"
    if facts.get("zone_details"):
        return "zone_details"
    if DURATION_TEXT.search(text) and not facts.get("search"):
        return "duration"
    if facts.get("search"):
        return "search"
    return "unknown"


def _speakable(s: object, limit: int) -> str:
    """Page text made safe to show and read back: plain characters only, clipped."""
    t = re.sub(r"[^A-Za-z0-9 .,:/&()$#'-]", " ", str(s or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit].rstrip()


def pm_price_text(text: object) -> str | None:
    """The first line of the page with a dollar amount, plain and clipped (e.g. 'Total $4.35').
    Lines with an @ (an email address) are never used."""
    for line in str(text or "").splitlines():
        if PM_PRICE_RE.search(line) and "@" not in line:
            return _speakable(line, 80) or None
    return None


def pm_zone_info(lines: object, zone: str | None) -> dict:
    """From the zone-details page lines ['P', '91987', 'Atlanta, GA - Off St Operator',
    'Surface lot', '•', 'Park Tavern', 'Park here', ...]: {"zone", "zone_name", "operator"}."""
    out = {"zone": zone, "zone_name": None, "operator": None}
    if not isinstance(lines, list):
        return out
    ls = [str(x).strip() for x in lines if isinstance(x, str) and str(x).strip() and "@" not in x]
    idx = next((i for i, x in enumerate(ls) if ZONE_RE.fullmatch(x) and (zone is None or x == zone)), None)
    if idx is None:
        return out
    out["zone"] = ls[idx]
    rest = []
    for x in ls[idx + 1: idx + 8]:
        if re.fullmatch(r"park here|privacy policy", x, re.I) or PM_INFO_TEXT.search(x):
            break                                       # "Accepted payment methods" box (signed in)
        if x not in ("•", "·", "-"):
            rest.append(x)
    if rest:
        out["operator"] = _speakable(rest[0], 60) or None
        out["zone_name"] = _speakable(rest[-1], 40) or None
    return out


def pm_duration_patterns(minutes: int) -> list[re.Pattern]:
    """Labels a duration control might use for ``minutes`` (2 h -> '2 hours', '2 hr', '2h', '120 min')."""
    pats = [re.compile(rf"^\s*{minutes}\s*(m|min|mins|minutes)\b", re.I)]
    if minutes % 60 == 0:
        h = minutes // 60
        pats.insert(0, re.compile(rf"^\s*{h}\s*(h|hr|hrs|hour|hours)\b", re.I))
        pats.append(re.compile(rf"^\s*{h}:00\b"))
    return pats


PM_STOPPED_AT = {
    "sign_in": "ParkMobile's Add email / sign-in screen (before duration, plate and price)",
    "payment": "ParkMobile's payment step",
    "review": "ParkMobile's price review, just before payment",
    "robot_check": "a robot check on ParkMobile",
    "unsupported": "ParkMobile says this zone isn't supported on the web",
    "space_number": "ParkMobile asks for a space number",
    "verification": "a ParkMobile verification-code screen (the saved sign-in is gone)",
    "price": "ParkMobile's checkout with the price on screen, before any payment step",
}


def pm_status(screen: str) -> str:
    """Final status for the screen the run stopped on."""
    return {"payment": "ready_to_pay", "review": "ready_to_pay", "price": "ready_to_pay",
            "sign_in": "needs_sign_in", "robot_check": "robot_check",
            "verification": "needs_verification"}.get(screen, "failed")


def pm_step_text(step: str, zone: str = "", plate: str = "", minutes: int = 0) -> str:
    if minutes and minutes % 60 == 0:
        d = f"{minutes // 60} hour" + ("" if minutes == 60 else "s")
    else:
        d = f"{minutes} minutes"
    return {
        "open": "Opening the official ParkMobile site",
        "zone": f"Searching zone {zone}".rstrip(),
        "pick": f"Choosing zone {zone}".rstrip(),
        "park_here": "Tapping Park here",
        "duration": f"Choosing {d}",
        "plate": f"Typing your plate {plate}".rstrip(),
        "continue": "Tapping Continue",
        "stop_sign_in": "ParkMobile wants an email first. Stopping here",
        "stop_pay": "Price on screen. Stopped before payment",
        "stop_robot": "Robot check. Not touching it",
        "session": "Using your saved ParkMobile sign-in",
        "vehicle": f"Choosing your vehicle {plate}".rstrip(),
        "stop_verify": "ParkMobile wants a sign-in code. Stopping here",
        "stop_signed_out": "ParkMobile signed us out. Stopping here",
    }.get(step, step)


# --- saved, signed-in session (the person's OWN ParkMobile account) ----------------------------
#
# ParkMobile sign-in is passwordless (an emailed one-time code), so nothing here ever signs in.
# The person signs in once on the Mac; their Playwright storage_state (cookies + localStorage,
# *.parkmobile.io only) is kept on the sandbox VM and server.py mounts it read-only at
# PM_STATE_PATH for adapter "parkmobile" runs only. run_scan.py loads it into the context (filtered
# again by pm_filter_state), never writes it back, and never prints a cookie or token. If ParkMobile
# shows a sign-in / email / code screen anyway, the session is gone: stop (needs_sign_in /
# needs_verification). No email or code is ever typed.

PM_STATE_PATH = "/run/pm_state.json"
PM_VERIFY_TEXT = re.compile(r"verification code|enter (the |your )?(\d-digit )?code|we (just )?sent"
                            r"|one[\s-]?time (pass)?code|verify (your )?(email|phone|identity|account)"
                            r"|check your (email|inbox|phone|texts)|two[\s-]?factor|\b2fa\b"
                            r"|confirm your (email|phone)", re.I)
_OTP_FIELD = re.compile(r"one[\s-]?time|\botp\b|verification|passcode", re.I)


def _pm_domain_ok(host: object) -> bool:
    h = str(host or "").lower().lstrip(".")
    return h == "parkmobile.io" or h.endswith(".parkmobile.io")


def _pm_origin_ok(origin: object) -> bool:
    try:
        parts = urlsplit(str(origin or ""))
        port = parts.port
    except ValueError:
        return False
    return parts.scheme == "https" and port is None and _pm_domain_ok(parts.hostname)


def pm_filter_state(state: object) -> dict | None:
    """Only the *.parkmobile.io cookies and https origins of a Playwright storage_state.
    None if nothing usable is left (then the run is a guest run)."""
    if not isinstance(state, dict):
        return None
    cookies = [c for c in state.get("cookies") or []
               if isinstance(c, dict) and _pm_domain_ok(c.get("domain")) and c.get("name")]
    origins = [{k: o[k] for k in ("origin", "localStorage", "indexedDB") if k in o}
               for o in state.get("origins") or []
               if isinstance(o, dict) and _pm_origin_ok(o.get("origin"))]
    if not cookies and not origins:
        return None
    return {"cookies": cookies, "origins": origins}


PM_SESSION_ORIGIN = "https://app.parkmobile.io"
PM_MAX_SESSION_ITEMS = 200
PM_MAX_SESSION_VALUE = 100_000


def pm_session_items(state: object) -> list[dict]:
    """sessionStorage items saved for exactly https://app.parkmobile.io (top-level
    "sessionStorage": [{"origin", "items": [{"name", "value"}]}]); strings only, bounded."""
    items: list[dict] = []
    if not isinstance(state, dict):
        return items
    for entry in state.get("sessionStorage") or []:
        if not isinstance(entry, dict) or entry.get("origin") != PM_SESSION_ORIGIN:
            continue
        for it in entry.get("items") or []:
            if (isinstance(it, dict) and isinstance(it.get("name"), str) and isinstance(it.get("value"), str)
                    and 0 < len(it["name"]) <= 200 and len(it["value"]) <= PM_MAX_SESSION_VALUE):
                items.append({"name": it["name"], "value": it["value"]})
    return items[:PM_MAX_SESSION_ITEMS]


def pm_session_script(items: list) -> str:
    """Init script that puts ``items`` into sessionStorage on https://app.parkmobile.io only. The
    items travel as DATA: a JS string literal holding JSON (json.dumps twice, ASCII-escaped),
    parsed with JSON.parse at run time. No code is ever built from a name or value."""
    data = json.dumps(json.dumps([{"name": str(i["name"]), "value": str(i["value"])} for i in items]))
    return ("(() => { if (location.origin !== " + json.dumps(PM_SESSION_ORIGIN) + ") return; try { "
            "const items = JSON.parse(" + data + "); "
            "for (const it of items) { if (typeof it.name === 'string' && typeof it.value === 'string' "
            "&& sessionStorage.getItem(it.name) === null) sessionStorage.setItem(it.name, it.value); } "
            "} catch (e) {} })();")


# --- the payment fence (fix B) ---------------------------------------------------------------------

# A SAVED card shows masked digits; a brand name alone (e.g. the accepted-cards logos) isn't one.
PM_SAVED_CARD_TEXT = re.compile(r"\b(visa|mastercard|master card|amex|american express|discover)\b[^\n$]{0,16}?\d{4}\b"
                                r"|ending in \d{4}|[•*]{2,}\s?\d{4}", re.I)
PM_FORWARD_OK = re.compile(r"^(continue|next)$", re.I)


def pm_price_visible(facts: object) -> bool:
    """A price, a payment step or a saved payment method is on screen: from here on nothing
    else is clicked (no forward button, no vehicle or plate)."""
    if not isinstance(facts, dict):
        return False
    text = pm_scrub(facts.get("text"))
    return bool(PM_PRICE_RE.search(text) or PM_PAYMENT_TEXT.search(text)
                or PM_SAVED_CARD_TEXT.search(text) or pm_has_card_fields(facts))


def pm_forward_ok(info: object) -> bool:
    """The only forward buttons ever tapped: exactly "Continue" or "Next" (trimmed, any case)
    in both its text and its accessible name, whichever are set."""
    if not isinstance(info, dict):
        return False
    labels = [re.sub(r"\s+", " ", str(info.get(k) or "")).strip() for k in ("text", "aria")]
    labels = [x for x in labels if x]
    return bool(labels) and all(PM_FORWARD_OK.fullmatch(x) for x in labels)


PM_PAY_PATH_WORDS = re.compile(r"start|extend|purchase|checkout|payment|pay|order|charge|transaction"
                               r"|session|park", re.I)
PM_SAFE_PATH_WORDS = re.compile(r"search|quote", re.I)


def pm_request_blocked(method: object, url: object) -> bool:
    """Every non-GET request to *.parkmobile.io whose path looks like it starts, extends or pays
    for parking (start / extend / purchase / checkout / payment / pay / order / charge /
    transaction / session / park...), unless it's a search or a quote. Blocked in on_route."""
    if str(method or "GET").upper() in ("GET", "HEAD", "OPTIONS"):
        return False
    try:
        parts = urlsplit(str(url or ""))
    except ValueError:
        return True
    if not _pm_domain_ok(parts.hostname):
        return False
    path = re.sub(r"parkmobile", "", unquote(parts.path).lower())
    return bool(PM_PAY_PATH_WORDS.search(path)) and not PM_SAFE_PATH_WORDS.search(path)


def pm_redact_urls(text: object) -> str:
    """Drop the query/fragment of every URL in a message (tokens never reach the result)."""
    return re.sub(r"(https?://[^\s?#'\"]+)[?#][^\s'\"]*", r"\1", str(text or ""))


def pm_clean_url(url: object) -> str:
    """scheme://host/path only: no query, fragment or credentials in nav lines or the result."""
    try:
        parts = urlsplit(str(url or ""))
    except ValueError:
        return ""
    host = (parts.hostname or "").lower()
    return f"{parts.scheme}://{host}{parts.path}"[:300] if parts.scheme and host else str(url or "")[:40]
