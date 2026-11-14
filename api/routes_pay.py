"""POST /pay: send an approved Solana Pay payment on devnet, or (payment_method "virtual_card") pay
a Dogwood parking meter with a one-time Lithic SANDBOX virtual card the server mints for exactly that
amount. Plus pay-by-the-hour parking: POST /pay/quote, GET /pay/quote/{scan_id},
GET /pay/status/{scan_id} (see api/meter_pay.py).

Mount in api/main.py:  from api.routes_pay import router as pay_router; app.include_router(pay_router)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api import account_crypto, lithic_cards, meter_pay, session
from api.account_crypto import AccountConfigError
from api.lithic_cards import CardError
from api.merchants import KNOWN_MERCHANTS, meter_for  # noqa: F401  (tests check it's the shared table)
from api.meter_pay import PayStateError
from api.schema import Payment
from api.solana_pay import PaymentError, send_payment

log = logging.getLogger("scansafe.pay")
router = APIRouter()

PAYMENT_METHODS = ("solana_devnet", "virtual_card")
DEFAULT_METHOD = "solana_devnet"

_sessions_lock = threading.Lock()
_dogwood_sessions: dict[str, str] = {}    # scan_id -> Dogwood session_id (reused on a retry)


class PayRequest(BaseModel):
    scan_id: str
    payment: Optional[Payment] = None   # optional: the server's own copy of the scan wins
    approved: bool = False              # true only after the user tapped confirm
    hours: Any = None                   # parking meters: required; the server prices it
    payment_method: Any = None          # "solana_devnet" (default) | "virtual_card" (signed in, meters)


class PayResponse(BaseModel):
    ok: bool = True
    scan_id: str
    signature: str
    explorer_url: str
    payment: Payment                    # with tx_signature filled in
    amount_sol: float                   # what was actually sent (set by the server)
    hours: Optional[int] = None         # parking meters only


class QuoteRequest(BaseModel):
    scan_id: str
    hours: Any = None


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"ok": False, "error": code, "message": message})


def _signed_in_hash(request: Request) -> Optional[str]:
    phone = session.current_phone(request)
    return account_crypto.phone_hash(phone) if phone else None


def _claim(scan_id: str, request: Request) -> None:
    """Signed in: remember this scan as theirs (the Dogwood app view shows their plate).
    Never raises: a quote or a payment must never fail over this."""
    if not session.request_tokens(request):
        return
    try:
        ph = _signed_in_hash(request)
        if ph:
            meter_pay.claim_owner(scan_id, ph)
    except Exception as e:  # noqa: BLE001
        log.warning("couldn't remember the scan owner: %s", type(e).__name__)


def _dogwood_session(token: str, scan_id: str, meter_id: str, plate: str, hours: int) -> str:
    """The Dogwood parking session to pay for this scan: an earlier unpaid one with the same
    plate and hours, else a new one. Raises CardError."""
    from api import dogwood
    with _sessions_lock:
        prev = _dogwood_sessions.get(scan_id)
    if prev:
        status, s = dogwood.get_session(token, prev)
        if status == 200 and s["status"] == "pending_payment" and (s["plate"], s["hours"]) == (plate, hours):
            return prev
    status, s = dogwood.create_session(token, meter_id, plate, hours)
    if status == 401:
        raise CardError(409, "dogwood_relink_needed", "Reconnect Dogwood Parking in your account.")
    if status != 200:
        raise CardError(502, "dogwood_error", "Dogwood couldn't start the parking session. Nothing was charged.")
    with _sessions_lock:
        _dogwood_sessions[scan_id] = s["session_id"]
        while len(_dogwood_sessions) > 2000:
            _dogwood_sessions.pop(next(iter(_dogwood_sessions)))
    return s["session_id"]


def _pay_virtual_card(req: PayRequest, request: Request, payment: Payment, meter, hours: Optional[int]):
    """Mint a SINGLE_USE Lithic sandbox card whose limit is exactly hours x DOGWOOD_RATE_USD, and
    pay Dogwood with it server to server (the operator API, in-process). The card is closed
    afterwards whatever happens. Same rules as Solana: approved, hours, one payment per scan."""
    from api import dogwood
    from api.merchants import env_decimal, meter_usd
    from api.routes_accounts import Refusal, get_plate, linked_secret
    if meter is None or hours is None:
        return _error(400, "not_a_meter", "Virtual cards pay parking meters only. Pay this code with the devnet wallet.")
    if payment.label != dogwood.OPERATOR:
        return _error(400, "not_dogwood", "Virtual cards only pay Dogwood Lot & Meter Co. meters in this demo.")
    try:
        lithic_cards.require_configured()
        ph = _signed_in_hash(request)
        if not ph:
            return _error(401, "not_signed_in", "Sign in with your phone to pay with a virtual card.")
        dw = linked_secret(ph, "dogwood")
        if not dw or not dw.get("access_token"):
            return _error(403, "dogwood_not_linked", "Connect Dogwood Parking in your account first.")
        plate = get_plate(ph)
        if not plate:
            return _error(400, "plate_required", "Add your plate in your account first.")
    except (Refusal, CardError) as e:
        return _error(e.status, e.code, e.message)
    except AccountConfigError as e:
        return _error(503, e.code, e.message)
    amount = meter_usd(hours)
    cents = int(amount * 100)
    cap = env_decimal("VIRTUAL_CARD_MAX_USD", "25")
    if amount > cap:
        return _error(400, "over_cap", f"This demo only pays up to ${cap:.2f} with a virtual card.")
    meter_pay.claim_owner(req.scan_id, ph)

    try:
        meter_pay.begin_payment(req.scan_id)
    except PayStateError as e:
        return _error(e.status, e.code, e.message)
    card_token, outcome = "", {}
    base = {"method": "virtual_card", "provider": lithic_cards.PROVIDER, "amount_usd": float(amount),
            "currency": "USD", "hours": hours, "merchant": payment.label}
    try:
        session_id = _dogwood_session(dw["access_token"], req.scan_id, meter.meter_id, plate, hours)
        card = lithic_cards.create_card(cents, memo=f"ScanSafe \u00b7 Dogwood meter {meter.meter_id} \u00b7 {req.scan_id}")
        card_token = card.token
        try:
            status, paid = dogwood.pay_session(dw["access_token"], session_id, card)
        finally:
            card.wipe()
            del card
        if status != 200:
            raise CardError(status if status in (400, 402, 409) else 502, paid.get("error") or "dogwood_error",
                            paid.get("message") or "Dogwood couldn't take the payment. Nothing was charged.")
        p = paid["payment"]
        outcome = {"state": "paid", **base, "card_last4": p["card_last4"], "card_token": card_token,
                   "authorization_token": p.get("authorization_token"), "settled": p.get("settled"),
                   "simulated": True, "dogwood_session_id": session_id, "paid_at": p["paid_at"]}
    except CardError as e:
        outcome = {"state": "failed", **base, "error": e.code, "message": e.message}
        return _error(e.status, e.code, e.message)
    finally:
        if card_token:
            closed = lithic_cards.close_card(card_token)   # success or failure: never leave it open
            if outcome:
                outcome["card_closed"] = closed
        meter_pay.finish_payment(req.scan_id, outcome)
    return JSONResponse({"ok": True, "scan_id": req.scan_id, **{k: v for k, v in outcome.items() if k != "state"},
                         "payment": payment.model_dump(mode="json")})


@router.post("/pay", response_model=PayResponse,
             responses={400: {}, 401: {}, 402: {}, 403: {}, 404: {}, 409: {}, 502: {}, 503: {}})
def pay(req: PayRequest, request: Request):
    if req.approved is not True:
        return _error(403, "not_approved", "The user has not approved this payment.")
    method = DEFAULT_METHOD if req.payment_method is None else req.payment_method
    if method not in PAYMENT_METHODS:
        return _error(400, "bad_payment_method", 'payment_method must be "solana_devnet" or "virtual_card".')

    # The server's own copy of the scan wins over whatever the client sends.
    scan = meter_pay.lookup_scan(req.scan_id)
    source = scan.payment if scan is not None and scan.payment is not None else req.payment
    if source is None:
        if scan is None:
            return _error(404, "unknown_scan", "We couldn't find this scan. Scan the code again.")
        return _error(400, "not_a_payment", "This scan isn't a payment code.")

    # Never trust the client's merchant_verified flag: re-check against our own list.
    payment = meter_pay.verified_copy(source)
    if not payment.merchant_verified:
        return _error(403, "merchant_not_verified",
                      f"The wallet does not match {payment.label or 'any known merchant'}. "
                      "Payment refused.")

    hours: Optional[int] = None
    meter = meter_for(payment.label)
    if meter is not None:
        # Parking by the hour: the server sets the amount from the hours the user confirmed in
        # THIS request. Any amount from the app is ignored, and the stored quote is never used
        # (anyone with the scan_id can change it; it only drives the FaceTime live view).
        if req.hours is None:
            return _error(400, "hours_required",
                          f"hours is required: pick {meter.min_hours} to {meter.max_hours} hours.")
        try:
            hours = meter_pay.parse_hours(req.hours, meter)
        except PayStateError as e:
            return _error(e.status, e.code, e.message)
        payment.amount_sol = meter.amount_sol(hours)
        payment.message = (f"Meter {meter.meter_id} " if meter.meter_id else "Parking ") + \
            f"- {hours} hour{'s' if hours != 1 else ''}"

    if method == "virtual_card":
        return _pay_virtual_card(req, request, payment, meter, hours)
    _claim(req.scan_id, request)

    try:
        meter_pay.begin_payment(req.scan_id)
    except PayStateError as e:
        return _error(e.status, e.code, e.message)
    outcome: dict = {}
    try:
        sent = send_payment(payment)
        payment.tx_signature = sent["signature"]
        outcome = {"state": "paid", "signature": sent["signature"],
                   "explorer_url": sent["explorer_url"], "amount_sol": payment.amount_sol,
                   "hours": hours, "merchant": payment.label, "method": "solana_devnet",
                   "paid_at": int(time.time())}
    except PaymentError as e:
        outcome = {"state": "failed", "error": e.code, "message": e.message,
                   "amount_sol": payment.amount_sol, "hours": hours, "merchant": payment.label,
                   "method": "solana_devnet"}
        return _error(e.status, e.code, e.message)
    finally:
        meter_pay.finish_payment(req.scan_id, outcome)

    return PayResponse(scan_id=req.scan_id, signature=sent["signature"],
                       explorer_url=sent["explorer_url"], payment=payment,
                       amount_sol=payment.amount_sol, hours=hours)


@router.post("/pay/quote", responses={400: {}, 403: {}, 404: {}})
def quote(req: QuoteRequest, request: Request):
    """Price `hours` of parking for a meter code the server scanned; the latest one is kept.
    Signed in: the scan is remembered as yours (the Dogwood app view then shows your plate)."""
    try:
        q = meter_pay.make_quote(req.scan_id, req.hours)
    except PayStateError as e:
        return _error(e.status, e.code, e.message)
    _claim(req.scan_id, request)
    return q


@router.get("/pay/quote/{scan_id}", responses={404: {}})
def latest_quote(scan_id: str):
    q = meter_pay.get_quote(scan_id)
    if q is None:
        return _error(404, "no_quote", "No hours have been picked for this scan yet.")
    return q


@router.get("/pay/status/{scan_id}")
def pay_status(scan_id: str) -> dict:
    """{"scan_id", "state": "none" | "paid" | "failed", ...}. Unknown ids are "none"."""
    return meter_pay.get_status(scan_id)
