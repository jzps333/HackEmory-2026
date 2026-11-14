"""ParkMobile adapter (real site, stops before payment): sandbox/operate.py rules and guards,
run_scan.py --operate-parkmobile with a fake Playwright, server.py /operate/stream adapter
"parkmobile", the agent's stream client, chert/parkmobile.py speech and the call wiring.
Offline: no Docker, no Playwright, no network."""
import asyncio
import importlib.util
import io
import json
import os
import sys
import types

import httpx
import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SANDBOX = os.path.join(ROOT, "sandbox")
sys.path.insert(0, SANDBOX)
import operate as op  # noqa: E402
import run_scan as rs  # noqa: E402

import test_dogwood_agent as tda  # noqa: E402  (LiveKit stub, fake video, jpeg helper)
from chert import parkmobile as pm  # noqa: E402
from chert import scansafe_tools as tools  # noqa: E402

ENTRY = "https://app.parkmobile.io/v2/parking"
ZONE_PAGE = "https://app.parkmobile.io/v2/parking/zone-details?areaNo=10891987"
# Lines of the real zone-details page for Park Tavern (2026-11-14).
ZONE_LINES = ["P", "91987", "Atlanta, GA - Off St Operator", "Surface lot", "•", "Park Tavern",
              "Park here", "Privacy Policy", "Terms of Use"]


# --- url / request allowlist ---------------------------------------------------------------------

@pytest.mark.parametrize("url", [ENTRY, ZONE_PAGE, "https://app.parkmobile.io/zone/start?internalZoneCode=10891987",
                                 "https://app.parkmobile.io/search", "https://APP.parkmobile.io/v2/parking"])
def test_entry_urls_allowed(url):
    assert op.parkmobile_url_allowed(url) == (True, "ok")


@pytest.mark.parametrize("url", [
    "http://app.parkmobile.io/v2/parking", "https://parkmobile.io/v2/parking",
    "https://app.parkmobile.io.evil.com/v2/parking", "https://evil.com/app.parkmobile.io/v2/parking",
    "https://app.parkmobile.io:8443/v2/parking", "https://u:p@app.parkmobile.io/v2/parking",
    "https://app.parkmobile.io/v2/parking/../../account", "https://app.parkmobile.io/v2/parking/%2e%2e/x",
    "https://app.parkmobile.io/account/payment", "https://app.parkmobile.io/v2/parkingx",
    "https://app.parkmobile.io/v2/parking bad", "", None, 42,
])
def test_entry_urls_refused(url):
    assert op.parkmobile_url_allowed(url)[0] is False


def test_top_level_pages_stay_on_the_host():
    assert op.parkmobile_request_allowed("https://app.parkmobile.io/v2/parking/guest-registration", True)[0]
    assert not op.parkmobile_request_allowed("https://parkmobile.io/legal/terms-of-use", True)[0]
    assert not op.parkmobile_request_allowed("https://accounts.google.com/o/oauth2", True)[0]


@pytest.mark.parametrize("url", [
    "https://app.parkmobile.io/api/zones?x=1", "https://api.parkmobile.io/v1/x",
    "https://fonts.gstatic.com/s/x.woff2", "https://res.cloudinary.com/pm/x.png",
    "https://api.mapbox.com/styles/v1/x", "https://app.launchdarkly.com/sdk/evalx/x",
    "https://www.google.com/recaptcha/enterprise.js", "https://www.gstatic.com/recaptcha/releases/x/recaptcha__en.js",
    "data:image/png;base64,AAAA",
])
def test_subresources_allowed(url):
    assert op.parkmobile_request_allowed(url, False)[0]


@pytest.mark.parametrize("url", [
    "https://www.googletagmanager.com/gtm.js", "https://api-js.mixpanel.com/track",
    "https://cdn.cookielaw.org/x.js", "https://connect.facebook.net/x.js", "https://events.launchdarkly.com/x",
    "https://events.mapbox.com/events/v2", "https://accounts.google.com/gsi/client",
    "https://www.google.com/maps", "https://js.stripe.com/v3", "http://fonts.gstatic.com/x",
    "https://app.parkmobile.io:444/x", "https://evilparkmobile.io/x",
])
def test_subresources_refused(url):
    assert not op.parkmobile_request_allowed(url, False)[0]


