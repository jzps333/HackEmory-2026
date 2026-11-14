"""Voice-confirmed payment, agent side (chert/voice_pay.py + the tools in chert/agent_integration.py):
the consent rule, transcript timing (after the readback, not over it, within 20 s), no backend call
without consent, cancel on no / stop / hours change, tool gating, the consent card on our video, and
one full run against the real API. Offline: LiveKit is stubbed, HTTP is MockTransport / ASGI."""
import asyncio
import json
import sys
import types

import httpx
import pytest

try:
    import livekit.rtc  # noqa: F401
    import livekit.agents  # noqa: F401
except ImportError:   # same stub as test_meter_pay.py / test_dogwood_agent.py
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

from chert import voice_pay as vpm  # noqa: E402
from chert.voice_pay import Heard, VoicePay, consent_check, consent_ok, declines  # noqa: E402

METER = {"merchant": "Dogwood Lot & Meter Co.", "rate_per_hour_sol": 0.01, "min_hours": 1,
         "max_hours": 4, "meter_url": "https://scansafe-demo-sites.vercel.app/fixtures/meter/index.html",
         "meter_id": "42", "spoken_name": "Dogwood Lot and Meter", "scan_id": "abc123abc123",
         "scan_url": "solana:x"}
READBACK = ("Pay 0.03 SOL to Dogwood Lot and Meter for 3 hours, plate GA 4821K. "
            "Say 'yes, pay' to confirm, or 'no' to cancel.")
ASK = "Ask the caller to clearly say 'yes, pay' to confirm"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SCANSAFE_API_URL", "http://scansafe.test")
    monkeypatch.setenv("AGENT_INTERNAL_KEY", "agent-key-test")


# --- the consent rule ----------------------------------------------------------------------------

@pytest.mark.parametrize("words", ["yes, pay", "Yes pay.", "YES PAY", "yeah, pay it", "yep pay",
                                   "confirm, pay", "Yes — pay.", "yes please pay", "okay yes, pay",
                                   "yeah go ahead and pay"])
def test_clear_yes_pay(words):
    assert consent_ok(words)


@pytest.mark.parametrize("words", ["pay", "yes", "no pay", "yes, don't pay", "yes, don’t pay",
                                   "yes dont pay", "yes, do not pay", "no, yes, pay", "yes pay. wait",
                                   "yes pay, cancel", "stop, yes pay", "yes, how much will I pay?",
                                   "yesterday I paid", "payment yes", "eyes pay", "yes pay later",
                                   "maybe yes pay", "yes pay if it's cheap", "yes I won't pay",
                                   "yes I would like to know the total before I pay", "", None, 3,
                                   "yes, pay... actually hold on", "nope, yes pay", "yes but not pay"])
def test_anything_else_is_not_consent(words):
    assert not consent_ok(words)


def test_declines():
    for w in ("no", "No thanks", "stop", "cancel that", "wait", "don't", "never mind", "nope"):
        assert declines(w), w
    for w in ("yes, pay", "how much", "", None):
        assert not declines(w), w


# --- timing: after the readback, not over it, within 20 s ----------------------------------------

class Clock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t

    async def sleep(self, s):
        self.t += s
        await asyncio.sleep(0)


def spoke(heard, clock, secs=8.0, *, user_at=None):
    heard.on_agent_state("speaking")
    if user_at is not None:
        clock.t += user_at
        heard.on_user_state("speaking")
        heard.on_user_state("listening")
        clock.t += secs - user_at
    else:
        clock.t += secs
    heard.on_agent_state("listening")
    clock.t += 0.5                                   # the caller answers a moment later


