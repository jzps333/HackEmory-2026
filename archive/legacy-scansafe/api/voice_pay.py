"""Voice-confirmed payments for the FaceTime agent: single-use payment intents (in memory).

The agent never pays on its own. It asks for an intent; the SERVER prices it from its own data
(verified merchant, meter config, rate x hours, the owner's plate) and returns a fixed readback
line. Only a confirm that carries the caller's transcribed words, and those words pass the strict
consent rule (chert.voice_pay.consent_ok, the same rule the agent applies first), pays, once:

  create_intent(scan_id, hours, method?, plate?) -> {intent_id, readback, amount_sol, ..., expires_at}
  confirm(intent_id, utterance)                  -> (HTTP status, POST /pay result + pay status)
  cancel(intent_id)

Rules: one open intent per scan (a new one replaces it); 45 s to live; single use (also when the
payment then fails: ask for a new intent); 3 confirm tries per intent; never above the payment
caps (0.05 SOL, VIRTUAL_CARD_MAX_USD). Routes and the X-Agent-Key check: api/routes_voicepay.py.

How the payment is executed (re-point here if POST /pay changes):
  solana_devnet -> api.routes_pay.pay(PayRequest(scan_id, hours, approved=True,
                   payment_method="solana_devnet"), <a request with no sign-in>), the POST /pay
                   handler itself, in-process.
  virtual_card  -> _pay_virtual_card_as_owner() below: the same steps as
                   api.routes_pay._pay_virtual_card, but paid for the scan's owner as the server
                   recorded it (meter_pay.get_owner, set by /call-me), never an identity the agent
                   or a client sent. routes_pay's version reads the payer from the request's
                   sign-in, which the agent doesn't have, and that file is owned by another branch.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from fastapi.responses import JSONResponse
from starlette.requests import Request

from api import meter_pay
from api.merchants import MeterConfig
from api.meter_pay import PayStateError
from chert.voice_pay import consent_ok, hours_text, sol_text

log = logging.getLogger("scansafe.voicepay")

INTENT_TTL_S = 45.0
MAX_CONFIRM_TRIES = 3
MAX_INTENTS = 2000
METHODS = ("solana_devnet", "virtual_card")
DEFAULT_METHOD = "solana_devnet"

_lock = threading.Lock()
_intents: dict[str, "Intent"] = {}
_by_scan: dict[str, str] = {}


class IntentError(Exception):
    """A refusal with the HTTP status and error code the route returns as-is."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass
class Intent:
    intent_id: str
    scan_id: str
    hours: int
    method: str
    amount_sol: Optional[float]          # solana_devnet: what will be sent
    amount_usd: Optional[float]          # virtual_card: the card's exact limit
    merchant: str
    spoken_name: str
    plate: Optional[str]
    created_at: float
    expires_at: float
    owner_hash: Optional[str] = None     # virtual_card payer (server's own owner map); never returned
    used: bool = False
    tries: int = 0

    def public(self) -> dict:
        return {"intent_id": self.intent_id, "scan_id": self.scan_id, "hours": self.hours,
                "method": self.method, "amount_sol": self.amount_sol, "amount_usd": self.amount_usd,
                "merchant": self.merchant, "plate": self.plate, "readback": readback(self),
                "created_at": round(self.created_at, 3), "expires_at": round(self.expires_at, 3),
                "expires_in": int(INTENT_TTL_S)}


# --- readback --------------------------------------------------------------------------------------

def readback(i: Intent) -> str:
    plate = f", plate {i.plate}" if i.plate else ""
    if i.method == "virtual_card":
        return (f"Pay ${i.amount_usd:.2f} to {i.spoken_name} for {hours_text(i.hours)}{plate}, "
                "with a one-time virtual card. Say 'yes, pay' to confirm.")
    return (f"Pay {sol_text(i.amount_sol)} SOL to {i.spoken_name} for {hours_text(i.hours)}{plate}. "
            "Say 'yes, pay' to confirm, or 'no' to cancel.")


# --- making an intent ------------------------------------------------------------------------------

def _owner_profile(owner: Optional[str]) -> dict:
    """The owner's saved profile (plate, preferred_payment), or {}. Never raises."""
    if not owner:
        return {}
    try:
        from data import accounts_store
        return accounts_store.get_store().get_profile(owner) or {}
    except Exception as e:  # noqa: BLE001 - a plate is nice to have, never required for SOL
        log.info("voice pay: couldn't read the owner's profile: %s", type(e).__name__)
        return {}