# --- inputs ----------------------------------------------------------------------------------------

def test_zone_validation():
    assert op.clean_zone("91987") == "91987" and op.clean_zone(" 919 87 ") == "91987"
    assert op.clean_zone(8610) == "8610" and op.clean_zone("123") == "123" and op.clean_zone("1234567")
    for bad in ("12", "12345678", "91a87", "", None, True, 9.5, "-1", "91987; rm"):
        assert op.clean_zone(bad) is None


def test_check_parkmobile_request():
    assert op.check_parkmobile_request(ENTRY, "91987", "DEMO123", hours=2) == (True, "ok")
    assert op.check_parkmobile_request(ZONE_PAGE, None, "demo123", minutes=120) == (True, "ok")
    assert not op.check_parkmobile_request(ENTRY, None, "DEMO123", hours=2)[0]      # no zone, no areaNo
    assert not op.check_parkmobile_request(ENTRY, "91a", "DEMO123", hours=2)[0]
    assert not op.check_parkmobile_request(ENTRY, "91987", "DEMO;123", hours=2)[0]
    assert not op.check_parkmobile_request(ENTRY, "91987", "DEMO123")[0]           # no duration
    assert not op.check_parkmobile_request(ENTRY, "91987", "DEMO123", minutes=5)[0]
    assert not op.check_parkmobile_request(ENTRY, "91987", "DEMO123", hours=13)[0]
    assert not op.check_parkmobile_request(ENTRY, "91987", "DEMO123", hours=True)[0]
    assert not op.check_parkmobile_request("https://example.com/v2/parking", "91987", "DEMO123", hours=2)[0]
    assert op.pm_area_from_url(ZONE_PAGE) == "10891987" and op.pm_area_from_url(ENTRY) is None


# --- the hard guards ------------------------------------------------------------------------------

@pytest.mark.parametrize("label", [
    "Pay", "Pay $4.35", "PAY NOW", "Purchase", "Checkout", "Check out", "Confirm payment", "Confirm",
    "Start parking", "START PARKING", "Start session", "Buy now", "Submit order", "Place order",
    "Apple Pay", "Google Pay", "GPay", "PayPal", "Sign in", "Log in", "Sign up", "I agree",
    "Accept", "Download app", "Continue to payment",
])
def test_click_guard_refuses_pay_like_labels(label):
    assert op.pm_click_refused(label)


@pytest.mark.parametrize("label", ["Park here", "Continue", "Next", "P 91987 Atlanta, GA - Off St Operator",
                                   "2 hours", "Search another zone", "Go back", "Close"])
def test_click_guard_allows_flow_buttons(label):
    assert not op.pm_click_refused(label)


SEARCH_ATTRS = {"type": "", "name": "", "id": "search-input", "autocomplete": "off",
                "aria": "Search for parking", "placeholder": "Zone, address", "label": "",
                "testid": "search-input"}


@pytest.mark.parametrize("attrs", [
    {"autocomplete": "cc-number"}, {"name": "cardnumber"}, {"aria": "Card number"}, {"name": "cvv"},
    {"placeholder": "CVC"}, {"id": "exp-date"}, {"label": "Expiration"}, {"type": "password"},
    {"type": "email"}, {"type": "tel"}, {"aria": "Enter email address"}, {"placeholder": "Email"},
    {"label": "Phone number"}, {"name": "mobile"}, {"autocomplete": "one-time-code"},
    {"name": "zip"}, {"label": "Billing address"}, {"autocomplete": "email"},
    {"id": "guest-registration-email-input"}, {"name": "first_name"}, None, "card",
])
def test_type_guard_refuses_sensitive_fields(attrs):
    assert op.pm_type_refused(attrs)


def test_type_guard_allows_zone_and_plate_boxes():
    assert not op.pm_type_refused(SEARCH_ATTRS)
    assert not op.pm_type_refused({"type": "text", "aria": "License plate", "name": "plate"})
    assert op.pm_type_value_ok("91987", "91987", "DEMO123") and op.pm_type_value_ok("DEMO123", "91987", "DEMO123")
    assert not op.pm_type_value_ok("4111111111111111", "91987", "DEMO123")
    assert not op.pm_type_value_ok("me@example.com", None, "DEMO123") and not op.pm_type_value_ok("", None, None)


