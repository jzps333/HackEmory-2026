"""Runs INSIDE a throwaway Docker container. Opens one URL, records what happened, prints JSON.

Usage (inside the container): python run_scan.py <url> [--stream]
                              python run_scan.py --operate <url> <plate> <hours>
                              python run_scan.py --operate-parkmobile <url> <zone|-> <plate> <minutes>
--operate-parkmobile drives the REAL ParkMobile web app (app.parkmobile.io) and stops at the first
sign-in / contact-details / payment / price screen; it never pays (see operate.py).
--operate is operator mode (operate.py), a separate, fenced path that is NOT a scan: it drives
the made-up official Dogwood Parking app on our demo site (Install, Open, type the plate, tap
the hours, tap Pay, watch for the receipt), streaming frames like --stream. Scans never type.
--stream: also print the browser's screen as it changes, one JSON line per frame
({"type":"frame","jpeg":...}) plus {"type":"nav","url":...} lines, before the final result line.
The LAST line is always the plain result JSON, with or without --stream.
No keys, no logins, no personal data live here. Downloads are blocked, never opened.

Network guard: every request the browser makes (first URL, each redirect hop, subresources,
popups, iframes) goes through context.route(); its hostname is resolved and the request is
aborted unless EVERY resolved address is public (see netguard.py). Blocked requests are listed
in `blocked_requests`. Service workers and WebSockets are blocked so nothing bypasses routing.
The host firewall on the sandbox VM is the second layer (see README.md).

Barriers: after the page settles the browser clicks past up to 3 harmless interstitials (cookie
banners, preferring "Reject all"; "Continue"/"Skip ad"; modal close buttons; age gates; "click
here if not redirected" links), listed in `clicked`. It never types, and never clicks anything
that looks like pay/buy/download/install/sign in/subscribe/submit/call/notifications, a file
link, or a button that would submit a form with fields to fill. Robot checks (reCAPTCHA,
hCaptcha, Cloudflare Turnstile) and sign-in walls are detected, never touched: `bot_check`,
`login_wall`. In --stream mode each click is also printed as {"type":"step","text":...}.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import threading
import time
import unicodedata
from urllib.parse import urlparse

from netguard import CachingGuard, is_public_ip
from operate import (PHASE_JS, STEPS_FROM_APP, clean_plate, hours_selector, operate_request_allowed,
                     operate_status, operate_url_allowed, page_phase, plan_steps, step_text,
                     valid_hours)
from operate import SEL as OP_SEL
from operate import (PM_ENTRY_URL, PM_FACTS_JS, PM_MASK_EMAIL_JS, PM_SEL, PM_STATE_PATH, PM_STOPPED_AT,
                     check_parkmobile_request, clean_zone, parkmobile_request_allowed,
                     pm_area_from_url, pm_clean_url, pm_click_refused, pm_duration_patterns,
                     pm_filter_state, pm_forward_ok, pm_must_stop, PM_DURATION_PATH, pm_minutes, pm_price_text, pm_price_visible,
                     pm_redact_urls, pm_request_blocked, pm_result_selector, pm_screen,
                     pm_session_items, pm_session_script, pm_status, pm_step_text,
                     pm_type_refused, pm_type_value_ok, pm_zone_info)

MAX_TEXT = 4000            # page_text characters
MAX_HIDDEN = 1500          # hidden_text characters
MAX_FIELDS = 25            # form fields
MAX_FIELD_STR = 80         # characters per form-field attribute
MAX_BLOCKED = 30           # blocked_requests entries
MAX_HOPS = 10              # main-frame navigations before we stop following
MAX_REQUESTS = 300         # total requests per scan before we abort the rest
TIMEOUT_MS = 20000
SETTLE_MS = 2500           # wait for JS redirects / popups
SHOT_QUALITY = 80
STREAM_MIN_GAP_S = 0.12    # at most ~8 frames/s on the live stream
STREAM_QUALITY = 55
STREAM_MAX_FRAMES = 400    # hard cap per scan
CLICK_ROUNDS = 3           # barriers clicked past, at most one per round
CLICK_SETTLE_MS = 800      # wait after each click
CLICK_TIMEOUT_MS = 1500    # Playwright's own click (then a plain JS click as fallback)
CLICK_BUDGET_S = 8.0       # all click-past rounds together
CHALLENGE_WAIT_MS = 3000   # one extra wait for a "Just a moment..." page to clear by itself
MAX_CANDIDATES = 80        # buttons/links per frame looked at per round
MAX_CLICK_FRAMES = 5       # same-site iframes looked into besides the main frame
MAX_LABEL = 60             # characters of a clicked label kept in the result


_out_lock = threading.Lock()


def _emit_line(line: str) -> None:
    """One whole line on stdout. Locked: the screencast's trailing-frame timer prints too."""
    with _out_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def _emit(obj: dict) -> None:
    _emit_line(json.dumps(obj))

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


# ---------- click past harmless barriers: pure helpers (tested offline in tests/) ----------
#
# The browser only ever clicks a button/link whose visible label EXACTLY matches one of the
# short phrases below (after lower-casing and trimming punctuation), or one of a few tight
# patterns (age gates, "click here if not redirected"). FORBIDDEN wins over everything.

FORBIDDEN = re.compile(r"""
    \bpay | \bbuy\b | \bpurchas | check\s?out | \border | \bdonat | \bcard\b | \bbilling
  | \bwallet | \bsubscri | \bsign[\s-]?(in|up|on)\b | \blog[\s-]?(in|on)\b | \bregist
  | create\ (an\ )?account | \bjoin\b | \bdownload | \binstall | \bget\ (the\ )?app
  | \bopen\ (in\ )?(the\ )?app | app\ store | google\ play | \bnotif | \bpush\b
  | \ballow\ (location|camera|microphone|access) | \bsubmit | \bsend\b | \bcall\b | \bphone
  | \bdial\b | \bsms\b | \btext\ (me|us)\b | whatsapp | \bverif | captcha | \brobot | \bhuman\b
  | \bclaim | \bredeem | \bprize | \bunlock | \bupgrade | \btrial\b | \bpassword
  | \bcontinu(e|ar|er)\ (with|con|avec)\b
  | pagar | comprar | tarjeta | descarg | instalar | iniciar\ sesi | suscrib | enviar | llamar
  | payer | acheter | t[ée]l[ée]charg | installer | se\ connecter | connexion | inscri | abonn
  | envoyer | appeler
""", re.X)

COOKIE_REJECT = {
    "reject", "reject all", "reject all cookies", "reject cookies", "reject optional cookies",
    "reject non-essential", "reject non-essential cookies", "reject additional cookies",
    "decline", "decline all", "decline cookies", "decline all cookies", "decline optional cookies",
    "deny", "deny all", "refuse", "refuse all", "disagree", "i disagree", "do not accept",
    "don't accept", "i do not accept", "necessary only", "only necessary",
    "necessary cookies only", "only necessary cookies", "use necessary cookies only",
    "allow necessary cookies only", "accept necessary", "accept necessary cookies",
    "accept only necessary", "accept only necessary cookies", "accept essential",
    "accept essential cookies", "accept only essential", "accept only essential cookies",
    "essential only", "only essential", "essential cookies only", "only essential cookies",
    "strictly necessary only", "continue without accepting", "continue without agreeing",
    "rechazar", "rechazar todo", "rechazar todas", "rechazar cookies",
    "rechazar todas las cookies", "solo necesarias", "sólo necesarias", "solo las necesarias",
    "aceptar solo necesarias", "aceptar solo las necesarias", "continuar sin aceptar",
    "refuser", "tout refuser", "refuser tout", "refuser les cookies", "je refuse",
    "continuer sans accepter", "uniquement nécessaires",
}
COOKIE_ACCEPT = {
    "accept", "accept all", "accept all cookies", "accept cookies", "accept and close",
    "accept & close", "accept and continue", "accept & continue", "accept and proceed",
    "accept & proceed", "allow all", "allow all cookies", "allow cookies", "i accept", "i agree",
    "agree", "agree and close", "agree & close", "agree and continue", "agree & continue",
    "agree and proceed", "yes, i agree", "yes, i accept", "ok", "okay", "ok, i agree",
    "consent", "i consent",
    "aceptar", "aceptar todo", "aceptar todas", "aceptar cookies", "aceptar todas las cookies",
    "acepto", "de acuerdo", "aceptar y cerrar", "aceptar y continuar", "permitir todas",
    "accepter", "tout accepter", "accepter tout", "accepter et fermer", "accepter et continuer",
    "j'accepte", "d'accord",
}
CLOSE_LABELS = {
    "close", "×", "x", "✕", "✖", "╳", "⨯", "no thanks", "no, thanks", "no thank you",
    "no, thank you", "not now", "not right now", "maybe later", "later", "remind me later",
    "got it", "ok, got it", "okay, got it", "dismiss", "i understand", "understood", "hide",
    "cerrar", "no, gracias", "no gracias", "ahora no", "más tarde", "mas tarde", "entendido",
    "fermer", "non merci", "non, merci", "pas maintenant", "plus tard", "j'ai compris", "compris",
}
CLOSE_RE = re.compile(
    r"^(close|dismiss|hide|cerrar|fermer)( (this|the))? ?(dialog|modal|popup|pop-up|pop up|"
    r"banner|window|message|ad|advert|advertisement|overlay|notice|alert|announcement|offer|"
    r"panel|menu)?$")