def _card_ready(owner: Optional[str], label: str) -> tuple[Optional[str], Optional[IntentError]]:
    """(owner's plate, None) when a virtual-card payment can go ahead for this owner and merchant,
    else (None, why not). Same checks as routes_pay._pay_virtual_card, before anything is minted."""
    from api import dogwood, lithic_cards
    from api.account_crypto import AccountConfigError
    from api.routes_accounts import Refusal, get_plate, linked_secret
    if label != dogwood.OPERATOR:
        return None, IntentError(400, "not_dogwood", "Virtual cards only pay Dogwood Lot & Meter Co. meters.")
    problem = lithic_cards.config_problem()
    if problem:
        return None, IntentError(503, *problem)
    if not owner:
        return None, IntentError(401, "not_signed_in",
                                 "This call isn't tied to a signed-in ScanSafe account, so there's no card to use.")
    try:
        dw = linked_secret(owner, "dogwood")
        if not dw or not dw.get("access_token"):
            return None, IntentError(403, "dogwood_not_linked", "Connect Dogwood Parking in your account first.")
        plate = get_plate(owner)
    except Refusal as e:
        return None, IntentError(e.status, e.code, e.message)
    except AccountConfigError as e:
        return None, IntentError(503, e.code, e.message)
    if not plate:
        return None, IntentError(400, "plate_required", "Add your plate in your account first.")
    return plate, None


def _clean_plate(raw: Any) -> Optional[str]:
    """Optional plate from the agent: 1 to 10 of A-Z, 0-9, space or dash. IntentError otherwise."""
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        raise IntentError(400, "bad_plate", "plate must be 1 to 10 letters, numbers, spaces or dashes.")
    p = re.sub(r"\s+", " ", raw).strip().upper()
    if not re.fullmatch(r"[A-Z0-9 -]{1,10}", p) or not re.search(r"[A-Z0-9]", p):
        raise IntentError(400, "bad_plate", "plate must be 1 to 10 letters, numbers, spaces or dashes.")
    return p


def _prune(now: float) -> None:
    for k in [k for k, i in _intents.items() if i.expires_at < now - 60]:
        i = _intents.pop(k)
        if _by_scan.get(i.scan_id) == k:
            _by_scan.pop(i.scan_id, None)
    while len(_intents) > MAX_INTENTS:
        k = next(iter(_intents))
        i = _intents.pop(k)
        if _by_scan.get(i.scan_id) == k:
            _by_scan.pop(i.scan_id, None)


def create_intent(scan_id: Any, hours: Any, method: Any = None, plate: Any = None,
                  now: Optional[float] = None) -> dict:
    """Price and store a single-use intent for a verified meter scan. Raises IntentError.
    method: "solana_devnet" | "virtual_card"; left out -> the owner's saved preference when a card
    payment can go ahead for them, else "solana_devnet"."""
    from api import solana_pay
    from api.merchants import env_decimal, meter_usd
    if not isinstance(scan_id, str) or not scan_id:
        raise IntentError(400, "bad_scan_id", "scan_id is required.")
    if method is not None and method not in METHODS:
        raise IntentError(400, "bad_payment_method", 'method must be "solana_devnet" or "virtual_card".')
    agent_plate = _clean_plate(plate)
    try:
        _scan, payment, meter = meter_pay.meter_scan(scan_id)   # verified merchant + meter, or refusal
        n = meter_pay.parse_hours(hours, meter)
    except PayStateError as e:
        raise IntentError(e.status, e.code, e.message) from None
    if meter_pay.get_status(scan_id).get("state") == "paid":
        raise IntentError(409, "already_paid", "This code is already paid. The receipt is in the app.")

    owner = meter_pay.get_owner(scan_id)
    profile = _owner_profile(owner)
    if method is None:
        method = DEFAULT_METHOD
        if profile.get("preferred_payment") == "virtual_card" and _card_ready(owner, payment.label)[1] is None:
            method = "virtual_card"

    amount_sol: Optional[float] = None
    amount_usd: Optional[float] = None
    if method == "virtual_card":
        card_plate, why = _card_ready(owner, payment.label)
        if why is not None:
            raise why
        usd: Decimal = meter_usd(n)
        cap = env_decimal("VIRTUAL_CARD_MAX_USD", "25")
        if usd > cap:
            raise IntentError(400, "over_cap", f"This demo only pays up to ${cap:.2f} with a virtual card.")
        amount_usd = float(usd)
        the_plate = card_plate                      # what Dogwood will be told: the owner's saved plate
    else:
        amount_sol = meter.amount_sol(n)
        if not amount_sol > 0 or amount_sol > solana_pay.MAX_SOL:
            raise IntentError(400, "over_cap", f"Demo cap is {solana_pay.MAX_SOL} SOL per payment.")
        the_plate = profile.get("plate") or agent_plate   # our own record wins over the agent's

    t = time.time() if now is None else now
    intent = Intent(intent_id="pi_" + secrets.token_urlsafe(16), scan_id=scan_id, hours=n, method=method,
                    amount_sol=amount_sol, amount_usd=amount_usd, merchant=payment.label,
                    spoken_name=_spoken(meter, payment.label), plate=the_plate, created_at=t,
                    expires_at=t + INTENT_TTL_S, owner_hash=owner if method == "virtual_card" else None)
    with _lock:
        _prune(t)
        old = _by_scan.get(scan_id)
        if old:
            _intents.pop(old, None)                 # one open intent per scan: the new one wins
        _intents[intent.intent_id] = intent
        _by_scan[scan_id] = intent.intent_id
    log.info("voice pay: intent for %s (%s, %d h)", scan_id, method, n)
    return intent.public()


