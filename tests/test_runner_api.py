"""Relay API for the Toolstone helper app (api/routes_runner.py, data/runner_store.py) and the demo
permit form (api/demo_forms.py). Contract: docs/superpowers/specs/2026-11-15-helper-app-contract.md."""
import base64
import hashlib
import json
import logging
import re
import threading
import time

import pytest
from fastapi.testclient import TestClient

from api import demo_forms
from api import main as api_main
from api import session
from data import runner_store as store
from data import tiger_store

AGENT = {"X-Agent-Key": "agent-secret"}
PHONE_A = "+14045550123"
PHONE_B = "+14045559876"
BEARERS = {"tok-a": PHONE_A, "tok-b": PHONE_B}
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 1000 + b"\xff\xd9"
T0 = 1_800_000_000.0


@pytest.fixture
def clock(monkeypatch):
    t = {"now": T0}
    monkeypatch.setattr(store, "now", lambda: t["now"])
    return t


@pytest.fixture
def client(monkeypatch, clock):
    monkeypatch.setenv("AGENT_INTERNAL_KEY", "agent-secret")
    monkeypatch.setenv("ACCOUNT_PEPPER", "test-pepper")
    monkeypatch.delenv("TIGER_DATABASE_URL", raising=False)

    def signed_in(request):
        return BEARERS.get(session.bearer_token(request.headers.get("authorization", "")))
    monkeypatch.setattr(session, "current_phone", signed_in)
    store.reset()
    yield TestClient(api_main.app)
    store.reset()


def person(who="a"):
    return {"Authorization": f"Bearer tok-{who}"}


def runner(token):
    return {"Authorization": f"Runner {token}"}


def pair(client, who="a", name="Vineet's MacBook"):
    r = client.post("/runner/pair", headers=person(who), json={"name": name})
    assert r.status_code == 200, r.text
    body = r.json()
    return body["runner_token"], body["runner_id"]


def connect(client, token):
    r = client.get("/runner/next?wait=0", headers=runner(token))
    assert r.status_code == 200, r.text
    return r.json()


def queue(client, kind="vercel_status", args=None, phone=PHONE_A):
    return client.post("/runner/jobs", headers=AGENT,
                       json={"phone": phone, "kind": kind, "args": {} if args is None else args})


def running_job(client, who="a", kind="vercel_status", args=None):
    token, _ = pair(client, who)
    connect(client, token)
    job_id = queue(client, kind, args, BEARERS[f"tok-{who}"]).json()["job_id"]
    got = connect(client, token)["job"]
    assert got["job_id"] == job_id
    return token, job_id


# --- pairing + status ----------------------------------------------------------------------------

def test_pair_needs_sign_in(client):
    r = client.post("/runner/pair", json={"name": "Laptop"})
    assert r.status_code == 401 and r.json() == {"ok": False, "error": "signed_out",
                                                 "message": "Sign in with your phone number first."}
    assert client.post("/runner/pair", headers={"Authorization": "Bearer nope"}, json={}).status_code == 401
    assert client.get("/runner/status").status_code == 401


def test_pair_returns_token_once_and_stores_only_its_hash(client):
    r = client.post("/runner/pair", headers=person(), json={"name": "Vineet's MacBook"})
    body = r.json()
    assert set(body) == {"runner_token", "runner_id"}
    assert re.fullmatch(r"[0-9a-f]{12}", body["runner_id"]) and len(body["runner_token"]) >= 40
    assert r.headers["cache-control"] == "no-store"
    token = body["runner_token"]
    kept = json.dumps(list(store._by_owner.values())) + json.dumps(store._owner_by_token)
    assert token not in kept and hashlib.sha256(token.encode()).hexdigest() in kept
    assert PHONE_A not in kept                                       # keyed by phone_hash only
    status = client.get("/runner/status", headers=person()).json()
    assert status == {"connected": False, "name": "Vineet's MacBook", "last_seen": None}


