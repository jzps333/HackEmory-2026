"""Cheap, explainable scam signals computed in the backend, next to Jev's AI answers.

Everything here is a pure function of what the sandbox saw, except registration_date(), which
asks RDAP (https://rdap.org) once per website with a short timeout and caches the answer.
Nothing in this module raises: a signal we can't compute is "unknown" and changes nothing.

How the signals move the score (the weights) is score_adjustment() below; api/scan.py decide()
applies it. Every signal also carries a plain-English fact for Gemini's explanation.
"""
from __future__ import annotations

import ipaddress
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from api import config

# ---------- weights (score is 0..1; malicious at config.BLOCK_SCORE 0.8, suspicious at 0.5) ----------
# Bumps are added to Jev's malicious_p before the hard floors (prompt injection, download,
# recovery phrase), so trust credit can never undo a floor.
W_NEW_DOMAIN = 0.25         # registered < 30 days ago: most phishing domains are used within days
W_YOUNG_DOMAIN = 0.10       # registered 30-90 days ago
W_LOOKALIKE = 0.25          # the address itself imitates a brand (paypa1.com, usps-redelivery.top)
W_PUNYCODE = 0.15           # xn-- / non-ASCII letters that can pass for Latin ones
W_IP_HOST = 0.15            # a bare IP address instead of a website name
W_BRAND_MISMATCH = 0.15     # the title names a brand whose website this isn't (0 on an old site
                            # that asks for nothing: a news headline can name a brand)
W_SHORTENER_HOP = 0.05      # a link shortener / QR redirector that lands on another website
W_MULTI_HOP = 0.10          # 2+ jumps between different websites
W_CHEAP_TLD = 0.05          # small bump only: plenty of real sites use these endings too
W_SENSITIVE_COMBO = 0.25    # asks for card / CVV / password / recovery phrase / SSN / bank details
                            # AND at least one warning sign (any above, free hosting, or Jev saw
                            # an impersonation). Never on an established site of the brand it shows.
W_OLD_DOMAIN = -0.05        # registered > 2 years ago (not on free hosting): slightly lower risk
W_ESTABLISHED_BRAND = -0.20 # old domain that really is the brand/site it shows (replaces W_OLD_DOMAIN):
                            # fixes false alarms on real login pages (GitHub, PayPal, Chase)
RECOVERY_PHRASE_FLOOR = 0.85  # real wallets never ask for a recovery phrase on a web page

NEW_DAYS, YOUNG_DAYS, OLD_DAYS = 30, 90, 730
JEV_ASKS_P = 0.8            # Jev's asks_* answer stands in for form fields we didn't see

RDAP_URL = "https://rdap.org/domain/{}"           # public redirector (rate-limited in bursts)
IANA_BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"   # TLD -> registry RDAP server
RDAP_TIMEOUT_S = 3.0
RDAP_OK_TTL_S = 12 * 3600
RDAP_FAIL_TTL_S = 2 * 60
RDAP_CACHE_MAX = 5000

# ---------- lists ----------