def test_consent_timing():
    c = Clock()
    h = Heard(clock=c)
    opened = c()
    h.on_agent_state("thinking")
    assert consent_check(h, opened, READBACK, c()) == "not_read"
    c.t += 1
    h.on_agent_state("speaking")
    c.t += 1
    h.on_agent_state("listening")                                # "Okay." isn't the readback
    assert consent_check(h, opened, READBACK, c()) == "not_read"
    h.on_agent_state("speaking")
    c.t += 3
    h.on_transcript("yes, pay", True)                            # while it's still being read
    assert consent_check(h, opened, READBACK, c()) == "not_read"
    c.t += 5
    h.on_agent_state("listening")
    assert consent_check(h, opened, READBACK, c()) == "no_answer"   # said before the readback ended
    c.t += 2
    h.on_transcript("yes", True)
    assert consent_check(h, opened, READBACK, c()) == "no_consent"
    c.t += 1
    h.on_transcript("yes, pay", False)                           # interim: not counted
    h.on_transcript("   ", True)                                 # empty final: not counted
    assert consent_check(h, opened, READBACK, c()) == "no_consent"
    h.on_transcript("yes, pay", True)
    assert consent_check(h, opened, READBACK, c()) == "ok"
    c.t += 21
    assert consent_check(h, opened, READBACK, c()) == "no_answer"   # too old now


def test_answer_more_than_20s_after_the_readback_is_too_late():
    c = Clock()
    h = Heard(clock=c)
    opened = c()
    spoke(h, c)
    c.t += 20.5
    h.on_transcript("yes, pay", True)
    assert consent_check(h, opened, READBACK, c()) == "no_answer"


def test_talking_over_the_readback_doesnt_count():
    c = Clock()
    h = Heard(clock=c)
    opened = c()
    spoke(h, c, user_at=2.0)
    c.t += 1
    h.on_transcript("yes, pay", True)
    assert consent_check(h, opened, READBACK, c()) == "talked_over"


def test_without_agent_state_events_it_assumes_a_plausible_readback_time():
    c = Clock()
    h = Heard(clock=c)
    opened = c()
    c.t += 2
    h.on_transcript("yes, pay", True)
    assert consent_check(h, opened, READBACK, c()) == "no_answer"
    c.t += 7
    h.on_transcript("yes, pay", True)
    assert consent_check(h, opened, READBACK, c()) == "ok"


# --- VoicePay against a fake API -----------------------------------------------------------------

class FakeAPI:
    def __init__(self, intent_status=200, intent_body=None, confirm_status=200, confirm_body=None):
        self.requests: list[httpx.Request] = []
        self.intent_status, self.confirm_status = intent_status, confirm_status
        self.intent_body = intent_body or {"ok": True, "intent_id": "pi_1", "readback": READBACK,
                                           "method": "solana_devnet", "amount_sol": 0.03, "amount_usd": None,
                                           "hours": 3, "plate": "GA 4821K", "expires_in": 45}
        self.confirm_body = confirm_body or {"ok": True, "signature": "sig", "status": {
            "state": "paid", "hours": 3, "amount_sol": 0.03}}

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        path = req.url.path
        if path == "/pay/intent":
            return httpx.Response(self.intent_status, json=self.intent_body)
        if path.endswith("/confirm"):
            return httpx.Response(self.confirm_status, json=self.confirm_body)
        if path.endswith("/cancel"):
            return httpx.Response(200, json={"ok": True, "cancelled": True})
        return httpx.Response(404, json={})

    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]

    def confirms(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.url.path.endswith("/confirm")]


def make_vp(api=None, hours=3, plate="ga 4821k"):
    api = api or FakeAPI()
    c = Clock()
    h = Heard(clock=c)
    h.on_agent_state("listening")                    # a live session reports agent states
    shown = []
    vp = VoicePay(METER, h, show=shown.append, default_hours=lambda: hours, plate=lambda: plate,
                  client=httpx.AsyncClient(transport=httpx.MockTransport(api.handler)),
                  clock=c, sleep=c.sleep)
    return vp, h, c, shown, api


async def settle():
    for _ in range(5):
        await asyncio.sleep(0)


