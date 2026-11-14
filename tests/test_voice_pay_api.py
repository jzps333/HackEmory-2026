"""Voice-confirmed payments, server side: POST /pay/intent, /pay/intent/{id}/confirm and /cancel.
Agent key, server-side pricing and readback, the 0.05 SOL cap, expiry, single use, one open intent
per scan, 3 tries, the consent rule on the caller's words, replay, and both payment methods
(Solana devnet; Lithic sandbox virtual card for the scan's server-recorded owner). Offline: the
devnet RPC and Lithic are MockTransports (fakes shared with test_meter_pay / test_accounts)."""
import pytest

import test_accounts as ta
from test_accounts import _env, lithic  # noqa: F401  (fixtures: same env as the saved-accounts tests)
from test_meter_pay import FAKE_SIG, mock_rpc, sent_lamports_and_recipient, wallet  # noqa: F401

from api import account_crypto, main as api_main, merchants, meter_pay, voice_pay
from api.merchants import KNOWN_MERCHANTS, MeterConfig

client = ta.client
AGENT = {"X-Agent-Key": "agent-test-key"}
DOGWOOD = KNOWN_MERCHANTS["Dogwood Lot & Meter Co."]
SOL_READBACK = ("Pay 0.03 SOL to Dogwood Lot and Meter for 3 hours. "
                "Say 'yes, pay' to confirm, or 'no' to cancel.")


@pytest.fixture(autouse=True)
def _intents():
    voice_pay.clear()
    yield
    voice_pay.clear()


def intent(sid, hours=3, headers=AGENT, **extra):
    return client.post("/pay/intent", json={"scan_id": sid, "hours": hours, **extra}, headers=headers)


def confirm(intent_id, utterance="yes, pay", headers=AGENT):
    return client.post(f"/pay/intent/{intent_id}/confirm", json={"utterance": utterance}, headers=headers)


def owned(sid, phone=ta.PHONE):
    """What /call-me does for a meter call: the person being called owns the scan."""
    meter_pay.set_owner(sid, account_crypto.phone_hash(phone))
    return sid


def test_routes_are_mounted_on_the_real_app():
    assert client.app is api_main.app
    assert client.post("/pay/intent", json={"scan_id": "abc", "hours": 1}, headers=AGENT).json()["error"] == "unknown_scan"
    assert client.post("/pay/intent/pi_x/confirm", json={"utterance": "yes, pay"}, headers=AGENT).json()["error"] == "unknown_intent"
    assert client.post("/pay/intent/pi_x/cancel", headers=AGENT).json() == {"ok": True, "cancelled": False}


def test_agent_key_required_everywhere(monkeypatch):
    sid = ta.scanned()
    for h in ({}, {"X-Agent-Key": "wrong"}, {"X-Agent-Key": ""}, {"X-Agent-Key": "agent-test-key-and-more"}):
        r = intent(sid, headers=h)
        assert r.status_code == 401 and r.json()["error"] == "bad_agent_key"
    good = intent(sid).json()["intent_id"]
    assert confirm(good, headers={"X-Agent-Key": "nope"}).status_code == 401
    assert client.post(f"/pay/intent/{good}/cancel", headers={}).status_code == 401
    assert voice_pay.get(good).tries == 0 and not voice_pay.get(good).used   # a wrong key costs nothing
    monkeypatch.delenv("AGENT_INTERNAL_KEY")
    r = intent(sid)
    assert r.status_code == 503 and r.json()["error"] == "agent_key_not_configured"
    assert "agent-test-key" not in r.text


def test_server_prices_it_and_reads_it_back():
    sid = ta.scanned()
    r = intent(sid, amount_sol=0.0001, merchant="Evil", recipient="x", owner="someone")  # extra: ignored
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["readback"] == SOL_READBACK
    assert (body["amount_sol"], body["amount_usd"], body["hours"], body["method"], body["merchant"]) == \
        (0.03, None, 3, "solana_devnet", "Dogwood Lot & Meter Co.")
    assert body["intent_id"].startswith("pi_") and body["expires_in"] == 45
    assert 44 <= body["expires_at"] - body["created_at"] <= 46
    assert "owner_hash" not in body and "owner" not in body
    one = intent(sid, hours=1).json()
    assert one["readback"].startswith("Pay 0.01 SOL to Dogwood Lot and Meter for 1 hour. ")


