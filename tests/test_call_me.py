"""/call-me (Chert outbound FaceTime) and the agent's outbound greeting trigger. Offline:
LiveKit and Chert are faked."""
import asyncio
import json
import types

import httpx
import pytest
from fastapi.testclient import TestClient

lk = pytest.importorskip("livekit.api")   # the backend uses livekit-api (installed with livekit-agents)

from api import main as api_main  # noqa: E402
from api import routes_call  # noqa: E402

PHONE = "+14045550123"
_real_sleep = asyncio.sleep
ENV = {"SCANSAFE_DEMO_PHONE": PHONE, "CALL_ALLOWED_PHONES": "+14045550999",
       "LIVEKIT_URL": "wss://lk.test", "LIVEKIT_API_KEY": "k", "LIVEKIT_API_SECRET": "s" * 32,
       "CHERT_API_KEY": "ftk_test", "CHERT_PROJECT_ID": "proj", "CHERT_LINE_ID": "line-1",
       "AGENT_NAME": "scansafe-agent"}


@pytest.fixture
def env(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(routes_call, "_last_call_at", 0.0)
    return monkeypatch


# --- fakes -----------------------------------------------------------------------------------

def _participant(identity, kinds, agent=True):
    return types.SimpleNamespace(
        identity=identity,
        kind=lk.ParticipantInfo.Kind.AGENT if agent else lk.ParticipantInfo.Kind.STANDARD,
        tracks=[types.SimpleNamespace(type=t) for t in kinds])


class FakeLK:
    """Stands in for livekit.api.LiveKitAPI; records calls."""
    calls: list = []
    ready_after = 1      # list_participants calls before the agent has audio+video

    def __init__(self, *a, **k):
        FakeLK.calls = []
        self._n = 0
        rec = FakeLK.calls

        async def create_room(req): rec.append(("create_room", req.name))

        async def list_participants(req):
            self._n += 1
            if self._n <= FakeLK.ready_after:
                return types.SimpleNamespace(participants=[_participant("agent-AJ_1", [lk.TrackType.AUDIO])])
            return types.SimpleNamespace(participants=[
                _participant("agent-AJ_1", [lk.TrackType.AUDIO, lk.TrackType.VIDEO])])

        async def update_room_metadata(req): rec.append(("metadata", req.room, req.metadata))
        async def delete_room(req): rec.append(("delete_room", req.room))
        async def create_dispatch(req): rec.append(("dispatch", req.agent_name, req.room, req.metadata))

        self.room = types.SimpleNamespace(create_room=create_room, list_participants=list_participants,
                                          update_room_metadata=update_room_metadata, delete_room=delete_room)
        self.agent_dispatch = types.SimpleNamespace(create_dispatch=create_dispatch)

    async def aclose(self):
        pass


def _chert(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(routes_call.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


@pytest.fixture
def fakes(env, monkeypatch):
    monkeypatch.setattr(lk, "LiveKitAPI", FakeLK)
    monkeypatch.setattr(routes_call.asyncio, "sleep", lambda *_: _real_sleep(0))
    FakeLK.calls = []
    seen = {}

    def handler(req: httpx.Request):
        seen["req"] = req
        return httpx.Response(201, json={"data": {"id": "call-123", "status": "allocated"}})
    _chert(monkeypatch, handler)
    return seen


client = TestClient(api_main.app)


# --- endpoint --------------------------------------------------------------------------------

def test_places_call_in_order(fakes):
    r = client.post("/call-me", json={"url": "https://example.com", "phone": PHONE})
    assert r.status_code == 200, r.text
    assert r.json()["call_id"] == "call-123"
    kinds = [c[0] for c in FakeLK.calls]
    assert kinds == ["create_room", "dispatch", "metadata"]     # dial happens between dispatch and metadata
    _, agent, room, md = FakeLK.calls[1]
    assert agent == "scansafe-agent" and room.startswith("scansafe-out-")
    assert json.loads(md) == {"scansafe_outbound": True, "scan_url": "https://example.com", "phone": PHONE}
    assert json.loads(FakeLK.calls[2][2]) == {"chert_call_id": "call-123"}
    req = fakes["req"]
    body = json.loads(req.content)
    assert str(req.url) == "https://facetime.trychert.com/api/v1/calls"
    assert req.headers["Authorization"] == "Bearer ftk_test" and req.headers["X-Chert-Project-Id"] == "proj"
    assert len(req.headers["Idempotency-Key"]) >= 8
    assert body["direction"] == "outbound" and body["mode"] == "customer_managed"
    assert body["destination"] == PHONE and body["destination_type"] == "phone"
    assert body["media"] == {"audio": True, "video": True} and body["line_id"] == "line-1"
    assert body["remote_participant_identity"] == "agent-AJ_1"      # only once it had audio+video
    assert body["livekit_url"] == "wss://lk.test" and body["participant_token"].count(".") == 2


def test_second_allowlisted_number_ok(fakes):
    assert client.post("/call-me", json={"url": "https://example.com", "phone": "+14045550999"}).status_code == 200


def test_unlisted_number_refused(fakes):
    r = client.post("/call-me", json={"url": "https://example.com", "phone": "+12125550000"})
    assert r.status_code == 403
    assert FakeLK.calls == []          # nothing was created, nobody was rung


@pytest.mark.parametrize("url,phone", [("solana:abc", PHONE), ("", PHONE), ("https://x.com", "4045550123")])
def test_bad_input(fakes, url, phone):
    assert client.post("/call-me", json={"url": url, "phone": phone}).status_code == 400


def test_rate_limited(fakes):
    assert client.post("/call-me", json={"url": "https://example.com", "phone": PHONE}).status_code == 200
    r = client.post("/call-me", json={"url": "https://example.com", "phone": PHONE})
    assert r.status_code == 429


def test_not_configured(env, monkeypatch):
    monkeypatch.delenv("CHERT_LINE_ID")
    r = client.post("/call-me", json={"url": "https://example.com", "phone": PHONE})
    assert r.status_code == 503 and "CHERT_LINE_ID" in r.text


def test_chert_refusal_cleans_up(env, monkeypatch):
    monkeypatch.setattr(lk, "LiveKitAPI", FakeLK)
    monkeypatch.setattr(routes_call.asyncio, "sleep", lambda *_: _real_sleep(0))
    _chert(monkeypatch, lambda req: httpx.Response(403, json={"error": "missing scope facetime:write"}))
    r = client.post("/call-me", json={"url": "https://example.com", "phone": PHONE})
    assert r.status_code == 502 and "facetime:write" in r.text
    assert FakeLK.calls[-1][0] == "delete_room"


def test_agent_never_ready(env, monkeypatch):
    monkeypatch.setattr(lk, "LiveKitAPI", FakeLK)
    monkeypatch.setattr(FakeLK, "ready_after", 10**9)
    monkeypatch.setattr(routes_call, "AGENT_READY_TIMEOUT_S", 0.05)
    _chert(monkeypatch, lambda req: httpx.Response(500))
    r = client.post("/call-me", json={"url": "https://example.com", "phone": PHONE})
    assert r.status_code == 504
    assert FakeLK.calls[-1][0] == "delete_room"


def test_status_proxy(env, monkeypatch):
    _chert(monkeypatch, lambda req: httpx.Response(200, json={"data": {
        "status": "active", "answered": True, "terminal_reason": None,
        "facetime_call_events": [{"type": "ringing"}, {"type": "bridge_ready", "source": "worker"}]}}))
    r = client.get("/call-me/call-123")
    assert r.json() == {"call_id": "call-123", "status": "active", "answered": True,
                        "terminal_reason": None, "events": ["ringing", "bridge_ready"]}
    assert client.get("/call-me/bad id!").status_code in (400, 404)


# --- agent side: when to greet ---------------------------------------------------------------

ai = pytest.importorskip("chert.agent_integration")


def test_outbound_job_parsing():
    assert ai.outbound_job(json.dumps({"scansafe_outbound": True, "scan_url": "https://a.b"}))["scan_url"] == "https://a.b"
    assert ai.outbound_job('{"chert_warm": true}') is None
    assert ai.outbound_job(json.dumps({"chert_call": "x", "media": {"video": True}})) is None
    assert ai.outbound_job("not json") is None and ai.outbound_job(None) is None


def test_bridge_ready_rule():
    ev = [{"type": "bridge_ready", "source": "worker"}]
    assert ai.bridge_ready_in({"status": "active", "facetime_call_events": ev})
    assert not ai.bridge_ready_in({"status": "ringing", "facetime_call_events": ev})
    assert not ai.bridge_ready_in({"status": "active", "facetime_call_events": [{"type": "bridge_ready", "source": "relay"}]})
    assert ai.bridge_ready_in({"status": "active", "facetime_call_events": [{"event_type": "bridge_ready", "source": "worker"}]})


def _poll(seq, room_md='{"chert_call_id": "c1"}'):
    it = iter(seq)

    def handler(req):
        assert req.url.path.endswith("/calls/c1")
        return httpx.Response(200, json={"data": next(it)})
    room = types.SimpleNamespace(metadata=room_md)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await ai.wait_for_outbound_answer(room, timeout=5, client=c)
    return asyncio.run(go())


def test_greets_after_bridge_ready(monkeypatch):
    monkeypatch.setattr(ai.asyncio, "sleep", lambda *_: _real_sleep(0))
    assert _poll([{"status": "allocated"}, {"status": "ringing"},
                  {"status": "active", "facetime_call_events": []},
                  {"status": "active", "facetime_call_events": [{"type": "bridge_ready", "source": "worker"}]}])


@pytest.mark.parametrize("done", ["ended", "failed", "rejected"])
def test_gives_up_when_call_ends(monkeypatch, done):
    monkeypatch.setattr(ai.asyncio, "sleep", lambda *_: _real_sleep(0))
    assert _poll([{"status": "ringing"}, {"status": done}]) is False


def test_no_call_id_gives_up(monkeypatch):
    room = types.SimpleNamespace(metadata="")
    assert asyncio.run(ai.wait_for_outbound_answer(room, timeout=0.3)) is False