# "Dismiss sign-in info", "Close subscribe banner": closing a named pop-up is a close, even when
# the pop-up's name mentions something forbidden. No "and"/"then"/"to" in between.
CLOSE_OBJECT_RE = re.compile(
    r"^(close|dismiss|hide|cerrar|fermer) (this |the )?(?:(?!(and|then|to|y|et)\b)[\w'-]+ ){0,3}"
    r"(dialog|modal|popup|pop-up|banner|window|message|ad|advert|overlay|notice|alert|"
    r"announcement|offer|panel|info|information|prompt|promo|promotion|box|bar|sheet|drawer|"
    r"tooltip|toast|popover)$")
CONTINUE_LABELS = {
    "continue", "continue to site", "continue to website", "continue to the site",
    "continue to the website", "continue to page", "continue to the page", "continue anyway",
    "proceed", "proceed to site", "proceed to website", "proceed anyway", "skip", "skip ad",
    "skip ads", "skip this ad", "skip intro", "skip video", "go to site", "go to website",
    "go to the site", "visit site", "visit website", "take me to the site",
    "continuar", "continuar al sitio", "ir al sitio", "omitir", "omitir anuncio", "saltar",
    "saltar anuncio", "proceder",
    "continuer", "continuer vers le site", "continuer sur le site", "accéder au site", "passer",
    "passer la publicité", "ignorer la publicité",
}
AGE_RE = re.compile(
    r"^(yes,? )?(i'?m|i am) (at least |over |older than )?(18|19|21)( years old| years of age)?"
    r"( or older| or over|\+| and over| or above)?(,? (let me )?enter( site)?)?$"
    r"|^(yes,? )?(i'?m|i am) of legal (drinking )?age$|^(i'?m|i am) an adult$"
    r"|^(18|21)\+?,? enter$|^enter,? (i'?m|i am) (18|21)\+?$"
    r"|^soy mayor de edad$|^tengo (18|21) años o más$|^j'ai (18|21) ans ou plus$"
    r"|^je suis majeure?$")
ENTER_LABELS = {"enter", "enter site", "enter the site", "enter website", "yes", "yes, enter",
                "yes, let me in", "entrar", "sí", "si", "entrer", "oui"}
REDIRECT_RE = re.compile(
    r"not (been )?(automatically )?redirected|redirect(ed)? now|if nothing happens"
    r"|if (the|this) page does(n't| not) (load|redirect|change)|isn't redirecting"
    r"|no (es |eres )?redirigido|pas redirigée?")
HERE_LABELS = {"click here", "here", "this link", "click this link", "go now", "redirect",
               "haz clic aquí", "aquí", "cliquez ici", "ici"}

CONSENT_CTX = re.compile(
    r"cookie|consent|gdpr|ccpa|privacy|personal data|personali[sz]ed (ads|content)|tracking "
    r"technolog|our partners|vendors|datos personales|privacidad|données personnelles|vie privée"
    r"|traceurs|confidentialité")
CMP_ATTR = re.compile(
    r"cookie|consent|gdpr|ccpa|onetrust|didomi|cookiebot|truste|usercentrics|qc-cmp|sp_message"
    r"|osano|termly|iubenda|\bcmp|cc-window|cc-banner|cookielaw|evidon|quantcast|privacy")
AGE_CTX = re.compile(r"\b(18|19|21)\b|\bage\b|\badult|\bolder\b|legal age|of age|drinking"
                     r"|mayor de edad|\bedad\b|\bâge\b|majeur|\bans\b")
REDIRECT_CTX = re.compile(r"redirect|forward|automatic|if nothing happens|redirig|redirection"
                          r"|automáticamente|automatiquement|reenvi")

FILE_EXT = (".exe", ".msi", ".msix", ".appx", ".apk", ".aab", ".xapk", ".ipa", ".dmg", ".pkg",
            ".deb", ".rpm", ".bin", ".bat", ".cmd", ".com", ".scr", ".ps1", ".vbs", ".js", ".jar",
            ".lnk", ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".iso", ".img", ".pdf", ".doc",
            ".docx", ".docm", ".xls", ".xlsx", ".xlsm", ".ppt", ".pptx", ".rtf", ".mobileconfig",
            ".torrent", ".hta", ".svg")
OK_LINK_SCHEMES = {"", "http", "https", "javascript"}   # javascript: = in-page, no new network

KIND_PRIORITY = {"cookie": 0, "age_gate": 1, "close": 2, "continue": 3, "redirect_link": 4}
CHOICE_PRIORITY = {"reject": 0, "dismiss": 1, "accept": 2}   # cookie banners: least consent first

_CLOSE_GLYPHS = "×✕✖╳⨯"
_TRIM = " .!?:;,·•›»→>«‹←<-–—()[]\"“”'"


def norm_label(label: str) -> str:
    """Lower-case, NFKC, straight quotes, single spaces, no punctuation/arrows at the ends."""
    s = unicodedata.normalize("NFKC", str(label or ""))
    s = s.replace("’", "'").replace("‘", "'").replace("`", "'")
    s = re.sub(r"\s+", " ", s).strip().lower().strip(_TRIM)
    if len(s) > 1:   # "Close ×" -> "close"; a lone "×" stays
        s = s.strip(_CLOSE_GLYPHS).strip(_TRIM) or s
    return s


def classify_label(label: str) -> str | None:
    """What a button/link label says, ignoring context: 'reject', 'accept', 'close', 'continue',
    'age', 'enter', 'redirect', 'here', or None (not ours to click, or forbidden)."""
    s = norm_label(label)
    if not s or len(s) > 80:
        return None
    if len(s) <= 48 and CLOSE_OBJECT_RE.match(s):
        return "close"
    if FORBIDDEN.search(s):
        return None
    if AGE_RE.search(s):
        return "age"
    if REDIRECT_RE.search(s):
        return "redirect"
    if len(s) > 48:
        return None
    if s in COOKIE_REJECT:
        return "reject"
    if s in COOKIE_ACCEPT:
        return "accept"
    if s in CLOSE_LABELS or CLOSE_RE.match(s):
        return "close"
    if s in CONTINUE_LABELS:
        return "continue"
    if s in ENTER_LABELS:
        return "enter"
    if s in HERE_LABELS:
        return "here"
    return None


def is_file_link(href: str) -> bool:
    path = urlparse(href or "").path.lower().rstrip("/")
    return path.endswith(FILE_EXT)


def click_kind(c: dict) -> tuple[str, str | None] | None:
    """(kind, cookie choice) if this candidate (facts from CANDIDATES_JS) is a harmless barrier
    button we may click, else None. kind: cookie|continue|close|age_gate|redirect_link."""
    cls = classify_label(c.get("label", ""))
    if cls is None:
        return None
    abs_href = c.get("abs_href") or ""
    scheme = urlparse(abs_href).scheme.lower() if abs_href else ""
    if c.get("download") or is_file_link(abs_href) or scheme not in OK_LINK_SCHEMES:
        return None
    if c.get("submits_fillable_form"):
        return None                     # pressing it would submit a form with fields to fill
    ctx = (c.get("ctx_text") or "").lower()
    overlay = bool(c.get("overlay"))
    # A cookie banner: a known consent tool's id/class, the word "cookie", or consent wording
    # in a pop-up. ("privacy" alone in the page flow could be anything.)
    consent = bool(CMP_ATTR.search((c.get("ctx_attrs") or "").lower()) or "cookie" in ctx
                   or "cookie" in norm_label(c.get("label", ""))
                   or (overlay and CONSENT_CTX.search(ctx)))
    if cls == "reject":
        if consent:
            return "cookie", "reject"
        return ("close", None) if overlay else None   # "Decline" on some other pop-up
    if cls == "accept":
        return ("cookie", "accept") if consent else None
    if cls == "close":   # "Got it" / "×" on a cookie notice: dismissed without choosing
        return ("cookie", "dismiss") if consent else (("close", None) if overlay else None)
    if c.get("fillable_ctx"):
        return None                     # "Continue" next to an email box is a form step
    if cls == "continue":
        return "continue", None
    if cls == "age":
        return "age_gate", None
    if cls == "enter":
        return ("age_gate", None) if AGE_CTX.search(ctx) else None
    if cls in ("redirect", "here"):
        raw = (c.get("href") or "").strip()
        if c.get("tag") != "a" or scheme not in ("http", "https") or raw.startswith("#"):
            return None
        if cls == "here" and not REDIRECT_CTX.search(ctx):
            return None
        return "redirect_link", None
    return None


def choose_click(cands: list[dict], login_wall: bool = False,
                 skip_labels: set[str] | frozenset = frozenset()) -> tuple[int, str, str | None] | None:
    """Pick the one barrier to click this round: (index, kind, choice) or None.
    Cookie banners first ("Reject", then a plain close, then "Accept"), then age gates, close
    buttons, "Continue", redirect links. On a sign-in page only cookie banners and close
    buttons are touched."""
    best, best_key = None, None
    for i, c in enumerate(cands):
        res = click_kind(c)
        if res is None or norm_label(c.get("label", "")) in skip_labels:
            continue
        kind, choice = res
        if login_wall and kind not in ("cookie", "close"):
            continue
        key = (KIND_PRIORITY[kind], CHOICE_PRIORITY.get(choice, 0), 0 if c.get("overlay") else 1)
        if best_key is None or key < best_key:
            best, best_key = (i, kind, choice), key
    return best


