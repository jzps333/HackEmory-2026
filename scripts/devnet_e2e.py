"""End-to-end devnet check against the live API, doing exactly what the app does.

Scans every demo QR in fixtures/qr/ with POST /scan, checks /pay refuses the impostor and an
unapproved payment, then pays the real Dogwood meter (0.01 test SOL) with approved: true and
confirms the transaction and the merchant's balance on devnet. Devnet only. Run from the repo root:
  python3 scripts/devnet_e2e.py [--api https://api.scansafe.nyc] [--no-pay]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api.merchants import KNOWN_MERCHANTS  # noqa: E402
from api.solana_pay import DEVNET_GENESIS_HASH, LAMPORTS_PER_SOL, explorer_url  # noqa: E402
from chert.qr_reader import read_qr  # noqa: E402

RPC = "https://api.devnet.solana.com"   # used only to verify; fixed to devnet
QR = ROOT / "fixtures" / "qr"
EXPECT = {"real_meter.png": "safe", "magnolia_table.png": "safe", "fake_sticker.png": "malicious"}


def rpc(method: str, params: list):
    body = httpx.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                      timeout=30).json()
    if "error" in body:
        raise RuntimeError(f"{method}: {body['error']}")
    return body["result"]


def balance(addr: str) -> int:
    return rpc("getBalance", [addr, {"commitment": "confirmed"}])["value"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="https://api.scansafe.nyc")
    ap.add_argument("--no-pay", action="store_true", help="scan and refusal checks only")
    args = ap.parse_args()
    api = args.api.rstrip("/")
    if rpc("getGenesisHash", []) != DEVNET_GENESIS_HASH:
        sys.exit("Verification RPC is not devnet. Stopping.")
    failed = False

    def check(ok: bool, what: str) -> None:
        nonlocal failed
        failed |= not ok
        print(f"[{'ok' if ok else 'FAIL'}] {what}")

    scans = {}
    for name, want in EXPECT.items():
        qr = read_qr(cv2.imread(str(QR / name)))
        r = httpx.post(f"{api}/scan", json={"url": qr}, timeout=90).json()
        scans[name] = r
        p = r.get("payment") or {}
        check(r.get("verdict") == want and p.get("merchant_verified") == (want == "safe"),
              f"/scan {name}: {r.get('verdict')}, {p.get('amount_sol')} SOL to {p.get('label')!r} "
              f"({p.get('recipient')}), verified={p.get('merchant_verified')}")

    def pay(name: str, approved: bool = True) -> httpx.Response:   # same body as app/src/lib/api.ts
        s = scans[name]
        return httpx.post(f"{api}/pay", json={"scan_id": s["scan_id"], "payment": s["payment"],
                                              "approved": approved}, timeout=60)

    r = pay("fake_sticker.png")
    check(r.status_code == 403 and r.json().get("error") == "merchant_not_verified",
          f"/pay impostor refused: {r.status_code} {r.json().get('error')}")
    r = pay("real_meter.png", approved=False)
    check(r.status_code == 403 and r.json().get("error") == "not_approved",
          f"/pay without approval refused: {r.status_code} {r.json().get('error')}")

    if not args.no_pay:
        merchant = KNOWN_MERCHANTS["Dogwood Lot & Meter Co."]
        before = balance(merchant)
        r = pay("real_meter.png")
        check(r.status_code == 200, f"/pay approved: {r.status_code} {r.text[:200]}")
        if r.status_code == 200:
            sig = r.json()["signature"]
            status = None
            for _ in range(30):
                status = rpc("getSignatureStatuses", [[sig]])["value"][0]
                if status and status.get("confirmationStatus") in ("confirmed", "finalized"):
                    break
                time.sleep(2)
            check(bool(status) and status.get("err") is None,
                  f"devnet status: {status and status.get('confirmationStatus')}, "
                  f"err={status and status.get('err')}")
            tx = rpc("getTransaction", [sig, {"encoding": "json", "commitment": "confirmed",
                                              "maxSupportedTransactionVersion": 0}])
            keys = tx["transaction"]["message"]["accountKeys"] if tx else []
            ref = scans["real_meter.png"]["payment"]["reference"]
            check(merchant in keys and ref in keys, "transaction pays the merchant and carries the reference")
            delta = balance(merchant) - before
            want = round(scans["real_meter.png"]["payment"]["amount_sol"] * LAMPORTS_PER_SOL)
            check(delta == want, f"merchant balance +{delta / LAMPORTS_PER_SOL} SOL")
            print(f"signature: {sig}\nexplorer:  {explorer_url(sig)}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