MULTI_PART_SUFFIXES = {
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "ltd.uk", "plc.uk", "net.uk",
    "com.au", "net.au", "org.au", "edu.au", "gov.au", "co.nz", "org.nz", "govt.nz",
    "co.jp", "ne.jp", "or.jp", "ac.jp", "go.jp", "co.kr", "or.kr", "go.kr", "co.in", "gov.in",
    "com.br", "gov.br", "com.mx", "gob.mx", "com.cn", "gov.cn", "com.sg", "gov.sg", "com.hk",
    "com.tw", "com.ar", "com.co", "com.my", "com.ph", "co.id", "com.vn", "co.za", "com.tr",
}
# Free hosting where anyone gets a subdomain: each subdomain is its own website, the platform's
# age says nothing about it.
SHARED_HOSTING = {
    "vercel.app", "netlify.app", "github.io", "gitlab.io", "pages.dev", "workers.dev", "web.app",
    "firebaseapp.com", "glitch.me", "onrender.com", "herokuapp.com", "repl.co", "replit.app",
    "replit.dev", "surge.sh", "ngrok.io", "ngrok-free.app", "ngrok.app", "trycloudflare.com",
    "azurewebsites.net", "blogspot.com", "weebly.com", "wixsite.com", "000webhostapp.com",
    "webflow.io", "framer.app", "framer.website", "carrd.co", "godaddysites.com",
    "mystrikingly.com", "translate.goog", "r2.dev", "amplifyapp.com", "appspot.com",
    "fly.dev", "deno.dev", "railway.app", "up.railway.app", "codesandbox.io", "csb.app",
    # user content on big brands' domains: the brand's age and name say nothing about the page
    "sharepoint.com", "amazonaws.com", "googleusercontent.com", "notion.site", "my.canva.site",
    "blob.core.windows.net", "web.core.windows.net", "myshopify.com",
}
# Single hosts where anyone can publish a page or form (phishers love these).
USER_CONTENT_HOSTS = {
    "docs.google.com", "sites.google.com", "drive.google.com", "forms.gle", "storage.googleapis.com",
    "firebasestorage.googleapis.com", "forms.office.com", "forms.microsoft.com", "onedrive.live.com",
    "1drv.ms", "raw.githubusercontent.com", "gist.github.com", "dl.dropboxusercontent.com",
    "linktr.ee", "t.me", "telegra.ph", "form.jotform.com", "typeform.com",
    "script.google.com", "script.googleusercontent.com",
}
SHORTENERS = {
    "bit.ly", "bitly.com", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "buff.ly",
    "rebrand.ly", "cutt.ly", "shorturl.at", "tiny.cc", "rb.gy", "bit.do", "s.id", "t.ly",
    "v.gd", "lnkd.in", "shorte.st", "adf.ly", "bl.ink", "short.gy", "tiny.one", "shrtco.de",
    # QR-code generators that redirect through their own short links
    "qrco.de", "l.ead.me", "me-qr.com", "qr.codes", "qrs.ly", "scan.page", "qr1.be", "qrfy.io",
    "qr-code-generator.com", "linktr.ee",
}
CHEAP_TLDS = {
    "top", "xyz", "icu", "click", "sbs", "cfd", "bond", "cyou", "buzz", "monster", "rest",
    "quest", "lol", "mom", "pics", "zip", "mov", "tk", "ml", "ga", "cf", "gq", "cam", "beauty",
    "hair", "skin", "makeup", "boats", "autos", "homes", "yachts", "motorcycles", "qpon", "win",
    "loan", "bid", "men", "date", "download", "stream", "gdn", "kim", "vip", "online", "site",
    "website", "fun", "space",
}
RESTRICTED_TLDS = {"gov", "mil", "edu"}          # only verified institutions can register these
RESERVED_TLDS = {"test", "example", "invalid", "localhost", "local", "onion", "internal",
                 "lan", "home", "arpa"}         # never sent to RDAP
MAINSTREAM_SUFFIXES = {
    "com", "net", "org", "co.uk", "de", "fr", "ca", "co.jp", "com.au", "in", "it", "es",
    "com.br", "com.mx", "nl", "se", "pl", "ie", "ch", "at", "be", "sg", "ae", "us", "cn", "jp",
}

