"""ScanSafe backend. Run: uvicorn api.main:app --reload"""
from __future__ import annotations

from typing import Optional

from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api import config
from api.routes_data import flagged_before, record_scan
from api.routes_data import router as data_router
from api.routes_pay import router as pay_router
from api.scan import scan
from chert.imessage import router as chert_router
from api.schema import ScanResult

app = FastAPI(title="ScanSafe")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(data_router)   # /report, /pins, /search, /stats/*
app.include_router(pay_router)    # /pay (devnet only)
app.include_router(chert_router)  # /chert/webhook (Chert call + message events, signed)


class ScanRequest(BaseModel):
    url: str                          # whatever the QR code contained
    lat: Optional[float] = None       # only sent if the user agreed to share location
    lng: Optional[float] = None


@app.get("/health")
def health() -> dict:
    return {"ok": True, "mock_mode": not config.SANDBOX_URL}


@app.post("/scan", response_model=ScanResult)
def scan_endpoint(req: ScanRequest, background_tasks: BackgroundTasks) -> ScanResult:
    location = [req.lat, req.lng] if req.lat is not None and req.lng is not None else None
    result = scan(req.url.strip(), location)
    result.flagged_before = flagged_before(result)   # "reported N times near you"; never raises
    background_tasks.add_task(record_scan, result)   # log to Tiger Data off the request path
    return result
