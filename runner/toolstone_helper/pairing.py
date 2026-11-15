"""`pair`: phone sign-in (reverse OTP: the person texts a code) then POST /runner/pair.

Never prints the sign-in token, the runner token or the request_id.
"""
from __future__ import annotations

import re
import time
from typing import Callable, Optional

from . import config
from .relay import Relay, RelayError

_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_phone(raw: str) -> Optional[str]:
    """'(404) 555-0123' -> '+14045550123'; '+44 20 7946 0958' stays international."""
    s = re.sub(r"[\s\-().]", "", str(raw or "").strip())
    if s.startswith("+"):
        cand = s if re.fullmatch(r"\+\d+", s) else None
    elif re.fullmatch(r"\d{10}", s):
        cand = "+1" + s
    elif re.fullmatch(r"1\d{10}", s):
        cand = "+" + s
    else:
        cand = None
    return cand if cand and _E164.match(cand) else None


def pair_flow(relay: Relay, phone: str, name: str, out: Callable[[str], None] = print,
              sleep: Callable[[float], None] = time.sleep,
              clock: Callable[[], float] = time.monotonic,
              interval: float = 3.0, max_wait: float = 15 * 60) -> int:
    """Returns a process exit code (0 = paired)."""
    try:
        start = relay.phone_start(phone)
    except RelayError as e:
        out(f"Could not start sign-in: {e.message}")
        return 1
    code, request_id, line = start.get("code"), start.get("request_id"), start.get("line")
    if not code or not request_id or not line:
        out("Could not start sign-in: unexpected response from Toolstone.")
        return 1
    out("")
    out("To pair this computer, send a text from your phone:")
    out(f"  Text {code} to {line}")
    if start.get("sms_body"):
        out(f"  Message: {start['sms_body']}")
    out("Waiting for your text (up to 15 minutes, Ctrl-C to cancel)...")

    token = None
    warned = False
    deadline = clock() + max_wait
    while clock() < deadline:
        sleep(interval)
        try:
            v = relay.phone_verify(phone, request_id)
        except RelayError as e:
            if e.status in (0, 429) or e.status >= 500:
                if not warned:
                    out("Connection problem, still trying...")
                    warned = True
                continue
            out(f"Sign-in failed: {config.redact(e.message, [request_id])}")
            return 1
        if v.get("verified") and v.get("token"):
            token = str(v["token"])
            break
    if not token:
        out("Timed out waiting for the text. Run pair again to get a new code.")
        return 1
    out("Got your text. Pairing this computer...")

    try:
        p = relay.pair(token, name)
    except RelayError as e:
        out(f"Pairing failed: {config.redact(e.message, [token])}")
        return 1
    finally:
        try:   # the runner never needs the phone sign-in token again: revoke it
            relay._call("POST", "/auth/logout", auth=f"Bearer {token}")
        except Exception:
            pass
    runner_token = p.get("runner_token")
    if not runner_token:
        out("Pairing failed: Toolstone did not return a runner token.")
        return 1
    path = config.save_runner(str(runner_token), str(p.get("runner_id") or ""), name, relay.base)
    out(f'Paired as "{name}". Saved to {path} (only you can read it).')
    out("Next: python3 runner/toolstone_runner.py run")
    return 0
