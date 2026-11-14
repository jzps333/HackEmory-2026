"""POST /pay: send an approved Solana Pay payment on devnet, or (payment_method "paypal") charge
the signed-in user's saved PayPal SANDBOX account. Plus pay-by-the-hour parking:
POST /pay/quote, GET /pay/quote/{scan_id}, GET /pay/status/{scan_id} (see api/meter_pay.py).

Mount in api/main.py:  from api.routes_pay import router as pay_router; app.include_router(pay_router)
"""
from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api import account_crypto, meter_pay, paypal_vault, session
from api.account_crypto import AccountConfigError
from api.paypal_vault import PayPalError
from api.merchants import KNOWN_MERCHANTS, meter_for  # noqa: F401  (tests check it's the shared table)
from api.meter_pay import PayStateError
from api.schema import Payment
from api.solana_pay import PaymentError, send_payment

log = logging.getLogger("scansafe.pay")
router = APIRouter()

PAYMENT_METHODS = ("solana_devnet", "paypal")
DEFAULT_METHOD = "solana_devnet"


class PayRequest(BaseModel):
    scan_id: str
    payment: Optional[Payment] = None   # optional: the server's own copy of the scan wins
    approved: bool = False              # true only after the user tapped confirm
    hours: Any = None                   # parking meters: required; the server prices it
    payment_method: Any = None          # "solana_devnet" (default) | "paypal" (signed in, linked)


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


def paypal_amount(payment: Payment, meter, hours: Optional[int]) -> tuple[Decimal, Optional[str]]:
    """(USD amount, demo-rate note or None). Meters: hours x DOGWOOD_RATE_USD. Fixed-price codes:
    their test-SOL amount x DEMO_USD_PER_SOL, a made-up demo rate (labelled as such)."""
    if meter is not None and hours is not None:
        return paypal_vault.usd(paypal_vault.dogwood_rate_usd() * hours), None
    rate = paypal_vault.demo_usd_per_sol()
    return (paypal_vault.usd(Decimal(str(payment.amount_sol)) * rate),
            f"Demo conversion at a fixed {rate} USD per test SOL (not a market price).")


def _pay_paypal(req: PayRequest, request: Request, payment: Payment, meter, hours: Optional[int]):
    """Charge the signed-in user's saved PayPal sandbox account. Same rules as Solana: approved,
    hours for meters, one payment per scan_id."""
    from api.routes_accounts import Refusal, linked_secret
    try:
        paypal_vault.require_configured()
        ph = _signed_in_hash(request)
        if not ph:
            return _error(401, "not_signed_in", "Sign in with your phone to pay with PayPal.")
        secret = linked_secret(ph, "paypal")
        if not secret or not secret.get("vault_id"):
            return _error(403, "paypal_not_linked", "Connect PayPal in your account first.")
        amount, demo_note = paypal_amount(payment, meter, hours)
        cap = paypal_vault.env_decimal("PAYPAL_MAX_USD", "25")
        if not Decimal("0.01") <= amount <= cap:
            return _error(400, "over_cap", f"This demo only charges PayPal sandbox up to ${cap:.2f}.")
    except (Refusal, PayPalError) as e:
        return _error(e.status, e.code, e.message)
    except AccountConfigError as e:
        return _error(503, e.code, e.message)
    meter_pay.claim_owner(req.scan_id, ph)

    try:
        meter_pay.begin_payment(req.scan_id)
    except PayStateError as e:
        return _error(e.status, e.code, e.message)
    what = (f"{hours} hour{'s' if hours != 1 else ''} of parking" if hours is not None else "your order")
    outcome: dict = {}
    try:
        charged = paypal_vault.charge(secret["vault_id"], amount,
                                      f"{payment.label or 'Merchant'}: {what} (ScanSafe demo, sandbox)",
                                      req.scan_id)
        outcome = {"state": "paid", "method": "paypal", "paypal_order_id": charged["order_id"],
                   "paypal_capture_id": charged["capture_id"], "amount_usd": float(amount),
                   "currency": "USD", "hours": hours, "merchant": payment.label,
                   "paid_at": int(time.time())}
        if demo_note:
            outcome["usd_note"] = demo_note
    except PayPalError as e:
        outcome = {"state": "failed", "method": "paypal", "error": e.code, "message": e.message,
                   "amount_usd": float(amount), "hours": hours, "merchant": payment.label}
        return _error(e.status, e.code, e.message)
    finally:
        meter_pay.finish_payment(req.scan_id, outcome)
    body = {"ok": True, "scan_id": req.scan_id, "method": "paypal",
            "paypal_order_id": charged["order_id"], "paypal_capture_id": charged["capture_id"],
            "amount_usd": float(amount), "currency": "USD", "hours": hours, "merchant": payment.label,
            "payment": payment.model_dump(mode="json"), "paid_at": outcome["paid_at"]}
    if demo_note:
        body["usd_note"] = demo_note
    return JSONResponse(body)


@router.post("/pay", response_model=PayResponse,
             responses={400: {}, 401: {}, 402: {}, 403: {}, 404: {}, 409: {}, 502: {}, 503: {}})
def pay(req: PayRequest, request: Request):
    if req.approved is not True:
        return _error(403, "not_approved", "The user has not approved this payment.")
    method = DEFAULT_METHOD if req.payment_method is None else req.payment_method
    if method not in PAYMENT_METHODS:
        return _error(400, "bad_payment_method", 'payment_method must be "solana_devnet" or "paypal".')

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

    if method == "paypal":
        return _pay_paypal(req, request, payment, meter, hours)
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
