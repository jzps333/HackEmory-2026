"""FaceTime agent, parking meter mode: follow the app while the person picks hours and pays.

/call-me sends a verified meter code (solana:...) with job metadata
  {"scansafe_outbound": true, "scan_url": "solana:...", "phone": ..., "scan_id": ...,
   "meter_url": ..., "meter": {"merchant", "rate_per_hour_sol", "min_hours", "max_hours",
                               "meter_url", "meter_id", "spoken_name"}}
The agent greets, shows the meter page live (meter_url?hours=N through the sandbox stream),
then polls the API about every 1.5 s:
  GET /pay/quote/{scan_id}   hours changed (and held for ~2 s) -> "Okay, 3 hours, 0.03 SOL." + new
                             live view (the old one is hung up first: never two at once)
  GET /pay/status/{scan_id}  state "paid" -> "Paid. 3 hours on meter 42. ..." + the Paid screen
The agent NEVER pays: only the app's Pay button (POST /pay, approved: true) does. "Stop" stops
all of it, including speech the polling would have triggered.

Linked Dogwood account (POST /operators/dogwood/app-session says linked: true): the agent says it
will use the official Dogwood app instead of the sticker, and the live view is the sandbox
operating that app (install -> open -> plate -> hours -> "Pay with linked ScanSafe account",
which only asks for approval in ScanSafe) instead of the meter page; DogwoodView below. Hours
changes before payment re-run it (straight to the app, no second install); paid -> the receipt
line and the Paid banner over the app's receipt. If the app path fails before Pay (sandbox not
deployed yet, session refused), it falls back to the meter page for the rest of the call.

No LiveKit imports here, so the logic is unit-testable: QuoteFollower is pure, and MeterPayFlow
takes its speech, video and HTTP as plain callables.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from chert.scansafe_tools import api_url

log = logging.getLogger("scansafe.meter")

POLL_S = 1.5
DEBOUNCE_S = 2.0
HTTP_TIMEOUT_S = 3.0
MAX_FLOW_S = 20 * 60        # stop polling eventually, even if nobody hangs up cleanly


# --- what we say (fixed templates; numbers come from our own server, never from a page) --------

def hours_text(n: int) -> str:
    return f"{n} hour" if n == 1 else f"{n} hours"


def sol_text(amount: float) -> str:
    """0.03 -> "0.03", 0.1 -> "0.1" (no float noise, no trailing zeros)."""
    s = f"{float(amount):.9f}".rstrip("0").rstrip(".")
    return s or "0"


def greeting(meter: dict) -> str:
    name = meter.get("spoken_name") or meter.get("merchant") or "the parking company"
    return ("Hi, this is ScanSafe. You scanned a parking meter code. "
            f"It belongs to {name}, and it's their real wallet. "
            f"It costs {sol_text(meter.get('rate_per_hour_sol', 0))} test SOL per hour.")


def hours_line(hours: int, amount: float) -> str:
    return f"Okay, {hours_text(hours)}, {sol_text(amount)} SOL."


def paid_line(hours: int, meter_id: str = "") -> str:
    where = f" on meter {meter_id}" if meter_id else ""
    return f"Paid. {hours_text(hours)}{where}. Your receipt is in the app."


LINKED_LINE = ("You've linked your Dogwood Parking account. "
               "I'll use the official Dogwood app instead of the sticker.")
APP_FALLBACK_LINE = "The Dogwood app isn't answering right now, so I'll show you the meter instead."


def linked_greeting() -> str:
    return f"Hi, this is ScanSafe. {LINKED_LINE}"


def dogwood_paid_line(hours: int, meter_id: str = "", plate: str = "") -> str:
    where = f" on meter {meter_id}" if meter_id else ""
    car = f" for plate {plate}" if plate else ""
    return f"Paid. {hours_text(hours)}{where}{car}. Your receipt is in the Dogwood app."


INSTRUCTIONS = """
This call is about paying a parking meter. The person picks the hours and pays in the ScanSafe
app. You cannot pay, change the hours, or move money. If they ask you to pay or add time, tell
them to pick the hours in the app and tap Pay there. Never say a payment went through unless you
were told to say "Paid". If you said you'd use the official Dogwood app, your video shows that
app being filled in on our computer; it still can't pay: they approve the payment in ScanSafe.
"""


# --- job metadata and URLs ---------------------------------------------------------------------

def meter_job(job: Optional[dict]) -> Optional[dict]:
    """The meter dict (plus scan_id, scan_url) from an outbound job, or None if this call isn't a
    parking meter payment."""
    if not isinstance(job, dict):
        return None
    meter, scan_id, code = job.get("meter"), job.get("scan_id"), job.get("scan_url")
    if not (isinstance(meter, dict) and isinstance(scan_id, str) and scan_id
            and isinstance(code, str) and code.startswith("solana:")):
        return None
    url = job.get("meter_url") or meter.get("meter_url")
    if not isinstance(url, str) or not url.startswith("https://"):
        return None
    try:
        lo, hi = int(meter.get("min_hours", 1)), int(meter.get("max_hours", 1))
        rate = float(meter.get("rate_per_hour_sol", 0))
    except (TypeError, ValueError):
        return None
    return {**meter, "meter_url": url, "min_hours": lo, "max_hours": hi,
            "rate_per_hour_sol": rate, "scan_id": scan_id, "scan_url": code}


def meter_view_url(meter_url: str, hours: int) -> str:
    """meter_url with ?hours=N set (other query parameters kept)."""
    p = urlparse(meter_url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k != "hours"]
    q.append(("hours", str(int(hours))))
    return urlunparse(p._replace(query=urlencode(q)))


def install_url_for(app_url: str) -> str:
    """The Dogwood install page for this session (first run: Install, then Open).
    /dogwood/app?s=T -> /dogwood/install?s=T; anything else is returned unchanged."""
    p = urlparse(app_url)
    if p.path.rstrip("/") == "/dogwood/app":
        return urlunparse(p._replace(path="/dogwood/install"))
    return app_url


def app_page_url(app_url: str) -> str:
    """The Dogwood app page itself (re-runs after an hours change: already installed).
    /dogwood/install?s=T -> /dogwood/app?s=T; anything else is returned unchanged."""
    p = urlparse(app_url)
    if p.path.rstrip("/") == "/dogwood/install":
        return urlunparse(p._replace(path="/dogwood/app"))
    return app_url


def amount_for(meter: dict, hours: int) -> float:
    """Same math as the server (whole lamports), only for what we say before a quote arrives."""
    lamports = round(float(meter.get("rate_per_hour_sol", 0)) * 1_000_000_000)
    return lamports * hours / 1_000_000_000


def quote_hours(quote: Optional[dict], meter: dict) -> Optional[int]:
    """The hours in a quote, if it is a sane whole number within the meter's limits."""
    if not isinstance(quote, dict):
        return None
    h = quote.get("hours")
    if isinstance(h, bool) or not isinstance(h, int):
        return None
    return h if meter["min_hours"] <= h <= meter["max_hours"] else None


