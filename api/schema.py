"""The shared scan result format. Every part of ScanSafe passes this around.

Person 1 produces it, Person 2 speaks/sends it, Person 3 stores it, Person 4 displays it.
Change it only after telling the team. JSON examples live in shared/.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Verdict = Literal["safe", "suspicious", "malicious"]
ScamType = Literal[
    "none", "fake_bank", "fake_payment_app", "fake_parking_or_toll", "fake_delivery",
    "fake_government", "tech_support", "fake_login_other", "malware_download", "other",
]


class JevChecks(BaseModel):
    """Each of Jev's typed decisions, with its calibrated probability."""
    impersonates: str = "none"          # which kind of brand the page pretends to be
    impersonates_p: float = 0.0
    asks_password_p: float = 0.0        # P(page asks for a password or login)
    asks_payment_p: float = 0.0         # P(page asks for card / payment details)
    prompt_injection_p: float = 0.0     # P(page has hidden text aimed at AI agents)
    malicious_p: float = 0.0            # P(overall verdict is malicious)


class Payment(BaseModel):
    """A Solana Pay request found in the QR code (devnet only)."""
    recipient: str
    amount_sol: float
    label: str = ""
    message: str = ""
    reference: str = ""
    merchant_verified: bool = False     # does the wallet match the merchant it claims to be?
    tx_signature: Optional[str] = None  # set after the user approves and we pay


class ScanResult(BaseModel):
    scan_id: str
    url: str                                   # what the QR code contained
    final_url: Optional[str] = None            # where it ended up after redirects
    redirect_chain: list[str] = Field(default_factory=list)
    domain: Optional[str] = None
    page_title: Optional[str] = None

    verdict: Verdict
    jev_score: float                           # 0..1, how likely it's a scam
    scam_type: ScamType = "none"
    explanation: str                           # plain English, from Gemini; safe to read aloud
    checks: JevChecks = Field(default_factory=JevChecks)

    screenshots: list[str] = Field(default_factory=list)   # URLs or file names
    flagged_before: int = 0                    # times this URL/domain was already reported nearby
    payment: Optional[Payment] = None
    location: Optional[list[float]] = None     # [lat, lng], rounded to ~100 m, only if user agreed
    scanned_at: int                            # unix seconds
    scan_ms: Optional[int] = None              # how long the sandbox took
