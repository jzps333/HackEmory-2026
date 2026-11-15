"""ScanSafe backend. Run: uvicorn api.main:app --reload"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from contextlib import closing
from typing import Optional

from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import httpx
from pydantic import BaseModel

from api import config, recent_scans, result_store, session
from api.dogwood import router as dogwood_router
from api.routes_accounts import router as accounts_router
from api.routes_data import flagged_before, record_scan
from api.routes_data import router as data_router
from api.routes_call import router as call_router
from api.routes_pay import router as pay_router
from api.routes_plugins import router as plugins_router
from api.routes_memory import router as memory_router
from api.routes_result import router as result_router
from api.routes_research import router as research_router
from api.routes_runner import router as runner_router
from api.routes_voicepay import router as voicepay_router
from api.scan import (SandboxStreamError, failed_result, parse_solana_pay, sandbox_result, scan,
                      stream_sandbox, with_location)
from chert.imessage import router as chert_router
from api.schema import ScanResult

log = logging.getLogger("scansafe.scan")
app = FastAPI(title="ScanSafe")
# Explicit origins (not "*") so browsers may send the ss_session cookie (api/session.py).
app.add_middleware(CORSMiddleware, allow_origins=session.allowed_origins(), allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], allow_headers=["*"])
app.include_router(data_router)   # /report, /pins, /search, /stats/*
app.include_router(pay_router)    # /pay (devnet only)
app.include_router(chert_router)  # /chert/webhook (Chert call + message events, signed)
app.include_router(call_router)   # /call-me (Chert FaceTimes the person, agent walks the link live)
app.include_router(result_router) # /result/{scan_id} (the page linked from follow-up texts)
app.include_router(accounts_router)  # /me, /me/linked, /link/dogwood/* (saved accounts)
app.include_router(dogwood_router)   # /operators/dogwood/* (DEMO: fictional operator's OAuth + API)
app.include_router(voicepay_router)  # /pay/intent* (FaceTime agent: voice-confirmed payments)
app.include_router(plugins_router)   # /plugins* (community plugins: index, search, enabled set)
app.include_router(memory_router)    # /plugins/{id}/memory|flashcards (agent), /me/apps (signed in)
app.include_router(research_router)  # /research/start, /research/{job_id} (agent), /research/r/{token} (page)
app.include_router(runner_router)    # /runner/* (Toolstone helper app relay), /demo/forms/permit


class ScanRequest(BaseModel):
    url: str                          # whatever the QR code contained
    lat: Optional[float] = None       # only sent if the user agreed to share location
    lng: Optional[float] = None


@app.get("/health")
def health() -> dict:
    return {"ok": True, "mock_mode": not config.SANDBOX_URL}


def _location(req: ScanRequest) -> list[float] | None:
    return [req.lat, req.lng] if req.lat is not None and req.lng is not None else None


def _finish(result: ScanResult, background_tasks: BackgroundTasks) -> ScanResult:
    result.flagged_before = flagged_before(result)   # "reported N times near you"; never raises
    recent_scans.remember(result)                    # so /report can trust only our own results
    background_tasks.add_task(result_store.save, result)   # for api.scansafe.nyc/r/<id> (follow-up text link)
    background_tasks.add_task(record_scan, result)   # log to Tiger Data off the request path
    return result


@app.post("/scan", response_model=ScanResult)
def scan_endpoint(req: ScanRequest, background_tasks: BackgroundTasks) -> ScanResult:
    return _finish(scan(req.url.strip(), _location(req)), background_tasks)


FRAME_MIN_GAP_S = 1 / 8   # forward at most ~8 frames/s; when faster, keep only the newest


@app.post("/scan/stream")
def scan_stream_endpoint(req: ScanRequest) -> StreamingResponse:
    """/scan, live. NDJSON lines: the sandbox's {"type":"frame",...} and {"type":"nav",...} as it
    browses, then always exactly one {"type":"result","data":<ScanResult, same JSON as /scan>}.
    If the sandbox fails, that last line is a "suspicious" fallback result plus a short "error"
    code: no_result, sandbox_error, sandbox_timeout, sandbox_http_<status>, sandbox_unreachable,
    scan_failed. Details go to the server log only."""
    qr, location = req.url.strip(), _location(req)
    tasks = BackgroundTasks()   # run after the last line is sent, like /scan's

    def lines() -> Iterator[str]:   # sync: Starlette runs it in a threadpool
        started = time.time()
        result: ScanResult | None = None
        error = "no_result"
        try:
            if parse_solana_pay(qr) or not config.SANDBOX_URL:
                result = scan(qr, location)   # payment or mock mode: nothing to stream
            else:
                sandbox, last_sent, pending = None, 0.0, None
                with closing(stream_sandbox(qr)) as events:
                    for msg in events:
                        kind = msg.get("type")
                        if kind == "frame":
                            now = time.monotonic()
                            if now - last_sent >= FRAME_MIN_GAP_S:
                                last_sent, pending = now, None
                                yield json.dumps(msg) + "\n"
                            else:
                                pending = msg
                        elif kind == "nav":
                            yield json.dumps(msg) + "\n"
                        elif kind == "result":
                            sandbox = msg.get("data")
                            break
                        elif kind == "error":
                            log.warning("sandbox stream error: %s", str(msg.get("detail"))[:300])
                            error = "sandbox_error"
                            break
                if pending:   # the newest frame is usually the final page: always show it
                    yield json.dumps(pending) + "\n"
                if isinstance(sandbox, dict):   # same post-processing as /scan (Jev, rule, Gemini)
                    result = with_location(sandbox_result(qr, sandbox, started), location)
        except (httpx.TimeoutException, SandboxStreamError):
            result, error = None, "sandbox_timeout"
        except httpx.HTTPStatusError as e:
            result, error = None, f"sandbox_http_{e.response.status_code}"
        except httpx.HTTPError as e:
            log.warning("sandbox stream unreachable: %s", type(e).__name__)
            result, error = None, "sandbox_unreachable"
        except Exception:  # noqa: BLE001 - the stream must still end with a result
            log.exception("scan stream failed")
            result, error = None, "scan_failed"
        if result is not None:
            out = {"type": "result", "data": _finish(result, tasks).model_dump(mode="json")}
        else:   # like /scan on a sandbox failure: nothing is logged
            failed = with_location(failed_result(qr, started), location)
            out = {"type": "result", "data": failed.model_dump(mode="json"), "error": error}
        yield json.dumps(out) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson", background=tasks,
                             headers={"X-Accel-Buffering": "no"})   # don't let a proxy buffer it