def _spoken(meter: MeterConfig, label: str) -> str:
    return meter.spoken_name or label.replace("&", "and")


# --- confirm / cancel ------------------------------------------------------------------------------

def _take(intent_id: str, utterance: Any, now: float) -> Intent:
    """Under the lock: check everything and mark the intent used. Raises IntentError."""
    with _lock:
        i = _intents.get(intent_id or "")
        if i is None:
            raise IntentError(404, "unknown_intent", "There's no payment like that. Prepare it again.")
        if i.used:
            raise IntentError(409, "intent_used", "This payment was already confirmed once.")
        if now >= i.expires_at:
            _intents.pop(intent_id, None)
            if _by_scan.get(i.scan_id) == intent_id:
                _by_scan.pop(i.scan_id, None)
            raise IntentError(410, "intent_expired", "This payment offer timed out. Prepare it again.")
        i.tries += 1
        if i.tries > MAX_CONFIRM_TRIES:
            _intents.pop(intent_id, None)
            if _by_scan.get(i.scan_id) == intent_id:
                _by_scan.pop(i.scan_id, None)
            raise IntentError(429, "too_many_tries", "Too many tries. Prepare the payment again.")
        if not consent_ok(utterance):
            raise IntentError(403, "no_consent", "The caller hasn't clearly said 'yes, pay'.")
        i.used = True
        if _by_scan.get(i.scan_id) == intent_id:
            _by_scan.pop(i.scan_id, None)
        return i


def confirm(intent_id: str, utterance: Any, now: Optional[float] = None) -> tuple[int, dict]:
    """Pay an intent once the caller's words are a clear "yes, pay". (HTTP status, body). The body
    is the POST /pay result (or its error) plus "status": GET /pay/status for the scan."""
    t = time.time() if now is None else now
    try:
        i = _take(intent_id, utterance, t)
    except IntentError as e:
        return e.status, {"ok": False, "error": e.code, "message": e.message}
    log.info("voice pay: consent ok; paying %s (%s)", i.scan_id, i.method)
    try:
        status, body = execute(i)
    except Exception:  # noqa: BLE001 - never leave the caller without an answer
        log.exception("voice pay: payment crashed")
        status, body = 500, {"ok": False, "error": "payment_failed", "message": "The payment failed. Nothing was sent."}
    out = {**body, "intent_id": i.intent_id, "method": i.method, "status": meter_pay.get_status(i.scan_id)}
    return status, out


def cancel(intent_id: str) -> tuple[int, dict]:
    with _lock:
        i = _intents.get(intent_id or "")
        if i is None:
            return 200, {"ok": True, "cancelled": False}
        if i.used:
            return 409, {"ok": False, "error": "intent_used", "message": "This payment was already confirmed."}
        _intents.pop(intent_id, None)
        if _by_scan.get(i.scan_id) == intent_id:
            _by_scan.pop(i.scan_id, None)
    log.info("voice pay: intent for %s cancelled", i.scan_id)
    return 200, {"ok": True, "cancelled": True}


