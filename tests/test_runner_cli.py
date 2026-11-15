"""Helper app (runner/): local files, field matching, dispatcher, Vercel client, pairing, run
loop. Offline: every HTTP call goes to an httpx.MockTransport; no browser is launched."""
import json
import os
import stat
import sys
from pathlib import Path

import httpx
import pytest

RUNNER_DIR = Path(__file__).resolve().parents[1] / "runner"
sys.path.insert(0, str(RUNNER_DIR))

import toolstone_runner  # noqa: E402
from toolstone_helper import config, fields, forms, jobs, loop, pairing, relay, vercel  # noqa: E402

RUNNER_TOKEN = "rt_SECRET_runner_token_abcdef123456"
SIGNIN_TOKEN = "st_SECRET_signin_token_zyxw987654"
REQUEST_ID = "req_SECRET_8f3a2b1c"
VERCEL_TOKEN = "vt_SECRET_vercel_token_0123456789"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    h = tmp_path / "toolstone"
    monkeypatch.setenv("TOOLSTONE_HOME", str(h))
    monkeypatch.setenv("TOOLSTONE_API", "https://relay.test")
    return h


def _mode(p: Path) -> int:
    return stat.S_IMODE(os.stat(p).st_mode)


class Recorder:
    """Stands in for JobReporter."""

    def __init__(self):
        self.notes, self.frames, self.results = [], [], []

    def progress(self, note):
        self.notes.append(note)

    def frame(self, jpeg):
        self.frames.append(jpeg)

    def result(self, status, result=None, error=""):
        self.results.append((status, result or {}, error))


class NoBrowser(forms.FormRunner):
    def _ensure_browser(self):
        raise AssertionError("tests must not launch a browser")


def _ctx(transport=None):
    return jobs.Context(forms=NoBrowser(headless=True), vercel_transport=transport)


# --- profile / .env -------------------------------------------------------------------------

def test_profile_command_creates_private_files(home, capsys):
    assert toolstone_runner.main(["profile"]) == 0
    prof, env = home / "profile.json", home / ".env"
    assert _mode(prof) == 0o600 and _mode(env) == 0o600 and _mode(home) == 0o700
    data = json.loads(prof.read_text())
    for k in config.PROFILE_KEYS:
        assert isinstance(data[k], str) and data[k]
    assert data["_demo"] is True and "PLACEHOLDER" in data["_note"]
    text = env.read_text()
    assert "# VERCEL_TOKEN=" in text and "# VERCEL_TEAM_ID=" in text
    assert config.parse_env(text) == {}          # only comments: nothing is connected
    out = capsys.readouterr().out
    assert str(prof) in out and "demo" in out

    prof.write_text('{"name": "Mine"}')            # never overwritten
    os.chmod(prof, 0o644)
    toolstone_runner.main(["profile"])
    assert json.loads(prof.read_text()) == {"name": "Mine"}
    assert _mode(prof) == 0o600                   # but tightened


def test_load_profile_drops_marker_keys_and_derives_names(home):
    config.ensure_profile()
    p = config.load_profile()
    assert "_note" not in p and "_demo" not in p and p["state"] == "GA"
    config.write_private(config.profile_path(), json.dumps({"name": "Sam Q Public", "zip": 30303}))
    p = config.load_profile()
    assert p["first_name"] == "Sam" and p["last_name"] == "Q Public" and p["zip"] == "30303"


def test_env_parser():
    text = """
# comment
   # indented comment
VERCEL_TOKEN=abc123
export VERCEL_TEAM_ID = "team_42"
QUOTED='x # not a comment'
INLINE=value # trailing comment
EMPTY=
not a line
=nokey
# VERCEL_OTHER=hidden
"""
    env = config.parse_env(text)
    assert env == {"VERCEL_TOKEN": "abc123", "VERCEL_TEAM_ID": "team_42",
                   "QUOTED": "x # not a comment", "INLINE": "value", "EMPTY": ""}
    assert config.connections(env) == ["vercel"]
    assert config.connections({"VERCEL_TOKEN": "  "}) == []


