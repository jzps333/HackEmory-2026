"""Pay a parking meter by the hour: quotes, server-side amounts, payment status, /call-me for
meter codes, the agent's quote-following logic, and the StatusVideo meter/paid screens.
Offline: the Solana RPC, LiveKit and Chert are faked; nothing touches the network."""
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
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from solders.keypair import Keypair
from solders.transaction import Transaction

# chert.status_video / chert.agent_integration import livekit, which a plain test venv doesn't
# have. Stub just enough of it (same stub as test_live_stream.py); the real one wins if installed.
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

from api import main as api_main  # noqa: E402
from api import merchants, meter_pay, recent_scans, result_store, routes_call, solana_pay  # noqa: E402
from api.merchants import KNOWN_MERCHANTS, MERCHANT_METERS, MeterConfig  # noqa: E402
from api.routes_pay import router as pay_router  # noqa: E402
from api.scan import payment_result, parse_solana_pay  # noqa: E402
from api.schema import ScanResult  # noqa: E402
from chert import meter_pay as agent_meter  # noqa: E402
from chert import status_video  # noqa: E402
from chert.status_video import StatusVideo  # noqa: E402

DOGWOOD = KNOWN_MERCHANTS["Dogwood Lot & Meter Co."]
MAGNOLIA = KNOWN_MERCHANTS["Magnolia Diner"]
SCAMMER = str(Keypair().pubkey())
FAKE_SIG = "5" * 88
METER_QR = (f"solana:{DOGWOOD}?amount=0.01&reference={Keypair().pubkey()}"
            "&label=Dogwood%20Lot%20%26%20Meter%20Co.&message=Meter%2042")
FAKE_QR = (f"solana:{SCAMMER}?amount=0.01&reference={Keypair().pubkey()}"
           "&label=Dogwood%20Lot%20%26%20Meter%20Co.&message=Meter%2042")
DINER_QR = f"solana:{MAGNOLIA}?amount=0.005&label=Magnolia%20Diner&message=Table%207"
METER_URL = "https://scansafe-demo-sites.vercel.app/fixtures/meter/index.html"
REAL_CLIENT = httpx.Client


def scanned(qr: str) -> ScanResult:
    """What /scan does for a payment code: the server's own copy, kept in memory."""
    r = payment_result(qr, parse_solana_pay(qr))
    recent_scans.remember(r)
    return r


def scanned_web() -> ScanResult:
    r = ScanResult(scan_id="aaaabbbbcccc", url="https://example.com", verdict="safe",
                   jev_score=0.01, explanation="ok", scanned_at=int(time.time()))
    recent_scans.remember(r)
    return r


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    recent_scans.clear()
    monkeypatch.setattr(result_store, "RESULT_DIR", tmp_path / "results")
    yield
    recent_scans.clear()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(pay_router)
    return TestClient(app)


@pytest.fixture
def wallet(tmp_path, monkeypatch):
    p = tmp_path / "devnet.json"
    p.write_text(json.dumps(list(bytes(Keypair()))))
    monkeypatch.setenv("SOLANA_KEYPAIR_PATH", str(p))
    monkeypatch.setenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")
    return p