def test_prepare_asks_the_server_and_reads_back_verbatim():
    async def go():
        vp, h, c, shown, api = make_vp()
        out = await vp.prepare()
        (req,) = api.requests
        assert str(req.url) == "http://scansafe.test/pay/intent" and req.headers["X-Agent-Key"] == "agent-key-test"
        assert json.loads(req.content) == {"scan_id": "abc123abc123", "hours": 3, "plate": "GA 4821K"}
        assert f'"{READBACK}"' in out and "word for word" in out and "confirm_payment" in out
        assert shown == ["Say “yes, pay” to confirm · 0.03 SOL · 3 h · GA 4821K"]
        await vp.prepare(hours=2, pay_with="card")
        await settle()
        last = [json.loads(r.content) for r in api.requests if r.url.path == "/pay/intent"][-1]
        assert last["method"] == "virtual_card" and last["hours"] == 2
        assert "/pay/intent/pi_1/cancel" in api.paths()              # the old one was cancelled
    asyncio.run(go())


def test_prepare_refusals_never_open_an_intent():
    async def go():
        vp, *_ = make_vp(hours=None)
        assert "how many hours" in await vp.prepare()
        assert "how many hours" in await vp.prepare(hours=9)
        api = FakeAPI(intent_status=409, intent_body={"ok": False, "error": "already_paid"})
        vp, _h, _c, shown, api = make_vp(api)
        assert "already paid" in await vp.prepare()
        assert vp.intent is None and shown == []
        api = FakeAPI(intent_status=503, intent_body={"ok": False, "error": "lithic_not_configured"})
        vp, *_ = make_vp(api)
        assert await vp.prepare(pay_with="card") == vpm.CARD_UNAVAILABLE
        assert vp.intent is None
        monkey = make_vp()[0]
        import os
        os.environ.pop("AGENT_INTERNAL_KEY")
        assert "tap Pay" in await monkey.prepare() and monkey.intent is None
    asyncio.run(go())


def test_no_backend_call_without_a_clear_yes_pay_after_the_readback():
    async def go():
        vp, h, c, shown, api = make_vp()
        assert (await vp.confirm())["reason"] == "no_intent"             # nothing prepared
        await vp.prepare()
        h.on_transcript("yes, pay", True)                                 # before it was read
        out = await vp.confirm()
        assert out["reason"] == "not_read" and READBACK in out["say"]
        spoke(h, c)
        assert (await vp.confirm())["say"] == ASK                         # last words came before it
        for words in ("yes", "pay", "okay", "yes, how much will I pay?", "sure go ahead"):
            c.t += 1
            h.on_transcript(words, True)
            out = await vp.confirm()
            assert out["ok"] is False and out["say"] == ASK, words
        assert vp.backend_confirms == 0 and not [p for p in api.paths() if p.endswith("/confirm")]
        assert vp.intent is not None                                      # still waiting for them
    asyncio.run(go())


def test_yes_pay_confirms_once_with_the_callers_words():
    async def go():
        vp, h, c, shown, api = make_vp()
        await vp.prepare()
        spoke(h, c)
        c.t += 2
        h.on_transcript("Yes, pay.", True)
        out = await vp.confirm()
        assert out["ok"] is True and out["status"]["state"] == "paid"
        assert api.confirms() == [{"utterance": "Yes, pay."}]
        assert [str(r.url) for r in api.requests if r.url.path.endswith("/confirm")] == \
            ["http://scansafe.test/pay/intent/pi_1/confirm"]
        assert vp.intent is None and shown[-1] is None                   # card off the video
        assert (await vp.confirm())["reason"] == "no_intent"             # single use
        assert len(api.confirms()) == 1
    asyncio.run(go())


def test_confirm_waits_briefly_for_the_transcript_to_land():
    async def go():
        vp, h, c, shown, api = make_vp()
        await vp.prepare()
        spoke(h, c)
        c.t += 1

        async def late_words():
            await asyncio.sleep(0)
            h.on_transcript("yes pay", True)
        asyncio.create_task(late_words())
        assert (await vp.confirm())["ok"] is True
    asyncio.run(go())