def test_connections_list_job_returns_names_only(home):
    config.ensure_env()
    rec = Recorder()
    assert jobs.dispatch({"job_id": "j1", "kind": "connections_list", "args": {}}, rec, _ctx()) == ("done", "")
    assert rec.results == [("done", {"connections": []}, "")]
    config.write_private(config.env_path(), f"VERCEL_TOKEN={VERCEL_TOKEN}\n")
    rec = Recorder()
    jobs.dispatch({"job_id": "j2", "kind": "connections_list", "args": {}}, rec, _ctx())
    assert rec.results == [("done", {"connections": ["vercel"]}, "")]
    assert VERCEL_TOKEN not in json.dumps(rec.results)


# --- field matching -------------------------------------------------------------------------

PROFILE = {"name": "Alex Demo", "first_name": "Alex", "last_name": "Demo",
           "email": "alex.demo@example.com", "phone": "+14045550123",
           "street_address": "123 Demo Street", "city": "Atlanta", "state": "GA", "zip": "30303",
           "license_plate": "DEMO123", "vehicle_make": "Toyota", "vehicle_model": "Corolla",
           "vehicle_color": "Blue"}

STATE_OPTIONS = [{"value": "", "label": "Choose a state"}] + [
    {"value": ab, "label": nm} for ab, nm in fields.US_STATES.items()]


def F(**kw):
    d = {"tag": "input", "type": "text", "name": "", "id": "", "autocomplete": "", "label": "",
         "aria_label": "", "placeholder": "", "options": []}
    d.update(kw)
    return d


@pytest.mark.parametrize("desc,key", [
    # autocomplete first
    (F(autocomplete="name", label="Your legal name"), "name"),
    (F(autocomplete="given-name"), "first_name"),
    (F(autocomplete="family-name"), "last_name"),
    (F(autocomplete="email", type="email"), "email"),
    (F(autocomplete="tel", label="Mobile"), "phone"),
    (F(autocomplete="shipping street-address"), "street_address"),
    (F(autocomplete="section-a billing address-line1"), "street_address"),
    (F(autocomplete="address-level2"), "city"),
    (F(tag="select", autocomplete="address-level1", options=STATE_OPTIONS), "state"),
    (F(autocomplete="postal-code", label="Something odd"), "zip"),
    (F(autocomplete="address-line2", label="Street address line 2"), None),   # never the street
    (F(autocomplete="organization", label="Company name"), None),
    # keywords: label / name / id / aria-label / placeholder
    (F(label="License plate"), "license_plate"),
    (F(name="plateNumber"), "license_plate"),
    (F(label="Driver's license number"), None),
    (F(label="Vehicle make"), "vehicle_make"),
    (F(id="vehicle_model"), "vehicle_model"),
    (F(label="Vehicle colour"), "vehicle_color"),
    (F(placeholder="ZIP code"), "zip"),
    (F(name="postalCode"), "zip"),
    (F(aria_label="City"), "city"),
    (F(label="State / Province"), "state"),
    (F(label="Phone number"), "phone"),
    (F(name="email_address"), "email"),
    (F(label="First name"), "first_name"),
    (F(name="lname"), "last_name"),
    (F(label="Full name"), "name"),
    (F(name="fullname"), "name"),
    (F(label="Street address"), "street_address"),
    (F(label="Address line 2"), None),
    (F(label="Apt / Suite", name="address2"), None),
    (F(label="Business name"), None),
    (F(label="Username"), None),
    (F(label="Permit type", tag="select"), None),
    (F(type="email", label="Where should we write?"), "email"),
])
def test_match_key(desc, key):
    assert not fields.is_sensitive(desc)
    assert fields.match_key(desc) == key


