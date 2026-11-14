"""Framework-agnostic helpers for the FaceTime agent: call the backend, turn a result into speech.

    from chert.scansafe_tools import scan_url, speech_for
    result = scan_url("https://bit.ly/peachtree-park-42")
    text = speech_for(result)    # short, slow, plain words, verdict first

Nothing here imports LiveKit, so it is easy to test and reuse (web app, iMessage, etc.).

Safety: the page we scanned is attacker-controlled. Its title, domain and text (and anything a
model wrote after reading it, like ``explanation``) can contain instructions aimed at our agent.
So the spoken script is built ONLY from fixed sentences picked by structured fields
(``verdict``, ``scam_type``, ``checks``, ``flagged_before``, ``payment.merchant_verified``).
No page text is ever read aloud or handed to the voice model as an instruction.
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import re
import threading
import time
from typing import Any, Callable, Optional

import httpx

log = logging.getLogger("scansafe.tools")

DEFAULT_API_URL = "http://127.0.0.1:8000"
SCAN_TIMEOUT_S = 60.0
STREAM_TIMEOUT_S = 75.0     # whole live-stream scan, start to result
STREAM_CONNECT_S = 5.0      # a missing/down stream endpoint should fail fast and fall back

# Words an elderly caller shouldn't have to decode. speech_for() never produces them.
JARGON = ("phishing", "redirect", "url", "domain", "malware", "sandbox", "jev", "probability",
          "score", "http", "solana", "wallet address", "credential")

FALLBACK_EXPLANATION = (
    "I couldn't finish checking this code. To be safe, please don't pay or type anything on it "
    "for now. You can try again in a minute."
)


def api_url() -> str:
    return (os.getenv("SCANSAFE_API_URL") or DEFAULT_API_URL).rstrip("/")


def fallback_result(url: str, reason: str) -> dict:
    """What scan_url returns when the backend can't be reached or answers badly."""
    return {
        "scan_id": None,
        "url": url,
        "verdict": "error",
        "scam_type": "none",
        "explanation": FALLBACK_EXPLANATION,
        "checks": {},
        "screenshots": [],
        "flagged_before": 0,
        "payment": None,
        "error": reason,
    }


