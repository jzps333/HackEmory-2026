"""Typesense `scans` collection: the search layer over the Tiger Data scan log.

One document per row of the Tiger `scans` table (Tiger stays the source of truth). Config is the
same as `scam_pins` (TYPESENSE_HOST, TYPESENSE_API_KEY), see data/typesense_store.py.

What a document holds:
- Always (these are Tiger's columns): domain, verdict, scam_type, jev_score, scan_ms, scanned_at.
- Only for scans indexed live by record_scan (Tiger doesn't keep them, so backfilled rows lack them):
  url and final_url without query string, fragment or user:password (http/https only; other QR
  content such as WIFI: or vCard text is never stored; solana: keeps only the recipient),
  page_title, explanation.
- location: only after the user taps Report on a malicious scan (the same rounded point that
  goes on the public scam map). Unreported scans never get a location.

Doc id = hash of the Tiger row, so the live path and the backfill (data/sync_scans.py) write the
same document, and re-running the backfill never duplicates. Both use action=emplace, which
creates or merges, so a backfill keeps the url/explanation a live scan added.
"""
from __future__ import annotations

import hashlib
import html
import json
from collections.abc import Mapping
from datetime import datetime
from urllib.parse import urlsplit

from api.schema import ScanResult
from data import tiger_store
from data.typesense_store import _client, _quote

COLLECTION = "scans"
SCHEMA = {
    "name": COLLECTION,
    "fields": [
        {"name": "domain", "type": "string", "facet": True},
        {"name": "verdict", "type": "string", "facet": True},
        {"name": "scam_type", "type": "string", "facet": True},
        {"name": "jev_score", "type": "float"},
        {"name": "scan_ms", "type": "int32", "optional": True},
        {"name": "scanned_at", "type": "int64"},
        {"name": "url", "type": "string", "optional": True},
        {"name": "final_url", "type": "string", "optional": True},
        {"name": "page_title", "type": "string", "optional": True},
        {"name": "explanation", "type": "string", "optional": True},
        {"name": "location", "type": "geopoint", "optional": True},
    ],
    "default_sorting_field": "scanned_at",
    # Split "en.wikipedia.org" / URL paths into words, so "wikipedia" matches mid-domain.
    "token_separators": [".", "-", "/", ":", "_"],
}
QUERY_BY = "domain,url,final_url,page_title,explanation"
QUERY_BY_WEIGHTS = "5,3,3,2,1"
HIT_FIELDS = ("id", "url", "final_url", "domain", "verdict", "scam_type", "jev_score",
              "explanation", "page_title", "scanned_at", "scan_ms")
FACETS = ("verdict", "scam_type")
# Typesense doesn't HTML-escape snippets, and page titles come from (possibly hostile) pages:
# mark matches with plain-text sentinels, escape everything, then turn the sentinels into <mark>.
_MARK, _END = "[[ss-mark]]", "[[/ss-mark]]"
IMPORT_TIMEOUT = 60


# ---------- documents ----------

def doc_id(row: Mapping) -> str:
    """Stable id for one Tiger row (time, domain, verdict, scam_type, jev_score, scan_ms)."""
    jev, ms = row.get("jev_score"), row.get("scan_ms")
    key = json.dumps([
        _epoch(row["time"]), row.get("domain") or "", row.get("verdict") or "", row.get("scam_type") or "",
        None if jev is None else round(float(jev), 6), None if ms is None else int(ms),
    ])
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def _epoch(t) -> int:
    return int(t.timestamp()) if isinstance(t, datetime) else int(t)


def row_document(row: Mapping) -> dict:
    """A Tiger `scans` row (dict) -> Typesense document with only what Tiger stores."""
    doc = {
        "id": doc_id(row),
        "domain": (row.get("domain") or "").lower(),
        "verdict": row.get("verdict") or "",
        "scam_type": row.get("scam_type") or "none",
        "jev_score": float(row.get("jev_score") or 0.0),
        "scanned_at": _epoch(row["time"]),
    }
    if row.get("scan_ms") is not None:
        doc["scan_ms"] = int(row["scan_ms"])
    return doc


def _tiger_row(result: ScanResult) -> dict:
    """Exactly the row record_scan inserts into Tiger, so ids match what the backfill reads back."""
    names = ("time", "domain", "verdict", "scam_type", "jev_score", "scan_ms")
    return dict(zip(names, tiger_store.scan_row(result)))


def clean_url(value: str | None) -> str | None:
    """http(s) URL without query, fragment or credentials; solana: without its query; else None."""
    if not value:
        return None
    value = value.strip()
    if value.lower().startswith("solana:"):
        return value.split("?", 1)[0].split("#", 1)[0][:200]
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    return f"{parts.scheme.lower()}://{host}{f':{port}' if port else ''}{parts.path or '/'}"[:2000]


def _clip(text: str | None, n: int) -> str | None:
    text = (text or "").strip()
    return text[:n] if text else None


def result_document(result: ScanResult) -> dict:
    """The document record_scan indexes for a live scan. Never includes the location."""
    doc = row_document(_tiger_row(result))
    if result.verdict == "safe":
        # Privacy: /scans/search is public, and a link's path can hold private things (a shared
        # document's id, a booking code). Safe scans keep only domain, verdict and time.
        return doc
    extras = {
        "url": clean_url(result.url),
        "final_url": clean_url(result.final_url),
        "page_title": _clip(result.page_title, 300),
        "explanation": _clip(result.explanation, 2000),
    }
    doc.update({k: v for k, v in extras.items() if v})
    return doc


# ---------- writes ----------

