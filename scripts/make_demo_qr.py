"""Generate demo Solana Pay QR codes (devnet) into fixtures/qr/.

  real_meter.png     -> pays Dogwood Lot & Meter Co.'s wallet from api/merchants.py (SAFE)
  magnolia_table.png -> pays Magnolia Diner's wallet from api/merchants.py (SAFE)
  fake_sticker.png   -> same label and amount as real_meter, but a scammer's wallet (MALICIOUS:
                        the impersonation demo)

Dogwood Lot & Meter Co. and Magnolia Diner are made-up demo brands. Each run uses a fresh Solana
Pay `reference` per code. Run from the repo root:
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

from api.merchants import KNOWN_MERCHANTS  # noqa: E402

OUT = ROOT / "fixtures" / "qr"
# file -> (label, amount in SOL, message). Keep amounts tiny: this is devnet test SOL.
CODES = {
    "real_meter.png": ("Dogwood Lot & Meter Co.", "0.01", "Meter 42"),
    "magnolia_table.png": ("Magnolia Diner", "0.005", "Table 7"),
}
SCAM = ("fake_sticker.png", "real_meter.png")   # impostor copies this code's label and amount


def solana_pay_url(recipient: str, amount: str, label: str, message: str, reference: str) -> str:
    """Solana Pay transfer request: solana:<recipient>?amount=&reference=&label=&message="""
    q = (f"amount={amount}&reference={reference}"
         f"&label={quote(label)}&message={quote(message)}")
    return f"solana:{recipient}?{q}"


def build_urls(scammer: str) -> dict[str, str]:
    if scammer in KNOWN_MERCHANTS.values():
        raise ValueError("Scammer wallet must not be a known merchant wallet.")
    urls = {name: solana_pay_url(KNOWN_MERCHANTS[label], amount, label, message,
                                 str(Keypair().pubkey()))
            for name, (label, amount, message) in CODES.items()}
    label, amount, message = CODES[SCAM[1]]
    urls[SCAM[0]] = solana_pay_url(scammer, amount, label, message, str(Keypair().pubkey()))
    return urls


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scammer", help="wallet for the fake sticker (default: random new address)")
    args = ap.parse_args()
    scammer = args.scammer or str(Keypair().pubkey())   # public key only; secret is discarded
    try:
        urls = build_urls(scammer)
    except ValueError as e:
        sys.exit(str(e))

    OUT.mkdir(parents=True, exist_ok=True)
    for name, url in urls.items():
        qrcode.make(url).save(OUT / name)
        print(f"{name}: {url}")
    print(f"Saved to {OUT}")


if __name__ == "__main__":
    main()
