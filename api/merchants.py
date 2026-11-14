"""Demo merchants ScanSafe trusts for Solana Pay: QR `label` -> the merchant's DEVNET wallet.

Every business here is made up. Only PUBLIC addresses go in this file. The matching keypairs
live on the API server in /root/solana/merchant-*.json (chmod 600) and are never committed;
they are only there so the demo can show the merchant's devnet balance going up.

A Solana Pay QR is "verified" only when its label is a key here AND its recipient is that
exact wallet. A sticker with the same label but another wallet is an impostor.
"""
from __future__ import annotations

KNOWN_MERCHANTS: dict[str, str] = {
    "Dogwood Lot & Meter Co.": "6jQGteA52iYssC8A8ss3tsnfGtPCAGPaDH5Z1o8X66TL",
    "Magnolia Diner": "9qAFfuxQcEsTwPirRu24BGh7UzKeJA5ayXKghufTDqXX",
}