def ensure_collection() -> bool:
    """Create `scans` if it doesn't exist. Returns True if it was created."""
    with _client() as c:
        r = c.get(f"/collections/{COLLECTION}")
        if r.status_code == 200:
            return False
        if r.status_code != 404:
            r.raise_for_status()
        r = c.post("/collections", json=SCHEMA)
        if r.status_code == 409:
            return False
        r.raise_for_status()
        return True


def index_scan(result: ScanResult) -> dict:
    """Create or merge this scan's document. Raises on HTTP errors (record_scan catches them)."""
    doc = result_document(result)
    with _client() as c:
        r = c.post(f"/collections/{COLLECTION}/documents", params={"action": "emplace"}, json=doc)
        r.raise_for_status()
    return doc


def set_location(result: ScanResult) -> bool:
    """After a Report: add the pin's rounded location to the scan's document. False if not indexed."""
    if not result.location or len(result.location) != 2:
        return False
    lat, lng = (round(float(v), 3) for v in result.location)
    with _client() as c:
        r = c.patch(f"/collections/{COLLECTION}/documents/{doc_id(_tiger_row(result))}",
                    json={"location": [lat, lng]})
        if r.status_code == 404:
            return False
        r.raise_for_status()
    return True


def import_documents(docs: list[dict]) -> tuple[int, list[str]]:
    """Bulk create-or-merge. Returns (ok count, error messages for the failed lines)."""
    if not docs:
        return 0, []
    body = "\n".join(json.dumps(d) for d in docs)
    with _client() as c:
        r = c.post(f"/collections/{COLLECTION}/documents/import", params={"action": "emplace"},
                   content=body, headers={"Content-Type": "text/plain"}, timeout=IMPORT_TIMEOUT)
        r.raise_for_status()
    ok, errors = 0, []
    for line in r.text.splitlines():
        if not line.strip():
            continue
        res = json.loads(line)
        if res.get("success"):
            ok += 1
        else:
            errors.append(str(res.get("error", "unknown error"))[:200])
    return ok, errors


def all_ids() -> set[str]:
    with _client() as c:
        r = c.get(f"/collections/{COLLECTION}/documents/export", params={"include_fields": "id"},
                  timeout=IMPORT_TIMEOUT)
        r.raise_for_status()
    return {json.loads(line)["id"] for line in r.text.splitlines() if line.strip()}


def delete_ids(ids) -> int:
    n = 0
    with _client() as c:
        for i in ids:
            r = c.delete(f"/collections/{COLLECTION}/documents/{i}")
            if r.status_code != 404:
                r.raise_for_status()
                n += 1
    return n


def count() -> int:
    with _client() as c:
        r = c.get(f"/collections/{COLLECTION}")
        r.raise_for_status()
        return int(r.json().get("num_documents", 0))


# ---------- search ----------

def search_params(q: str = "", verdict: str | None = None, scam_type: str | None = None,
                  lat: float | None = None, lng: float | None = None, radius_km: float = 5.0,
                  page: int = 1, per_page: int = 20) -> dict:
    q = (q or "").strip()
    browse = q in ("", "*")
    geo = lat is not None and lng is not None
    filters = []
    if verdict:
        filters.append(f"verdict:={_quote(verdict)}")
    if scam_type:
        filters.append(f"scam_type:={_quote(scam_type)}")
    if geo:
        filters.append(f"location:({lat}, {lng}, {radius_km} km)")
    sort = ([] if browse else ["_text_match:desc"]) + ["scanned_at:desc"]
    if geo:
        sort.append(f"location({lat}, {lng}):asc")   # last: only there so hits carry a distance
    params = {
        "q": "*" if browse else q,
        "query_by": QUERY_BY,
        "query_by_weights": QUERY_BY_WEIGHTS,
        "sort_by": ",".join(sort),
        "facet_by": ",".join(FACETS),
        "max_facet_values": 20,
        "page": max(1, int(page)),
        "per_page": max(1, min(int(per_page), 100)),
        "highlight_start_tag": _MARK,
        "highlight_end_tag": _END,
    }
    if filters:
        params["filter_by"] = " && ".join(filters)
    return params


def _safe_snippet(snippet: str) -> str:
    return html.escape(snippet).replace(_MARK, "<mark>").replace(_END, "</mark>")


def _hit(hit: dict) -> dict:
    doc = hit.get("document") or {}
    out = {k: doc.get(k) for k in HIT_FIELDS}
    out["reported"] = "location" in doc
    if "geo_distance_meters" in hit:
        out["distance_m"] = (hit["geo_distance_meters"] or {}).get("location")
    marks = {}
    for field, h in (hit.get("highlight") or {}).items():
        if isinstance(h, dict) and h.get("matched_tokens") and h.get("snippet"):
            marks[field] = _safe_snippet(h["snippet"])
    if marks:
        out["highlight"] = marks
    return out


def search(**kwargs) -> dict:
    """Typo-tolerant search over the scan log. Empty q or "*" = browse, newest first."""
    params = search_params(**kwargs)
    with _client() as c:
        r = c.get(f"/collections/{COLLECTION}/documents/search", params=params)
        r.raise_for_status()
        resp = r.json()
    facets = {name: {} for name in FACETS}
    for fc in resp.get("facet_counts") or []:
        if fc.get("field_name") in facets:
            facets[fc["field_name"]] = {c["value"]: c["count"] for c in fc.get("counts") or []}
    return {
        "found": int(resp.get("found", 0)),
        "out_of": int(resp.get("out_of", 0)),
        "page": params["page"],
        "per_page": params["per_page"],
        "hits": [_hit(h) for h in resp.get("hits") or []],
        "facets": facets,
    }
