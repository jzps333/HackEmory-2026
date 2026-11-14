"""Offline tests for POST /scan/stream. The sandbox stream, Jev and Gemini are mocked."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from api import config, jev
from api import main as api_main
from api import scan as api_scan
from api.schema import JevChecks, ScanResult

QR = "https://bit.ly/parking-pay"
SANDBOX = {  # what /run returns (and what the stream's "result" line carries)
    "url": QR, "final_url": "https://pay-parking.example/login", "domain": "pay-parking.example",
    "redirect_chain": [QR, "https://pay-parking.example/login"], "page_title": "Pay Parking",
    "page_text": "Enter your card", "downloads": [], "blocked_requests": [],
    "screenshots": ["shot1.jpg"],
}
VOLATILE = {"scan_id", "scanned_at", "scan_ms"}


def frame(t):
    return {"type": "frame", "jpeg": "/9j/AAAA", "t_ms": t}


def ndjson(*msgs):
    return "".join((m if isinstance(m, str) else json.dumps(m)) + "\n" for m in msgs).encode()


@pytest.fixture
def env(monkeypatch):
    """Sandbox configured; Jev, Gemini and the data layer mocked. Returns call records."""
    seen = {"requests": [], "recorded": []}
    monkeypatch.setattr(config, "SANDBOX_URL", "http://sandbox.test/")
    monkeypatch.setattr(config, "SANDBOX_TOKEN", "tok")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(jev, "check_page",
                        lambda sandbox: JevChecks(impersonates="fake_bank", malicious_p=0.92))
    monkeypatch.setattr(api_scan, "explain", lambda sandbox, verdict, scam_type, sig=None: f"EXPLAINED {verdict}")
    monkeypatch.setattr(api_main, "flagged_before", lambda result: 3)
    monkeypatch.setattr(api_main, "record_scan", lambda result: seen["recorded"].append(result))
    monkeypatch.setattr(api_main, "FRAME_MIN_GAP_S", 0)   # forward every frame unless a test says not
    return seen


def mock_sandbox(monkeypatch, seen, respond):
    """Route api.scan's httpx.Client through a MockTransport; respond(request) -> httpx.Response."""
    real_client = httpx.Client

    def handler(request):
        seen["requests"].append(request)
        return respond(request)

    monkeypatch.setattr(api_scan.httpx, "Client",
                        lambda *a, **k: real_client(*a, transport=httpx.MockTransport(handler), **k))


def post_stream(body=None):
    r = TestClient(api_main.app).post("/scan/stream", json=body or {"url": QR})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(line) for line in r.text.splitlines()]
    assert r.text.endswith("\n")
    results = [m for m in lines if m["type"] == "result"]
    assert len(results) == 1 and lines[-1] is results[0]   # always exactly one result, last
    return lines


def test_frames_forwarded_and_result_matches_scan(env, monkeypatch):
    sent = [frame(0), {"type": "nav", "url": "https://pay-parking.example/login"}, frame(250),
            "", "not json", {"type": "result", "data": SANDBOX}]
    mock_sandbox(monkeypatch, env, lambda req: httpx.Response(200, content=ndjson(*sent)))

    lines = post_stream({"url": f"  {QR} ", "lat": 33.749123, "lng": -84.388456})
    assert lines[:-1] == [sent[0], sent[1], sent[2]]   # frames + nav forwarded as-is, in order

    req = env["requests"][0]
    assert str(req.url) == "http://sandbox.test/run/stream"
    assert req.headers["authorization"] == "Bearer tok"
    assert json.loads(req.content) == {"url": QR}

    data = lines[-1]["data"]
    assert "error" not in lines[-1]
    assert set(data) == set(ScanResult.model_fields)
    assert (data["verdict"], data["scam_type"], data["explanation"]) == (
        "malicious", "fake_bank", "EXPLAINED malicious")
    assert data["flagged_before"] == 3 and data["location"] == [33.749, -84.388]
    assert data["final_url"] == SANDBOX["final_url"] and data["screenshots"] == ["shot1.jpg"]
    assert len(env["recorded"]) == 1 and env["recorded"][0].scan_id == data["scan_id"]

    # Same sandbox output through POST /scan gives the same JSON (apart from ids/timestamps).
    monkeypatch.setattr(api_scan, "run_sandbox", lambda url: dict(SANDBOX))
    plain = TestClient(api_main.app).post(
        "/scan", json={"url": QR, "lat": 33.749123, "lng": -84.388456}).json()
    strip = lambda d: {k: v for k, v in d.items() if k not in VOLATILE}  # noqa: E731
    assert strip(plain) == strip(data)