def get(intent_id: str) -> Optional[Intent]:  # tests
    with _lock:
        return _intents.get(intent_id)


def clear() -> None:  # tests
    with _lock:
        _intents.clear()
        _by_scan.clear()


# --- executing the payment -------------------------------------------------------------------------

def _no_sign_in_request() -> Request:
    """A request with no Authorization header and no cookie: POST /pay then claims nothing for
    anyone and charges exactly what the server computes for the scan and hours."""
    return Request({"type": "http", "method": "POST", "path": "/pay", "headers": [], "query_string": b""})


def _as_result(resp: Any) -> tuple[int, dict]:
    if isinstance(resp, JSONResponse):
        try:
            return resp.status_code, json.loads(bytes(resp.body))
        except ValueError:
            return resp.status_code, {"ok": resp.status_code == 200}
    if hasattr(resp, "model_dump"):
        return 200, resp.model_dump(mode="json")
    return 500, {"ok": False, "error": "payment_failed", "message": "Unexpected payment result."}


def execute(i: Intent) -> tuple[int, dict]:
    """Do the payment the caller agreed to: approved, explicit hours, the intent's method."""
    from api import routes_pay
    if i.method == "virtual_card":
        return _pay_virtual_card_as_owner(i)
    req = routes_pay.PayRequest(scan_id=i.scan_id, approved=True, hours=i.hours, payment_method="solana_devnet")
    return _as_result(routes_pay.pay(req, _no_sign_in_request()))


def _error(status: int, code: str, message: str) -> tuple[int, dict]:
    return status, {"ok": False, "error": code, "message": message}


def _pay_virtual_card_as_owner(i: Intent) -> tuple[int, dict]:
    """routes_pay._pay_virtual_card, step for step (same refusals, card closed whatever happens,
    same pay status), for the payer the server recorded as the scan's owner."""
    from api import dogwood, lithic_cards, routes_pay
    from api.lithic_cards import CardError
    from api.merchants import env_decimal, meter_usd
    try:
        _scan, payment, meter = meter_pay.meter_scan(i.scan_id)
        hours = meter_pay.parse_hours(i.hours, meter)
    except PayStateError as e:
        return _error(e.status, e.code, e.message)
    owner = meter_pay.get_owner(i.scan_id)
    if not owner or not i.owner_hash or owner != i.owner_hash:
        return _error(409, "owner_changed", "This call's account changed. Prepare the payment again.")
    plate, why = _card_ready(owner, payment.label)
    if why is not None:
        return _error(why.status, why.code, why.message)
    amount = meter_usd(hours)
    if i.amount_usd is None or float(amount) != i.amount_usd:
        return _error(409, "price_changed", "The price changed. Prepare the payment again.")
    cap = env_decimal("VIRTUAL_CARD_MAX_USD", "25")
    if amount > cap:
        return _error(400, "over_cap", f"This demo only pays up to ${cap:.2f} with a virtual card.")
    from api.routes_accounts import Refusal, linked_secret
    try:
        dw = linked_secret(owner, "dogwood") or {}
    except Refusal as e:
        return _error(e.status, e.code, e.message)
    cents = int(amount * 100)
    payment.amount_sol = meter.amount_sol(hours)        # as POST /pay sets it for meters
    payment.message = (f"Meter {meter.meter_id} " if meter.meter_id else "Parking ") + \
        f"- {hours} hour{'s' if hours != 1 else ''}"

    try:
        meter_pay.begin_payment(i.scan_id)
    except PayStateError as e:
        return _error(e.status, e.code, e.message)
    card_token, outcome = "", {}
    base = {"method": "virtual_card", "provider": lithic_cards.PROVIDER, "amount_usd": float(amount),
            "currency": "USD", "hours": hours, "merchant": payment.label}
    try:
        session_id = routes_pay._dogwood_session(dw["access_token"], i.scan_id, meter.meter_id, plate, hours)
        card = lithic_cards.create_card(cents, memo=f"ScanSafe · Dogwood meter {meter.meter_id} · {i.scan_id}")
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
        meter_pay.finish_payment(i.scan_id, outcome)
    return 200, {"ok": True, "scan_id": i.scan_id, **{k: v for k, v in outcome.items() if k != "state"},
                 "payment": payment.model_dump(mode="json")}