_MULTI_PART_SUFFIXES = {
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "com.au", "net.au", "org.au", "co.jp",
    "co.nz", "co.in", "co.za", "co.kr", "com.br", "com.mx", "com.cn", "com.tr", "com.sg",
    "com.hk", "com.ar", "com.co", "com.tw", "com.my", "com.ph", "co.id", "com.vn",
}


def site_of(host: str | None) -> str:
    """Rough registrable domain ('news.bbc.co.uk' -> 'bbc.co.uk'). IP literals stay whole."""
    host = (host or "").lower().rstrip(".")
    if not host or re.fullmatch(r"[\d.]+|\[?[0-9a-f:]+\]?", host):
        return host
    parts = host.split(".")
    n = 3 if len(parts) >= 3 and ".".join(parts[-2:]) in _MULTI_PART_SUFFIXES else 2
    return ".".join(parts[-n:])


def same_site(host_a: str | None, host_b: str | None) -> bool:
    return bool(host_a) and site_of(host_a) == site_of(host_b)


BOT_TEXT = re.compile(
    r"verify (that )?you are (a )?human|verifying you are human|i'?m not a robot|i am not a robot"
    r"|checking your browser|checking if the site connection is secure|are you a robot"
    r"|are you (a )?human|prove (that )?you'?re (a )?human|confirm (that )?you are (a )?human"
    r"|human verification|press (and|&) hold|complete the security check|bot detection"
    r"|ddos protection by|needs to review the security of your connection"
    r"|performing security verification|verif(y|ies) (that )?you are not a (bot|robot)"
    r"|no soy un robot|verifica que eres (un )?humano|je ne suis pas un robot"
    r"|vérifiez que vous êtes (un )?humain")
BOT_TITLE = re.compile(r"^just a moment|^attention required|^one more step|^security check"
                       r"|^verify you are human|^are you a robot|^access denied|^ddos-guard")
BOT_GATE_TEXT = 2500   # a visible robot check on a page with less text than this "gates" it
BOT_TEXT_SHORT = 1500  # robot-check wording only counts on a page this short (or in the title)


def captcha_frame_kind(src: str) -> str | None:
    """Which robot check an iframe URL belongs to, if it is a visible-challenge frame."""
    u = urlparse(src or "")
    host, path, rest = (u.hostname or "").lower(), u.path.lower(), (u.query + "#" + u.fragment).lower()
    if host == "challenges.cloudflare.com" or host.endswith(".challenges.cloudflare.com"):
        return "turnstile"
    if host == "hcaptcha.com" or host.endswith(".hcaptcha.com"):
        return None if "invisible" in rest else "hcaptcha"
    if (host.endswith("google.com") or host.endswith("recaptcha.net")) and "/recaptcha/" in path:
        return None if "size=invisible" in rest else "recaptcha"   # v3 badge = invisible
    return None


def detect_bot_check(state: dict | None) -> dict:
    """{"detected", "kind"} from DETECT_JS facts. Detected = the page is mostly a robot check:
    a visible reCAPTCHA/hCaptcha/Turnstile frame on a short page, a Cloudflare challenge page,
    or robot-check wording in the title / on a short page. Never clicked, never solved."""
    none = {"detected": False, "kind": None}
    if not isinstance(state, dict):
        return none
    text_len = int(state.get("text_len") or 0)
    if set(state.get("markers") or []) & {"cf_challenge", "cf_chl_opt"}:
        return {"detected": True, "kind": "turnstile"}
    if text_len < BOT_GATE_TEXT:
        for f in state.get("iframes") or []:
            kind = captcha_frame_kind(f.get("src", ""))
            if kind and f.get("visible"):
                return {"detected": True, "kind": kind}
    title = norm_label(state.get("title") or "")
    text = (state.get("text") or "")[:BOT_TEXT_SHORT].lower().replace("’", "'")
    if BOT_TITLE.search(title) or BOT_TEXT.search(title) or (
            text_len < BOT_TEXT_SHORT and BOT_TEXT.search(text)):
        return {"detected": True, "kind": "text"}
    return none


SIGNIN = re.compile(r"\b(sign[\s-]?in|log[\s-]?in|log[\s-]?on)\b|iniciar? sesi[oó]n|inicia sesi[oó]n"
                    r"|connexion|se connecter|identifiez-vous|anmelden")
LOGIN_SHORT_TEXT = 2000


def detect_login_wall(state: dict | None) -> bool:
    """True if a password box is visible, or the page is mostly a sign-in form (an email/user
    box plus 'Sign in'/'Log in' wording on a short page). Nothing is ever typed into it."""
    if not isinstance(state, dict):
        return False
    if int(state.get("password_visible") or 0) > 0:
        return True
    return bool(state.get("user_field_visible")
                and SIGNIN.search((state.get("signin_text") or "").lower())
                and int(state.get("text_len") or 0) < LOGIN_SHORT_TEXT)


def clip_label(label: str) -> str:
    return re.sub(r"\s+", " ", str(label or "")).strip()[:MAX_LABEL]


# Facts for detect_bot_check / detect_login_wall, from the main frame. Robot-check widgets live
# in cross-site iframes: we only look at the <iframe> element (src, size), never inside it.
DETECT_JS = r"""
() => {
  const vis = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8 || r.bottom < -50 || r.right < -50) return false;
    return el.checkVisibility ? el.checkVisibility({opacityProperty: true, visibilityProperty: true}) : true;
  };
  const iframes = [...document.querySelectorAll('iframe')].slice(0, 40).map(f => {
    const r = f.getBoundingClientRect();
    return {src: (f.src || '').slice(0, 300), visible: vis(f), top: Math.round(r.top + scrollY),
            w: Math.round(r.width), h: Math.round(r.height)};
  });
  const markers = [];
  const SEL = {'#challenge-form': 'cf_challenge', '#challenge-stage': 'cf_challenge',
               '#challenge-running': 'cf_challenge', '#cf-challenge-running': 'cf_challenge',
               '.cf-browser-verification': 'cf_challenge'};
  for (const [s, name] of Object.entries(SEL)) if (document.querySelector(s)) markers.push(name);
  if (window._cf_chl_opt) markers.push('cf_chl_opt');
  const inputs = [...document.querySelectorAll('input, textarea')].slice(0, 200);
  const USER = /mail|user|login|account|phone|mobile|identifier/i;
  const password_visible = inputs.filter(e => e.type === 'password' && vis(e)).length;
  const user_field_visible = inputs.some(e => (e.type === 'email' || e.type === 'tel' ||
      (e.type === 'text' && USER.test([e.name, e.id, e.autocomplete, e.placeholder,
                                       e.getAttribute('aria-label')].join(' ')))) && vis(e));
  const bits = [document.title || ''];
  for (const el of [...document.querySelectorAll('h1, h2, legend, button, [role=button], input[type=submit]')].slice(0, 40))
    if (vis(el)) bits.push((el.innerText || el.value || '').slice(0, 60));
  const body = document.body ? (document.body.innerText || '') : '';
  return {iframes, markers, password_visible, user_field_visible,
          signin_text: bits.join(' | ').slice(0, 600), text: body.slice(0, 2000),
          text_len: body.length, title: (document.title || '').slice(0, 200)};
}
"""

# Visible, short-labelled buttons/links that might be a barrier, with the facts click_kind()
# needs. Returns [facts[], elements[]] so Python can click the chosen element by index.
CANDIDATES_JS = r"""
(maxCands) => {
  const COARSE = /accept|agree|allow|reject|decline|deny|refuse|necessar|essential|continu|proceed|\bskip|close|dismiss|thank|not now|\blater\b|got it|\bok\b|okay|understand|\bhide\b|\benter\b|\b1[89]\b|\b21\b|older|\bover\b|legal|adult|\bage\b|\byes\b|\bhere\b|redirect|\blink\b|go now|go to|visit|take me|consent|acept|acuerdo|rechaz|omitir|saltar|cerrar|gracias|ahora no|entend|ir al|proceder|entrar|mayor|accepter|refuser|continuer|passer|fermer|merci|compris|entrer|accord|accéder|ignorer|\bici\b|aquí|majeur|\bans\b|\boui\b|\bs[ií]\b/i;
  const FILLABLE = new Set(['text', 'email', 'password', 'tel', 'number', 'search', 'url', 'date',
      'datetime-local', 'month', 'week', 'time', 'textarea', 'select-one', 'select-multiple']);
  const vis = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4 || r.bottom < 0 || r.right < 0 || r.left > innerWidth) return false;
    if (el.checkVisibility && !el.checkVisibility({opacityProperty: true, visibilityProperty: true})) return false;
    return getComputedStyle(el).pointerEvents !== 'none';
  };
  const overlayNode = (e) => {
    const s = getComputedStyle(e);
    return s.position === 'fixed' || s.position === 'sticky' || e.tagName === 'DIALOG' ||
      /dialog/.test(e.getAttribute('role') || '') || e.getAttribute('aria-modal') === 'true';
  };
  const fillableIn = (root) => !!root && [...root.querySelectorAll('input, textarea, select')]
      .slice(0, 60).some(e => FILLABLE.has(e.type) && vis(e));
  const sel = 'button, a, [role=button], [role=link], input[type=button], input[type=submit], ' +
              '[aria-label], [class*="close" i], [class*="dismiss" i]';
  const facts = [], els = [];
  for (const el of document.querySelectorAll(sel)) {
    if (facts.length >= maxCands) break;
    // Cheap first look (textContent needs no layout), then the visible label.
    const quick = (el.getAttribute('aria-label') || el.textContent || el.value || el.title || '').trim();
    if (!quick || quick.length > 300 || (quick.length > 2 && !COARSE.test(quick))) continue;
    if (!vis(el)) continue;
    const raw = (el.getAttribute('aria-label') || el.innerText || el.value || el.title || '')
        .replace(/\s+/g, ' ').trim();
    if (!raw || raw.length > 80 || (raw.length > 2 && !COARSE.test(raw))) continue;
    let overlay = false, container = el.parentElement || el;
    const attrs = [];
    for (let e = el, d = 0; e && e !== document.body && e !== document.documentElement && d < 10;
         e = e.parentElement, d++) {
      // Left the banner/dialog (lots of text): stop. textContent first, it needs no layout.
      if (e !== el && ((e.textContent || '').length > 8000 || (e.innerText || '').length > 2500)) break;
      attrs.push((e.id || '') + ' ' + (typeof e.className === 'string' ? e.className : ''));
      if (e !== el) container = e;
      if (overlayNode(e)) { overlay = true; break; }
    }
    const r = el.getBoundingClientRect();
    if (!overlay && r.top > innerHeight * 1.5) continue;     // far down the page: not a barrier
    const form = el.form || el.closest('form');
    const submits = !!form && (el.type === 'submit' || el.type === 'image');
    facts.push({label: raw, tag: el.tagName.toLowerCase(), type: String(el.type || '').slice(0, 20),
                href: (el.getAttribute('href') || '').slice(0, 300),
                abs_href: (typeof el.href === 'string' ? el.href : '').slice(0, 300),
                download: el.hasAttribute('download'), overlay, top: Math.round(r.top),
                submits_fillable_form: submits && fillableIn(form),
                fillable_ctx: fillableIn(container) || (!!form && fillableIn(form)),
                ctx_text: (container.innerText || '').slice(0, 600),
                ctx_attrs: attrs.join(' ').slice(0, 300)});
    els.push(el);
  }
  return [facts, els];
}
"""


