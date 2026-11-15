"""FaceTime agent + linked Dogwood account: app-session client, sandbox /operate stream client,
DogwoodView (install once, re-run on hours changes, fall back to the meter page), the meter call
wiring, and the live header. Offline: the backend and the sandbox are httpx MockTransports or
plain fakes; LiveKit is stubbed when it isn't installed."""
import asyncio
import base64
import io
import json
import sys
import threading
import time
import types

import httpx
import pytest
from PIL import Image

try:
    import livekit.rtc  # noqa: F401
    import livekit.agents  # noqa: F401
except ImportError:   # same stub as test_live_stream.py / test_meter_pay.py
    _lk = types.ModuleType("livekit")
    _rtc = types.ModuleType("livekit.rtc")
    _agents = types.ModuleType("livekit.agents")

    class _Any:
        def __init__(self, *a, **k):
            pass

        def __getattr__(self, _name):
            return _Any()

        def __call__(self, *a, **k):
            return a[0] if len(a) == 1 and callable(a[0]) and not k else _Any()

    _rtc.__getattr__ = lambda name: _Any
    for name in ("Agent", "AgentServer", "AgentSession", "JobContext", "RunContext", "cli",
                 "room_io"):
        setattr(_agents, name, _Any)
    _agents.function_tool = lambda f: f
    _agents.AgentServer = type("AgentServer", (), {"__init__": lambda self, *a, **k: None,
                                                  "rtc_session": lambda self, **k: (lambda f: f)})
    _lk.rtc, _lk.agents = _rtc, _agents
    sys.modules.update({"livekit": _lk, "livekit.rtc": _rtc, "livekit.agents": _agents})

from chert import meter_pay as mp  # noqa: E402
from chert import scansafe_tools as tools  # noqa: E402
from chert import status_video  # noqa: E402
from chert.status_video import StatusVideo  # noqa: E402

SITE = "https://scansafe-demo-sites.vercel.app"
APP_URL = f"{SITE}/dogwood/app?s=tok_abc123456"
INSTALL_URL = f"{SITE}/dogwood/install?s=tok_abc123456"
METER_URL = f"{SITE}/fixtures/meter/index.html"
METER = {"merchant": "Dogwood Lot & Meter Co.", "rate_per_hour_sol": 0.01, "min_hours": 1,
         "max_hours": 4, "meter_url": METER_URL, "meter_id": "42",
         "spoken_name": "Dogwood Lot and Meter", "scan_id": "abc123abc123", "scan_url": "solana:x"}
SESSION = {"app_url": APP_URL, "plate": "GA 4821K", "linked": True}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SCANSAFE_API_URL", "http://scansafe.test")
    monkeypatch.setenv("AGENT_INTERNAL_KEY", "agent-key-test")
    monkeypatch.setenv("SANDBOX_URL", "http://sandbox.test:8080/")
    monkeypatch.setenv("SANDBOX_TOKEN", "sandbox-token-test")


def jpeg(color=(10, 120, 200), size=(390, 844)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG", quality=90)
    return buf.getvalue()


def data_uri(color) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg(color)).decode()


# --- app-session client --------------------------------------------------------------------------