def test_talked_over_readback_cancels_and_asks_to_prepare_again():
    async def go():
        vp, h, c, shown, api = make_vp()
        await vp.prepare()
        spoke(h, c, user_at=3.0)
        h.on_transcript("yes pay", True)
        out = await vp.confirm()
        assert out["reason"] == "talked_over" and "prepare_payment again" in out["say"]
        await settle()
        assert vp.intent is None and api.paths()[-1] == "/pay/intent/pi_1/cancel"
        assert vp.backend_confirms == 0
    asyncio.run(go())


@pytest.mark.parametrize("words", ["no", "No, don't", "stop", "cancel it", "wait a second", "never mind"])
def test_no_stop_cancel_after_the_readback_cancels_it(words):
    async def go():
        vp, h, c, shown, api = make_vp()
        await vp.prepare()
        spoke(h, c)
        h.on_transcript(words, True)
        await settle()
        assert vp.intent is None and shown[-1] is None
        assert api.paths()[-1] == "/pay/intent/pi_1/cancel"
        h.on_transcript("yes, pay", True)
        assert (await vp.confirm())["reason"] == "no_intent" and vp.backend_confirms == 0
    asyncio.run(go())


def test_hours_changed_in_the_app_or_paid_in_the_app_drop_it():
    async def go():
        vp, h, c, shown, api = make_vp()
        await vp.prepare()
        vp.on_hours_changed(3)                                           # same hours: kept
        assert vp.intent is not None
        vp.on_hours_changed(2)
        await settle()
        assert vp.intent is None and api.paths()[-1] == "/pay/intent/pi_1/cancel"
        await vp.prepare()
        vp.on_paid()
        assert vp.intent is None and shown[-1] is None
        assert "already paid" in await vp.prepare()
    asyncio.run(go())


def test_expired_intent_never_reaches_the_backend():
    async def go():
        vp, h, c, shown, api = make_vp()
        await vp.prepare()
        spoke(h, c)
        c.t += 40
        h.on_transcript("yes, pay", True)
        assert (await vp.confirm())["reason"] == "no_intent"
        assert vp.backend_confirms == 0 and shown[-1] is None
    asyncio.run(go())


def test_server_refusal_is_passed_on_kindly():
    async def go():
        api = FakeAPI(confirm_status=503, confirm_body={"ok": False, "error": "payer_unfunded"})
        vp, h, c, shown, api = make_vp(api)
        await vp.prepare()
        spoke(h, c)
        h.on_transcript("yes pay", True)
        out = await vp.confirm()
        assert out["ok"] is False and "didn't go through" in out["say"] and "nothing was paid" in out["say"]
    asyncio.run(go())


# --- the agent: tools only on meter calls, stop cancels, the video card ---------------------------

def agent_mod(monkeypatch):
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    from chert import agent_integration as ai
    return ai


def make_call(ai):
    from test_meter_pay import make_video
    call = ai.ScanSafeCall.__new__(ai.ScanSafeCall)
    call.session = types.SimpleNamespace(interrupt=lambda: None)
    call.video = make_video()
    call._inflight, call._results = {}, {}
    call.generation = 0
    call.meter_flow = None
    call.heard = Heard()
    call.voice_pay = None
    return call


def test_payment_tools_only_on_meter_calls_with_the_agent_key(monkeypatch):
    ai = agent_mod(monkeypatch)
    call = make_call(ai)
    plain = ai.agent_for(call, None)
    assert type(plain) is ai.ScanSafeAgent and not hasattr(ai.ScanSafeAgent, "prepare_payment")
    meter_agent = ai.agent_for(call, METER)
    assert type(meter_agent) is ai.MeterPayAgent
    assert all(hasattr(ai.MeterPayAgent, t) for t in ("prepare_payment", "confirm_payment", "cancel_payment",
                                                 "check_qr_code", "stop"))
    assert "yes, pay" in vpm.INSTRUCTIONS and "tap Pay" in vpm.INSTRUCTIONS
    assert "Never say a payment went through unless confirm_payment" in vpm.INSTRUCTIONS
    monkeypatch.delenv("AGENT_INTERNAL_KEY")
    assert type(ai.agent_for(call, METER)) is ai.ScanSafeAgent        # app's Pay button only
    assert ai.attach_voice_pay(call, METER) is None


