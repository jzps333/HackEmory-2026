"""Pure field-matching logic (no browser): which profile key goes into which form field.

A field descriptor is a dict collected from the page:
  {"tag": "input"|"select"|"textarea", "type", "name", "id", "autocomplete", "label",
   "aria_label", "placeholder", "options": [{"value", "label"}]}

Sensitive fields (card, CVV, SSN, passwords, bank numbers, files) are never touched.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Tuple

# Input types the filler never touches. password/file are also reported as "skipped".
IGNORE_TYPES = {"hidden", "submit", "button", "image", "reset", "checkbox", "radio", "range",
                "color"}
SENSITIVE_TYPES = {"password", "file"}

_SENSITIVE_RE = re.compile(
    r"\b(card|creditcard|debitcard|cardnumber|cvv|cvc|csc|ssn|social security|password|"
    r"passwd|passcode|iban|routing|account|acct|security code|cc (number|num|exp|csc|name|type))")
_SENSITIVE_AC = {"current-password", "new-password", "one-time-code"}

AUTOCOMPLETE_MAP = {
    "name": "name",
    "given-name": "first_name",
    "family-name": "last_name",
    "email": "email",
    "tel": "phone",
    "tel-national": "phone",
    "street-address": "street_address",
    "address-line1": "street_address",
    "address-level2": "city",
    "address-level1": "state",
    "postal-code": "zip",
}
# Standard autocomplete tokens that mean "a known field that is NOT in the profile": no
# keyword guessing for these (address-line2 must never get the street).
_OTHER_AC = {
    "honorific-prefix", "additional-name", "honorific-suffix", "nickname", "username",
    "organization-title", "organization", "address-line2", "address-line3", "address-level3",
    "address-level4", "country", "country-name", "bday", "bday-day", "bday-month", "bday-year",
    "sex", "url", "photo", "impp", "tel-country-code", "tel-area-code", "tel-local",
    "tel-extension", "language", "transaction-currency", "transaction-amount",
}
_AC_QUALIFIERS = {"shipping", "billing", "home", "work", "mobile", "fax", "pager", "webauthn"}

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
_STATE_BY_NAME = {v.lower(): k for k, v in US_STATES.items()}

_EXCLUDE = "__exclude__"   # a source clearly names a field we must not fill: stop looking


def norm(text: Optional[str]) -> str:
    """'creditCardNumber_2' -> 'credit card number 2'."""
    t = str(text or "")
    t = re.sub(r"([a-z])([A-Z])", r"\1 \2", t)
    t = re.sub(r"([A-Za-z])(\d)", r"\1 \2", t)
    t = re.sub(r"(\d)([A-Za-z])", r"\1 \2", t)
    t = re.sub(r"[^A-Za-z0-9]+", " ", t)
    return " ".join(t.lower().split())


def _sources(desc: dict) -> List[str]:
    return [str(desc.get(k) or "") for k in ("label", "aria_label", "placeholder", "name", "id")]


def label_of(desc: dict) -> str:
    for k in ("label", "aria_label", "placeholder", "name", "id"):
        v = " ".join(str(desc.get(k) or "").split())
        if v:
            return v[:80]
    return "(unlabeled field)"


def _ac_tokens(desc: dict) -> List[str]:
    toks = str(desc.get("autocomplete") or "").lower().split()
    return [t for t in toks if not t.startswith("section-") and t not in _AC_QUALIFIERS]


def is_sensitive(desc: dict) -> bool:
    if str(desc.get("type") or "").lower() in SENSITIVE_TYPES:
        return True
    for tok in _ac_tokens(desc):
        if tok.startswith("cc-") or tok in _SENSITIVE_AC:
            return True
    text = " ".join(norm(s) for s in _sources(desc) + [str(desc.get("autocomplete") or "")])
    return bool(_SENSITIVE_RE.search(text))


def is_ignored(desc: dict) -> bool:
    return str(desc.get("type") or "").lower() in IGNORE_TYPES


_NAME_BLOCK = {"user", "username", "company", "business", "organization", "organisation", "org",
               "street", "file", "project", "card", "account", "middle", "nick", "nickname",
               "display", "pet", "school", "vehicle", "team", "site", "domain", "app", "event",
               "product", "group", "father", "mother", "maiden", "spouse", "emergency", "parent",
               "guardian", "screen", "host", "server", "employer", "bank", "reference", "dog"}


def keyword_key(text: str) -> Optional[str]:
    """Profile key named by one label/name/id/aria-label/placeholder string, None if nothing,
    or _EXCLUDE when it clearly names something we must not fill."""
    t = norm(text)
    if not t:
        return None
    words = set(t.split())
    if re.search(r"\be ?mail", t):
        return "email"
    if re.search(r"\bplate", t):
        return "license_plate"
    if re.search(r"\blicen[cs]e", t):
        return _EXCLUDE if re.search(r"\bdriver|\bdl\b", t) else "license_plate"
    if re.search(r"\b(zip|postal|post ?code)", t):
        return "zip"
    if re.search(r"\b(phone|telephone|tel|mobile|cell|cellphone)\b", t):
        return "phone"
    if re.search(r"\b(first ?name|given ?name|fname|first)\b", t):
        return "first_name"
    if re.search(r"\b(last ?name|family ?name|surname|lname|last)\b", t):
        return "last_name"
    if re.search(r"\bmake\b", t):
        return "vehicle_make"
    if re.search(r"\bmodel\b", t):
        return "vehicle_model"
    if re.search(r"\bcolou?r\b", t):
        return "vehicle_color"
    if re.search(r"\b(city|town)\b", t):
        return "city"
    if re.search(r"\b(state|province)\b", t):
        return "state"
    if re.search(r"\b(street|address|addr)", t):
        if re.search(r"\b(address|addr|line|street) ?[23]\b|\b(apt|apartment|suite|unit|web|"
                     r"website|ip|url)\b", t):
            return _EXCLUDE
        return "street_address"
    if "name" in words or "fullname" in words or "full name" in t:
        return _EXCLUDE if words & _NAME_BLOCK else "name"
    if words & {"username", "company", "organization", "organisation"}:
        return _EXCLUDE
    return None


def match_key(desc: dict) -> Optional[str]:
    """The profile key for a (non-sensitive) field: autocomplete token first, then keywords from
    label, aria-label, placeholder, name, id (first source that names something wins)."""
    for tok in reversed(_ac_tokens(desc)):
        if tok in AUTOCOMPLETE_MAP:
            return AUTOCOMPLETE_MAP[tok]
        if tok in _OTHER_AC:
            return None
    for src in _sources(desc):
        k = keyword_key(src)
        if k == _EXCLUDE:
            return None
        if k:
            return k
    typ = str(desc.get("type") or "").lower()
    return {"email": "email", "tel": "phone"}.get(typ)


def plan_fill(descs: Iterable[dict], profile: Dict[str, str]) -> Dict[str, list]:
    """Decide what to do with every field.

    Returns {"fill": [(desc, key)], "missing": [label], "skipped": [label]}: "missing" are
    fillable fields with no profile value, "skipped" are sensitive fields left for the person.
    """
    fill: List[Tuple[dict, str]] = []
    missing: List[str] = []
    skipped: List[str] = []
    for d in descs:
        if is_ignored(d):
            continue
        if is_sensitive(d):
            skipped.append(label_of(d))
            continue
        key = match_key(d)
        if key and (profile.get(key) or "").strip():
            if str(d.get("tag") or "").lower() == "select" and choose_option(
                    key, profile[key], d.get("options") or []) is None:
                missing.append(label_of(d))
                continue
            fill.append((d, key))
        else:
            missing.append(label_of(d))
    return {"fill": fill, "missing": missing, "skipped": skipped}


def _cmp(s: Optional[str]) -> str:
    return " ".join(str(s or "").lower().split())


def choose_option(key: str, value: str, options: List[dict]) -> Optional[str]:
    """The <option> value to select for a profile value, or None. States accept 'GA' or 'Georgia'."""
    want = {_cmp(value)}
    abbr = None
    if key == "state":
        v = value.strip()
        if v.upper() in US_STATES:
            abbr = v.upper()
        elif v.lower() in _STATE_BY_NAME:
            abbr = _STATE_BY_NAME[v.lower()]
        if abbr:
            want |= {abbr.lower(), US_STATES[abbr].lower()}
    real = [o for o in options if str(o.get("value") or "").strip() or _cmp(o.get("label"))]
    for o in real:
        if _cmp(o.get("value")) in want or _cmp(o.get("label")) in want:
            return str(o.get("value") if o.get("value") is not None else o.get("label"))
    if abbr:   # "GA - Georgia", "Georgia (GA)"
        for o in real:
            toks = set(norm(o.get("label")).split()) | set(norm(o.get("value")).split())
            if abbr.lower() in toks:
                return str(o.get("value") if o.get("value") is not None else o.get("label"))
    return None


# --- submit helpers -------------------------------------------------------------------------

_CERTIFY_RE = re.compile(r"\b(certify|confirm|agree|accurate|correct|attest)")
_OPTIN_RE = re.compile(r"\b(newsletter|marketing|promotion|promotional|offers|subscribe|"
                       r"updates|text messages|sms)\b")
_SUBMIT_TEXT_RE = re.compile(r"^(submit( .*)?|apply( now)?|send( application| form)?)$")


def should_tick(label: str) -> bool:
    """The certify/agree checkbox (ticked only by form_submit), never a marketing opt-in."""
    t = norm(label)
    return bool(_CERTIFY_RE.search(t)) and not _OPTIN_RE.search(t)


def is_submit_text(text: str) -> bool:
    return bool(_SUBMIT_TEXT_RE.match(norm(text)))


def text_change(before: str, after: str, limit: int = 200) -> str:
    """The visible text that appeared after submitting (new lines), at most `limit` chars."""
    seen = {" ".join(line.split()) for line in (before or "").splitlines()}
    new = [" ".join(line.split()) for line in (after or "").splitlines()]
    new = [line for line in new if line and line not in seen]
    return " ".join(new)[:limit]


SCRUB_KEYS = ("name", "first_name", "last_name", "email", "phone", "street_address",
              "license_plate")


def scrub(text: str, profile: Dict[str, str]) -> str:
    """Remove the person's identifying profile values (name, email, phone, street, plate) from
    page text before it goes in a result. Single-word names match case-sensitively, so a page
    saying "demo" keeps it while "Alex Demo" goes."""
    out = str(text or "")
    vals = {str(profile.get(k) or "").strip() for k in SCRUB_KEYS} - {""}
    for v in sorted(vals, key=len, reverse=True):
        if len(v) < 3:
            continue
        flags = 0 if re.fullmatch(r"[A-Za-z'-]+", v) else re.IGNORECASE
        out = re.sub(r"(?<!\w)" + re.escape(v) + r"(?!\w)", "[your info]", out, flags=flags)
    return out
