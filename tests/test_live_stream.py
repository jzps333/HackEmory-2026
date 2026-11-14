"""Offline tests for the live sandbox-browser stream on the FaceTime video (no LiveKit, no network)."""
import asyncio
import base64
import io
import json
import sys
import threading
import time
import types
from pathlib import Path

import httpx
import pytest
from PIL import Image

# chert.status_video / chert.agent_integration import livekit, which a plain test venv doesn't
# have. Stub just enough of it; the real package is used when it is installed.
try:
    import livekit.rtc  # noqa: F401
    import livekit.agents  # noqa: F401
except ImportError:
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

from chert import scansafe_tools  # noqa: E402
from chert import status_video  # noqa: E402
from chert.scansafe_tools import scan_url_stream  # noqa: E402
from chert.status_video import StatusVideo  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SAFE = json.loads((ROOT / "shared" / "mock_safe.json").read_text())
MAL = json.loads((ROOT / "shared" / "mock_malicious.json").read_text())
URL = "https://bit.ly/peachtree-park-42"
LIVE_COLOR = (10, 120, 200)


@pytest.fixture(autouse=True)
def _api(monkeypatch):
    monkeypatch.setenv("SCANSAFE_API_URL", "http://scansafe.test")


def jpeg(size=(780, 1688), color=LIVE_COLOR) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG", quality=90)
    return buf.getvalue()


def frame_line(data: bytes, t_ms=0) -> dict:
    return {"type": "frame", "jpeg": base64.b64encode(data).decode(), "t_ms": t_ms}


def ndjson(*objs) -> bytes:
    return b"".join(json.dumps(o).encode() + b"\n" for o in objs)


def mock_client(stream_response, scan_result=SAFE):
    """httpx client whose /scan/stream gives ``stream_response`` (Response or callable) and whose
    plain /scan gives ``scan_result``. Returns (client, list of paths requested)."""
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        assert json.loads(req.content)["url"] == URL
        if req.url.path == "/scan/stream":
            return stream_response(req) if callable(stream_response) else stream_response
        if req.url.path == "/scan":
            return httpx.Response(200, json=scan_result)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


# --- scan_url_stream ---------------------------------------------------------------------------

def test_stream_delivers_frames_and_navs_and_returns_result():
    a, b = jpeg(color=(1, 2, 3)), jpeg(color=(200, 10, 10))
    body = ndjson(frame_line(a, 10), {"type": "nav", "url": "https://trk.redirect-hub.top/x"},
                  frame_line(b, 300), {"type": "result", "data": MAL})
    client, calls = mock_client(httpx.Response(200, content=body))
    frames, navs = [], []
    out = scan_url_stream(URL, frames.append, navs.append, client=client)
    assert out == MAL
    assert frames == [a, b]
    assert navs == ["https://trk.redirect-hub.top/x"]
    assert calls == ["/scan/stream"]                 # no fallback when the stream worked


def test_stream_404_falls_back_to_scan():
    client, calls = mock_client(httpx.Response(404, json={"detail": "Not Found"}))
    frames = []
    assert scan_url_stream(URL, frames.append, client=client) == SAFE
    assert calls == ["/scan/stream", "/scan"] and frames == []


def test_stream_without_result_falls_back_to_scan():
    body = ndjson(frame_line(jpeg()), {"type": "nav", "url": "https://a.example"})
    client, calls = mock_client(httpx.Response(200, content=body))
    frames = []
    assert scan_url_stream(URL, frames.append, client=client) == SAFE
    assert calls == ["/scan/stream", "/scan"] and len(frames) == 1


def test_stream_bad_json_falls_back_to_scan():
    client, calls = mock_client(httpx.Response(200, content=b'{"type":"frame","jpeg":\n'))
    assert scan_url_stream(URL, lambda _j: None, client=client) == SAFE
    assert calls == ["/scan/stream", "/scan"]


