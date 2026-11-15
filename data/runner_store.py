"""The Toolstone helper app ("runner") relay: pairings, jobs and live frames.

Pairings: one runner per person. Tiger table `runners` (owner = api.account_crypto.phone_hash, so the
phone itself is never stored; only sha256(runner token) is kept, never the token). Without
TIGER_DATABASE_URL (or while Tiger is failing) pairings live in memory for this process. Pairings
are also cached in memory, so a runner polling every few seconds costs no database round trip;
`last_seen` is written back to Tiger at most every LAST_SEEN_WRITE_S.

Jobs and frames live in memory only (single uvicorn process): a job is `queued` until its runner
fetches it (`running`), then `done` or `failed`. Jobs older than JOB_TTL_S are dropped, and at most
MAX_JOBS are kept. Contract: docs/superpowers/specs/2026-11-15-helper-app-contract.md.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
from typing import Any, Optional

from data import tiger_store

log = logging.getLogger("scansafe.runner")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runners (
  owner      TEXT PRIMARY KEY,
  runner_id  TEXT NOT NULL UNIQUE,
  token_hash TEXT NOT NULL UNIQUE,
  name       TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen  TIMESTAMPTZ
);
"""
_COLS = "runner_id, token_hash, owner, name, extract(epoch from created_at) AS created_at, " \
        "extract(epoch from last_seen) AS last_seen"

KINDS = ("form_fill", "form_submit", "vercel_status", "vercel_redeploy", "connections_list")
ONLINE_S = 60                    # connected = seen in the last minute
JOB_TTL_S = 15 * 60              # jobs (and their frames) are dropped after this
MAX_JOBS = 200                   # all runners together; the oldest are dropped beyond this
MAX_QUEUED_PER_RUNNER = 20
MAX_NAME = 60
MAX_ARGS_BYTES = 4 * 1024
MAX_RESULT_BYTES = 16 * 1024
MAX_FRAME_BYTES = 400 * 1024
MAX_NOTE = 200
MAX_ERROR = 200
MAX_PROGRESS = 20
LAST_SEEN_WRITE_S = 30.0
TIGER_RETRY_S = 60.0
JOB_ID_RE = re.compile(r"^[0-9a-f]{16}$")
JPEG_MAGIC = b"\xff\xd8"

_lock = threading.Lock()
_by_owner: dict[str, dict] = {}       # owner -> runner {runner_id, token_hash, owner, name, created_at, last_seen}
_owner_by_token: dict[str, str] = {}  # token_hash -> owner
_jobs: dict[str, dict] = {}           # job_id -> job (insertion order = creation order)
_schema_ready = False
_tiger_down_until = 0.0