@pytest.mark.parametrize("desc", [
    F(label="Card number"), F(name="cardnumber"), F(autocomplete="cc-number"),
    F(autocomplete="cc-csc", label="Code"), F(label="CVV"), F(placeholder="CVC"),
    F(label="Social Security Number"), F(name="ssn"), F(id="SocialSecurityNumber"),
    F(type="password", label="Email"), F(label="Password"), F(autocomplete="new-password"),
    F(label="IBAN"), F(label="Routing number"), F(label="Account number"),
    F(label="Name on card"), F(type="file", label="Photo of your license plate"),
    F(aria_label="Security code"),
])
def test_sensitive_fields_are_never_matched(desc):
    assert fields.is_sensitive(desc)
    plan = fields.plan_fill([desc], PROFILE)
    assert plan["fill"] == [] and len(plan["skipped"]) == 1


def test_plan_fill_demo_permit_form():
    descs = [
        F(label="Full name", autocomplete="name", name="full_name"),
        F(label="Email", autocomplete="email", type="email"),
        F(label="Phone", autocomplete="tel", type="tel"),
        F(label="Street address", autocomplete="street-address"),
        F(label="City", autocomplete="address-level2"),
        F(tag="select", label="State", autocomplete="address-level1", options=STATE_OPTIONS),
        F(label="ZIP", autocomplete="postal-code"),
        F(label="License plate", name="plate"),
        F(label="Vehicle make", name="make"),
        F(label="Vehicle model", name="model"),
        F(label="Vehicle color", name="color"),
        F(tag="select", label="Permit type", name="permit_type",
          options=[{"value": "residential", "label": "Residential"}]),
        F(type="checkbox", label="I certify this information is correct"),
        F(type="submit", label="Submit"),
        F(type="hidden", name="csrf"),
        F(label="Card number", autocomplete="cc-number"),
    ]
    plan = fields.plan_fill(descs, PROFILE)
    assert [k for _, k in plan["fill"]] == [
        "name", "email", "phone", "street_address", "city", "state", "zip", "license_plate",
        "vehicle_make", "vehicle_model", "vehicle_color"]
    assert plan["missing"] == ["Permit type"]
    assert plan["skipped"] == ["Card number"]
    # missing profile value -> "missing", not filled
    plan = fields.plan_fill([F(label="Vehicle make")], {"name": "x"})
    assert plan == {"fill": [], "missing": ["Vehicle make"], "skipped": []}


def test_choose_option_states_and_plain():
    assert fields.choose_option("state", "GA", STATE_OPTIONS) == "GA"
    assert fields.choose_option("state", "Georgia", STATE_OPTIONS) == "GA"
    by_name = [{"value": nm, "label": nm} for nm in fields.US_STATES.values()]
    assert fields.choose_option("state", "GA", by_name) == "Georgia"
    combo = [{"value": "13", "label": "GA - Georgia"}, {"value": "54", "label": "WV - West Virginia"}]
    assert fields.choose_option("state", "Georgia", combo) == "13"
    assert fields.choose_option("state", "VA", combo) is None       # not West Virginia
    colors = [{"value": "", "label": "Pick"}, {"value": "blu", "label": "Blue"}]
    assert fields.choose_option("vehicle_color", "blue", colors) == "blu"
    assert fields.choose_option("vehicle_color", "Teal", colors) is None


def test_submit_helpers():
    assert fields.should_tick("I certify this information is correct")
    assert fields.should_tick("I agree to the terms")
    assert not fields.should_tick("Send me the marketing newsletter, I agree")
    assert not fields.should_tick("Remember me")
    assert fields.is_submit_text("Submit") and fields.is_submit_text("Submit application")
    assert fields.is_submit_text("Apply") and fields.is_submit_text("send")
    assert not fields.is_submit_text("Send me a code") and not fields.is_submit_text("Cancel")
    before = "Parking permit\nFull name\nSubmit"
    after = "Parking permit\nApplication received (demo, nothing was sent)\nThanks Alex Demo"
    msg = fields.scrub(fields.text_change(before, after), PROFILE)
    assert msg == "Application received (demo, nothing was sent) Thanks [your info]"
    assert fields.scrub("City of Atlanta permit for DEMO123, alex.demo@EXAMPLE.com", PROFILE) == (
        "City of Atlanta permit for [your info], [your info]")
    assert len(fields.text_change("", "x" * 500)) == 200