def test_tools_before_voice_pay_is_ready(monkeypatch):
    ai = agent_mod(monkeypatch)
    call = make_call(ai)
    agent = ai.MeterPayAgent(call)
    assert "tap Pay" in asyncio.run(agent.prepare_payment(None))
    assert "tap Pay" in asyncio.run(agent.confirm_payment(None))


def wired(ai, monkeypatch, api=None):
    call = make_call(ai)
    vp = ai.attach_voice_pay(call, METER)
    api = api or FakeAPI()
    c = Clock()
    vp.heard.clock = c
    vp.heard.on_agent_state("listening")
    vp.clock, vp.sleep = c, c.sleep
    vp._client = httpx.AsyncClient(transport=httpx.MockTransport(api.handler))
    vp.default_hours = lambda: 3
    return call, vp, c, api


def test_tool_flow_and_the_consent_card(monkeypatch):
    ai = agent_mod(monkeypatch)

    async def go():
        call, vp, c, api = wired(ai, monkeypatch)
        agent = ai.MeterPayAgent(call, vpm.INSTRUCTIONS)
        out = await agent.prepare_payment(None)
        assert READBACK in out
        assert call.video.consent.startswith("Say “yes, pay” to confirm · 0.03 SOL · 3 h")
        assert await agent.confirm_payment(None) != "" and vp.backend_confirms == 0
        spoke(vp.heard, c)
        vp.heard.on_transcript("yes, pay", True)
        flow = types.SimpleNamespace(stopped=False)
        call.meter_flow = flow
        out = await agent.confirm_payment(None)
        assert "Say only: Okay" in out and "receipt line comes next" in out
        assert call.video.consent is None and call.video.state != "paid"   # the status poll does Paid
        # Flow already stopped (the caller said stop earlier): the tool says Paid itself.
        call2, vp2, c2, _ = wired(ai, monkeypatch)
        agent2 = ai.MeterPayAgent(call2)
        await agent2.prepare_payment(None)
        spoke(vp2.heard, c2)
        vp2.heard.on_transcript("yep, pay", True)
        out = await agent2.confirm_payment(None)
        assert out == "Tell the caller exactly this: Paid. 3 hours on meter 42. Your receipt is in the app."
        assert call2.video.state == "paid" and call2.video.meter["hours"] == 3
    asyncio.run(go())


def test_stop_and_cancel_payment_cancel_the_intent(monkeypatch):
    ai = agent_mod(monkeypatch)

    async def go():
        call, vp, c, api = wired(ai, monkeypatch)
        agent = ai.MeterPayAgent(call)
        await agent.prepare_payment(None)
        call.stop()
        await settle()
        assert vp.intent is None and call.video.consent is None
        assert api.paths()[-1] == "/pay/intent/pi_1/cancel"
        await agent.prepare_payment(None)
        assert "won't pay" in await agent.cancel_payment(None)
        await settle()
        assert vp.intent is None and api.paths().count("/pay/intent/pi_1/cancel") >= 2
        spoke(vp.heard, c)
        vp.heard.on_transcript("yes, pay", True)
        assert "prepare_payment" in await agent.confirm_payment(None) and vp.backend_confirms == 0
    asyncio.run(go())


def test_wire_transcripts_uses_the_session_events():
    from chert import agent_integration as ai
    handlers = {}
    session = types.SimpleNamespace(on=lambda name, fn: handlers.__setitem__(name, fn))
    heard = Heard()
    ai.wire_transcripts(session, heard)
    assert set(handlers) == {"user_input_transcribed", "agent_state_changed", "user_state_changed"}
    handlers["user_input_transcribed"](types.SimpleNamespace(transcript="yes pa", is_final=False))
    assert heard.seq == 0
    handlers["user_input_transcribed"](types.SimpleNamespace(transcript="yes, pay", is_final=True))
    assert heard.text == "yes, pay" and heard.seq == 1
    handlers["agent_state_changed"](types.SimpleNamespace(old_state="thinking", new_state="speaking"))
    handlers["agent_state_changed"](types.SimpleNamespace(old_state="speaking", new_state="listening"))
    assert len(heard.agent_spans) == 1
    handlers["user_state_changed"](types.SimpleNamespace(old_state="listening", new_state="speaking"))
    assert len(heard.user_starts) == 1


