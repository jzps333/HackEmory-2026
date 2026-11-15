"""FaceTime agent, parking meter mode: pay by voice, but only after the caller clearly agrees.

The agent never decides to pay. The flow, for one verified meter scan:

  1. Caller asks to pay -> the model calls prepare_payment -> POST /pay/intent (X-Agent-Key).
     The SERVER prices it (rate x hours, verified merchant, plate from its own records) and
     returns a single-use intent (45 s) with a fixed `readback` line. The model must read that
     line word for word: "Pay 0.03 SOL to Dogwood Lot and Meter for 3 hours, plate GA 4821K.
     Say 'yes, pay' to confirm, or 'no' to cancel."
  2. Caller answers. Gemini Live transcribes the caller (input transcription); we keep the latest
     FINAL transcript and when it arrived (Heard), plus when the agent was speaking.
  3. The model calls confirm_payment. It only reaches the server if ALL of these hold locally:
     an open intent; the agent spoke the readback after the intent was made (a speaking stretch
     long enough for that line) and the caller didn't talk over it; the caller's latest final
     transcript came after that, within 20 s, and passes consent_ok() ("yes"/"yeah"/"yep"/
     "confirm" AND "pay" as words, no "no"/"don't"/"not"/"stop"/"cancel"/"wait", no question,
     at most 8 words). The server checks the same utterance again, then pays once.
  4. Paid: the meter flow's status poll says the "Paid..." line and shows the Paid banner
     (and, for a linked Dogwood account, the Dogwood app shows its receipt), exactly as when
     the caller taps Pay in the ScanSafe app, which keeps working the same way.

"No", "stop", "cancel" (or the stop tool) cancel the open intent. So does the app changing the
hours, or the meter being paid in the app.

No LiveKit imports here (unit-testable); the API imports consent_ok() from this module so the
agent and the server use one rule.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Any, Callable, Optional

import httpx

from chert.scansafe_tools import api_url, clean_plate

log = logging.getLogger("scansafe.voicepay")

AFFIRM = frozenset({"yes", "yeah", "yep", "confirm"})
NEGATIONS = frozenset({"no", "not", "don't", "dont", "stop", "cancel", "wait", "nope", "nah",
                       "never", "hold", "later", "maybe", "if"})
DECLINES = frozenset({"no", "nope", "nah", "stop", "cancel", "wait", "don't", "dont", "never"})
MAX_CONSENT_WORDS = 8
_WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")

CONSENT_WINDOW_S = 20.0      # "yes, pay" must come within this long after the readback ended
CONSENT_WAIT_S = 1.5         # confirm_payment waits this long for the caller's transcript to land
MIN_READBACK_S_PER_WORD = 0.15   # a speaking stretch shorter than this x words isn't the readback
FALLBACK_READBACK_S_PER_WORD = 0.3   # no agent-state events at all: assume it took this long
INTENT_TIMEOUT_S = 5.0
CONFIRM_TIMEOUT_S = 45.0     # a virtual-card payment can take a while (same as the app's timeout)


# --- the consent rule (shared with api/voice_pay.py) ---------------------------------------------

def _words(text: Any) -> list[str]:
    if not isinstance(text, str):
        return []
    t = text.lower().replace("’", "'").replace("`", "'")
    return [w.strip("'") for w in _WORD.findall(t)]


def _negated(word: str) -> bool:
    return word in NEGATIONS or word.endswith("n't")


def consent_ok(utterance: Any, verb: str = "pay") -> bool:
    """True only for a short, clear yes to paying: "yes, pay", "yeah pay it", "yep, go ahead and
    pay", "confirm, pay". Never for "pay", "yes", "no pay", "yes, don't pay", "yes pay. wait",
    "yes, how much will I pay?" or a long sentence that merely contains both words. ``verb``: the
    same rule for another action ("submit", "redeploy": the helper app, chert/runner.py)."""
    if not isinstance(utterance, str) or "?" in utterance or len(utterance) > 200:
        return False
    words = _words(utterance)
    if not words or len(words) > MAX_CONSENT_WORDS:
        return False
    if any(_negated(w) for w in words):
        return False
    return verb in words and any(w in AFFIRM for w in words)


def declines(utterance: Any) -> bool:
    """The caller said no / stop / cancel / wait / don't (anywhere in what they said)."""
    return any(w in DECLINES or w.endswith("n't") for w in _words(utterance))