def mock_rpc(monkeypatch, send_error: str = "") -> list:
    """Devnet RPC stand-in. Returns the list of (method, params) it was asked for."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        req = json.loads(request.content)
        calls.append((req["method"], req.get("params")))
        if req["method"] == "sendTransaction" and send_error:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1,
                                             "error": {"code": -32002, "message": send_error}})
        result = {"getGenesisHash": solana_pay.DEVNET_GENESIS_HASH, "sendTransaction": FAKE_SIG,
                  "getLatestBlockhash": {"context": {"slot": 1}, "value": {
                      "blockhash": "EkSnNWid2cvwEVnVx9aBqawnmiCNiDgp3gUdkDPTKN1N",
                      "lastValidBlockHeight": 100}}}[req["method"]]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    monkeypatch.setattr(solana_pay.httpx, "Client",
                        lambda *a, **k: REAL_CLIENT(transport=httpx.MockTransport(handler)))
    return calls


def sent_lamports_and_recipient(calls) -> tuple[int, list[str]]:
    params = [p for m, p in calls if m == "sendTransaction"][-1]
    tx = Transaction.from_bytes(base64.b64decode(params[0]))
    return (int.from_bytes(bytes(tx.message.instructions[0].data)[4:12], "little"),
            [str(k) for k in tx.message.account_keys])


# --- merchant config ---------------------------------------------------------------------------

def test_meter_config_and_existing_table_shape():
    assert set(KNOWN_MERCHANTS) == {"Dogwood Lot & Meter Co.", "Magnolia Diner"}
    assert all(isinstance(v, str) for v in KNOWN_MERCHANTS.values())   # old callers still work
    m = MERCHANT_METERS["Dogwood Lot & Meter Co."]
    assert (m.rate_per_hour_sol, m.min_hours, m.max_hours) == (0.01, 1, 4)
    assert m.meter_url == METER_URL
    assert [m.amount_sol(h) for h in range(1, 5)] == [0.01, 0.02, 0.03, 0.04]
    assert m.amount_sol(m.max_hours) <= solana_pay.MAX_SOL
    assert merchants.meter_for("Magnolia Diner") is None and merchants.meter_for("") is None
    assert set(MERCHANT_METERS) <= set(KNOWN_MERCHANTS)


# --- POST /pay/quote and GET /pay/quote/{id} ---------------------------------------------------

def test_quote_happy_path_and_latest_wins(client):
    sid = scanned(METER_QR).scan_id
    r = client.post("/pay/quote", json={"scan_id": sid, "hours": 3})
    assert r.status_code == 200, r.text
    q = r.json()
    assert {k: q[k] for k in ("scan_id", "merchant", "rate_per_hour_sol", "hours", "amount_sol",
                              "min_hours", "max_hours", "meter_url")} == {
        "scan_id": sid, "merchant": "Dogwood Lot & Meter Co.", "rate_per_hour_sol": 0.01,
        "hours": 3, "amount_sol": 0.03, "min_hours": 1, "max_hours": 4, "meter_url": METER_URL}
    assert abs(q["updated_at"] - time.time()) < 5
    assert client.get(f"/pay/quote/{sid}").json() == q
    client.post("/pay/quote", json={"scan_id": sid, "hours": 1})
    assert client.get(f"/pay/quote/{sid}").json()["amount_sol"] == 0.01


def test_quote_unknown_scan_and_missing_quote(client):
    r = client.post("/pay/quote", json={"scan_id": "deadbeef0000", "hours": 2})
    assert r.status_code == 404 and r.json()["error"] == "unknown_scan"
    r = client.get("/pay/quote/deadbeef0000")
    assert r.status_code == 404 and r.json()["error"] == "no_quote"


def test_quote_refuses_non_meter_codes(client):
    web = scanned_web().scan_id
    r = client.post("/pay/quote", json={"scan_id": web, "hours": 2})
    assert r.status_code == 400 and r.json()["error"] == "not_a_payment"
    fake = scanned(FAKE_QR).scan_id
    r = client.post("/pay/quote", json={"scan_id": fake, "hours": 2})
    assert r.status_code == 403 and r.json()["error"] == "merchant_not_verified"
    diner = scanned(DINER_QR).scan_id
    r = client.post("/pay/quote", json={"scan_id": diner, "hours": 2})
    assert r.status_code == 400 and r.json()["error"] == "not_a_meter"
    assert client.get(f"/pay/quote/{diner}").status_code == 404


def test_quote_rechecks_a_stored_scan_that_claims_verified(client):
    r = payment_result(FAKE_QR, parse_solana_pay(FAKE_QR))
    r.payment.merchant_verified = True             # tampered copy: we re-check the wallet
    recent_scans.remember(r)
    assert client.post("/pay/quote", json={"scan_id": r.scan_id, "hours": 1}).status_code == 403


@pytest.mark.parametrize("hours", [0, 5, -1, 2.5, "2", True, None, [2]])
def test_quote_bad_hours(client, hours):
    sid = scanned(METER_QR).scan_id
    r = client.post("/pay/quote", json={"scan_id": sid, "hours": hours})
    assert r.status_code == 400 and r.json()["error"] == "bad_hours"
    assert "1 to 4" in r.json()["message"]


def test_quote_accepts_whole_float_and_result_store_scans(client):
    r = payment_result(METER_QR, parse_solana_pay(METER_QR))
    result_store.save(r)                            # not in memory: e.g. after an API restart
    q = client.post("/pay/quote", json={"scan_id": r.scan_id, "hours": 4.0})
    assert q.status_code == 200 and q.json()["hours"] == 4 and q.json()["amount_sol"] == 0.04


# --- POST /pay for meters: the server sets the amount ------------------------------------------

def test_pay_by_hours_without_a_payment_object(client, wallet, monkeypatch):
    calls = mock_rpc(monkeypatch)
    sid = scanned(METER_QR).scan_id
    r = client.post("/pay", json={"scan_id": sid, "hours": 3, "approved": True})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["amount_sol"] == 0.03 and j["hours"] == 3 and j["payment"]["amount_sol"] == 0.03
    assert j["signature"] == FAKE_SIG and j["explorer_url"].endswith("?cluster=devnet")
    lamports, keys = sent_lamports_and_recipient(calls)
    assert lamports == 30_000_000 and DOGWOOD in keys


def test_client_amount_and_recipient_are_ignored(client, wallet, monkeypatch):
    calls = mock_rpc(monkeypatch)
    sid = scanned(METER_QR).scan_id
    lying = parse_solana_pay(METER_QR).model_dump() | {"amount_sol": 0.5, "recipient": SCAMMER,
                                                        "merchant_verified": True}
    r = client.post("/pay", json={"scan_id": sid, "payment": lying, "hours": 2, "approved": True})
    assert r.status_code == 200, r.text
    lamports, keys = sent_lamports_and_recipient(calls)
    assert lamports == 20_000_000                   # rate x hours, not the client's 0.5
    assert DOGWOOD in keys and SCAMMER not in keys  # the server's own scan wins


def test_client_amount_ignored_even_without_a_server_scan(client, wallet, monkeypatch):
    calls = mock_rpc(monkeypatch)
    p = parse_solana_pay(METER_QR).model_dump() | {"amount_sol": 0.04}
    r = client.post("/pay", json={"scan_id": "not-on-server", "payment": p, "hours": 1,
                                  "approved": True})
    assert r.status_code == 200, r.text
    assert r.json()["amount_sol"] == 0.01 and r.json()["hours"] == 1
    assert sent_lamports_and_recipient(calls)[0] == 10_000_000


def test_meter_pay_requires_hours_and_never_uses_the_quote(client, wallet, monkeypatch):
    calls = mock_rpc(monkeypatch)
    sid = scanned(METER_QR).scan_id
    # Anyone with the scan_id can set the quote; /pay must not pick its hours up.
    client.post("/pay/quote", json={"scan_id": sid, "hours": 4})
    for extra in ({}, {"hours": None}):
        r = client.post("/pay", json={"scan_id": sid, "approved": True, **extra})
        assert r.status_code == 400 and r.json()["error"] == "hours_required"
        assert r.json()["message"].startswith("hours is required")
    p = parse_solana_pay(METER_QR).model_dump()
    r = client.post("/pay", json={"scan_id": "not-on-server", "payment": p, "approved": True})
    assert r.status_code == 400 and r.json()["error"] == "hours_required"
    assert calls == []
    assert client.get(f"/pay/status/{sid}").json()["state"] == "none"
    r = client.post("/pay", json={"scan_id": sid, "hours": 2, "approved": True})   # what the user confirmed
    assert r.status_code == 200 and r.json()["hours"] == 2
    assert sent_lamports_and_recipient(calls)[0] == 20_000_000                    # not the quote's 4 h


def test_pay_refusals_send_nothing(client, wallet, monkeypatch):
    calls = mock_rpc(monkeypatch)
    sid = scanned(METER_QR).scan_id
    for hours in (0, 5, 1.5, "3"):
        r = client.post("/pay", json={"scan_id": sid, "hours": hours, "approved": True})
        assert r.status_code == 400 and r.json()["error"] == "bad_hours"
    r = client.post("/pay", json={"scan_id": sid, "hours": 2})                 # not approved
    assert r.status_code == 403 and r.json()["error"] == "not_approved"
    r = client.post("/pay", json={"scan_id": "deadbeef0000", "hours": 2, "approved": True})
    assert r.status_code == 404 and r.json()["error"] == "unknown_scan"
    r = client.post("/pay", json={"scan_id": scanned_web().scan_id, "approved": True})
    assert r.status_code == 400 and r.json()["error"] == "not_a_payment"
    r = client.post("/pay", json={"scan_id": scanned(FAKE_QR).scan_id, "hours": 1, "approved": True})
    assert r.status_code == 403 and r.json()["error"] == "merchant_not_verified"
    assert calls == []
    assert client.get(f"/pay/status/{sid}").json() == {"scan_id": sid, "state": "none"}


def test_meter_price_still_hits_the_cap(client, wallet, monkeypatch):
    calls = mock_rpc(monkeypatch)
    monkeypatch.setitem(MERCHANT_METERS, "Dogwood Lot & Meter Co.",
                        MeterConfig(0.02, 1, 4, METER_URL, "42"))
    sid = scanned(METER_QR).scan_id
    r = client.post("/pay", json={"scan_id": sid, "hours": 3, "approved": True})   # 0.06 SOL
    assert r.status_code == 400 and r.json()["error"] == "over_cap"
    assert [m for m, _ in calls] == []
    st = client.get(f"/pay/status/{sid}").json()
    assert st["state"] == "failed" and st["error"] == "over_cap"


def test_fixed_amount_codes_keep_their_qr_amount(client, wallet, monkeypatch):
    calls = mock_rpc(monkeypatch)
    sid = scanned(DINER_QR).scan_id
    r = client.post("/pay", json={"scan_id": sid, "hours": 4, "approved": True})   # hours ignored
    assert r.status_code == 200, r.text
    assert r.json()["amount_sol"] == 0.005 and r.json()["hours"] is None
    assert sent_lamports_and_recipient(calls)[0] == 5_000_000
    sid2 = scanned(DINER_QR).scan_id
    r = client.post("/pay", json={"scan_id": sid2, "approved": True})              # and not required
    assert r.status_code == 200 and r.json()["amount_sol"] == 0.005


# --- GET /pay/status/{id} ----------------------------------------------------------------------

def test_status_after_pay_and_no_double_pay(client, wallet, monkeypatch):
    calls = mock_rpc(monkeypatch)
    sid = scanned(METER_QR).scan_id
    assert client.get(f"/pay/status/{sid}").json() == {"scan_id": sid, "state": "none"}
    assert client.post("/pay", json={"scan_id": sid, "hours": 2, "approved": True}).status_code == 200
    st = client.get(f"/pay/status/{sid}").json()
    assert st == {"scan_id": sid, "state": "paid", "signature": FAKE_SIG,
                  "explorer_url": solana_pay.explorer_url(FAKE_SIG), "amount_sol": 0.02,
                  "hours": 2, "merchant": "Dogwood Lot & Meter Co."}
    n = len(calls)
    r = client.post("/pay", json={"scan_id": sid, "hours": 2, "approved": True})   # double tap
    assert r.status_code == 409 and r.json()["error"] == "already_paid"
    assert len(calls) == n


def test_status_failed_then_paid(client, wallet, monkeypatch):
    mock_rpc(monkeypatch, send_error="Transaction simulation failed: insufficient lamports")
    sid = scanned(METER_QR).scan_id
    r = client.post("/pay", json={"scan_id": sid, "hours": 1, "approved": True})
    assert r.status_code == 503 and r.json()["error"] == "payer_unfunded"
    st = client.get(f"/pay/status/{sid}").json()
    assert st["state"] == "failed" and st["error"] == "payer_unfunded" and "signature" not in st
    mock_rpc(monkeypatch)                           # topped up: trying again works
    assert client.post("/pay", json={"scan_id": sid, "hours": 1, "approved": True}).status_code == 200
    assert client.get(f"/pay/status/{sid}").json()["state"] == "paid"


def test_payment_in_progress_is_refused(client, wallet, monkeypatch):
    mock_rpc(monkeypatch)
    sid = scanned(METER_QR).scan_id
    meter_pay.begin_payment(sid)                    # another request is sending right now
    r = client.post("/pay", json={"scan_id": sid, "hours": 1, "approved": True})
    assert r.status_code == 409 and r.json()["error"] == "payment_in_progress"
    meter_pay.finish_payment(sid, {})
    assert client.post("/pay", json={"scan_id": sid, "hours": 1, "approved": True}).status_code == 200


def test_routes_are_mounted_on_the_real_app():
    real = TestClient(api_main.app)
    assert real.get("/pay/status/abc").json() == {"scan_id": "abc", "state": "none"}
    assert real.get("/pay/quote/abc").json()["error"] == "no_quote"
    assert real.post("/pay/quote", json={"scan_id": "abc", "hours": 1}).json()["error"] == "unknown_scan"


# --- /call-me for meter codes ------------------------------------------------------------------

PHONE = "+14045550123"
CALL_ENV = {"SCANSAFE_DEMO_PHONE": PHONE, "LIVEKIT_URL": "wss://lk.test", "LIVEKIT_API_KEY": "k",
            "LIVEKIT_API_SECRET": "s" * 32, "CHERT_API_KEY": "ftk_test",
            "CHERT_PROJECT_ID": "proj", "CHERT_LINE_ID": "line-1"}


@pytest.fixture
def calls(monkeypatch, tmp_path):
    """/call-me with place_call faked: returns the (url, phone, extra) it was asked to place."""
    for k, v in CALL_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(routes_call, "_last_call_at", 0.0)
    monkeypatch.setattr(routes_call, "CONSENT_FILE", str(tmp_path / "consent.json"))
    placed = []

    async def fake_place_call(url, phone, extra=None):
        placed.append((url, phone, extra))
        return {"call_id": "call-1", "room": "scansafe-out-x", "status": "allocated"}

    monkeypatch.setattr(routes_call, "place_call", fake_place_call)
    return placed


call_client = TestClient(api_main.app)


def call_me(body: dict):
    routes_call._last_call_at = 0.0
    return call_client.post("/call-me", json={"phone": PHONE, **body})


def test_call_me_accepts_a_verified_meter_code_with_the_apps_scan(calls):
    sid = scanned(METER_QR).scan_id
    r = call_me({"url": METER_QR, "scan_id": sid})
    assert r.status_code == 200, r.text
    assert r.json() == {"call_id": "call-1", "room": "scansafe-out-x", "status": "allocated",
                        "scan_id": sid}
    url, phone, extra = calls[-1]
    assert url == METER_QR and phone == PHONE
    assert extra["scan_id"] == sid and extra["meter_url"] == METER_URL
    assert extra["meter"] == {"merchant": "Dogwood Lot & Meter Co.", "rate_per_hour_sol": 0.01,
                              "min_hours": 1, "max_hours": 4, "meter_url": METER_URL,
                              "meter_id": "42", "spoken_name": "Dogwood Lot and Meter"}
    job = {"scansafe_outbound": True, "scan_url": url, "phone": phone, **extra}
    m = agent_meter.meter_job(json.loads(json.dumps(job)))    # what the agent will read
    assert m["scan_id"] == sid and m["meter_url"] == METER_URL and m["max_hours"] == 4


def test_call_me_meter_code_without_scan_id_gets_a_server_scan(calls, client):
    r = call_me({"url": METER_QR})
    assert r.status_code == 200, r.text
    sid = r.json()["scan_id"]
    assert calls[-1][2]["scan_id"] == sid
    assert client.post("/pay/quote", json={"scan_id": sid, "hours": 2}).status_code == 200


def test_call_me_web_links_are_unchanged(calls):
    r = call_me({"url": "https://example.com"})
    assert r.status_code == 200 and "scan_id" not in r.json()
    assert calls[-1] == ("https://example.com", PHONE, None)


@pytest.mark.parametrize("url", [FAKE_QR, DINER_QR, "solana:abc", f"solana:{DOGWOOD}",
                                 "javascript:alert(1)", "tel:+14045550123", "ftp://x.example/a"])
def test_call_me_refuses_other_codes(calls, url):
    r = call_me({"url": url})
    assert r.status_code == 400 and "verified parking meter" in r.json()["detail"]
    assert calls == []


def test_call_me_checks_the_scan_id(calls):
    r = call_me({"url": METER_QR, "scan_id": "deadbeef0000"})
    assert r.status_code == 404
    other = scanned(DINER_QR).scan_id
    r = call_me({"url": METER_QR, "scan_id": other})
    assert r.status_code == 400 and "different code" in r.json()["detail"]
    assert calls == []


# --- agent: what it says, and the pure quote-following logic -----------------------------------

METER = {"merchant": "Dogwood Lot & Meter Co.", "rate_per_hour_sol": 0.01, "min_hours": 1,
         "max_hours": 4, "meter_url": METER_URL, "meter_id": "42",
         "spoken_name": "Dogwood Lot and Meter", "scan_id": "abc123abc123", "scan_url": METER_QR}


def test_agent_lines():
    assert agent_meter.greeting(METER) == (
        "Hi, this is ScanSafe. You scanned a parking meter code. It belongs to Dogwood Lot and "
        "Meter, and it's their real wallet. It costs 0.01 test SOL per hour.")
    assert agent_meter.hours_line(2, 0.02) == "Okay, 2 hours, 0.02 SOL."
    assert agent_meter.hours_line(1, 0.01) == "Okay, 1 hour, 0.01 SOL."
    assert agent_meter.hours_line(3, 0.01 * 3) == "Okay, 3 hours, 0.03 SOL."   # no float noise
    assert agent_meter.paid_line(2, "42") == "Paid. 2 hours on meter 42. Your receipt is in the app."


def test_meter_view_url_and_job_parsing():
    assert agent_meter.meter_view_url(METER_URL, 3) == METER_URL + "?hours=3"
    assert agent_meter.meter_view_url(METER_URL + "?hours=1&z=9", 2).endswith("?z=9&hours=2")
    job = {"scansafe_outbound": True, "scan_url": METER_QR, "scan_id": "abc", "meter_url": METER_URL,
           "meter": {k: v for k, v in METER.items() if k not in ("scan_id", "scan_url")}}
    assert agent_meter.meter_job(job)["scan_id"] == "abc"
    assert agent_meter.meter_job({**job, "scan_url": "https://example.com"}) is None
    assert agent_meter.meter_job({**job, "scan_id": ""}) is None
    assert agent_meter.meter_job({**job, "meter": None}) is None
    assert agent_meter.meter_job({**job, "meter_url": "javascript:x"}) is None
    assert agent_meter.meter_job({"scansafe_outbound": True, "scan_url": "https://a.b"}) is None
    assert agent_meter.meter_job(None) is None


def test_quote_hours_sanity():
    assert agent_meter.quote_hours({"hours": 3}, METER) == 3
    for q in (None, {}, {"hours": 9}, {"hours": 0}, {"hours": "2"}, {"hours": True}, []):
        assert agent_meter.quote_hours(q, METER) is None


def test_follower_debounces_and_respects_stop():
    f = agent_meter.QuoteFollower(1, debounce_s=2.0)
    f.observe(1, 0.0)
    assert f.due(5.0) is None                       # nothing changed
    f.observe(2, 10.0)
    assert f.due(11.0) is None                      # not settled yet
    f.observe(3, 11.5)                              # rapid change: the clock restarts
    assert f.due(13.0) is None
    f.observe(3, 13.0)
    assert f.due(13.6) == 3 and f.shown == 3        # one announcement, for the final value
    assert f.due(20.0) is None
    f.observe(4, 21.0)
    f.observe(3, 22.0)                              # changed back before settling: silent
    assert f.due(30.0) is None
    assert f.on_status({"state": "none"}) is None
    assert f.on_status({"state": "paid", "hours": 3})["hours"] == 3
    assert f.on_status({"state": "paid"}) is None   # only once
    f.observe(2, 31.0)
    assert f.due(40.0) is None                      # nothing after paid

    g = agent_meter.QuoteFollower(1)
    g.observe(2, 0.0)
    g.stop()
    assert g.due(10.0) is None and g.on_status({"state": "paid"}) is None


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    async def sleep(self, s):
        for _ in range(10):                         # let spawned speech / live views run first
            await asyncio.sleep(0)
        self.t += s


def make_flow(quotes, statuses, *, on_fetch=None):
    """quotes/statuses: functions of fake time -> dict or None. Returns (flow, record)."""
    clock = FakeClock()
    rec = {"said": [], "live": [], "paid": [], "active": 0, "max_active": 0}

    async def say(text):
        rec["said"].append((round(clock.t, 2), text))

    async def show_live(url, hours, amount):
        rec["active"] += 1
        rec["max_active"] = max(rec["max_active"], rec["active"])
        rec["live"].append((url, hours, amount))
        try:
            await asyncio.Event().wait()            # a live view runs until replaced
        finally:
            for _ in range(3):                      # hanging up the stream takes a moment
                await asyncio.sleep(0)
            rec["active"] -= 1

    async def fetch_quote(_sid):
        if on_fetch:
            on_fetch(clock.t)
        return quotes(clock.t)

    async def fetch_status(_sid):
        return statuses(clock.t)

    flow = agent_meter.MeterPayFlow(METER, say=say, show_live=show_live,
                                    show_paid=lambda h, a: rec["paid"].append((h, a)),
                                    fetch_quote=fetch_quote, fetch_status=fetch_status,
                                    clock=clock, sleep=clock.sleep, max_s=60)
    return flow, rec, clock


async def start(flow):
    await flow.render(await flow.initial_hours())
    await flow.run()


def test_flow_follows_hours_then_paid():
    def quotes(t):
        if t < 3:
            return None if t < 1 else {"hours": 1}
        return {"hours": 2} if t < 3.6 else {"hours": 3}     # 1 -> 2 -> 3 within the debounce

    def statuses(t):
        return {"state": "paid", "hours": 3, "amount_sol": 0.03} if t >= 12 else {"state": "none"}

    flow, rec, _ = make_flow(quotes, statuses)
    asyncio.run(start(flow))
    lines = [text for _, text in rec["said"]]
    assert lines == ["Okay, 3 hours, 0.03 SOL.", "Paid. 3 hours on meter 42. Your receipt is in the app."]
    said_at = rec["said"][0][0]
    assert 5.0 <= said_at <= 7.0                    # ~2 s after the last change (t=3.6), not per poll
    assert [h for _, h, _ in rec["live"]] == [1, 3]
    assert rec["live"][0][0] == METER_URL + "?hours=1" and rec["live"][1][0] == METER_URL + "?hours=3"
    assert rec["max_active"] == 1                   # never two live views at once
    assert rec["active"] == 0                       # the paid screen replaced the live view
    assert rec["paid"] == [(3, 0.03)]


def test_flow_starts_at_the_apps_current_hours():
    flow, rec, _ = make_flow(lambda t: {"hours": 2},
                             lambda t: {"state": "paid", "hours": 2, "amount_sol": 0.02} if t > 4 else None)
    asyncio.run(start(flow))
    assert rec["live"][0][1] == 2
    assert [t for _, t in rec["said"]] == ["Paid. 2 hours on meter 42. Your receipt is in the app."]


def test_flow_many_quick_changes_never_overlap_live_views():
    def quotes(t):
        return {"hours": 1 + int(t / 2.5) % 4}       # a new value every 2.5 s

    flow, rec, _ = make_flow(quotes, lambda t: {"state": "paid", "hours": 4, "amount_sol": 0.04}
                             if t > 30 else None)
    asyncio.run(start(flow))
    assert len(rec["live"]) >= 5 and rec["max_active"] == 1


def test_stop_silences_everything():
    state = {"flow": None}

    def on_fetch(t):
        if t >= 2.5 and not state["flow"].stopped:
            state["flow"].stop()                    # the caller said "stop"

    flow, rec, clock = make_flow(lambda t: {"hours": 1 if t < 2 else 4},
                                 lambda t: {"state": "paid", "hours": 4, "amount_sol": 0.04},
                                 on_fetch=on_fetch)
    state["flow"] = flow
    flow._fetch_status = lambda _sid: _none()       # not paid yet when stop comes

    async def _none():
        return None

    async def go():
        await flow.render(1)
        await flow.run()
        # Even if hours change and the payment lands later, a stopped flow does nothing.
        await flow.render(3)
        await flow.say("should not be said")
        await clock.sleep(5)

    asyncio.run(go())
    assert rec["said"] == [] and rec["paid"] == []
    assert [h for _, h, _ in rec["live"]] == [1]


def test_paid_wins_over_a_pending_change():
    flow, rec, _ = make_flow(lambda t: {"hours": 1 if t < 1 else 2},
                             lambda t: {"state": "paid", "hours": 1, "amount_sol": 0.01} if t >= 1.5 else None)
    asyncio.run(start(flow))
    assert [t for _, t in rec["said"]] == ["Paid. 1 hour on meter 42. Your receipt is in the app."]
    assert rec["paid"] == [(1, 0.01)]


# --- agent: ScanSafeCall wiring ----------------------------------------------------------------

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


def jpeg(size=(390, 844), color=(10, 120, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG", quality=90)
    return buf.getvalue()


def make_call(monkeypatch, fake_stream):
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    from chert import agent_integration as ai
    monkeypatch.setattr(ai, "scan_url_stream", fake_stream)
    call = ai.ScanSafeCall.__new__(ai.ScanSafeCall)
    call.session = types.SimpleNamespace(interrupt=lambda: None)
    call.video = make_video()
    call._inflight, call._results = {}, {}
    call.generation = 0
    return call


PAGE = {"verdict": "suspicious", "screenshots": ["data:image/jpeg;base64," +
                                                 base64.b64encode(jpeg(color=(250, 250, 250))).decode()]}


def test_meter_live_shows_the_page_without_a_verdict(monkeypatch):
    def fake(url, on_frame, on_nav=None, should_stop=None):
        assert url.endswith("?hours=2")
        on_frame(jpeg())
        return PAGE

    call = make_call(monkeypatch, fake)
    url = agent_meter.meter_view_url(METER_URL, 2)
    out = asyncio.run(call.meter_live(url, 2, 0.02))
    assert out == PAGE
    v = call.video
    assert v.state == "meter" and v.meter["hours"] == 2 and v.meter["amount"] == 0.02
    assert v.shot is not None and v.live is None    # the page picture, not "Be careful"


def test_meter_live_cancel_waits_for_the_stream_to_hang_up(monkeypatch):
    hung_up = threading.Event()

    def fake(url, on_frame, on_nav=None, should_stop=None):
        on_frame(jpeg())
        deadline = time.monotonic() + 5
        while not should_stop() and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.05)                            # closing the stream takes a moment
        hung_up.set()
        return None

    call = make_call(monkeypatch, fake)

    async def go():
        task = asyncio.create_task(call.meter_live(METER_URL + "?hours=1", 1, 0.01))
        for _ in range(300):
            if call.video.live is not None:
                break
            await asyncio.sleep(0.01)
        assert call.video.live is not None and call.video.meter["hours"] == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert hung_up.is_set()                     # the old stream was closed before we moved on

    asyncio.run(go())


def test_stop_also_stops_the_meter_flow_and_camera_skips_the_meter_code(monkeypatch):
    call = make_call(monkeypatch, lambda *a, **k: None)
    flow, _, _ = make_flow(lambda t: None, lambda t: None)
    call.meter_flow = flow
    call.stop()
    assert flow.stopped and flow.follower.stopped
    call.ignore_codes = {METER_QR}
    call.debouncer = types.SimpleNamespace(should_handle=lambda c: pytest.fail("camera re-checked it"))
    asyncio.run(call._on_code(METER_QR))


# --- StatusVideo meter and paid screens --------------------------------------------------------

def pixel(frame: bytes, x: int, y: int) -> tuple:
    i = (y * StatusVideo.W + x) * 4
    return tuple(frame[i:i + 3])


def test_paid_state_renders_green_banner():
    v = make_video()
    v.meter_label = "Meter 42 · Dogwood Lot & Meter Co."
    v.begin_meter_view(METER_URL + "?hours=2", 2, 0.02)
    now = time.monotonic()
    checking = v._render(now)                       # "Opening the meter…" before any frame
    assert len(checking) == v.W * v.H * 4
    assert v.set_live_frame(jpeg())
    live = v._render(now + 1)
    assert pixel(live, v.W // 2, 800) != pixel(checking, v.W // 2, 800)

    v.set_meter_view(PAGE, 2, 0.02)
    meter = v._render(now + 2)
    assert v.state == "meter" and pixel(meter, 5, 5) == status_video.COLORS["meter"]
    k_meter = v._frame_key(now)

    v.set_paid(2, 0.02)
    paid = v._render(now + 3)
    assert v.state == "paid" and len(paid) == v.W * v.H * 4
    assert pixel(paid, 5, 5) == status_video.COLORS["paid"]          # green banner
    assert v.shot is not None                                       # same hours: page picture kept
    assert v._frame_key(now) != k_meter

    v.set_paid(3, 0.03)                             # paid for other hours than the picture shows
    assert v.shot is None
    card = v._render(now + 4)
    assert pixel(card, 5, 5) == status_video.COLORS["paid"]
    assert pixel(card, v.W // 2, 640 - 100) == status_video.COLORS["paid"]   # the big tick card

    v.reset()
    assert v.state == "idle" and v.meter is None


def test_ordinary_checks_do_not_show_meter_info():
    v = make_video()
    v.begin_meter_view(METER_URL, 1, 0.01)
    v.begin_check("https://example.com")
    assert v.meter is None
