"""Sandbox operator mode (sandbox/operate.py, server.py /operate/stream, run_scan.py --operate).
Offline: no Docker, no Playwright, no network. The container is a fake subprocess."""
import importlib.util
import inspect
import io
import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

SANDBOX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sandbox")
sys.path.insert(0, SANDBOX)
import operate as op  # noqa: E402
import run_scan as rs  # noqa: E402  (Playwright is only imported inside scan()/operate())

INSTALL = "https://scansafe-demo-sites.vercel.app/dogwood/install?s=tok_abc123456"
APP = "https://scansafe-demo-sites.vercel.app/dogwood/app?s=tok_abc123456"


def load_server(monkeypatch):
    monkeypatch.setenv("SANDBOX_TOKEN", "tok")
    spec = importlib.util.spec_from_file_location("sandbox_server_under_test", os.path.join(SANDBOX, "server.py"))
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mod)    # pydantic resolves the models through it
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "url_allowed", lambda url: (True, "public"))   # no DNS in tests
    return mod


# --- URL allowlist -------------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    INSTALL, APP, "https://scansafe-demo-sites.vercel.app/dogwood/authorize?state=x",
    "https://SCANSAFE-DEMO-SITES.vercel.app/dogwood/app?s=abc12345",
])
def test_operate_url_allowed(url):
    assert op.operate_url_allowed(url) == (True, "ok")


@pytest.mark.parametrize("url", [
    "http://scansafe-demo-sites.vercel.app/dogwood/app",               # not https
    "https://evil.com/dogwood/app",
    "https://scansafe-demo-sites.vercel.app.evil.com/dogwood/app",
    "https://evil.scansafe-demo-sites.vercel.app/dogwood/app",          # subdomain
    "https://scansafe-demo-sites.vercel.app./dogwood/app",              # trailing dot
    "https://scansafe-demo-sites.vercel.app:443/dogwood/app",           # explicit port
    "https://scansafe-demo-sites.vercel.app:8443/dogwood/app",
    "https://user:pw@scansafe-demo-sites.vercel.app/dogwood/app",
    "https://scansafe-demo-sites.vercel.app@evil.com/dogwood/app",
    "https://scansafe-demo-sites.vercel.app/dogwood",                   # not under /dogwood/
    "https://scansafe-demo-sites.vercel.app/websites/scams/unpaid-toll",
    "https://scansafe-demo-sites.vercel.app/fixtures/meter/index.html",
    "https://scansafe-demo-sites.vercel.app/dogwood/../websites/scams/unpaid-toll",
    "https://scansafe-demo-sites.vercel.app/dogwood/%2e%2e/websites",
    "https://scansafe-demo-sites.vercel.app/dogwood/%252e%252e/websites",
    "https://scansafe-demo-sites.vercel.app/dogwood//evil.com",
    "https://scansafe-demo-sites.vercel.app/dogwood/..%5cwebsites",
    "https://scansafe-demo-sites.vercel.app/dogwood/app ?s=x",
    "https://scansafe-demo-sites.vercel.app/dogwood/app\n",
    "javascript:alert(1)", "file:///etc/passwd", "", None, 42,
    "https://scansafe-demo-sites.vercel.app/dogwood/" + "a" * 3000,
    "https://[::1]/dogwood/app", "https://127.0.0.1/dogwood/app",
])
def test_operate_url_refused(url):
    ok, why = op.operate_url_allowed(url)
    assert ok is False and why