# --- what the caller said and when the agent was talking -----------------------------------------

class Heard:
    """Fed from AgentSession events (agent_integration wires them):
      user_input_transcribed -> on_transcript(text, is_final)  (only final, non-empty ones count)
      agent_state_changed    -> on_agent_state(new_state)      ("speaking" stretches are kept)
      user_state_changed     -> on_user_state(new_state)       (when the caller starts talking)
    Times are this process's monotonic clock, stamped on arrival."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, keep: int = 40) -> None:
        self.clock, self.keep = clock, keep
        self.text, self.at, self.seq = "", 0.0, 0
        self.agent_events = 0
        self.agent_speaking_since: Optional[float] = None
        self.agent_spans: list[tuple[float, float]] = []      # finished speaking stretches
        self.user_starts: list[float] = []
        self.listeners: list[Callable[[str], Any]] = []       # called with each final transcript

    def on_transcript(self, text: Any, is_final: bool) -> None:
        if not is_final or not isinstance(text, str) or not text.strip():
            return
        self.text, self.at = " ".join(text.split())[:500], self.clock()
        self.seq += 1
        for fn in list(self.listeners):
            try:
                fn(self.text)
            except Exception:  # noqa: BLE001 - a listener must never break the session's events
                log.exception("transcript listener failed")

    def on_agent_state(self, new_state: Any) -> None:
        now = self.clock()
        self.agent_events += 1
        if new_state == "speaking":
            if self.agent_speaking_since is None:
                self.agent_speaking_since = now
        elif self.agent_speaking_since is not None:
            self.agent_spans.append((self.agent_speaking_since, now))
            self.agent_spans = self.agent_spans[-self.keep:]
            self.agent_speaking_since = None

    def on_user_state(self, new_state: Any) -> None:
        if new_state == "speaking":
            self.user_starts.append(self.clock())
            self.user_starts = self.user_starts[-self.keep:]

    def readback_end(self, since: float, min_s: float) -> tuple[Optional[float], bool]:
        """(end of the latest finished agent speaking stretch after ``since`` that lasted at least
        ``min_s`` (the readback), whether the caller started talking during it). (None, False) if
        there is none yet, e.g. the agent is still reading it."""
        for start, end in reversed(self.agent_spans):
            if end <= since:
                break
            s = max(start, since)
            if end - s >= min_s:
                return end, any(s <= u <= end for u in self.user_starts)
        return None, False


def readback_words(text: str) -> int:
    return max(1, len(_words(text)))


def consent_check(heard: Heard, opened_at: float, readback: str, now: float,
                  window_s: float = CONSENT_WINDOW_S, verb: str = "pay") -> str:
    """"ok", or why not: "not_read" (readback not spoken yet), "talked_over" (the caller spoke
    during it), "no_answer" (no transcript after it, or too old), "no_consent" (it isn't a clear
    yes, pay)."""
    n = readback_words(readback)
    if heard.agent_events:
        end, talked_over = heard.readback_end(opened_at, n * MIN_READBACK_S_PER_WORD)
        if end is None:
            return "not_read"
        if talked_over:
            return "talked_over"
    else:   # no agent-state events in this session at all: assume it took a plausible time
        end = opened_at + n * FALLBACK_READBACK_S_PER_WORD
    if heard.seq == 0 or heard.at <= end or heard.at - end > window_s or now - heard.at > window_s:
        return "no_answer"
    return "ok" if consent_ok(heard.text, verb) else "no_consent"


# --- one call's payment intent -------------------------------------------------------------------

def hours_text(n: int) -> str:
    return f"{n} hour" if n == 1 else f"{n} hours"


def sol_text(amount: Any) -> str:
    s = f"{float(amount):.9f}".rstrip("0").rstrip(".")
    return s or "0"


def amount_label(intent: dict) -> str:
    if intent.get("method") == "virtual_card" and intent.get("amount_usd") is not None:
        return f"${float(intent['amount_usd']):.2f}"
    return f"{sol_text(intent.get('amount_sol') or 0)} SOL"


def consent_banner(intent: dict) -> str:
    """The line on our video while an intent is open."""
    parts = ["Say “yes, pay” to confirm", amount_label(intent),
             f"{int(intent.get('hours') or 0)} h"]
    if intent.get("plate"):
        parts.append(str(intent["plate"]))
    return " · ".join(parts)


METHOD_WORDS = {"card": "virtual_card", "virtual_card": "virtual_card", "virtual card": "virtual_card",
                "sol": "solana_devnet", "solana": "solana_devnet", "solana_devnet": "solana_devnet",
                "crypto": "solana_devnet", "wallet": "solana_devnet"}

# What the model says when the server refuses an intent (codes from api/voice_pay.py and /pay).
PREPARE_REFUSALS = {
    "already_paid": "This meter is already paid. Tell the caller their receipt is in the ScanSafe app.",
    "payment_in_progress": "A payment for this meter is already going through. Ask them to wait a moment.",
    "bad_hours": "Ask the caller how many hours they want, from {lo} to {hi}, then try again.",
    "over_cap": "That's more than this demo can pay. Ask them to pick fewer hours.",
}
CARD_UNAVAILABLE = ("Paying with a card isn't available right now. Tell the caller you can pay with test "
                    "SOL instead, or they can tap Pay in the ScanSafe app. If they want test SOL, call "
                    "prepare_payment again with pay_with set to sol.")
PREPARE_FAILED = ("Say you couldn't set up the payment right now, and they can tap Pay in the ScanSafe "
                  "app instead.")


class VoicePay:
    """Voice-confirmed payment for one parking meter call.

    meter: the meter dict from chert.meter_pay.meter_job (scan_id, min/max hours, ...).
    heard: the call's Heard. default_hours(): the hours the call is showing (the app's quote).
    show(text|None): put / clear the consent line on our video.
    """

    def __init__(self, meter: dict, heard: Heard, *, show: Callable[[Optional[str]], Any] = lambda t: None,
                 default_hours: Callable[[], Optional[int]] = lambda: None,
                 plate: Callable[[], Optional[str]] = lambda: None,
                 client: Optional[httpx.AsyncClient] = None,
                 clock: Callable[[], float] = time.monotonic,
                 wait_s: float = CONSENT_WAIT_S, sleep=asyncio.sleep) -> None:
        self.meter, self.heard = meter, heard
        self.scan_id = meter["scan_id"]
        self._show = show
        self.default_hours, self.plate = default_hours, plate   # callables; the call fills them in
        self._client = client
        self.clock, self.wait_s, self.sleep = clock, wait_s, sleep
        self.intent: Optional[dict] = None
        self.paid = False
        self.backend_confirms = 0       # how many times we called /confirm (tests: never without consent)
        self._tasks: set[asyncio.Task] = set()
        self._expiry: Optional[asyncio.TimerHandle] = None
        heard.listeners.append(self._on_transcript)

    @staticmethod
    def enabled() -> bool:
        """Voice payments need the shared AGENT_INTERNAL_KEY (the API refuses intents without it)."""
        return bool((os.getenv("AGENT_INTERNAL_KEY") or "").strip())

    # HTTP ------------------------------------------------------------------------------------

    async def _post(self, path: str, body: dict, timeout: float) -> tuple[int, dict]:
        key = (os.getenv("AGENT_INTERNAL_KEY") or "").strip()
        if not key:
            return 0, {"error": "agent_key_missing"}
        try:
            if self._client is None:
                self._client = httpx.AsyncClient()
            r = await self._client.post(f"{api_url()}{path}", json=body, headers={"X-Agent-Key": key},
                                        timeout=timeout)
            data = r.json()
            return r.status_code, data if isinstance(data, dict) else {}
        except (httpx.HTTPError, ValueError) as e:
            log.info("voice pay %s failed: %s", path.rsplit("/", 1)[-1], type(e).__name__)
            return 0, {"error": "unreachable"}

    async def aclose(self) -> None:
        self._drop()
        for t in list(self._tasks):
            t.cancel()
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _spawn(self, coro) -> None:
        try:
            t = asyncio.get_running_loop().create_task(coro)
        except RuntimeError:            # no loop (tests calling stop() synchronously)
            coro.close()
            return
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    # local state -----------------------------------------------------------------------------

    def _drop(self) -> Optional[dict]:
        """Forget the open intent locally and take the line off the video."""
        intent, self.intent = self.intent, None
        if self._expiry is not None:
            self._expiry.cancel()
            self._expiry = None
        if intent is not None:
            try:
                self._show(None)
            except Exception:  # noqa: BLE001
                log.exception("couldn't clear the consent line")
        return intent

    def _expire(self, intent_id: str) -> None:
        if self.intent is not None and self.intent["intent_id"] == intent_id:
            log.info("voice pay: intent expired")
            self._drop()

    def _open(self, data: dict) -> dict:
        self._drop()
        try:
            ttl = max(1.0, min(45.0, float(data.get("expires_in") or 45)) - 1.0)
        except (TypeError, ValueError):
            ttl = 44.0
        intent = {k: data.get(k) for k in ("intent_id", "readback", "method", "amount_sol", "amount_usd",
                                           "hours", "plate", "merchant")}
        intent["opened_at"] = self.clock()
        intent["expires_at"] = intent["opened_at"] + ttl
        self.intent = intent
        try:
            self._expiry = asyncio.get_running_loop().call_later(ttl, self._expire, intent["intent_id"])
        except RuntimeError:
            self._expiry = None
        self._show(consent_banner(intent))
        return intent

    def _live_intent(self) -> Optional[dict]:
        i = self.intent
        if i is not None and self.clock() >= i["expires_at"]:
            self._drop()
            return None
        return i

    # events ------------------------------------------------------------------------------------

    def _on_transcript(self, text: str) -> None:
        """A "no" / "stop" / "cancel" after the readback was offered cancels it right away."""
        i = self.intent
        if i is not None and self.heard.at > i["opened_at"] and declines(text):
            log.info("voice pay: caller declined; cancelling the intent")
            self.cancel_now()

    def on_hours_changed(self, hours: int) -> None:
        """The app changed the hours: the readback no longer matches the screen."""
        i = self.intent
        if i is not None and i.get("hours") != hours:
            log.info("voice pay: hours changed in the app; cancelling the intent")
            self.cancel_now()

    def on_paid(self) -> None:
        """Paid (in the app or by voice): nothing left to confirm."""
        self.paid = True
        self._drop()

    def cancel_now(self) -> bool:
        """Cancel the open intent: locally at once, on the server in the background."""
        intent = self._drop()
        if intent is None:
            return False
        self._spawn(self._post(f"/pay/intent/{intent['intent_id']}/cancel", {}, INTENT_TIMEOUT_S))
        return True

    # the tools' work ---------------------------------------------------------------------------

    async def prepare(self, hours: Optional[int] = None, pay_with: Optional[str] = None) -> str:
        if self.paid:
            return PREPARE_REFUSALS["already_paid"]
        lo, hi = int(self.meter.get("min_hours", 1)), int(self.meter.get("max_hours", 1))
        if hours is None:
            hours = self.default_hours()
        if isinstance(hours, bool) or not isinstance(hours, int):
            hours = None
        if hours is None or not lo <= hours <= hi:
            return PREPARE_REFUSALS["bad_hours"].format(lo=lo, hi=hi)
        body: dict[str, Any] = {"scan_id": self.scan_id, "hours": hours}
        method = METHOD_WORDS.get(str(pay_with or "").strip().lower()) if pay_with else None
        if method:
            body["method"] = method
        plate = clean_plate(self.plate())
        if plate:
            body["plate"] = plate
        self.cancel_now()                    # a new readback replaces the old one (the server does too)
        status, data = await self._post("/pay/intent", body, INTENT_TIMEOUT_S)
        if status == 400 and data.get("error") == "bad_plate" and "plate" in body:
            body.pop("plate")
            status, data = await self._post("/pay/intent", body, INTENT_TIMEOUT_S)
        if status != 200 or not data.get("intent_id") or not isinstance(data.get("readback"), str):
            code = str(data.get("error") or "")
            log.info("voice pay: intent refused (HTTP %s, %s)", status, code or "-")
            if method == "virtual_card" and status in (400, 401, 403, 409, 503) and code not in PREPARE_REFUSALS:
                return CARD_UNAVAILABLE
            if code in PREPARE_REFUSALS:
                if code == "already_paid":
                    self.paid = True
                return PREPARE_REFUSALS[code].format(lo=lo, hi=hi)
            return PREPARE_FAILED
        intent = self._open(data)
        log.info("voice pay: intent open (%s, %s h)", intent.get("method"), intent.get("hours"))
        return ("Read this to the caller slowly, word for word, and nothing else: \"" + intent["readback"] +
                "\" Then stop and wait for their answer. Only if they clearly say \"yes, pay\" after "
                "hearing it, call confirm_payment. If they say no, stop or cancel, call cancel_payment.")

    async def confirm(self) -> dict:
        """{"ok": True, "status": {...}} once paid, else {"ok": False, "say": <instruction>}.
        Calls the backend only with an open intent and a clear, timely "yes, pay"."""
        intent = self._live_intent()
        if intent is None:
            return {"ok": False, "reason": "no_intent",
                    "say": "There's no payment ready to confirm. If the caller wants to pay, call "
                           "prepare_payment and read the new line to them first."}
        deadline = self.clock() + self.wait_s
        why = consent_check(self.heard, intent["opened_at"], intent["readback"], self.clock())
        while why != "ok" and self.clock() < deadline:
            await self.sleep(0.1)           # the caller's words may still be on their way in
            if self.intent is not intent:
                return {"ok": False, "reason": "cancelled",
                        "say": "The payment was cancelled. Say: Okay, I won't pay. Then wait."}
            why = consent_check(self.heard, intent["opened_at"], intent["readback"], self.clock())
        if why != "ok":
            log.info("voice pay: no consent yet (%s); not calling the backend", why)
            if why == "not_read":
                return {"ok": False, "reason": why,
                        "say": "You haven't read the payment to the caller yet. Read it word for word "
                               f"first: \"{intent['readback']}\" Then wait for their answer."}
            if why == "talked_over":
                self.cancel_now()
                return {"ok": False, "reason": why,
                        "say": "The caller spoke while you were reading the payment, so it wasn't heard "
                               "clearly. If they still want to pay, call prepare_payment again and read "
                               "the new line word for word."}
            return {"ok": False, "reason": why,
                    "say": "Ask the caller to clearly say 'yes, pay' to confirm"}
        utterance = self.heard.text
        self._drop()                         # single use, here too: no second confirm for it
        self.backend_confirms += 1
        status, data = await self._post(f"/pay/intent/{intent['intent_id']}/confirm",
                                        {"utterance": utterance}, CONFIRM_TIMEOUT_S)
        if status == 200 and data.get("ok") is True:
            log.info("voice pay: confirmed and paid (%s)", intent.get("method"))
            return {"ok": True, "status": data.get("status") or {}, "intent": intent}
        code = str(data.get("error") or "")
        log.info("voice pay: confirm refused (HTTP %s, %s)", status, code or "-")
        if code == "already_paid":
            return {"ok": False, "reason": code,
                    "say": "This meter was already paid. Tell the caller their receipt is in the app."}
        if code in ("intent_expired", "unknown_intent", "intent_used", "too_many_tries", "no_consent"):
            return {"ok": False, "reason": code,
                    "say": "That payment offer ran out. If the caller still wants to pay, call "
                           "prepare_payment again and read the new line word for word."}
        return {"ok": False, "reason": code or "failed",
                "say": "Say: Sorry, that payment didn't go through, so nothing was paid. They can try "
                       "again, or tap Pay in the ScanSafe app."}


INSTRUCTIONS = """
This call is about paying a parking meter. The person can pick the hours and tap Pay in the
ScanSafe app, or you can pay for them by voice, but ONLY like this:
- If they ask you to pay (or add time), call prepare_payment (with the hours if they said a
  number). It gives you one exact line. Read it word for word, then stop and wait.
- Call confirm_payment ONLY after they answered that line with "yes, pay". Never call it on your
  own, never after just "yes", "okay" or "pay", and never before you read the line.
- If they say no, stop, cancel, wait or not now, call cancel_payment (for stop, the stop tool).
- If confirm_payment asks you to have them say "yes, pay", ask them that, kindly.
- Never say a payment went through unless confirm_payment said it did, or you were told to say
  "Paid". You cannot change prices; the line from prepare_payment is the only price to say.
- Remind them they can also just tap Pay in the ScanSafe app.
If you said you'd use the official Dogwood app, your video shows that app being filled in on our
computer; it still can't pay on its own: the payment needs their "yes, pay" or the Pay button.
"""
