"""Relay between the FaceTime agent and the Toolstone helper app ("runner") on the user's computer.

The helper app connects OUT to us (the laptop is behind the user's Wi-Fi), long-polls for jobs, and
posts back screen frames, progress notes and a result. Contract (keep in sync):
docs/superpowers/specs/2026-11-15-helper-app-contract.md.

Person (phone sign-in token, Bearer or the ss_session cookie, api.session.current_phone):
  POST /runner/pair    {"name"}  -> {"runner_token" (shown once), "runner_id"}; replaces the older runner
  GET  /runner/status            -> {"connected", "name", "last_seen"}
Runner (`Authorization: Runner <runner_token>`; every call updates last_seen):
  GET  /runner/next?wait=0..25                -> {"job": null | {"job_id", "kind", "args"}} (long-poll)
  POST /runner/jobs/{job_id}/frame            raw JPEG <= 400 KB -> {"ok": true}
  POST /runner/jobs/{job_id}/progress {"note"}                 -> {"ok": true}
  POST /runner/jobs/{job_id}/result {"status", "result", "error"} -> {"ok": true}
  A runner only ever sees its own jobs (404 otherwise).
Agent (X-Agent-Key, as api.dogwood._agent_ok):
  POST /runner/jobs {"phone", "kind", "args"} -> {"job_id"} | 404 no_runner | 409 runner_offline | 400 bad_kind
  GET  /runner/jobs/{job_id}                  -> {"job_id", "kind", "status", "progress", "result", "error", "frame_seq"}
  GET  /runner/jobs/{job_id}/frame            -> the latest JPEG, or 204 when none yet
Demo: GET /demo/forms/permit (api/demo_forms.py; nothing is sent or stored).

Errors: {"ok": false, "error", "message"}. Phones and tokens are never logged: people are keyed by
phone_hash(phone) and runners by sha256(token).
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from typing import Any, Optional, Union

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from api import demo_forms, session
from api.dogwood import _agent_ok
from api.routes_memory import _e164
from data import runner_store as store
from data.runner_store import RunnerError

router = APIRouter()

MAX_WAIT_S = 25.0
POLL_S = 0.25
MAX_JSON_BODY = 32 * 1024
NO_STORE = {"Cache-Control": "no-store"}
PAIR_HINT = "Connect this computer again: python3 runner/toolstone_runner.py pair"


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": code, "message": message}, status_code=status, headers=NO_STORE)


def _refused(e: RunnerError) -> JSONResponse:
    return _error(e.status, e.code, e.message)


def _owner(phone: str) -> str:
    from api.account_crypto import phone_hash
    return phone_hash(phone)


async def _read_limited(request: Request, limit: int) -> Optional[bytes]:
    """The raw body, or None once it is over `limit` bytes (stops reading there)."""
    declared = request.headers.get("content-length") or ""
    if declared.isdigit() and int(declared) > limit:
        return None
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > limit:
            return None
    return bytes(data)


async def _json(request: Request, required: bool = True) -> Union[dict, JSONResponse]:
    raw = await _read_limited(request, MAX_JSON_BODY)
    if raw is None:
        return _error(413, "body_too_large", "That request is too big.")
    if not raw.strip() and not required:
        return {}
    try:
        body = json.loads(raw)
    except ValueError:
        return _error(400, "bad_json", "Send a JSON body.")
    if not isinstance(body, dict):
        return _error(400, "bad_json", "Send a JSON object.")
    return body


# --- runner auth -------------------------------------------------------------------------------------

def _runner_sync(authorization: str) -> Optional[dict]:
    scheme, _, value = (authorization or "").strip().partition(" ")
    if scheme.lower() != "runner" or not value.strip():
        return None
    runner = store.runner_for_token(value.strip())
    if runner is not None:
        store.touch(runner["runner_id"])
    return runner


async def _runner(request: Request) -> Union[dict, JSONResponse]:
    """The authenticated runner (and last_seen = now), or a 401. Tiger may be asked on a cache
    miss, so this runs in the threadpool, never on the event loop."""
    runner = await run_in_threadpool(_runner_sync, request.headers.get("authorization") or "")
    if runner is None:
        return _error(401, "bad_runner_token", "This computer isn't connected. " + PAIR_HINT)
    return runner


# --- person -----------------------------------------------------------------------------------------

@router.post("/runner/pair")
async def runner_pair(request: Request):
    phone = await run_in_threadpool(session.current_phone, request)
    if not phone:
        return _error(401, "signed_out", "Sign in with your phone number first.")
    body = await _json(request, required=False)
    if isinstance(body, JSONResponse):
        return body
    name = body.get("name")
    if name is not None and not isinstance(name, str):
        return _error(400, "bad_name", "name must be text.")
    try:
        token, runner_id = await run_in_threadpool(store.pair, _owner(phone), name)
    except store.PairingUnavailable:
        return _error(503, "pairing_unavailable", "Couldn't save the pairing right now. Try again in a minute.")
    return JSONResponse({"runner_token": token, "runner_id": runner_id}, headers=NO_STORE)


@router.get("/runner/status")
def runner_status(request: Request):
    phone = session.current_phone(request)
    if not phone:
        return _error(401, "signed_out", "Sign in with your phone number first.")
    runner = store.runner_for_owner(_owner(phone))
    seen = runner["last_seen"] if runner else None
    return JSONResponse({"connected": store.is_online(runner), "name": runner["name"] if runner else None,
                         "last_seen": int(seen) if seen is not None else None}, headers=NO_STORE)


# --- runner -----------------------------------------------------------------------------------------

def _wait_seconds(raw: Any) -> float:
    try:
        secs = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(secs, MAX_WAIT_S)) if math.isfinite(secs) else 0.0


@router.get("/runner/next")
async def runner_next(request: Request, wait: str = "0"):
    """Long-poll: the oldest queued job (now `running`) or {"job": null} after `wait` seconds.
    Sleeps with asyncio, so a waiting runner never holds a worker thread or the event loop."""
    runner = await _runner(request)
    if isinstance(runner, JSONResponse):
        return runner
    rid = runner["runner_id"]
    deadline = time.monotonic() + _wait_seconds(wait)
    job = None
    while True:
        try:
            gone = await request.is_disconnected()
        except Exception:  # noqa: BLE001 - treat an odd transport as still connected
            gone = False
        if gone:   # don't hand a job to a runner that can no longer receive it
            return Response(status_code=204)
        job = store.claim_next(rid)
        if job is not None:
            break
        left = deadline - time.monotonic()
        if left <= 0:
            break
        await asyncio.sleep(min(POLL_S, left))
    await run_in_threadpool(store.touch, rid)
    return JSONResponse({"job": job}, headers=NO_STORE)


@router.post("/runner/jobs/{job_id}/frame")
async def runner_frame(job_id: str, request: Request):
    runner = await _runner(request)
    if isinstance(runner, JSONResponse):
        return runner
    try:
        store.check_owner(runner["runner_id"], job_id)
    except RunnerError as e:
        return _refused(e)
    data = await _read_limited(request, store.MAX_FRAME_BYTES)   # the raw JPEG, never more than 400 KB
    if data is None:
        return _error(413, "frame_too_large", f"Frames must be under {store.MAX_FRAME_BYTES // 1024} KB.")
    try:
        store.put_frame(runner["runner_id"], job_id, data)
    except RunnerError as e:
        return _refused(e)
    return {"ok": True}


@router.post("/runner/jobs/{job_id}/progress")
async def runner_progress(job_id: str, request: Request):
    runner = await _runner(request)
    if isinstance(runner, JSONResponse):
        return runner
    body = await _json(request)
    if isinstance(body, JSONResponse):
        return body
    try:
        store.add_progress(runner["runner_id"], job_id, body.get("note"))
    except RunnerError as e:
        return _refused(e)
    return {"ok": True}


@router.post("/runner/jobs/{job_id}/result")
async def runner_result(job_id: str, request: Request):
    runner = await _runner(request)
    if isinstance(runner, JSONResponse):
        return runner
    body = await _json(request)
    if isinstance(body, JSONResponse):
        return body
    try:
        store.set_result(runner["runner_id"], job_id, body.get("status"), body.get("result"), body.get("error"))
    except RunnerError as e:
        return _refused(e)
    return {"ok": True}


# --- agent ------------------------------------------------------------------------------------------

def _queue_job(phone: str, kind: str, args: dict) -> Union[dict, JSONResponse]:
    runner = store.runner_for_owner(_owner(phone))
    if runner is None:
        return _error(404, "no_runner", "This caller hasn't connected a computer yet. "
                                        "They can run: python3 runner/toolstone_runner.py pair")
    if not store.is_online(runner):
        return _error(409, "runner_offline", "Their computer's helper app isn't running right now.")
    try:
        return {"job_id": store.create_job(runner, kind, args)}
    except RunnerError as e:
        return _refused(e)


@router.post("/runner/jobs")
async def agent_create_job(request: Request):
    bad = _agent_ok(request)
    if bad is not None:
        return bad
    body = await _json(request)
    if isinstance(body, JSONResponse):
        return body
    kind = body.get("kind")
    try:
        args = store.check_args(kind, body.get("args"))
    except RunnerError as e:
        return _refused(e)
    phone = _e164(body.get("phone"))
    if phone is None:
        return _error(400, "bad_phone", "A caller phone number is required.")
    out = await run_in_threadpool(_queue_job, phone, kind, args)
    return out if isinstance(out, JSONResponse) else JSONResponse(out, headers=NO_STORE)


@router.get("/runner/jobs/{job_id}")
def agent_job(job_id: str, request: Request):
    bad = _agent_ok(request)
    if bad is not None:
        return bad
    job = store.view(job_id)
    if job is None:
        return _error(404, "unknown_job", "No job with that id (jobs expire after 15 minutes).")
    return JSONResponse(job, headers=NO_STORE)


@router.get("/runner/jobs/{job_id}/frame")
def agent_frame(job_id: str, request: Request):
    bad = _agent_ok(request)
    if bad is not None:
        return bad
    frame = store.get_frame(job_id)
    if frame is None:
        if not store.job_exists(job_id):
            return _error(404, "unknown_job", "No job with that id (jobs expire after 15 minutes).")
        return Response(status_code=204, headers=NO_STORE)
    data, seq = frame
    return Response(data, media_type="image/jpeg",
                    headers={**NO_STORE, "X-Frame-Seq": str(seq), "X-Content-Type-Options": "nosniff"})


# --- demo -------------------------------------------------------------------------------------------

@router.get("/demo/forms/permit", response_class=HTMLResponse)
def demo_permit_form() -> HTMLResponse:
    return demo_forms.permit_page()