def session_client(status=200, body=None, seen=None, exc=None):
    def handler(req: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(req)
        if exc:
            raise exc
        return httpx.Response(status, json=body if body is not None else {})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_app_session_linked():
    seen = []
    c = session_client(body={"app_url": APP_URL, "plate": "ga 4821k", "linked": True}, seen=seen)
    assert tools.dogwood_app_session("abc123", client=c) == {"app_url": APP_URL, "plate": "GA 4821K", "linked": True}
    req = seen[0]
    assert str(req.url) == "http://scansafe.test/operators/dogwood/app-session"
    assert req.method == "POST" and json.loads(req.content) == {"scan_id": "abc123"}
    assert req.headers["X-Agent-Key"] == "agent-key-test"


@pytest.mark.parametrize("status,body", [
    (200, {"app_url": APP_URL, "plate": "GA1", "linked": False}),                 # not linked
    (200, {"app_url": APP_URL, "plate": "GA1"}),
    (200, {"app_url": "https://evil.com/dogwood/app?s=x", "plate": "GA1", "linked": True}),
    (200, {"app_url": f"{SITE}/websites/scams/unpaid-toll", "plate": "GA1", "linked": True}),
    (200, {"app_url": f"http://scansafe-demo-sites.vercel.app/dogwood/app", "plate": "GA1", "linked": True}),
    (200, {"app_url": APP_URL, "plate": "<script>", "linked": True}),
    (200, {"app_url": APP_URL, "plate": "", "linked": True}),
    (200, ["not", "a", "dict"]),
    (401, {"detail": "bad agent key"}), (404, {"detail": "Not Found"}), (500, {}),
])
def test_app_session_not_usable_means_meter_flow(status, body):
    assert tools.dogwood_app_session("abc123", client=session_client(status, body)) is None


def test_app_session_errors_and_missing_key(monkeypatch):
    assert tools.dogwood_app_session("abc", client=session_client(exc=httpx.ConnectTimeout("slow"))) is None
    assert tools.dogwood_app_session("abc", client=session_client(exc=httpx.ConnectError("down"))) is None
    bad_json = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"<html>")))
    assert tools.dogwood_app_session("abc", client=bad_json) is None
    assert tools.dogwood_app_session("", client=session_client(body=SESSION)) is None
    monkeypatch.delenv("AGENT_INTERNAL_KEY")
    seen = []
    assert tools.dogwood_app_session("abc", client=session_client(body=SESSION, seen=seen)) is None
    assert seen == []                                 # no key: never even asks


def test_dogwood_url_check():
    assert tools.dogwood_url_ok(APP_URL) and tools.dogwood_url_ok(INSTALL_URL)
    for bad in ("https://scansafe-demo-sites.vercel.app.evil.com/dogwood/app", f"{SITE}/dogwood",
                f"{SITE}:443/dogwood/app", f"{SITE}/dogwood/../websites", f"{SITE}/dogwood/%2e%2e/x",
                "https://u:p@scansafe-demo-sites.vercel.app/dogwood/app", None, 7, ""):
        assert not tools.dogwood_url_ok(bad), bad


# --- operate stream client -----------------------------------------------------------------------

def ndjson(*msgs) -> bytes:
    return b"".join(json.dumps(m).encode() + b"\n" for m in msgs)