def test_url_rules():
    for ok in ("http://localhost:8000/form.html", "https://example.com/a?b=1"):
        assert forms.allowed_url(ok)
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "chrome://settings", "ftp://x.com",
                "https://user:pw@example.com/", "about:blank", "", "http://"):
        assert not forms.allowed_url(bad)
    assert forms.public_url("https://x.com/p?token=abc#frag") == "https://x.com/p"


# --- dispatcher -----------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["shell", "exec", "FORM_FILL", "", None, 42, "__class__"])
def test_dispatcher_refuses_unknown_kinds(kind):
    rec = Recorder()
    assert jobs.dispatch({"job_id": "j1", "kind": kind, "args": {"cmd": "rm -rf ~"}}, rec, _ctx()) == (
        "failed", "unknown_kind")
    assert rec.results == [("failed", {}, "unknown_kind")]
    assert rec.notes == [] and rec.frames == []


def test_dispatcher_bad_args_and_never_raises(monkeypatch):
    rec = Recorder()
    assert jobs.dispatch({"job_id": "j1", "kind": "vercel_status", "args": ["x"]}, rec, _ctx())[1] == "bad_args"

    def boom(*a):
        raise RuntimeError("secret page text alex.demo@example.com")
    monkeypatch.setitem(jobs.HANDLERS, "connections_list", boom)
    rec = Recorder()
    assert jobs.dispatch({"job_id": "j2", "kind": "connections_list"}, rec, _ctx()) == (
        "failed", "internal_error:RuntimeError")
    assert "example.com" not in json.dumps(rec.results)


def test_form_jobs_fail_politely_without_browser(home):
    rec = Recorder()
    assert jobs.dispatch({"job_id": "j1", "kind": "form_submit", "args": {"fill_job": "nope"}},
                         rec, _ctx()) == ("failed", "form_not_open")
    rec = Recorder()
    status, err = jobs.dispatch({"job_id": "j2", "kind": "form_fill",
                                 "args": {"url": "http://localhost/x"}}, rec, _ctx())
    assert status == "failed" and err.startswith("missing_profile")
    config.ensure_profile()
    for url in ("file:///etc/passwd", "javascript:alert(1)"):
        rec = Recorder()
        assert jobs.dispatch({"job_id": "j3", "kind": "form_fill", "args": {"url": url}},
                             rec, _ctx()) == ("failed", "bad_url:only_http_https")
    rec = Recorder()
    assert jobs.dispatch({"job_id": "j4", "kind": "form_fill",
                          "args": {"url": "http://localhost/", "profile": "work"}},
                         rec, _ctx())[1] == "unknown_profile"


def test_empty_url_uses_only_the_fixed_osascript(monkeypatch, home):
    config.ensure_profile()
    calls = []

    class Out:
        returncode, stdout = 0, "chrome://newtab/\n"

    monkeypatch.setattr(forms.sys, "platform", "darwin")
    monkeypatch.setattr(forms.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or Out())
    rec = Recorder()
    assert jobs.dispatch({"job_id": "j1", "kind": "form_fill", "args": {"url": ""}}, rec,
                         _ctx()) == ("failed", "bad_url:only_http_https")
    assert calls == [["osascript", "-e",
                      'tell application "Google Chrome" to get URL of active tab of front window']]
    monkeypatch.setattr(forms.sys, "platform", "linux")
    rec = Recorder()
    assert jobs.dispatch({"job_id": "j2", "kind": "form_fill", "args": {}}, rec,
                         _ctx())[1] == "no_url:active_tab_needs_macos"


# --- Vercel ---------------------------------------------------------------------------------