def test_plate_in_readback_and_our_own_record_wins():
    sid = ta.scanned()
    assert intent(sid, plate=" ga  4821k ").json()["readback"] == (
        "Pay 0.03 SOL to Dogwood Lot and Meter for 3 hours, plate GA 4821K. "
        "Say 'yes, pay' to confirm, or 'no' to cancel.")
    for bad in ("<script>", "ABCDEFGHIJK", "--", 42, "ga_48"):
        r = intent(sid, plate=bad)
        assert r.status_code == 400 and r.json()["error"] == "bad_plate", bad
    token = ta.ready_driver(plate="gx 4242", link=False)
    assert token
    owned(sid)
    assert intent(sid, plate="GA 4821K").json()["plate"] == "GX 4242"


def test_intent_refusals():
    sid = ta.scanned()
    cases = [
        (intent("nope-not-a-scan"), 404, "unknown_scan"),
        (intent(ta.scanned(ta.DINER_QR)), 400, "not_a_meter"),
        (intent(sid, hours=0), 400, "bad_hours"),
        (intent(sid, hours=5), 400, "bad_hours"),
        (intent(sid, hours="2"), 400, "bad_hours"),
        (intent(sid, hours=None), 400, "bad_hours"),
        (intent(sid, method="agentcard"), 400, "bad_payment_method"),
        (client.post("/pay/intent", json={"hours": 2}, headers=AGENT), 400, "bad_scan_id"),
    ]
    for r, status, code in cases:
        assert (r.status_code, r.json()["error"]) == (status, code), r.text
    from solders.keypair import Keypair
    fake = f"solana:{Keypair().pubkey()}?amount=0.01&label=Dogwood%20Lot%20%26%20Meter%20Co."
    r = intent(ta.scanned(fake))
    assert r.status_code == 403 and r.json()["error"] == "merchant_not_verified"


def test_over_the_cap_is_refused(monkeypatch):
    label = "Dogwood Lot & Meter Co."
    old = merchants.MERCHANT_METERS[label]
    monkeypatch.setitem(merchants.MERCHANT_METERS, label, MeterConfig(
        rate_per_hour_sol=0.02, min_hours=1, max_hours=4, meter_url=old.meter_url, meter_id="42",
        spoken_name=old.spoken_name))
    sid = ta.scanned()
    assert intent(sid, hours=2).status_code == 200                  # 0.04 SOL
    r = intent(sid, hours=3)                                        # 0.06 SOL > 0.05
    assert r.status_code == 400 and r.json()["error"] == "over_cap"


def test_yes_pay_pays_once_and_replay_is_refused(wallet, monkeypatch):  # noqa: F811
    calls = mock_rpc(monkeypatch)
    sid = ta.scanned()
    iid = intent(sid).json()["intent_id"]
    r = confirm(iid, "Yes, pay.")
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["ok"], body["signature"], body["amount_sol"], body["hours"], body["method"]) == \
        (True, FAKE_SIG, 0.03, 3, "solana_devnet")
    assert body["status"]["state"] == "paid" and body["status"]["hours"] == 3
    lamports, keys = sent_lamports_and_recipient(calls)
    assert lamports == 30_000_000 and DOGWOOD in keys
    sends = len([m for m, _ in calls if m == "sendTransaction"])
    r = confirm(iid, "yes, pay")                                     # replay
    assert r.status_code == 409 and r.json()["error"] == "intent_used"
    r = intent(sid)                                                  # and no new one: it's paid
    assert r.status_code == 409 and r.json()["error"] == "already_paid"
    assert len([m for m, _ in calls if m == "sendTransaction"]) == sends == 1
    # The app's Pay button sees the same: one payment per scan.
    assert client.post("/pay", json={"scan_id": sid, "hours": 3, "approved": True}).status_code == 409


