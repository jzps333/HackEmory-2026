"""PayPal SANDBOX Vault: save a PayPal account once (setup token -> payment token), then pay with
it (order with payment_source.paypal.vault_id, intent CAPTURE). Test money only.

Env: PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET (a sandbox REST app from developer.paypal.com),
PAYPAL_ENV=sandbox (required; anything else is refused). The base URL is hard-coded to the
sandbox and never comes from env, so live money can't move even with live credentials.
Never log the client secret, access tokens or vault ids.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional

import httpx

from api import config  # noqa: F401  (loads .env)

log = logging.getLogger("scansafe.paypal")

SANDBOX_BASE = "https://api-m.sandbox.paypal.com"
TIMEOUT_S = 20

_lock = threading.Lock()
_token: dict = {"value": "", "exp": 0.0}


class PayPalError(Exception):
    """A refusal or failure with the HTTP status and error code the route returns as-is."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def config_problem() -> str:
    """"" when PayPal sandbox is usable, else a plain-words reason."""
    if not os.getenv("PAYPAL_CLIENT_ID", "").strip() or not os.getenv("PAYPAL_CLIENT_SECRET", "").strip():
        return "PayPal isn't set up on this server (PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET)."
    if os.getenv("PAYPAL_ENV", "").strip().lower() != "sandbox":
        return "PayPal is sandbox only here: set PAYPAL_ENV=sandbox."
    return ""


def is_configured() -> bool:
    return not config_problem()


def require_configured() -> None:
    problem = config_problem()
    if problem:
        raise PayPalError(503, "paypal_not_configured", problem)


def _http() -> httpx.Client:   # tests replace this with a MockTransport client
    return httpx.Client(timeout=TIMEOUT_S)


def reset() -> None:  # tests
    with _lock:
        _token.update(value="", exp=0.0)


def _access_token(client: httpx.Client) -> str:
    with _lock:
        if _token["value"] and _token["exp"] > time.time() + 60:
            return _token["value"]
    try:
        r = client.post(f"{SANDBOX_BASE}/v1/oauth2/token", data={"grant_type": "client_credentials"},
                        auth=(os.getenv("PAYPAL_CLIENT_ID", "").strip(), os.getenv("PAYPAL_CLIENT_SECRET", "").strip()),
                        headers={"Accept": "application/json"})
    except httpx.HTTPError:
        raise PayPalError(502, "paypal_unreachable", "We couldn't reach PayPal. Nothing was charged.") from None
    if r.status_code != 200:
        log.warning("paypal oauth failed: HTTP %s", r.status_code)
        raise PayPalError(502, "paypal_auth_failed", "PayPal didn't accept the server's sandbox credentials.")
    body = r.json()
    with _lock:
        _token.update(value=body["access_token"], exp=time.time() + float(body.get("expires_in", 300)))
        return _token["value"]


def _call(method: str, path: str, body: Optional[dict] = None, request_id: str = "",
          ok: tuple = (200, 201)) -> dict:
    require_configured()
    with _http() as client:
        headers = {"Authorization": f"Bearer {_access_token(client)}", "Content-Type": "application/json",
                   "Prefer": "return=representation"}
        if request_id:
            headers["PayPal-Request-Id"] = request_id[:108]
        try:
            r = client.request(method, f"{SANDBOX_BASE}{path}", json=body, headers=headers)
        except httpx.HTTPError:
            raise PayPalError(502, "paypal_unreachable", "We couldn't reach PayPal. Nothing was charged.") from None
    if r.status_code not in ok:
        try:
            err = r.json()
        except ValueError:
            err = {}
        name = str(err.get("name") or "")[:60]
        issue = str(((err.get("details") or [{}])[0] or {}).get("issue") or "")[:60]
        log.warning("paypal %s %s failed: HTTP %s %s %s debug_id=%s", method, path.split("/")[2:4],
                    r.status_code, name, issue, str(err.get("debug_id") or "")[:40])
        raise PayPalError(502, "paypal_error", f"PayPal refused the request (HTTP {r.status_code}"
                                               f"{', ' + (issue or name) if (issue or name) else ''}).")
    if r.status_code == 204 or not r.content:
        return {}
    return r.json()


def _link(body: dict, rel: str) -> str:
    for link in body.get("links") or []:
        if link.get("rel") == rel and link.get("href"):
            return link["href"]
    return ""