class RunnerError(ValueError):
    """A request the relay refuses: HTTP status, short error code, message for people."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def now() -> float:
    """The relay clock (unix seconds). Tests monkeypatch it."""
    return time.time()


def reset() -> None:   # tests
    global _schema_ready, _tiger_down_until
    with _lock:
        _by_owner.clear()
        _owner_by_token.clear()
        _jobs.clear()
        _schema_ready = False
        _tiger_down_until = 0.0


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# --- Tiger -----------------------------------------------------------------------------------------

def _tiger_ok() -> bool:
    return tiger_store.is_configured() and time.monotonic() >= _tiger_down_until


def _tiger_failed(what: str, e: Exception) -> None:
    global _tiger_down_until
    _tiger_down_until = time.monotonic() + TIGER_RETRY_S
    log.warning("runner store: Tiger %s failed (%s)", what, type(e).__name__)   # never the URL


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


def _row(row: Any) -> dict:
    """A runners row (psycopg dict_row or a plain tuple in _COLS order) as a runner dict."""
    if not isinstance(row, dict):
        row = dict(zip(("runner_id", "token_hash", "owner", "name", "created_at", "last_seen"), row))
    seen = row.get("last_seen")
    return {"runner_id": str(row["runner_id"]), "token_hash": str(row["token_hash"]), "owner": str(row["owner"]),
            "name": str(row["name"]), "created_at": float(row.get("created_at") or 0),
            "last_seen": float(seen) if seen is not None else None,
            "seen_written": float(seen) if seen is not None else 0.0}


def _tiger_one(where: str, value: str) -> Optional[dict]:
    if not _tiger_ok():
        return None
    try:
        with _conn() as conn:
            row = conn.execute(f"SELECT {_COLS} FROM runners WHERE {where} = %s", (value,)).fetchone()
        return _row(row) if row else None
    except Exception as e:  # noqa: BLE001 - fall back to memory, never fail the call
        _tiger_failed("read", e)
        return None


# --- pairings --------------------------------------------------------------------------------------

def _public(r: dict) -> dict:
    return {k: r[k] for k in ("runner_id", "owner", "name", "created_at", "last_seen")}


def clean_name(name: Any) -> str:
    text = " ".join(str(name or "").split())          # also drops control characters like \n
    text = "".join(ch for ch in text if ch.isprintable())[:MAX_NAME].strip()
    return text or "My computer"


def pair(owner: str, name: Any) -> tuple[str, str]:
    """A new runner for this person, replacing any older one (its token stops working and its
    unfinished jobs fail with `runner_replaced`). Returns (runner_token, runner_id); the token
    is shown once and only its sha256 is kept."""
    token = secrets.token_urlsafe(32)
    runner = {"runner_id": secrets.token_hex(6), "token_hash": token_hash(token), "owner": owner,
              "name": clean_name(name), "created_at": now(), "last_seen": None, "seen_written": 0.0}
    if _tiger_ok():
        try:
            with _conn() as conn:
                conn.execute(
                    "INSERT INTO runners (owner, runner_id, token_hash, name, created_at, last_seen) "
                    "VALUES (%s, %s, %s, %s, to_timestamp(%s), NULL) ON CONFLICT (owner) DO UPDATE SET "
                    "runner_id = EXCLUDED.runner_id, token_hash = EXCLUDED.token_hash, name = EXCLUDED.name, "
                    "created_at = EXCLUDED.created_at, last_seen = NULL",
                    (owner, runner["runner_id"], runner["token_hash"], runner["name"], runner["created_at"]))
        except Exception as e:  # noqa: BLE001 - memory still pairs it for this process
            _tiger_failed("write", e)
    with _lock:
        old = _by_owner.get(owner)
        if old is not None:
            _owner_by_token.pop(old["token_hash"], None)
            for job in _jobs.values():
                if job["runner_id"] == old["runner_id"] and job["status"] in ("queued", "running"):
                    job.update(status="failed", error="runner_replaced", updated_at=now())
        _by_owner[owner] = runner
        _owner_by_token[runner["token_hash"]] = owner
    log.info("runner paired: %s", runner["runner_id"])
    return token, runner["runner_id"]


def runner_for_owner(owner: str) -> Optional[dict]:
    with _lock:
        r = _by_owner.get(owner)
        if r is not None:
            return _public(r)
    r = _tiger_one("owner", owner)
    if r is None:
        return None
    with _lock:
        r = _by_owner.setdefault(owner, r)            # a pairing made meanwhile wins
        _owner_by_token[r["token_hash"]] = owner
        return _public(r)


def runner_for_token(token: str) -> Optional[dict]:
    """The runner this secret belongs to, or None (unknown or replaced token)."""
    if not isinstance(token, str) or not token or len(token) > 200:
        return None
    th = token_hash(token)
    with _lock:
        owner = _owner_by_token.get(th)
        r = _by_owner.get(owner) if owner else None
        if r is not None and hmac.compare_digest(r["token_hash"], th):
            return _public(r)
    r = _tiger_one("token_hash", th)
    if r is None or not hmac.compare_digest(r["token_hash"], th):
        return None
    with _lock:
        cur = _by_owner.get(r["owner"])
        if cur is not None and cur["runner_id"] != r["runner_id"]:
            return None                                # replaced here after Tiger last saw it
        r = _by_owner.setdefault(r["owner"], r)
        _owner_by_token[th] = r["owner"]
        return _public(r)


def touch(runner_id: str) -> None:
    """The runner just talked to us: last_seen = now (memory; Tiger at most every 30 s)."""
    t = now()
    write = None
    with _lock:
        r = next((r for r in _by_owner.values() if r["runner_id"] == runner_id), None)
        if r is None:
            return
        r["last_seen"] = t
        if t - r["seen_written"] >= LAST_SEEN_WRITE_S:
            r["seen_written"] = t
            write = (t, runner_id)
    if write and _tiger_ok():
        try:
            with _conn() as conn:
                conn.execute("UPDATE runners SET last_seen = to_timestamp(%s) WHERE runner_id = %s", write)
        except Exception as e:  # noqa: BLE001
            _tiger_failed("write", e)


def is_online(runner: Optional[dict]) -> bool:
    seen = runner.get("last_seen") if runner else None
    return seen is not None and now() - seen <= ONLINE_S


# --- jobs --------------------------------------------------------------------------------------------

def _purge_locked() -> None:
    cutoff = now() - JOB_TTL_S
    for jid in [jid for jid, j in _jobs.items() if j["created_at"] < cutoff]:
        del _jobs[jid]
    while len(_jobs) > MAX_JOBS:
        _jobs.pop(next(iter(_jobs)))


def _json_bytes(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())


def check_args(kind: Any, args: Any) -> dict:
    if not isinstance(kind, str) or kind not in KINDS:
        raise RunnerError(400, "bad_kind", "The helper app can't run that.")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise RunnerError(400, "bad_args", "args must be a JSON object.")
    try:
        size = _json_bytes(args)
    except (TypeError, ValueError):
        raise RunnerError(400, "bad_args", "args must be plain JSON.") from None
    if size > MAX_ARGS_BYTES:
        raise RunnerError(400, "bad_args", f"args must be under {MAX_ARGS_BYTES} bytes.")
    if kind == "form_fill":
        url = args.get("url") or ""
        if not isinstance(url, str) or (url and not re.match(r"^https?://", url.strip(), re.I)):
            raise RunnerError(400, "bad_args", "form_fill needs an http(s) url (or none for the active tab).")
    return args


def create_job(runner: dict, kind: Any, args: Any) -> str:
    args = check_args(kind, args)
    t = now()
    with _lock:
        _purge_locked()
        rid = runner["runner_id"]
        if kind == "form_submit":
            fill = _jobs.get(args.get("fill_job")) if isinstance(args.get("fill_job"), str) else None
            if fill is None or fill["runner_id"] != rid or fill["kind"] != "form_fill":
                raise RunnerError(400, "bad_args", "form_submit needs the job_id of this computer's form_fill.")
        if sum(1 for j in _jobs.values() if j["runner_id"] == rid and j["status"] == "queued") >= MAX_QUEUED_PER_RUNNER:
            raise RunnerError(429, "too_many_jobs", "That computer already has a lot of work waiting.")
        job_id = secrets.token_hex(8)
        _jobs[job_id] = {"job_id": job_id, "runner_id": rid, "kind": kind, "args": args, "status": "queued",
                         "progress": [], "result": None, "error": None, "frame": None, "frame_seq": 0,
                         "created_at": t, "updated_at": t}
        _purge_locked()
    log.info("runner job queued: %s %s for %s", job_id, kind, rid)
    return job_id


def claim_next(runner_id: str) -> Optional[dict]:
    """The oldest queued job of this runner, now `running`: {"job_id", "kind", "args"} or None."""
    with _lock:
        _purge_locked()
        job = next((j for j in _jobs.values() if j["runner_id"] == runner_id and j["status"] == "queued"), None)
        if job is None:
            return None
        job.update(status="running", updated_at=now())
        return {"job_id": job["job_id"], "kind": job["kind"], "args": json.loads(json.dumps(job["args"]))}


def view(job_id: str) -> Optional[dict]:
    """What the agent sees of a job."""
    with _lock:
        _purge_locked()
        j = _jobs.get(job_id) if isinstance(job_id, str) else None
        if j is None:
            return None
        return {"job_id": j["job_id"], "kind": j["kind"], "status": j["status"], "progress": list(j["progress"]),
                "result": json.loads(json.dumps(j["result"])) if j["result"] is not None else None,
                "error": j["error"], "frame_seq": j["frame_seq"]}


def _own_locked(runner_id: str, job_id: str) -> dict:
    _purge_locked()
    j = _jobs.get(job_id) if isinstance(job_id, str) else None
    if j is None or not hmac.compare_digest(j["runner_id"], runner_id):
        raise RunnerError(404, "unknown_job", "No job with that id.")
    return j


def check_owner(runner_id: str, job_id: str) -> None:
    """RunnerError 404 unless this job exists and belongs to this runner."""
    with _lock:
        _own_locked(runner_id, job_id)


def put_frame(runner_id: str, job_id: str, data: bytes) -> int:
    if not data or not data.startswith(JPEG_MAGIC):
        raise RunnerError(400, "bad_frame", "Send one JPEG image.")
    if len(data) > MAX_FRAME_BYTES:
        raise RunnerError(413, "frame_too_large", f"Frames must be under {MAX_FRAME_BYTES // 1024} KB.")
    with _lock:
        j = _own_locked(runner_id, job_id)
        j["frame"] = bytes(data)
        j["frame_seq"] += 1
        j["updated_at"] = now()
        return j["frame_seq"]


def get_frame(job_id: str) -> Optional[tuple[bytes, int]]:
    """(latest JPEG, its sequence number), or None when the job has none (or doesn't exist)."""
    with _lock:
        _purge_locked()
        j = _jobs.get(job_id) if isinstance(job_id, str) else None
        if j is None or j["frame"] is None:
            return None
        return j["frame"], j["frame_seq"]


def job_exists(job_id: str) -> bool:
    with _lock:
        _purge_locked()
        return isinstance(job_id, str) and job_id in _jobs


def add_progress(runner_id: str, job_id: str, note: Any) -> None:
    if not isinstance(note, str) or not note.strip():
        raise RunnerError(400, "bad_note", "note must be a short text.")
    note = "".join(ch for ch in " ".join(note.split()) if ch.isprintable())[:MAX_NOTE]
    with _lock:
        j = _own_locked(runner_id, job_id)
        j["progress"].append(note)
        del j["progress"][:-MAX_PROGRESS]
        j["updated_at"] = now()


def set_result(runner_id: str, job_id: str, status: Any, result: Any, error: Any) -> None:
    if status not in ("done", "failed"):
        raise RunnerError(400, "bad_status", 'status must be "done" or "failed".')
    if result is not None and not isinstance(result, dict):
        raise RunnerError(400, "bad_result", "result must be a JSON object.")
    if result is not None:
        try:
            size = _json_bytes(result)
        except (TypeError, ValueError):
            raise RunnerError(400, "bad_result", "result must be plain JSON.") from None
        if size > MAX_RESULT_BYTES:
            raise RunnerError(413, "result_too_large", f"result must be under {MAX_RESULT_BYTES // 1024} KB.")
    if error is not None and not isinstance(error, str):
        raise RunnerError(400, "bad_error", "error must be a short text.")
    error = "".join(ch for ch in " ".join(error.split()) if ch.isprintable())[:MAX_ERROR] if error else None
    with _lock:
        j = _own_locked(runner_id, job_id)
        if j["status"] != "running":
            raise RunnerError(409, "not_running", "This job isn't running (it already finished).")
        j.update(status=status, result=result, error=error, updated_at=now())
    log.info("runner job %s: %s", job_id, status)
