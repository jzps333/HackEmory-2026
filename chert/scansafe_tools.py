"""Framework-agnostic helpers for the FaceTime agent: call the backend, turn a result into speech.

    from chert.scansafe_tools import scan_url, speech_for
    result = scan_url("https://bit.ly/dogwood-meter-42")
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


def _safe_call(fn: Callable, *args: Any) -> None:
    """A broken video callback must never break the scan itself."""
    try:
        fn(*args)
    except Exception:
        log.exception("live stream callback failed")


# --- Dogwood Parking (operator mode): the official app instead of the sticker ------------------
#
# When the person linked their Dogwood account in ScanSafe, the agent drives the made-up official
# Dogwood Parking app in the sandbox (install -> open -> plate -> hours -> Pay, which only asks for
# approval in ScanSafe) and streams it on the FaceTime video. It never pays: the person taps Pay
# in the ScanSafe app. The backend doesn't proxy /operate yet, so the agent server calls the
# sandbox directly with SANDBOX_URL + SANDBOX_TOKEN from the repo .env (it already has them).

DOGWOOD_HOST = "scansafe-demo-sites.vercel.app"
APP_SESSION_TIMEOUT_S = 4.0
OPERATE_TIMEOUT_S = 200.0   # sandbox: steps + up to 120 s waiting for approval (+ its own 180 s cap)
_PLATE_RE = re.compile(r"^[A-Z0-9][A-Z0-9 -]{0,9}$")


def sandbox_configured() -> bool:
    return bool(os.getenv("SANDBOX_URL") and os.getenv("SANDBOX_TOKEN"))


def dogwood_url_ok(url: Any) -> bool:
    """https://scansafe-demo-sites.vercel.app/dogwood/... only (the sandbox checks it again)."""
    if not isinstance(url, str) or len(url) > 2048 or any(c.isspace() for c in url):
        return False
    try:
        from urllib.parse import unquote, urlsplit
        u = urlsplit(url)
        if u.port is not None:
            return False
    except ValueError:
        return False
    path = unquote(u.path)
    return (u.scheme == "https" and u.netloc.lower() == DOGWOOD_HOST and path.startswith("/dogwood/")
            and ".." not in path and "//" not in path and "\\" not in path)


def clean_plate(plate: Any) -> Optional[str]:
    """'ga 4821k' -> 'GA 4821K'; None unless 1-10 letters, digits, spaces or dashes."""
    if not isinstance(plate, str):
        return None
    p = re.sub(r"\s+", " ", plate).strip().upper()
    return p if _PLATE_RE.fullmatch(p) else None


def dogwood_app_session(scan_id: Any, *, client: Optional[httpx.Client] = None,
                        timeout: float = APP_SESSION_TIMEOUT_S) -> Optional[dict]:
    """POST {SCANSAFE_API_URL}/operators/dogwood/app-session {scan_id} (X-Agent-Key header).

    Returns {"app_url", "plate", "linked": True} only when the person linked Dogwood and the
    answer is usable (app_url on our Dogwood pages, a sane plate). None otherwise: not linked,
    no AGENT_INTERNAL_KEY, HTTP error, timeout, bad JSON. Never raises; never logs the key or
    the session token in app_url."""
    key = os.getenv("AGENT_INTERNAL_KEY") or ""
    if not key or not isinstance(scan_id, str) or not scan_id:
        return None
    endpoint = f"{api_url()}/operators/dogwood/app-session"
    try:
        kw = dict(json={"scan_id": scan_id}, headers={"X-Agent-Key": key}, timeout=timeout)
        r = client.post(endpoint, **kw) if client is not None else httpx.post(endpoint, **kw)
        if r.status_code != 200:
            log.info("dogwood app-session: HTTP %s; using the meter flow", r.status_code)
            return None
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        log.info("dogwood app-session failed (%s); using the meter flow", type(e).__name__)
        return None
    if not isinstance(data, dict) or data.get("linked") is not True:
        return None
    plate = clean_plate(data.get("plate"))
    if not dogwood_url_ok(data.get("app_url")) or plate is None:
        log.warning("dogwood app-session: unusable app_url or plate; using the meter flow")
        return None
    return {"app_url": data["app_url"], "plate": plate, "linked": True}


def operate_failed(why: str) -> dict:
    return {"mode": "operate", "status": "failed", "paid": False, "steps": [], "error": why[:300],
            "screenshots": []}


