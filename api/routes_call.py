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
from fastapi import APIRouter, Header, HTTPException, Request
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


MAX_PENDING = 2000
START_LIMIT_PER_MIN = 300          # global ceiling, well above any one client
START_LIMIT_PER_IP_MIN = 5
REQUEST_TTL_S = 15 * 60            # a pending sign-in must be texted within 15 minutes
MAX_PENDING_PER_PHONE = 3
MAX_PENDING_PER_CLIENT = 10


def _prune(data: dict, now: float) -> None:
    data["requests"] = {k: v for k, v in data.get("requests", {}).items() if now - v["at"] < REQUEST_TTL_S}
    data["tokens"] = {k: v for k, v in data.get("tokens", {}).items() if now - v["at"] < TOKEN_TTL_S}
    data.pop("codes", None)
    data.pop("verified", None)       # old format: verification no longer hands out tokens later


def start_sign_in(phone: str, client: str = "") -> tuple[str, str]:
    """New pending sign-in for `phone`: (code to text, secret request id for the requester).
    Several can be pending per phone, so one person can't cancel another's sign-in."""
    import hashlib, secrets
    code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
    request_id = secrets.token_urlsafe(24)
    now = time.time()
    with _consent_lock:
        data = _load_consent()
        _prune(data, now)
        reqs = data["requests"]
        if sum(1 for r in reqs.values() if r.get("client") == client) >= MAX_PENDING_PER_CLIENT:
            raise HTTPException(status_code=429, detail="too many sign-ins from this device; try again later")
        mine = sorted((k for k, r in reqs.items() if r["phone"] == phone), key=lambda k: reqs[k]["at"])
        for k in mine[: max(0, len(mine) - MAX_PENDING_PER_PHONE + 1)]:
            del reqs[k]                      # only ever drop this phone's own oldest codes
        if len(reqs) >= MAX_PENDING:
            raise HTTPException(status_code=503, detail="too many sign-ins in progress; try again soon")
        reqs[hashlib.sha256(request_id.encode()).hexdigest()] = {"phone": phone, "code": code, "at": now,
                                                                 "client": client}
        _save_consent(data)
    return code, request_id


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


def complete_sign_in(phone: str, request_id: str) -> Optional[str]:
    """If this request's code was texted to the line from a number ending in the same 4 digits,
    issue one token (to the holder of request_id) and close the request. Otherwise None."""
    import hashlib
    key = hashlib.sha256(request_id.encode()).hexdigest()
    with _consent_lock:
        data = _load_consent()
        _prune(data, time.time())
        req = data["requests"].get(key)
    if not req or req["phone"] != phone:
        return None
    if not any(last4 == phone[-4:] and req["code"] in text for last4, text in _inbound_texts()):
        return None
    with _consent_lock:
        data = _load_consent()
        if data.get("requests", {}).pop(key, None) is None:
            return None                      # already completed: one token per request
        _save_consent(data)
    log.info("phone sign-in completed for a phone ending %s", phone[-4:])
    return _issue_token(phone)


class PhoneRequest(BaseModel):
    phone: str
    request_id: str = ""


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
def phone_start(req: PhoneRequest, request: Request) -> dict:
    """Sign in with your phone, step 1: get a code to text to the ScanSafe line from this phone.
    (Reverse OTP: the user texts us, so no SMS provider is needed, and it also lets Chert reach them.)"""
    phone = _norm_phone(req.phone)
    _take_code_slot(phone, _client_ip(request))   # same client value used below
    client = _client_ip(request)
    code, request_id = start_sign_in(phone, client)
    return {"code": code, "request_id": request_id, "line": "+16504444331",
            "sms_body": f"Hi ScanSafe! My sign-in code is {code}"}


@router.post("/auth/phone/verify")
def phone_verify(req: PhoneRequest) -> dict:
    """Step 2 (the app polls this every few seconds): once the code text has arrived from this
    phone, returns a sign-in token. The token is what /call-me trusts, never a phone in the body."""
    phone = _norm_phone(req.phone)
    if not req.request_id:
        raise HTTPException(status_code=400, detail="request_id from /auth/phone/start is required")
    token = complete_sign_in(phone, req.request_id)
    if not token:
        return {"verified": False}
    return {"verified": True, "phone": phone, "token": token}


_code_slots: dict[str, float] = {}
_start_times: list[float] = []
_ip_starts: dict[str, list[float]] = {}


def _take_code_slot(phone: str, client: str = "") -> None:
    """Per client (IP): START_LIMIT_PER_IP_MIN starts a minute. Per phone: one every 10 s.
    Global ceiling only as a backstop, set far above what one client can reach."""
    now = time.monotonic()
    with _rate_lock:
        recent = [t for t in _ip_starts.get(client, []) if now - t < 60]
        if len(recent) >= START_LIMIT_PER_IP_MIN:
            raise HTTPException(status_code=429, detail="too many sign-ins from this device; try again in a minute")
        if now - _code_slots.get(phone, -1e9) < 10:
            raise HTTPException(status_code=429, detail="please wait a few seconds")
        _start_times[:] = [t for t in _start_times if now - t < 60]
        if len(_start_times) >= START_LIMIT_PER_MIN:
            raise HTTPException(status_code=429, detail="too many sign-ins right now; try again in a minute")
        for k in [k for k, t in _code_slots.items() if now - t > 60]:
            del _code_slots[k]
        for k in [k for k, ts in _ip_starts.items() if not ts or now - ts[-1] > 60]:
            del _ip_starts[k]
        recent.append(now)
        _ip_starts[client] = recent
        _code_slots[phone] = now
        _start_times.append(now)


TRUSTED_PROXIES = {"127.0.0.1", "::1"}    # Caddy runs on this machine


def _client_ip(request: Request) -> str:
    """The caller's IP. X-Forwarded-For is only believed when the request came from our own
    Caddy on localhost (its last entry is the address Caddy saw). IPv6 is grouped by /64."""
    import ipaddress
    peer = request.client.host if request.client else ""
    ip = peer
    if peer in TRUSTED_PROXIES:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            ip = xff.split(",")[-1].strip()
    try:
        addr = ipaddress.ip_address(ip)
        if addr.version == 6:
            return str(ipaddress.ip_network(f"{addr}/64", strict=False))
        return str(addr)
    except ValueError:
        return ip or "?"


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
