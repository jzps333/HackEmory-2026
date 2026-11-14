"""Tiny HTTP service on the SANDBOX server. The backend calls POST /run {"url": ...}.

Each request starts a fresh container, waits for its JSON, and the container is deleted (--rm).
This server holds no API keys except SANDBOX_TOKEN, which only lets the backend call it.

Run on the sandbox VM:
    pip install fastapi uvicorn
    SANDBOX_TOKEN=... uvicorn server:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import json
import os
import subprocess

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

TOKEN = os.environ.get("SANDBOX_TOKEN", "")
IMAGE = os.environ.get("SANDBOX_IMAGE", "scansafe-sandbox")
TIMEOUT_S = 45

app = FastAPI(title="ScanSafe sandbox")


class RunRequest(BaseModel):
    url: str


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/run")
def run(req: RunRequest, authorization: str = Header(default="")) -> dict:
    if not TOKEN or authorization != f"Bearer {TOKEN}":
        raise HTTPException(status_code=401, detail="bad token")
    if not req.url.startswith(("http://", "https://")) or len(req.url) > 2000:
        raise HTTPException(status_code=400, detail="not a web link")
    cmd = [
        "docker", "run", "--rm",
        "--memory", "1g", "--cpus", "1", "--pids-limit", "256",
        "--read-only", "--tmpfs", "/tmp", "--tmpfs", "/home/pwuser/.cache",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        IMAGE, req.url,   # passed as one argument, never through a shell
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="scan timed out")
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        raise HTTPException(status_code=500, detail=f"scan failed: {proc.stderr[-300:]}")