def _vercel_mock(seen, fail=None):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        assert req.headers["Authorization"] == f"Bearer {VERCEL_TOKEN}"
        if fail:
            return fail(req)
        p, q = req.url.path, dict(req.url.params)
        if p == "/v9/projects":
            return httpx.Response(200, json={"projects": [
                {"id": "prj_a", "name": "site-a", "framework": "nextjs",
                 "targets": {"production": {"alias": ["site-a.vercel.app"]}}},
                {"id": "prj_b", "name": "api-b", "framework": None,
                 "alias": [{"domain": "api-b.example.com"}]},
            ]})
        if p == "/v6/deployments":
            created = {"prj_a": 1_700_000_000_000, "prj_b": 1_800_000_000_000}[q["projectId"]]
            return httpx.Response(200, json={"deployments": [{
                "uid": f"dpl_{q['projectId']}", "url": f"{q['projectId']}-x.vercel.app",
                "state": "READY", "created": created, "target": q.get("target", "production"),
                "meta": {"githubCommitMessage": "Fix the header"},
                "creator": {"username": "vineet"}}]})
        if p == "/v13/deployments" and req.method == "POST":
            return httpx.Response(200, json={"id": "dpl_new", "url": "site-a-new.vercel.app",
                                             "readyState": "QUEUED"})
        return httpx.Response(404, json={"error": {"code": "not_found"}})
    return httpx.MockTransport(handler)


def _with_token(team=""):
    body = f"# keys\nVERCEL_TOKEN={VERCEL_TOKEN}\n" + (f"VERCEL_TEAM_ID={team}\n" if team else "")
    config.write_private(config.env_path(), body)


def test_vercel_status_shape(home):
    _with_token(team="team_9")
    seen = []
    rec = Recorder()
    assert jobs.dispatch({"job_id": "j1", "kind": "vercel_status", "args": {}}, rec,
                         _ctx(_vercel_mock(seen))) == ("done", "")
    status, result, err = rec.results[0]
    assert [p["name"] for p in result["projects"]] == ["api-b", "site-a"]     # newest deploy first
    a = result["projects"][1]
    assert a == {"name": "site-a", "framework": "nextjs", "url": "https://site-a.vercel.app",
                 "latest": {"state": "READY", "url": "https://prj_a-x.vercel.app",
                            "created": 1_700_000_000, "target": "production",
                            "commit_message": "Fix the header", "creator": "vineet"}}
    assert result["projects"][0]["url"] == "https://api-b.example.com"
    assert all(r.url.params.get("teamId") == "team_9" for r in seen)
    assert dict(seen[0].url.params) == {"limit": "10", "teamId": "team_9"}
    assert VERCEL_TOKEN not in json.dumps(rec.results)

    rec = Recorder()
    jobs.dispatch({"job_id": "j2", "kind": "vercel_status", "args": {"project": "SITE-A"}}, rec,
                  _ctx(_vercel_mock([])))
    assert [p["name"] for p in rec.results[0][1]["projects"]] == ["site-a"]


def test_vercel_redeploy_body(home):
    _with_token()
    seen = []
    rec = Recorder()
    assert jobs.dispatch({"job_id": "j1", "kind": "vercel_redeploy", "args": {"project": "site-a"}},
                         rec, _ctx(_vercel_mock(seen))) == ("done", "")
    assert rec.results[0][1] == {"deployment": {"id": "dpl_new",
                                                "url": "https://site-a-new.vercel.app",
                                                "state": "QUEUED"}}
    dep_lookup = [r for r in seen if r.url.path == "/v6/deployments"][0]
    assert dict(dep_lookup.url.params) == {"projectId": "prj_a", "limit": "1", "target": "production"}
    post = [r for r in seen if r.method == "POST"][0]
    assert post.url.path == "/v13/deployments" and post.url.params.get("forceNew") == "1"
    assert json.loads(post.content) == {"name": "site-a", "deploymentId": "dpl_prj_a",
                                        "target": "production"}
    assert "teamId" not in post.url.params

    rec = Recorder()
    assert jobs.dispatch({"job_id": "j2", "kind": "vercel_redeploy", "args": {}}, rec,
                         _ctx(_vercel_mock([]))) == ("failed", "project_required")
    rec = Recorder()
    assert jobs.dispatch({"job_id": "j3", "kind": "vercel_redeploy", "args": {"project": "ghost"}},
                         rec, _ctx(_vercel_mock([]))) == ("failed", "project_not_found")


