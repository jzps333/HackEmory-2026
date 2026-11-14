"""Generate demo Solana Pay QR codes into fixtures/qr/.

  real_meter.png  -> pays the Peachtree Parking Co. wallet from api.scan.KNOWN_MERCHANTS (SAFE)
  fake_sticker.png -> same label and amount, but a scammer's wallet (MALICIOUS)

Peachtree Parking Co. is a made-up demo brand. Run from the repo root:
  python3 scripts/make_demo_qr.py [--scammer <devnet address>]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import quote

import qrcode
from solders.keypair import Keypair

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api.scan import KNOWN_MERCHANTS  # noqa: E402

LABEL = "Peachtree Parking Co."
AMOUNT = "0.02"
MESSAGE = "Meter 42"
OUT = ROOT / "fixtures" / "qr"


def solana_pay_url(recipient: str, reference: str) -> str:
    q = (f"amount={AMOUNT}&reference={reference}"
         f"&label={quote(LABEL)}&message={quote(MESSAGE)}")
    return f"solana:{recipient}?{q}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scammer", help="wallet for the fake sticker (default: random new address)")
    args = ap.parse_args()

    merchant = KNOWN_MERCHANTS[LABEL]
    scammer = args.scammer or str(Keypair().pubkey())   # public key only; secret is discarded
    if scammer == merchant:
        sys.exit("Scammer wallet must differ from the merchant wallet.")

    OUT.mkdir(parents=True, exist_ok=True)
    codes = {
        "real_meter.png": solana_pay_url(merchant, str(Keypair().pubkey())),
        "fake_sticker.png": solana_pay_url(scammer, str(Keypair().pubkey())),
    }
    for name, url in codes.items():
        qrcode.make(url).save(OUT / name)
        print(f"{name}: {url}")
    print(f"Saved to {OUT}")


if __name__ == "__main__":
    main()
