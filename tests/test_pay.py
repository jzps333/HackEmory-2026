"""Offline tests for POST /pay and api.solana_pay. The RPC is mocked; nothing touches the network."""
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from solders.keypair import Keypair
from solders.transaction import Transaction

from api import solana_pay
from api.routes_pay import router
from api.scan import KNOWN_MERCHANTS, parse_solana_pay

MERCHANT = KNOWN_MERCHANTS["Dogwood Lot & Meter Co."]
SCAMMER = str(Keypair().pubkey())
REFERENCE = str(Keypair().pubkey())
FAKE_SIG = "5" * 88


def body(recipient=MERCHANT, amount=0.02, approved=True, verified=True, label="Dogwood Lot & Meter Co."):
    # hours: Dogwood is a parking meter, so /pay needs them (ignored for fixed-amount merchants)
    return {"scan_id": "abc123", "approved": approved, "hours": 1, "payment": {
        "recipient": recipient, "amount_sol": amount, "label": label, "message": "Meter 42",
        "reference": REFERENCE, "merchant_verified": verified}}


@pytest.fixture
def wallet(tmp_path, monkeypatch):
    p = tmp_path / "devnet.json"
    p.write_text(json.dumps(list(bytes(Keypair()))))
    monkeypatch.setenv("SOLANA_KEYPAIR_PATH", str(p))
    monkeypatch.setenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")
    return p


@pytest.fixture
def rpc(monkeypatch):
    """Mock the JSON-RPC endpoint and record every request."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        req = json.loads(request.content)
        calls.append((str(request.url), req))
        if req["method"] == "getGenesisHash":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1,
                                             "result": solana_pay.DEVNET_GENESIS_HASH})
        if req["method"] == "getLatestBlockhash":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {
                "context": {"slot": 1},
                "value": {"blockhash": "EkSnNWid2cvwEVnVx9aBqawnmiCNiDgp3gUdkDPTKN1N",
                          "lastValidBlockHeight": 100}}})
        if req["method"] == "sendTransaction":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": FAKE_SIG})
        return httpx.Response(400, json={"error": {"message": "unexpected"}})

    real_client = httpx.Client
    monkeypatch.setattr(solana_pay.httpx, "Client",
                        lambda *a, **k: real_client(transport=httpx.MockTransport(handler)))
    return calls


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_refuses_when_not_approved(client, wallet, rpc):
    r = client.post("/pay", json=body(approved=False))
    assert r.status_code == 403 and r.json()["error"] == "not_approved"
    assert rpc == []


def test_refuses_mismatched_wallet_even_if_client_says_verified(client, wallet, rpc):
    r = client.post("/pay", json=body(recipient=SCAMMER, verified=True))
    assert r.status_code == 403 and r.json()["error"] == "merchant_not_verified"
    r = client.post("/pay", json=body(label="Some Other Co.", verified=True))
    assert r.status_code == 403
    assert rpc == []


def test_refuses_non_devnet_rpc(client, wallet, rpc, monkeypatch):
    for url in ("https://api.mainnet-beta.solana.com", "https://evil.example/?devnet"):
        monkeypatch.setenv("SOLANA_RPC_URL", url)
        r = client.post("/pay", json=body())
        assert r.status_code == 403 and r.json()["error"] == "not_devnet"
    assert rpc == []


def test_refuses_over_cap(client, wallet, rpc):
    # A fixed-amount merchant (Dogwood is a parking meter: the server prices it, see test_meter_pay).
    r = client.post("/pay", json=body(recipient=KNOWN_MERCHANTS["Magnolia Diner"], amount=0.51,
                                      label="Magnolia Diner"))
    assert r.status_code == 400 and r.json()["error"] == "over_cap"
    assert rpc == []


def test_send_payment_refuses_unverified_directly(wallet, rpc):
    p = parse_solana_pay(f"solana:{SCAMMER}?amount=0.02&label=Dogwood%20Lot%20%26%20Meter%20Co.")
    with pytest.raises(solana_pay.PaymentError) as e:
        solana_pay.send_payment(p)
    assert e.value.code == "merchant_not_verified"


def test_503_without_keypair(client, rpc, monkeypatch):
    monkeypatch.setenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")
    monkeypatch.delenv("SOLANA_KEYPAIR_PATH", raising=False)
    r = client.post("/pay", json=body())
    assert r.status_code == 503 and r.json()["error"] == "no_wallet"


def test_happy_path(client, wallet, rpc):
    r = client.post("/pay", json={**body(), "hours": 2})     # Dogwood meter: 2 h x 0.01 SOL
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["amount_sol"] == 0.02 and j["hours"] == 2
    assert j["signature"] == FAKE_SIG
    assert j["explorer_url"] == f"https://explorer.solana.com/tx/{FAKE_SIG}?cluster=devnet"
    assert j["payment"]["tx_signature"] == FAKE_SIG
    assert [c[1]["method"] for c in rpc] == ["getGenesisHash", "getLatestBlockhash", "sendTransaction"]
    assert all("devnet" in c[0] for c in rpc)

    # The sent transaction: transfer of 0.02 SOL with the reference as a read-only non-signer key.
    import base64
    tx = Transaction.from_bytes(base64.b64decode(rpc[-1][1]["params"][0]))
    keys = [str(k) for k in tx.message.account_keys]
    ref_i = keys.index(REFERENCE)
    assert MERCHANT in keys
    readonly_unsigned_start = len(keys) - tx.message.header.num_readonly_unsigned_accounts
    assert not tx.message.is_signer(ref_i) and ref_i >= readonly_unsigned_start
    transfer_ix = tx.message.instructions[0]
    assert ref_i in list(transfer_ix.accounts)
    assert int.from_bytes(bytes(transfer_ix.data)[4:12], "little") == 20_000_000
    assert tx.verify() is None