def page_state(page) -> dict | None:
    """DETECT_JS facts for the main frame; None if the page is mid-navigation and won't answer."""
    state = None
    for _ in range(2):
        try:
            state = page.evaluate(DETECT_JS)
            break
        except Exception:
            try:
                page.wait_for_load_state("domcontentloaded", timeout=2000)
            except Exception:
                pass
    if state is not None:
        state["iframes"] = (state.get("iframes") or []) + _captcha_frames(page)
    return state


def _captcha_frames(page) -> list[dict]:
    """Robot-check iframes from Playwright's own frame list: Turnstile puts its iframe in a
    shadow root, where DETECT_JS's querySelectorAll can't see it. Only the size is read."""
    found = []
    for fr in page.frames[:40]:
        try:
            if fr == page.main_frame or not captcha_frame_kind(fr.url):
                continue
            box = fr.frame_element().bounding_box()
            visible = bool(box and box["width"] >= 8 and box["height"] >= 8
                           and fr.frame_element().is_visible())
            found.append({"src": fr.url[:300], "visible": visible,
                          "w": int(box["width"]) if box else 0, "h": int(box["height"]) if box else 0})
        except Exception:
            continue
    return found


def _click_frames(page) -> list:
    """The main frame plus visible same-site iframes. Cross-site frames (ads, consent vendors,
    robot checks) are never clicked into."""
    frames, host = [page.main_frame], urlparse(page.url).hostname
    for fr in page.frames:
        if fr == page.main_frame or len(frames) > MAX_CLICK_FRAMES:
            continue
        try:
            u = urlparse(fr.url)
            if fr.is_detached() or u.scheme not in ("http", "https") or not same_site(u.hostname, host):
                continue
            el = fr.frame_element()
            if el.is_visible():
                frames.append(fr)
        except Exception:
            continue
    return frames


def _settle_after_click(page, deadline: float) -> None:
    left_ms = int((deadline - time.monotonic()) * 1000)
    try:
        page.wait_for_load_state("domcontentloaded", timeout=max(500, min(3000, left_ms)))
    except Exception:
        pass
    page.wait_for_timeout(CLICK_SETTLE_MS)


def new_click_state() -> dict:
    """Shared by the click-past passes of one scan: CLICK_ROUNDS and CLICK_BUDGET_S in total."""
    return {"clicked": [], "done": set(), "rounds": 0, "waited": False,
            "deadline": time.monotonic() + CLICK_BUDGET_S}


def click_past(page, stream: bool, popup_sink: dict, cp: dict | None = None) -> list[dict]:
    """Click harmless barriers, one per round. Stops at once on a robot check. Never types.
    Popups a click opens are recorded on that click (popup_sink), not in `popups`.
    A page that breaks mid-click keeps what was clicked so far; the scan carries on."""
    cp = cp if cp is not None else new_click_state()
    try:
        _click_rounds(page, stream, popup_sink, cp)
    except Exception:
        pass
    finally:
        popup_sink.update(on=False)
    return cp["clicked"]


def _click_rounds(page, stream: bool, popup_sink: dict, cp: dict) -> None:
    clicked, done, deadline = cp["clicked"], cp["done"], cp["deadline"]
    while cp["rounds"] < CLICK_ROUNDS and time.monotonic() < deadline:
        state = page_state(page)
        bot = detect_bot_check(state)
        interstitial = bot["kind"] == "text" or bool(
            set((state or {}).get("markers") or []) & {"cf_challenge", "cf_chl_opt"})
        if bot["detected"] and interstitial and not cp["waited"]:
            cp["waited"] = True         # "Just a moment...": give it one chance to clear itself
            page.wait_for_timeout(CHALLENGE_WAIT_MS)
            state = page_state(page)
            bot = detect_bot_check(state)
        if bot["detected"]:
            break                       # never interact with a robot check
        login = detect_login_wall(state)
        handles, facts, where = [], [], []
        for fr in _click_frames(page):
            try:
                h = fr.evaluate_handle(CANDIDATES_JS, MAX_CANDIDATES)
                fr_facts = h.evaluate("x => x[0]")
            except Exception:
                continue
            handles.append(h)
            for j, f in enumerate(fr_facts):
                facts.append(f)
                where.append((h, j))
        pick = choose_click(facts, login_wall=login, skip_labels=done)
        if pick is None:
            for h in handles:
                _dispose(h)
            break
        cp["rounds"] += 1
        i, kind, choice = pick
        h, j = where[i]
        label = clip_label(facts[i]["label"])
        done.add(norm_label(facts[i]["label"]))
        before = page.url
        popup_sink.update(on=True, urls=[])
        ok = False
        try:
            el = h.evaluate_handle("(x, j) => x[1][j]", j).as_element()
            try:
                el.click(timeout=CLICK_TIMEOUT_MS)
                ok = True
            except Exception:
                el.evaluate("e => e.click()")   # e.g. a transparent layer over the button
                ok = True
        except Exception:
            ok = page.url != before             # the click navigated before we heard back
        if ok:
            entry = {"label": label, "kind": kind}
            if choice:
                entry["choice"] = choice
            clicked.append(entry)
            if stream:
                _emit({"type": "step", "text": f"Clicked “{label}”"})
            _settle_after_click(page, deadline)
            if popup_sink["urls"]:
                entry["popups"] = popup_sink["urls"][:3]
        popup_sink.update(on=False)
        for hh in handles:
            _dispose(hh)


def _dispose(handle) -> None:
    try:
        handle.dispose()
    except Exception:
        pass


def _now_ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


