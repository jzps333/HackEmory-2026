"""Research library: finished research reports in the Typesense collection `research_reports`.

One document per done job (id = job_id): owner (the phone hash, facet), topic, summary, section
titles, at (unix seconds, the sort field), page_token (stored for the page link, never searched)
and job_id. Searches are always filtered to one owner. The collection is created on first use.
Nothing here raises: when Typesense is unset or failing, add() does nothing and search() returns
None, and api/research.py falls back to a substring match over the stored jobs.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from data import typesense_store

log = logging.getLogger("scansafe.research_index")

COLLECTION = "research_reports"
SCHEMA = {
    "name": COLLECTION,
    "fields": [
        {"name": "owner", "type": "string", "facet": True},
        {"name": "topic", "type": "string"},
        {"name": "summary", "type": "string"},
        {"name": "sections", "type": "string[]"},
        {"name": "at", "type": "int64", "sort": True},
        {"name": "page_token", "type": "string", "index": False, "optional": True},
        {"name": "job_id", "type": "string"},
    ],
    "default_sorting_field": "at",
}
QUERY_BY = "topic,sections,summary"
QUERY_WEIGHTS = "3,2,1"
RETRY_S = 60.0

_lock = threading.Lock()
_ready = False
_down_until = 0.0


def reset() -> None:   # tests
    global _ready, _down_until
    with _lock:
        _ready, _down_until = False, 0.0


def _ok() -> bool:
    return typesense_store.is_configured() and time.monotonic() >= _down_until


def _failed(what: str, e: Exception) -> None:
    global _down_until
    _down_until = time.monotonic() + RETRY_S
    log.warning("research library: Typesense %s failed (%s)", what, type(e).__name__)


def _ensure(c) -> None:
    global _ready
    if _ready:
        return
    r = c.get(f"/collections/{COLLECTION}")
    if r.status_code == 404:
        r = c.post("/collections", json=SCHEMA)
        if r.status_code != 409:   # 409: created by someone else in the meantime
            r.raise_for_status()
    else:
        r.raise_for_status()
    _ready = True


def document(job: dict) -> dict:
    rep = job.get("report") or {}
    return {"id": job["job_id"], "job_id": job["job_id"], "owner": job["owner"],
            "topic": str(job.get("topic") or ""), "summary": str(rep.get("summary") or ""),
            "sections": [str(s.get("title") or "") for s in rep.get("sections") or [] if isinstance(s, dict)],
            "at": int(job.get("finished_at") or time.time()),
            "page_token": str(job.get("page_token") or "")}


def add(job: dict) -> bool:
    """Upsert a done job's report. True when Typesense took it. Never raises."""
    if not _ok():
        return False
    try:
        doc = document(job)
        with typesense_store._client() as c:
            _ensure(c)
            r = c.post(f"/collections/{COLLECTION}/documents", params={"action": "upsert"}, json=doc)
            r.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001 - the report is saved either way
        _failed("upsert", e)
        return False


def search(owner: str, q: str, limit: int = 3) -> Optional[list[dict]]:
    """This owner's reports best matching ``q`` (empty: the latest), as Typesense documents.
    None when Typesense is unset or failing."""
    if not _ok() or not owner:
        return None
    params = {"q": q or "*", "query_by": QUERY_BY, "query_by_weights": QUERY_WEIGHTS,
              "filter_by": f"owner:={typesense_store._quote(owner)}",
              "sort_by": "at:desc" if not q else "_text_match:desc,at:desc",
              "per_page": max(1, min(int(limit), 10))}
    try:
        with typesense_store._client() as c:
            _ensure(c)
            r = c.get(f"/collections/{COLLECTION}/documents/search", params=params)
            r.raise_for_status()
            hits = r.json().get("hits") or []
    except Exception as e:  # noqa: BLE001 - search falls back to the stored jobs
        _failed("search", e)
        return None
    docs = [h.get("document") for h in hits if isinstance(h, dict) and isinstance(h.get("document"), dict)]
    return [d for d in docs if d.get("owner") == owner][:limit]    # belt and braces on the filter
