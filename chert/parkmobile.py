"""ParkMobile calls: the agent fills in the REAL official ParkMobile web app in the sandbox
(adapter "parkmobile", sandbox/operate.py) and stops before payment. Pure helpers, no LiveKit.

Trigger (demo): POST /call-me with url = an https://app.parkmobile.io link that names a zone:
  https://app.parkmobile.io/v2/parking?zone=91987                     (types the zone in the search)
  https://app.parkmobile.io/v2/parking/zone-details?areaNo=10891987   (ParkMobile's own zone page)
The plate is PARKMOBILE_DEMO_PLATE (default DEMO123); the duration is 2 hours. If the sandbox has a
saved, signed-in ParkMobile session (the person's own account, captured on the Mac) the run gets
to ParkMobile's price; otherwise it stops at the guest "Add email" screen. Nothing is ever paid:
the agent never offers to pay on real sites. The greeting is in the model's own words
(ScanSafeCall.converse); the facts read back afterwards are fixed lines (speech()).
"""
from __future__ import annotations

import os
import re
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

PM_HOST = "app.parkmobile.io"
ENTRY_URL = "https://app.parkmobile.io/v2/parking"
ZONE_DETAILS_PATH = "/v2/parking/zone-details"
DEFAULT_MINUTES = 120
DEFAULT_PLATE = "DEMO123"
_ZONE_RE = re.compile(r"^\d{3,7}$")
_AREA_RE = re.compile(r"^\d{3,12}$")
_PLATE_RE = re.compile(r"^[A-Z0-9][A-Z0-9 -]{0,9}$")

INSTRUCTIONS = (
    "This call is about the official ParkMobile website, which ScanSafe opens live on its own "
    "computer. ScanSafe only fills in the zone, the duration and the licence plate, and always "
    "stops before payment. Never offer to pay, never ask for or repeat card numbers, email "
    "addresses, phone numbers or passwords, and never say anything was paid. If the caller wants "
    "to park, tell them to finish in the ParkMobile app or website themselves.")


def demo_plate() -> str:
    p = re.sub(r"\s+", " ", os.getenv("PARKMOBILE_DEMO_PLATE") or "").strip().upper()
    return p if _PLATE_RE.fullmatch(p) else DEFAULT_PLATE


def e164(raw: Any) -> Optional[str]:
    """'+1 (404) 555-0123' / '404-555-0123' / '0014045550123' -> '+14045550123'; None if not a phone."""
    if not isinstance(raw, str):
        return None
    s = re.sub(r"[\s().-]", "", raw.strip())
    if s.startswith("00"):
        s = "+" + s[2:]
    if s.startswith("+"):
        digits = s[1:]
    elif len(s) == 10:
        digits = "1" + s                     # a US number without the country code
    elif len(s) == 11 and s.startswith("1"):
        digits = s
    else:
        return None
    return "+" + digits if digits.isdigit() and 8 <= len(digits) <= 15 else None


def is_session_owner(phone: Any) -> bool:
    """True only when the phone being called is PARKMOBILE_OWNER_PHONE (both in E.164). The saved
    ParkMobile session belongs to that one person; everyone else gets a guest run."""
    owner = e164(os.getenv("PARKMOBILE_OWNER_PHONE") or "")
    return owner is not None and e164(phone) == owner