# Same throwaway phone browser for scans and operator mode.
BROWSER_ARGS = ["--disable-dev-shm-usage", "--dns-prefetch-disable",
                "--disable-background-networking", "--no-pings",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--webrtc-ip-handling-policy=disable_non_proxied_udp"]
CONTEXT_OPTS = dict(accept_downloads=False, java_script_enabled=True, service_workers="block",
                    viewport={"width": 390, "height": 844}, device_scale_factor=2,  # phone-sized, sharp on FaceTime
                    is_mobile=True, has_touch=True)


def _launch(p, on_route, **extra_opts):
    """Browser + context with every request (popups and iframes too) going through on_route."""
    browser = p.chromium.launch(
        chromium_sandbox=os.environ.get("CHROMIUM_SANDBOX") == "1",
        executable_path=os.environ.get("CHROMIUM_PATH") or None,   # local testing only
        args=BROWSER_ARGS)
    context = browser.new_context(**{**CONTEXT_OPTS, **extra_opts})
    context.route("**/*", on_route)   # context-wide: also covers popups and iframes
    try:
        # A routed WebSocket never reaches the server unless the handler calls
        # connect_to_server(), so a no-op handler blocks them all. (Calling ws.close() in
        # here deadlocked the sync API at 100% CPU on some pages, e.g. Cloudflare checks.)
        context.route_web_socket("**/*", lambda ws: None)
    except AttributeError:            # older Playwright: no WebSocket routing
        pass
    return browser, context


def start_screencast(context, page, t0: float, pace: dict) -> bool:
    """Chrome's own screen stream (CDP screencast): a new JPEG whenever the page changes, printed
    as {"type":"frame",...} lines that the sandbox server forwards live. ``pace`` is
    {"gap": min seconds between frames, "max": frame cap}; the caller may change "gap" later.
    False if the screencast couldn't start."""
    # Chrome only sends a frame when the page changes, so a frame dropped for coming too soon
    # may be the last one (a tapped button, then nothing moves). Keep the newest dropped frame
    # and send it once the gap has passed, unless a newer frame went out first.
    sent = {"n": 0, "last": 0.0, "pending": None, "timer": None}
    lock = threading.Lock()
    cdp = context.new_cdp_session(page)

    def send(data: str) -> None:              # with lock held
        sent["n"] += 1
        sent["last"] = time.monotonic()
        _emit({"type": "frame", "jpeg": data, "t_ms": _now_ms(t0)})

    def flush() -> None:
        with lock:
            data, sent["pending"], sent["timer"] = sent["pending"], None, None
            if data is not None and sent["n"] < pace["max"]:
                send(data)

    def on_frame(ev) -> None:
        try:
            cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
        except Exception:
            pass
        with lock:
            if sent["n"] >= pace["max"]:
                return
            wait = pace["gap"] - (time.monotonic() - sent["last"])
            if wait <= 0:
                sent["pending"] = None
                send(ev["data"])
                return
            sent["pending"] = ev["data"]
            if sent["timer"] is None:
                timer = threading.Timer(wait, flush)
                timer.daemon = True
                sent["timer"] = timer
                timer.start()

    cdp.on("Page.screencastFrame", on_frame)
    try:
        cdp.send("Page.startScreencast", {"format": "jpeg", "quality": STREAM_QUALITY,
                                          "maxWidth": 540, "maxHeight": 1170,
                                          "everyNthFrame": 1})
        return True
    except Exception:
        return False


def scan(url: str, stream: bool = False) -> dict:
    t0 = time.monotonic()
    out = {"url": url, "final_url": None, "domain": None, "redirect_chain": [],
           "status_codes": [], "page_title": None, "page_text": "", "hidden_text": "",
           "hidden_text_items": [], "form_fields": [], "downloads": [], "popups": [],
           "blocked_requests": [], "screenshots": [], "timings": {}, "error": None,
           "clicked": [], "bot_check": {"detected": False, "kind": None}, "login_wall": False}
    guard = CachingGuard()

    ok, reason = guard.check(url)
    if not ok:
        out["error"] = f"blocked: {reason}"
        out["blocked_requests"].append({"url": url[:300], "reason": reason, "type": "document"})
        out["timings"]["total_ms"] = _now_ms(t0)
        return out

    counters = {"requests": 0, "nav": 0}
    popup_sink = {"on": False, "urls": []}   # popups opened by OUR clicks, kept apart

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

    from playwright.sync_api import sync_playwright   # here so tests can import the helpers

    with sync_playwright() as p:
        browser, context = _launch(p, on_route)
        page = context.new_page()
        out["timings"]["browser_ready_ms"] = _now_ms(t0)

        def on_nav(frame) -> None:
            if frame == page.main_frame and frame.url != "about:blank":
                if out["redirect_chain"] and out["redirect_chain"][-1] == frame.url:
                    return      # the same page announcing itself again is not a new hop
                out["redirect_chain"].append(frame.url)
                if stream:
                    _emit({"type": "nav", "url": frame.url[:300]})

        if stream:
            # no screencast: the scan still works, just without frames
            stream = start_screencast(context, page, t0,
                                      {"gap": STREAM_MIN_GAP_S, "max": STREAM_MAX_FRAMES})

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
            (popup_sink["urls"] if popup_sink["on"] else out["popups"]).append(pg.url[:300])
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
            cp = new_click_state()
            out["clicked"] = cp["clicked"]           # filled in place by each pass
            click_past(page, stream, popup_sink, cp)
            out["timings"]["clicked_ms"] = _now_ms(t0)
            if stream:
                # A slow look down the page so the caller sees it move, then back to the top
                # for the screenshot. Scrolling never clicks or types anything.
                for _ in range(3):
                    page.mouse.wheel(0, 320)
                    page.wait_for_timeout(450)
                page.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")
                page.wait_for_timeout(300)
                click_past(page, stream, popup_sink, cp)   # pop-ups that showed up meanwhile
        except Exception as e:                   # timeouts, DNS failures, blocked requests
            out["error"] = str(e).splitlines()[0][:300]

        out["final_url"] = page.url
        out["domain"] = urlparse(page.url).hostname
        state = page_state(page)
        out["bot_check"] = detect_bot_check(state)
        out["login_wall"] = detect_login_wall(state)
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


# ---------- operator mode (run_scan.py --operate): NOT a scan, see operate.py ----------
#
# Drives the made-up official Dogwood Parking app on our own demo site for a person who linked
# their Dogwood account: Install -> Open -> type the plate -> tap hours-N -> tap Pay (which only
# asks for approval in ScanSafe) -> watch for the receipt. Only fixed data-testid selectors are
# clicked and only the checked plate is typed. Scans never come through here.

OPERATE_WAIT_S = 120.0       # after tapping Pay: watch this long for the receipt
OPERATE_MAX_REQUESTS = 600   # the app polls the ScanSafe API every 1.5 s
OPERATE_STEP_MS = 15000      # each selector wait / click
OPERATE_WAIT_GAP_S = 0.5     # ~2 frames/s while only waiting for approval (keeps the stream small)
OPERATE_MAX_FRAMES = 900
TYPE_DELAY_MS = 90           # typed one key at a time so the caller sees it happen


class OperateError(Exception):
    """A step that can't go on; the message goes into the result's ``error``."""


def operate(url: str, plate: str, hours: int | None) -> dict:
    t0 = time.monotonic()
    out = {"mode": "operate", "url": url, "final_url": None, "plate": None, "hours": None,
           "status": "failed", "paid": False, "steps": [], "error": None,
           "blocked_requests": [], "screenshots": [], "timings": {}}
    ok, why = operate_url_allowed(url)
    plan = plan_steps(url) if ok else ()
    clean, h = clean_plate(plate), valid_hours(hours)
    if not ok or not plan or clean is None or h is None:
        out["error"] = "blocked: " + (why if not ok else "not a Dogwood install or app page" if not plan
                                      else "bad plate" if clean is None else "bad hours")
        out["timings"]["total_ms"] = _now_ms(t0)
        return out
    out["plate"], out["hours"] = clean, h
    guard = CachingGuard()
    ok, why = guard.check(url)
    if not ok:
        out["error"] = f"blocked: {why}"
        out["timings"]["total_ms"] = _now_ms(t0)
        return out

    counters = {"requests": 0}
    done: list[str] = out["steps"]
    phase = "unknown"

    def block(route, req_url: str, why: str, stay: bool) -> None:
        if len(out["blocked_requests"]) < MAX_BLOCKED:
            out["blocked_requests"].append({"url": req_url[:300], "reason": why,
                                            "type": route.request.resource_type})
        if stay:
            route.fulfill(status=204, body="")   # a page we won't open: stay where we are
        else:
            route.abort("blockedbyclient")

    def on_route(route) -> None:
        req = route.request
        counters["requests"] += 1
        if counters["requests"] > OPERATE_MAX_REQUESTS:
            return block(route, req.url, "request budget exceeded", stay=False)
        if req.url.startswith(("data:", "blob:")):
            return route.continue_()
        try:
            top_nav = req.is_navigation_request() and req.frame.parent_frame is None
        except Exception:
            top_nav = False
        allowed, why = operate_request_allowed(req.url, top_nav)
        if allowed:
            allowed, why = guard.check(req.url)   # the usual network guard, every request
        if not allowed:
            return block(route, req.url, why, stay=top_nav)
        route.continue_()

    def say_step(name: str) -> None:
        _emit({"type": "step", "text": step_text(name, clean, h), "step": name})

    def mark(name: str) -> None:
        done.append(name)
        out["timings"][f"{name}_ms"] = _now_ms(t0)

    def current_phase() -> str:
        try:
            return page_phase(page.evaluate(PHASE_JS))
        except Exception:      # mid-navigation
            return "unknown"

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser, context = _launch(p, on_route)
        page = context.new_page()
        out["timings"]["browser_ready_ms"] = _now_ms(t0)
        pace = {"gap": STREAM_MIN_GAP_S, "max": OPERATE_MAX_FRAMES}
        start_screencast(context, page, t0, pace)
        last_nav = {"url": ""}

        def on_nav(frame) -> None:
            if frame == page.main_frame and frame.url not in ("about:blank", last_nav["url"]):
                last_nav["url"] = frame.url
                _emit({"type": "nav", "url": frame.url[:300]})

        def on_download(d) -> None:
            try:
                d.cancel()
            except Exception:
                pass

        def on_popup(pg) -> None:
            try:
                pg.close()
            except Exception:
                pass

        page.on("framenavigated", on_nav)
        page.on("download", on_download)
        page.on("popup", on_popup)

        try:
            say_step("open")
            page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            mark("open")
            if "install" in plan:
                page.wait_for_selector(OP_SEL["install"], state="visible", timeout=OPERATE_STEP_MS)
                page.wait_for_timeout(800)                    # let the caller see the store page
                say_step("install")
                page.click(OP_SEL["install"], timeout=OPERATE_STEP_MS)
                mark("install")
                page.wait_for_selector(OP_SEL["open"], state="visible", timeout=OPERATE_STEP_MS)
                page.wait_for_timeout(500)
                say_step("open_app")
                page.click(OP_SEL["open"], timeout=OPERATE_STEP_MS)
                page.wait_for_url(lambda u: plan_steps(u) == STEPS_FROM_APP,
                                  wait_until="domcontentloaded", timeout=TIMEOUT_MS)
                if not operate_url_allowed(page.url)[0]:
                    raise OperateError("Open didn't lead to the Dogwood app")
                mark("open_app")
            app_ready = ", ".join(OP_SEL[k] for k in ("plate", "waiting", "receipt", "no_session"))
            page.wait_for_selector(app_ready, state="visible", timeout=OPERATE_STEP_MS)
            phase = current_phase()
            if phase == "waiting":
                # Already waiting from an earlier run (the hours changed): back to the form.
                page.click(OP_SEL["change"], timeout=OPERATE_STEP_MS)
                page.wait_for_selector(OP_SEL["plate"], state="visible", timeout=OPERATE_STEP_MS)
                phase = current_phase()
            if phase == "no_session":
                raise OperateError("the Dogwood app says this session isn't valid")
            if phase == "app":
                say_step("plate")
                box = page.locator(OP_SEL["plate"])
                box.click(timeout=OPERATE_STEP_MS)
                box.fill("", timeout=OPERATE_STEP_MS)
                box.press_sequentially(clean, delay=TYPE_DELAY_MS, timeout=OPERATE_STEP_MS)
                if box.input_value().strip().upper() != clean:
                    raise OperateError("the plate didn't go in as typed")
                mark("plate")
                page.wait_for_timeout(400)
                say_step("hours")
                page.click(hours_selector(h), timeout=OPERATE_STEP_MS)
                mark("hours")
                page.wait_for_timeout(900)                    # total updates, the caller sees it
                say_step("pay")
                page.click(OP_SEL["pay"], timeout=OPERATE_STEP_MS)
                page.wait_for_selector(f'{OP_SEL["waiting"]}, {OP_SEL["receipt"]}', state="visible",
                                       timeout=OPERATE_STEP_MS)
                mark("pay")
            if phase != "paid":
                say_step("wait")
                pace["gap"] = OPERATE_WAIT_GAP_S
                deadline = time.monotonic() + OPERATE_WAIT_S
                while time.monotonic() < deadline:
                    phase = current_phase()
                    if phase in ("paid", "no_session"):
                        break
                    page.wait_for_timeout(500)
            if phase == "no_session":
                raise OperateError("the Dogwood session ended")
            if phase == "paid":
                pace["gap"] = STREAM_MIN_GAP_S
                say_step("paid")
                mark("paid")
                page.wait_for_timeout(1500)                   # let the receipt reach the stream
        except OperateError as e:
            out["error"] = str(e)
        except Exception as e:                                # timeouts, blocked page, crash
            out["error"] = str(e).splitlines()[0][:300] if str(e) else type(e).__name__
        out["final_url"] = page.url
        try:
            shot = page.screenshot(full_page=False, type="jpeg", quality=SHOT_QUALITY, timeout=5000)
            out["screenshots"].append("data:image/jpeg;base64," + base64.b64encode(shot).decode())
        except Exception:
            pass
        browser.close()
    out["status"] = operate_status(done, phase, out["error"])
    out["paid"] = out["status"] == "paid"
    out["timings"]["total_ms"] = _now_ms(t0)
    return out


# ---------- ParkMobile adapter (run_scan.py --operate-parkmobile): the REAL site, see operate.py ----
#
# [saved session, if mounted] open -> type the zone -> pick it -> "Park here" -> then, screen by
# screen: duration, vehicle / plate, the forward button, until a stop screen: sign-in / email / code
# (needs_sign_in / needs_verification), payment, price review or a refused pay button
# (ready_to_pay), robot check (robot_check). Every click goes through pm_click (never pay-like
# labels) and every keystroke through pm_type (only the zone or plate, never card / email / phone
# fields). It never signs in, never pays, never accepts terms, never writes the session back.

PM_MAX_REQUESTS = 700
PM_STEP_MS = 15000
PM_ROUNDS = 8                # screens looked at after "Park here"
PM_SETTLE_MS = 2500
PM_MAX_FRAMES = 600
PM_STEPPER_MAX = 16          # taps on a "+" duration stepper
# A phone browser, not "HeadlessChrome": same Chromium, ordinary mobile Chrome user agent. The
# Mac session capture must use the same user agent and CONTEXT_OPTS.
PM_USER_AGENT = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
                 "Chrome/140.0.0.0 Mobile Safari/537.36")
