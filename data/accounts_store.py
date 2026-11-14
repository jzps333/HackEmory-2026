"""Saved accounts: the profile (plate, preferred payment) and linked accounts (Dogwood, PayPal).

Tables live in Tiger Data (same database as the scan log) and are created on first use, or by
`python3 -m data.setup`. Rows are keyed by phone_hash (api/account_crypto.phone_hash); no phone
number is stored. Linked-account tokens are stored only as Fernet ciphertext (secret_enc), and a
revoked link keeps no ciphertext at all.

Backend: env ACCOUNTS_STORE = "tiger" | "memory". Unset: Tiger when TIGER_DATABASE_URL is set,
otherwise not configured (routes answer 503). "memory" is for tests and local dev only: a
restart forgets everything.
"""
from __future__ import annotations

import copy
import os
import threading
from datetime import datetime, timezone
from typing import Optional

from data import tiger_store

PROFILE_FIELDS = ("plate", "preferred_payment")

ACCOUNTS_SQL = [
    """CREATE TABLE IF NOT EXISTS accounts (
        phone_hash        TEXT PRIMARY KEY,
        plate             TEXT,
        preferred_payment TEXT,
        created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS linked_accounts (
        id          BIGSERIAL PRIMARY KEY,
        phone_hash  TEXT NOT NULL,
        provider    TEXT NOT NULL,
        secret_enc  TEXT NOT NULL,
        meta        JSONB NOT NULL DEFAULT '{}'::jsonb,
        linked_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        revoked_at  TIMESTAMPTZ
    )""",
    # At most one ACTIVE link per (phone_hash, provider); revoked rows stay as history.
    """CREATE UNIQUE INDEX IF NOT EXISTS linked_accounts_one_active
        ON linked_accounts (phone_hash, provider) WHERE revoked_at IS NULL""",
]


class NotConfigured(RuntimeError):
    """No accounts backend: set TIGER_DATABASE_URL (or ACCOUNTS_STORE=memory for local dev)."""


def backend() -> str:
    choice = os.getenv("ACCOUNTS_STORE", "").strip().lower()
    if choice in ("tiger", "memory"):
        return choice
    return "tiger" if tiger_store.is_configured() else ""


def is_configured() -> bool:
    b = backend()
    return b == "memory" or (b == "tiger" and tiger_store.is_configured())


def get_store():
    b = backend()
    if b == "memory":
        return _memory
    if b == "tiger" and tiger_store.is_configured():
        return _tiger
    raise NotConfigured("Saved accounts are unavailable: set TIGER_DATABASE_URL.")


def ensure_schema() -> None:
    with tiger_store._connect() as conn:
        for sql in ACCOUNTS_SQL:
            conn.execute(sql)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- Tiger (Postgres) --------------------------------------------------------------------------

class TigerAccountStore:
    def __init__(self):
        self._ready = False

    def _conn(self):
        conn = tiger_store._connect()
        if not self._ready:
            for sql in ACCOUNTS_SQL:
                conn.execute(sql)
            self._ready = True
        return conn

    def get_profile(self, phone_hash: str) -> Optional[dict]:
        with self._conn() as conn:
            return conn.execute(
                "SELECT plate, preferred_payment, created_at, updated_at FROM accounts "
                "WHERE phone_hash = %s", (phone_hash,)).fetchone()

    def update_profile(self, phone_hash: str, fields: dict) -> dict:
        cols = [c for c in PROFILE_FIELDS if c in fields]   # fixed whitelist: safe to format
        if not cols:
            return self.get_profile(phone_hash) or {}
        sql = (f"INSERT INTO accounts (phone_hash, {', '.join(cols)}) "
               f"VALUES (%s, {', '.join(['%s'] * len(cols))}) "
               f"ON CONFLICT (phone_hash) DO UPDATE SET "
               f"{', '.join(f'{c} = EXCLUDED.{c}' for c in cols)}, updated_at = now() "
               "RETURNING plate, preferred_payment, created_at, updated_at")
        with self._conn() as conn:
            return conn.execute(sql, (phone_hash, *[fields[c] for c in cols])).fetchone()

    def list_linked(self, phone_hash: str) -> list[dict]:
        with self._conn() as conn:
            return conn.execute(
                "SELECT provider, meta, linked_at FROM linked_accounts "
                "WHERE phone_hash = %s AND revoked_at IS NULL ORDER BY linked_at",
                (phone_hash,)).fetchall()

    def get_linked(self, phone_hash: str, provider: str) -> Optional[dict]:
        with self._conn() as conn:
            return conn.execute(
                "SELECT provider, secret_enc, meta, linked_at FROM linked_accounts "
                "WHERE phone_hash = %s AND provider = %s AND revoked_at IS NULL",
                (phone_hash, provider)).fetchone()

    def link(self, phone_hash: str, provider: str, secret_enc: str, meta: dict) -> dict:
        """Replace any active link for this provider. Returns the new row (provider, meta,
        linked_at) plus "replaced": the old secret_enc or None."""
        from psycopg.types.json import Jsonb
        with self._conn() as conn:
            with conn.transaction():
                old = conn.execute(
                    "WITH old AS (SELECT id, secret_enc FROM linked_accounts WHERE phone_hash = %s "
                    "AND provider = %s AND revoked_at IS NULL FOR UPDATE) "
                    "UPDATE linked_accounts l SET revoked_at = now(), secret_enc = '' FROM old "
                    "WHERE l.id = old.id RETURNING old.secret_enc AS secret_enc",
                    (phone_hash, provider)).fetchone()
                row = conn.execute(
                    "INSERT INTO linked_accounts (phone_hash, provider, secret_enc, meta) "
                    "VALUES (%s, %s, %s, %s) RETURNING provider, meta, linked_at",
                    (phone_hash, provider, secret_enc, Jsonb(meta))).fetchone()
        return {**row, "replaced": (old or {}).get("secret_enc") or None}

    def revoke(self, phone_hash: str, provider: str) -> Optional[dict]:
        """Revoke the active link (keeps the row, wipes its ciphertext). Returns the row as it
        was (with secret_enc, so the caller can revoke it upstream), or None."""
        with self._conn() as conn:
            return conn.execute(
                "WITH old AS (SELECT id, secret_enc, meta, linked_at FROM linked_accounts "
                "WHERE phone_hash = %s AND provider = %s AND revoked_at IS NULL FOR UPDATE) "
                "UPDATE linked_accounts l SET revoked_at = now(), secret_enc = '' FROM old "
                "WHERE l.id = old.id "
                "RETURNING l.provider, old.secret_enc AS secret_enc, old.meta AS meta, old.linked_at AS linked_at",
                (phone_hash, provider)).fetchone()


