"""Show the demo's devnet wallets: the payer's PUBLIC address and every balance. Devnet only.

Reads SOLANA_KEYPAIR_PATH / SOLANA_RPC_URL from .env like the API does. Prints public addresses
and balances only, never key material. Run from the repo root:
  python3 scripts/devnet_wallets.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api import solana_pay  # noqa: E402  (loads .env)
from api.merchants import KNOWN_MERCHANTS  # noqa: E402


def main() -> None:
    url = solana_pay.rpc_url()
    with httpx.Client() as client:
        try:
            solana_pay.check_devnet(url)
            solana_pay.check_genesis(client, url)
            payer = solana_pay.load_keypair().pubkey()
        except solana_pay.PaymentError as e:
            sys.exit(f"{e.code}: {e.message}")

        def balance(addr: str) -> float:
            res = solana_pay._rpc(client, url, "getBalance", [addr, {"commitment": "confirmed"}])
            return res["value"] / solana_pay.LAMPORTS_PER_SOL

        print(f"RPC: devnet ({urlparse(url).hostname})")   # host only: URLs can hold API keys
        print(f"payer  {payer}  {balance(str(payer)):.6f} SOL")
        for label, addr in KNOWN_MERCHANTS.items():
            print(f"merchant {label!r}  {addr}  {balance(addr):.6f} SOL")
    print("Top up the payer at https://faucet.solana.com (choose devnet, paste the payer address).")


if __name__ == "__main__":
    main()