def create_setup_token(return_url: str, cancel_url: str, request_id: str) -> dict:
    """Step 1 of saving PayPal. Returns {"id", "approve_url"} (send the user to approve_url)."""
    body = {"payment_source": {"paypal": {
        "description": "ScanSafe demo: pay parking with PayPal (sandbox, test money only)",
        "usage_pattern": "IMMEDIATE", "usage_type": "MERCHANT", "customer_type": "CONSUMER",
        "permit_multiple_payment_tokens": False,
        "experience_context": {"brand_name": "ScanSafe (demo)", "locale": "en-US",
                               "shipping_preference": "NO_SHIPPING",
                               "return_url": return_url, "cancel_url": cancel_url}}}}
    out = _call("POST", "/v3/vault/setup-tokens", body, request_id=request_id)
    approve = _link(out, "approve")
    if not out.get("id") or not approve:
        raise PayPalError(502, "paypal_error", "PayPal didn't return an approval link.")
    return {"id": out["id"], "approve_url": approve}


def create_payment_token(setup_token_id: str, request_id: str) -> dict:
    """Step 2, after the user approved: {"id" (the vault id), "customer_id", "email"}."""
    out = _call("POST", "/v3/vault/payment-tokens",
                {"payment_source": {"token": {"id": setup_token_id, "type": "SETUP_TOKEN"}}},
                request_id=request_id)
    if not out.get("id"):
        raise PayPalError(502, "paypal_error", "PayPal didn't save the account.")
    paypal = (out.get("payment_source") or {}).get("paypal") or {}
    return {"id": out["id"], "customer_id": (out.get("customer") or {}).get("id") or "",
            "email": paypal.get("email_address") or ""}


def delete_payment_token(vault_id: str) -> None:
    """Best effort: forget the saved account at PayPal too. Never raises."""
    if not vault_id or not is_configured():
        return
    try:
        _call("DELETE", f"/v3/vault/payment-tokens/{vault_id}", ok=(200, 204))
    except PayPalError as e:
        log.warning("paypal delete payment token failed: %s", e.code)


def env_decimal(name: str, default: str) -> Decimal:
    """A positive, finite number from env, else the default."""
    try:
        d = Decimal(os.getenv(name, "").strip() or default)
        if d.is_finite() and d > 0:
            return d
    except ArithmeticError:
        pass
    return Decimal(default)


def dogwood_rate_usd() -> Decimal:
    """USD per hour for Dogwood meters paid with PayPal sandbox (env DOGWOOD_RATE_USD)."""
    return env_decimal("DOGWOOD_RATE_USD", "2.50")


def demo_usd_per_sol() -> Decimal:
    """Made-up fixed demo rate for fixed-price codes paid with PayPal (env DEMO_USD_PER_SOL)."""
    return env_decimal("DEMO_USD_PER_SOL", "100")


def usd(value) -> Decimal:
    try:
        d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise PayPalError(400, "bad_amount", "That amount isn't valid.") from None
    return d


def charge(vault_id: str, amount: Decimal, description: str, scan_id: str) -> dict:
    """Create an order paid by the saved account and capture it. Returns {"order_id",
    "capture_id", "status"}. The PayPal-Request-Id depends on scan and amount, so a retry
    after a lost response returns the same order instead of charging twice."""
    value = f"{amount:.2f}"
    request_id = f"scansafe-{scan_id}-{value.replace('.', '')}"
    order = _call("POST", "/v2/checkout/orders", {
        "intent": "CAPTURE",
        "purchase_units": [{"reference_id": scan_id[:256], "custom_id": scan_id[:127],
                            "description": description[:127],
                            "amount": {"currency_code": "USD", "value": value}}],
        "payment_source": {"paypal": {"vault_id": vault_id}},
    }, request_id=request_id)
    if order.get("status") in ("CREATED", "APPROVED", "SAVED"):
        order = _call("POST", f"/v2/checkout/orders/{order.get('id')}/capture", {},
                      request_id=request_id + "-capture")
    if order.get("status") == "PAYER_ACTION_REQUIRED":
        raise PayPalError(409, "paypal_needs_approval",
                          "PayPal wants the user to approve this payment again. Reconnect PayPal.")
    captures = [c for pu in order.get("purchase_units") or []
                for c in ((pu.get("payments") or {}).get("captures") or [])]
    capture = captures[0] if captures else {}
    if order.get("status") != "COMPLETED" or capture.get("status") in ("DECLINED", "FAILED"):
        log.warning("paypal order not completed: %s / %s", order.get("status"), capture.get("status"))
        raise PayPalError(402, "paypal_declined", "PayPal declined the payment. Nothing was charged.")
    return {"order_id": order.get("id") or "", "capture_id": capture.get("id") or "",
            "status": capture.get("status") or order.get("status")}


def mask_email(email: str) -> str:
    """"jane.doe@example.com" -> "j•••@example.com" ("" if it isn't an email)."""
    local, at, domain = (email or "").partition("@")
    if not at or not local or not domain:
        return ""
    return f"{local[0]}•••@{domain}"