# brand key -> (scam type if faked, display name, names as they appear in titles, official websites)
# A name in ALL CAPS is matched case-sensitively (so "ups" in "pop-ups" doesn't count).
BRANDS: dict[str, tuple[str, str, tuple[str, ...], tuple[str, ...]]] = {
    "paypal": ("fake_payment_app", "PayPal", ("paypal",), ("paypal.com", "paypal.me", "paypalobjects.com")),
    "venmo": ("fake_payment_app", "Venmo", ("venmo",), ("venmo.com",)),
    "cashapp": ("fake_payment_app", "Cash App", ("cash app", "cashapp"), ("cash.app", "squareup.com", "square.com")),
    "zelle": ("fake_payment_app", "Zelle", ("zelle",), ("zellepay.com", "zelle.com")),
    "coinbase": ("fake_payment_app", "Coinbase", ("coinbase",), ("coinbase.com",)),
    "binance": ("fake_payment_app", "Binance", ("binance",), ("binance.com", "binance.us")),
    "metamask": ("fake_payment_app", "MetaMask", ("metamask",), ("metamask.io",)),
    "chase": ("fake_bank", "Chase", ("chase",), ("chase.com", "jpmorganchase.com", "jpmorgan.com")),
    "wellsfargo": ("fake_bank", "Wells Fargo", ("wells fargo", "wellsfargo"), ("wellsfargo.com", "wf.com")),
    "bankofamerica": ("fake_bank", "Bank of America", ("bank of america", "bankofamerica"), ("bankofamerica.com", "bofa.com")),
    "citi": ("fake_bank", "Citi", ("citibank", "citi"), ("citi.com", "citibank.com")),
    "capitalone": ("fake_bank", "Capital One", ("capital one", "capitalone"), ("capitalone.com",)),
    "amex": ("fake_bank", "American Express", ("american express", "amex"), ("americanexpress.com", "amex.com")),
    "usps": ("fake_delivery", "USPS", ("usps", "postal service"), ("usps.com", "usps.gov")),
    "ups": ("fake_delivery", "UPS", ("UPS",), ("ups.com",)),
    "fedex": ("fake_delivery", "FedEx", ("fedex",), ("fedex.com",)),
    "dhl": ("fake_delivery", "DHL", ("DHL",), ("dhl.com", "dhl.de")),
    "irs": ("fake_government", "the IRS", ("IRS", "internal revenue service"), ("irs.gov",)),
    "ezpass": ("fake_parking_or_toll", "E-ZPass", ("e-zpass", "ezpass", "e-z pass"),
               ("e-zpassny.com", "ezpassnj.com", "e-zpassiag.com", "ezpassva.com", "ezpassmd.com",
                "ezpassde.com", "ezpassoh.com", "ezpassma.com", "ezpassrimaine.com")),
    "sunpass": ("fake_parking_or_toll", "SunPass", ("sunpass",), ("sunpass.com",)),
    "peachpass": ("fake_parking_or_toll", "Peach Pass", ("peach pass", "peachpass"), ("peachpass.com",)),
    "fastrak": ("fake_parking_or_toll", "FasTrak", ("fastrak",), ("bayareafastrak.org", "thetollroads.com")),
    "parkmobile": ("fake_parking_or_toll", "ParkMobile", ("parkmobile",), ("parkmobile.io", "parkmobile.com")),
    "apple": ("fake_login_other", "Apple", ("apple", "icloud", "apple id"), ("apple.com", "icloud.com")),
    "google": ("fake_login_other", "Google", ("google", "gmail"),
               ("google.com", "gmail.com", "youtube.com", "googleusercontent.com", "gstatic.com")),
    "microsoft": ("fake_login_other", "Microsoft", ("microsoft", "outlook", "office 365", "office365", "hotmail"),
                  ("microsoft.com", "live.com", "outlook.com", "office.com", "microsoftonline.com",
                   "hotmail.com", "microsoft365.com", "office365.com", "sharepoint.com")),
    "amazon": ("fake_login_other", "Amazon", ("amazon",), ("amazon.com", "a.co")),
    "netflix": ("fake_login_other", "Netflix", ("netflix",), ("netflix.com",)),
    "facebook": ("fake_login_other", "Facebook", ("facebook",), ("facebook.com", "fb.com", "meta.com", "fbcdn.net")),
    "instagram": ("fake_login_other", "Instagram", ("instagram",), ("instagram.com",)),
    "whatsapp": ("fake_login_other", "WhatsApp", ("whatsapp",), ("whatsapp.com", "whatsapp.net", "wa.me")),
    "docusign": ("fake_login_other", "DocuSign", ("docusign",), ("docusign.com", "docusign.net")),
    "dropbox": ("fake_login_other", "Dropbox", ("dropbox",), ("dropbox.com",)),
    "linkedin": ("fake_login_other", "LinkedIn", ("linkedin",), ("linkedin.com", "lnkd.in")),
    "github": ("fake_login_other", "GitHub", ("github",), ("github.com",)),
    "spotify": ("fake_login_other", "Spotify", ("spotify",), ("spotify.com",)),
    "roblox": ("fake_login_other", "Roblox", ("roblox",), ("roblox.com",)),
}
# Words phishing domains glue onto a brand ("paypal-login", "usps-redelivery", "chasesecure").
COMPANION_WORDS = {
    "login", "signin", "logon", "secure", "security", "verify", "verification", "account",
    "accounts", "update", "support", "help", "billing", "pay", "payment", "payments", "wallet",
    "refund", "confirm", "auth", "id", "service", "services", "alert", "alerts", "unlock",
    "track", "tracking", "delivery", "redelivery", "parcel", "package", "toll", "tolls", "fee",
    "fees", "claim", "reward", "rewards", "gift", "bonus", "online", "portal", "center",
    "customer", "notice", "usa", "us", "app", "web", "official", "recovery", "restore",
}

_TITLE_RES = {
    key: [re.compile(r"(?<![A-Za-z0-9])" + re.escape(n) + r"(?![A-Za-z0-9])",
                     0 if n.isupper() else re.IGNORECASE) for n in names]
    for key, (_, _, names, _) in BRANDS.items()
}

