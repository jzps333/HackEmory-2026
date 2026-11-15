"""Tiny HTTP service on the SANDBOX server. The backend calls POST /run {"url": ...}.

Each request starts a fresh container, waits for its JSON, and the container is deleted (--rm).
This server holds no API keys except SANDBOX_TOKEN, which only lets the backend call it.

POST /operate/stream {"url", "plate", "hours"} is operator mode (see operate.py), a separate path
from scanning: it ONLY accepts https://scansafe-demo-sites.vercel.app/dogwood/... (else 400) and
streams the container's browser while it drives the made-up official Dogwood Parking app.
With {"adapter": "parkmobile", "url", "zone", "plate", "hours"|"minutes"} it instead fills in the
REAL ParkMobile web app (https://app.parkmobile.io only) and stops before payment; if
PARKMOBILE_STATE_FILE (default /etc/scansafe/parkmobile_state.json) exists, it is mounted read-only
into that container only (a saved, signed-in session of the person's own ParkMobile account).

Run on the sandbox VM:
    pip install fastapi uvicorn
    SANDBOX_TOKEN=... uvicorn server:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from netguard import url_allowed  # noqa: E402  (pure module, no Playwright)
from operate import (check_operate_request, check_parkmobile_request, clean_plate,  # noqa: E402
                     clean_zone, pm_minutes)

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

TOKEN = os.environ.get("SANDBOX_TOKEN", "")
IMAGE = os.environ.get("SANDBOX_IMAGE", "scansafe-sandbox")
TIMEOUT_S = 45
# Optional dedicated Docker network for scan containers, so the host firewall can target its
# bridge (see README.md "Host firewall"). Unset = Docker's default bridge.
NETWORK = os.environ.get("SANDBOX_NETWORK", "")
MAX_OUTPUT = 3_000_000   # bytes of container stdout we accept
MAX_STREAM_OUTPUT = 40_000_000   # /run/stream: frames included
OPERATE_TIMEOUT_S = 180          # /operate/stream: steps + up to 120 s waiting for approval
MAX_OPERATE_OUTPUT = 80_000_000
PARKMOBILE_TIMEOUT_S = 120       # /operate/stream adapter "parkmobile": no approval wait

app = FastAPI(title="ScanSafe sandbox")


class RunRequest(BaseModel):
    url: str


class OperateRequest(BaseModel):
    url: str
    plate: Any = None      # checked by operate.check_operate_request (400, not 422)
    hours: Any = None
    adapter: Any = None    # None = Dogwood (unchanged); "parkmobile" = the real ParkMobile web app
    zone: Any = None       # parkmobile only: 3-7 digits
    minutes: Any = None    # parkmobile only: instead of hours
    use_session: Any = False   # parkmobile only: True = the agent says the callee owns the saved session


@app.get("/health")
def health() -> dict:
    return {"ok": True}


def _container_cmd(name: str, *args: str, mounts: tuple = ()) -> list[str]:
    return [
        "docker", "run", "--rm", "--init", "--name", name,
        *(["--network", NETWORK] if NETWORK else []),
        "--memory", "1g", "--cpus", "1", "--pids-limit", "256",
        "--read-only", "--tmpfs", "/tmp", "--tmpfs", "/home/pwuser/.cache",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        *mounts,
        IMAGE, *args,   # passed as separate arguments, never through a shell
    ]


PARKMOBILE_STATE_DEFAULT = "/etc/scansafe/parkmobile_state.json"
PARKMOBILE_STATE_IN_CONTAINER = "/run/pm_state.json"     # operate.PM_STATE_PATH


def _parkmobile_mounts() -> tuple:
    """The saved ParkMobile session (one person's own account, captured on the Mac), mounted
    read-only, for adapter "parkmobile" runs that ask for it (use_session is True: the agent
    checked the callee is PARKMOBILE_OWNER_PHONE) and only if the file exists. Path from
    PARKMOBILE_STATE_FILE. Otherwise () and the run stays a guest run."""
    path = os.environ.get("PARKMOBILE_STATE_FILE") or PARKMOBILE_STATE_DEFAULT
    if not os.path.isabs(path) or any(c in path for c in ",:\n") or not os.path.isfile(path):
        return ()
    return ("-v", f"{path}:{PARKMOBILE_STATE_IN_CONTAINER}:ro")


def _check_token(authorization: str) -> None:
    if not TOKEN or not hmac.compare_digest(authorization.encode(), f"Bearer {TOKEN}".encode()):
        raise HTTPException(status_code=401, detail="bad token")


def _check(req: RunRequest, authorization: str) -> None:
    _check_token(authorization)
    ok, reason = url_allowed(req.url)
    if not ok:
        raise HTTPException(status_code=400, detail=f"url not allowed: {reason}")


@app.post("/run/stream")
def run_stream(req: RunRequest, authorization: str = Header(default="")) -> StreamingResponse:
    """Same scan as /run, but streams NDJSON while the browser works:
    {"type":"frame","jpeg":...,"t_ms":...} and {"type":"nav","url":...} lines as they happen,
    then exactly one {"type":"result","data":{...same as /run...}} or {"type":"error","detail":...}."""
    _check(req, authorization)
    name = f"scansafe-{uuid.uuid4().hex[:12]}"
    return _stream_container(name, _container_cmd(name, req.url, "--stream"), TIMEOUT_S,
                             MAX_STREAM_OUTPUT, "scan")


def operate_stream(req: OperateRequest, authorization: str = Header(default="")) -> StreamingResponse:
    """Operator mode (operate.py), NOT a scan. Only https://scansafe-demo-sites.vercel.app/dogwood/...
    (anything else: 400). Same NDJSON as /run/stream: frame / nav / step lines while the browser
    taps Install, Open, types the plate, taps hours-N and Pay (which only asks for approval in
    ScanSafe), then watches up to 120 s for the receipt; last line {"type":"result","data":{...}}
    with {"mode":"operate","status":"paid"|"waiting"|"failed","paid",...}."""
    _check_token(authorization)
    if req.adapter == "parkmobile":
        return _operate_parkmobile(req)
    if req.adapter is not None:
        raise HTTPException(status_code=400, detail="unknown adapter")
    ok, reason = check_operate_request(req.url, req.plate, req.hours)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)
    ok, reason = url_allowed(req.url)          # the usual network guard on top
    if not ok:
        raise HTTPException(status_code=400, detail=f"url not allowed: {reason}")
    name = f"scansafe-op-{uuid.uuid4().hex[:12]}"
    cmd = _container_cmd(name, "--operate", req.url, clean_plate(req.plate), str(int(req.hours)))
    return _stream_container(name, cmd, OPERATE_TIMEOUT_S, MAX_OPERATE_OUTPUT, "operate")


def _operate_parkmobile(req: OperateRequest) -> StreamingResponse:
    """adapter "parkmobile" (operate.py): the REAL https://app.parkmobile.io web app. Types the
    zone and plate, picks the duration, and stops at the first sign-in / contact-details /
    payment / price-review / robot-check screen. Never pays. Last line {"type":"result","data":
    {"mode":"operate","adapter":"parkmobile","status":"ready_to_pay"|"needs_sign_in"|
    "robot_check"|"failed","price_text"?,"zone_name"?,"stopped_at",...}}."""
    ok, reason = check_parkmobile_request(req.url, req.zone, req.plate, req.hours, req.minutes)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)
    ok, reason = url_allowed(req.url)          # the usual network guard on top
    if not ok:
        raise HTTPException(status_code=400, detail=f"url not allowed: {reason}")
    name = f"scansafe-pm-{uuid.uuid4().hex[:12]}"
    cmd = _container_cmd(name, "--operate-parkmobile", req.url, clean_zone(req.zone) or "-",
                         clean_plate(req.plate), str(pm_minutes(req.hours, req.minutes)),
                         mounts=_parkmobile_mounts() if req.use_session is True else ())
    return _stream_container(name, cmd, PARKMOBILE_TIMEOUT_S, MAX_OPERATE_OUTPUT, "parkmobile")


def _stream_container(name: str, cmd: list[str], timeout_s: float, max_output: int,
                      what: str) -> StreamingResponse:
    """Run one container and forward its frame/nav/step lines as NDJSON, then one result/error
    line. The container is removed on timeout, on too much output, or as soon as the client
    hangs up (an async generator: Starlette cancels it on disconnect even while we wait for the
    next line, so an operate run whose hours changed never keeps driving the page)."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    timed_out = threading.Event()

    def _remove() -> None:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)

    def _kill() -> None:
        timed_out.set()
        _remove()
        proc.kill()
    watchdog = threading.Timer(timeout_s, _kill)
    watchdog.start()

    async def gen():
        result, tail, total = None, [], 0
        loop = asyncio.get_running_loop()
        try:
            while True:
                line = await loop.run_in_executor(None, proc.stdout.readline)
                if not line:
                    break
                total += len(line)
                if total > max_output:
                    await loop.run_in_executor(None, _kill)
                    yield json.dumps({"type": "error", "detail": f"{what} output too large"}) + "\n"
                    return
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    tail = (tail + [line])[-5:]          # Playwright/Chrome noise on stderr
                    continue
                if isinstance(obj, dict) and obj.get("type") in ("frame", "nav", "step"):
                    yield line + "\n"
                else:
                    result = obj                          # the final plain result JSON
            await loop.run_in_executor(None, lambda: proc.wait(timeout=15))
            if timed_out.is_set():
                yield json.dumps({"type": "error", "detail": f"{what} timed out"}) + "\n"
            elif isinstance(result, dict):
                yield json.dumps({"type": "result", "data": result}) + "\n"
            else:
                yield json.dumps({"type": "error", "detail": f"{what} failed: {' | '.join(tail)[-300:]}"}) + "\n"
        finally:
            watchdog.cancel()
            if proc.poll() is None:                       # client went away mid-run
                proc.kill()
                threading.Thread(target=_remove, daemon=True).start()

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.post("/run")
def run(req: RunRequest, authorization: str = Header(default="")) -> dict:
    if not TOKEN or not hmac.compare_digest(authorization.encode(), f"Bearer {TOKEN}".encode()):
        raise HTTPException(status_code=401, detail="bad token")
    # Check the destination BEFORE starting a container. The container re-checks every
    # request (redirects, subresources) itself; this just refuses obvious SSRF early.
    ok, reason = url_allowed(req.url)
    if not ok:
        raise HTTPException(status_code=400, detail=f"url not allowed: {reason}")
    name = f"scansafe-{uuid.uuid4().hex[:12]}"
    cmd = [
        "docker", "run", "--rm", "--init", "--name", name,
        *(["--network", NETWORK] if NETWORK else []),
        "--memory", "1g", "--cpus", "1", "--pids-limit", "256",
        "--read-only", "--tmpfs", "/tmp", "--tmpfs", "/home/pwuser/.cache",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        IMAGE, req.url,   # passed as one argument, never through a shell
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        # Killing the docker CLI does not stop the container: remove it explicitly.
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
        raise HTTPException(status_code=504, detail="scan timed out")
    if len(proc.stdout) > MAX_OUTPUT:
        raise HTTPException(status_code=500, detail="scan output too large")
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        raise HTTPException(status_code=500, detail=f"scan failed: {proc.stderr[-300:]}")