def scan_url(url: str, lat: Optional[float] = None, lng: Optional[float] = None,
             *, client: Optional[httpx.Client] = None, timeout: float = SCAN_TIMEOUT_S) -> dict:
    """POST {SCANSAFE_API_URL}/scan and return the ScanResult as a dict.

    Never raises: on a network error, timeout, or bad response it returns ``fallback_result``
    (``verdict == "error"``) so the agent always has something kind to say.
    Location is only sent when both lat and lng are given (the caller agreed to share it).
    """
    body: dict[str, Any] = {"url": url}
    if lat is not None and lng is not None:
        body["lat"], body["lng"] = float(lat), float(lng)
    endpoint = f"{api_url()}/scan"
    try:
        if client is not None:
            resp = client.post(endpoint, json=body, timeout=timeout)
        else:
            resp = httpx.post(endpoint, json=body, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except httpx.TimeoutException:
        return fallback_result(url, "timeout")
    except (httpx.HTTPError, ValueError) as e:  # ValueError covers bad JSON
        return fallback_result(url, f"{type(e).__name__}: {e}"[:300])
    if not isinstance(data, dict) or data.get("verdict") not in ("safe", "suspicious", "malicious"):
        return fallback_result(url, "unexpected response shape")
    return data


def scan_url_stream(url: str, on_frame: Callable[[bytes], Any],
                    on_nav: Optional[Callable[[str], Any]] = None,
                    should_stop: Optional[Callable[[], bool]] = None,
                    lat: Optional[float] = None, lng: Optional[float] = None,
                    *, client: Optional[httpx.Client] = None,
                    timeout: float = STREAM_TIMEOUT_S) -> Optional[dict]:
    """POST {SCANSAFE_API_URL}/scan/stream and watch the sandbox browser while it works.

    Blocking (run it with asyncio.to_thread). The endpoint answers NDJSON, one object per line:
      {"type": "frame", "jpeg": "<base64>", "t_ms": 1234}  -> on_frame(jpeg_bytes)
      {"type": "nav", "url": "https://..."}                -> on_nav(url)
      {"type": "result", "data": {...}}                    -> returned (same dict as POST /scan)

    Returns None if ``should_stop()`` turned True (the stream is closed, nothing else is sent).
    On ANY failure before a usable result (endpoint missing/404, connection error, bad JSON,
    stream ends without a result, timeout) it falls back to the plain ``scan_url`` and returns
    that, so callers get exactly what they got before. Never raises.
    """
    def stopped() -> bool:
        try:
            return bool(should_stop and should_stop())
        except Exception:
            return False

    body: dict[str, Any] = {"url": url}
    if lat is not None and lng is not None:
        body["lat"], body["lng"] = float(lat), float(lng)
    endpoint = f"{api_url()}/scan/stream"
    deadline = time.monotonic() + timeout
    result: Any = None
    why = "stream ended without a result"
    own = client is None
    c = client or httpx.Client()
    try:
        with c.stream("POST", endpoint, json=body,
                      timeout=httpx.Timeout(timeout, connect=STREAM_CONNECT_S)) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if stopped():
                    return None                      # leaving the with-block closes the stream
                if time.monotonic() > deadline:
                    why = "stream timeout"
                    break
                line = line.strip()
                if not line:
                    continue
                msg = json.loads(line)
                kind = msg.get("type") if isinstance(msg, dict) else None
                if kind == "frame":
                    try:
                        jpeg = base64.b64decode(msg.get("jpeg") or "", validate=False)
                    except (binascii.Error, ValueError, TypeError):
                        continue                     # one bad frame isn't worth a rescan
                    if jpeg:
                        _safe_call(on_frame, jpeg)
                elif kind == "nav" and on_nav is not None and isinstance(msg.get("url"), str):
                    _safe_call(on_nav, msg["url"])
                elif kind == "result":
                    result = msg.get("data")
                    break
    except httpx.TimeoutException:
        why = "stream timeout"
    except Exception as e:    # 404 (not deployed), connection error, bad JSON, broken stream...
        why = f"{type(e).__name__}: {e}"[:300]
    finally:
        if own:
            c.close()
    if stopped():
        return None
    if isinstance(result, dict) and result.get("verdict") in ("safe", "suspicious", "malicious"):
        return result
    if result is not None:
        why = "unexpected result shape"
    log.info("live stream unavailable (%s); falling back to POST /scan", why)
    return scan_url(url, lat, lng, client=client)


def _safe_call(fn: Callable, arg: Any) -> None:
    """A broken video callback must never break the scan itself."""
    try:
        fn(arg)
    except Exception:
        log.exception("live stream callback failed")


# --- Speech ------------------------------------------------------------------------------------

# "It's <thing>." for each scam_type. Plain words only.
SCAM_PHRASES = {
    "fake_bank": "a fake bank page",
    "fake_payment_app": "a fake payment app page",
    "fake_parking_or_toll": "a fake parking page",
    "fake_delivery": "a fake delivery page",
    "fake_government": "a fake government page",
    "tech_support": "a fake tech support page",
    "fake_login_other": "a fake sign-in page",
    "malware_download": "a page that tries to put a harmful app on your phone",
    "other": "a scam page",
}


FLAGGED_REASON = "Other people nearby have reported this same code."


def _checks(result: dict) -> dict:
    c = result.get("checks") or {}
    return c if isinstance(c, dict) else {}


def _num(d: dict, key: str) -> float:
    try:
        return float(d.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _danger_reason(result: dict) -> str:
    """One plain reason a malicious/suspicious page is risky, from structured fields only."""
    c = _checks(result)
    payment = result.get("payment") or {}
    if isinstance(payment, dict) and payment and not payment.get("merchant_verified", False):
        return "The money would not go to the business it names."
    if result.get("scam_type") == "malware_download":
        return "It tries to download something harmful."
    if _num(c, "asks_payment_p") >= 0.5 and _num(c, "impersonates_p") >= 0.5:
        return "It asks for your card number, but the website does not belong to that company."
    if _num(c, "asks_password_p") >= 0.5 and _num(c, "impersonates_p") >= 0.5:
        return "It asks for your password, but the website does not belong to that company."
    if _num(c, "asks_payment_p") >= 0.5:
        return "It asks for your card number, and I can't tell who would get the money."
    if _num(c, "asks_password_p") >= 0.5:
        return "It asks for your password, and I can't tell who runs the website."
    if _num(c, "impersonates_p") >= 0.5:
        return "It pretends to be a company it isn't."
    if int(result.get("flagged_before") or 0) > 0:
        return FLAGGED_REASON
    return "It doesn't act like a real business website."


def _safe_reason(result: dict) -> str:
    payment = result.get("payment") or {}
    if isinstance(payment, dict) and payment.get("merchant_verified"):
        return "It's a payment to the business it names, and their account checks out."
    return "I didn't see it asking for anything it shouldn't."


def speech_for(result: dict, *, will_text: bool = True) -> str:
    """A short, slow, plain-words script for the caller. Verdict first, one reason, then the text.

    Examples:
      malicious -> "Please don't pay this. It's a fake parking page. It asks for your card
                    number, but the website does not belong to that company. I'll text you
                    the details."
      safe      -> "This one looks safe. I didn't see it asking for anything it shouldn't.
                    I'll text you the details."
    """
    verdict = (result or {}).get("verdict")
    scam_type = (result or {}).get("scam_type") or "none"
    parts: list[str]
    if verdict == "malicious":
        phrase = SCAM_PHRASES.get(scam_type)
        parts = ["Please don't pay this.",
                 f"It's {phrase}." if phrase else "It looks like a scam.",
                 _danger_reason(result)]
    elif verdict == "suspicious":
        parts = ["Please be careful with this one.",
                 "I'm not sure it's safe.",
                 _danger_reason(result),
                 "Don't pay or sign in until you check with the business yourself."]
    elif verdict == "safe":
        parts = ["This one looks safe.", _safe_reason(result)]
    else:  # error / unknown
        parts = [FALLBACK_EXPLANATION]
        will_text = False
    if (verdict == "malicious" and int((result or {}).get("flagged_before") or 0) > 0
            and FLAGGED_REASON not in parts):
        parts.append("Other people nearby have reported it too.")
    if will_text:
        parts.append("I'll text you the details.")
    return " ".join(p for p in parts if p)


def has_jargon(text: str) -> bool:
    low = text.lower()
    return any(re.search(rf"\b{re.escape(w)}", low) for w in JARGON)


# --- Debounce ----------------------------------------------------------------------------------

class CodeDebouncer:
    """Remembers codes we've already handled so the agent doesn't repeat itself every frame."""

    def __init__(self, window_s: float = 30.0, clock=time.monotonic) -> None:
        self.window_s = window_s
        self._clock = clock
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def should_handle(self, code: str) -> bool:
        """True (and starts the window) if ``code`` wasn't handled in the last ``window_s``."""
        now = self._clock()
        with self._lock:
            last = self._seen.get(code)
            if last is not None and now - last < self.window_s:
                return False
            self._seen[code] = now
            # keep the dict small on long calls
            for k in [k for k, t in self._seen.items() if now - t >= self.window_s]:
                if k != code:
                    del self._seen[k]
            return True