@pytest.mark.parametrize("words", ["pay", "yes", "no pay", "yes, don't pay", "yes dont pay",
                                   "yes, do not pay", "no. yes, pay", "yes pay. wait", "yes pay, cancel",
                                   "stop! yes pay", "yes, how much will I pay?", "payment yes", "", None,
                                   "yes I would like to know the total before I pay anything", 5])
def test_unclear_words_never_pay(words, wallet, monkeypatch):  # noqa: F811
    calls = mock_rpc(monkeypatch)
    sid = ta.scanned()
    iid = intent(sid).json()["intent_id"]
    r = confirm(iid, words)
    assert r.status_code == 403 and r.json()["error"] == "no_consent"
    assert calls == [] and meter_pay.get_status(sid)["state"] == "none"
    assert confirm(iid, "yeah, pay it").status_code == 200           # a clear yes still works after


def test_three_tries_per_intent(wallet, monkeypatch):  # noqa: F811
    calls = mock_rpc(monkeypatch)
    sid = ta.scanned()
    iid = intent(sid).json()["intent_id"]
    for _ in range(3):
        assert confirm(iid, "pay").status_code == 403
    r = confirm(iid, "yes, pay")
    assert r.status_code == 429 and r.json()["error"] == "too_many_tries"
    assert confirm(iid, "yes, pay").status_code == 404               # gone
    assert calls == []
    assert confirm(intent(sid).json()["intent_id"], "yep, pay").status_code == 200


def test_expired_intents_are_refused(wallet, monkeypatch):  # noqa: F811
    calls = mock_rpc(monkeypatch)
    sid = ta.scanned()
    iid = intent(sid).json()["intent_id"]
    voice_pay.get(iid).expires_at -= 46
    r = confirm(iid)
    assert r.status_code == 410 and r.json()["error"] == "intent_expired"
    assert confirm(iid).status_code == 404 and calls == []


def test_one_open_intent_per_scan(wallet, monkeypatch):  # noqa: F811
    mock_rpc(monkeypatch)
    sid = ta.scanned()
    first = intent(sid, hours=2).json()["intent_id"]
    second = intent(sid, hours=3).json()["intent_id"]
    assert first != second
    assert confirm(first).status_code == 404                         # replaced
    r = confirm(second)
    assert r.status_code == 200 and r.json()["hours"] == 3


def test_cancel(wallet, monkeypatch):  # noqa: F811
    calls = mock_rpc(monkeypatch)
    sid = ta.scanned()
    iid = intent(sid).json()["intent_id"]
    r = client.post(f"/pay/intent/{iid}/cancel", headers=AGENT)
    assert r.status_code == 200 and r.json() == {"ok": True, "cancelled": True}
    assert confirm(iid).status_code == 404 and calls == []
    assert client.post(f"/pay/intent/{iid}/cancel", headers=AGENT).json() == {"ok": True, "cancelled": False}
    used = intent(sid).json()["intent_id"]
    assert confirm(used).status_code == 200
    r = client.post(f"/pay/intent/{used}/cancel", headers=AGENT)
    assert r.status_code == 409 and r.json()["error"] == "intent_used"


def test_failed_payment_still_uses_up_the_intent(wallet, monkeypatch):  # noqa: F811
    mock_rpc(monkeypatch, send_error="Attempt to debit an account but found no record of a prior credit.")
    sid = ta.scanned()
    iid = intent(sid).json()["intent_id"]
    r = confirm(iid)
    assert r.status_code == 503 and r.json()["error"] == "payer_unfunded"
    assert r.json()["status"]["state"] == "failed"
    assert confirm(iid).status_code == 409                           # no silent retry of the same one
    mock_rpc(monkeypatch)
    assert confirm(intent(sid).json()["intent_id"]).status_code == 200