def test_fast_frames_keep_newest(env, monkeypatch):
    monkeypatch.setattr(api_main, "FRAME_MIN_GAP_S", 10)
    sent = [frame(t) for t in range(5)] + [{"type": "result", "data": SANDBOX}]
    mock_sandbox(monkeypatch, env, lambda req: httpx.Response(200, content=ndjson(*sent)))
    lines = post_stream()
    assert [m["t_ms"] for m in lines if m["type"] == "frame"] == [0, 4]


class _TimesOut(httpx.SyncByteStream):
    def __iter__(self):
        yield ndjson(frame(0))
        raise httpx.ReadTimeout("sandbox went quiet")


def _raise_connect(req):
    raise httpx.ConnectError("refused")


@pytest.mark.parametrize("respond, frames, error", [
    (lambda req: httpx.Response(200, content=ndjson(frame(0), {"type": "error", "detail": "boom"})),
     1, "sandbox_error"),
    (lambda req: httpx.Response(200, content=ndjson(frame(0))), 1, "no_result"),
    (lambda req: httpx.Response(200, stream=_TimesOut()), 1, "sandbox_timeout"),
    (lambda req: httpx.Response(500, text="Internal Server Error"), 0, "sandbox_http_500"),
    (lambda req: httpx.Response(401, json={"detail": "bad token"}), 0, "sandbox_http_401"),
    (_raise_connect, 0, "sandbox_unreachable"),
], ids=["error-line", "no-result", "timeout", "http-500", "http-401", "unreachable"])
def test_failures_still_end_with_one_result(env, monkeypatch, respond, frames, error):
    mock_sandbox(monkeypatch, env, respond)
    lines = post_stream()
    assert len(lines) == frames + 1
    last = lines[-1]
    assert last["error"] == error
    assert set(last["data"]) == set(ScanResult.model_fields)
    assert last["data"]["verdict"] == "suspicious" and last["data"]["url"] == QR
    assert env["recorded"] == []   # like /scan, a failed scan isn't logged


def test_postprocessing_crash_still_ends_with_result(env, monkeypatch):
    def broken(sandbox):
        raise RuntimeError("not a JevError")
    monkeypatch.setattr(jev, "check_page", broken)
    mock_sandbox(monkeypatch, env, lambda req: httpx.Response(
        200, content=ndjson(frame(0), {"type": "result", "data": SANDBOX})))
    lines = post_stream()
    assert [m["type"] for m in lines] == ["frame", "result"]
    assert lines[-1]["error"] == "scan_failed" and lines[-1]["data"]["verdict"] == "suspicious"


def test_mock_mode_single_result_line(env, monkeypatch):
    monkeypatch.setattr(config, "SANDBOX_URL", "")
    mock_sandbox(monkeypatch, env, lambda req: pytest.fail("sandbox must not be called"))
    lines = post_stream()
    assert len(lines) == 1 and "error" not in lines[0]
    data = lines[0]["data"]
    assert set(data) == set(ScanResult.model_fields)
    assert data["url"] == QR and data["verdict"] == "malicious" and data["flagged_before"] == 3
    assert len(env["recorded"]) == 1


def test_solana_pay_skips_sandbox(env, monkeypatch):
    mock_sandbox(monkeypatch, env, lambda req: pytest.fail("sandbox must not be called"))
    qr = "solana:So11111111111111111111111111111111111111112?amount=5&label=Peachtree%20Parking%20Co."
    lines = post_stream({"url": qr})
    assert len(lines) == 1 and lines[0]["data"]["scam_type"] == "fake_payment_app"


def test_bad_request_is_422_like_scan(env):
    c = TestClient(api_main.app)
    assert c.post("/scan/stream", json={}).status_code == 422
    assert c.post("/scan/stream", json={"url": QR, "lat": "x"}).status_code == 422