# --- memory (tests, local dev) -------------------------------------------------------------------

class MemoryAccountStore:
    """Same behaviour as the Tiger store. `accounts` / `linked_rows` mirror the table rows."""

    def __init__(self):
        self._lock = threading.Lock()
        self.accounts: dict[str, dict] = {}
        self.linked_rows: list[dict] = []

    def clear(self) -> None:
        with self._lock:
            self.accounts.clear()
            self.linked_rows.clear()

    def get_profile(self, phone_hash: str) -> Optional[dict]:
        with self._lock:
            row = self.accounts.get(phone_hash)
            return {k: row[k] for k in ("plate", "preferred_payment", "created_at", "updated_at")} if row else None

    def update_profile(self, phone_hash: str, fields: dict) -> dict:
        cols = {c: fields[c] for c in PROFILE_FIELDS if c in fields}
        with self._lock:
            row = self.accounts.get(phone_hash)
            if row is None and not cols:
                return {}
            if row is None:
                row = {"phone_hash": phone_hash, "plate": None, "preferred_payment": None,
                       "created_at": _now(), "updated_at": _now()}
                self.accounts[phone_hash] = row
            if cols:
                row.update(cols)
                row["updated_at"] = _now()
        return self.get_profile(phone_hash)

    def _active(self, phone_hash: str, provider: str) -> Optional[dict]:
        for r in self.linked_rows:
            if r["phone_hash"] == phone_hash and r["provider"] == provider and r["revoked_at"] is None:
                return r
        return None

    def list_linked(self, phone_hash: str) -> list[dict]:
        with self._lock:
            rows = [r for r in self.linked_rows if r["phone_hash"] == phone_hash and r["revoked_at"] is None]
            return [{"provider": r["provider"], "meta": copy.deepcopy(r["meta"]), "linked_at": r["linked_at"]}
                    for r in sorted(rows, key=lambda r: r["linked_at"])]

    def get_linked(self, phone_hash: str, provider: str) -> Optional[dict]:
        with self._lock:
            r = self._active(phone_hash, provider)
            return ({"provider": r["provider"], "secret_enc": r["secret_enc"],
                     "meta": copy.deepcopy(r["meta"]), "linked_at": r["linked_at"]} if r else None)

    def link(self, phone_hash: str, provider: str, secret_enc: str, meta: dict) -> dict:
        with self._lock:
            old = self._active(phone_hash, provider)
            replaced = None
            if old:
                replaced, old["secret_enc"], old["revoked_at"] = old["secret_enc"], "", _now()
            row = {"phone_hash": phone_hash, "provider": provider, "secret_enc": secret_enc,
                   "meta": copy.deepcopy(meta), "linked_at": _now(), "revoked_at": None}
            self.linked_rows.append(row)
            return {"provider": provider, "meta": copy.deepcopy(meta), "linked_at": row["linked_at"],
                    "replaced": replaced or None}

    def revoke(self, phone_hash: str, provider: str) -> Optional[dict]:
        with self._lock:
            r = self._active(phone_hash, provider)
            if not r:
                return None
            out = {"provider": provider, "secret_enc": r["secret_enc"], "meta": copy.deepcopy(r["meta"]),
                   "linked_at": r["linked_at"]}
            r["secret_enc"], r["revoked_at"] = "", _now()
            return out


_tiger = TigerAccountStore()
_memory = MemoryAccountStore()
