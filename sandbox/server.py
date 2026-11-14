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
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from netguard import url_allowed  # noqa: E402  (pure module, no Playwright)

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

TOKEN = os.environ.get("SANDBOX_TOKEN", "")
IMAGE = os.environ.get("SANDBOX_IMAGE", "scansafe-sandbox")
TIMEOUT_S = 45
# Optional dedicated Docker network for scan containers, so the host firewall can target its
# bridge (see README.md "Host firewall"). Unset = Docker's default bridge.
NETWORK = os.environ.get("SANDBOX_NETWORK", "")
MAX_OUTPUT = 3_000_000   # bytes of container stdout we accept

app = FastAPI(title="ScanSafe sandbox")


class RunRequest(BaseModel):
    url: str


@app.get("/health")
def health() -> dict:
    return {"ok": True}


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