def parkmobile_job(job: Any) -> Optional[dict]:
    """{"url", "scan_url", "zone", "plate", "minutes", "use_session"} when an outbound job's scan_url is an
    https://app.parkmobile.io link naming a zone (?zone=NNNN, or a zone-details ?areaNo= page).
    None otherwise (the call is an ordinary walkthrough)."""
    if not isinstance(job, dict):
        return None
    url = job.get("scan_url")
    if not isinstance(url, str) or len(url) > 2048 or any(c.isspace() or ord(c) < 32 for c in url):
        return None
    try:
        u = urlsplit(url)
        port = u.port
    except ValueError:
        return None
    if (u.scheme != "https" or u.netloc.lower() != PM_HOST or port is not None
            or u.username is not None or u.password is not None):
        return None
    q = parse_qs(u.query)
    zone = next((v[0] for k in ("zone", "zoneNumber", "zone_number") if (v := q.get(k))), "")
    zone = zone if _ZONE_RE.fullmatch(zone) else None
    area = q.get("areaNo", [""])[0] if u.path.rstrip("/") == ZONE_DETAILS_PATH else ""
    area = area if _AREA_RE.fullmatch(area) else None
    if zone is None and area is None:
        return None
    entry = f"https://{PM_HOST}{ZONE_DETAILS_PATH}?areaNo={area}" if area else ENTRY_URL
    return {"url": entry, "scan_url": url, "zone": zone, "plate": demo_plate(),
            "minutes": DEFAULT_MINUTES,
            # the owner's saved session only when /call-me took the phone from a sign-in token
            # (phone_verified), never for an unsigned call to an allow-listed number
            "use_session": job.get("phone_verified") is True and is_session_owner(job.get("phone"))}


def _say_safe(s: Any, limit: int) -> str:
    """Page text made safe to speak: plain characters only (no quotes), clipped."""
    t = re.sub(r"[^A-Za-z0-9 .,:/&()$#-]", " ", str(s or ""))
    return re.sub(r"\s+", " ", t).strip()[:limit].rstrip(" ,.-")


def duration_text(minutes: int) -> str:
    if minutes % 60 == 0:
        h = minutes // 60
        return "1 hour" if h == 1 else f"{h} hours"
    return f"{minutes} minutes"


def hello_instructions(job: dict) -> str:
    """Instructions for the greeting, said in the model's own words (ScanSafeCall.converse)."""
    zone = job.get("zone")
    where = f"zone {zone}" if zone else "the parking zone they picked"
    return ("You just called this person about parking. Greet them warmly in your own words, in "
            "one or two short sentences: say it's ScanSafe, that you're opening the official "
            f"ParkMobile site for {where} on our computer so they can watch it on this video, that "
            f"you'll fill in {duration_text(job['minutes'])} and plate {job['plate']}, and that "
            "you'll stop before any payment. Don't ask them for any details and don't offer to pay.")


def speech(result: Optional[dict], job: dict) -> str:
    """What the agent says when the sandbox run ends. Page text (zone name, price) is cleaned
    and clipped; the agent never offers to pay."""
    r = result if isinstance(result, dict) else {}
    status = r.get("status")
    zone = _say_safe(r.get("zone") or job.get("zone") or "", 8)
    name = _say_safe(r.get("zone_name"), 40)
    where = ", ".join(x for x in (f"Zone {zone}" if zone else "", name) if x) or "This zone"
    dur, plate = duration_text(job["minutes"]), job["plate"]
    if status == "ready_to_pay":
        price = _say_safe(r.get("price_text"), 60)
        shows = f"ParkMobile shows {price}." if price else "ParkMobile is on its payment step."
        check = ("" if r.get("duration_set", True) and r.get("plate_set", True) else
                 " Please check the duration and plate on the screen before you pay yourself.")
        return (f"This is the official ParkMobile site. {where}, {dur}, plate {plate}. {shows} "
                f"I've stopped at the payment step, so nothing has been paid.{check}")
    if status in ("needs_sign_in", "needs_verification") and r.get("session") == "loaded":
        return (f"This is the official ParkMobile site. {where}. ParkMobile signed us out, so I "
                "stopped at its sign-in screen and didn't type anything. Nothing has been paid. "
                "Please sign in to ParkMobile again on the Mac, then call me again.")
    if status == "needs_verification":
        return ("ParkMobile asked for a sign-in code, so I stopped and didn't type anything. "
                "Nothing has been paid.")
    if status == "needs_sign_in":
        return (f"This is the official ParkMobile site. {where}. ParkMobile asks for an email "
                f"address and its terms before it shows the price for {dur}, so I've stopped there. "
                f"I didn't enter anything, and nothing has been paid. You can finish it yourself in "
                f"the ParkMobile app with plate {plate}.")
    if status == "robot_check":
        return ("ParkMobile showed a robot check, so I stopped and didn't touch it. "
                "Nothing has been paid.")
    return "I couldn't get through the ParkMobile site this time, so I stopped. Nothing has been paid."