def test_second_pair_replaces_the_first(client):
    old, old_id = pair(client, name="Old laptop")
    connect(client, old)
    pending = queue(client).json()["job_id"]                          # queued for the old runner
    new, new_id = pair(client, name="New laptop")
    assert new != old and new_id != old_id
    r = client.get("/runner/next?wait=0", headers=runner(old))
    assert r.status_code == 401 and r.json()["error"] == "bad_runner_token"
    assert connect(client, new) == {"job": None}                      # never sees the old runner's job
    assert client.get(f"/runner/jobs/{pending}", headers=AGENT).json()["status"] == "failed"
    assert client.get(f"/runner/jobs/{pending}", headers=AGENT).json()["error"] == "runner_replaced"
    assert client.get("/runner/status", headers=person()).json()["name"] == "New laptop"


def test_pair_name_is_trimmed_and_defaulted(client):
    pair(client, name="  A\nvery   long " + "x" * 100)
    assert client.get("/runner/status", headers=person()).json()["name"] == ("A very long " + "x" * 100)[:60]
    client.post("/runner/pair", headers=person())                    # no body at all
    assert client.get("/runner/status", headers=person()).json()["name"] == "My computer"
    assert client.post("/runner/pair", headers=person(), json={"name": 5}).status_code == 400


def test_status_connected_and_last_seen(client, clock):
    assert client.get("/runner/status", headers=person()).json() == {"connected": False, "name": None,
                                                                    "last_seen": None}
    token, _ = pair(client)
    connect(client, token)
    assert client.get("/runner/status", headers=person()).json() == {
        "connected": True, "name": "Vineet's MacBook", "last_seen": int(T0)}
    clock["now"] += 45
    assert client.get("/runner/status", headers=person()).json()["connected"] is True
    clock["now"] += 16                                               # 61 s since last seen
    status = client.get("/runner/status", headers=person()).json()
    assert status["connected"] is False and status["last_seen"] == int(T0)
    assert client.get("/runner/status", headers=person("b")).json()["name"] is None   # B has none


# --- agent: creating jobs ------------------------------------------------------------------------

def test_agent_job_create_needs_the_agent_key(client):
    r = client.post("/runner/jobs", json={"phone": PHONE_A, "kind": "vercel_status", "args": {}})
    assert r.status_code == 401
    r = client.post("/runner/jobs", headers={"X-Agent-Key": "wrong"},
                    json={"phone": PHONE_A, "kind": "vercel_status", "args": {}})
    assert r.status_code == 401
    assert client.get("/runner/jobs/0123456789abcdef").status_code == 401
    assert client.get("/runner/jobs/0123456789abcdef/frame").status_code == 401


def test_agent_job_create_errors(client, clock):
    r = queue(client)
    assert r.status_code == 404 and r.json()["error"] == "no_runner"
    token, _ = pair(client)
    r = queue(client)                                                # paired, never connected
    assert r.status_code == 409 and r.json()["error"] == "runner_offline"
    connect(client, token)
    assert queue(client).status_code == 200
    clock["now"] += 61
    r = queue(client)
    assert r.status_code == 409 and r.json() == {
        "ok": False, "error": "runner_offline", "message": "Their computer's helper app isn't running right now."}
    for kind in ("shell", "run_code", "", None, "FORM_FILL"):
        r = queue(client, kind=kind)
        assert r.status_code == 400 and r.json()["error"] == "bad_kind", kind
    assert queue(client, phone="not a phone").json()["error"] == "bad_phone"


def test_agent_job_args_must_be_a_small_object(client):
    token, _ = pair(client)
    connect(client, token)
    for args in (["a"], "x", 5):
        r = client.post("/runner/jobs", headers=AGENT, json={"phone": PHONE_A, "kind": "vercel_status", "args": args})
        assert r.status_code == 400 and r.json()["error"] == "bad_args"
    assert queue(client, args={"project": "x" * 5000}).json()["error"] == "bad_args"
    assert queue(client, args={"project": "x" * 4000}).status_code == 200
    r = client.post("/runner/jobs", headers=AGENT, json={"phone": PHONE_A, "kind": "connections_list"})
    assert r.status_code == 200                                      # args left out = {}
    assert queue(client, "form_fill", {"url": "file:///etc/passwd"}).json()["error"] == "bad_args"
    assert queue(client, "form_fill", {"url": "javascript:alert(1)"}).json()["error"] == "bad_args"
    assert queue(client, "form_fill", {"url": "", "profile": "default"}).status_code == 200
    assert queue(client, "form_fill", {"url": "https://example.com/apply"}).status_code == 200


