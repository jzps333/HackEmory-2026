"""POST /call-me: the app scanned a QR code, now Chert FaceTimes the person and our agent walks
them through the link live.

Flow (Chert "Outbound" + bring-your-own-LiveKit docs):
  1. make a LiveKit room and dispatch our agent into it, with the scanned URL as job metadata;
  2. wait until the agent has joined and published its audio AND video (Chert's bridge takes
     audio and video from the one participant that publishes audio; publish before dialing);
  3. mint a room-scoped token for Chert's bridge and ask Chert to place the call;
  4. put the Chert call id in the room metadata, so the agent can poll the call and greet only
     once FaceTime is really up (nothing writes chert_bridge_ready in our own rooms).

Safety: this rings a real phone, so only allow-listed numbers (CALL_ALLOWED_PHONES, plus
SCANSAFE_DEMO_PHONE) and at most one call every CALL_MIN_GAP_S seconds.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import timedelta
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api import config  # noqa: F401  (loads .env and the LiveKit fallback file)

log = logging.getLogger("scansafe.call")
router = APIRouter()

PHONE_RE = re.compile(r"^\+[1-9]\d{6,14}$")
CALL_MIN_GAP_S = float(os.getenv("CALL_MIN_GAP_S", "30"))
AGENT_READY_TIMEOUT_S = 20.0
BRIDGE_TOKEN_TTL = timedelta(hours=1)
CHERT_FACETIME_API = os.getenv("CHERT_FACETIME_API", "https://facetime.trychert.com/api/v1").rstrip("/")

_rate_lock = threading.Lock()
_last_call_at = 0.0


class CallRequest(BaseModel):
    url: str
    phone: str
    lat: Optional[float] = None
    lng: Optional[float] = None


def allowed_phones() -> set[str]:
    raw = [os.getenv("SCANSAFE_DEMO_PHONE", "")] + os.getenv("CALL_ALLOWED_PHONES", "").split(",")
    return {p.strip().replace(" ", "") for p in raw if p.strip()}


def _livekit_http_url() -> str:
    url = os.getenv("LIVEKIT_URL", "")
    return url.replace("wss://", "https://", 1).replace("ws://", "http://", 1)


def _chert_headers(idempotency_key: Optional[str] = None) -> dict:
    h = {"Authorization": f"Bearer {os.getenv('CHERT_API_KEY', '')}",
         "X-Chert-Project-Id": os.getenv("CHERT_PROJECT_ID", ""),
         "Content-Type": "application/json"}
    if idempotency_key:
        h["Idempotency-Key"] = idempotency_key
    return h


def _take_rate_slot() -> None:
    global _last_call_at
    with _rate_lock:
        now = time.monotonic()
        wait = CALL_MIN_GAP_S - (now - _last_call_at)
        if _last_call_at and wait > 0:
            raise HTTPException(status_code=429, detail=f"one call at a time: try again in {int(wait) + 1} s")
        _last_call_at = now


def validate(req: CallRequest) -> tuple[str, str]:
    url, phone = req.url.strip(), req.phone.strip().replace(" ", "")
    if not url or len(url) > 2000 or not re.match(r"^https?://", url, re.I):
        raise HTTPException(status_code=400, detail="only web links (http/https) can be walked through on a call")
    if not PHONE_RE.match(phone):
        raise HTTPException(status_code=400, detail="phone must be in international format, e.g. +14045550123")
    if phone not in allowed_phones():
        raise HTTPException(status_code=403, detail="this number isn't set up for ScanSafe calls")
    missing = [k for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "CHERT_API_KEY",
                           "CHERT_PROJECT_ID", "CHERT_LINE_ID") if not os.getenv(k)]
    if missing:
        raise HTTPException(status_code=503, detail=f"calling isn't configured on the server ({', '.join(missing)})")
    return url, phone


def _agent_ready(participants) -> Optional[str]:
    """Identity of our agent once it publishes both audio and video, else None."""
    from livekit import api as lk
    for p in participants:
        is_agent = p.kind == lk.ParticipantInfo.Kind.AGENT or p.identity.startswith("agent-")
        kinds = {t.type for t in p.tracks}
        if is_agent and lk.TrackType.AUDIO in kinds and lk.TrackType.VIDEO in kinds:
            return p.identity
    return None


def bridge_token(room: str, identity: str) -> str:
    from livekit import api as lk
    return (lk.AccessToken(os.getenv("LIVEKIT_API_KEY"), os.getenv("LIVEKIT_API_SECRET"))
            .with_identity(identity)
            .with_ttl(BRIDGE_TOKEN_TTL)
            .with_grants(lk.VideoGrants(room_join=True, room=room, can_publish=True,
                                        can_subscribe=True, can_publish_data=True))
            .to_jwt())


async def place_call(url: str, phone: str) -> dict:
    """Steps 1-4 above. Raises HTTPException with a short reason on failure."""
    from livekit import api as lk
    room = f"scansafe-out-{uuid.uuid4().hex[:12]}"
    lkapi = lk.LiveKitAPI(_livekit_http_url(), os.getenv("LIVEKIT_API_KEY"), os.getenv("LIVEKIT_API_SECRET"))
    try:
        await lkapi.room.create_room(lk.CreateRoomRequest(name=room, empty_timeout=300, max_participants=4))
        await lkapi.agent_dispatch.create_dispatch(lk.CreateAgentDispatchRequest(
            agent_name=os.getenv("AGENT_NAME", "scansafe-agent"), room=room,
            metadata=json.dumps({"scansafe_outbound": True, "scan_url": url, "phone": phone})))

        agent_identity, deadline = None, time.monotonic() + AGENT_READY_TIMEOUT_S
        while time.monotonic() < deadline:
            res = await lkapi.room.list_participants(lk.ListParticipantsRequest(room=room))
            agent_identity = _agent_ready(res.participants)
            if agent_identity:
                break
            await asyncio.sleep(0.4)
        if not agent_identity:
            raise HTTPException(status_code=504, detail="the ScanSafe agent didn't get ready in time")

        bridge_identity = f"chert-bridge-out-{uuid.uuid4().hex[:10]}"
        body = {
            "direction": "outbound", "mode": "customer_managed",
            "line_id": os.getenv("CHERT_LINE_ID"), "destination": phone, "destination_type": "phone",
            "media": {"audio": True, "video": True},
            "livekit_url": os.getenv("LIVEKIT_URL"),
            "participant_token": bridge_token(room, bridge_identity),
            "remote_participant_identity": agent_identity,
        }
        async with httpx.AsyncClient(timeout=40, follow_redirects=True) as c:
            r = await c.post(f"{CHERT_FACETIME_API}/calls", json=body, headers=_chert_headers(uuid.uuid4().hex))
        if r.status_code not in (200, 201):
            log.warning("chert create call failed: HTTP %s %s", r.status_code, r.text[:300])
            raise HTTPException(status_code=502, detail=f"Chert refused the call (HTTP {r.status_code}): {r.text[:200]}")
        data = r.json().get("data", r.json())
        call_id = data.get("id")
        if not call_id:
            raise HTTPException(status_code=502, detail="Chert didn't return a call id")
        await lkapi.room.update_room_metadata(lk.UpdateRoomMetadataRequest(
            room=room, metadata=json.dumps({"chert_call_id": call_id})))
        log.info("outbound call %s placed in room %s", call_id, room)
        return {"call_id": call_id, "room": room, "status": data.get("status", "allocated")}
    except HTTPException:
        await _cleanup(lkapi, room)
        raise
    except Exception as e:  # noqa: BLE001 - LiveKit/Chert/network: report, clean up
        log.exception("placing call failed")
        await _cleanup(lkapi, room)
        raise HTTPException(status_code=502, detail=f"couldn't place the call: {type(e).__name__}")
    finally:
        await lkapi.aclose()


async def _cleanup(lkapi, room: str) -> None:
    from livekit import api as lk
    try:
        await lkapi.room.delete_room(lk.DeleteRoomRequest(room=room))
    except Exception:  # noqa: BLE001
        pass


@router.post("/call-me")
async def call_me(req: CallRequest) -> dict:
    """Ring the person on FaceTime; our agent opens `url` in the sandbox and shows it live."""
    url, phone = validate(req)
    _take_rate_slot()
    return await place_call(url, phone)


@router.get("/call-me/{call_id}")
async def call_status(call_id: str) -> dict:
    if not re.match(r"^[A-Za-z0-9_-]{1,80}$", call_id):
        raise HTTPException(status_code=400, detail="bad call id")
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        r = await c.get(f"{CHERT_FACETIME_API}/calls/{call_id}", headers=_chert_headers())
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Chert said HTTP {r.status_code}")
    d = r.json().get("data", r.json())
    events = [e.get("type") or e.get("event_type") or e.get("name")
              for e in (d.get("facetime_call_events") or []) if isinstance(e, dict)]
    return {"call_id": call_id, "status": d.get("status"), "answered": d.get("answered"),
            "terminal_reason": d.get("terminal_reason"), "events": [e for e in events if e]}