_SENSITIVE_RES = [
    ("recovery phrase", re.compile(r"recovery.?phrase|seed.?phrase|secret.?(recovery.?)?phrase|"
                                   r"mnemonic|private.?key|word1 word2|\b(12|24).?words?\b|"
                                   r"wallet.?phrase", re.I)),
    ("card number", re.compile(r"card.?(number|no\b|num)|credit.?card|debit.?card|cc.?num|"
                               r"\b\d{4}[ -]\d{4}[ -]\d{4}[ -]\d{4}\b|num[eé]ro de carte|"
                               r"n[uú]mero de (la )?tarjeta", re.I)),
    ("card security code (CVV)", re.compile(r"\bcvv2?\b|\bcvc2?\b|\bcsc\b|security.?code|"
                                            r"card.?verification", re.I)),
    ("password", re.compile(r"pass(word|code)|\bpwd\b|contrase[nñ]a|mot de passe|passwort", re.I)),
    ("Social Security number", re.compile(r"\bssn\b|social.?security", re.I)),
    ("bank account details", re.compile(r"routing.?number|account.?number|\biban\b|sort.?code", re.I)),
]
_AUTOCOMPLETE = {"cc-number": "card number", "cc-csc": "card security code (CVV)",
                 "current-password": "password", "new-password": "password"}
_SKIP_FIELD_TYPES = {"hidden", "submit", "button", "checkbox", "radio", "image", "reset",
                     "search", "range", "color", "file"}


# ---------- small helpers ----------

def host_of(url: str | None) -> str:
    try:
        return (urlparse(url or "").hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def split_site(host: str) -> tuple[str, str, bool]:
    """(site, public suffix, on shared hosting) for a hostname.
    'news.bbc.co.uk' -> ('bbc.co.uk', 'co.uk', False);
    'shop.vercel.app' -> ('shop.vercel.app', 'vercel.app', True);
    'docs.google.com' -> ('docs.google.com', 'docs.google.com', True). IPs stay whole."""
    host = (host or "").lower().rstrip(".")
    if not host or is_ip(host) or "." not in host:
        return host, "", False
    if host in USER_CONTENT_HOSTS:
        return host, host, True
    for platform in SHARED_HOSTING:
        if host.endswith("." + platform):
            label = host[: -len(platform) - 1].split(".")[-1]
            return f"{label}.{platform}", platform, True
    parts = host.split(".")
    n = 3 if len(parts) >= 3 and ".".join(parts[-2:]) in MULTI_PART_SUFFIXES else 2
    return ".".join(parts[-n:]), ".".join(parts[-(n - 1):]), False


def site_of(host: str) -> str:
    return split_site(host)[0]


def own_part(host: str) -> str:
    """The part of the address its owner chose: the whole host, minus a free-hosting platform
    ('paypal-verify.vercel.app' -> 'paypal-verify'; 'docs.google.com' -> '')."""
    site, platform, shared = split_site(host)
    if not shared:
        return host
    return "" if host == platform else host[: -len(platform) - 1]


def _same_page(a: str, b: str) -> bool:
    """Same address apart from a #fragment or a trailing slash."""
    def norm(u: str) -> str:
        u = u.split("#", 1)[0]
        return u[:-1] if u.endswith("/") else u
    return norm(a) == norm(b)


def clean_chain(chain) -> list[str]:
    """The redirect chain without repeats: the sandbox sometimes records the final page twice
    (a page that re-announces its own address) or a #fragment change as a hop. Keeps the
    later entry, so the last one still matches final_url."""
    out: list[str] = []
    for u in chain or []:
        if not isinstance(u, str) or not u:
            continue
        if out and _same_page(out[-1], u):
            out[-1] = u
        else:
            out.append(u)
    return out


def hop_summary(sandbox: dict) -> tuple[int, list[str]]:
    """(page changes after the QR link, websites visited in order). A move between pages of
    one website is a page change but not a new website."""
    chain = clean_chain(sandbox.get("redirect_chain"))
    urls = [u for u in [sandbox.get("url")] + chain + [sandbox.get("final_url")]
            if isinstance(u, str) and u]
    pages = clean_chain(urls)
    sites: list[str] = []
    for u in pages:
        s = site_of(host_of(u))
        if s and (not sites or sites[-1] != s):
            sites.append(s)
    return max(0, len(pages) - 1), sites


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


_SKELETON = [("rn", "m"), ("vv", "w"), ("cl", "d"), ("0", "o"), ("1", "l"), ("i", "l"),
             ("3", "e"), ("5", "s"), ("4", "a"), ("$", "s"), ("@", "a")]


def _skeleton(s: str) -> str:
    s = s.lower()
    for a, b in _SKELETON:
        s = s.replace(a, b)
    return s


def official_brands(site: str, suffix: str) -> set[str]:
    """Brands this website really belongs to (paypal.com -> {"paypal"}; amazon.de -> {"amazon"})."""
    label = site[: -len(suffix) - 1] if suffix and site.endswith("." + suffix) else site
    out = set()
    for key, (_, _, _, domains) in BRANDS.items():
        if site in domains or (label == key and suffix in MAINSTREAM_SUFFIXES):
            out.add(key)
    return out


def title_brands(title: str) -> set[str]:
    return {key for key, res in _TITLE_RES.items() if any(r.search(title or "") for r in res)}


def lookalike_brand(host: str, official: set[str], claimed: set[str]) -> str:
    """The brand the address imitates, or "". Typosquats (paypa1, rnicrosoft) always count;
    a brand glued to another word (paypal-login, chasesecure) counts when the other word is
    a typical phishing word or the page also claims that brand."""
    if not host or is_ip(host) or official:
        return ""
    tokens = [t for t in re.split(r"[.\-_]", host) if t]
    for key, (_, _, _, domains) in BRANDS.items():
        if any(f".{d}." in f".{host}." for d in domains):    # paypal.com.account-check.top
            return key
        for tok in tokens:
            if tok == key:
                others = set(tokens) - {tok}
                if key in claimed or others & COMPANION_WORDS:
                    return key
            elif len(key) >= 5 and tok.startswith(key):
                rest = tok[len(key):]
                if rest in COMPANION_WORDS or rest.isdigit() or key in claimed:
                    return key
            elif len(key) >= 5 and abs(len(tok) - len(key)) <= 1 and _skeleton(tok) == _skeleton(key):
                return key
    return ""


def sensitive_fields(form_fields) -> list[str]:
    """What the page's form asks for, from field type/name/placeholder/label/autocomplete."""
    found: list[str] = []
    for f in form_fields or []:
        if not isinstance(f, dict):
            continue
        ftype = str(f.get("type") or "").lower()
        if ftype in _SKIP_FIELD_TYPES:
            continue
        kinds = set()
        if ftype == "password":
            kinds.add("password")
        ac = str(f.get("autocomplete") or "").lower().split()
        kinds.update(_AUTOCOMPLETE[a] for a in ac if a in _AUTOCOMPLETE)
        text = " ".join(str(f.get(k) or "") for k in ("name", "placeholder", "label"))
        for kind, rx in _SENSITIVE_RES:
            if rx.search(text):
                kinds.add(kind)
        for kind, _ in _SENSITIVE_RES:          # keep a stable order
            if kind in kinds and kind not in found:
                found.append(kind)
    return found


# ---------- domain age (RDAP), cached, never raises ----------

_lock = threading.Lock()
_cache: dict[str, tuple[float, datetime | None]] = {}    # site -> (expires_at, registered)
_inflight: dict[str, Future] = {}
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="rdap")