# --- the pure part: when to speak and re-render ------------------------------------------------

class QuoteFollower:
    """Decides, from the polled quote hours and payment status, what the agent does next.

    observe(hours, now) after every quote poll; due(now) -> hours to announce and show now
    (once they have held for ``debounce_s``), else None; on_status(status) -> the status dict
    the first time it says "paid", else None. After stop() or paid, nothing more happens.
    """

    def __init__(self, shown_hours: int, debounce_s: float = DEBOUNCE_S) -> None:
        self.shown = shown_hours           # what the live view shows / we last said
        self.debounce_s = debounce_s
        self.pending: Optional[int] = None
        self.pending_since = 0.0
        self.paid = False
        self.stopped = False

    @property
    def done(self) -> bool:
        return self.paid or self.stopped

    def observe(self, hours: Optional[int], now: float) -> None:
        if self.done or hours is None:
            return
        if hours == self.shown:
            self.pending = None             # changed back before it settled: nothing to say
        elif hours != self.pending:
            self.pending, self.pending_since = hours, now

    def due(self, now: float) -> Optional[int]:
        if self.done or self.pending is None or now - self.pending_since < self.debounce_s:
            return None
        self.shown, self.pending = self.pending, None
        return self.shown

    def on_status(self, status: Optional[dict]) -> Optional[dict]:
        if self.done or not isinstance(status, dict) or status.get("state") != "paid":
            return None
        self.paid, self.pending = True, None
        return status

    def stop(self) -> None:
        self.stopped, self.pending = True, None


# --- the async part ----------------------------------------------------------------------------

Fetch = Callable[[str], Awaitable[Optional[dict]]]