class FakeLoc:
    def __init__(self, label="", attrs=None):
        self.label, self.attrs, self.calls = label, attrs or {}, []

    def evaluate(self, js, timeout=None):
        return self.label if js == rs.PM_LABEL_JS else self.attrs

    def click(self, timeout=None):
        self.calls.append("click")

    def fill(self, v, timeout=None):
        self.calls.append(("fill", v))

    def press_sequentially(self, v, delay=None, timeout=None):
        self.calls.append(("type", v))


def test_pm_click_refuses_and_never_clicks():
    refused = []
    loc = FakeLoc("Start parking")
    with pytest.raises(rs.GuardRefused):
        rs.pm_click(loc, refused)
    assert loc.calls == [] and refused == [{"action": "click", "label": "Start parking"}]
    ok = FakeLoc("Park here")
    rs.pm_click(ok, refused)
    assert ok.calls == ["click"]


def test_pm_type_refuses_sensitive_fields_and_other_values():
    refused = []
    email = FakeLoc(attrs={"type": "email", "id": "guest-registration-email-input"})
    with pytest.raises(rs.GuardRefused):
        rs.pm_type(email, "DEMO123", "91987", "DEMO123", refused)
    box = FakeLoc(attrs=SEARCH_ATTRS)
    with pytest.raises(rs.GuardRefused):
        rs.pm_type(box, "someone@example.com", "91987", "DEMO123", refused)
    assert email.calls == [] and box.calls == [] and len(refused) == 2
    rs.pm_type(box, "91987", "91987", "DEMO123", refused)
    assert box.calls == ["click", ("fill", ""), ("type", "91987")]


# --- screens ---------------------------------------------------------------------------------------

def facts(**kw):
    base = {"path": "/v2/parking", "text": "", "lines": [], "inputs": [], "pay_frames": 0,
            "search": False, "zone_details": False, "unsupported": False, "space_number": False}
    return {**base, **kw}


GUEST = facts(path="/v2/parking/guest-registration", text="Add email\nEmail\nI agree to the ParkMobile Terms",
              inputs=[{"type": "email", "id": "guest-registration-email-input", "aria": "Enter email address"},
                      {"type": "checkbox", "id": "guest-registration-terms-checkbox"}])


def test_screens():
    assert op.pm_screen(GUEST) == "sign_in"
    assert op.pm_screen(facts(path="/v2/parking/x", inputs=[{"type": "password"}])) == "sign_in"
    assert op.pm_screen(facts(text="Payment method\nAdd card")) == "payment"
    assert op.pm_screen(facts(inputs=[{"autocomplete": "cc-number"}])) == "payment"
    assert op.pm_screen(facts(pay_frames=1)) == "payment"
    assert op.pm_screen(facts(text="Review\nParking $4.00\nTransaction fee $0.35\nTotal $4.35")) == "review"
    assert op.pm_screen(GUEST, robot=True) == "robot_check"
    assert op.pm_screen(facts(unsupported=True, zone_details=True)) == "unsupported"
    assert op.pm_screen(facts(space_number=True)) == "space_number"
    assert op.pm_screen(facts(zone_details=True, lines=ZONE_LINES)) == "zone_details"
    assert op.pm_screen(facts(search=True)) == "search"
    assert op.pm_screen(facts(inputs=[{"aria": "License plate"}])) == "plate"
    assert op.pm_screen(facts(text="How long?\n1 hour\n2 hours")) == "duration"
    assert op.pm_screen(facts()) == "unknown" and op.pm_screen(None) == "unknown"
    assert [op.pm_status(s) for s in ("review", "payment", "sign_in", "robot_check", "unsupported", "unknown")] == \
        ["ready_to_pay", "ready_to_pay", "needs_sign_in", "robot_check", "failed", "failed"]


