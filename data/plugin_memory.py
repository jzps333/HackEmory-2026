"""Per-person memory for community plugins: one Tiger table shared by every plugin.

plugin_records(plugin_id, owner, key, data jsonb, updated_at), primary key (plugin_id, owner, key).
`owner` is api.account_crypto.phone_hash(phone): the phone number itself is never stored. Without
TIGER_DATABASE_URL (or while Tiger is failing) records live in memory for this process.

Flashcards are records too (key "card:<id>"), scheduled with a small spaced-repetition rule:
right answer -> next review in 1 day, then x2.5 each time; wrong -> again in 1 minute.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import threading
import time
from typing import Optional

from data import tiger_store

log = logging.getLogger("scansafe.plugin_memory")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS plugin_records (
  plugin_id  TEXT NOT NULL,
  owner      TEXT NOT NULL,
  key        TEXT NOT NULL,
  data       JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (plugin_id, owner, key)
);
CREATE INDEX IF NOT EXISTS plugin_records_owner ON plugin_records (owner, plugin_id, updated_at DESC);
"""
KEY_RE = re.compile(r"^[A-Za-z0-9:_.-]{1,80}$")
MAX_DATA_BYTES = 4096
MAX_RECORDS_PER_PLUGIN = 2000          # per person; oldest dropped beyond this (memory backend)
TIGER_RETRY_S = 60.0
FIRST_INTERVAL_S, AGAIN_S, GROWTH = 86400, 60, 2.5

_lock = threading.Lock()
_mem: dict[tuple[str, str], dict[str, tuple[dict, float]]] = {}
_schema_ready = False
_tiger_down_until = 0.0


class MemoryError_(ValueError):
    """Bad input (key, size)."""


def reset() -> None:   # tests
    global _schema_ready, _tiger_down_until
    with _lock:
        _mem.clear()
        _schema_ready = False
        _tiger_down_until = 0.0


def _tiger_ok() -> bool:
    return tiger_store.is_configured() and time.monotonic() >= _tiger_down_until


def _tiger_failed(what: str, e: Exception) -> None:
    global _tiger_down_until
    _tiger_down_until = time.monotonic() + TIGER_RETRY_S
    log.warning("plugin memory: Tiger %s failed (%s)", what, type(e).__name__)   # never the URL


def _conn():
    global _schema_ready
    conn = tiger_store._connect()
    if not _schema_ready:
        try:
            conn.execute(SCHEMA_SQL)
            conn.commit()
        except Exception:
            conn.close()
            raise
        _schema_ready = True
    return conn


def _check(key: str, data: dict) -> str:
    if not isinstance(key, str) or not KEY_RE.fullmatch(key):
        raise MemoryError_("key must be 1-80 characters of letters, digits and : _ . -")
    if not isinstance(data, dict):
        raise MemoryError_("data must be a JSON object")
    raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    if len(raw.encode()) > MAX_DATA_BYTES:
        raise MemoryError_(f"data must be under {MAX_DATA_BYTES} bytes")
    return raw


def put(plugin_id: str, owner: str, key: str, data: dict) -> None:
    raw = _check(key, data)
    if _tiger_ok():
        try:
            with _conn() as conn:
                conn.execute(
                    "INSERT INTO plugin_records (plugin_id, owner, key, data, updated_at) "
                    "VALUES (%s, %s, %s, %s::jsonb, now()) ON CONFLICT (plugin_id, owner, key) "
                    "DO UPDATE SET data = EXCLUDED.data, updated_at = now()",
                    (plugin_id, owner, key, raw))
            return
        except Exception as e:  # noqa: BLE001 - fall back to memory, never fail the call
            _tiger_failed("write", e)
    with _lock:
        bucket = _mem.setdefault((plugin_id, owner), {})
        bucket[key] = (json.loads(raw), time.time())
        if len(bucket) > MAX_RECORDS_PER_PLUGIN:
            for k, _ in sorted(bucket.items(), key=lambda kv: kv[1][1])[: len(bucket) - MAX_RECORDS_PER_PLUGIN]:
                bucket.pop(k, None)