_bootstrap: dict = {"until": 0.0, "map": {}}
_boot_lock = threading.Lock()


def _rdap_base(tld: str) -> str | None:
    """The registry's own RDAP server for a TLD, from IANA's bootstrap file (fetched at most
    once a day; retried after 10 minutes on failure). Asking the registry directly avoids
    rdap.org's burst rate limit (HTTP 429). None = use rdap.org."""
    with _boot_lock:
        if time.monotonic() >= _bootstrap["until"]:
            _refresh_bootstrap()
    return _bootstrap["map"].get(tld)


def _refresh_bootstrap() -> None:
    mapping: dict[str, str] = {}
    try:
        r = httpx.get(IANA_BOOTSTRAP_URL, timeout=RDAP_TIMEOUT_S)
        r.raise_for_status()
        for tlds, urls in (r.json().get("services") or []):
            https = [u for u in urls if str(u).startswith("https://")]
            for t in tlds:
                if https:
                    mapping[str(t).lower()] = https[0]
    except Exception:  # noqa: BLE001
        mapping = {}
    _bootstrap.update(map=mapping or _bootstrap["map"],
                      until=time.monotonic() + (86400 if mapping else 600))


def _fetch_registered(site: str) -> datetime | None:
    """One RDAP lookup: the domain's registration date, or None. ALL RDAP HTTP lives here."""
    try:
        base = _rdap_base(site.rsplit(".", 1)[-1])
        url = f"{base.rstrip('/')}/domain/{site}" if base else RDAP_URL.format(site)
        r = httpx.get(url, timeout=RDAP_TIMEOUT_S, follow_redirects=True,
                      headers={"accept": "application/rdap+json"})
        if r.status_code != 200 and base:      # registry hiccup: try the public redirector once
            r = httpx.get(RDAP_URL.format(site), timeout=RDAP_TIMEOUT_S, follow_redirects=True,
                          headers={"accept": "application/rdap+json"})
        if r.status_code != 200:
            return None
        for ev in r.json().get("events") or []:
            if isinstance(ev, dict) and ev.get("eventAction") == "registration":
                d = datetime.fromisoformat(str(ev.get("eventDate")).replace("Z", "+00:00"))
                return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001 - network, JSON, date format: all mean "unknown"
        return None
    return None


