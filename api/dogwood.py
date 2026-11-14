"""DEMO ONLY: "Dogwood Lot & Meter Co." is a FICTIONAL parking operator. To show "link your
parking account" end to end, ScanSafe hosts Dogwood's OAuth server and a tiny Dogwood API here,
under /operators/dogwood. Its consent page and its web app live on the demo-sites Vercel project
(https://scansafe-demo-sites.vercel.app/dogwood/...). No real company, account or money is involved.

OAuth (authorization code, one registered client "scansafe"):
  consent page -> POST /operators/dogwood/oauth/authorize {client_id, redirect_uri, scope, state, decision}
               -> {"redirect": "<redirect_uri>?code=...&state=..."}   (code: single use, 5 min)
  ScanSafe     -> POST /operators/dogwood/oauth/token (form, grant_type=authorization_code)
               -> {"access_token", "token_type": "Bearer", "expires_in", "scope"}
  Dogwood has no login of its own: the demo account is derived from the ScanSafe sign-in that
  started the link (the signed state), so each ScanSafe user gets one stable Dogwood account.
Operator API (Bearer = Dogwood access token): GET /api/me, POST /api/sessions, GET /api/sessions/{id},
POST /api/sessions/{id}/pay {card} (a Lithic SANDBOX authorization + clearing on that one-time card;
keeps only last4 + the Lithic card token).
Agent live view: POST /app-session (X-Agent-Key) -> one-time app link; GET/POST /app-state?s=...

Operator tokens and parking sessions are kept in DOGWOOD_OPERATOR_FILE
(default ~/.scansafe-dogwood-operator.json, chmod 600; only token HASHES are stored).
Codes and app links live in memory (a restart only means linking or opening the app again).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api import account_crypto, meter_pay
from api.merchants import MERCHANT_METERS
from api.meter_pay import PayStateError

log = logging.getLogger("scansafe.dogwood")
router = APIRouter(prefix="/operators/dogwood", tags=["dogwood-demo-operator"])

OPERATOR = "Dogwood Lot & Meter Co."          # the merchant label in MERCHANT_METERS
ACCOUNT_NAME = "Dogwood Parking"              # how a linked account is shown in ScanSafe
CLIENT_ID = "scansafe"
SCOPE = "pay_parking"
STATE_PURPOSE = "link:dogwood"
STATE_TTL_S = 10 * 60
CODE_TTL_S = 5 * 60
TOKEN_TTL_S = 90 * 24 * 3600
APP_TTL_S = 15 * 60

_lock = threading.Lock()
_codes: dict[str, dict] = {}        # sha256(code) -> grant (in memory, 5 min)
_spent_codes: dict[str, dict] = {}  # sha256(code) -> {"token_hash", "at"}: a replayed code revokes its token
_apps: dict[str, dict] = {}         # scan_id -> the one live app link {nonce, exp, plate, linked}


def api_base() -> str:
    return os.getenv("API_BASE_URL", "https://api.scansafe.nyc").strip().rstrip("/")


def site_base() -> str:
    return os.getenv("DOGWOOD_SITE_URL", "https://scansafe-demo-sites.vercel.app").strip().rstrip("/")


def redirect_uri() -> str:
    """The only redirect_uri registered for client "scansafe"."""
    return f"{api_base()}/link/dogwood/callback"


def client_secret() -> str:
    return account_crypto.derived_secret("dogwood-client")


def meter():
    return MERCHANT_METERS[OPERATOR]


def _h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _oauth_error(status: int, error: str, description: str, headers: Optional[dict] = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": error, "error_description": description},
                        headers=headers)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"ok": False, "error": code, "message": message})


# --- operator token store (file) ---------------------------------------------------------------

def _file() -> str:
    return os.getenv("DOGWOOD_OPERATOR_FILE", os.path.expanduser("~/.scansafe-dogwood-operator.json"))


def _load() -> dict:
    try:
        with open(_file()) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data.setdefault("tokens", {})
    data.setdefault("sessions", {})
    return data


def _save(data: dict) -> None:
    now = time.time()
    data["tokens"] = {k: v for k, v in data["tokens"].items() if v.get("exp", 0) > now}
    if len(data["sessions"]) > 5000:   # demo: keep the newest
        keep = sorted(data["sessions"].items(), key=lambda kv: kv[1].get("created_at", 0))[-5000:]
        data["sessions"] = dict(keep)
    path = _file()
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def account_for(phone_hash: str, masked_phone: str = "") -> dict:
    """The demo Dogwood account of a ScanSafe user (stable, derived from phone_hash)."""
    account_id = "dw_" + account_crypto.derived_secret("dogwood-account:" + phone_hash)[:12].lower()
    name = f"Demo driver {masked_phone}".strip() if masked_phone else "Demo driver"
    return {"account_id": account_id, "name": name}


def revoke_access_token(token: str) -> bool:
    """Revoke a Dogwood access token (ScanSafe calls this on Disconnect). True if it existed."""
    if not token:
        return False
    with _lock:
        data = _load()
        if data["tokens"].pop(_h(token), None) is None:
            return False
        _save(data)
    return True


def account_for_token(token: str) -> Optional[dict]:
    """The Dogwood account a (non-expired, non-revoked) access token belongs to, or None."""
    if not token:
        return None
    with _lock:
        t = _load()["tokens"].get(_h(token))
    if not t or t.get("exp", 0) < time.time():
        return None
    return t


def _request_token(request: Request) -> str:
    scheme, _, value = (request.headers.get("authorization") or "").strip().partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


def _token_account(request: Request) -> Optional[dict]:
    return account_for_token(_request_token(request))


# --- OAuth -------------------------------------------------------------------------------------

class AuthorizeRequest(BaseModel):
    client_id: str = ""
    redirect_uri: str = ""
    scope: str = ""
    state: str = ""
    decision: str = ""


@router.post("/oauth/authorize")
def oauth_authorize(req: AuthorizeRequest):
    """Called by the Dogwood consent page when the user taps Allow or Deny."""
    if req.client_id != CLIENT_ID:
        return _oauth_error(400, "invalid_client", "Unknown app.")
    # Never redirect anywhere but the exact registered URI (no prefix or "startswith" matching).
    if not hmac.compare_digest(req.redirect_uri.encode(), redirect_uri().encode()):
        return _oauth_error(400, "invalid_redirect_uri", "That redirect address isn't registered for this app.")
    state, reason = account_crypto.verify(STATE_PURPOSE, req.state)
    if state is None:
        return _oauth_error(400, "invalid_state", "This link expired. Go back to ScanSafe and tap Connect again."
                            if reason == "expired" else "This link isn't valid. Go back to ScanSafe and try again.")
    back = {"state": req.state}
    if req.decision == "deny":
        return {"redirect": f"{req.redirect_uri}?{urlencode({'error': 'access_denied', **back})}"}
    if req.decision != "allow":
        return _oauth_error(400, "invalid_request", 'decision must be "allow" or "deny".')
    if req.scope != SCOPE:
        return {"redirect": f"{req.redirect_uri}?{urlencode({'error': 'invalid_scope', **back})}"}
    code = "dwc_" + secrets.token_urlsafe(24)
    account = account_for(state["ph"], state.get("d", ""))
    now = time.time()
    with _lock:
        for k in [k for k, v in _codes.items() if v["exp"] < now]:
            del _codes[k]
        for k in [k for k, v in _spent_codes.items() if now - v["at"] > 2 * CODE_TTL_S]:
            del _spent_codes[k]
        _codes[_h(code)] = {"client_id": CLIENT_ID, "redirect_uri": req.redirect_uri, "scope": SCOPE,
                            "exp": now + CODE_TTL_S, **account}
    return {"redirect": f"{req.redirect_uri}?{urlencode({'code': code, **back})}"}


def exchange_code(form: dict) -> tuple[int, dict]:
    """The token endpoint's logic: (HTTP status, JSON body). ScanSafe's callback calls it
    in-process; POST /operators/dogwood/oauth/token exposes the same thing over HTTP."""
    if form.get("grant_type") != "authorization_code":
        return 400, {"error": "unsupported_grant_type", "error_description": "Only authorization_code."}
    if form.get("client_id") != CLIENT_ID or not hmac.compare_digest(
            (form.get("client_secret") or "").encode(), client_secret().encode()):
        return 401, {"error": "invalid_client", "error_description": "Client authentication failed."}
    code_hash = _h(form.get("code") or "")
    now = time.time()
    with _lock:
        grant = _codes.pop(code_hash, None)       # single use: gone after the first try
        spent = _spent_codes.get(code_hash)
    if grant is None:
        if spent:   # a replayed code: revoke what it was exchanged for (RFC 6749 4.1.2)
            with _lock:
                data = _load()
                if data["tokens"].pop(spent["token_hash"], None) is not None:
                    _save(data)
            log.warning("dogwood: authorization code replayed; its token was revoked")
        return 400, {"error": "invalid_grant", "error_description": "Unknown, used or expired code."}
    if grant["exp"] < now:
        return 400, {"error": "invalid_grant", "error_description": "The code expired."}
    if form.get("redirect_uri") != grant["redirect_uri"]:
        return 400, {"error": "invalid_grant", "error_description": "redirect_uri doesn't match."}
    token = "dwat_" + secrets.token_urlsafe(32)
    with _lock:
        data = _load()
        data["tokens"][_h(token)] = {"account_id": grant["account_id"], "name": grant["name"],
                                     "scope": grant["scope"], "client_id": CLIENT_ID,
                                     "at": now, "exp": now + TOKEN_TTL_S}
        _save(data)
        _spent_codes[code_hash] = {"token_hash": _h(token), "at": now}
    return 200, {"access_token": token, "token_type": "Bearer", "expires_in": TOKEN_TTL_S,
                 "scope": grant["scope"], "account_id": grant["account_id"]}


@router.post("/oauth/token")
async def oauth_token(request: Request):
    """application/x-www-form-urlencoded: grant_type, code, redirect_uri, client_id,
    client_secret (or HTTP Basic client auth)."""
    raw = (await request.body()).decode("utf-8", "replace")
    form = {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}
    basic = request.headers.get("authorization", "")
    if basic.lower().startswith("basic "):
        import base64
        try:
            cid, _, csec = base64.b64decode(basic[6:].strip()).decode().partition(":")
            form.setdefault("client_id", cid)
            form.setdefault("client_secret", csec)
        except ValueError:
            pass
    status, body = exchange_code(form)
    headers = {"Cache-Control": "no-store"}
    return JSONResponse(status_code=status, content=body, headers=headers)


# --- operator API ------------------------------------------------------------------------------
# Each call is a function taking the Dogwood access token and returning (HTTP status, JSON body):
# the HTTP routes below wrap them, and ScanSafe's /pay calls them in-process (server to server,
# so card details never cross a network hop we own).

_BEARER_ERR = {"WWW-Authenticate": 'Bearer error="invalid_token"'}
_NO_TOKEN = (401, {"error": "invalid_token", "error_description": "Missing, revoked or expired Dogwood token."})
CARD_FIELDS = ("pan", "cvv", "exp_month", "exp_year")   # Lithic card object names
DESCRIPTOR = "DOGWOOD LOT & METER"                       # what the card statement shows (max 25)


def _respond(result: tuple[int, dict]) -> JSONResponse:
    status, body = result
    return JSONResponse(status_code=status, content=body, headers=_BEARER_ERR if status == 401 else None)


def _session_view(s: dict) -> dict:
    out = {k: s[k] for k in ("session_id", "meter_id", "plate", "hours", "amount_sol", "status")}
    out["amount_usd"] = s.get("amount_usd")
    if s.get("payment"):
        out["payment"] = dict(s["payment"])   # method, provider, card_last4, card_token, authorization_token, paid_at
    return out


def _fail(status: int, code: str, message: str) -> tuple[int, dict]:
    return status, {"ok": False, "error": code, "message": message}


def create_session(token: str, meter_id: Any, plate: Any, hours: Any) -> tuple[int, dict]:
    acct = account_for_token(token)
    if acct is None:
        return _NO_TOKEN
    if SCOPE not in (acct.get("scope") or "").split():
        return 403, {"error": "insufficient_scope", "error_description": "This token can't pay for parking."}
    m = meter()
    if str(meter_id or "") != m.meter_id:
        return _fail(404, "unknown_meter", f"Dogwood has no meter {str(meter_id)[:20]}. Try meter {m.meter_id}.")
    from api.routes_accounts import PlateError, normalize_plate
    try:
        plate = normalize_plate(plate if isinstance(plate, str) else None)
    except PlateError as e:
        return _fail(400, "bad_plate", str(e))
    if not plate:
        return _fail(400, "bad_plate", "A plate is required.")
    try:
        hours = meter_pay.parse_hours(hours, m)
    except PayStateError as e:
        return _fail(e.status, e.code, e.message)
    from api.merchants import meter_usd
    s = {"session_id": "dws_" + secrets.token_hex(8), "meter_id": m.meter_id, "plate": plate,
         "hours": hours, "amount_sol": m.amount_sol(hours), "amount_usd": float(meter_usd(hours)),
         "status": "pending_payment", "account_id": acct["account_id"], "created_at": time.time()}
    with _lock:
        data = _load()
        data["sessions"][s["session_id"]] = s
        _save(data)
    return 200, _session_view(s)


def get_session(token: str, session_id: str) -> tuple[int, dict]:
    acct = account_for_token(token)
    if acct is None:
        return _NO_TOKEN
    with _lock:
        s = _load()["sessions"].get(session_id)
    if not s or s.get("account_id") != acct["account_id"]:
        return _fail(404, "unknown_session", "No such parking session on this account.")
    return 200, _session_view(s)


def _card_problem(card) -> str:
    """"" if the card details look like a usable card (no Luhn check: sandbox numbers)."""
    from api.lithic_cards import CardDetails
    if not isinstance(card, CardDetails):
        return "card details are missing"
    pan = card.pan.replace(" ", "")
    if not pan.isdigit() or len(pan) != 16:
        return "the card number isn't valid"
    if card.last4 and card.last4 != pan[-4:]:
        return "the card number isn't valid"
    if not (card.cvv.isdigit() and 3 <= len(card.cvv) <= 4):
        return "the security code isn't valid"
    try:
        month, year = int(card.exp_month), int(card.exp_year)
    except (TypeError, ValueError):
        return "the expiry date isn't valid"
    year = year + 2000 if year < 100 else year
    now = time.gmtime()
    if not 1 <= month <= 12 or (year, month) < (now.tm_year, now.tm_mon):
        return "the card has expired"
    if not card.token:
        return "the card token is missing"
    return ""


def pay_session(token: str, session_id: str, card) -> tuple[int, dict]:
    """Dogwood "charges" the card for the session: a Lithic SANDBOX authorization for exactly the
    session's USD amount (the card's own limit really applies), then a simulated clearing, then
    the session is marked paid. Keeps only last4 + the Lithic card token. `card` is an
    api.lithic_cards.CardDetails; it is never stored, logged or echoed."""
    from api import lithic_cards
    acct = account_for_token(token)
    if acct is None:
        return _NO_TOKEN
    with _lock:
        s = _load()["sessions"].get(session_id)
    if not s or s.get("account_id") != acct["account_id"]:
        return _fail(404, "unknown_session", "No such parking session on this account.")
    if s.get("status") == "paid":
        return _fail(409, "already_paid", "This parking session is already paid.")
    problem = _card_problem(card)
    if problem:
        return _fail(400, "card_invalid", f"Dogwood couldn't use that card: {problem}.")
    cents = int(round(float(s.get("amount_usd") or 0) * 100))
    try:
        auth = lithic_cards.simulate_authorize(card.pan.replace(" ", ""), cents, DESCRIPTOR)
    except lithic_cards.CardError as e:
        return _fail(e.status, e.code, e.message)
    settled = lithic_cards.simulate_clearing(auth)
    payment = {"method": "virtual_card", "provider": lithic_cards.PROVIDER, "card_last4": card.last4,
               "card_token": card.token, "authorization_token": auth, "settled": settled,
               "simulated": True, "amount_usd": s.get("amount_usd"), "paid_at": int(time.time())}
    with _lock:
        data = _load()
        cur = data["sessions"].get(session_id) or s
        if cur.get("status") == "paid":   # a parallel request won: don't mark twice
            return _fail(409, "already_paid", "This parking session is already paid.")
        cur.update(status="paid", payment=payment)
        data["sessions"][session_id] = cur
        _save(data)
    return 200, _session_view(cur)


class SessionRequest(BaseModel):
    meter_id: Any = None
    plate: Any = None
    hours: Any = None


@router.get("/api/me")
def api_me(request: Request):
    acct = _token_account(request)
    if acct is None:
        return _respond(_NO_TOKEN)
    return {"account_id": acct["account_id"], "name": acct["name"]}


@router.post("/api/sessions")
def api_create_session(req: SessionRequest, request: Request):
    return _respond(create_session(_request_token(request), req.meter_id, req.plate, req.hours))


@router.get("/api/sessions/{session_id}")
def api_get_session(session_id: str, request: Request):
    return _respond(get_session(_request_token(request), session_id))


@router.post("/api/sessions/{session_id}/pay")
async def api_pay_session(session_id: str, request: Request):
    """{"card": {"token", "pan", "cvv", "exp_month", "exp_year", "last_four"?}} (the Lithic card
    object). The body is parsed by hand so no validation error can echo it."""
    import asyncio
    from api.lithic_cards import CardDetails
    try:
        body = json.loads(await request.body() or b"{}")
    except ValueError:
        body = None
    raw = body.get("card") if isinstance(body, dict) else None
    card = None
    if isinstance(raw, dict) and all(isinstance(raw.get(k), (str, int)) for k in CARD_FIELDS):
        card = CardDetails(token=str(raw.get("token") or ""), pan=str(raw["pan"]), cvv=str(raw["cvv"]),
                           exp_month=raw["exp_month"], exp_year=raw["exp_year"],
                           last4=str(raw.get("last_four") or ""))
    try:
        return _respond(await asyncio.to_thread(pay_session, _request_token(request), session_id, card))
    finally:
        if card is not None:
            card.wipe()


# --- the agent's live view of the Dogwood app --------------------------------------------------

APP_PURPOSE = "dogwood-app"


class AppSessionRequest(BaseModel):
    scan_id: str = ""


class AppHoursRequest(BaseModel):
    hours: Any = None


def _agent_ok(request: Request) -> Optional[JSONResponse]:
    want = os.getenv("AGENT_INTERNAL_KEY", "").strip()
    if not want:
        return _error(503, "agent_key_not_configured", "The server needs AGENT_INTERNAL_KEY for this.")
    got = (request.headers.get("x-agent-key") or "").strip()
    if not got or not hmac.compare_digest(got.encode(), want.encode()):
        return _error(401, "bad_agent_key", "Only the ScanSafe agent can open the Dogwood app.")
    return None


def _owner_profile(scan_id: str) -> tuple[Optional[str], bool]:
    """(plate, dogwood linked) of the signed-in person this scan belongs to. Never raises."""
    ph = meter_pay.get_owner(scan_id)
    if not ph:
        return None, False
    try:
        from data import accounts_store
        store = accounts_store.get_store()
        profile = store.get_profile(ph) or {}
        return profile.get("plate"), store.get_linked(ph, "dogwood") is not None
    except Exception as e:  # noqa: BLE001 - the live view must still open
        log.warning("dogwood app: couldn't read the owner's profile: %s", type(e).__name__)
        return None, False


def _dogwood_scan(scan_id: str):
    _scan, payment, m = meter_pay.meter_scan(scan_id)
    if payment.label != OPERATOR:
        raise PayStateError(400, "not_dogwood", "This meter code isn't a Dogwood meter.")
    return payment, m


@router.post("/app-session")
def app_session(req: AppSessionRequest, request: Request):
    """FaceTime agent only (X-Agent-Key). A fresh one-time link to the Dogwood app for this scan;
    it replaces any earlier link for the same scan and works for 15 minutes."""
    bad = _agent_ok(request)
    if bad:
        return bad
    try:
        _dogwood_scan(req.scan_id)
    except PayStateError as e:
        return _error(e.status, e.code, e.message)
    plate, linked = _owner_profile(req.scan_id)
    nonce = secrets.token_urlsafe(12)
    token = account_crypto.sign(APP_PURPOSE, {"sid": req.scan_id, "n": nonce}, APP_TTL_S)
    with _lock:
        now = time.time()
        for k in [k for k, v in _apps.items() if v["exp"] < now]:
            del _apps[k]
        _apps[req.scan_id] = {"nonce": nonce, "exp": now + APP_TTL_S, "plate": plate, "linked": linked}
    return {"app_url": f"{site_base()}/dogwood/app?{urlencode({'s': token})}", "plate": plate,
            "linked": linked, "expires_in": APP_TTL_S}


def _app_from_token(s: str) -> tuple[Optional[dict], Optional[JSONResponse]]:
    body, reason = account_crypto.verify(APP_PURPOSE, s)
    if body is None:
        if reason == "expired":
            return None, _error(401, "app_link_expired", "This Dogwood link expired. Ask the agent to open it again.")
        return None, _error(401, "app_link_invalid", "This Dogwood link isn't valid.")
    with _lock:
        app = _apps.get(body.get("sid", ""))
    if not app or not hmac.compare_digest(app["nonce"], str(body.get("n", ""))):
        return None, _error(401, "app_link_invalid", "This Dogwood link was replaced by a newer one.")
    return {"scan_id": body["sid"], **app}, None


def app_state(scan_id: str, plate: Optional[str]) -> dict:
    """What the Dogwood app shows, from the app's /pay/quote and /pay/status for this scan."""
    payment, m = _dogwood_scan(scan_id)
    quote = meter_pay.get_quote(scan_id)
    status = meter_pay.get_status(scan_id)
    paid = status.get("state") == "paid"
    hours = status.get("hours") if paid else (quote or {}).get("hours")
    out = {"meter_id": m.meter_id, "operator": payment.label, "plate": plate, "hours": hours,
           "rate_per_hour_sol": m.rate_per_hour_sol,
           "amount_sol": m.amount_sol(hours) if isinstance(hours, int) else None,
           "min_hours": m.min_hours, "max_hours": m.max_hours,
           "status": "paid" if paid else ("waiting_for_approval" if hours else "choose")}
    if paid:
        out["payment_method"] = status.get("method", "solana_devnet")
        out["receipt"] = {"signature": status.get("signature"), "explorer_url": status.get("explorer_url"),
                          "paid_at": status.get("paid_at"), "method": out["payment_method"]}
        if out["payment_method"] == "virtual_card":
            out["amount_usd"] = status.get("amount_usd")
            out["receipt"].update(provider=status.get("provider"), card_last4=status.get("card_last4"),
                                  amount_usd=status.get("amount_usd"),
                                  dogwood_session_id=status.get("dogwood_session_id"),
                                  text=f"Paid with a one-time virtual card \u2022\u2022{status.get('card_last4')} "
                                       "(Lithic sandbox)")
    return out


@router.get("/app-state")
def get_app_state(s: str = ""):
    """Polled by the Dogwood web app (browser). `s` is the one-time link token."""
    app, bad = _app_from_token(s)
    if bad:
        return bad
    try:
        return JSONResponse(app_state(app["scan_id"], app["plate"]), headers={"Cache-Control": "no-store"})
    except PayStateError as e:
        return _error(e.status, e.code, e.message)


@router.post("/app-state")
def set_app_hours(req: AppHoursRequest, s: str = ""):
    """The Dogwood app's own hours control: updates the scan's quote (what the agent says and
    shows). It never pays: only the ScanSafe app's confirm button pays, with its own hours."""
    app, bad = _app_from_token(s)
    if bad:
        return bad
    try:
        if meter_pay.get_status(app["scan_id"]).get("state") == "paid":
            return _error(409, "already_paid", "This meter is already paid.")
        meter_pay.make_quote(app["scan_id"], req.hours)
        return app_state(app["scan_id"], app["plate"])
    except PayStateError as e:
        return _error(e.status, e.code, e.message)


def clear() -> None:  # tests
    with _lock:
        _codes.clear()
        _spent_codes.clear()
        _apps.clear()
