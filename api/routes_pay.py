"""POST /pay: send an approved Solana Pay payment on devnet. Plus pay-by-the-hour parking:
POST /pay/quote, GET /pay/quote/{scan_id}, GET /pay/status/{scan_id} (see api/meter_pay.py).

Mount in api/main.py:  from api.routes_pay import router as pay_router; app.include_router(pay_router)
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api import meter_pay
from api.merchants import KNOWN_MERCHANTS, meter_for  # noqa: F401  (tests check it's the shared table)
from api.meter_pay import PayStateError
from api.schema import Payment
from api.solana_pay import PaymentError, send_payment

router = APIRouter()


class PayRequest(BaseModel):
    scan_id: str
    payment: Optional[Payment] = None   # optional: the server's own copy of the scan wins
    approved: bool = False              # true only after the user tapped confirm
    hours: Any = None                   # parking meters: required; the server prices it


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


@router.post("/pay", response_model=PayResponse,
             responses={400: {}, 403: {}, 404: {}, 409: {}, 502: {}, 503: {}})
def pay(req: PayRequest):
    if req.approved is not True:
        return _error(403, "not_approved", "The user has not approved this payment.")

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
                   "hours": hours, "merchant": payment.label}
    except PaymentError as e:
        outcome = {"state": "failed", "error": e.code, "message": e.message,
                   "amount_sol": payment.amount_sol, "hours": hours, "merchant": payment.label}
        return _error(e.status, e.code, e.message)
    finally:
        meter_pay.finish_payment(req.scan_id, outcome)

    return PayResponse(scan_id=req.scan_id, signature=sent["signature"],
                       explorer_url=sent["explorer_url"], payment=payment,
                       amount_sol=payment.amount_sol, hours=hours)


@router.post("/pay/quote", responses={400: {}, 403: {}, 404: {}})
def quote(req: QuoteRequest):
    """Price `hours` of parking for a meter code the server scanned; the latest one is kept."""
    try:
        return meter_pay.make_quote(req.scan_id, req.hours)
    except PayStateError as e:
        return _error(e.status, e.code, e.message)


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
