"""Saved accounts: profile (GET/PUT /me), linked accounts (GET /me/linked, DELETE
/me/linked/{provider}), and the two link flows: Dogwood Parking (a fictional operator whose OAuth
server we host, see api/dogwood.py) and PayPal SANDBOX Vault (api/paypal_vault.py).

Auth: the phone sign-in token, as `Authorization: Bearer <token>` or the `ss_session` cookie
(api/session.py). Errors: {"ok": false, "error": "<code>", "message": "<plain words>"}.
Link callbacks are browser navigations, so they always answer with a 302 back to the app:
  success  APP_BASE_URL/accounts?linked=<provider>
  failure  APP_BASE_URL/accounts?link_error=<code>&provider=<provider>
(APP_BASE_URL unset: https://scansafe.nyc/?linked=... and https://scansafe.nyc/?link_error=...)
"""
from __future__ import annotations

import hmac
import logging
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from api import account_crypto, dogwood, paypal_vault, session
from api.account_crypto import AccountConfigError
from api.paypal_vault import PayPalError
from data import accounts_store

log = logging.getLogger("scansafe.accounts")
router = APIRouter(tags=["accounts"])

PROVIDERS = ("dogwood", "paypal")
PAYMENT_METHODS = ("solana_devnet", "paypal")
DEFAULT_PAYMENT = "solana_devnet"
PAYPAL_STATE_PURPOSE = "link:paypal"
LINK_TTL_S = 10 * 60
PLATE_RE = re.compile(r"[A-Z0-9 -]{2,10}")
NO_STORE = {"Cache-Control": "no-store"}

_lock = threading.Lock()
_spent_states: dict[str, float] = {}      # nonce -> expiry: each link state works once
_paypal_pending: dict[str, dict] = {}     # nonce -> {"setup_token_id", "exp"}


class Refusal(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class PlateError(ValueError):
    pass


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"ok": False, "error": code, "message": message},
                        headers=NO_STORE)


def _refused(e: Exception) -> JSONResponse:
    if isinstance(e, (Refusal, PayPalError)):
        return _error(e.status, e.code, e.message)
    if isinstance(e, AccountConfigError):
        return _error(503, e.code, e.message)
    raise e


def normalize_plate(raw: Optional[str]) -> Optional[str]:
    """Uppercased plate, None to clear it ("" or null). Raises PlateError."""
    if raw is None:
        return None
    plate = raw.strip().upper()
    if not plate:
        return None
    if not PLATE_RE.fullmatch(plate) or not re.search(r"[A-Z0-9]", plate):
        raise PlateError("Plates are 2 to 10 letters, numbers, spaces or dashes.")
    return plate


def app_url(**params) -> str:
    base = os.getenv("APP_BASE_URL", "").strip().rstrip("/")
    target = f"{base}/accounts" if base else "https://scansafe.nyc/"
    return f"{target}?{urlencode(params)}"


# --- helpers -----------------------------------------------------------------------------------

def _store():
    try:
        return accounts_store.get_store()
    except accounts_store.NotConfigured:
        raise Refusal(503, "accounts_not_configured",
                      "Saved accounts aren't available on this server yet.") from None


def _db(fn, *args):
    """Run one store call; a database hiccup becomes a 502 with plain words (type logged only)."""
    try:
        return fn(*args)
    except Refusal:
        raise
    except Exception as e:  # noqa: BLE001 - psycopg errors can echo connection details
        log.warning("accounts store call %s failed: %s", getattr(fn, "__name__", "?"), type(e).__name__)
        raise Refusal(502, "accounts_store_error",
                      "We couldn't reach saved accounts. Try again in a minute.") from None


def _who(request: Request) -> tuple[str, str]:
    phone = session.current_phone(request)
    if not phone:
        raise Refusal(401, "not_signed_in", "Sign in with your phone first.")
    return phone, account_crypto.phone_hash(phone)