def sandbox_client(content=b"", status=200, seen=None):
    def handler(req: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(req)
        return httpx.Response(status, content=content,
                              headers={"content-type": "application/x-ndjson" if status == 200 else "application/json"})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_operate_stream_frames_steps_and_result():
    seen, frames, navs, steps = [], [], [], []
    result = {"mode": "operate", "status": "paid", "paid": True, "steps": ["open", "install", "pay", "paid"]}
    body = ndjson({"type": "step", "text": "Opening Dogwood Parking", "step": "open"},
                  {"type": "nav", "url": INSTALL_URL},
                  {"type": "frame", "jpeg": base64.b64encode(b"jpegbytes").decode(), "t_ms": 5},
                  {"type": "frame", "jpeg": "!!!notbase64", "t_ms": 6},
                  {"type": "step", "text": "Tapping Install", "step": "install"},
                  {"type": "result", "data": result})
    out = tools.operate_stream(INSTALL_URL, "GA 4821K", 3, frames.append, on_nav=navs.append,
                               on_step=lambda t, s: steps.append((t, s)), client=sandbox_client(body, seen=seen))
    assert out == result
    assert frames[0] == b"jpegbytes" and navs == [INSTALL_URL]
    assert steps == [("Opening Dogwood Parking", "open"), ("Tapping Install", "install")]
    req = seen[0]
    assert str(req.url) == "http://sandbox.test:8080/operate/stream"
    assert req.headers["Authorization"] == "Bearer sandbox-token-test"
    assert json.loads(req.content) == {"url": INSTALL_URL, "plate": "GA 4821K", "hours": 3}


@pytest.mark.parametrize("content,status,why", [
    (b'{"detail":"Not Found"}', 404, "HTTP 404: Not Found"),                     # sandbox not redeployed yet
    (b'{"detail":"url not allowed: only https"}', 400, "HTTP 400: url not allowed"),
    (ndjson({"type": "error", "detail": "operate timed out"}), 200, "operate timed out"),
    (ndjson({"type": "step", "text": "x", "step": "open"}), 200, "stream ended without a result"),
    (ndjson({"type": "result", "data": {"verdict": "safe"}}), 200, "unexpected result shape"),
    (b"not json\n", 200, "JSONDecodeError"),
])
def test_operate_stream_failures_never_raise(content, status, why):
    out = tools.operate_stream(APP_URL, "GA1", 2, lambda j: None, client=sandbox_client(content, status))
    assert out["status"] == "failed" and not out["paid"] and why in out["error"]


def test_operate_stream_stop_and_unconfigured(monkeypatch):
    body = ndjson(*[{"type": "frame", "jpeg": base64.b64encode(b"x").decode()}] * 5,
                  {"type": "result", "data": {"status": "paid"}})
    got = []
    out = tools.operate_stream(APP_URL, "GA1", 2, got.append, should_stop=lambda: len(got) >= 2,
                               client=sandbox_client(body))
    assert out is None and len(got) == 2                 # hung up, nothing returned
    monkeypatch.delenv("SANDBOX_TOKEN")
    seen = []
    out = tools.operate_stream(APP_URL, "GA1", 2, got.append, client=sandbox_client(body, seen=seen))
    assert out["status"] == "failed" and out["error"] == "sandbox not configured" and seen == []


# --- lines and URLs ------------------------------------------------------------------------------

def test_dogwood_lines_and_urls():
    assert mp.linked_greeting() == ("Hi, this is ScanSafe. You've linked your Dogwood Parking account. "
                                    "I'll use the official Dogwood app instead of the sticker.")
    assert mp.dogwood_paid_line(3, "42", "GA 4821K") == (
        "Paid. 3 hours on meter 42 for plate GA 4821K. Your receipt is in the Dogwood app.")
    assert mp.dogwood_paid_line(1) == "Paid. 1 hour. Your receipt is in the Dogwood app."
    assert mp.install_url_for(APP_URL) == INSTALL_URL and mp.install_url_for(INSTALL_URL) == INSTALL_URL
    assert mp.app_page_url(INSTALL_URL) == APP_URL and mp.app_page_url(APP_URL) == APP_URL
    assert mp.install_url_for(f"{SITE}/dogwood/app/?s=x") == f"{SITE}/dogwood/install?s=x"


# --- DogwoodView + MeterPayFlow ------------------------------------------------------------------

class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    async def sleep(self, s):
        for _ in range(10):
            await asyncio.sleep(0)
        self.t += s


def make_dogwood_flow(quotes, statuses, *, operate=None, grace=2.0):
    """A MeterPayFlow wired like run_meter_call does for a linked account. operate(url, hours,
    rec, clock) -> coroutine for each run; default: the app runs until the payment lands."""
    clock = FakeClock()
    rec = {"said": [], "op": [], "meter": [], "paid": [], "active": 0, "max_active": 0, "cancelled": 0}
    paid_evt = asyncio.Event()

    async def say(text):
        rec["said"].append(text)

    async def operate_live(url, plate, hours, amount, on_step):
        rec["active"] += 1
        rec["max_active"] = max(rec["max_active"], rec["active"])
        rec["op"].append((url, plate, hours, amount))
        try:
            if operate:
                return await operate(url, hours, on_step)
            on_step("Tapping Install", "install")
            on_step("Opening the app", "open_app")
            await paid_evt.wait()
            return {"mode": "operate", "status": "paid", "paid": True, "steps": ["open", "open_app", "pay", "paid"]}
        except asyncio.CancelledError:
            rec["cancelled"] += 1
            raise
        finally:
            rec["active"] -= 1

    async def meter_live(url, hours, amount):
        rec["meter"].append((url, hours))
        await asyncio.Event().wait()

    async def fetch_quote(_sid):
        return quotes(clock.t)

    async def fetch_status(_sid):
        s = statuses(clock.t)
        if s and s.get("state") == "paid":
            paid_evt.set()
        return s

    view = mp.DogwoodView(SESSION, METER, operate_live=operate_live, meter_live=meter_live, say=say)
    flow = mp.MeterPayFlow(METER, say=say, show_live=view.show, show_paid=lambda h, a: rec["paid"].append((h, a)),
                           fetch_quote=fetch_quote, fetch_status=fetch_status, clock=clock, sleep=clock.sleep,
                           max_s=60, view_url=view.view_url, paid_text=view.paid_text, paid_grace_s=grace)
    return flow, view, rec


async def start(flow):
    await flow.render(await flow.initial_hours())
    await flow.run()


def test_installs_once_reruns_on_hours_change_then_paid():
    flow, view, rec = make_dogwood_flow(
        lambda t: {"hours": 1} if t < 3 else {"hours": 3},
        lambda t: {"state": "paid", "hours": 3, "amount_sol": 0.03} if t >= 10 else {"state": "none"})
    asyncio.run(start(flow))
    assert [(u, h) for u, _, h, _ in rec["op"]] == [(INSTALL_URL, 1), (APP_URL, 3)]   # no second install
    assert all(p == "GA 4821K" for _, p, _, _ in rec["op"])
    assert rec["max_active"] == 1 and rec["cancelled"] == 1     # the 1-hour run was hung up first
    assert rec["said"] == ["Okay, 3 hours, 0.03 SOL.",
                           "Paid. 3 hours on meter 42 for plate GA 4821K. Your receipt is in the Dogwood app."]
    assert rec["paid"] == [(3, 0.03)] and rec["meter"] == []
    assert rec["cancelled"] == 1                                # the paid run finished by itself (grace)


def test_no_rerun_when_hours_never_change():
    flow, view, rec = make_dogwood_flow(lambda t: {"hours": 2},
                                        lambda t: {"state": "paid", "hours": 2, "amount_sol": 0.02} if t > 5 else None)
    asyncio.run(start(flow))
    assert [(u, h) for u, _, h, _ in rec["op"]] == [(INSTALL_URL, 2)]
    assert rec["said"] == ["Paid. 2 hours on meter 42 for plate GA 4821K. Your receipt is in the Dogwood app."]


def test_app_failure_before_pay_falls_back_to_the_meter_page():
    async def broken(url, hours, on_step):
        return {"mode": "operate", "status": "failed", "steps": [], "error": "HTTP 404: Not Found"}

    flow, view, rec = make_dogwood_flow(lambda t: {"hours": 1} if t < 3 else {"hours": 2},
                                        lambda t: {"state": "paid", "hours": 2, "amount_sol": 0.02} if t > 9 else None,
                                        operate=broken, grace=0.0)
    asyncio.run(start(flow))
    assert len(rec["op"]) == 1 and view.fallen_back
    assert [h for _, h in rec["meter"]] == [1, 2]                   # the meter page, following hours
    assert rec["meter"][0][0] == METER_URL + "?hours=1"
    assert rec["said"] == [mp.APP_FALLBACK_LINE, "Okay, 2 hours, 0.02 SOL.",
                           "Paid. 2 hours on meter 42. Your receipt is in the app."]


def test_failure_after_pay_keeps_the_app():
    async def timed_out(url, hours, on_step):
        return {"mode": "operate", "status": "waiting", "steps": ["open", "plate", "hours", "pay"], "error": None}

    flow, view, rec = make_dogwood_flow(lambda t: {"hours": 1},
                                        lambda t: {"state": "paid", "hours": 1, "amount_sol": 0.01} if t > 6 else None,
                                        operate=timed_out, grace=0.0)
    asyncio.run(start(flow))
    assert not view.fallen_back and rec["meter"] == [] and view.installed
    assert rec["said"] == ["Paid. 1 hour on meter 42 for plate GA 4821K. Your receipt is in the Dogwood app."]


def test_stop_hangs_up_the_app_and_says_nothing():
    holder = {}

    def quotes(t):
        if t >= 2 and not holder["flow"].stopped:
            holder["flow"].stop()                                  # the caller said "stop"
        return {"hours": 1 if t < 1 else 4}

    flow, view, rec = make_dogwood_flow(quotes, lambda t: None)
    holder["flow"] = flow
    asyncio.run(start(flow))
    assert rec["said"] == [] and rec["paid"] == [] and rec["active"] == 0
    assert [h for _, _, h, _ in rec["op"]] == [1]


# --- run_meter_call wiring -----------------------------------------------------------------------

def make_video() -> StatusVideo:
    v = StatusVideo.__new__(StatusVideo)
    v.state = "idle"
    v.shot = v.thumb = None
    v.code = v.code_host = ""
    v.result = None
    v.check_started = v.replay_started = 0.0
    v.live, v.live_seq, v.live_host = None, 0, ""
    v._task = None
    v._f = status_video._fonts()
    return v


def agent(monkeypatch):
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    from chert import agent_integration as ai
    return ai


def fake_call(ai, rec):
    call = ai.ScanSafeCall.__new__(ai.ScanSafeCall)
    call.video = make_video()
    call.ignore_codes = set()
    call.greeted = asyncio.Event()
    call.meter_flow = None
    call.generation = 0

    async def say(text):
        rec["said"].append(text)

    async def meter_live(url, hours, amount):
        rec["meter"].append((url, hours))

    async def dogwood_live(url, plate, hours, amount, on_step=None):
        rec["op"].append((url, plate, hours))
        return {"mode": "operate", "status": "waiting", "steps": ["open", "open_app", "pay"]}

    call.say, call.meter_live, call.dogwood_live = say, meter_live, dogwood_live
    return call


def patch_flow(monkeypatch, ai, status_at=3.0, hours=2):
    """MeterPayFlow with fake /pay/quote and /pay/status and a fake clock (no HTTP)."""
    real = mp.MeterPayFlow
    clock = FakeClock()

    async def quote(_sid):
        return {"hours": hours}

    async def status(_sid):
        return {"state": "paid", "hours": hours, "amount_sol": hours / 100} if clock.t >= status_at else None

    def make(meter, **kw):
        kw.update(fetch_quote=quote, fetch_status=status, clock=clock, sleep=clock.sleep, max_s=30)
        return real(meter, **kw)
    monkeypatch.setattr(ai.meter_pay, "MeterPayFlow", make)


def room():
    return types.SimpleNamespace(isconnected=lambda: True)


def test_run_meter_call_linked_uses_the_official_app(monkeypatch):
    ai = agent(monkeypatch)
    patch_flow(monkeypatch, ai)
    rec = {"said": [], "meter": [], "op": []}
    call = fake_call(ai, rec)

    async def go():
        async def session():
            return dict(SESSION)
        await ai.run_meter_call(call, METER, room(), asyncio.create_task(session()))

    asyncio.run(go())
    assert rec["said"][0] == mp.linked_greeting()                 # the first thing said
    assert rec["op"][0] == (INSTALL_URL, "GA 4821K", 2) and rec["meter"] == []
    assert rec["said"][-1] == "Paid. 2 hours on meter 42 for plate GA 4821K. Your receipt is in the Dogwood app."
    assert call.video.state == "paid" and call.greeted.is_set()


@pytest.mark.parametrize("kind", ["none", "raises", "slow", "no_task"])
def test_run_meter_call_falls_back_to_the_sticker_flow(monkeypatch, kind):
    ai = agent(monkeypatch)
    patch_flow(monkeypatch, ai)
    monkeypatch.setattr(ai, "DOGWOOD_SESSION_WAIT_S", 0.05)
    rec = {"said": [], "meter": [], "op": []}
    call = fake_call(ai, rec)

    async def session():
        if kind == "raises":
            raise RuntimeError("boom")
        if kind == "slow":
            await asyncio.sleep(5)
        return None

    async def go():
        task = None if kind == "no_task" else asyncio.create_task(session())
        await ai.run_meter_call(call, METER, room(), task)

    asyncio.run(go())
    assert rec["said"][0] == mp.greeting(METER)
    assert rec["op"] == [] and rec["meter"][0] == (METER_URL + "?hours=2", 2)
    assert rec["said"][-1] == "Paid. 2 hours on meter 42. Your receipt is in the app."


def test_fetch_dogwood_session_needs_the_sandbox(monkeypatch):
    ai = agent(monkeypatch)
    monkeypatch.setattr(ai, "dogwood_app_session", lambda scan_id: dict(SESSION, scan=scan_id))
    assert asyncio.run(ai.fetch_dogwood_session(METER))["scan"] == "abc123abc123"
    monkeypatch.delenv("SANDBOX_URL")
    assert asyncio.run(ai.fetch_dogwood_session(METER)) is None


# --- ScanSafeCall.dogwood_live on the video -------------------------------------------------------

def real_call(monkeypatch, fake_stream):
    ai = agent(monkeypatch)
    monkeypatch.setattr(ai, "operate_stream", fake_stream)
    call = ai.ScanSafeCall.__new__(ai.ScanSafeCall)
    call.session = types.SimpleNamespace(interrupt=lambda: None)
    call.video = make_video()
    call.video.meter_label = "Meter 42 · Dogwood Lot & Meter Co."
    call._inflight, call._results = {}, {}
    call.generation = 0
    call.meter_flow = None
    return call


def test_dogwood_live_streams_steps_then_receipt_under_paid(monkeypatch):
    steps_seen = []

    def fake(url, plate, hours, on_frame, on_nav=None, on_step=None, should_stop=None):
        assert (url, plate, hours) == (INSTALL_URL, "GA 4821K", 3)
        on_frame(jpeg())
        on_nav(APP_URL)
        on_step("Typing your plate GA 4821K", "plate")
        return {"mode": "operate", "status": "paid", "steps": ["open", "plate", "pay", "paid"],
                "screenshots": [data_uri((250, 250, 250))]}

    call = real_call(monkeypatch, fake)
    out = asyncio.run(call.dogwood_live(INSTALL_URL, "GA 4821K", 3, 0.03,
                                        on_step=lambda t, s: steps_seen.append(s)))
    assert out["status"] == "paid" and steps_seen == ["plate"]
    v = call.video
    assert v.state == "meter" and v.meter["hours"] == 3 and v.shot is not None
    assert v.live_step == "Typing your plate GA 4821K"
    v.set_paid(3, 0.03)
    assert v.state == "paid" and v.shot is not None               # Paid over the app's receipt


def test_dogwood_live_cancel_waits_for_the_stream_to_hang_up(monkeypatch):
    hung_up = threading.Event()

    def fake(url, plate, hours, on_frame, on_nav=None, on_step=None, should_stop=None):
        on_frame(jpeg())
        on_step("Tapping Install", "install")
        deadline = time.monotonic() + 5
        while not should_stop() and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.05)
        hung_up.set()
        return None

    call = real_call(monkeypatch, fake)

    async def go():
        task = asyncio.create_task(call.dogwood_live(INSTALL_URL, "GA1", 1, 0.01))
        for _ in range(300):
            if call.video.live is not None and call.video.live_step:
                break
            await asyncio.sleep(0.01)
        assert call.video.live is not None and call.video.live_step == "Tapping Install"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert hung_up.is_set()

    asyncio.run(go())