def list_records(plugin_id: str, owner: str, prefix: str = "", limit: int = 50) -> list[dict]:
    """Newest first: [{"key", "data", "updated_at": unix}]."""
    limit = max(1, min(int(limit), 500))
    prefix = prefix if isinstance(prefix, str) and len(prefix) <= 40 else ""
    if _tiger_ok():
        try:
            with _conn() as conn:
                rows = conn.execute(
                    "SELECT key, data, extract(epoch from updated_at) FROM plugin_records "
                    "WHERE plugin_id = %s AND owner = %s AND key LIKE %s "
                    "ORDER BY updated_at DESC LIMIT %s",
                    (plugin_id, owner, prefix.replace("%", "").replace("_", r"\_") + "%", limit)).fetchall()
            return [{"key": k, "data": d if isinstance(d, dict) else json.loads(d), "updated_at": int(t)}
                    for k, d, t in rows]
        except Exception as e:  # noqa: BLE001
            _tiger_failed("read", e)
    with _lock:
        items = [(k, d, t) for k, (d, t) in _mem.get((plugin_id, owner), {}).items() if k.startswith(prefix)]
    items.sort(key=lambda r: r[2], reverse=True)
    return [{"key": k, "data": d, "updated_at": int(t)} for k, d, t in items[:limit]]


def apps_for(owner: str) -> list[dict]:
    """[{"plugin_id", "records", "updated_at"}] for every plugin holding data for this person."""
    if _tiger_ok():
        try:
            with _conn() as conn:
                rows = conn.execute(
                    "SELECT plugin_id, count(*), extract(epoch from max(updated_at)) FROM plugin_records "
                    "WHERE owner = %s GROUP BY plugin_id ORDER BY max(updated_at) DESC", (owner,)).fetchall()
            return [{"plugin_id": p, "records": int(n), "updated_at": int(t)} for p, n, t in rows]
        except Exception as e:  # noqa: BLE001
            _tiger_failed("read", e)
    with _lock:
        out = [{"plugin_id": p, "records": len(b), "updated_at": int(max(t for _, t in b.values()))}
               for (p, o), b in _mem.items() if o == owner and b]
    return sorted(out, key=lambda a: a["updated_at"], reverse=True)


# --- flashcards (spaced repetition) ---------------------------------------------------------------

def _cards(plugin_id: str, owner: str) -> list[dict]:
    return [r["data"] for r in list_records(plugin_id, owner, "card:", 500) if isinstance(r["data"], dict)]


def deck(plugin_id: str, owner: str, now: Optional[float] = None) -> dict:
    now = time.time() if now is None else now
    cards = sorted(_cards(plugin_id, owner), key=lambda c: c.get("due_at", 0))
    return {"due": sum(1 for c in cards if c.get("due_at", 0) <= now), "total": len(cards), "cards": cards}


def add_card(plugin_id: str, owner: str, front: str, back: str, now: Optional[float] = None) -> dict:
    front, back = (front or "").strip()[:300], (back or "").strip()[:300]
    if not front or not back:
        raise MemoryError_("a card needs a front and a back")
    now = time.time() if now is None else now
    card = {"id": secrets.token_hex(6), "front": front, "back": back, "due_at": int(now),
            "interval_s": 0, "reps": 0}
    put(plugin_id, owner, f"card:{card['id']}", card)
    return card


def next_card(plugin_id: str, owner: str, now: Optional[float] = None) -> Optional[dict]:
    now = time.time() if now is None else now
    due = [c for c in _cards(plugin_id, owner) if c.get("due_at", 0) <= now]
    return min(due, key=lambda c: c.get("due_at", 0)) if due else None


def grade_card(plugin_id: str, owner: str, card_id: str, correct: bool,
               now: Optional[float] = None) -> Optional[dict]:
    now = time.time() if now is None else now
    if not isinstance(card_id, str) or not re.fullmatch(r"[0-9a-f]{12}", card_id):
        return None
    card = next((c for c in _cards(plugin_id, owner) if c.get("id") == card_id), None)
    if card is None:
        return None
    if correct:
        prev = int(card.get("interval_s") or 0)
        card["interval_s"] = FIRST_INTERVAL_S if prev < FIRST_INTERVAL_S else int(prev * GROWTH)
        card["reps"] = int(card.get("reps") or 0) + 1
    else:
        card["interval_s"] = AGAIN_S
        card["reps"] = 0
    card["due_at"] = int(now + card["interval_s"])
    put(plugin_id, owner, f"card:{card_id}", card)
    return card
