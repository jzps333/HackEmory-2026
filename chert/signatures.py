import hashlib
import hmac
import time
from typing import Mapping, Optional
SIGNATURE_TOLERANCE_S = 300

def _parse_signature(headers: Mapping[str, str]) -> tuple[Optional[int], list[str]]:
    """Return (timestamp, [hex signatures]) from either Chert header format."""
    h = {k.lower(): v for k, v in headers.items()}
    new = h.get("x-webhook-signature")
    if new:  # t=<ts>,v1=<hex>[,v1=<hex>]
        ts, sigs = None, []
        for part in new.split(","):
            k, _, v = part.strip().partition("=")
            if k == "t" and v.isdigit():
                ts = int(v)
            elif k == "v1" and v:
                sigs.append(v.strip().lower())
        if ts is None and h.get("x-webhook-timestamp", "").isdigit():
            ts = int(h["x-webhook-timestamp"])
        return ts, sigs
    legacy = h.get("x-chert-signature")
    if legacy:  # v1,<ts>,<hex>
        bits = [b.strip() for b in legacy.split(",")]
        if len(bits) == 3 and bits[0] == "v1" and bits[1].isdigit():
            return int(bits[1]), [bits[2].lower()]
    return None, []


def verify_signature(secret: str, raw_body: bytes, headers: Mapping[str, str],
                     now: Optional[float] = None) -> bool:
    ts, sigs = _parse_signature(headers)
    if ts is None or not sigs:
        return False
    now = time.time() if now is None else now
    if abs(now - ts) > SIGNATURE_TOLERANCE_S:
        return False
    expected = hmac.new(secret.encode(), str(ts).encode() + b"." + raw_body, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s) for s in sigs)


def sign_for_test(secret: str, raw_body: bytes, ts: Optional[int] = None) -> str:
    """Build an X-Webhook-Signature value (handy for tests and curl)."""
    ts = int(time.time()) if ts is None else ts
    hex_ = hmac.new(secret.encode(), str(ts).encode() + b"." + raw_body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={hex_}"
