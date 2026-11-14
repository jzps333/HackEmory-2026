"""Tiny HTTP service on the SANDBOX server. The backend calls POST /run {"url": ...}.

Each request starts a fresh container, waits for its JSON, and the container is deleted (--rm).
This server holds no API keys except SANDBOX_TOKEN, which only lets the backend call it.

Run on the sandbox VM:
    pip install fastapi uvicorn
    SANDBOX_TOKEN=... uvicorn server:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import hmac
import json
import os
import subprocess
import sys
import threading
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from netguard import url_allowed  # noqa: E402  (pure module, no Playwright)

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

app = FastAPI(title="ScanSafe sandbox")


class RunRequest(BaseModel):
    url: str


@app.get("/health")
def health() -> dict:
    return {"ok": True}


def _container_cmd(name: str, url: str, *extra: str) -> list[str]:
    return [
        "docker", "run", "--rm", "--init", "--name", name,
        *(["--network", NETWORK] if NETWORK else []),
        "--memory", "1g", "--cpus", "1", "--pids-limit", "256",
        "--read-only", "--tmpfs", "/tmp", "--tmpfs", "/home/pwuser/.cache",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        IMAGE, url, *extra,   # passed as separate arguments, never through a shell
    ]


def _check(req: RunRequest, authorization: str) -> None:
    if not TOKEN or not hmac.compare_digest(authorization.encode(), f"Bearer {TOKEN}".encode()):
        raise HTTPException(status_code=401, detail="bad token")
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
    proc = subprocess.Popen(_container_cmd(name, req.url, "--stream"), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    timed_out = threading.Event()

    def _kill() -> None:
        timed_out.set()
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
        proc.kill()
    watchdog = threading.Timer(TIMEOUT_S, _kill)
    watchdog.start()

    def gen():
        result, tail, total = None, [], 0
        try:
            for line in proc.stdout:
                total += len(line)
                if total > MAX_STREAM_OUTPUT:
                    _kill()
                    yield json.dumps({"type": "error", "detail": "scan output too large"}) + "\n"
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
            proc.wait(timeout=15)
            if timed_out.is_set():
                yield json.dumps({"type": "error", "detail": "scan timed out"}) + "\n"
            elif isinstance(result, dict):
                yield json.dumps({"type": "result", "data": result}) + "\n"
            else:
                yield json.dumps({"type": "error", "detail": f"scan failed: {' | '.join(tail)[-300:]}"}) + "\n"
        finally:
            watchdog.cancel()
            if proc.poll() is None:                       # client went away mid-scan
                subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
                proc.kill()

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
