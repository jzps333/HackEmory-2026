"""Typesense: the `scam_pins` collection behind the scam map, search and "flagged before".

Config (env): TYPESENSE_HOST (full URL, e.g. https://xyz.a1.typesense.net), TYPESENSE_API_KEY.
Only malicious scans with a location are pinned, and we never store who reported them.
"""
from __future__ import annotations

import os
import time
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

from api.schema import ScanResult

load_dotenv()

COLLECTION = "scam_pins"
SCHEMA = {
    "name": COLLECTION,
    "fields": [
        {"name": "url", "type": "string"},
        {"name": "domain", "type": "string", "facet": True},
        {"name": "scam_type", "type": "string", "facet": True},
        {"name": "jev_score", "type": "float"},
        {"name": "explanation", "type": "string"},
        {"name": "location", "type": "geopoint"},
        {"name": "reported_at", "type": "int64"},
    ],
    "default_sorting_field": "reported_at",
}
TIMEOUT = 10


class NotConfigured(RuntimeError):
    """Raised when TYPESENSE_HOST / TYPESENSE_API_KEY are missing."""


def is_configured() -> bool:
    return bool(os.getenv("TYPESENSE_HOST") and os.getenv("TYPESENSE_API_KEY"))


def _client() -> httpx.Client:
    host = os.getenv("TYPESENSE_HOST", "").rstrip("/")
    key = os.getenv("TYPESENSE_API_KEY", "")
    if not host or not key:
        raise NotConfigured("Typesense is not configured (set TYPESENSE_HOST and TYPESENSE_API_KEY)")
    return httpx.Client(base_url=host, headers={"X-TYPESENSE-API-KEY": key}, timeout=TIMEOUT)


def _domain_of(result: ScanResult) -> str:
    if result.domain:
        return result.domain.lower()
    return (urlparse(result.final_url or result.url).hostname or "").lower()


def _quote(value: str) -> str:
    """Backtick-quote a value for filter_by (backticks themselves are stripped)."""
    return "`" + value.replace("`", "") + "`"


def ensure_collection() -> bool:
    """Create `scam_pins` if it doesn't exist. Returns True if it was created."""
    with _client() as c:
        r = c.get(f"/collections/{COLLECTION}")
        if r.status_code == 200:
            return False
        if r.status_code != 404:
            r.raise_for_status()
        r = c.post("/collections", json=SCHEMA)
        if r.status_code == 409:  # created by someone else in the meantime
            return False
        r.raise_for_status()
        return True


def pin_document(result: ScanResult) -> dict | None:
    """The document we'd store for this result, or None if it must not be pinned."""
    if result.verdict != "malicious" or not result.location or len(result.location) != 2:
        return None
    lat, lng = (round(float(v), 3) for v in result.location)  # ~100 m, never exact
    return {
        "id": result.scan_id,  # one pin per scan, so double-taps on Report don't duplicate
        "url": result.final_url or result.url,
        "domain": _domain_of(result),
        "scam_type": result.scam_type,
        "jev_score": float(result.jev_score),
        "explanation": result.explanation,
        "location": [lat, lng],
        "reported_at": int(time.time()),
    }


def add_pin(result: ScanResult) -> dict | None:
    """Pin a reported scan on the map. Returns the stored doc, or None if not eligible."""
    doc = pin_document(result)
    if doc is None:
        return None
    with _client() as c:
        r = c.post(f"/collections/{COLLECTION}/documents", params={"action": "upsert"}, json=doc)
        r.raise_for_status()
    return doc


def _search(params: dict) -> dict:
    with _client() as c:
        r = c.get(f"/collections/{COLLECTION}/documents/search", params=params)
        r.raise_for_status()
        return r.json()


def nearby_params(lat: float, lng: float, radius_km: float = 1.0, limit: int = 100) -> dict:
    return {
        "q": "*",
        "query_by": "domain",
        "filter_by": f"location:({lat}, {lng}, {radius_km} km)",
        "sort_by": f"location({lat}, {lng}):asc",
        "per_page": max(1, min(int(limit), 250)),
    }


def _docs(resp: dict) -> list[dict]:
    out = []
    for hit in resp.get("hits", []):
        doc = dict(hit.get("document", {}))
        if "geo_distance_meters" in hit:
            doc["distance_m"] = hit["geo_distance_meters"].get("location")
        out.append(doc)
    return out


def nearby(lat: float, lng: float, radius_km: float = 1.0, limit: int = 100) -> list[dict]:
    """Pins within radius_km of (lat, lng), nearest first."""
    return _docs(_search(nearby_params(lat, lng, radius_km, limit)))


def search(q: str, limit: int = 20) -> list[dict]:
    """Typo-tolerant text search over explanation, domain and url."""
    return _docs(_search({
        "q": q or "*",
        "query_by": "explanation,domain,url",
        "per_page": max(1, min(int(limit), 250)),
    }))


def flagged_count(domain: str, lat: float | None = None, lng: float | None = None,
                  radius_km: float = 5) -> int:
    """How many pins exist for this domain (near lat/lng, if given)."""
    if not domain:
        return 0
    filt = f"domain:={_quote(domain.lower())}"
    if lat is not None and lng is not None:
        filt += f" && location:({lat}, {lng}, {radius_km} km)"
    resp = _search({"q": "*", "query_by": "domain", "filter_by": filt, "per_page": 0})
    return int(resp.get("found", 0))
