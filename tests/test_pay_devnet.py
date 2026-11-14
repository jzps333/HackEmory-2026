"""Devnet Solana Pay setup: merchant table, demo QR codes, and the devnet-only guards.

Offline: the RPC is mocked; nothing touches the network.
"""
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from api import scan, solana_pay
from api.merchants import KNOWN_MERCHANTS
from api.routes_pay import router
from api.scan import parse_solana_pay, payment_result
from scripts import make_demo_qr

QR_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "qr"
MAINNET_GENESIS = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"
FAKE_SIG = "5" * 88
REAL_CLIENT = httpx.Client


# --- merchant table ----------------------------------------------------------------------------

def test_merchants_are_distinct_valid_public_addresses():
    assert set(KNOWN_MERCHANTS) == {"Dogwood Lot & Meter Co.", "Magnolia Diner"}
    addrs = list(KNOWN_MERCHANTS.values())
    assert len(set(addrs)) == len(addrs)
    for a in addrs:
        assert Pubkey.from_string(a).is_on_curve()   # a real wallet key, not a PDA or program
    assert "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU" not in addrs   # old placeholder


def test_scan_and_pay_share_one_merchant_table():
    import api.routes_pay as routes_pay
    assert scan.KNOWN_MERCHANTS is KNOWN_MERCHANTS is routes_pay.KNOWN_MERCHANTS


# --- demo QR codes -----------------------------------------------------------------------------

def decode(name: str) -> str:
    cv2 = pytest.importorskip("cv2")
    from chert.qr_reader import read_qr
    text = read_qr(cv2.imread(str(QR_DIR / name)))
    assert text, f"{name} did not decode"
    return text


@pytest.mark.parametrize("name,label", [("real_meter.png", "Dogwood Lot & Meter Co."),
                                        ("magnolia_table.png", "Magnolia Diner")])
def test_real_qr_codes_are_verified_and_safe(name, label):
    qr = decode(name)
    p = parse_solana_pay(qr)
    assert p and p.label == label and p.recipient == KNOWN_MERCHANTS[label]
    assert p.merchant_verified and 0 < p.amount_sol <= 0.01
    Pubkey.from_string(p.reference)
    assert payment_result(qr, p).verdict == "safe"


def test_fake_sticker_impersonates_dogwood_and_is_blocked():
    real, fake = parse_solana_pay(decode("real_meter.png")), parse_solana_pay(decode("fake_sticker.png"))
    assert (fake.label, fake.amount_sol, fake.message) == (real.label, real.amount_sol, real.message)
    assert fake.recipient not in KNOWN_MERCHANTS.values()
    assert not fake.merchant_verified
    r = payment_result(decode("fake_sticker.png"), fake)
    assert r.verdict == "malicious" and r.scam_type == "fake_payment_app"


def test_unknown_label_is_not_verified():
    p = parse_solana_pay(f"solana:{KNOWN_MERCHANTS['Magnolia Diner']}?amount=0.01&label=Magnolia%20Cafe")
    assert not p.merchant_verified


def test_make_demo_qr_urls_round_trip():
    scammer = str(Keypair().pubkey())
    urls = make_demo_qr.build_urls(scammer)
    assert set(urls) == {"real_meter.png", "magnolia_table.png", "fake_sticker.png"}
    for name, url in urls.items():
        p = parse_solana_pay(url)
        assert p.merchant_verified == (name != "fake_sticker.png")
        assert p.amount_sol <= 0.01
    with pytest.raises(ValueError):
        make_demo_qr.build_urls(KNOWN_MERCHANTS["Magnolia Diner"])


# --- /pay on devnet ----------------------------------------------------------------------------

@pytest.fixture
def wallet(tmp_path, monkeypatch):
    p = tmp_path / "devnet.json"
    p.write_text(json.dumps(list(bytes(Keypair()))))
    monkeypatch.setenv("SOLANA_KEYPAIR_PATH", str(p))
    monkeypatch.setenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")
    return p