# --- one-time virtual card (Lithic sandbox), paid for the scan's owner ------------------------------

CARD_READBACK = ("Pay $7.50 to Dogwood Lot and Meter for 3 hours, plate GX 4242, "
                 "with a one-time virtual card. Say 'yes, pay' to confirm.")


def test_virtual_card_by_voice(lithic):  # noqa: F811
    ta.ready_driver()
    sid = owned(ta.scanned())
    body = intent(sid, method="virtual_card", plate="ZZ 1").json()
    assert body["readback"] == CARD_READBACK
    assert (body["amount_usd"], body["amount_sol"], body["plate"], body["method"]) == (7.5, None, "GX 4242", "virtual_card")
    assert lithic.calls == []                                        # nothing minted for an intent
    r = confirm(body["intent_id"], "yes, pay")
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["method"], out["provider"], out["amount_usd"], out["hours"], out["card_closed"]) == \
        ("virtual_card", "lithic_sandbox", 7.5, 3, True)
    assert ta.PAN not in r.text and '"cvv"' not in r.text
    (create,) = lithic.bodies("POST", "/v1/cards")
    assert create["spend_limit"] == 750 and create["type"] == "SINGLE_USE"
    assert lithic.closed() == ["card-tok-1"]
    st = client.get(f"/pay/status/{sid}").json()
    assert (st["state"], st["method"], st["amount_usd"], st["card_last4"]) == ("paid", "virtual_card", 7.5, "4142")
    assert confirm(body["intent_id"]).status_code == 409             # replay


def test_virtual_card_default_follows_the_owners_preference(lithic):  # noqa: F811
    token = ta.ready_driver()
    sid = owned(ta.scanned())
    assert intent(sid).json()["method"] == "solana_devnet"           # no preference saved
    client.put("/me", json={"preferred_payment": "virtual_card"}, headers=ta.bearer(token))
    assert intent(sid).json()["method"] == "virtual_card"
    assert intent(sid, method="solana_devnet").json()["method"] == "solana_devnet"   # explicit wins
    other = ta.scanned()                                             # nobody owns this scan
    assert intent(other).json()["method"] == "solana_devnet"


def test_virtual_card_refusals(monkeypatch, lithic):  # noqa: F811
    sid = ta.scanned()
    r = intent(sid, method="virtual_card")
    assert r.status_code == 401 and r.json()["error"] == "not_signed_in"   # no owner recorded
    ta.ready_driver(ta.OTHER, link=False)
    owned(sid, ta.OTHER)
    r = intent(sid, method="virtual_card")
    assert r.status_code == 403 and r.json()["error"] == "dogwood_not_linked"
    sid2 = owned(ta.scanned())
    ta.ready_driver(plate="")
    r = intent(sid2, method="virtual_card")
    assert r.status_code == 400 and r.json()["error"] == "plate_required"
    monkeypatch.delenv("LITHIC_API_KEY")
    r = intent(sid2, method="virtual_card")
    assert r.status_code == 503 and r.json()["error"] == "lithic_not_configured"
    monkeypatch.setenv("LITHIC_API_KEY", "lithic-sandbox-test-key")
    monkeypatch.setenv("VIRTUAL_CARD_MAX_USD", "5")
    client.put("/me", json={"plate": "GX 4242"}, headers=ta.bearer(ta.signed_in()))
    r = intent(sid2, method="virtual_card", hours=3)
    assert r.status_code == 400 and r.json()["error"] == "over_cap"
    assert lithic.calls == []


def test_virtual_card_owner_change_after_the_readback_is_refused(lithic):  # noqa: F811
    ta.ready_driver()
    sid = owned(ta.scanned())
    iid = intent(sid, method="virtual_card").json()["intent_id"]
    owned(sid, ta.OTHER)                                             # a new call for the same scan
    r = confirm(iid)
    assert r.status_code == 409 and r.json()["error"] == "owner_changed"
    assert lithic.calls == [] and meter_pay.get_status(sid)["state"] == "none"