def test_requests_inside_the_operate_browser():
    # top-level pages: only the Dogwood pages
    assert op.operate_request_allowed(APP, top_nav=True)[0]
    assert not op.operate_request_allowed("https://scansafe-demo-sites.vercel.app/websites", top_nav=True)[0]
    assert not op.operate_request_allowed("https://explorer.solana.com/tx/abc", top_nav=True)[0]
    assert not op.operate_request_allowed("https://api.scansafe.nyc/", top_nav=True)[0]
    # subresources: the demo site's own scripts and the ScanSafe API, nothing else
    assert op.operate_request_allowed("https://scansafe-demo-sites.vercel.app/_next/static/a.js", False)[0]
    assert op.operate_request_allowed("https://api.scansafe.nyc/operators/dogwood/app-state?s=x", False)[0]
    assert op.operate_request_allowed("data:image/png;base64,AAAA", False)[0]
    for url in ("https://evil.com/x.js", "http://api.scansafe.nyc/x", "https://api.scansafe.nyc:8000/x",
                "https://explorer.solana.com/", "https://u:p@api.scansafe.nyc/", "wss://api.scansafe.nyc/"):
        assert not op.operate_request_allowed(url, False)[0], url


def test_plate_and_hours_checks():
    assert op.clean_plate(" ga  4821k ") == "GA 4821K"
    assert op.clean_plate("ABC-123") == "ABC-123"
    assert op.clean_plate("AB\n12") == "AB 12"                 # whitespace collapses to one space
    for bad in ("", "   ", "A" * 11, "AB<script>", "ÄBC", "AB\x0012", "-ABC", None, 1234, ["A"]):
        assert op.clean_plate(bad) is None, bad
    assert [op.valid_hours(h) for h in (1, 2, 3, 4)] == [1, 2, 3, 4]
    for bad in (0, 5, -1, True, False, 2.0, "3", None):
        assert op.valid_hours(bad) is None, bad
    assert op.check_operate_request(INSTALL, "GA4821K", 3) == (True, "ok")
    assert not op.check_operate_request("https://evil.com/dogwood/app", "GA4821K", 3)[0]
    assert not op.check_operate_request(INSTALL, "", 3)[0]
    assert not op.check_operate_request(INSTALL, "GA4821K", 9)[0]


# --- step logic ----------------------------------------------------------------------------------

def test_plan_steps_from_install_or_app():
    assert op.plan_steps(INSTALL) == ("open", "install", "open_app", "plate", "hours", "pay", "wait")
    assert op.plan_steps(APP) == ("open", "plate", "hours", "pay", "wait")
    assert op.plan_steps(APP.replace("/app?", "/app/?")) == op.STEPS_FROM_APP
    assert op.plan_steps("https://scansafe-demo-sites.vercel.app/dogwood/authorize") == ()


def test_step_texts_and_selectors():
    assert op.step_text("install") == "Tapping Install"
    assert op.step_text("plate", "GA 4821K", 2) == "Typing your plate GA 4821K"
    assert op.step_text("hours", "X", 1) == "Choosing 1 hour"
    assert op.step_text("hours", "X", 3) == "Choosing 3 hours"
    assert op.step_text("pay") == "Tapping Pay with linked ScanSafe account"
    assert op.hours_selector(3) == '[data-testid="hours-3"]'
    assert op.SEL["plate"] == '[data-testid="plate"]' and op.SEL["install"] == '[data-testid="install"]'


@pytest.mark.parametrize("flags,phase", [
    ({"install": True}, "install"),
    ({"installing": True}, "installing"),
    ({"open": True}, "ready_to_open"),
    ({"plate": True, "pay": True}, "app"),
    ({"waiting": True}, "waiting"),
    ({"receipt": True, "waiting": True}, "paid"),          # the receipt wins
    ({"no_session": True}, "no_session"),
    ({}, "unknown"), (None, "unknown"), ([], "unknown"),
])
def test_page_phase(flags, phase):
    assert op.page_phase(flags) == phase


def test_operate_status():
    assert op.operate_status(["open", "plate", "hours", "pay"], "paid", None) == "paid"
    assert op.operate_status(["open", "plate", "hours", "pay"], "waiting", None) == "waiting"
    assert op.operate_status(["open"], "app", "Timeout 15000ms exceeded") == "failed"
    assert op.operate_status(["open", "pay"], "waiting", "browser crashed") == "failed"
    assert op.operate_status([], "unknown", None) == "failed"