def mock_rpc(monkeypatch, genesis: str) -> list:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        req = json.loads(request.content)
        calls.append(req["method"])
        result = {"getGenesisHash": genesis, "sendTransaction": FAKE_SIG,
                  "getLatestBlockhash": {"context": {"slot": 1}, "value": {
                      "blockhash": "EkSnNWid2cvwEVnVx9aBqawnmiCNiDgp3gUdkDPTKN1N",
                      "lastValidBlockHeight": 100}}}.get(req["method"])
        if result is None:
            return httpx.Response(400, json={"error": {"message": "unexpected"}})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    monkeypatch.setattr(solana_pay.httpx, "Client",
                        lambda *a, **k: REAL_CLIENT(transport=httpx.MockTransport(handler)))
    return calls


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def pay_body(qr: str, approved: bool = True, scan_id: str = "devnet-test") -> dict:
    """Exactly what the app sends: the scan's payment object plus approved: true (and hours,
    which the Dogwood parking meter requires and fixed-amount merchants ignore)."""
    p = parse_solana_pay(qr)
    return {"scan_id": scan_id, "payment": p.model_dump(), "approved": approved, "hours": 1}


def test_pays_each_real_qr(client, wallet, monkeypatch):
    for name in ("real_meter.png", "magnolia_table.png"):
        calls = mock_rpc(monkeypatch, solana_pay.DEVNET_GENESIS_HASH)
        r = client.post("/pay", json=pay_body(decode(name), scan_id=f"devnet-{name}"))   # one pay per scan
        assert r.status_code == 200, r.text
        assert r.json()["explorer_url"].endswith("?cluster=devnet")
        assert calls == ["getGenesisHash", "getLatestBlockhash", "sendTransaction"]


def test_refuses_impostor_and_unapproved(client, wallet, monkeypatch):
    calls = mock_rpc(monkeypatch, solana_pay.DEVNET_GENESIS_HASH)
    fake = pay_body(decode("fake_sticker.png"))
    fake["payment"]["merchant_verified"] = True          # a lying client changes nothing
    r = client.post("/pay", json=fake)
    assert r.status_code == 403 and r.json()["error"] == "merchant_not_verified"
    r = client.post("/pay", json=pay_body(decode("real_meter.png"), approved=False))
    assert r.status_code == 403 and r.json()["error"] == "not_approved"
    assert calls == []


def test_refuses_rpc_that_is_not_really_devnet(client, wallet, monkeypatch):
    # Hostname says devnet, but the cluster behind it is mainnet: refuse before signing anything.
    monkeypatch.setenv("SOLANA_RPC_URL", "https://devnet.example-rpc.test")
    calls = mock_rpc(monkeypatch, MAINNET_GENESIS)
    r = client.post("/pay", json=pay_body(decode("real_meter.png")))
    assert r.status_code == 403 and r.json()["error"] == "not_devnet"
    assert calls == ["getGenesisHash"]


@pytest.mark.parametrize("url", ["http://api.devnet.solana.com",
                                 "https://api.mainnet-beta.solana.com",
                                 "https://mainnet.devnet-proxy.test",
                                 "https://solana.example/devnet"])
def test_refuses_non_devnet_urls_without_any_rpc(client, wallet, monkeypatch, url):
    monkeypatch.setenv("SOLANA_RPC_URL", url)
    calls = mock_rpc(monkeypatch, solana_pay.DEVNET_GENESIS_HASH)
    r = client.post("/pay", json=pay_body(decode("real_meter.png")))
    assert r.status_code == 403 and r.json()["error"] == "not_devnet"
    assert calls == []


def test_cap_is_tiny(client, wallet, monkeypatch):
    calls = mock_rpc(monkeypatch, solana_pay.DEVNET_GENESIS_HASH)
    m = KNOWN_MERCHANTS["Magnolia Diner"]     # fixed amount; meter prices are capped in test_meter_pay
    r = client.post("/pay", json=pay_body(f"solana:{m}?amount=0.06&label=Magnolia%20Diner"))
    assert r.status_code == 400 and r.json()["error"] == "over_cap"
    assert calls == []


def test_unfunded_payer_gets_a_clear_error(client, wallet, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["method"]
        if method == "sendTransaction":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {
                "code": -32002, "message": "Transaction simulation failed: This account may not "
                                           "be used to pay transaction fees"}})
        result = {"getGenesisHash": solana_pay.DEVNET_GENESIS_HASH,
                  "getLatestBlockhash": {"context": {"slot": 1}, "value": {
                      "blockhash": "EkSnNWid2cvwEVnVx9aBqawnmiCNiDgp3gUdkDPTKN1N",
                      "lastValidBlockHeight": 100}}}[method]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    monkeypatch.setattr(solana_pay.httpx, "Client",
                        lambda *a, **k: REAL_CLIENT(transport=httpx.MockTransport(handler)))
    r = client.post("/pay", json=pay_body(decode("real_meter.png")))
    assert r.status_code == 503 and r.json()["error"] == "payer_unfunded"
    assert "faucet.solana.com" in r.json()["message"]