def test_agent_resolves_the_runner_by_phone_hash(client):
    token, _ = pair(client)
    connect(client, token)
    job_id = queue(client, phone="(404) 555-0123").json()["job_id"]       # same person, other format
    assert connect(client, token)["job"]["job_id"] == job_id
    assert queue(client, phone=PHONE_B).json()["error"] == "no_runner"


def test_form_submit_must_point_at_this_computers_form_fill(client):
    token_a, fill_a = running_job(client, "a", "form_fill", {"url": "https://example.com"})
    token_b, _ = pair(client, "b")
    connect(client, token_b)
    assert queue(client, "form_submit", {"fill_job": "0" * 16}).json()["error"] == "bad_args"
    assert queue(client, "form_submit", {"fill_job": fill_a}, phone=PHONE_B).json()["error"] == "bad_args"
    other = queue(client, "vercel_status").json()["job_id"]
    assert queue(client, "form_submit", {"fill_job": other}).json()["error"] == "bad_args"
    ok = queue(client, "form_submit", {"fill_job": fill_a})
    assert ok.status_code == 200


# --- runner: long-poll -----------------------------------------------------------------------------

def test_next_needs_a_runner_token(client):
    assert client.get("/runner/next?wait=0").status_code == 401
    assert client.get("/runner/next?wait=0", headers={"Authorization": "Runner nope"}).status_code == 401
    assert client.get("/runner/next?wait=0", headers=person()).status_code == 401   # a sign-in isn't a runner


def test_long_poll_returns_the_job_and_marks_it_running(client):
    token, _ = pair(client)
    connect(client, token)
    job_id = queue(client, "vercel_redeploy", {"project": "toolstone-site"}).json()["job_id"]
    assert client.get(f"/runner/jobs/{job_id}", headers=AGENT).json()["status"] == "queued"
    r = client.get("/runner/next?wait=5", headers=runner(token))
    assert r.json() == {"job": {"job_id": job_id, "kind": "vercel_redeploy", "args": {"project": "toolstone-site"}}}
    view = client.get(f"/runner/jobs/{job_id}", headers=AGENT).json()
    assert view == {"job_id": job_id, "kind": "vercel_redeploy", "status": "running", "progress": [],
                    "result": None, "error": None, "frame_seq": 0}
    assert connect(client, token) == {"job": None}                   # handed out once only


def test_long_poll_waits_then_returns_null(client):
    token, _ = pair(client)
    started = time.monotonic()
    assert client.get("/runner/next?wait=0.6", headers=runner(token)).json() == {"job": None}
    assert 0.5 <= time.monotonic() - started < 3
    started = time.monotonic()
    for bad in ("abc", "-4", "nan", "inf"):
        assert client.get(f"/runner/next?wait={bad}", headers=runner(token)).json() == {"job": None}
    assert time.monotonic() - started < 2                            # bad / negative / inf: no wait


def test_long_poll_wakes_for_a_job_created_meanwhile_without_blocking_the_server(client):
    token, _ = pair(client)
    connect(client, token)
    got = {}
    with TestClient(api_main.app) as shared:                          # one event loop for both requests

        def poll():
            got["started"] = time.monotonic()
            got["reply"] = shared.get("/runner/next?wait=10", headers=runner(token)).json()
            got["took"] = time.monotonic() - got["started"]
        t = threading.Thread(target=poll)
        t.start()
        time.sleep(0.4)
        before = time.monotonic()
        assert shared.get("/demo/forms/permit").status_code == 200     # the loop is free while it waits
        assert time.monotonic() - before < 1.5 and t.is_alive()
        job_id = shared.post("/runner/jobs", headers=AGENT,
                             json={"phone": PHONE_A, "kind": "connections_list", "args": {}}).json()["job_id"]
        t.join(timeout=8)
    assert not t.is_alive()
    assert got["reply"]["job"]["job_id"] == job_id and got["took"] < 5