class MeterPayFlow:
    """Runs the meter walkthrough for one call.

    say(text):                     speak one line (ScanSafeCall.say: one at a time)
    show_live(url, hours, amount): run one live view of the meter page; must hang up its stream
                                   and return/raise only once it is really over when cancelled
    show_paid(hours, amount):      put the Paid screen on the video
    fetch_quote/fetch_status(id):  GET /pay/quote/{id} and /pay/status/{id} -> dict or None
    """

    def __init__(self, meter: dict, *, say: Callable[[str], Awaitable[Any]],
                 show_live: Callable[[str, int, float], Awaitable[Any]],
                 show_paid: Callable[[int, float], Any],
                 fetch_quote: Optional[Fetch] = None, fetch_status: Optional[Fetch] = None,
                 alive: Callable[[], bool] = lambda: True,
                 poll_s: float = POLL_S, debounce_s: float = DEBOUNCE_S,
                 max_s: float = MAX_FLOW_S, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
                 view_url: Optional[Callable[[int], str]] = None,
                 paid_text: Optional[Callable[[int], str]] = None,
                 paid_grace_s: float = 0.0) -> None:
        """view_url(hours): what the live view opens (default: the meter page with ?hours=N).
        paid_text(hours): the line said once paid (default: paid_line).
        paid_grace_s: once paid, let the live view finish by itself for up to this long (the
        Dogwood app shows its receipt), then hang it up."""
        self.meter = meter
        self.scan_id = meter["scan_id"]
        self._say, self._show_live, self._show_paid = say, show_live, show_paid
        self._view_url = view_url or (lambda h: meter_view_url(self.meter["meter_url"], h))
        self._paid_text = paid_text or (lambda h: paid_line(h, str(self.meter.get("meter_id") or "")))
        self.paid_grace_s = paid_grace_s
        self._fetch_quote = fetch_quote or self._get("/pay/quote/")
        self._fetch_status = fetch_status or self._get("/pay/status/")
        self.alive, self.poll_s, self.max_s = alive, poll_s, max_s
        self.clock, self.sleep = clock, sleep
        self.follower = QuoteFollower(meter["min_hours"], debounce_s)
        self.stopped = False
        self._live: Optional[asyncio.Task] = None
        self._live_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self._client: Optional[httpx.AsyncClient] = None

    # HTTP ------------------------------------------------------------------------------------

    def _get(self, prefix: str) -> Fetch:
        async def fetch(scan_id: str) -> Optional[dict]:
            try:
                if self._client is None:
                    self._client = httpx.AsyncClient(timeout=HTTP_TIMEOUT_S)
                r = await self._client.get(f"{api_url()}{prefix}{scan_id}")
                if r.status_code != 200:
                    return None
                data = r.json()
                return data if isinstance(data, dict) else None
            except (httpx.HTTPError, ValueError):
                return None
        return fetch

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # pieces ----------------------------------------------------------------------------------

    async def initial_hours(self) -> int:
        """Hours the app has picked so far (its latest quote), else the meter's minimum."""
        h = quote_hours(await self._fetch_quote(self.scan_id), self.meter)
        if h is not None:
            self.follower.shown = h
        return self.follower.shown

    def _spawn(self, coro) -> Optional[asyncio.Task]:
        if self.stopped:
            coro.close()
            return None
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return t

    async def say(self, text: str) -> None:
        if not self.stopped:
            await self._say(text)

    async def _cancel_live(self) -> None:
        """Hang up the current live view and wait until its stream is really closed."""
        t, self._live = self._live, None
        if t is not None and not t.done():
            t.cancel()
            try:
                await t
            except BaseException:   # noqa: BLE001 - its CancelledError (or error) is expected
                pass

    async def render(self, hours: int) -> None:
        """Show the meter page for ``hours`` live, replacing any live view still running."""
        async with self._live_lock:
            await self._cancel_live()
            if self.stopped or self.follower.paid:
                return
            url = self._view_url(hours)
            self._live = asyncio.create_task(self._show_live(url, hours, amount_for(self.meter, hours)))

    async def _paid(self, status: dict) -> None:
        try:
            hours = int(status.get("hours") or self.follower.shown)
        except (TypeError, ValueError):
            hours = self.follower.shown
        try:
            amount = float(status.get("amount_sol"))
        except (TypeError, ValueError):
            amount = amount_for(self.meter, hours)
        async with self._live_lock:
            t = self._live
            if self.paid_grace_s > 0 and t is not None and not t.done() and not self.stopped:
                # wait() never raises for the view's own outcome and doesn't cancel it on timeout
                await asyncio.wait({t}, timeout=self.paid_grace_s)
            await self._cancel_live()
        if self.stopped:
            return
        self._show_paid(hours, amount)
        await self.say(self._paid_text(hours))

    # main loop -------------------------------------------------------------------------------

    async def run(self) -> None:
        """Poll until paid, stopped, the call is gone, or MAX_FLOW_S passes."""
        started = self.clock()
        try:
            while not self.stopped and self.alive() and self.clock() - started < self.max_s:
                f = self.follower
                f.observe(quote_hours(await self._fetch_quote(self.scan_id), self.meter), self.clock())
                n = f.due(self.clock())
                if n is not None and not self.stopped:
                    log.info("meter: hours changed to %d", n)
                    self._spawn(self.render(n))
                    self._spawn(self.say(hours_line(n, amount_for(self.meter, n))))
                status = f.on_status(await self._fetch_status(self.scan_id)) if not self.stopped else None
                if status is not None:
                    log.info("meter: paid")
                    await self._paid(status)
                    return
                wait = self.poll_s
                if f.pending is not None:   # wake up when the new hours will have settled
                    wait = max(0.05, min(wait, f.pending_since + f.debounce_s - self.clock()))
                await self.sleep(wait)
        finally:
            await self.aclose()

    def stop(self) -> None:
        """The caller said stop: no more polling, speech, or live views."""
        self.stopped = True
        self.follower.stop()
        for t in list(self._tasks):
            t.cancel()
        if self._live is not None:
            self._live.cancel()