def operate_stream(url: str, plate: str, hours: int, on_frame: Callable[[bytes], Any],
                   on_nav: Optional[Callable[[str], Any]] = None,
                   on_step: Optional[Callable[[str, str], Any]] = None,
                   should_stop: Optional[Callable[[], bool]] = None,
                   *, client: Optional[httpx.Client] = None,
                   timeout: float = OPERATE_TIMEOUT_S, payload: Optional[dict] = None,
                   statuses: tuple = ("paid", "waiting", "failed")) -> Optional[dict]:
    """POST {SANDBOX_URL}/operate/stream {url, plate, hours} and watch the Dogwood app being used.
    (``payload``/``statuses``: another adapter's request body and result statuses, see
    parkmobile_stream.)

    Blocking (run it with asyncio.to_thread). Same NDJSON as the scan stream:
      {"type": "frame", "jpeg": ...}          -> on_frame(jpeg_bytes)
      {"type": "nav", "url": ...}             -> on_nav(url)
      {"type": "step", "text": ..., "step"}   -> on_step(text, step_id)
      {"type": "result", "data": {...}}       -> returned ({"mode": "operate", "status": "paid" |
                                                 "waiting" | "failed", "steps": [...], ...})
    None if ``should_stop()`` turned True (the stream is closed; the sandbox removes the
    container). Any failure (sandbox not configured or not deployed yet, HTTP error, bad JSON,
    timeout, error line) returns ``operate_failed(why)``. Never raises, never falls back to a scan."""
    def stopped() -> bool:
        try:
            return bool(should_stop and should_stop())
        except Exception:
            return False

    base, token = os.getenv("SANDBOX_URL") or "", os.getenv("SANDBOX_TOKEN") or ""
    if not base or not token:
        return operate_failed("sandbox not configured")
    endpoint = f"{base.rstrip('/')}/operate/stream"
    deadline = time.monotonic() + timeout
    result: Any = None
    why = "stream ended without a result"
    own = client is None
    c = client or httpx.Client()
    try:
        body = payload if payload is not None else {"url": url, "plate": plate, "hours": int(hours)}
        with c.stream("POST", endpoint, json=body,
                      headers={"Authorization": f"Bearer {token}"},
                      timeout=httpx.Timeout(timeout, connect=STREAM_CONNECT_S)) as resp:
            if resp.status_code != 200:
                resp.read()
                detail = ""
                try:
                    detail = str((resp.json() or {}).get("detail") or "")[:200]
                except (ValueError, AttributeError):
                    pass
                why = f"HTTP {resp.status_code}" + (f": {detail}" if detail else "")
            else:
                for line in resp.iter_lines():
                    if stopped():
                        return None                  # leaving the with-block closes the stream
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
                            continue
                        if jpeg:
                            _safe_call(on_frame, jpeg)
                    elif kind == "nav" and on_nav is not None and isinstance(msg.get("url"), str):
                        _safe_call(on_nav, msg["url"])
                    elif kind == "step" and on_step is not None and isinstance(msg.get("text"), str):
                        _safe_call(on_step, msg["text"][:120], str(msg.get("step") or ""))
                    elif kind == "result":
                        result = msg.get("data")
                        break
                    elif kind == "error":
                        why = str(msg.get("detail") or "sandbox error")[:300]
                        break
    except httpx.TimeoutException:
        why = "stream timeout"
    except Exception as e:    # connection refused, bad JSON, broken stream...
        why = f"{type(e).__name__}: {e}"[:300]
    finally:
        if own:
            c.close()
    if stopped():
        return None
    if isinstance(result, dict) and result.get("status") in statuses:
        return result
    if result is not None:
        why = "unexpected result shape"
    log.info("operate stream (%s): %s", (payload or {}).get("adapter") or "dogwood", why)
    return operate_failed(why)


# --- ParkMobile (adapter "parkmobile"): the REAL official web app, stops before payment --------

PARKMOBILE_TIMEOUT_S = 140.0   # sandbox caps the run at 120 s
PARKMOBILE_STATUSES = ("ready_to_pay", "needs_sign_in", "robot_check", "failed")


def parkmobile_stream(url: str, zone: Optional[str], plate: str, minutes: int,
                      on_frame: Callable[[bytes], Any],
                      on_nav: Optional[Callable[[str], Any]] = None,
                      on_step: Optional[Callable[[str, str], Any]] = None,
                      should_stop: Optional[Callable[[], bool]] = None,
                      *, client: Optional[httpx.Client] = None,
                      timeout: float = PARKMOBILE_TIMEOUT_S) -> Optional[dict]:
    """POST {SANDBOX_URL}/operate/stream {"adapter": "parkmobile", url, zone, plate, minutes}: the
    sandbox fills in the real ParkMobile web app and stops at the first sign-in / contact-details /
    payment / price screen. Returns its result ({"status": "ready_to_pay" | "needs_sign_in" |
    "robot_check" | "failed", "price_text"?, "zone_name"?, "stopped_at", ...}), None if
    ``should_stop()`` turned True, operate_failed(why) on any failure. Never raises, never pays."""
    body = {"adapter": "parkmobile", "url": url, "zone": zone, "plate": plate, "minutes": int(minutes)}
    return operate_stream(url, plate, 0, on_frame, on_nav, on_step, should_stop, client=client,
                          timeout=timeout, payload=body, statuses=PARKMOBILE_STATUSES)


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
