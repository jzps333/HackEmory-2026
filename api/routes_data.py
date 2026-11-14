"""Data endpoints (Person 3): scam map pins, search, scan-log search, and the Tiger Data dashboard.

Include in main.py with `app.include_router(router)`. Call `record_scan(result)` after every scan.
Every endpoint returns a clear 503 if its service isn't configured, 502 if the service errors.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query

from pydantic import BaseModel, ConfigDict

from api import recent_scans
from api.schema import ScamType, ScanResult, Verdict
from data import scan_search, tiger_store, typesense_store

log = logging.getLogger("scansafe.data")
router = APIRouter(tags=["data"])


def _need_typesense(what: str = "Scam map") -> None:
    if not typesense_store.is_configured():
        raise HTTPException(503, detail={
            "error": "typesense_not_configured", "service": "typesense",
            "message": f"{what} is unavailable: set TYPESENSE_HOST and TYPESENSE_API_KEY."})


def _need_tiger() -> None:
    if not tiger_store.is_configured():
        raise HTTPException(503, detail={
            "error": "tiger_not_configured", "service": "tiger_data",
            "message": "Stats are unavailable: set TIGER_DATABASE_URL."})


def _upstream(service: str, e: Exception) -> HTTPException:
    log.warning("%s request failed: %s", service, type(e).__name__)
    return HTTPException(502, detail={"error": f"{service}_error", "service": service,
                                      "message": f"{service} request failed, try again."})


# ---------- helpers for /scan (never raise) ----------

def record_scan(result: ScanResult) -> None:
    """Log one scan to Tiger Data, then index it in the Typesense `scans` collection (scan-log
    search). Each step is best effort and independent. Never raises: a hiccup must not break a scan."""
    try:
        if tiger_store.is_configured():
            tiger_store.log_scan(result)
    except Exception as e:  # noqa: BLE001 - intentionally swallow everything
        log.warning("record_scan failed: %s", type(e).__name__)
    try:
        if typesense_store.is_configured():
            scan_search.index_scan(result)
    except Exception as e:  # noqa: BLE001
        log.warning("index_scan failed: %s", type(e).__name__)


def flagged_before(result: ScanResult, radius_km: float = 5) -> int:
    """How many reported pins share this domain (near the scan, if it has a location). Never raises."""
    try:
        if not typesense_store.is_configured() or not result.domain:
            return 0
        lat, lng = (result.location or [None, None])[:2]
        return typesense_store.flagged_count(result.domain, lat, lng, radius_km)
    except Exception as e:  # noqa: BLE001
        log.warning("flagged_before failed: %s", type(e).__name__)
        return 0


# ---------- Typesense ----------

class ReportRequest(BaseModel):
    """Only the scan_id is used. The app may still send the whole ScanResult; everything else
    in the body is ignored, because the pin is built from the server's own copy of the check."""
    model_config = ConfigDict(extra="ignore")
    scan_id: str


@router.post("/report")
def report(req: ReportRequest) -> dict:
    """User tapped "Report scam". Pins malicious scans that have a location; never stores who.
    The scan must be one this server ran recently (see api/recent_scans.py)."""
    result = recent_scans.get(req.scan_id)
    if result is None:
        return {"stored": False, "code": "unknown_scan",
                "reason": "We couldn't find that check. Please scan the code again."}
    if result.verdict != "malicious":
        return {"stored": False, "code": "not_malicious",
                "reason": "Only scans we confirmed as scams are pinned on the map."}
    if not result.location:
        return {"stored": False, "code": "no_location",
                "reason": "No location was shared, so there is nothing to pin."}
    _need_typesense()   # only needed when there is something to pin
    try:
        doc = typesense_store.add_pin(result)
    except httpx.HTTPError as e:
        raise _upstream("typesense", e)
    if doc is not None:
        try:   # the scan-log entry gets the same rounded point, so /scans/search can filter by place
            scan_search.set_location(result)
        except Exception as e:  # noqa: BLE001 - the pin is stored; this part is best effort
            log.warning("scan set_location failed: %s", type(e).__name__)
    return {"stored": doc is not None, "code": "pinned" if doc is not None else "not_pinned", "pin": doc}


@router.get("/pins")
def pins(lat: float = Query(..., ge=-90, le=90), lng: float = Query(..., ge=-180, le=180),
         radius_km: float = Query(1.0, gt=0, le=100), limit: int = Query(100, ge=1, le=250)) -> dict:
    _need_typesense()
    try:
        found = typesense_store.nearby(lat, lng, radius_km, limit)
    except httpx.HTTPError as e:
        raise _upstream("typesense", e)
    return {"count": len(found), "pins": found}


@router.get("/search")
def search(q: str = Query(..., min_length=1, max_length=200), limit: int = Query(20, ge=1, le=100)) -> dict:
    _need_typesense()
    try:
        found = typesense_store.search(q, limit)
    except httpx.HTTPError as e:
        raise _upstream("typesense", e)
    return {"count": len(found), "results": found}


@router.get("/scans/search")
def scans_search(q: str = Query("", max_length=200),
                 verdict: Optional[Verdict] = Query(None),
                 scam_type: Optional[ScamType] = Query(None),
                 lat: Optional[float] = Query(None, ge=-90, le=90),
                 lng: Optional[float] = Query(None, ge=-180, le=180),
                 radius_km: float = Query(5.0, gt=0, le=100),
                 page: int = Query(1, ge=1, le=100),
                 per_page: int = Query(20, ge=1, le=100)) -> dict:
    """Typo-tolerant search over every logged scan (Typesense `scans`, mirrored from Tiger Data).
    Empty q or "*" = browse, newest first. lat+lng only match scans that were reported."""
    if (lat is None) != (lng is None):
        raise HTTPException(422, detail={"error": "bad_location", "message": "Send both lat and lng, or neither."})
    _need_typesense("Scan search")
    try:
        return scan_search.search(q=q, verdict=verdict, scam_type=scam_type, lat=lat, lng=lng,
                                  radius_km=radius_km, page=page, per_page=per_page)
    except httpx.HTTPError as e:
        raise _upstream("typesense", e)


# ---------- Tiger Data ----------

@router.get("/stats/hourly")
def stats_hourly(hours: int = Query(24, ge=1, le=720)) -> dict:
    _need_tiger()
    try:
        rows = tiger_store.hourly_stats(hours)
    except Exception as e:  # noqa: BLE001 - psycopg errors, connection errors
        raise _upstream("tiger_data", e)
    return {"hours": hours, "rows": rows}


@router.get("/stats/summary")
def stats_summary() -> dict:
    _need_tiger()
    try:
        return tiger_store.summary()
    except Exception as e:  # noqa: BLE001
        raise _upstream("tiger_data", e)