def test_zone_info_and_price_text():
    assert op.pm_zone_info(ZONE_LINES, "91987") == {"zone": "91987", "zone_name": "Park Tavern",
                                                    "operator": "Atlanta, GA - Off St Operator"}
    assert op.pm_zone_info(ZONE_LINES, None)["zone"] == "91987"
    assert op.pm_zone_info(ZONE_LINES, "8610")["zone_name"] is None
    assert op.pm_price_text("Review\nTotal: $4.35 <b>\"incl. fees\"</b>\nPay") == "Total: $4.35 b incl. fees /b"
    assert op.pm_price_text("no price here") is None
    assert len(op.pm_price_text("Total $1.00 " + "x" * 300)) <= 80


# --- run_scan.py --operate-parkmobile with a fake Playwright ------------------------------------

class FakePage:
    """search -> (type zone, pick result) -> zone details -> (Park here) -> ``after``."""
    def __init__(self, after, continue_label="Park here Park here"):
        self.state, self.after, self.continue_label = "search", after, continue_label
        self.url, self.typed, self.clicked = "about:blank", [], []

    def on(self, *a):
        pass

    def goto(self, url, **kw):
        self.url = url

    def wait_for_selector(self, sel, **kw):
        pass

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, js):
        assert js == op.PM_FACTS_JS
        if self.state == "search":
            return facts(search=True)
        if self.state == "zone":
            return facts(path="/v2/parking/zone-details", zone_details=True, lines=ZONE_LINES)
        return self.after

    def locator(self, sel):
        page = self

        class L(FakeLoc):
            first = property(lambda s: s)

            def wait_for(self, **kw):
                pass

            def click(self, timeout=None):
                page.clicked.append(sel)
                if sel == op.pm_result_selector("91987"):
                    page.state, page.url = "zone", ZONE_PAGE
                elif sel == op.PM_SEL["continue"]:
                    page.state, page.url = "after", "https://app.parkmobile.io/v2/parking/guest-registration"

            def press_sequentially(self, v, delay=None, timeout=None):
                page.typed.append(v)
        if sel == op.PM_SEL["search"]:
            return L(attrs=SEARCH_ATTRS)
        if sel == op.PM_SEL["continue"]:
            return L(self.continue_label)
        return L("P 91987 Atlanta, GA - Off St Operator")

    def screenshot(self, **kw):
        return b"\xff\xd8jpeg"


def run_fake(monkeypatch, page, robot=False):
    browser = types.SimpleNamespace(close=lambda: None)
    context = types.SimpleNamespace(new_page=lambda: page)
    monkeypatch.setattr(rs, "_launch", lambda p, on_route, **kw: (browser, context))
    monkeypatch.setattr(rs, "start_screencast", lambda *a: True)
    monkeypatch.setattr(rs, "page_state", lambda pg: {"text_len": 50, "title": "", "text": "", "markers": [],
                                                       "iframes": [{"src": "https://www.google.com/recaptcha/api2/bframe?k=1",
                                                                    "visible": True}] if robot else []})
    monkeypatch.setattr(rs.CachingGuard, "check", lambda self, url: (True, "public"))
    monkeypatch.setattr(rs, "PM_SETTLE_MS", 0)

    class CM:
        def __enter__(self):
            return object()

        def __exit__(self, *a):
            return False
    fake = types.ModuleType("playwright.sync_api")
    fake.sync_playwright = lambda: CM()
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake)
    lines = []
    monkeypatch.setattr(rs, "_emit", lambda obj: lines.append(obj))
    return rs.operate_parkmobile(ENTRY, "91987", "demo123", 120), lines


def test_guest_flow_stops_at_add_email(monkeypatch):
    page = FakePage(GUEST)
    out, lines = run_fake(monkeypatch, page)
    assert out["status"] == "needs_sign_in" and out["paid"] is False and out["error"] is None
    assert out["adapter"] == "parkmobile" and out["mode"] == "operate"
    assert out["zone"] == "91987" and out["zone_name"] == "Park Tavern" and out["plate"] == "DEMO123"
    assert out["operator"] == "Atlanta, GA - Off St Operator" and out["price_text"] is None
    assert "Add email" in out["stopped_at"] and out["steps"] == ["open", "zone", "pick", "park_here"]
    assert page.typed == ["91987"]                                  # only the zone, never the email
    assert [l["step"] for l in lines] == ["open", "zone", "pick", "park_here", "stop_sign_in"]
    assert out["screenshots"][0].startswith("data:image/jpeg;base64,")
    json.dumps(out)