def _rdap_eligible(site: str, shared: bool) -> bool:
    return (config.SIGNALS_RDAP and bool(site) and "." in site and not shared and not is_ip(site)
            and site.rsplit(".", 1)[-1] not in RESERVED_TLDS | RESTRICTED_TLDS)


def _lookup(site: str) -> datetime | None:
    reg = _fetch_registered(site)
    ttl = RDAP_OK_TTL_S if reg else RDAP_FAIL_TTL_S
    with _lock:
        if len(_cache) >= RDAP_CACHE_MAX:
            _cache.pop(next(iter(_cache)))
        _cache[site] = (time.monotonic() + ttl, reg)
        _inflight.pop(site, None)
    return reg


def _start(site: str) -> Future | None:
    """Cached answer as a done Future, the running lookup, or a new one. Caller holds no lock."""
    with _lock:
        hit = _cache.get(site)
        if hit and hit[0] > time.monotonic():
            f: Future = Future()
            f.set_result(hit[1])
            return f
        if site in _inflight:
            return _inflight[site]
        try:
            f = _pool.submit(_lookup, site)
        except RuntimeError:          # interpreter shutting down
            return None
        _inflight[site] = f
        return f


def prefetch(sandbox: dict) -> None:
    """Start the domain-age lookup now (e.g. while Jev thinks). Never raises, never waits."""
    try:
        site, _, shared = split_site(host_of(sandbox.get("final_url")) or str(sandbox.get("domain") or ""))
        if _rdap_eligible(site, shared):
            _start(site)
    except Exception:  # noqa: BLE001
        pass


def registration_date(site: str, wait: float = RDAP_TIMEOUT_S) -> datetime | None:
    """When the website's domain was registered, or None (unknown / slow / not applicable).
    wait <= 0: only a cached answer, never a new lookup."""
    try:
        if wait <= 0:
            with _lock:
                hit = _cache.get(site)
            return hit[1] if hit and hit[0] > time.monotonic() else None
        f = _start(site)
        return f.result(timeout=wait) if f else None
    except (FutureTimeout, Exception):  # noqa: BLE001 - a slow lookup keeps filling the cache
        return None


# ---------- the signals ----------