PM_LABEL_JS = r"""
el => [el.innerText || '', el.getAttribute('aria-label') || '', el.getAttribute('title') || '',
       el.getAttribute('value') || '', el.getAttribute('data-testid') || ''].join(' ').slice(0, 300)
"""
PM_ATTRS_JS = r"""
el => ({type: (el.getAttribute('type') || '').toLowerCase(), name: el.getAttribute('name') || '',
        id: el.id || '', autocomplete: (el.getAttribute('autocomplete') || '').toLowerCase(),
        aria: el.getAttribute('aria-label') || '', placeholder: el.getAttribute('placeholder') || '',
        testid: el.getAttribute('data-testid') || '',
        label: ((el.labels && el.labels[0] && el.labels[0].innerText) || '').slice(0, 60)})
"""
PM_LINES_JS = "() => document.body.innerText.split('\\n').map(s => s.trim()).filter(Boolean).slice(0, 200)"
PM_OPTIONS_JS = "el => [...el.options].slice(0, 100).map(o => (o.label || o.textContent || '').trim())"
PM_PICKED_JS = r"""
el => ['aria-checked', 'aria-selected', 'aria-pressed'].some(a => el.getAttribute(a) === 'true')
"""
# The forward button: an exact allowlist (pm_forward_ok), only while no price is on screen.
PM_FORWARD = re.compile(r"^\s*(continue|next)\s*$", re.I)
PM_BUTTON_JS = r"""
el => ({text: (el.innerText || '').trim().slice(0, 80), aria: (el.getAttribute('aria-label') || '').trim().slice(0, 80)})
"""
PM_VEHICLE_OPENER = re.compile(r"^\s*(add (a )?(new )?vehicle|select (a )?vehicle|choose (a )?vehicle"
                               r"|change vehicle|vehicle)\b", re.I)
PM_HARD_STOPS = ("robot_check", "verification", "sign_in", "unsupported", "space_number")


class GuardRefused(OperateError):
    """pm_click / pm_type refused an action."""


def pm_click(locator, refused: list, timeout: int = PM_STEP_MS) -> str:
    """Click ``locator`` unless its label looks like pay / purchase / checkout / confirm / start
    parking / buy / submit / agree / sign in / card. Refusals are recorded and raise."""
    label = locator.evaluate(PM_LABEL_JS, timeout=timeout)
    if pm_click_refused(label):
        refused.append({"action": "click", "label": clip_label(label)})
        raise GuardRefused(f"refused to click {clip_label(label)!r}")
    locator.click(timeout=timeout)
    return label


def pm_type(locator, value: str, zone: str | None, plate: str | None, refused: list,
            timeout: int = PM_STEP_MS) -> None:
    """Type ``value`` (only ever the checked zone or plate) unless the field looks like a card,
    password, email, phone or other personal field."""
    attrs = locator.evaluate(PM_ATTRS_JS, timeout=timeout)
    if not pm_type_value_ok(value, zone, plate) or pm_type_refused(attrs):
        refused.append({"action": "type", "field": clip_label(" ".join(
            str(attrs.get(k) or "") for k in ("type", "name", "id", "aria")) if isinstance(attrs, dict) else "")})
        raise GuardRefused("refused to type into that field")
    locator.click(timeout=timeout)
    locator.fill("", timeout=timeout)
    locator.press_sequentially(value, delay=TYPE_DELAY_MS, timeout=timeout)


def load_pm_state(path: str | None = None) -> tuple[dict | None, list, str]:
    """The saved ParkMobile session server.py mounted read-only: (storage_state with cookies +
    origins incl. indexedDB, filtered to *.parkmobile.io; sessionStorage items for
    https://app.parkmobile.io; "loaded"), or (None, [], "none" | "unreadable" | "unusable").
    Its contents are never printed, and it is never written back."""
    path = path or PM_STATE_PATH
    if not os.path.exists(path):
        return None, [], "none"
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return None, [], "unreadable"
    state, items = pm_filter_state(raw), pm_session_items(raw)
    return (state, items, "loaded") if state or items else (None, [], "unusable")


