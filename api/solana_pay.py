"""Send a Solana Pay transfer on DEVNET. Used only by POST /pay after the user taps confirm.

Builds the transaction with `solders` and talks JSON-RPC with httpx (no solana-py needed).
The payer keypair is read from SOLANA_KEYPAIR_PATH (Solana CLI JSON file) and never logged.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction

from api import config  # noqa: F401  (loads .env)
from api.schema import Payment

DEFAULT_RPC_URL = "https://api.devnet.solana.com"
MAX_SOL = 0.5                       # demo safety cap
LAMPORTS_PER_SOL = 1_000_000_000
MEMO_PROGRAM_ID = Pubkey.from_string("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr")


class PaymentError(Exception):
    """A refusal or failure with an HTTP status the route can return as-is."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def rpc_url() -> str:
    return os.getenv("SOLANA_RPC_URL", "").strip() or DEFAULT_RPC_URL


def check_devnet(url: str) -> None:
    """Hard guard: refuse anything that isn't a devnet RPC host."""
    host = (urlparse(url).hostname or "").lower()
    if "devnet" not in host:
        raise PaymentError(403, "not_devnet",
                           "Payments are devnet only. SOLANA_RPC_URL must be a devnet endpoint.")


def keypair_path() -> Path | None:
    raw = os.getenv("SOLANA_KEYPAIR_PATH", "").strip()
    if not raw:
        return None
    p = Path(raw).expanduser()
    return p if p.is_file() else None


def load_keypair() -> Keypair:
    p = keypair_path()
    if p is None:
        raise PaymentError(503, "no_wallet", "No payer wallet configured (SOLANA_KEYPAIR_PATH).")
    try:
        return Keypair.from_bytes(bytes(json.loads(p.read_text())))
    except Exception:  # never echo file contents
        raise PaymentError(503, "bad_wallet", "Payer wallet file could not be read.") from None


def _pubkey(value: str, field: str) -> Pubkey:
    try:
        return Pubkey.from_string(value)
    except Exception:
        raise PaymentError(400, "bad_address", f"{field} is not a valid Solana address.") from None


def validate(payment: Payment) -> int:
    """Checks that don't need the network. Returns the amount in lamports."""
    if not payment.merchant_verified:
        raise PaymentError(403, "merchant_not_verified",
                           "This wallet does not belong to the merchant it claims to be.")
    if not (payment.amount_sol > 0):
        raise PaymentError(400, "bad_amount", "Amount must be greater than zero.")
    if payment.amount_sol > MAX_SOL:
        raise PaymentError(400, "over_cap", f"Demo cap is {MAX_SOL} SOL per payment.")
    _pubkey(payment.recipient, "recipient")
    if payment.reference:
        _pubkey(payment.reference, "reference")
    return round(payment.amount_sol * LAMPORTS_PER_SOL)


def build_transaction(payment: Payment, payer: Keypair, blockhash: Hash, lamports: int) -> Transaction:
    ix = transfer(TransferParams(from_pubkey=payer.pubkey(),
                                 to_pubkey=Pubkey.from_string(payment.recipient), lamports=lamports))
    if payment.reference:
        # Solana Pay: reference is a read-only, non-signer key on the transfer instruction.
        ix = Instruction(ix.program_id, ix.data,
                         list(ix.accounts) + [AccountMeta(Pubkey.from_string(payment.reference),
                                                          is_signer=False, is_writable=False)])
    ixs = [ix]
    if payment.message:
        ixs.append(Instruction(MEMO_PROGRAM_ID, payment.message[:200].encode(), []))
    msg = Message.new_with_blockhash(ixs, payer.pubkey(), blockhash)
    return Transaction([payer], msg, blockhash)


def _rpc(client: httpx.Client, url: str, method: str, params: list) -> dict:
    try:
        r = client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                        timeout=20)
        r.raise_for_status()
        body = r.json()
    except (httpx.HTTPError, ValueError):
        raise PaymentError(502, "rpc_unreachable", "Could not reach the Solana devnet RPC.") from None
    if "error" in body:
        msg = str(body["error"].get("message", "unknown error"))[:200]
        raise PaymentError(502, "rpc_error", f"Solana RPC rejected the request: {msg}")
    return body["result"]


def explorer_url(sig: str) -> str:
    return f"https://explorer.solana.com/tx/{sig}?cluster=devnet"


def send_payment(payment: Payment, client: httpx.Client | None = None) -> dict:
    """Pay payment.amount_sol to payment.recipient on devnet. Returns {signature, explorer_url}."""
    url = rpc_url()
    check_devnet(url)
    lamports = validate(payment)
    payer = load_keypair()
    own = client is None
    client = client or httpx.Client()
    try:
        bh = _rpc(client, url, "getLatestBlockhash", [{"commitment": "confirmed"}])
        blockhash = Hash.from_string(bh["value"]["blockhash"])
        tx = build_transaction(payment, payer, blockhash, lamports)
        sig = _rpc(client, url, "sendTransaction",
                   [base64.b64encode(bytes(tx)).decode(),
                    {"encoding": "base64", "preflightCommitment": "confirmed"}])
    finally:
        if own:
            client.close()
    return {"signature": sig, "explorer_url": explorer_url(sig)}
