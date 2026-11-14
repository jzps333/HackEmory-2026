"""One-time virtual cards from Lithic's SANDBOX, minted by the server to pay the demo parking
operator. Test money only: the base URL is hard-coded to the sandbox and LITHIC_ENV must be
"sandbox", so a production key can't move real money.

Shapes follow the Lithic API reference (docs.lithic.com, read 2026-11-14):
  auth     header `Authorization: <api key>` (raw key, no "Bearer")
  POST  /v1/cards              {type: "SINGLE_USE", spend_limit (cents), spend_limit_duration:
                                "TRANSACTION", memo, state: "OPEN"} + Idempotency-Key (UUID)
                               -> {token, last_four, pan, cvv, exp_month, exp_year, spend_limit, state, type, ...}
                               SINGLE_USE: "Card is closed upon first successful authorization."
                               (pan/cvv come back in sandbox; production needs PCI.)
  PATCH /v1/cards/{token}      {state: "CLOSED"}  (final, can't be undone)
  POST  /v1/simulate/authorize {amount (cents), descriptor (1-25 chars), pan (16 digits), mcc}
                               -> 201 {token, debugging_request_id}; a decline carries "message"
                                  (e.g. "Transaction exceeds user-set transaction limit") or is a 422
  POST  /v1/simulate/clearing  {token}  -> PENDING becomes SETTLED
  GET   /v1/transactions/{token} -> {result: "APPROVED" | <decline reason>, status, ...}
                               TODO(verify): `result`/`status` names are from the transaction
                               schema; used only as an extra decline check.

Env (never log values): LITHIC_API_KEY (the SANDBOX key from the Lithic Dashboard),
LITHIC_ENV=sandbox (required). Card numbers, CVVs and expiry: held in a CardDetails (whose repr
hides them) for the length of one payment, passed in-process to the operator, never logged,
stored or returned. Response bodies of card calls are never logged.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Optional

import httpx

from api import config  # noqa: F401  (loads .env)

log = logging.getLogger("scansafe.lithic")

BASE_URL = "https://sandbox.lithic.com"     # hard-coded: sandbox only tonight
TIMEOUT_S = 20
PARKING_MCC = "7523"                        # parking lots and garages
PROVIDER = "lithic_sandbox"


class CardError(Exception):
    """A refusal or failure with the HTTP status and error code the route returns as-is."""

    def __init__(self, status: int, code: str, message: str, upstream_status: int = 0):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.upstream_status = upstream_status


class CardDetails:
    """Full card details, only for the length of one payment. repr/str never show the PAN,
    CVV or expiry."""
    __slots__ = ("token", "pan", "cvv", "exp_month", "exp_year", "last4")

    def __init__(self, token: str, pan: str, cvv: str, exp_month, exp_year, last4: str = ""):
        self.token, self.pan, self.cvv = str(token or ""), str(pan or ""), str(cvv or "")
        self.exp_month, self.exp_year = exp_month, exp_year
        self.last4 = str(last4 or self.pan[-4:])

    def __repr__(self) -> str:
        return f"CardDetails(token={self.token!r}, last4={self.last4!r})"

    __str__ = __repr__

    def wipe(self) -> None:
        self.pan = self.cvv = ""
        self.exp_month = self.exp_year = None


def config_problem() -> Optional[tuple[str, str]]:
    """None when usable, else (error code, plain-words reason)."""
    if not os.getenv("LITHIC_API_KEY", "").strip():
        return ("lithic_not_configured", "One-time virtual cards aren't set up on this server (LITHIC_API_KEY).")
    if os.getenv("LITHIC_ENV", "").strip().lower() != "sandbox":
        return ("lithic_sandbox_only", "Virtual cards are sandbox only tonight: set LITHIC_ENV=sandbox.")
    return None


def is_configured() -> bool:
    return config_problem() is None


def require_configured() -> None:
    problem = config_problem()
    if problem:
        raise CardError(503, *problem)


def _http() -> httpx.Client:   # tests replace this with a MockTransport client
    return httpx.Client(timeout=TIMEOUT_S)


def _call(method: str, path: str, body: Optional[dict] = None, idempotency_key: str = "",
          ok: tuple = (200, 201)) -> tuple[int, dict]:
    require_configured()
    headers = {"Authorization": os.getenv("LITHIC_API_KEY", "").strip(), "Accept": "application/json"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    try:
        with _http() as client:
            r = client.request(method, f"{BASE_URL}{path}", json=body, headers=headers)
    except httpx.HTTPError:
        raise CardError(502, "lithic_unreachable", "We couldn't reach the card network. Nothing was charged.") from None
    if r.status_code not in ok:
        # Only the route name and status: bodies can echo card data.
        log.warning("lithic %s %s failed: HTTP %s", method, "/".join(path.split("/")[1:3]), r.status_code)
        if r.status_code == 401:
            raise CardError(502, "lithic_auth_failed", "The card provider didn't accept the server's sandbox key.",
                            upstream_status=401)
        raise CardError(502, "lithic_error", f"The card provider refused the request (HTTP {r.status_code}).",
                        upstream_status=r.status_code)
    try:
        return r.status_code, (r.json() if r.content else {})
    except ValueError:
        raise CardError(502, "lithic_error", "The card provider sent a reply we couldn't read.") from None


def create_card(amount_cents: int, memo: str) -> CardDetails:
    """Mint a SINGLE_USE card whose spend limit is exactly amount_cents (per transaction)."""
    if not isinstance(amount_cents, int) or amount_cents < 1:
        raise CardError(400, "bad_amount", "That amount isn't valid.")
    _, card = _call("POST", "/v1/cards", {"type": "SINGLE_USE", "spend_limit": amount_cents,
                                          "spend_limit_duration": "TRANSACTION", "memo": memo[:200],
                                          "state": "OPEN"},
                    idempotency_key=str(uuid.uuid4()))
    token = card.get("token") or ""
    if not token:
        raise CardError(502, "lithic_error", "The card provider didn't return a card.")
    if card.get("spend_limit") != amount_cents or card.get("type") not in (None, "SINGLE_USE"):
        close_card(token)
        raise CardError(502, "lithic_error", "The card came back with the wrong limit, so it was closed.")
    if not card.get("pan") or not card.get("cvv"):
        close_card(token)
        raise CardError(502, "lithic_no_pan", "The card provider didn't return the card number (sandbox only).")
    return CardDetails(token=token, pan=card["pan"], cvv=card["cvv"], exp_month=card.get("exp_month"),
                       exp_year=card.get("exp_year"), last4=card.get("last_four") or "")


def simulate_authorize(pan: str, amount_cents: int, descriptor: str, mcc: str = PARKING_MCC) -> str:
    """Sandbox authorization at the merchant; the card's limit really applies. Returns the
    transaction token. Raises CardError(402, "card_declined") on a decline."""
    try:
        _, out = _call("POST", "/v1/simulate/authorize",
                       {"amount": amount_cents, "descriptor": descriptor[:25], "pan": pan, "mcc": mcc})
    except CardError as e:
        if e.upstream_status in (400, 402, 409, 422):
            raise CardError(402, "card_declined", "The card was declined. Nothing was charged.",
                            upstream_status=e.upstream_status) from None
        raise
    if out.get("message") or not out.get("token"):
        log.info("lithic: simulated authorization declined")
        raise CardError(402, "card_declined", "The card was declined. Nothing was charged.")
    tx = transaction(out["token"])
    if tx and (tx.get("status") == "DECLINED" or tx.get("result") not in (None, "APPROVED")):
        log.info("lithic: transaction not approved: %s", str(tx.get("result"))[:40])
        raise CardError(402, "card_declined", "The card was declined. Nothing was charged.")
    return out["token"]


def transaction(token: str) -> Optional[dict]:
    """The transaction (result/status only matter here), or None if it can't be read. Never raises."""
    try:
        _, tx = _call("GET", f"/v1/transactions/{token}")
        return {"result": tx.get("result"), "status": tx.get("status")}
    except CardError:
        return None


def simulate_clearing(token: str) -> bool:
    """Settle a simulated authorization. True on success. Never raises."""
    try:
        _call("POST", "/v1/simulate/clearing", {"token": token})
        return True
    except CardError as e:
        log.warning("lithic clearing failed: %s", e.code)
        return False


def close_card(card_token: str) -> bool:
    """Close the card for good (SINGLE_USE closes itself after its first authorization; this
    covers failures). True if it is closed. Never raises."""
    if not card_token:
        return False
    try:
        _, card = _call("PATCH", f"/v1/cards/{card_token}", {"state": "CLOSED"})
        return card.get("state") == "CLOSED"
    except CardError as e:
        log.warning("lithic close failed: %s", e.code)
    except Exception as e:  # noqa: BLE001 - cleanup must never mask the real outcome
        log.warning("lithic close failed: %s", type(e).__name__)
    try:   # maybe it was already closed (a used SINGLE_USE card)
        _, card = _call("GET", f"/v1/cards/{card_token}")
        return card.get("state") == "CLOSED"
    except Exception:  # noqa: BLE001
        return False
