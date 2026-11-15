"""Research jobs (plugins/research): one Tiger row per job, plus an in-process copy.

research_jobs(job_id text pk, owner, topic, details, status, progress jsonb, report jsonb,
reason, page_token, started_at, finished_at, created_at). `owner` is
api.account_crypto.phone_hash(phone): the phone number itself is NEVER stored here
(api/research.py keeps it in process memory for the life of the job, only to text and call
back). `page_token` (set when the job is done) is the secret in the results page link
/research/r/<token>.

Every write goes to memory first (this process runs the jobs, so its copy is the freshest), then
to Tiger when TIGER_DATABASE_URL is set. Reads try memory, then Tiger. A Tiger error is logged by
type only and Tiger is skipped for TIGER_RETRY_S. Nothing here ever raises.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Optional

from data import tiger_store

log = logging.getLogger("scansafe.research_store")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS research_jobs (
  job_id      TEXT PRIMARY KEY,
  owner       TEXT NOT NULL,
  topic       TEXT NOT NULL,
  details     TEXT NOT NULL DEFAULT '',
  status      TEXT NOT NULL,
  progress    JSONB NOT NULL DEFAULT '[]'::jsonb,
  report      JSONB,
  reason      TEXT,
  page_token  TEXT,
  started_at  TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS research_jobs_owner ON research_jobs (owner, created_at DESC);
ALTER TABLE research_jobs ADD COLUMN IF NOT EXISTS page_token TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS research_jobs_page_token ON research_jobs (page_token);
"""
UPSERT_SQL = (
    "INSERT INTO research_jobs (job_id, owner, topic, details, status, progress, report, reason, "
    "page_token, started_at, finished_at) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, "
    "to_timestamp(%s), to_timestamp(%s)) ON CONFLICT (job_id) DO UPDATE SET "
    "status = EXCLUDED.status, progress = EXCLUDED.progress, report = EXCLUDED.report, "
    "reason = EXCLUDED.reason, page_token = EXCLUDED.page_token, "
    "started_at = EXCLUDED.started_at, finished_at = EXCLUDED.finished_at")
SELECT_SQL = (
    "SELECT job_id, owner, topic, details, status, progress, report, reason, page_token, "
    "extract(epoch from started_at) AS started_at, extract(epoch from finished_at) AS finished_at "
    "FROM research_jobs WHERE {} = %s")
FIELDS = ("job_id", "owner", "topic", "details", "status", "progress", "report", "reason",
          "page_token", "started_at", "finished_at")
MAX_MEM_JOBS = 500
TIGER_RETRY_S = 60.0

_lock = threading.Lock()
_mem: "OrderedDict[str, dict]" = OrderedDict()
_schema_ready = False
_tiger_down_until = 0.0


def reset() -> None:   # tests
    global _schema_ready, _tiger_down_until
    with _lock:
        _mem.clear()
        _schema_ready = False
        _tiger_down_until = 0.0


def _tiger_ok() -> bool:
    return tiger_store.is_configured() and time.monotonic() >= _tiger_down_until


def _tiger_failed(what: str, e: Exception) -> None:
    global _tiger_down_until
    _tiger_down_until = time.monotonic() + TIGER_RETRY_S
    log.warning("research jobs: Tiger %s failed (%s)", what, type(e).__name__)   # never the URL


def _conn():
    global _schema_ready
    conn = tiger_store._connect()
    if not _schema_ready:
        try:
            conn.execute(SCHEMA_SQL)
        except Exception:
            conn.close()
            raise
        _schema_ready = True
    return conn


def _copy(job: dict) -> dict:
    return json.loads(json.dumps({k: job.get(k) for k in FIELDS}))


def save(job: dict) -> None:
    """Insert or update one job (only the FIELDS above are kept; anything else is dropped)."""
    row = _copy(job)
    with _lock:
        _mem[row["job_id"]] = row
        _mem.move_to_end(row["job_id"])
        while len(_mem) > MAX_MEM_JOBS:
            _mem.popitem(last=False)
    if not _tiger_ok():
        return
    try:
        with _conn() as conn:
            conn.execute(UPSERT_SQL, (
                row["job_id"], row["owner"], row["topic"], row["details"] or "", row["status"],
                json.dumps(row["progress"] or []),
                None if row["report"] is None else json.dumps(row["report"]),
                row["reason"], row["page_token"], row["started_at"], row["finished_at"]))
    except Exception as e:  # noqa: BLE001 - the job carries on from memory
        _tiger_failed("write", e)


def get(job_id: str) -> Optional[dict]:
    with _lock:
        row = _mem.get(job_id)
        if row is not None:
            return _copy(row)
    return _tiger_get("job_id", job_id)


def get_by_token(token: str) -> Optional[dict]:
    """The job whose results page token is ``token`` (only done jobs have one)."""
    if not isinstance(token, str) or not token:
        return None
    with _lock:
        row = next((r for r in _mem.values() if r.get("page_token") == token), None)
        if row is not None:
            return _copy(row)
    return _tiger_get("page_token", token)


def done_for_owner(owner: str, limit: int = 100) -> list[dict]:
    """This owner's done jobs, newest first (memory and Tiger merged; memory wins)."""
    if not isinstance(owner, str) or not owner:
        return []
    with _lock:
        jobs = {r["job_id"]: _copy(r) for r in _mem.values()
                if r.get("owner") == owner and r.get("status") == "done"}
    if _tiger_ok():
        try:
            with _conn() as conn:
                rows = conn.execute(
                    SELECT_SQL.format("owner") + " AND status = 'done' ORDER BY finished_at DESC LIMIT %s",
                    (owner, max(1, min(int(limit), 500)))).fetchall()
            for r in rows:
                if r["job_id"] not in jobs:
                    jobs[r["job_id"]] = _row(r)
        except Exception as e:  # noqa: BLE001
            _tiger_failed("read", e)
    out = sorted(jobs.values(), key=lambda j: j.get("finished_at") or 0, reverse=True)
    return out[:limit]


def _tiger_get(column: str, value: str) -> Optional[dict]:
    if column not in ("job_id", "page_token") or not _tiger_ok():
        return None
    try:
        with _conn() as conn:
            r = conn.execute(SELECT_SQL.format(column), (value,)).fetchone()
    except Exception as e:  # noqa: BLE001
        _tiger_failed("read", e)
        return None
    return _row(r) if r else None


def _row(r) -> dict:
    out = {k: r[k] for k in FIELDS}
    for k in ("progress", "report"):
        if isinstance(out[k], str):
            try:
                out[k] = json.loads(out[k])
            except ValueError:
                out[k] = None
    out["progress"] = out["progress"] or []
    for k in ("started_at", "finished_at"):
        out[k] = float(out[k]) if out[k] is not None else None
    return out
