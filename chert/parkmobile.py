"""ParkMobile calls: the agent fills in the REAL official ParkMobile web app in the sandbox
(adapter "parkmobile", sandbox/operate.py) and stops before payment. Pure helpers, no LiveKit.

Trigger (demo): POST /call-me with url = an https://app.parkmobile.io link that names a zone:
  https://app.parkmobile.io/v2/parking?zone=91987                     (types the zone in the search)
  https://app.parkmobile.io/v2/parking/zone-details?areaNo=10891987   (ParkMobile's own zone page)
The plate is PARKMOBILE_DEMO_PLATE (default DEMO123); the duration is 2 hours. Nothing is ever paid:
the agent never offers to pay on real sites.
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


def parkmobile_job(job: Any) -> Optional[dict]:
    """{"url", "scan_url", "zone", "plate", "minutes"} when an outbound job's scan_url is an
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
            "minutes": DEFAULT_MINUTES}


def _say_safe(s: Any, limit: int) -> str:
    """Page text made safe to speak: plain characters only (no quotes), clipped."""
    t = re.sub(r"[^A-Za-z0-9 .,:/&()$#-]", " ", str(s or ""))
    return re.sub(r"\s+", " ", t).strip()[:limit].rstrip(" ,.-")


def duration_text(minutes: int) -> str:
    if minutes % 60 == 0:
        h = minutes // 60
        return "1 hour" if h == 1 else f"{h} hours"
    return f"{minutes} minutes"


def greeting(job: dict) -> str:
    zone = job.get("zone")
    where = f"zone {zone}" if zone else "that parking zone"
    return (f"Hi, this is ScanSafe. I'm opening the official ParkMobile site for {where} on our "
            f"computer, so you can watch. I'll fill in {duration_text(job['minutes'])} and plate "
            f"{job['plate']}, and I'll stop before any payment.")


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
        return (f"This is the official ParkMobile site. {where}, {dur}, plate {plate}. {shows} "
                "I've stopped at the payment step, so nothing has been paid.")
    if status == "needs_sign_in":
        return (f"This is the official ParkMobile site. {where}. ParkMobile asks for an email "
                f"address and its terms before it shows the price for {dur}, so I've stopped there. "
                f"I didn't enter anything, and nothing has been paid. You can finish it yourself in "
                f"the ParkMobile app with plate {plate}.")
    if status == "robot_check":
        return ("ParkMobile showed a robot check, so I stopped and didn't touch it. "
                "Nothing has been paid.")
    return "I couldn't get through the ParkMobile site this time, so I stopped. Nothing has been paid."