def test_vercel_missing_token(home):
    with pytest.raises(vercel.VercelError, match="missing_connection:vercel"):
        vercel.VercelClient("")
    for kind in ("vercel_status", "vercel_redeploy"):
        rec = Recorder()
        assert jobs.dispatch({"job_id": "j1", "kind": kind, "args": {"project": "x"}}, rec,
                             _ctx(_vercel_mock([]))) == ("failed", "missing_connection:vercel")
    config.ensure_env()                           # commented-out lines only
    rec = Recorder()
    assert jobs.dispatch({"job_id": "j2", "kind": "vercel_status", "args": {}}, rec,
                         _ctx(_vercel_mock([]))) == ("failed", "missing_connection:vercel")


def test_vercel_token_never_in_error_text(home):
    _with_token(team="team_9")

    def leaky(req):   # an upstream error that echoes the token back
        return httpx.Response(403, json={"error": {"code": f"forbidden token {VERCEL_TOKEN}",
                                                   "message": f"Bearer {VERCEL_TOKEN}"}})
    rec = Recorder()
    status, err = jobs.dispatch({"job_id": "j1", "kind": "vercel_status", "args": {}}, rec,
                                _ctx(_vercel_mock([], fail=leaky)))
    assert status == "failed" and err.startswith("vercel_http_403")
    assert VERCEL_TOKEN not in err and VERCEL_TOKEN not in json.dumps(rec.results)

    def down(req):
        raise httpx.ConnectError(f"cannot connect with {VERCEL_TOKEN}", request=req)
    rec = Recorder()
    status, err = jobs.dispatch({"job_id": "j2", "kind": "vercel_status", "args": {}}, rec,
                                _ctx(_vercel_mock([], fail=down)))
    assert err == "vercel_unreachable:ConnectError" and VERCEL_TOKEN not in json.dumps(rec.results)


def test_reporter_scrubs_secrets_before_sending():
    sent = []

    def handler(req):
        sent.append(req.content.decode())
        return httpx.Response(200, json={"ok": True})
    r = relay.Relay("https://relay.test", RUNNER_TOKEN, transport=httpx.MockTransport(handler))
    rep = relay.JobReporter(r, "job_1", [VERCEL_TOKEN, RUNNER_TOKEN])
    rep.progress(f"note {VERCEL_TOKEN}")
    rep.result("failed", {"x": f"Runner {RUNNER_TOKEN}"}, f"err {VERCEL_TOKEN}")
    assert sent and not any(VERCEL_TOKEN in s or RUNNER_TOKEN in s for s in sent)


# --- pairing --------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,phone", [
    ("4045550123", "+14045550123"), ("(404) 555-0123", "+14045550123"),
    ("1 404 555 0123", "+14045550123"), ("+44 20 7946 0958", "+442079460958"),
    ("12345", None), ("+0123456789", None), ("call me", None), ("", None),
])
def test_normalize_phone(raw, phone):
    assert pairing.normalize_phone(raw) == phone