def test_stop_bumps_generation_so_the_operate_stream_hangs_up(monkeypatch):
    stopped = threading.Event()

    def fake(url, plate, hours, on_frame, on_nav=None, on_step=None, should_stop=None):
        deadline = time.monotonic() + 5
        while not should_stop() and time.monotonic() < deadline:
            time.sleep(0.01)
        stopped.set()
        return None

    call = real_call(monkeypatch, fake)

    async def go():
        task = asyncio.create_task(call.dogwood_live(APP_URL, "GA1", 2, 0.02))
        await asyncio.sleep(0.05)
        call.stop()
        assert await task is None

    asyncio.run(go())
    assert stopped.is_set() and call.video.state == "idle"


def test_live_header_shows_the_step():
    v = make_video()
    v.meter_label = "Meter 42 · Dogwood Lot & Meter Co."
    v.begin_meter_view(INSTALL_URL, 2, 0.02)
    v.set_live_frame(jpeg())
    now = time.monotonic()
    k1, f1 = v._frame_key(now), v._render(now)
    v.note_step("Tapping Install")
    k2, f2 = v._frame_key(now), v._render(now)
    assert k1 != k2 and f1 != f2 and len(f2) == v.W * v.H * 4
    v.begin_check("https://example.com")
    assert v.live_step == ""
