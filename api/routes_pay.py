"""POST /pay: send an approved Solana Pay payment on devnet.

Mount in api/main.py:  from api.routes_pay import router as pay_router; app.include_router(pay_router)
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.scan import KNOWN_MERCHANTS
from api.schema import Payment
from api.solana_pay import PaymentError, send_payment

router = APIRouter()


class PayRequest(BaseModel):
    scan_id: str
    payment: Payment
    approved: bool = False          # true only after the user tapped confirm


class PayResponse(BaseModel):
    ok: bool = True
    scan_id: str
    signature: str
    explorer_url: str
    payment: Payment                # with tx_signature filled in


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"ok": False, "error": code, "message": message})


@router.post("/pay", response_model=PayResponse,
             responses={400: {}, 403: {}, 502: {}, 503: {}})
def pay(req: PayRequest):
    if req.approved is not True:
        return _error(403, "not_approved", "The user has not approved this payment.")

    # Never trust the client's merchant_verified flag: re-check against our own list.
    payment = req.payment.model_copy()
    payment.merchant_verified = (
        bool(payment.label) and KNOWN_MERCHANTS.get(payment.label) == payment.recipient
    )
    if not payment.merchant_verified:
        return _error(403, "merchant_not_verified",
                      f"The wallet does not match {payment.label or 'any known merchant'}. "
                      "Payment refused.")

    try:
        sent = send_payment(payment)
    except PaymentError as e:
        return _error(e.status, e.code, e.message)

    payment.tx_signature = sent["signature"]
    return PayResponse(scan_id=req.scan_id, signature=sent["signature"],
                       explorer_url=sent["explorer_url"], payment=payment)