# --- linked Dogwood account: operate the official app instead of showing the sticker -----------

OperateLive = Callable[[str, str, int, float, Callable[[str, str], Any]], Awaitable[Optional[dict]]]


class DogwoodView:
    """The live view for MeterPayFlow when the person linked their Dogwood Parking account.

    session: {"app_url", "plate"} from POST /operators/dogwood/app-session (our server).
    operate_live(url, plate, hours, amount, on_step) runs one sandbox /operate stream on the video
    and returns its result (None if cancelled); meter_live(url, hours, amount) is today's meter
    view, used as the fallback. Pass view_url / show to MeterPayFlow, and paid_text for the line.

    First run opens the install page (Install, Open, ...); once a run has opened the app, later
    runs (hours changed before payment) go straight to the app page. If a run fails before it
    tapped Pay, the rest of the call uses the meter page instead, said once out loud.
    """

    def __init__(self, session: dict, meter: dict, *, operate_live: OperateLive,
                 meter_live: Callable[[str, int, float], Awaitable[Any]],
                 say: Callable[[str], Awaitable[Any]]) -> None:
        self.app_url, self.plate = session["app_url"], session["plate"]
        self.meter = meter
        self._operate_live, self._meter_live, self._say = operate_live, meter_live, say
        self.installed = False
        self.fallen_back = False
        self.runs = 0

    def view_url(self, hours: int) -> str:
        if self.fallen_back:
            return meter_view_url(self.meter["meter_url"], hours)
        return app_page_url(self.app_url) if self.installed else install_url_for(self.app_url)

    def _on_step(self, _text: str, step: str) -> None:
        if step in ("open_app", "plate", "hours", "pay", "wait", "paid"):
            self.installed = True

    async def show(self, url: str, hours: int, amount: float) -> Optional[dict]:
        if self.fallen_back or url.startswith(self.meter["meter_url"]):
            return await self._meter_live(url, hours, amount)
        self.runs += 1
        result = await self._operate_live(url, self.plate, hours, amount, self._on_step)
        if not isinstance(result, dict):
            return result                       # cancelled (hours changed, paid, or stop)
        steps = result.get("steps") or []
        if "open_app" in steps or "plate" in steps:
            self.installed = True
        if result.get("status") == "failed" and "pay" not in steps:
            log.info("dogwood app failed before Pay (%s); meter page from now on",
                     str(result.get("error") or "")[:120])
            self.fallen_back = True
            await self._say(APP_FALLBACK_LINE)
            return await self._meter_live(meter_view_url(self.meter["meter_url"], hours), hours, amount)
        return result

    def paid_text(self, hours: int) -> str:
        meter_id = str(self.meter.get("meter_id") or "")
        if self.fallen_back:
            return paid_line(hours, meter_id)
        return dogwood_paid_line(hours, meter_id, self.plate)
