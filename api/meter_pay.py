"""Pay-by-the-hour parking: quotes and payment status, kept in memory (enough for a demo).

The app picks hours -> POST /pay/quote stores the server's own price for that scan_id; the
FaceTime agent polls GET /pay/quote/{scan_id} to update the live meter view (that is ALL a quote
is for: anyone with the scan_id can change it, so POST /pay never reads it). POST /pay requires
the hours the user confirmed and charges rate x hours computed here, never an amount from the
app; GET /pay/status/{scan_id} says whether that scan has been paid. One API process holds this state (uvicorn without --workers);
a restart forgets quotes and statuses, which only means the app quotes again.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Optional

from api import recent_scans, result_store
from api.merchants import MeterConfig, is_verified, meter_for
from api.schema import Payment, ScanResult

MAX_ITEMS = 2000
TTL_S = 2 * 60 * 60
MAX_ID_LEN = 64

_lock = threading.Lock()
_quotes: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()
_status: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()
_paying: set[str] = set()
# scan_id -> phone_hash of the signed-in person this meter scan belongs to (set by /call-me,
# claimed by a signed-in /pay/quote or /pay). Only used to show their plate in the Dogwood app.
_owners: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()


class PayStateError(Exception):
    """A refusal with the HTTP status and error code the route returns as-is."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# --- scans and meters --------------------------------------------------------------------------

def lookup_scan(scan_id: str) -> Optional[ScanResult]:
    """The server's own copy of a check: memory (2 h), then the 7-day result store."""
    if not scan_id or len(scan_id) > MAX_ID_LEN:
        return None
    return recent_scans.get(scan_id) or result_store.get(scan_id)


def verified_copy(payment: Payment) -> Payment:
    """A copy whose merchant_verified is OUR answer, whatever the client or file said."""
    p = payment.model_copy()
    p.merchant_verified = is_verified(p.label, p.recipient)
    return p


def meter_scan(scan_id: str) -> tuple[ScanResult, Payment, MeterConfig]:
    """A recent server-side scan of a verified merchant's meter code, or PayStateError."""
    scan = lookup_scan(scan_id)
    if scan is None:
        raise PayStateError(404, "unknown_scan",
                            "We couldn't find this scan. Scan the meter code again.")
    if scan.payment is None:
        raise PayStateError(400, "not_a_payment", "This scan isn't a payment code.")
    payment = verified_copy(scan.payment)
    if not payment.merchant_verified:
        raise PayStateError(403, "merchant_not_verified",
                            f"The wallet does not match {payment.label or 'any known merchant'}. "
                            "Don't pay this code.")
    meter = meter_for(payment.label)
    if meter is None:
        raise PayStateError(400, "not_a_meter",
                            f"{payment.label} charges a fixed amount, not by the hour.")
    return scan, payment, meter


def parse_hours(raw: Any, meter: MeterConfig) -> int:
    """A whole number of hours within the meter's limits, or PayStateError(400, bad_hours)."""
    hours: Optional[int] = None
    if isinstance(raw, bool):
        hours = None
    elif isinstance(raw, int):
        hours = raw
    elif isinstance(raw, float) and raw.is_integer():
        hours = int(raw)
    if hours is None or not meter.min_hours <= hours <= meter.max_hours:
        raise PayStateError(400, "bad_hours",
                            f"Pick a whole number of hours from {meter.min_hours} to "
                            f"{meter.max_hours}.")
    return hours


# --- in-memory stores --------------------------------------------------------------------------

def _put(store: OrderedDict, key: str, value: dict) -> None:
    store[key] = (time.monotonic(), value)
    store.move_to_end(key)
    while len(store) > MAX_ITEMS:
        store.popitem(last=False)


def _get(store: OrderedDict, key: str) -> Optional[dict]:
    item = store.get(key)
    if not item:
        return None
    at, value = item
    if time.monotonic() - at > TTL_S:
        store.pop(key, None)
        return None
    return dict(value)


def make_quote(scan_id: str, raw_hours: Any) -> dict:
    """Validate and store the latest quote for scan_id. Raises PayStateError."""
    _scan, payment, meter = meter_scan(scan_id)
    hours = parse_hours(raw_hours, meter)
    from api import paypal_vault
    usd_rate = paypal_vault.dogwood_rate_usd()
    quote = {"scan_id": scan_id, "merchant": payment.label,
             "rate_per_hour_sol": meter.rate_per_hour_sol, "hours": hours,
             "amount_sol": meter.amount_sol(hours), "min_hours": meter.min_hours,
             "max_hours": meter.max_hours, "meter_url": meter.meter_url,
             # the same hours paid with PayPal sandbox instead (test money, USD)
             "rate_per_hour_usd": float(usd_rate), "amount_usd": float(paypal_vault.usd(usd_rate * hours)),
             "updated_at": round(time.time(), 3)}
    with _lock:
        _put(_quotes, scan_id, quote)
    return dict(quote)


def get_quote(scan_id: str) -> Optional[dict]:
    with _lock:
        return _get(_quotes, scan_id)


def get_status(scan_id: str) -> dict:
    """{"scan_id", "state": "none"|"paid"|"failed", ...}. Never raises."""
    with _lock:
        s = _get(_status, scan_id)
    return s if s else {"scan_id": scan_id, "state": "none"}


def begin_payment(scan_id: str) -> None:
    """Claim scan_id for one payment: a double tap must never pay twice."""
    with _lock:
        s = _get(_status, scan_id)
        if s and s.get("state") == "paid":
            raise PayStateError(409, "already_paid",
                                "This code is already paid. Your receipt is in the app.")
        if scan_id in _paying:
            raise PayStateError(409, "payment_in_progress", "This payment is already being sent.")
        _paying.add(scan_id)


def finish_payment(scan_id: str, status: dict) -> None:
    """Release the claim; record the outcome (a later success replaces a failure)."""
    with _lock:
        _paying.discard(scan_id)
        if status:
            _put(_status, scan_id, {"scan_id": scan_id, **status})


def set_owner(scan_id: str, phone_hash: str) -> None:
    """The person on the FaceTime call for this scan (replaces an earlier claim)."""
    if scan_id and phone_hash:
        with _lock:
            _put(_owners, scan_id, {"phone_hash": phone_hash})


def claim_owner(scan_id: str, phone_hash: str) -> None:
    """Record a signed-in person as the owner, unless someone already is."""
    if scan_id and phone_hash:
        with _lock:
            if _get(_owners, scan_id) is None:
                _put(_owners, scan_id, {"phone_hash": phone_hash})


def get_owner(scan_id: str) -> Optional[str]:
    with _lock:
        o = _get(_owners, scan_id)
    return o["phone_hash"] if o else None


def clear() -> None:  # tests
    with _lock:
        _quotes.clear()
        _status.clear()
        _paying.clear()
        _owners.clear()