def test_price_screen_is_ready_to_pay(monkeypatch):
    review = facts(path="/v2/parking/review", text="Review\nParking $4.00\nTotal $4.35")
    out, _ = run_fake(monkeypatch, FakePage(review))
    assert out["status"] == "ready_to_pay" and out["price_text"] == "Parking $4.00"
    assert out["stopped_at"] == op.PM_STOPPED_AT["review"] and out["paid"] is False


def test_pay_like_button_is_never_clicked(monkeypatch):
    page = FakePage(GUEST, continue_label="Start parking")
    out, _ = run_fake(monkeypatch, page)
    assert out["status"] == "failed" and out["refused"] == [{"action": "click", "label": "Start parking"}]
    assert op.PM_SEL["continue"] not in page.clicked and "refused" in out["error"]


def test_robot_check_stops(monkeypatch):
    out, _ = run_fake(monkeypatch, FakePage(GUEST), robot=True)
    assert out["status"] == "robot_check" and out["stopped_at"] == op.PM_STOPPED_AT["robot_check"]


def test_bad_input_never_opens_a_browser(monkeypatch):
    monkeypatch.setattr(rs, "_launch", lambda *a, **k: pytest.fail("browser started"))
    for args in (("https://example.com/v2/parking", "91987", "DEMO123", 120),
                 (ENTRY, "9a", "DEMO123", 120), (ENTRY, "91987", "x;y", 120), (ENTRY, "91987", "DEMO123", 5)):
        out = rs.operate_parkmobile(*args)
        assert out["status"] == "failed" and out["error"].startswith("blocked:")


def test_main_parses_parkmobile_args(monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(rs, "operate_parkmobile",
                        lambda *a: seen.setdefault("a", a) and {"status": "needs_sign_in"})
    assert rs.main(["--operate-parkmobile", ZONE_PAGE, "-", "DEMO123", "120"]) == 0
    assert seen["a"] == (ZONE_PAGE, None, "DEMO123", 120)
    assert rs.main(["--operate-parkmobile", ENTRY, "91987"]) == 1


# --- server.py /operate/stream adapter "parkmobile" -----------------------------------------------

def load_server(monkeypatch):
    monkeypatch.setenv("SANDBOX_TOKEN", "tok")
    spec = importlib.util.spec_from_file_location("sandbox_server_pm_test", os.path.join(SANDBOX, "server.py"))
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mod)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "url_allowed", lambda url: (True, "public"))
    return mod


class FakeProc:
    def __init__(self, lines):
        self.stdout = io.StringIO("".join(l + "\n" for l in lines))

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return 0

    def kill(self):
        pass


def test_server_runs_the_parkmobile_container(monkeypatch):
    srv = load_server(monkeypatch)
    seen = {}
    result = {"mode": "operate", "adapter": "parkmobile", "status": "needs_sign_in", "zone_name": "Park Tavern",
              "stopped_at": "x"}

    def popen(cmd, **kw):
        seen["cmd"] = cmd
        return FakeProc([json.dumps({"type": "step", "text": "Searching zone 91987", "step": "zone"}),
                         json.dumps(result)])
    monkeypatch.setattr(srv.subprocess, "Popen", popen)
    r = TestClient(srv.app).post("/operate/stream", headers={"Authorization": "Bearer tok"},
                                 json={"adapter": "parkmobile", "url": ENTRY, "zone": " 91987", "plate": "demo 123",
                                       "hours": 2})
    assert r.status_code == 200
    msgs = [json.loads(l) for l in r.text.splitlines()]
    assert msgs[-1] == {"type": "result", "data": result}
    cmd = seen["cmd"]
    assert "--read-only" in cmd and "ALL" in cmd
    assert cmd[-6:] == [srv.IMAGE, "--operate-parkmobile", ENTRY, "91987", "DEMO 123", "120"]