def test_stream_bad_result_shape_falls_back_to_scan():
    body = ndjson({"type": "result", "data": {"verdict": "who knows"}})
    client, calls = mock_client(httpx.Response(200, content=body))
    assert scan_url_stream(URL, lambda _j: None, client=client) == SAFE
    assert calls == ["/scan/stream", "/scan"]


def test_stream_connection_error_falls_back_to_scan():
    def refuse(req):
        raise httpx.ConnectError("connection refused", request=req)
    client, calls = mock_client(refuse)
    assert scan_url_stream(URL, lambda _j: None, client=client) == SAFE
    assert calls == ["/scan/stream", "/scan"]


def test_stream_and_fallback_both_down_gives_error_result():
    def handler(req):
        raise httpx.ConnectError("down", request=req)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    out = scan_url_stream(URL, lambda _j: None, client=client)
    assert out["verdict"] == "error" and out["url"] == URL


def test_broken_frame_callback_does_not_break_the_scan():
    body = ndjson(frame_line(jpeg()), {"type": "result", "data": SAFE})
    client, calls = mock_client(httpx.Response(200, content=body))

    def boom(_jpeg):
        raise RuntimeError("video gone")
    assert scan_url_stream(URL, boom, client=client) == SAFE
    assert calls == ["/scan/stream"]


def test_should_stop_closes_stream_and_returns_none():
    sent = []

    def lines():
        for i in range(50):
            sent.append(i)
            yield ndjson(frame_line(jpeg(size=(39, 84)), i))
        yield ndjson({"type": "result", "data": SAFE})

    client, calls = mock_client(lambda req: httpx.Response(200, content=lines()))
    frames = []
    out = scan_url_stream(URL, frames.append, should_stop=lambda: len(frames) >= 2, client=client)
    assert out is None
    assert len(frames) == 2
    assert len(sent) < 50                            # we hung up; the rest was never read
    assert calls == ["/scan/stream"]                 # and no fallback scan after a stop


def test_scan_url_is_unchanged():
    client, calls = mock_client(httpx.Response(500))
    assert scansafe_tools.scan_url(URL, client=client) == SAFE
    assert calls == ["/scan"]


# --- StatusVideo live screen -------------------------------------------------------------------

def make_video() -> StatusVideo:
    """StatusVideo without its LiveKit VideoSource (same attributes __init__ sets)."""
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


def pixel(frame: bytes, x: int, y: int) -> tuple:
    i = (y * StatusVideo.W + x) * 4
    return tuple(frame[i:i + 3])


def close(a, b, tol=12) -> bool:
    return all(abs(p - q) <= tol for p, q in zip(a, b))