def _pm_norm(s: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def _pm_plate_box(page):
    """The visible plate / licence box, if it passes pm_type_refused; else None."""
    for box in page.locator("input:visible").all()[:20]:
        attrs = box.evaluate(PM_ATTRS_JS)
        blob = " ".join(str(v) for v in attrs.values()) if isinstance(attrs, dict) else ""
        if re.search(r"plate|licen[cs]e|vehicle", blob, re.I) and not pm_type_refused(attrs):
            return box
    return None


def _pm_shows(page, pats: list) -> bool:
    return any(p.search(line) for line in page.evaluate(PM_LINES_JS) for p in pats)


def _pm_set_duration(page, minutes: int, refused: list, fence=lambda: False) -> bool:
    """Pick ``minutes`` on whatever duration control is showing (all guarded): a chip / option /
    radio with that duration, a <select> (or an hours <select>), or a "+" stepper tapped until the
    page shows it. False if there's no such control. UNVERIFIED on the signed-in site."""
    pats = pm_duration_patterns(minutes)
    chips = page.locator("button:visible, [role=option]:visible, [role=radio]:visible, "
                         "[role=tab]:visible, label:visible")
    for pat in pats:
        loc = chips.filter(has_text=pat)
        if loc.count():
            pm_click(loc.first, refused)
            return True
    for sel in page.locator("select:visible").all()[:6]:
        attrs = sel.evaluate(PM_ATTRS_JS)
        if pm_type_refused(attrs):
            continue
        options = sel.evaluate(PM_OPTIONS_JS) or []
        want = next((o for o in options for pat in pats if pat.search(o)), None)
        blob = " ".join(str(v) for v in attrs.values()) if isinstance(attrs, dict) else ""
        if want is None and minutes % 60 == 0 and re.search(r"hour|\bhrs?\b", blob, re.I):
            want = next((o for o in options if o == str(minutes // 60)), None)
        if want is not None:
            sel.select_option(label=want, timeout=PM_STEP_MS)
            return True
    plus = page.locator("button:visible").filter(has_text=re.compile(r"^\s*\+\s*$"))
    if not plus.count():
        plus = page.locator('button[aria-label*="increase" i]:visible, button[aria-label*="add time" i]:visible')
    if plus.count():
        for _ in range(PM_STEPPER_MAX + 1):
            if _pm_shows(page, pats):
                return True
            if fence():                                 # a price showed up: no more taps
                return False
            pm_click(plus.first, refused)
            page.wait_for_timeout(250)
    return False


def _pm_set_plate(page, plate: str, zone: str | None, refused: list) -> str | None:
    """"picked" (tapped the saved vehicle with this plate), "shown" (it's already the chosen one),
    "typed" (into the plate box), "opened" (opened the vehicle chooser / Add vehicle), or None.
    UNVERIFIED on the signed-in site."""
    want = _pm_norm(plate)
    cands = page.locator("button:visible, [role=radio]:visible, [role=option]:visible, "
                         "[role=button]:visible, label:visible, li:visible")
    for el in cands.all()[:60]:
        text = el.inner_text(timeout=2000) or ""
        if want and len(text) <= 80 and want in _pm_norm(text):
            if el.evaluate(PM_PICKED_JS):
                return "shown"
            pm_click(el, refused)
            return "picked"
    box = _pm_plate_box(page)
    if box is not None:
        pm_type(box, plate, zone, plate, refused)
        return "typed"
    if any(want and want == _pm_norm(line) or (want and want in _pm_norm(line) and len(line) <= 40)
           for line in page.evaluate(PM_LINES_JS)):
        return "shown"                                  # e.g. "Vehicle DEMO123" on the review
    opener = page.locator("button:visible, [role=button]:visible, a:visible").filter(has_text=PM_VEHICLE_OPENER)
    if opener.count():
        pm_click(opener.first, refused)
        return "opened"
    return None


PM_PLATE_STATE = ("GA", "Georgia")        # the demo zone is in Atlanta
PM_ADD_VEHICLE = re.compile(r"^\s*add vehicle\s*$", re.I)


def _pm_pick_state(page, refused: list) -> bool:
    """Add vehicle screen (real, signed in, 2026-11-14): Country / License plate / State/province /
    Nickname, then "Add vehicle" (disabled until the state is set). Sets State/province only."""
    code, name = PM_PLATE_STATE
    # Real markup (probed 2026-11-14): button [data-testid=vehicle-form-state-select] opens an
    # action sheet whose options are [data-testid=vehicle-form-state-select-option-<CODE>].
    trigger = page.locator('[data-testid="vehicle-form-state-select"]').filter(visible=True)
    if trigger.count():
        pm_click(trigger.first, refused)
        opt = page.locator(f'[data-testid="vehicle-form-state-select-option-{code}"]')
        try:
            opt.first.wait_for(state="visible", timeout=5000)
        except Exception:   # noqa: BLE001 - sheet didn't open: fall through to the generic ways
            page.keyboard.press("Escape")
        else:
            pm_click(opt.first, refused)
            return True
    # A native <select> (often styled, label drawn on top): the one listing the US states.
    for sel in page.locator("select").all()[:6]:
        try:
            labels = sel.evaluate("el => Array.from(el.options).map(o => [o.value, o.label || o.text])")
        except Exception:   # noqa: BLE001
            continue
        for value, label in labels or []:
            if str(value).strip().upper() in (code, f"US-{code}") or str(label).strip().lower() in (name.lower(), code.lower()):
                try:
                    sel.select_option(value=value, timeout=3000, force=True)
                    return True
                except Exception:   # noqa: BLE001
                    break
    box = page.get_by_role("combobox", name=re.compile(r"state|province", re.I)).filter(visible=True)
    if not box.count():
        box = page.get_by_text(re.compile(r"^\s*State\s*/\s*province\s*$", re.I)).filter(visible=True)
    if not box.count():
        return False
    try:
        pm_click(box.first, refused)
    except GuardRefused:
        raise
    except Exception:   # noqa: BLE001 - label drawn over the real control: give up on the state
        return False
    page.wait_for_timeout(600)
    want = re.compile(rf"^\s*({name}|{code})(\s*\(?{code}\)?)?\s*$", re.I)
    for opt in (page.get_by_role("option", name=want), page.get_by_text(want)):
        opt = opt.filter(visible=True)
        if opt.count():
            pm_click(opt.first, refused)
            return True
    page.keyboard.press("Escape")
    return False


def _pm_add_vehicle(page, refused: list) -> bool:
    """On ParkMobile's Add vehicle screen, after the plate is typed: pick the state, then tap the
    exact "Add vehicle" button once it is enabled. Saves the plate to the person's own account
    (no payment). Returns True if "Add vehicle" was tapped."""
    if "/add-vehicle" not in (urlparse(page.url).path or ""):
        return False
    _pm_pick_state(page, refused)
    page.wait_for_timeout(400)
    btn = page.get_by_role("button", name=PM_ADD_VEHICLE).filter(visible=True)
    if btn.count() and btn.first.is_enabled():
        pm_click(btn.first, refused)
        return True
    return False


def _pm_continue(page, refused: list) -> bool:
    """Tap a button labelled exactly Continue or Next (pm_forward_ok, then pm_click). Only called
    while no price is on screen, or on the duration preview (pm_duration_preview), whose Continue
    only goes to "Confirm parking"; re-checked here right before the tap."""
    try:
        if pm_must_stop(page.evaluate(PM_FACTS_JS)):
            return False
    except Exception:   # noqa: BLE001 - can't tell: don't tap
        return False
    for b in page.get_by_role("button", name=PM_FORWARD).filter(visible=True).all()[:4]:
        if pm_forward_ok(b.evaluate(PM_BUTTON_JS)):
            pm_click(b, refused)
            return True
    return False


def operate_parkmobile(url: str, zone: str | None, plate: str, minutes: int | None) -> dict:
    t0 = time.monotonic()
    out = {"mode": "operate", "adapter": "parkmobile", "url": url, "final_url": None,
           "zone": None, "plate": None, "minutes": None, "status": "failed", "paid": False,
           "session": "none", "stopped_at": None, "price_text": None, "zone_name": None,
           "operator": None, "duration_set": False, "plate_set": False, "steps": [],
           "refused": [], "error": None, "blocked_requests": [], "fenced_requests": [],
           "screenshots": [], "timings": {}}
    ok, why = check_parkmobile_request(url, zone, plate, minutes=minutes)
    if not ok:
        out["error"] = f"blocked: {why}"
        out["timings"]["total_ms"] = _now_ms(t0)
        return out
    z, clean, mins = clean_zone(zone), clean_plate(plate), pm_minutes(minutes=minutes)
    out["zone"], out["plate"], out["minutes"] = z, clean, mins
    start = url if pm_area_from_url(url) else PM_ENTRY_URL     # the v2 search page otherwise
    guard = CachingGuard()
    ok, why = guard.check(start)
    if not ok:
        out["error"] = f"blocked: {why}"
        out["timings"]["total_ms"] = _now_ms(t0)
        return out
    state, session_items, out["session"] = load_pm_state()
    counters = {"requests": 0}
    done: list[str] = out["steps"]
    refused: list = out["refused"]
    screen, facts = "unknown", {}

    def block(route, req_url: str, why: str, stay: bool) -> None:
        if len(out["blocked_requests"]) < MAX_BLOCKED:
            out["blocked_requests"].append({"url": pm_clean_url(req_url)[:120], "reason": why,
                                            "type": route.request.resource_type,
                                            "method": route.request.method})
        if stay:
            route.fulfill(status=204, body="")
        else:
            route.abort("blockedbyclient")

    def on_route(route) -> None:
        req = route.request
        counters["requests"] += 1
        if counters["requests"] > PM_MAX_REQUESTS:
            return block(route, req.url, "request budget exceeded", stay=False)
        if req.url.startswith(("data:", "blob:")):
            return route.continue_()
        try:
            top_nav = req.is_navigation_request() and req.frame.parent_frame is None
        except Exception:
            top_nav = False
        if pm_request_blocked(req.method, req.url):      # never start, extend or pay for parking
            if len(out["fenced_requests"]) < MAX_BLOCKED:    # own list: analytics can't crowd it out
                out["fenced_requests"].append({"method": req.method, "url": pm_clean_url(req.url)[:120]})
            if top_nav:
                route.fulfill(status=204, body="")
            else:
                route.abort("blockedbyclient")
            return None
        allowed, why = parkmobile_request_allowed(req.url, top_nav)
        if allowed:
            allowed, why = guard.check(req.url)
        if not allowed:
            return block(route, req.url, why, stay=top_nav)
        route.continue_()

    def say_step(name: str) -> None:
        _emit({"type": "step", "text": pm_step_text(name, z or out["zone"] or "", clean, mins),
               "step": name})

    def mark(name: str) -> None:
        done.append(name)
        out["timings"][f"{name}_ms"] = _now_ms(t0)

    def look(page) -> tuple[str, dict]:
        try:
            f = page.evaluate(PM_FACTS_JS)
        except Exception:
            return "unknown", {}
        robot = detect_bot_check(page_state(page))["detected"]
        return pm_screen(f, robot), (f if isinstance(f, dict) else {})

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        opts = {"user_agent": PM_USER_AGENT, "locale": "en-US"}
        if state:
            opts["storage_state"] = state               # read-only copy; never saved back
        browser, context = _launch(p, on_route, **opts)
        context.add_init_script(script=PM_MASK_EMAIL_JS)  # account email never on the video
        if session_items:     # sessionStorage for https://app.parkmobile.io, passed as JSON data
            context.add_init_script(script=pm_session_script(session_items))
        state = session_items = None
        page = context.new_page()
        out["timings"]["browser_ready_ms"] = _now_ms(t0)
        start_screencast(context, page, t0, {"gap": STREAM_MIN_GAP_S, "max": PM_MAX_FRAMES})
        last_nav = {"url": ""}

        def on_nav(frame) -> None:
            if frame == page.main_frame and frame.url not in ("about:blank", last_nav["url"]):
                last_nav["url"] = frame.url
                _emit({"type": "nav", "url": pm_clean_url(frame.url)})
        page.on("framenavigated", on_nav)
        page.on("download", lambda d: d.cancel())
        page.on("popup", lambda pg: pg.close())

        try:
            if out["session"] == "loaded":
                say_step("session")
            say_step("open")
            page.goto(start, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            mark("open")
            page.wait_for_selector(f'{PM_SEL["search"]}, {PM_SEL["continue"]}', state="attached",
                                   timeout=PM_STEP_MS)
            screen, facts = look(page)
            if screen == "search":
                if z is None:
                    raise OperateError("no zone number to search for")
                page.wait_for_timeout(600)
                say_step("zone")
                pm_type(page.locator(PM_SEL["search"]).first, z, z, clean, refused)
                mark("zone")
                result = page.locator(pm_result_selector(z)).first
                result.wait_for(state="attached", timeout=PM_STEP_MS)
                page.wait_for_timeout(500)
                say_step("pick")
                pm_click(result, refused)
                mark("pick")
                page.wait_for_selector(PM_SEL["continue"], state="attached", timeout=PM_STEP_MS)
                page.wait_for_timeout(800)
                screen, facts = look(page)
            if screen == "zone_details":
                info = pm_zone_info(facts.get("lines"), z)
                if z is not None and info["zone"] != z:
                    raise OperateError("ParkMobile showed a different zone")
                out.update({k: info[k] for k in ("zone", "zone_name", "operator")})
                page.wait_for_timeout(1200)                       # caller sees the zone details
                say_step("park_here")
                pm_click(page.locator(PM_SEL["continue"]).first, refused)
                mark("park_here")
            def fenced() -> bool:
                """Look again; True (and stop) if a stop screen, a price or a payment method is
                showing. After that nothing else is clicked."""
                nonlocal screen, facts
                page.wait_for_timeout(400)
                s2, f2 = look(page)
                if s2 in PM_HARD_STOPS or pm_must_stop(f2):
                    screen = s2 if s2 in PM_HARD_STOPS + ("payment", "review") else "price"
                    facts = f2
                    return True
                return False

            def fence_quick() -> bool:
                try:
                    return pm_must_stop(page.evaluate(PM_FACTS_JS))
                except Exception:
                    return True

            for _ in range(PM_ROUNDS):
                page.wait_for_timeout(PM_SETTLE_MS)
                screen, facts = look(page)
                if screen in PM_HARD_STOPS:
                    break
                if pm_must_stop(facts):                           # hard stop: price / payment
                    if screen not in ("payment", "review"):
                        screen = "price"
                    break
                acted = False
                url_before = page.url
                try:
                    if not out["duration_set"] and _pm_set_duration(page, mins, refused, fence_quick):
                        out["duration_set"] = acted = True
                        say_step("duration")
                        mark("duration")
                        if fenced():
                            break
                    if not out["plate_set"]:
                        how = _pm_set_plate(page, clean, z, refused)
                        if how == "opened":
                            if fenced():
                                break
                            continue                              # the chooser: look again
                        if how in ("picked", "typed", "shown"):
                            out["plate_set"] = True
                            if how != "shown":
                                acted = True
                                say_step("vehicle" if how == "picked" else "plate")
                                mark("plate")
                                if fenced():
                                    break
                            if how == "typed" and _pm_add_vehicle(page, refused):
                                mark("add_vehicle")
                                if fenced():
                                    break
                                continue                          # vehicle saved: look again
                    on_duration = urlparse(page.url).path.rstrip("/") == PM_DURATION_PATH
                    if on_duration and not out["duration_set"] and not acted:
                        acted = True        # the hours couldn't be picked: go on with the default
                    if acted or (out["duration_set"] and out["plate_set"]):
                        page.wait_for_timeout(500)
                        if page.url != url_before:
                            continue        # that tap already moved on (e.g. vehicle -> hours): look first
                        if fenced():
                            break
                        _pm_continue(page, refused)
                except GuardRefused as e:
                    s2, f2 = look(page)
                    facts = f2
                    if s2 in PM_HARD_STOPS + ("payment", "review"):
                        screen = s2
                    elif pm_price_visible(f2):
                        screen = "price"
                    else:
                        screen, out["error"] = "refused", str(e)
                    break
            if screen in ("payment", "review", "price"):
                out["price_text"] = pm_price_text(facts.get("text"))
                say_step("stop_pay")
            elif screen in ("sign_in", "verification") and out["session"] == "loaded":
                say_step("stop_signed_out" if screen == "sign_in" else "stop_verify")
            elif screen in ("sign_in", "verification"):
                say_step("stop_sign_in")
            elif screen == "robot_check":
                say_step("stop_robot")
            out["stopped_at"] = PM_STOPPED_AT.get(screen, f"an unexpected ParkMobile screen ({screen})")
            if screen == "sign_in" and out["session"] == "loaded":
                out["stopped_at"] = "ParkMobile's sign-in screen: the saved sign-in was signed out"
            if screen == "refused":
                out["stopped_at"] = "a button or field the guard refused"
            elif screen not in PM_STOPPED_AT:
                out["error"] = "couldn't reach the price or sign-in screen"
            page.wait_for_timeout(1200)                           # last screen reaches the stream
        except GuardRefused as e:
            out["error"], out["stopped_at"] = str(e), "a button or field the guard refused"
            screen = "failed"
        except OperateError as e:
            out["error"] = str(e)
            screen = "failed"
        except Exception as e:                                    # timeouts, blocked page, crash
            out["error"] = pm_redact_urls(str(e).splitlines()[0][:300] if str(e) else type(e).__name__)
            screen, _ = look(page)
            if screen in ("sign_in", "verification", "robot_check"):
                out["stopped_at"] = PM_STOPPED_AT.get(screen)
            else:
                screen = "failed"
        out["final_url"] = pm_clean_url(page.url)
        try:
            shot = page.screenshot(full_page=False, type="jpeg", quality=SHOT_QUALITY, timeout=5000)
            out["screenshots"].append("data:image/jpeg;base64," + base64.b64encode(shot).decode())
        except Exception:
            pass
        browser.close()
    out["status"] = pm_status(screen)
    if out["status"] == "robot_check":
        out["stopped_at"] = PM_STOPPED_AT["robot_check"]
    out["stopped_at"] = out["stopped_at"] or "an error before the price or sign-in screen"
    if out["status"] == "failed":
        out["error"] = out["error"] or out["stopped_at"]
    out["timings"]["total_ms"] = _now_ms(t0)
    return out


USAGE = ("usage: run_scan.py <url> [--stream] | run_scan.py --operate <url> <plate> <hours>"
         " | run_scan.py --operate-parkmobile <url> <zone|-> <plate> <minutes>")


def main(args: list[str]) -> int:
    if args[:1] == ["--operate-parkmobile"]:
        if len(args) != 5:
            _emit_line(json.dumps({"error": USAGE}))
            return 1
        try:
            minutes = int(args[4])
        except ValueError:
            minutes = None
        try:
            result = operate_parkmobile(args[1], None if args[2] == "-" else args[2], args[3], minutes)
        except Exception:
            _emit_line("null")
            raise
        _emit_line(json.dumps(result))
        return 0
    if args[:1] == ["--operate"]:
        if len(args) != 4:
            _emit_line(json.dumps({"error": USAGE}))
            return 1
        try:
            hours = int(args[3])
        except ValueError:
            hours = None
        try:
            result = operate(args[1], args[2], hours)
        except Exception:
            _emit_line("null")   # never let a "step" line pass for the result
            raise
        _emit_line(json.dumps(result))
        return 0
    stream = "--stream" in args[1:]
    if not args or len(args) > 2 or (len(args) == 2 and not stream) or args[0].startswith("--"):
        _emit_line(json.dumps({"error": USAGE}))
        return 1
    try:
        result = scan(args[0], stream=stream)
    except Exception:
        if stream:
            # server.py keeps the last non-frame/nav JSON line as the result: make sure that
            # is never a "step" line. null = no result, so the scan is reported as failed.
            _emit_line("null")
        raise
    _emit_line(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