@dataclass(frozen=True)
class Signals:
    """Facts about one scanned page. Built by collect(); used by api/scan.py decide()."""
    host: str = ""
    site: str = ""                      # registrable domain ("paypal.com", "shop.vercel.app")
    shared_hosting: str = ""            # the free hosting platform, if any ("vercel.app")
    age_days: int | None = None         # None = unknown
    restricted_tld: bool = False        # .gov / .mil / .edu
    ip_host: bool = False
    punycode: bool = False
    cheap_tld: bool = False
    shortener: bool = False             # the QR link is a shortener that lands on another website
    redirects: int = 0                  # page changes after the QR link (duplicates removed)
    sites: tuple[str, ...] = ()         # websites visited, in order
    claimed_brands: tuple[str, ...] = ()  # brands named in the page title
    official_brand: str = ""            # the brand this website really is
    names_itself: bool = False          # the title names this website ("Sign in to GitHub" on github.com)
    brand_mismatch: str = ""            # a brand the title claims, on a website that isn't theirs
    lookalike: str = ""                 # a brand the address imitates
    sensitive: tuple[str, ...] = ()     # what the form asks for ("card number", "password", ...)
    sensitive_from_jev: bool = False    # no such field seen, but Jev says it asks for card/password
    jev_impersonation: bool = False     # Jev thinks the page pretends to be someone (p >= 0.6)

    @property
    def cross_site_hops(self) -> int:
        return max(0, len(self.sites) - 1)

    @property
    def new_domain(self) -> bool:
        return self.age_days is not None and self.age_days < NEW_DAYS

    @property
    def young_domain(self) -> bool:
        return self.age_days is not None and NEW_DAYS <= self.age_days < YOUNG_DAYS

    @property
    def old_domain(self) -> bool:
        return not self.shared_hosting and not self.ip_host and (
            self.restricted_tld or (self.age_days is not None and self.age_days >= OLD_DAYS))

    @property
    def address_tricks(self) -> bool:
        return bool(self.lookalike) or self.punycode or self.ip_host

    @property
    def brand_match(self) -> bool:
        """This website is who the page says it is. Only independent evidence counts: a curated
        brand's own domain, or a restricted TLD (.gov/.edu). A page naming its own site in its title
        (names_itself) is page-controlled, so it only prevents a false "mismatch", never earns trust."""
        return (bool(self.official_brand) or self.restricted_tld) \
            and not self.brand_mismatch and not self.address_tricks

    @property
    def established_brand(self) -> bool:
        """Long-established website that really is the brand/site it shows."""
        return self.old_domain and self.brand_match

    @property
    def asks_recovery_phrase(self) -> bool:
        return "recovery phrase" in self.sensitive

    @property
    def asks_sensitive(self) -> bool:
        return bool(self.sensitive) or self.sensitive_from_jev

    @property
    def warning_signs(self) -> bool:
        """Any sign that makes a sensitive ask dangerous."""
        return (self.new_domain or self.young_domain or self.address_tricks
                or bool(self.brand_mismatch) or self.shortener or self.cross_site_hops >= 2
                or self.cheap_tld or bool(self.shared_hosting) or self.jev_impersonation)

    def facts(self) -> list[tuple[str, str]]:
        """(tone, plain-English fact) pairs for the explanation. tone: "risk" or "trust"."""
        out: list[tuple[str, str]] = []
        if self.age_days is not None:
            if self.age_days < YOUNG_DAYS:
                out.append(("risk", f"The website's address ({self.site}) was registered only "
                                    f"{self.age_days} days ago."))
            elif self.age_days >= OLD_DAYS:
                out.append(("trust", f"The website's address ({self.site}) has been registered "
                                     f"for about {self.age_days // 365} years."))
        if self.official_brand and self.brand_match:
            out.append(("trust", f"{self.site} is the real website of "
                                 f"{BRANDS[self.official_brand][1]}."))
        elif self.restricted_tld and self.brand_match:
            out.append(("trust", f"{self.site} uses an address ending only verified institutions can get."))
        if self.lookalike:
            out.append(("risk", f"The address {self.host} imitates "
                                f"{BRANDS[self.lookalike][1]} but is not their website."))
        if self.brand_mismatch:
            out.append(("risk", f"The page claims to be "
                                f"{BRANDS[self.brand_mismatch][1]}, but {self.site} is not "
                                f"their website."))
        if self.punycode:
            out.append(("risk", "The address uses look-alike letters from another alphabet."))
        if self.ip_host:
            out.append(("risk", "The link goes to a bare number address instead of a website name."))
        if self.shortener:
            out.append(("risk", "The QR code uses a link shortener that hides where it really goes."))
        if self.cross_site_hops >= 2:
            out.append(("risk", f"The link passed through {self.cross_site_hops} different websites."))
        if self.cheap_tld:
            out.append(("risk", f"The address ends in .{self.host.rsplit('.', 1)[-1]}, an ending "
                                f"scam sites often use."))
        if self.shared_hosting and (self.asks_sensitive or self.claimed_brands):
            out.append(("risk", f"The page is on {self.shared_hosting}, a free service anyone can "
                                f"put pages on."))
        if self.sensitive:
            out.append(("risk", "The page asks for: " + ", ".join(self.sensitive) + "."))
        return out


def collect(sandbox: dict, checks=None, now: datetime | None = None,
            wait: float = RDAP_TIMEOUT_S) -> Signals:
    """All signals for one sandbox result. checks: Jev's JevChecks (optional). Never raises."""
    try:
        return _collect(sandbox, checks, now or datetime.now(timezone.utc), wait)
    except Exception:  # noqa: BLE001 - a bug here must never break a scan
        return Signals()