# --- runner: frames, progress, result ----------------------------------------------------------------

def test_frames_size_magic_and_agent_reads_latest(client):
    token, job_id = running_job(client)
    assert client.get(f"/runner/jobs/{job_id}/frame", headers=AGENT).status_code == 204
    url = f"/runner/jobs/{job_id}/frame"
    hdr = {**runner(token), "Content-Type": "image/jpeg"}
    for body in (b"", b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, b"GIF89a"):
        r = client.post(url, headers=hdr, content=body)
        assert r.status_code == 400 and r.json()["error"] == "bad_frame"
    r = client.post(url, headers=hdr, content=b"\xff\xd8" + b"\x00" * (400 * 1024))     # 400 KB + 2 bytes
    assert r.status_code == 413 and r.json()["error"] == "frame_too_large"
    exactly = b"\xff\xd8" + b"\x00" * (400 * 1024 - 2)
    assert client.post(url, headers=hdr, content=exactly).json() == {"ok": True}
    assert client.post(url, headers=hdr, content=JPEG).json() == {"ok": True}
    r = client.get(url, headers=AGENT)
    assert r.status_code == 200 and r.content == JPEG
    assert r.headers["content-type"] == "image/jpeg" and r.headers["x-frame-seq"] == "2"
    assert r.headers["cache-control"] == "no-store"
    assert client.get(f"/runner/jobs/{job_id}", headers=AGENT).json()["frame_seq"] == 2
    assert client.post(url, content=JPEG).status_code == 401           # needs the runner token
    assert client.get("/runner/jobs/0123456789abcdef/frame", headers=AGENT).status_code == 404


def test_progress_is_kept_short_and_capped(client):
    token, job_id = running_job(client)
    url = f"/runner/jobs/{job_id}/progress"
    for i in range(25):
        assert client.post(url, headers=runner(token), json={"note": f"step {i}"}).json() == {"ok": True}
    progress = client.get(f"/runner/jobs/{job_id}", headers=AGENT).json()["progress"]
    assert progress == [f"step {i}" for i in range(5, 25)]
    client.post(url, headers=runner(token), json={"note": "y" * 500})
    assert client.get(f"/runner/jobs/{job_id}", headers=AGENT).json()["progress"][-1] == "y" * 200
    for bad in ({"note": ""}, {"note": 5}, {}):
        assert client.post(url, headers=runner(token), json=bad).status_code == 400
    assert client.post(url, headers=runner(token), content=b"not json").status_code == 400


def test_result_is_stored_and_visible_to_the_agent(client):
    token, job_id = running_job(client)
    url = f"/runner/jobs/{job_id}/result"
    result = {"projects": [{"name": "site", "framework": "nextjs", "url": "site.vercel.app",
                            "latest": {"state": "READY", "url": "site-abc.vercel.app", "created": 1800000000,
                                       "target": "production", "commit_message": "Fix nav", "creator": "vineet"}}]}
    assert client.post(url, headers=runner(token), json={"status": "maybe", "result": {}}).json()["error"] == "bad_status"
    assert client.post(url, headers=runner(token), json={"status": "done", "result": [1]}).json()["error"] == "bad_result"
    big = client.post(url, headers=runner(token), json={"status": "done", "result": {"x": "y" * 17000}})
    assert big.status_code == 413 and big.json()["error"] == "result_too_large"
    assert client.post(url, headers=runner(token), json={"status": "done", "result": result}).json() == {"ok": True}
    view = client.get(f"/runner/jobs/{job_id}", headers=AGENT).json()
    assert view["status"] == "done" and view["result"] == result and view["error"] is None
    again = client.post(url, headers=runner(token), json={"status": "failed", "error": "late"})
    assert again.status_code == 409 and again.json()["error"] == "not_running"

    token2 = token
    job2 = queue(client).json()["job_id"]
    connect(client, token2)
    client.post(f"/runner/jobs/{job2}/result", headers=runner(token2),
                json={"status": "failed", "result": None, "error": "missing_connection:vercel " + "z" * 300})
    view = client.get(f"/runner/jobs/{job2}", headers=AGENT).json()
    assert view["status"] == "failed" and view["error"].startswith("missing_connection:vercel")
    assert len(view["error"]) == 200 and view["result"] is None