def _relay_mock(seen, verify_after=2):
    state = {"verify": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        body = json.loads(req.content) if req.content else {}
        if req.url.path == "/auth/phone/start":
            assert body == {"phone": "+14045550123"}
            return httpx.Response(200, json={"code": "482913", "request_id": REQUEST_ID,
                                             "line": "+16504444331",
                                             "sms_body": "Hi ScanSafe! My sign-in code is 482913"})
        if req.url.path == "/auth/phone/verify":
            assert body == {"phone": "+14045550123", "request_id": REQUEST_ID}
            state["verify"] += 1
            if state["verify"] < verify_after:
                return httpx.Response(200, json={"verified": False})
            return httpx.Response(200, json={"verified": True, "phone": "+14045550123",
                                             "token": SIGNIN_TOKEN})
        if req.url.path == "/runner/pair":
            assert req.headers["Authorization"] == f"Bearer {SIGNIN_TOKEN}"
            assert body == {"name": "Vineet's MacBook"}
            return httpx.Response(200, json={"runner_token": RUNNER_TOKEN, "runner_id": "a1b2c3d4e5f6"})
        if req.url.path == "/auth/logout":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={"detail": "nope"})
    return httpx.MockTransport(handler)


def test_pair_flow_prints_code_and_saves_token_privately(home):
    seen, out, sleeps = [], [], []
    r = relay.Relay("https://relay.test", transport=_relay_mock(seen, verify_after=3))
    code = pairing.pair_flow(r, "+14045550123", "Vineet's MacBook", out=out.append,
                             sleep=sleeps.append)
    assert code == 0
    text = "\n".join(out)
    assert "Text 482913 to +16504444331" in text
    assert "Hi ScanSafe! My sign-in code is 482913" in text
    for secret in (RUNNER_TOKEN, SIGNIN_TOKEN, REQUEST_ID):
        assert secret not in text
    assert sleeps == [3.0, 3.0, 3.0]                 # polls every 3 s
    saved = home / "runner.json"
    assert _mode(saved) == 0o600
    data = json.loads(saved.read_text())
    assert data["runner_token"] == RUNNER_TOKEN and data["runner_id"] == "a1b2c3d4e5f6"
    assert data["name"] == "Vineet's MacBook" and data["api"] == "https://relay.test"
    assert SIGNIN_TOKEN not in saved.read_text()
    assert [r.url.path for r in seen][-1] == "/auth/logout"   # sign-in token revoked after pairing


def test_pair_flow_times_out_and_reports_errors(home):
    clock = iter(range(0, 10_000, 3))
    out = []
    r = relay.Relay("https://relay.test", transport=_relay_mock([], verify_after=10**9))
    assert pairing.pair_flow(r, "+14045550123", "x", out=out.append, sleep=lambda s: None,
                             clock=lambda: next(clock)) == 1
    assert "Timed out" in out[-1] and not (home / "runner.json").exists()

    def bad_start(req):
        return httpx.Response(400, json={"detail": "phone must be in international format"})
    out = []
    r = relay.Relay("https://relay.test", transport=httpx.MockTransport(bad_start))
    assert pairing.pair_flow(r, "+14045550123", "x", out=out.append, sleep=lambda s: None) == 1
    assert "international format" in out[-1]


def test_status_command(home, capsys):
    assert toolstone_runner.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "Paired: no" in out and "Connections: none" in out
    config.save_runner(RUNNER_TOKEN, "a1b2c3d4e5f6", "Lab Mac", "https://relay.test")
    _with_token()
    config.ensure_profile()
    toolstone_runner.main(["status"])
    out = capsys.readouterr().out
    assert 'Paired: yes, as "Lab Mac"' in out and "Connections: vercel" in out
    assert "demo" in out and RUNNER_TOKEN not in out and VERCEL_TOKEN not in out


# --- run loop -------------------------------------------------------------------------------