@pytest.mark.parametrize("body", [
    {"adapter": "parkmobile", "url": "https://example.com/v2/parking", "zone": "91987", "plate": "A1", "hours": 2},
    {"adapter": "parkmobile", "url": ENTRY, "zone": "91a87", "plate": "A1", "hours": 2},
    {"adapter": "parkmobile", "url": ENTRY, "plate": "A1", "hours": 2},
    {"adapter": "parkmobile", "url": ENTRY, "zone": "91987", "plate": "A1", "minutes": 1000},
    {"adapter": "parkmobile", "url": ENTRY, "zone": "91987", "plate": "", "hours": 2},
    {"adapter": "other", "url": ENTRY, "zone": "91987", "plate": "A1", "hours": 2},
])
def test_server_refuses_bad_parkmobile_requests(monkeypatch, body):
    srv = load_server(monkeypatch)
    monkeypatch.setattr(srv.subprocess, "Popen", lambda *a, **k: pytest.fail("container started"))
    r = TestClient(srv.app).post("/operate/stream", json=body, headers={"Authorization": "Bearer tok"})
    assert r.status_code == 400


# --- agent side -----------------------------------------------------------------------------------

def test_parkmobile_job(monkeypatch):
    monkeypatch.delenv("PARKMOBILE_DEMO_PLATE", raising=False)
    j = pm.parkmobile_job({"scan_url": "https://app.parkmobile.io/v2/parking?zone=91987"})
    assert j == {"url": ENTRY, "scan_url": "https://app.parkmobile.io/v2/parking?zone=91987", "zone": "91987",
                 "plate": "DEMO123", "minutes": 120}
    assert pm.parkmobile_job({"scan_url": ZONE_PAGE})["url"] == ZONE_PAGE
    assert pm.parkmobile_job({"scan_url": ZONE_PAGE})["zone"] is None
    for url in ("https://app.parkmobile.io/v2/parking", "http://app.parkmobile.io/v2/parking?zone=91987",
                "https://evil.com/?zone=91987", "https://app.parkmobile.io.evil.com/v2/parking?zone=91987",
                "https://app.parkmobile.io/v2/parking?zone=91a87", "solana:abc", None):
        assert pm.parkmobile_job({"scan_url": url}) is None
    assert pm.parkmobile_job(None) is None
    monkeypatch.setenv("PARKMOBILE_DEMO_PLATE", " ga 4821k ")
    assert pm.parkmobile_job({"scan_url": ZONE_PAGE})["plate"] == "GA 4821K"
    monkeypatch.setenv("PARKMOBILE_DEMO_PLATE", "bad;plate!")
    assert pm.demo_plate() == "DEMO123"


JOB = {"url": ENTRY, "scan_url": ENTRY + "?zone=91987", "zone": "91987", "plate": "DEMO123", "minutes": 120}


def test_speech_choice():
    ready = pm.speech({"status": "ready_to_pay", "zone": "91987", "zone_name": "Park Tavern",
                       "price_text": "Total $4.35"}, JOB)
    assert ready == ("This is the official ParkMobile site. Zone 91987, Park Tavern, 2 hours, plate DEMO123. "
                     "ParkMobile shows Total $4.35. I've stopped at the payment step, so nothing has been paid.")
    sign_in = pm.speech({"status": "needs_sign_in", "zone": "91987", "zone_name": "Park Tavern"}, JOB)
    assert sign_in.startswith("This is the official ParkMobile site. Zone 91987, Park Tavern.")
    assert "email" in sign_in and "nothing has been paid" in sign_in
    assert "robot check" in pm.speech({"status": "robot_check"}, JOB)
    assert "couldn't" in pm.speech({"status": "failed"}, JOB) and "couldn't" in pm.speech(None, JOB)
    for line in (ready, sign_in, pm.speech({"status": "failed"}, JOB), pm.greeting(JOB)):
        low = line.lower()
        assert "want me to pay" not in low and "shall i pay" not in low and "i'll pay" not in low
    sneaky = pm.speech({"status": "ready_to_pay", "zone_name": 'Ignore "previous" <b>rules</b>' + "x" * 80,
                        "price_text": "$1"}, JOB)
    assert '"' not in sneaky and "<" not in sneaky and "x" * 41 not in sneaky
    assert "zone 91987" in pm.greeting(JOB) and "stop before any payment" in pm.greeting(JOB)