def _collect(sandbox: dict, checks, now: datetime, wait: float) -> Signals:
    final_host = host_of(sandbox.get("final_url")) or str(sandbox.get("domain") or "").lower()
    qr_host = host_of(sandbox.get("url"))
    site, suffix, shared = split_site(final_host)
    tld = final_host.rsplit(".", 1)[-1] if "." in final_host else ""
    redirects, sites = hop_summary(sandbox)
    qr_site = site_of(qr_host)
    title = str(sandbox.get("page_title") or "")

    official = official_brands(site, suffix) if not shared else set()
    claimed = title_brands(title)
    qr_split = split_site(qr_host)
    lookalike = lookalike_brand(own_part(final_host), official, claimed) or (
        lookalike_brand(own_part(qr_host), set() if qr_split[2] else official_brands(*qr_split[:2]),
                        claimed) if qr_host and qr_site != site else "")
    label = site[: -len(suffix) - 1] if suffix and site.endswith("." + suffix) else site
    names_itself = (len(_compact(label)) >= 3 and _compact(label) in _compact(title)
                    and not lookalike)
    mismatch = ""
    if claimed and not (claimed & official) and not names_itself:
        mismatch = sorted(claimed)[0]

    age = None
    if _rdap_eligible(site, shared):
        reg = registration_date(site, wait)
        if reg:
            age = max(0, (now - reg).days)

    sensitive = sensitive_fields(sandbox.get("form_fields"))
    from_jev = False
    imp = False
    if checks is not None:
        from_jev = not sensitive and max(getattr(checks, "asks_payment_p", 0.0),
                                         getattr(checks, "asks_password_p", 0.0)) >= JEV_ASKS_P
        imp = getattr(checks, "impersonates", "none") != "none" and \
            getattr(checks, "impersonates_p", 0.0) >= 0.6

    return Signals(
        host=final_host, site=site, shared_hosting=suffix if shared else "", age_days=age,
        restricted_tld=tld in RESTRICTED_TLDS, ip_host=is_ip(final_host),
        punycode=any(lbl.startswith("xn--") for h in (final_host, qr_host) for lbl in h.split("."))
        or any(ord(ch) > 127 for ch in final_host + qr_host),
        cheap_tld=tld in CHEAP_TLDS,
        shortener=(qr_site in SHORTENERS or qr_host in SHORTENERS) and bool(sites) and sites[-1] != qr_site,
        redirects=redirects, sites=tuple(sites),
        claimed_brands=tuple(sorted(claimed)), official_brand=sorted(official)[0] if official else "",
        names_itself=names_itself, brand_mismatch=mismatch, lookalike=lookalike,
        sensitive=tuple(sensitive), sensitive_from_jev=from_jev, jev_impersonation=imp,
    )


def score_adjustment(sig: Signals) -> tuple[float, list[str]]:
    """(change to Jev's score, names of the rules that fired). Weights documented at the top."""
    delta, fired = 0.0, []

    def add(w: float, name: str) -> None:
        nonlocal delta
        delta += w
        fired.append(f"{name} {w:+.2f}")

    if sig.new_domain:
        add(W_NEW_DOMAIN, "new_domain")
    elif sig.young_domain:
        add(W_YOUNG_DOMAIN, "young_domain")
    if sig.lookalike:
        add(W_LOOKALIKE, "lookalike")
    if sig.punycode:
        add(W_PUNYCODE, "punycode")
    if sig.ip_host:
        add(W_IP_HOST, "ip_host")
    if sig.brand_mismatch and (not sig.old_domain or sig.asks_sensitive):
        add(W_BRAND_MISMATCH, "brand_mismatch")
    if sig.shortener:
        add(W_SHORTENER_HOP, "shortener")
    if sig.cross_site_hops >= 2:
        add(W_MULTI_HOP, "multi_hop")
    if sig.cheap_tld:
        add(W_CHEAP_TLD, "cheap_tld")
    if sig.asks_sensitive and sig.warning_signs and not sig.established_brand:
        add(W_SENSITIVE_COMBO, "sensitive_ask_with_warning_signs")
    if sig.established_brand:
        add(W_ESTABLISHED_BRAND, "established_brand")
    elif sig.old_domain and not sig.address_tricks:
        add(W_OLD_DOMAIN, "old_domain")
    return round(delta, 3), fired


def scam_type_hint(sig: Signals) -> str | None:
    """The scam type of the brand being imitated, when the address or title gives it away."""
    key = sig.lookalike or sig.brand_mismatch
    return BRANDS[key][0] if key else None


def hop_fact(sig: Signals, domain: str | None) -> str:
    """One sentence about where the link went, so Gemini never invents a redirect."""
    if sig.cross_site_hops == 0:
        where = sig.site or domain or "the website"
        if sig.redirects == 0:
            return (f"Website changes: 0. The link opened {where} directly and did not send the "
                    f"visitor to another website.")
        return (f"Website changes: 0. The link moved between pages of the same website ({where}); "
                f"it did not send the visitor to another website.")
    return (f"Website changes: {sig.cross_site_hops}. The link sent the visitor through these "
            f"websites: {' -> '.join(sig.sites)}.")