def test_run_loop_runs_jobs_and_reconnects(home):
    _with_token()
    seen, out, sleeps = [], [], []
    script = [
        httpx.Response(503, json={"detail": "restarting"}),
        "error",
        httpx.Response(200, json={"job": None}),
        httpx.Response(200, json={"job": {"job_id": "job_1", "kind": "connections_list", "args": {}}}),
        httpx.Response(200, json={"job": {"job_id": "job_2", "kind": "run_shell", "args": {"c": "ls"}}}),
        httpx.Response(200, json={"job": {"job_id": "../../x", "kind": "connections_list"}}),
        httpx.Response(401, json={"detail": "unknown runner"}),
    ]

    def handler(req):
        seen.append(req)
        if req.url.path == "/runner/next":
            assert req.headers["Authorization"] == f"Runner {RUNNER_TOKEN}"
            assert req.url.params["wait"] == "25"
            nxt = script.pop(0)
            if nxt == "error":
                raise httpx.ReadTimeout("slow", request=req)
            return nxt
        return httpx.Response(200, json={"ok": True})

    r = relay.Relay("https://relay.test", RUNNER_TOKEN, transport=httpx.MockTransport(handler))
    code = loop.run_loop(r, _ctx(), secrets_fn=lambda: [RUNNER_TOKEN, VERCEL_TOKEN],
                         out=out.append, sleep=sleeps.append)
    assert code == 2 and "no longer paired" in out[-1]
    assert sleeps == [1.0, 2.0]                     # backoff, reset once connected
    results = {r.url.path: json.loads(r.content) for r in seen if r.url.path.endswith("/result")}
    assert results["/runner/jobs/job_1/result"] == {"status": "done",
                                                    "result": {"connections": ["vercel"]}, "error": ""}
    assert results["/runner/jobs/job_2/result"]["error"] == "unknown_kind"
    assert not any("../" in r.url.raw_path.decode() for r in seen)
    text = "\n".join(out)
    assert "connections_list: done" in text and "unknown kind (refused): failed" in text
    assert "run_shell" not in text
    for s in (RUNNER_TOKEN, VERCEL_TOKEN):
        assert s not in text and not any(s in r.content.decode(errors="ignore") for r in seen)


def test_run_requires_pairing(capsys):
    assert toolstone_runner.main(["run"]) == 1
    assert "isn't paired" in capsys.readouterr().out


def test_fit_result_caps_size():
    big = {"filled": [{"label": "x" * 70, "key": "name"}] * 600, "missing": [], "url": "u"}
    out = relay.fit_result(big)
    assert len(json.dumps(out)) <= relay.MAX_RESULT and out["truncated"] and out["url"] == "u"


# --- Playwright (only when installed; headless, localhost) ----------------------------------

def test_form_fill_and_submit_real_browser(tmp_path, home):
    pytest.importorskip("playwright.sync_api")
    import http.server
    import threading

    (tmp_path / "www").mkdir()
    (tmp_path / "www" / "f.html").write_text("""<!doctype html><title>Permit</title>
<form onsubmit="event.preventDefault();document.getElementById('m').textContent='Application received'">
<label>Full name <input name="full_name" autocomplete="name"></label>
<label>Card number <input name="card"></label>
<label><input type="checkbox" name="ok"> I certify this information is correct</label>
<button type="submit">Submit</button></form><p id="m"></p>""")
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(tmp_path / "www"), **k)  # noqa: E731
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    config.ensure_profile()
    runner = forms.FormRunner(headless=True)
    runner.fill_delay = 0
    try:
        try:
            runner._ensure_browser()
        except forms.JobError as e:
            pytest.skip(f"no chromium: {e.code}")
        ctx = jobs.Context(forms=runner)
        rec = Recorder()
        url = f"http://127.0.0.1:{srv.server_address[1]}/f.html"
        assert jobs.dispatch({"job_id": "f1", "kind": "form_fill", "args": {"url": url}}, rec, ctx) == ("done", "")
        res = rec.results[0][1]
        assert res["filled"] == [{"label": "Full name", "key": "name"}]
        assert res["skipped"] == ["Card number"] and res["submit_found"] is True
        assert "Alex" not in json.dumps(res) and rec.frames
        rec = Recorder()
        assert jobs.dispatch({"job_id": "s1", "kind": "form_submit", "args": {"fill_job": "f1"}}, rec, ctx) == ("done", "")
        assert rec.results[0][1] == {"submitted": True, "message": "Application received"}
    finally:
        runner.close()
        srv.shutdown()