def test_live_frame_renders_checking_screen():
    v = make_video()
    v.begin_check(URL)
    now = time.monotonic()
    before = v._render(now)                          # no frames yet: today's checklist
    key_before = v._frame_key(now)
    assert len(before) == v.W * v.H * 4
    assert not close(pixel(before, v.W // 2, 800), LIVE_COLOR)

    assert v.set_live_frame(jpeg()) is True
    pic, mask = v.live
    assert pic.width <= v.W - 40 and pic.height <= v.H - status_video.LIVE_TOP - 20
    assert mask.size == pic.size
    v.note_nav("https://www.trk.redirect-hub.top/landing?id=9")
    assert v.live_host == "trk.redirect-hub.top"

    frame = v._render(now + 4)
    assert len(frame) == v.W * v.H * 4
    assert close(pixel(frame, v.W // 2, 800), LIVE_COLOR)     # the live picture is on screen
    k1 = v._frame_key(now)
    assert k1 != key_before
    v.set_live_frame(jpeg(color=(0, 200, 0)))
    assert v._frame_key(now) != k1                   # a new frame forces a redraw


def test_phone_sized_and_small_frames_fit():
    v = make_video()
    v.begin_check(URL)
    for size in ((390, 844), (780, 1688), (1080, 1920), (300, 200)):
        assert v.set_live_frame(jpeg(size=size))
        pic, _ = v.live
        assert pic.width <= v.W - 40 and pic.height <= v.H - status_video.LIVE_TOP - 20
        assert len(v._render(time.monotonic())) == v.W * v.H * 4


def test_live_frame_ignored_when_not_checking_or_garbage():
    v = make_video()
    assert v.set_live_frame(jpeg()) is False         # idle: nothing to show it on
    v.begin_check(URL)
    assert v.set_live_frame(b"not a jpeg") is False
    assert v.live is None


def test_result_and_reset_clear_live_state():
    v = make_video()
    v.begin_check(URL)
    v.set_live_frame(jpeg())
    v.note_nav("https://a.example/")
    v.set_result(SAFE)
    assert v.live is None and v.state == "safe"
    frame = v._render(time.monotonic())              # replay checklist, as before
    assert len(frame) == v.W * v.H * 4
    assert v.set_live_frame(jpeg()) is False         # stragglers after the result are dropped
    v.begin_check(URL)
    v.set_live_frame(jpeg())
    v.reset()
    assert v.live is None and v.live_host == "" and v.state == "idle"
    v.begin_check("https://other.example")
    assert v.live is None and v.live_host == ""      # a new check starts clean


# --- ScanSafeCall.scan wiring --------------------------------------------------------------------

def make_call(monkeypatch, fake_stream):
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)   # don't pull a .env into the run
    from chert import agent_integration as ai
    monkeypatch.setattr(ai, "scan_url_stream", fake_stream)
    call = ai.ScanSafeCall.__new__(ai.ScanSafeCall)
    call.session = types.SimpleNamespace(interrupt=lambda: None)
    call.video = make_video()
    call._inflight, call._results = {}, {}
    call.generation = 0
    return call


def test_scan_streams_frames_and_caches(monkeypatch):
    seen = {"n": 0}

    def fake(code, on_frame, on_nav=None, should_stop=None):
        seen["n"] += 1
        on_nav("https://trk.redirect-hub.top/a")
        on_frame(jpeg())
        assert not should_stop()
        return MAL

    call = make_call(monkeypatch, fake)

    async def run():
        call.video.begin_check(URL)
        r1 = await call.scan(URL)
        assert call.video.live is not None and call.video.live_host == "trk.redirect-hub.top"
        r2 = await call.scan(URL)                    # cached for 30 s: no second stream
        return r1, r2

    r1, r2 = asyncio.run(run())
    assert r1 == r2 == MAL and seen["n"] == 1


def test_stop_mid_stream_drops_frames_and_cancels(monkeypatch):
    stopped_seen = threading.Event()
    late_frame_pushed = threading.Event()

    def fake(code, on_frame, on_nav=None, should_stop=None):
        on_frame(jpeg())
        deadline = time.monotonic() + 5
        while not should_stop() and time.monotonic() < deadline:
            time.sleep(0.01)
        stopped_seen.set()
        on_frame(jpeg(color=(0, 255, 0)))           # a straggler after stop must not show
        late_frame_pushed.set()
        return None

    call = make_call(monkeypatch, fake)

    async def run():
        call.video.begin_check(URL)
        task = asyncio.create_task(call.scan(URL))
        for _ in range(200):
            if call.video.live is not None:
                break
            await asyncio.sleep(0.01)
        assert call.video.live is not None            # the live frame made it on screen
        assert call.stop() is True
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.to_thread(late_frame_pushed.wait, 5)

    asyncio.run(run())
    assert stopped_seen.is_set()
    assert call.video.live is None and call.video.state == "idle"
    assert URL not in call._results                   # a stopped scan isn't cached


def test_stream_returning_none_is_treated_as_cancel(monkeypatch):
    call = make_call(monkeypatch, lambda code, on_frame, on_nav=None, should_stop=None: None)

    async def run():
        with pytest.raises(asyncio.CancelledError):
            await call.scan(URL)

    asyncio.run(run())
    assert URL not in call._results and not call._inflight