def test_meter_flow_tells_voice_pay_about_hours_changes():
    from chert import meter_pay as mp
    seen = []
    quotes = iter([{"hours": 1}, {"hours": 3}, {"hours": 3}, {"hours": 3}])
    statuses = iter([{"state": "none"}] * 3 + [{"state": "paid", "hours": 3, "amount_sol": 0.03}])
    t = [0.0]

    async def fq(_):
        return next(quotes, {"hours": 3})

    async def fs(_):
        return next(statuses, {"state": "paid", "hours": 3})

    async def sleep(s):
        t[0] += s

    async def nothing(*a):
        return None
    flow = mp.MeterPayFlow(METER, say=nothing, show_live=nothing, show_paid=lambda h, a: seen.append(("paid", h)),
                           fetch_quote=fq, fetch_status=fs, clock=lambda: t[0], sleep=sleep,
                           debounce_s=0.0, on_hours=lambda n: seen.append(("hours", n)))
    asyncio.run(flow.run())
    assert ("hours", 3) in seen and seen[-1] == ("paid", 3)


def test_consent_card_renders_and_clears():
    from chert.status_video import StatusVideo
    from test_meter_pay import make_video, pixel
    v = make_video()
    v.state = "meter"
    v.meter = {"label": "Meter 42", "hours": 3, "amount": 0.03}
    import time
    now = time.monotonic()
    plain = v._render(now)
    v.set_consent("Say “yes, pay” to confirm · 0.03 SOL · 3 h · GA 4821K")
    with_card = v._render(now)
    assert pixel(with_card, 40, StatusVideo.H - 60) == (251, 191, 36)   # amber card at the bottom
    assert pixel(plain, 40, StatusVideo.H - 60) != (251, 191, 36)
    v.set_paid(3, 0.03)
    assert v.consent is None
    v.set_consent("Say “yes, pay” to confirm · $7.50 · 3 h")
    v.reset()
    assert v.consent is None


# --- one full run: agent -> real API -> devnet (mocked) -------------------------------------------

def test_full_voice_payment_against_the_real_api(monkeypatch, tmp_path):
    from test_meter_pay import METER_QR, mock_rpc, scanned
    from api import main as api_main, result_store, voice_pay as server_vp
    from solders.keypair import Keypair
    wallet = tmp_path / "devnet.json"
    wallet.write_text(json.dumps(list(bytes(Keypair()))))
    monkeypatch.setenv("SOLANA_KEYPAIR_PATH", str(wallet))
    monkeypatch.setenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")
    monkeypatch.setenv("SCANSAFE_API_URL", "http://api.test")
    monkeypatch.setattr(result_store, "RESULT_DIR", tmp_path / "results")
    calls = mock_rpc(monkeypatch)
    server_vp.clear()
    sid = scanned(METER_QR).scan_id
    meter = {**METER, "scan_id": sid}

    async def go():
        c = Clock()
        h = Heard(clock=c)
        shown = []
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api_main.app)) as http:
            vp = VoicePay(meter, h, show=shown.append, default_hours=lambda: 2, client=http, clock=c,
                          sleep=c.sleep)
            out = await vp.prepare()
            assert "Pay 0.02 SOL to Dogwood Lot and Meter for 2 hours. Say 'yes, pay' to confirm" in out
            h.on_transcript("pay", True)
            spoke(h, c)
            assert (await vp.confirm())["say"] == ASK
            c.t += 1.5
            h.on_transcript("yes, pay", True)
            done = await vp.confirm()
            assert done["ok"] is True and done["status"]["state"] == "paid" and done["status"]["hours"] == 2
            vp._client = None
        assert [m for m, _ in calls].count("sendTransaction") == 1
    asyncio.run(go())
    server_vp.clear()