def test_operate_refuses_before_starting_a_browser(monkeypatch):
    monkeypatch.setitem(sys.modules, "playwright", None)        # importing it would fail loudly
    for args in (("https://evil.com/dogwood/app", "GA1", 2), (INSTALL, "<b>", 2), (INSTALL, "GA1", 7),
                 ("https://scansafe-demo-sites.vercel.app/dogwood/authorize", "GA1", 2)):
        out = rs.operate(*args)
        assert out["status"] == "failed" and out["error"].startswith("blocked:") and not out["paid"]


def test_scan_path_never_types():
    """Scanning only clicks past harmless barriers; typing exists only in operator mode."""
    for fn in (rs.scan, rs.click_past, rs._click_rounds, rs._launch, rs.start_screencast):
        src = inspect.getsource(fn)
        for typing in (".fill(", ".type(", "press_sequentially", "keyboard", ".press("):
            assert typing not in src, (fn.__name__, typing)
    assert "press_sequentially" in inspect.getsource(rs.operate)


def test_run_scan_cli_modes(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(rs, "operate", lambda url, plate, hours: calls.append(("op", url, plate, hours)) or {"mode": "operate"})
    monkeypatch.setattr(rs, "scan", lambda url, stream=False: calls.append(("scan", url, stream)) or {"url": url})
    assert rs.main(["--operate", INSTALL, "GA1", "3"]) == 0
    assert rs.main(["--operate", INSTALL, "GA1", "x"]) == 0               # bad hours -> operate refuses
    assert rs.main([INSTALL, "--stream"]) == 0
    assert rs.main([INSTALL, "--operate"]) == 1                          # never a scan that operates
    assert rs.main(["--operate", INSTALL]) == 1
    assert rs.main(["--stream"]) == 1
    assert calls == [("op", INSTALL, "GA1", 3), ("op", INSTALL, "GA1", None), ("scan", INSTALL, True)]
    lines = [json.loads(l) for l in capsys.readouterr().out.splitlines()]
    assert lines[0] == {"mode": "operate"} and "usage" in lines[-1]["error"]


# --- server: /operate/stream ---------------------------------------------------------------------

class FakeProc:
    """A finished container: its stdout lines, then exit 0."""
    def __init__(self, lines):
        self.stdout = io.StringIO("".join(l + "\n" for l in lines))

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return 0

    def kill(self):
        pass


def test_operate_stream_needs_the_token(monkeypatch):
    srv = load_server(monkeypatch)
    c = TestClient(srv.app)
    r = c.post("/operate/stream", json={"url": INSTALL, "plate": "GA1", "hours": 2})
    assert r.status_code == 401
    r = c.post("/operate/stream", json={"url": INSTALL, "plate": "GA1", "hours": 2},
               headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


@pytest.mark.parametrize("body", [
    {"url": "https://example.com/", "plate": "GA1", "hours": 2},
    {"url": "https://scansafe-demo-sites.vercel.app/websites/scams/unpaid-toll", "plate": "GA1", "hours": 2},
    {"url": "http://scansafe-demo-sites.vercel.app/dogwood/app", "plate": "GA1", "hours": 2},
    {"url": "https://169.254.169.254/dogwood/app", "plate": "GA1", "hours": 2},
    {"url": INSTALL, "plate": "GA1; rm -rf /", "hours": 2},
    {"url": INSTALL, "plate": "", "hours": 2},
    {"url": INSTALL, "plate": "GA1", "hours": 0},
    {"url": INSTALL, "plate": "GA1", "hours": "3"},
    {"url": INSTALL, "plate": "GA1", "hours": True},
    {"url": INSTALL, "plate": "GA1"},
])
def test_operate_stream_rejects_everything_else(monkeypatch, body):
    srv = load_server(monkeypatch)
    monkeypatch.setattr(srv.subprocess, "Popen", lambda *a, **k: pytest.fail("container started"))
    r = TestClient(srv.app).post("/operate/stream", json=body, headers={"Authorization": "Bearer tok"})
    assert r.status_code == 400, r.text


def test_operate_stream_also_runs_the_network_guard(monkeypatch):
    srv = load_server(monkeypatch)
    monkeypatch.setattr(srv, "url_allowed", lambda url: (False, "resolves to non-public address 10.0.0.1"))
    monkeypatch.setattr(srv.subprocess, "Popen", lambda *a, **k: pytest.fail("container started"))
    r = TestClient(srv.app).post("/operate/stream", json={"url": INSTALL, "plate": "GA1", "hours": 2},
                                 headers={"Authorization": "Bearer tok"})
    assert r.status_code == 400 and "non-public" in r.json()["detail"]


def test_operate_stream_runs_the_operate_container_and_streams(monkeypatch):
    srv = load_server(monkeypatch)
    seen = {}
    container_out = [
        json.dumps({"type": "step", "text": "Opening Dogwood Parking"}),
        json.dumps({"type": "nav", "url": INSTALL}),
        json.dumps({"type": "frame", "jpeg": "AAAA", "t_ms": 10}),
        "chromium noise on stderr",
        json.dumps({"type": "step", "text": "Tapping Install"}),
        json.dumps({"mode": "operate", "status": "paid", "paid": True, "steps": ["open", "pay", "paid"]}),
    ]

    def popen(cmd, **kw):
        seen["cmd"] = cmd
        return FakeProc(container_out)

    monkeypatch.setattr(srv.subprocess, "Popen", popen)
    r = TestClient(srv.app).post("/operate/stream", json={"url": INSTALL, "plate": " ga 4821k", "hours": 3},
                                 headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    msgs = [json.loads(l) for l in r.text.splitlines()]
    assert [m["type"] for m in msgs] == ["step", "nav", "frame", "step", "result"]
    assert msgs[-1]["data"]["status"] == "paid"
    cmd = seen["cmd"]
    # the hardened container, in operate mode, with the cleaned plate as its own argument
    assert cmd[:3] == ["docker", "run", "--rm"] and "--read-only" in cmd and "ALL" in cmd
    assert cmd[-5:] == [srv.IMAGE, "--operate", INSTALL, "GA 4821K", "3"]
    assert "--stream" not in cmd


def test_run_stream_still_scans_after_the_refactor(monkeypatch):
    srv = load_server(monkeypatch)
    seen = {}

    def popen(cmd, **kw):
        seen["cmd"] = cmd
        return FakeProc([json.dumps({"type": "frame", "jpeg": "AA", "t_ms": 1}), json.dumps({"url": "x"})])

    monkeypatch.setattr(srv.subprocess, "Popen", popen)
    r = TestClient(srv.app).post("/run/stream", json={"url": "https://example.com"},
                                 headers={"Authorization": "Bearer tok"})
    msgs = [json.loads(l) for l in r.text.splitlines()]
    assert [m["type"] for m in msgs] == ["frame", "result"]
    assert seen["cmd"][-3:] == [srv.IMAGE, "https://example.com", "--stream"]


def test_operate_stream_reports_a_failed_container(monkeypatch):
    srv = load_server(monkeypatch)
    monkeypatch.setattr(srv.subprocess, "Popen", lambda cmd, **kw: FakeProc(["Traceback ...", "null"]))
    r = TestClient(srv.app).post("/operate/stream", json={"url": APP, "plate": "GA1", "hours": 1},
                                 headers={"Authorization": "Bearer tok"})
    msgs = [json.loads(l) for l in r.text.splitlines()]
    assert msgs[-1]["type"] == "error" and msgs[-1]["detail"].startswith("operate failed")
