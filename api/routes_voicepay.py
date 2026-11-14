"""Voice-confirmed payments (FaceTime agent only, header X-Agent-Key = env AGENT_INTERNAL_KEY):

  POST /pay/intent                      {scan_id, hours, method?, plate?}
       -> {intent_id, readback, amount_sol, amount_usd, merchant, hours, plate, method,
           expires_at, expires_in}
  POST /pay/intent/{intent_id}/confirm  {utterance}   (the caller's transcribed words)
       -> the POST /pay result + "status" (GET /pay/status for the scan)
  POST /pay/intent/{intent_id}/cancel   {}

Logic and rules: api/voice_pay.py. Errors: {"ok": false, "error": "<code>", "message": "..."}.
The app needs nothing new: its Pay button (POST /pay) works as before.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api import voice_pay
from api.dogwood import _agent_ok   # same env var, header and constant-time compare as app-session

router = APIRouter(tags=["voice-pay"])
NO_STORE = {"Cache-Control": "no-store"}


class IntentRequest(BaseModel):
    scan_id: Any = None
    hours: Any = None
    method: Any = None          # "solana_devnet" | "virtual_card"; left out: see voice_pay.create_intent
    plate: Any = None           # optional, from the call; the owner's saved plate wins


class ConfirmRequest(BaseModel):
    utterance: Any = None


def _json(status: int, body: dict) -> JSONResponse:
    return JSONResponse(status_code=status, content=body, headers=NO_STORE)


def _refused(request: Request) -> Optional[JSONResponse]:
    bad = _agent_ok(request)
    if bad is not None:
        bad.headers.update(NO_STORE)
    return bad


@router.post("/pay/intent", responses={400: {}, 401: {}, 403: {}, 404: {}, 409: {}, 503: {}})
def create_intent(req: IntentRequest, request: Request):
    bad = _refused(request)
    if bad:
        return bad
    try:
        return _json(200, {"ok": True, **voice_pay.create_intent(req.scan_id, req.hours, req.method, req.plate)})
    except voice_pay.IntentError as e:
        return _json(e.status, {"ok": False, "error": e.code, "message": e.message})


@router.post("/pay/intent/{intent_id}/confirm",
             responses={400: {}, 401: {}, 402: {}, 403: {}, 404: {}, 409: {}, 410: {}, 429: {}, 502: {}, 503: {}})
def confirm_intent(intent_id: str, req: ConfirmRequest, request: Request):
    bad = _refused(request)
    if bad:
        return bad
    status, body = voice_pay.confirm(intent_id, req.utterance)
    return _json(status, body)


@router.post("/pay/intent/{intent_id}/cancel", responses={401: {}, 409: {}})
def cancel_intent(intent_id: str, request: Request):
    bad = _refused(request)
    if bad:
        return bad
    status, body = voice_pay.cancel(intent_id)
    return _json(status, body)