def test_a_runner_cannot_touch_another_runners_job(client):
    token_a, job_a = running_job(client, "a")
    token_b, _ = pair(client, "b")
    assert connect(client, token_b) == {"job": None}
    for path, kw in ((f"/runner/jobs/{job_a}/frame", {"content": JPEG}),
                     (f"/runner/jobs/{job_a}/progress", {"json": {"note": "hi"}}),
                     (f"/runner/jobs/{job_a}/result", {"json": {"status": "done", "result": {"x": 1}}})):
        r = client.post(path, headers=runner(token_b), **kw)
        assert r.status_code == 404 and r.json()["error"] == "unknown_job", path
    view = client.get(f"/runner/jobs/{job_a}", headers=AGENT).json()
    assert view["status"] == "running" and view["progress"] == [] and view["frame_seq"] == 0
    assert client.post("/runner/jobs/../../etc/progress", headers=runner(token_a), json={"note": "x"}).status_code == 404
    assert client.post("/runner/jobs/zzz/progress", headers=runner(token_a), json={"note": "x"}).status_code == 404


def test_jobs_are_dropped_after_15_minutes_and_capped(client, clock, monkeypatch):
    token, job_id = running_job(client)
    clock["now"] += 15 * 60 + 1
    assert client.get(f"/runner/jobs/{job_id}", headers=AGENT).status_code == 404
    assert client.post(f"/runner/jobs/{job_id}/progress", headers=runner(token), json={"note": "x"}).status_code == 404
    monkeypatch.setattr(store, "MAX_JOBS", 3)
    monkeypatch.setattr(store, "MAX_QUEUED_PER_RUNNER", 100)
    connect(client, token)
    ids = [queue(client).json()["job_id"] for _ in range(5)]
    assert len(store._jobs) == 3
    assert [client.get(f"/runner/jobs/{i}", headers=AGENT).status_code for i in ids] == [404, 404, 200, 200, 200]


def test_queued_jobs_per_runner_are_limited(client, monkeypatch):
    monkeypatch.setattr(store, "MAX_QUEUED_PER_RUNNER", 2)
    token, _ = pair(client)
    connect(client, token)
    assert queue(client).status_code == 200 and queue(client).status_code == 200
    r = queue(client)
    assert r.status_code == 429 and r.json()["error"] == "too_many_jobs"


def test_phones_and_tokens_never_reach_the_logs(client, caplog):
    caplog.set_level(logging.DEBUG)
    token, job_id = running_job(client)
    client.post(f"/runner/jobs/{job_id}/result", headers=runner(token), json={"status": "done", "result": {}})
    assert "runner job" in caplog.text
    for secret in (token, PHONE_A, "4045550123"):
        assert secret not in caplog.text


# --- Tiger pairing storage -------------------------------------------------------------------------

class FakeTiger:
    """Just enough of the `runners` table: upsert by owner, lookups, last_seen updates."""

    def __init__(self, down=False):
        self.rows, self.sql, self.down = {}, [], down

    def connect(self):
        if self.down:
            raise OSError("db down")
        return FakeConn(self)


class FakeConn:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        pass

    def execute(self, sql, params=()):
        db, s = self.db, " ".join(sql.split())
        db.sql.append((s, params))
        row = None
        if s.startswith("INSERT INTO runners"):
            owner, rid, th, name, created = params
            db.rows[owner] = {"runner_id": rid, "token_hash": th, "owner": owner, "name": name,
                              "created_at": created, "last_seen": None}
        elif s.startswith("SELECT"):
            col = "owner" if "WHERE owner" in s else "token_hash"
            row = next((dict(r) for r in db.rows.values() if r[col] == params[0]), None)
        elif s.startswith("UPDATE runners SET last_seen"):
            for r in db.rows.values():
                if r["runner_id"] == params[1]:
                    r["last_seen"] = params[0]
        return types_cursor(row)


def types_cursor(row):
    class Cursor:
        def fetchone(self):
            return row
    return Cursor()


