"""Plugin memory + flashcards (data/plugin_memory.py, api/routes_memory.py)."""
import pytest
from fastapi.testclient import TestClient

from api import main as api_main
from api import routes_memory, session
from data import plugin_memory as mem

KEY = {"X-Agent-Key": "agent-secret"}
PHONE = "+14045550123"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AGENT_INTERNAL_KEY", "agent-secret")
    monkeypatch.delenv("TIGER_DATABASE_URL", raising=False)
    monkeypatch.setattr(routes_memory, "_owner", lambda phone: "owner-" + phone[-4:])
    mem.reset()
    yield TestClient(api_main.app)
    mem.reset()


def test_agent_key_is_required(client):
    r = client.post("/plugins/squat-coach/memory/put", json={"phone": PHONE, "key": "note:1", "data": {}})
    assert r.status_code == 401
    r = client.post("/plugins/squat-coach/memory/put", headers={"X-Agent-Key": "wrong"},
                    json={"phone": PHONE, "key": "note:1", "data": {}})
    assert r.status_code == 401


def test_put_and_list_newest_first_scoped_by_plugin_and_person(client):
    for i, note in enumerate(["first", "second"]):
        assert client.post("/plugins/squat-coach/memory/put", headers=KEY,
                           json={"phone": PHONE, "key": f"session:{i}", "data": {"summary": note}}).json() == {"ok": True}
    client.post("/plugins/squat-coach/memory/put", headers=KEY,
                json={"phone": "+14045559999", "key": "session:9", "data": {"summary": "someone else"}})
    recs = client.post("/plugins/squat-coach/memory/list", headers=KEY,
                       json={"phone": "404-555-0123", "prefix": "session:", "limit": 10}).json()["records"]
    assert [r["data"]["summary"] for r in recs] == ["second", "first"]


def test_tool_must_be_listed_and_plugin_verified(client):
    r = client.post("/plugins/plugin-finder/memory/put", headers=KEY,
                    json={"phone": PHONE, "key": "note:1", "data": {}})          # plugin-finder has no memory
    assert r.status_code == 403 and r.json()["error"] == "tool_not_allowed"
    r = client.post("/plugins/squat-coach/flashcards/add", headers=KEY,
                    json={"phone": PHONE, "front": "a", "back": "b"})
    assert r.status_code == 403
    assert client.post("/plugins/nope-nope/memory/list", headers=KEY, json={"phone": PHONE}).status_code == 404


def test_bad_input_is_rejected(client):
    big = {"x": "y" * 5000}
    assert client.post("/plugins/squat-coach/memory/put", headers=KEY,
                       json={"phone": PHONE, "key": "session:1", "data": big}).status_code == 400
    assert client.post("/plugins/squat-coach/memory/put", headers=KEY,
                       json={"phone": PHONE, "key": "../../x y", "data": {}}).status_code == 400
    assert client.post("/plugins/squat-coach/memory/put", headers=KEY,
                       json={"phone": "not a phone", "key": "a", "data": {}}).status_code == 400


def test_flashcards_spaced_repetition(client):
    add = client.post("/plugins/study-buddy/flashcards/add", headers=KEY,
                      json={"phone": PHONE, "front": "Mitochondria", "back": "Powerhouse of the cell"}).json()
    assert add["due"] == 1 and add["total"] == 1
    card = client.post("/plugins/study-buddy/flashcards/next", headers=KEY, json={"phone": PHONE}).json()["card"]
    assert card["front"] == "Mitochondria"
    wrong = client.post("/plugins/study-buddy/flashcards/grade", headers=KEY,
                        json={"phone": PHONE, "card_id": card["id"], "correct": False}).json()
    assert wrong["card"]["interval_s"] == 60 and wrong["due"] == 0
    right = client.post("/plugins/study-buddy/flashcards/grade", headers=KEY,
                        json={"phone": PHONE, "card_id": card["id"], "correct": True}).json()
    assert right["card"]["interval_s"] == 86400 and right["card"]["reps"] == 1
    again = mem.grade_card("study-buddy", "owner-0123", card["id"], True)
    assert again["interval_s"] == 216000                                     # 1 day x 2.5
    assert client.post("/plugins/study-buddy/flashcards/next", headers=KEY,
                       json={"phone": PHONE}).json()["card"] is None
    assert client.post("/plugins/study-buddy/flashcards/grade", headers=KEY,
                       json={"phone": PHONE, "card_id": "zzz", "correct": True}).status_code == 404


def test_my_apps_needs_sign_in_and_shows_only_my_data(client, monkeypatch):
    assert client.get("/me/apps").status_code == 401
    client.post("/plugins/squat-coach/memory/put", headers=KEY,
                json={"phone": PHONE, "key": "session:1", "data": {"cues": ["Go deeper"], "summary": "s"}})
    client.post("/plugins/study-buddy/flashcards/add", headers=KEY, json={"phone": PHONE, "front": "a", "back": "b"})
    client.post("/plugins/squat-coach/memory/put", headers=KEY,
                json={"phone": "+14045559999", "key": "session:1", "data": {"summary": "not mine"}})
    monkeypatch.setattr(session, "current_phone", lambda request: PHONE)
    apps = {a["plugin_id"]: a for a in client.get("/me/apps").json()["apps"]}
    assert set(apps) == {"squat-coach", "study-buddy"}
    assert apps["squat-coach"]["kind"] == "sessions" and apps["study-buddy"]["kind"] == "flashcards"
    one = client.get("/me/apps/squat-coach").json()
    assert one["plugin"]["name"] == "Squat coach" and [r["data"]["summary"] for r in one["records"]] == ["s"]
    assert one["flashcards"] is None
    deck = client.get("/me/apps/study-buddy").json()
    assert deck["flashcards"]["total"] == 1 and deck["records"] == []
