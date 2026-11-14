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
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Header, HTTPException
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
# Calls this server placed. Status lookups are limited to these, so /call-me/{id} can't be used
# to read other calls on the Chert project with our credential.
_our_calls: set[str] = set()
_last_call_at = 0.0


class CallRequest(BaseModel):
    url: str
    phone: str
    lat: Optional[float] = None
    lng: Optional[float] = None


CHERT_MESSAGES_API = os.getenv("CHERT_API_BASE", "https://app.trychert.com/api/v1").rstrip("/")
CONSENT_TTL = timedelta(hours=24)          # Chert's trial can only reach phones that texted the line
CONSENT_FILE = os.getenv("SCANSAFE_CONSENT_FILE", os.path.expanduser("~/.scansafe-call-consent.json"))
_consent_lock = threading.Lock()
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O/1/I


def _load_consent() -> dict:
    try:
        with open(CONSENT_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"codes": {}, "verified": {}}


def _save_consent(data: dict) -> None:
    tmp = CONSENT_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONSENT_FILE)


def issue_consent_code(phone: str) -> str:
    """A short code the user texts to the ScanSafe line from this phone to allow calls to it."""
    import secrets
    code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
    with _consent_lock:
        data = _load_consent()
        data["codes"][phone] = {"code": code, "at": time.time()}
        _save_consent(data)
    return code


def _inbound_texts() -> list[tuple[str, str]]:
    """(last 4 digits of sender, text) for texts to the line in the last 24 h. Never raises."""
    out: list[tuple[str, str]] = []
    try:
        r = httpx.get(f"{CHERT_MESSAGES_API}/shared-messages", params={"limit": 100},
                      headers=_chert_headers(), timeout=8)
        r.raise_for_status()
        cutoff = datetime.now(timezone.utc) - CONSENT_TTL
        for m in (r.json().get("data") or {}).get("items") or []:
            if m.get("direction") != "inbound":
                continue
            try:
                when = datetime.fromisoformat(str(m.get("created_at")))
            except ValueError:
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            # Chert only exposes the other party masked ("•••9861"); for inbound texts that's the sender.
            digits = re.sub(r"\D", "", str(m.get("masked_recipient") or ""))
            if when >= cutoff and len(digits) >= 4:
                out.append((digits[-4:], str(m.get("text") or "").upper()))
    except Exception as e:  # noqa: BLE001
        log.warning("couldn't read recent texts from Chert: %s", type(e).__name__)
    return out


def phone_consented(phone: str) -> bool:
    """True if this exact phone texted its one-time code to the line within 24 h.

    The code is issued for the full number, and the text must contain that code AND come from a
    number ending in the same 4 digits (all Chert shows us), so a stranger can't enable calls to
    someone else's phone by texting from their own."""
    now = time.time()
    with _consent_lock:
        data = _load_consent()
        v = data["verified"].get(phone)
        if v and now - v < CONSENT_TTL.total_seconds():
            return True
        c = data["codes"].get(phone)
    if not c or now - c["at"] > CONSENT_TTL.total_seconds():
        return False
    if any(last4 == phone[-4:] and c["code"] in text for last4, text in _inbound_texts()):
        with _consent_lock:
            data = _load_consent()
            data["verified"][phone] = now
            data["codes"].pop(phone, None)
            _save_consent(data)
        log.info("calls enabled for a phone ending %s (code texted)", phone[-4:])
        return True
    return False


class PhoneRequest(BaseModel):
    phone: str


TOKEN_TTL_S = 30 * 24 * 3600


def _norm_phone(raw: str) -> str:
    phone = raw.strip().replace(" ", "")
    if not PHONE_RE.match(phone):
        raise HTTPException(status_code=400, detail="phone must be in international format, e.g. +14045550123")
    return phone


def _issue_token(phone: str) -> str:
    import hashlib, secrets
    token = secrets.token_urlsafe(32)
    with _consent_lock:
        data = _load_consent()
        data.setdefault("tokens", {})[hashlib.sha256(token.encode()).hexdigest()] = {"phone": phone, "at": time.time()}
        _save_consent(data)
    return token


def phone_for_token(token: str) -> Optional[str]:
    import hashlib
    if not token:
        return None
    with _consent_lock:
        t = _load_consent().get("tokens", {}).get(hashlib.sha256(token.encode()).hexdigest())
    if t and time.time() - t["at"] < TOKEN_TTL_S:
        return t["phone"]
    return None


@router.post("/auth/phone/start")
def phone_start(req: PhoneRequest) -> dict:
    """Sign in with your phone, step 1: get a code to text to the ScanSafe line from this phone.
    (Reverse OTP: the user texts us, so no SMS provider is needed, and it also lets Chert reach them.)"""
    phone = _norm_phone(req.phone)
    _take_code_slot(phone)
    code = issue_consent_code(phone)
    return {"code": code, "line": "+16504444331",
            "sms_body": f"Hi ScanSafe! My sign-in code is {code}"}


@router.post("/auth/phone/verify")
def phone_verify(req: PhoneRequest) -> dict:
    """Step 2 (the app polls this every few seconds): once the code text has arrived from this
    phone, returns a sign-in token. The token is what /call-me trusts, never a phone in the body."""
    phone = _norm_phone(req.phone)
    if not phone_consented(phone):
        return {"verified": False}
    return {"verified": True, "phone": phone, "token": _issue_token(phone)}


_code_slots: dict[str, float] = {}


def _take_code_slot(phone: str) -> None:
    now = time.monotonic()
    with _rate_lock:
        if now - _code_slots.get(phone, -1e9) < 10:
            raise HTTPException(status_code=429, detail="please wait a few seconds")
        _code_slots[phone] = now


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


def validate(req: CallRequest, signed_in: bool = False) -> tuple[str, str]:
    url, phone = req.url.strip(), req.phone.strip().replace(" ", "")
    if not url or len(url) > 2000 or not re.match(r"^https?://", url, re.I):
        raise HTTPException(status_code=400, detail="only web links (http/https) can be walked through on a call")
    if not PHONE_RE.match(phone):
        raise HTTPException(status_code=400, detail="phone must be in international format, e.g. +14045550123")
    if not signed_in and phone not in allowed_phones():
        raise HTTPException(status_code=403, detail="sign in with your phone first: text your code to "
                                                    "+1 650-444-4331 from this phone")
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
        _our_calls.add(str(call_id))
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
async def call_me(req: CallRequest, authorization: str = Header(default="")) -> dict:
    """Ring the person on FaceTime; our agent opens `url` in the sandbox and shows it live.
    Who gets called comes from the phone sign-in token (Authorization: Bearer <token>), not from
    the request body. Without a token only the server's own allowlist (the demo phone) works."""
    token = authorization.removeprefix("Bearer ").strip()
    signed_in = await asyncio.to_thread(phone_for_token, token) if token else None
    if signed_in:
        req = req.model_copy(update={"phone": signed_in})
    url, phone = await asyncio.to_thread(validate, req, bool(signed_in))
    _take_rate_slot()
    return await place_call(url, phone)


@router.get("/call-me/{call_id}")
async def call_status(call_id: str) -> dict:
    if call_id not in _our_calls:
        raise HTTPException(status_code=404, detail="unknown call")
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