def _restart():
    """A new process: the memory cache is gone, Tiger still has the pairing."""
    store._by_owner.clear()
    store._owner_by_token.clear()


def test_pairing_goes_to_tiger_and_survives_a_restart(client, monkeypatch, clock):
    db = FakeTiger()
    monkeypatch.setenv("TIGER_DATABASE_URL", "postgres://fake")
    monkeypatch.setattr(tiger_store, "_connect", db.connect)
    token, runner_id = pair(client)
    assert any("CREATE TABLE IF NOT EXISTS runners" in s for s, _ in db.sql)
    (row,) = db.rows.values()
    assert row["runner_id"] == runner_id and row["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in json.dumps([p for _, p in db.sql]) and PHONE_A not in json.dumps([p for _, p in db.sql])

    _restart()
    assert connect(client, token) == {"job": None}                     # token found in Tiger
    assert row["last_seen"] == T0                                       # written back
    _restart()
    assert client.get("/runner/status", headers=person()).json()["connected"] is True

    new, _ = pair(client)
    _restart()
    assert client.get("/runner/next?wait=0", headers=runner(token)).status_code == 401   # replaced in Tiger too
    assert connect(client, new) == {"job": None}


def test_tiger_down_falls_back_to_memory(client, monkeypatch):
    monkeypatch.setenv("TIGER_DATABASE_URL", "postgres://fake")
    monkeypatch.setattr(tiger_store, "_connect", FakeTiger(down=True).connect)
    token, _ = pair(client)
    assert connect(client, token) == {"job": None}
    assert client.get("/runner/status", headers=person()).json()["connected"] is True


# --- demo form -----------------------------------------------------------------------------------

def test_demo_permit_form_page(client):
    r = client.get("/demo/forms/permit")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    page = r.text
    assert "Residential Parking Permit Application" in page and "City of Atlanta" in page
    for fid, label, auto in (("full_name", "Full name", "name"), ("email", "Email", "email"),
                             ("phone", "Phone", "tel"), ("street_address", "Street address", "street-address"),
                             ("city", "City", "address-level2"), ("zip", "ZIP", "postal-code")):
        tag = re.search(rf'<input [^>]*id="{fid}"[^>]*>', page).group(0)
        assert f'autocomplete="{auto}"' in tag and f'name="{fid}"' in tag, fid
        assert re.search(rf'<label for="{fid}">{label}', page), fid
    state = re.search(r'<select id="state"[^>]*>(.*?)</select>', page, re.S)
    assert 'autocomplete="address-level1"' in state.group(0)
    assert '<option value="GA">Georgia</option>' in state.group(1) and state.group(1).count("<option") == 52
    for fid, label in (("license_plate", "License plate"), ("vehicle_make", "Vehicle make"),
                       ("vehicle_model", "Vehicle model"), ("vehicle_color", "Vehicle color")):
        assert re.search(rf'<input [^>]*id="{fid}"', page) and f'<label for="{fid}">{label}' in page
    permit = re.search(r'<select id="permit_type"[^>]*>(.*?)</select>', page, re.S).group(1)
    assert ">Residential<" in permit and ">Visitor<" in permit
    assert re.search(r'<input type="checkbox" id="certify"[^>]*>\s*I certify this information is correct', page)
    assert re.search(r'<button type="submit"[^>]*>Submit</button>', page)
    assert "Application received (demo, nothing was sent)" in page
    assert not re.search(r'(src|href)="https?:', page) and "fetch(" not in page   # no external assets, no network

    csp = r.headers["content-security-policy"]
    for part in ("default-src 'none'", "form-action 'none'", "connect-src 'none'", "frame-ancestors 'none'"):
        assert part in csp
    script = re.search(r"<script>(.*?)</script>", page, re.S).group(1)
    style = re.search(r"<style>(.*?)</style>", page, re.S).group(1)
    sha = lambda text: base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()  # noqa: E731
    assert f"script-src 'sha256-{sha(script)}'" in csp and f"style-src 'sha256-{sha(style)}'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert "noindex" in r.headers["x-robots-tag"] and '<meta name="robots" content="noindex' in page
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "no-referrer"
    assert demo_forms.permit_page().body.decode() == page