def _iso(value) -> Optional[str]:
    """ISO-8601 in UTC (Postgres hands back the session's time zone)."""
    if isinstance(value, datetime):
        return (value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
    return value


def _display(row: dict) -> str:
    meta = row.get("meta") or {}
    if row["provider"] == "dogwood":
        return meta.get("account_name") or dogwood.ACCOUNT_NAME
    if row["provider"] == "paypal":
        return meta.get("display") or "PayPal (sandbox)"
    return row["provider"]


def linked_view(rows: list[dict]) -> list[dict]:
    return [{"provider": r["provider"], "display": _display(r), "linked_at": _iso(r.get("linked_at"))}
            for r in rows]


def _need_encryption() -> None:
    account_crypto.encrypt({"check": True})   # raises AccountConfigError if ACCOUNT_KEY is unusable


def linked_secret(phone_hash: str, provider: str) -> Optional[dict]:
    """The decrypted secret of an active link, or None if there's no active link.
    Raises Refusal / AccountConfigError."""
    row = _db(_store().get_linked, phone_hash, provider)
    if not row:
        return None
    secret = account_crypto.decrypt(row.get("secret_enc") or "")
    if secret is None:
        raise Refusal(409, f"{provider}_relink_needed",
                      "This saved account can't be read anymore. Disconnect it and connect it again.")
    return secret


def _new_state(purpose: str, phone: str, phone_hash: str) -> tuple[str, str]:
    nonce = secrets.token_urlsafe(12)
    state = account_crypto.sign(purpose, {"ph": phone_hash, "d": session_mask(phone), "n": nonce}, LINK_TTL_S)
    return state, nonce


def session_mask(phone: str) -> str:
    from api.routes_call import mask_phone
    return mask_phone(phone)


def _take_state(purpose: str, state: str, request: Request) -> tuple[Optional[dict], str]:
    """Verify a link state from a callback and spend it. (payload, "") or (None, link_error)."""
    body, reason = account_crypto.verify(purpose, state)
    if body is None:
        return None, "link_expired" if reason == "expired" else "invalid_state"
    now = time.time()
    with _lock:
        for k in [k for k, exp in _spent_states.items() if exp < now]:
            del _spent_states[k]
        if body["n"] in _spent_states:
            return None, "invalid_state"
        _spent_states[body["n"]] = body["exp"] + 1
    # Someone signed in as another person in this browser? Don't link into the wrong account.
    current = session.current_phone(request)
    if current and not hmac.compare_digest(account_crypto.phone_hash(current), body["ph"]):
        return None, "signed_in_as_someone_else"
    return body, ""


# --- profile -----------------------------------------------------------------------------------

class ProfileUpdate(BaseModel):
    plate: Optional[str] = None
    preferred_payment: Optional[str] = None


def _profile(phone: str, phone_hash: str) -> dict:
    store = _store()
    profile = _db(store.get_profile, phone_hash) or {}
    rows = _db(store.list_linked, phone_hash)
    return {"signed_in": True, "phone_masked": session_mask(phone), "plate": profile.get("plate"),
            "preferred_payment": profile.get("preferred_payment") or DEFAULT_PAYMENT,
            "linked": linked_view(rows),
            "providers": {"dogwood": True, "paypal": paypal_vault.is_configured()},
            "paypal_rates": {"dogwood_usd_per_hour": float(paypal_vault.dogwood_rate_usd()),
                             "demo_usd_per_sol": float(paypal_vault.demo_usd_per_sol())}}


@router.get("/me")
def get_me(request: Request):
    """The signed-in person's saved account. 200 {"signed_in": false} when not signed in."""
    phone = session.current_phone(request)
    if not phone:
        return JSONResponse({"signed_in": False}, headers=NO_STORE)
    try:
        return JSONResponse(_profile(phone, account_crypto.phone_hash(phone)), headers=NO_STORE)
    except (Refusal, AccountConfigError) as e:
        return _refused(e)


@router.put("/me")
def put_me(req: ProfileUpdate, request: Request):
    """Change the plate and/or preferred payment. Fields left out stay as they are."""
    try:
        phone, ph = _who(request)
        fields: dict[str, Any] = {}
        if "plate" in req.model_fields_set:
            try:
                fields["plate"] = normalize_plate(req.plate)
            except PlateError as e:
                raise Refusal(400, "bad_plate", str(e)) from None
        if "preferred_payment" in req.model_fields_set:
            pref = req.preferred_payment
            if pref is not None and pref not in PAYMENT_METHODS:
                raise Refusal(400, "bad_preferred_payment",
                              'Preferred payment must be "solana_devnet" or "paypal".')
            if pref == "paypal" and _db(_store().get_linked, ph, "paypal") is None:
                raise Refusal(403, "paypal_not_linked", "Connect PayPal first.")
            fields["preferred_payment"] = pref
        if fields:
            _db(_store().update_profile, ph, fields)
        return JSONResponse(_profile(phone, ph), headers=NO_STORE)
    except (Refusal, AccountConfigError) as e:
        return _refused(e)


# --- linked accounts ---------------------------------------------------------------------------

@router.get("/me/linked")
def get_linked(request: Request):
    try:
        _phone, ph = _who(request)
        return JSONResponse({"linked": linked_view(_db(_store().list_linked, ph))}, headers=NO_STORE)
    except (Refusal, AccountConfigError) as e:
        return _refused(e)


def _revoke_upstream(provider: str, secret_enc: str) -> None:
    """Best effort: also revoke the token at the provider. Never raises."""
    try:
        secret = account_crypto.decrypt(secret_enc) if secret_enc else None
    except AccountConfigError:
        secret = None
    if not secret:
        return
    if provider == "dogwood":
        dogwood.revoke_access_token(secret.get("access_token", ""))
    elif provider == "paypal":
        paypal_vault.delete_payment_token(secret.get("vault_id", ""))


@router.delete("/me/linked/{provider}")
def delete_linked(provider: str, request: Request):
    """Disconnect. 200 {"ok": true, "provider", "revoked": true|false} (false: wasn't linked)."""
    try:
        if provider not in PROVIDERS:
            raise Refusal(404, "unknown_provider", "There's no such account to disconnect.")
        _phone, ph = _who(request)
        store = _store()
        row = _db(store.revoke, ph, provider)
        if row:
            _revoke_upstream(provider, row.get("secret_enc") or "")
            if provider == "paypal":
                profile = _db(store.get_profile, ph) or {}
                if profile.get("preferred_payment") == "paypal":
                    _db(store.update_profile, ph, {"preferred_payment": DEFAULT_PAYMENT})
        return JSONResponse({"ok": True, "provider": provider, "revoked": bool(row)}, headers=NO_STORE)
    except (Refusal, AccountConfigError) as e:
        return _refused(e)


def _save_link(phone_hash: str, provider: str, secret: dict, meta: dict) -> None:
    store = _store()
    out = _db(store.link, phone_hash, provider, account_crypto.encrypt(secret), meta)
    if out.get("replaced"):
        _revoke_upstream(provider, out["replaced"])


# --- Dogwood -----------------------------------------------------------------------------------

@router.get("/link/dogwood/start")
def dogwood_start(request: Request):
    """{"authorize_url"}: open it (same tab) to show Dogwood's consent page."""
    try:
        phone, ph = _who(request)
        _store()
        _need_encryption()
        state, _nonce = _new_state(dogwood.STATE_PURPOSE, phone, ph)
        q = urlencode({"client_id": dogwood.CLIENT_ID, "redirect_uri": dogwood.redirect_uri(),
                       "scope": dogwood.SCOPE, "state": state, "display": session_mask(phone)})
        return JSONResponse({"authorize_url": f"{dogwood.site_base()}/dogwood/authorize?{q}"}, headers=NO_STORE)
    except (Refusal, AccountConfigError) as e:
        return _refused(e)


def _back(provider: str, error: str = "") -> RedirectResponse:
    url = app_url(link_error=error, provider=provider) if error else app_url(linked=provider)
    return RedirectResponse(url, status_code=302, headers=NO_STORE)


@router.get("/link/dogwood/callback")
def dogwood_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    """Dogwood's consent page sends the browser here. Always a 302 back to the app."""
    body, problem = _take_state(dogwood.STATE_PURPOSE, state, request)
    if body is None:
        return _back("dogwood", problem)
    if error:
        return _back("dogwood", "access_denied" if error == "access_denied" else "dogwood_error")
    if not code:
        return _back("dogwood", "dogwood_error")
    status, tok = dogwood.exchange_code({"grant_type": "authorization_code", "code": code,
                                         "redirect_uri": dogwood.redirect_uri(),
                                         "client_id": dogwood.CLIENT_ID,
                                         "client_secret": dogwood.client_secret()})
    if status != 200:
        log.info("dogwood code exchange refused: %s", tok.get("error"))
        return _back("dogwood", "dogwood_refused")
    try:
        _save_link(body["ph"], "dogwood",
                   {"access_token": tok["access_token"], "account_id": tok.get("account_id", "")},
                   {"account_name": dogwood.ACCOUNT_NAME, "scope": tok.get("scope", dogwood.SCOPE)})
    except (Refusal, AccountConfigError) as e:
        dogwood.revoke_access_token(tok["access_token"])
        log.warning("dogwood link not saved: %s", getattr(e, "code", type(e).__name__))
        return _back("dogwood", "server_error")
    return _back("dogwood")


# --- PayPal (sandbox) --------------------------------------------------------------------------

@router.get("/link/paypal/start")
def paypal_start(request: Request):
    """{"approve_url"}: open it (same tab); PayPal sandbox sends the browser back to our callback."""
    try:
        paypal_vault.require_configured()
        phone, ph = _who(request)
        _store()
        _need_encryption()
        state, nonce = _new_state(PAYPAL_STATE_PURPOSE, phone, ph)
        back = f"{dogwood.api_base()}/link/paypal/callback?{urlencode({'state': state})}"
        setup = paypal_vault.create_setup_token(back, back + "&cancelled=1", request_id=f"scansafe-setup-{nonce}")
        now = time.time()
        with _lock:
            for k in [k for k, v in _paypal_pending.items() if v["exp"] < now]:
                del _paypal_pending[k]
            _paypal_pending[nonce] = {"setup_token_id": setup["id"], "exp": now + LINK_TTL_S}
        return JSONResponse({"approve_url": setup["approve_url"]}, headers=NO_STORE)
    except (Refusal, AccountConfigError, PayPalError) as e:
        return _refused(e)


@router.get("/link/paypal/callback")
def paypal_callback(request: Request, state: str = "", approval_token_id: str = "", cancelled: str = ""):
    """PayPal sends the browser here after Approve (with approval_token_id) or Cancel."""
    body, problem = _take_state(PAYPAL_STATE_PURPOSE, state, request)
    if body is None:
        return _back("paypal", problem)
    with _lock:
        pending = _paypal_pending.pop(body["n"], None)
    if cancelled:
        return _back("paypal", "cancelled")
    if not pending or not approval_token_id or not hmac.compare_digest(
            pending["setup_token_id"].encode(), approval_token_id.encode()):
        return _back("paypal", "invalid_state")
    try:
        tok = paypal_vault.create_payment_token(approval_token_id, request_id=f"scansafe-pt-{body['n']}")
    except PayPalError as e:
        log.info("paypal payment token refused: %s", e.code)
        return _back("paypal", "paypal_refused")
    try:
        _save_link(body["ph"], "paypal", {"vault_id": tok["id"], "customer_id": tok.get("customer_id", "")},
                   {"display": paypal_vault.mask_email(tok.get("email", "")) or "PayPal (sandbox)",
                    "env": "sandbox"})
    except (Refusal, AccountConfigError) as e:
        paypal_vault.delete_payment_token(tok["id"])
        log.warning("paypal link not saved: %s", getattr(e, "code", type(e).__name__))
        return _back("paypal", "server_error")
    return _back("paypal")


def clear() -> None:  # tests
    with _lock:
        _spent_states.clear()
        _paypal_pending.clear()
