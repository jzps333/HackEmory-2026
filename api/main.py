"""ScanSafe backend. Run: uvicorn api.main:app --reload"""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api import config
from api.scan import scan
from api.schema import ScanResult

app = FastAPI(title="ScanSafe")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ScanRequest(BaseModel):
    url: str                          # whatever the QR code contained
    lat: Optional[float] = None       # only sent if the user agreed to share location
    lng: Optional[float] = None


@app.get("/health")
def health() -> dict:
    return {"ok": True, "mock_mode": not config.SANDBOX_URL}


@app.post("/scan", response_model=ScanResult)
def scan_endpoint(req: ScanRequest) -> ScanResult:
    location = [req.lat, req.lng] if req.lat is not None and req.lng is not None else None
    return scan(req.url.strip(), location)
