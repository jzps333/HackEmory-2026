"""Plugins API (api/routes_plugins.py + data/plugins_store.py): list, detail, search, the demo
enabled set and install counts. Offline: Typesense and Tiger are unset or mocked."""
import json
import shutil
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from api import main as api_main
from api import plugins_index as pi
from api import routes_plugins
from data import plugins_store, typesense_store

REPO_PLUGINS = Path(__file__).resolve().parent.parent / "plugins"
STARTERS = ["parking", "plugin-finder", "qr-checker", "research", "safe-browser", "solana-pay", "squat-coach", "study-buddy"]

UNVERIFIED = """id: tip-jar
name: Tip jar
summary: Lets callers tip the creator over Solana.
author: someone-new
version: 1
kind: live
runs_on: server
triggers:
  phrases: ["send a tip"]
  qr: false
tools: [speak, screen, solana_pay]
permissions: This plugin asks you to confirm a payment by voice.
instructions: When the caller wants to tip, start a payment.
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "plugins"
    shutil.copytree(REPO_PLUGINS, root)
    monkeypatch.setattr(pi, "PLUGINS_DIR", root)
    monkeypatch.setattr(plugins_store, "PLUGINS_STATE_FILE", str(tmp_path / "state" / "enabled.json"))
    for var in ("TYPESENSE_HOST", "TYPESENSE_API_KEY", "TIGER_DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    plugins_store.reset()
    routes_plugins.reset()
    yield root
    plugins_store.reset()
    routes_plugins.reset()


@pytest.fixture
def client(env):
    return TestClient(api_main.app)


def _add(root: Path, folder: str, text: str, readme: str = "# Tip jar\n") -> None:
    d = root / folder
    d.mkdir()
    (d / "plugin.yaml").write_text(text)
    (d / "README.md").write_text(readme)


def test_list_shows_verified_and_enabled(client, env):
    _add(env, "tip-jar", UNVERIFIED)
    r = client.get("/plugins")
    assert r.status_code == 200
    body = r.json()
    by_id = {p["id"]: p for p in body["plugins"]}
    assert sorted(by_id) == sorted(STARTERS + ["tip-jar"])
    assert all(by_id[i]["verified"] for i in STARTERS)
    assert by_id["tip-jar"]["verified"] is False
    assert "solana_pay" not in by_id["tip-jar"]["effective_tools"]
    assert by_id["solana-pay"]["effective_tools"] == ["speak", "screen", "solana_pay"]
    assert body["enabled"] == STARTERS            # default set: the six starters, not tip-jar
    assert by_id["squat-coach"]["enabled"] is True and by_id["tip-jar"]["enabled"] is False
    assert by_id["squat-coach"]["installs"] == 0
    assert body["skipped"] == {}
    assert "readme" not in by_id["squat-coach"]   # the list stays small; detail has the README


def test_detail_and_404(client):
    r = client.get("/plugins/squat-coach")
    assert r.status_code == 200
    p = r.json()
    assert p["id"] == "squat-coach" and p["name"] == "Squat coach" and p["verified"] is True
    assert p["readme"].strip() and p["permissions"] and p["instructions"]
    assert p["enabled"] is True and p["installs"] == 0
    for bad in ("nope-not-here", "Squat-Coach", "x", "a" * 41, "-leading-dash", "squat-coach.."):
        r = client.get(f"/plugins/{bad}")
        assert r.status_code == 404, bad
        assert r.json()["error"] == "unknown_plugin"
    assert client.get("/plugins/..%2F..%2Fetc").status_code == 404


def test_enable_disable_round_trip_and_counts(client, env):
    state = Path(plugins_store.PLUGINS_STATE_FILE)
    r = client.post("/plugins/squat-coach/disable")
    assert r.status_code == 200
    assert r.json() == {"enabled": [i for i in STARTERS if i != "squat-coach"]}
    assert json.loads(state.read_text()) == [i for i in STARTERS if i != "squat-coach"]
    assert client.get("/plugins").json()["enabled"] == [i for i in STARTERS if i != "squat-coach"]

    r = client.post("/plugins/squat-coach/enable")
    assert r.status_code == 200 and r.json() == {"enabled": STARTERS}
    client.post("/plugins/squat-coach/enable")    # already on: not another install
    by_id = {p["id"]: p for p in client.get("/plugins").json()["plugins"]}
    assert by_id["squat-coach"]["installs"] == 1 and by_id["parking"]["installs"] == 0

    assert client.post("/plugins/nope-not-here/enable").status_code == 404
    assert client.post("/plugins/nope-not-here/disable").status_code == 404
    assert client.post("/plugins/Bad_Id/enable").status_code == 404
    # A random website can't flip the demo agent's plugins; our own sites (CORS list) can.
    assert client.post("/plugins/parking/disable", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/plugins/parking/disable", headers={"Origin": "http://localhost:3000"}).status_code == 200
    assert not list(state.parent.glob("*.tmp"))   # atomic write leaves no temp files behind


def test_search_falls_back_without_typesense(client, env):
    _add(env, "tip-jar", UNVERIFIED)
    r = client.get("/plugins/search", params={"q": "squat"})
    assert r.status_code == 200
    body = r.json()
    assert body["engine"] == "substring"
    assert [p["id"] for p in body["plugins"]][0] == "squat-coach"
    assert client.get("/plugins/search", params={"q": "send a tip"}).json()["plugins"][0]["id"] == "tip-jar"
    assert client.get("/plugins/search", params={"q": "zzzz-nothing"}).json()["plugins"] == []
    everything = client.get("/plugins/search", params={"q": ""}).json()["plugins"]
    assert len(everything) == len(STARTERS) + 1      # starters + tip-jar


def test_search_uses_typesense_and_falls_back_when_it_errors(client, env, monkeypatch):
    monkeypatch.setenv("TYPESENSE_HOST", "https://ts.example.test")
    monkeypatch.setenv("TYPESENSE_API_KEY", "test-key")
    seen, mode = [], {"down": False}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if mode["down"]:
            raise httpx.ConnectError("down")
        if request.url.path == "/collections/plugins" and request.method == "GET":
            return httpx.Response(404, json={})
        if request.url.path == "/collections/plugins/documents/import":
            n = len([ln for ln in request.content.decode().splitlines() if ln.strip()])
            return httpx.Response(200, text="\n".join(['{"success":true}'] * n))
        if request.url.path == "/collections/plugins/documents/search":
            return httpx.Response(200, json={"hits": [{"document": {"id": "gone-plugin"}},
                                                      {"document": {"id": "squat-coach"}}]})
        return httpx.Response(201, json={})

    real = httpx.Client
    monkeypatch.setattr(typesense_store.httpx, "Client",
                        lambda *a, **k: real(*a, **{**k, "transport": httpx.MockTransport(handler)}))
    body = client.get("/plugins/search", params={"q": "sqat"}).json()
    assert body["engine"] == "typesense"
    assert [p["id"] for p in body["plugins"]] == ["squat-coach"]     # stale ids are dropped
    assert ("POST", "/collections") in seen and ("POST", "/collections/plugins/documents/import") in seen
    seen.clear()
    client.get("/plugins/search", params={"q": "sqat"})
    assert ("POST", "/collections/plugins/documents/import") not in seen   # indexed once

    mode["down"] = True
    routes_plugins.reset()
    body = client.get("/plugins/search", params={"q": "squat"}).json()
    assert body["engine"] == "substring" and body["plugins"][0]["id"] == "squat-coach"


def test_plugins_endpoint_survives_a_broken_plugin(client, env):
    _add(env, "broken", "id: [unclosed\n")
    _add(env, "shell-tool", UNVERIFIED.replace("tip-jar", "shell-tool").replace("solana_pay]", "shell]"))
    r = client.get("/plugins")
    assert r.status_code == 200
    body = r.json()
    assert set(body["skipped"]) == {"broken", "shell-tool"}
    assert sorted(p["id"] for p in body["plugins"]) == STARTERS
    assert client.get("/plugins/broken").status_code == 404
    assert client.post("/plugins/broken/enable").status_code == 404
    assert all(p["id"] != "shell-tool" for p in client.get("/plugins/enabled").json()["plugins"])


def test_enabled_feed_has_agent_fields(client, env):
    _add(env, "tip-jar", UNVERIFIED)
    r = client.post("/plugins/tip-jar/enable")                     # unverified: shared agent says no
    assert r.status_code == 403 and r.json()["error"] == "needs_verification"
    feed = client.get("/plugins/enabled").json()["plugins"]
    by_id = {p["id"]: p for p in feed}
    assert sorted(by_id) == sorted(STARTERS)
    for p in feed:
        for key in ("instructions", "permissions", "phrases", "qr", "verified", "effective_tools", "name"):
            assert key in p, (p["id"], key)
        assert p["verified"] is True
    assert by_id["qr-checker"]["qr"] is True and "coach my squats" in by_id["squat-coach"]["phrases"]
    assert by_id["solana-pay"]["effective_tools"] == ["speak", "screen", "solana_pay"]   # verified keeps it

    # Editing a verified plugin after approval: it drops to unverified and leaves the agent's feed.
    (env / "solana-pay" / "README.md").write_text("changed after approval\n")
    ids = {p["id"] for p in client.get("/plugins/enabled").json()["plugins"]}
    assert "solana-pay" not in ids and "squat-coach" in ids


def test_unverified_plugin_in_the_state_file_never_reaches_the_agent(client, env):
    _add(env, "sneaky", UNVERIFIED.replace("tip-jar", "sneaky"))
    plugins_store.set_enabled(STARTERS + ["sneaky"])               # even if it got in somehow
    ids = {p["id"] for p in client.get("/plugins/enabled").json()["plugins"]}
    assert "sneaky" not in ids and ids == set(STARTERS)
    assert client.post("/plugins/sneaky/disable").status_code == 200   # turning it off is always fine


def test_store_never_raises_and_defaults(env, monkeypatch, tmp_path):
    assert plugins_store.get_enabled() == STARTERS                    # no file yet
    Path(plugins_store.PLUGINS_STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(plugins_store.PLUGINS_STATE_FILE).write_text("{not json")
    assert plugins_store.get_enabled() == STARTERS                    # corrupt file: default
    plugins_store.set_enabled(["squat-coach", "squat-coach", "../etc", "parking"])
    assert plugins_store.get_enabled() == ["parking", "squat-coach"]  # deduped, ids only

    # Tiger configured but down: installs are kept in memory, nothing raises.
    monkeypatch.setenv("TIGER_DATABASE_URL", "postgresql://u:p@db.invalid:5432/x")
    from data import tiger_store

    def down():
        raise RuntimeError("db down")

    monkeypatch.setattr(tiger_store, "_connect", down)
    plugins_store.record_install("squat-coach")
    assert plugins_store.install_counts() == {"squat-coach": 1}


def test_reserved_ids_are_rejected():
    import yaml
    base = yaml.safe_load("id: search\nname: n\nsummary: s\nauthor: a\nversion: 1\nkind: live\n"
                          "runs_on: server\ntools: [speak]\npermissions: p\ninstructions: i\n")
    assert any("reserved" in e for e in pi.validate(base, "search"))