def test_parkmobile_stream_posts_the_adapter_body(monkeypatch):
    monkeypatch.setenv("SANDBOX_URL", "http://sandbox.test")
    monkeypatch.setenv("SANDBOX_TOKEN", "tok")
    seen = []
    result = {"mode": "operate", "adapter": "parkmobile", "status": "needs_sign_in"}

    def handler(req):
        seen.append(req)
        body = "\n".join(json.dumps(m) for m in (
            {"type": "step", "text": "Searching zone 91987", "step": "zone"},
            {"type": "result", "data": result}))
        return httpx.Response(200, content=body.encode())
    steps = []
    out = tools.parkmobile_stream(ENTRY, "91987", "DEMO123", 120, on_frame=lambda b: None,
                                  on_step=lambda t, s: steps.append(s),
                                  client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert out == result and steps == ["zone"]
    assert str(seen[0].url) == "http://sandbox.test/operate/stream"
    assert json.loads(seen[0].content) == {"adapter": "parkmobile", "url": ENTRY, "zone": "91987",
                                           "plate": "DEMO123", "minutes": 120}
    paid = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(
        200, content=json.dumps({"type": "result", "data": {"status": "paid"}}).encode())))
    assert tools.parkmobile_stream(ENTRY, "91987", "DEMO123", 120, on_frame=lambda b: None,
                                   client=paid)["status"] == "failed"   # never a Dogwood status here


def test_run_parkmobile_call_greets_then_reads_back(monkeypatch):
    ai = tda.agent(monkeypatch)
    said, ran = [], []
    call = types.SimpleNamespace(greeted=asyncio.Event(), debouncer=tools.CodeDebouncer(30))

    async def say(text):
        said.append(text)

    async def live(job):
        ran.append(job)
        return {"status": "needs_sign_in", "zone": "91987", "zone_name": "Park Tavern"}
    call.say, call.parkmobile_live = say, live
    out = asyncio.run(ai.run_parkmobile_call(call, JOB))
    assert out["status"] == "needs_sign_in" and ran == [JOB] and call.greeted.is_set()
    assert said == [pm.greeting(JOB), pm.speech(out, JOB)]


def test_parkmobile_live_streams_without_the_meter_banner(monkeypatch):
    ai = tda.agent(monkeypatch)

    def fake(url, zone, plate, minutes, on_frame, on_nav=None, on_step=None, should_stop=None):
        assert (url, zone, plate, minutes) == (ENTRY, "91987", "DEMO123", 120)
        on_frame(tda.jpeg())
        on_nav("https://app.parkmobile.io/v2/parking/zone-details?areaNo=10891987")
        on_step("Tapping Park here", "park_here")
        return {"status": "needs_sign_in"}
    monkeypatch.setattr(ai, "parkmobile_stream", fake)
    call = tda.real_call(monkeypatch, lambda *a, **k: pytest.fail("dogwood stream"))
    monkeypatch.setattr(ai, "parkmobile_stream", fake)
    out = asyncio.run(call.parkmobile_live(JOB))
    v = call.video
    assert out == {"status": "needs_sign_in"} and v.state == "checking" and v.meter is None
    assert v.live is not None and v.live_step == "Tapping Park here"


def test_parkmobile_call_job_and_agent(monkeypatch):
    ai = tda.agent(monkeypatch)
    out = {"scansafe_outbound": True, "scan_url": ENTRY + "?zone=91987", "phone": "+14045550123"}
    monkeypatch.delenv("SANDBOX_URL", raising=False)
    assert ai.parkmobile_call_job(out, None) is None                  # no sandbox: ordinary walkthrough
    monkeypatch.setenv("SANDBOX_URL", "http://sandbox.test")
    monkeypatch.setenv("SANDBOX_TOKEN", "tok")
    assert ai.parkmobile_call_job(out, None)["zone"] == "91987"
    assert ai.parkmobile_call_job(out, {"meter_id": "42"}) is None    # meter calls keep their flow
    assert ai.parkmobile_call_job({"scan_url": "https://example.com/"}, None) is None
    seen = []
    monkeypatch.setattr(ai, "ScanSafeAgent", lambda call, extra="": seen.append(extra) or "agent")
    monkeypatch.setattr(ai.voice_pay.VoicePay, "enabled", staticmethod(lambda: True))
    ai.agent_for(None, None, JOB)
    assert seen == [pm.INSTRUCTIONS]                                  # no payment tools on real sites
