"""Demo merchants ScanSafe trusts for Solana Pay: QR `label` -> the merchant's DEVNET wallet.

Every business here is made up. Only PUBLIC addresses go in this file. The matching keypairs
live on the API server in /root/solana/merchant-*.json (chmod 600) and are never committed;
they are only there so the demo can show the merchant's devnet balance going up.

A Solana Pay QR is "verified" only when its label is a key here AND its recipient is that
exact wallet. A sticker with the same label but another wallet is an impostor.

MERCHANT_METERS: merchants that sell parking by the hour. For them the server sets the amount
(rate x hours) and ignores the amount in the QR or from the app.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

KNOWN_MERCHANTS: dict[str, str] = {
    "Dogwood Lot & Meter Co.": "6jQGteA52iYssC8A8ss3tsnfGtPCAGPaDH5Z1o8X66TL",
    "Magnolia Diner": "9qAFfuxQcEsTwPirRu24BGh7UzKeJA5ayXKghufTDqXX",
}

LAMPORTS_PER_SOL = 1_000_000_000


@dataclass(frozen=True)
class MeterConfig:
    """Pay-by-the-hour parking. Amounts are devnet test SOL."""
    rate_per_hour_sol: float
    min_hours: int
    max_hours: int
    meter_url: str          # page the FaceTime agent shows live, with ?hours=N added
    meter_id: str = ""      # shown and spoken: "meter 42"
    spoken_name: str = ""   # how the agent says the merchant's name ("&" read aloud is awkward)

    def amount_sol(self, hours: int) -> float:
        """rate x hours, computed in whole lamports so 0.01 x 3 is exactly 0.03."""
        return round(self.rate_per_hour_sol * LAMPORTS_PER_SOL) * hours / LAMPORTS_PER_SOL

    def as_dict(self) -> dict:
        return asdict(self)


MERCHANT_METERS: dict[str, MeterConfig] = {
    "Dogwood Lot & Meter Co.": MeterConfig(
        rate_per_hour_sol=0.01, min_hours=1, max_hours=4,
        meter_url="https://scansafe-demo-sites.vercel.app/fixtures/meter/index.html",
        meter_id="42", spoken_name="Dogwood Lot and Meter"),
}


def is_verified(label: str, recipient: str) -> bool:
    """The QR's label names a merchant we know AND it pays that merchant's exact wallet."""
    return bool(label) and KNOWN_MERCHANTS.get(label) == recipient


def meter_for(label: str) -> MeterConfig | None:
    """The merchant's meter config, or None if it charges a fixed amount (or isn't known)."""
    return MERCHANT_METERS.get(label or "")


# --- USD prices (one-time virtual cards pay Dogwood in test USD; Solana pays in test SOL) -------

def env_decimal(name: str, default: str) -> Decimal:
    """A positive, finite number from env, else the default."""
    try:
        d = Decimal(os.getenv(name, "").strip() or default)
        if d.is_finite() and d > 0:
            return d
    except ArithmeticError:
        pass
    return Decimal(default)


def dogwood_rate_usd() -> Decimal:
    """USD per hour for Dogwood meters paid with a one-time virtual card (env DOGWOOD_RATE_USD)."""
    return env_decimal("DOGWOOD_RATE_USD", "2.50")


def usd(value) -> Decimal:
    """Round to cents. Raises ValueError for something that isn't a number."""
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ValueError("not an amount") from None


def meter_usd(hours: int) -> Decimal:
    """What `hours` of Dogwood parking costs in USD (same number the quote shows and the card is capped at)."""
    return usd(dogwood_rate_usd() * hours)
