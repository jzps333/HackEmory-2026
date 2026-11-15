"""Community plugins: the demo enabled set and install counts.

Enabled set: one JSON list of plugin ids at env PLUGINS_STATE_FILE (default
~/.scansafe-plugins/enabled.json), shared by every caller of the demo line. No file (or a broken
one) means the six starter plugins. Written atomically (temp file + os.replace).

Install counts: Tiger table plugin_installs (one row per install) when TIGER_DATABASE_URL is set,
created on first use. Installs Tiger couldn't take, or all of them when Tiger isn't set, are kept
in memory (a restart forgets those). Nothing here ever raises.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path

from api.plugins_index import ID_RE
from data import tiger_store

log = logging.getLogger("scansafe.plugins")

PLUGINS_STATE_FILE = os.getenv("PLUGINS_STATE_FILE") or os.path.expanduser("~/.scansafe-plugins/enabled.json")
STARTER_IDS = ("parking", "plugin-finder", "qr-checker", "safe-browser", "solana-pay", "squat-coach",
               "study-buddy")
INSTALLS_SQL = """CREATE TABLE IF NOT EXISTS plugin_installs (
    plugin_id TEXT NOT NULL,
    at        TIMESTAMPTZ NOT NULL DEFAULT now()
)"""
COUNTS_TTL_S = 30       # GET /plugins asks for counts on every load; Tiger is asked at most this often
TIGER_RETRY_S = 60      # after a Tiger error, don't try it again for this long

_lock = threading.Lock()
_mem: Counter = Counter()           # installs not stored in Tiger
_cache: tuple[float, dict] | None = None
_tiger_down_until = 0.0
_schema_ready = False


def reset() -> None:
    """Forget in-memory installs and caches (tests)."""
    global _cache, _tiger_down_until, _schema_ready
    with _lock:
        _mem.clear()
        _cache, _tiger_down_until, _schema_ready = None, 0.0, False


# --- enabled set -------------------------------------------------------------------------------

def _clean(ids) -> list[str]:
    return sorted({i for i in ids if isinstance(i, str) and ID_RE.fullmatch(i)})


def get_enabled() -> list[str]:
    """Enabled plugin ids, sorted. Missing or unreadable file: the starter set."""
    try:
        data = json.loads(Path(PLUGINS_STATE_FILE).read_text())
    except (OSError, ValueError):
        return list(STARTER_IDS)
    return _clean(data) if isinstance(data, list) else list(STARTER_IDS)


def set_enabled(ids: list[str]) -> None:
    path = Path(PLUGINS_STATE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".enabled-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(_clean(ids), f)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def change_enabled(plugin_id: str, on: bool) -> tuple[list[str], bool]:
    """Turn one plugin on or off. Returns (enabled ids, whether it was newly turned on)."""
    with _lock:
        ids = set(get_enabled())
        newly_on = on and plugin_id not in ids
        (ids.add if on else ids.discard)(plugin_id)
        set_enabled(sorted(ids))
        return sorted(ids), newly_on


# --- install counts ----------------------------------------------------------------------------

def _tiger_ok() -> bool:
    return tiger_store.is_configured() and time.monotonic() >= _tiger_down_until


def _tiger_failed(what: str, e: Exception) -> None:
    global _tiger_down_until
    _tiger_down_until = time.monotonic() + TIGER_RETRY_S
    log.warning("plugin installs: Tiger %s failed (%s)", what, type(e).__name__)   # never the URL


def _conn():
    global _schema_ready
    conn = tiger_store._connect()
    if not _schema_ready:
        try:
            conn.execute(INSTALLS_SQL)
        except Exception:
            conn.close()
            raise
        _schema_ready = True
    return conn


def record_install(plugin_id: str) -> None:
    global _cache
    if _tiger_ok():
        try:
            with _conn() as conn:
                conn.execute("INSERT INTO plugin_installs (plugin_id) VALUES (%s)", (plugin_id,))
            with _lock:
                _cache = None
            return
        except Exception as e:  # noqa: BLE001 - counts must never break a request
            _tiger_failed("insert", e)
    with _lock:
        _mem[plugin_id] += 1
        _cache = None


def install_counts() -> dict[str, int]:
    """{plugin_id: installs}. Tiger rows plus the ones only in memory; cached for COUNTS_TTL_S."""
    global _cache
    with _lock:
        if _cache and time.monotonic() - _cache[0] < COUNTS_TTL_S:
            return dict(_cache[1])
    counts: Counter = Counter()
    if _tiger_ok():
        try:
            with _conn() as conn:
                rows = conn.execute("SELECT plugin_id, count(*) AS n FROM plugin_installs "
                                    "GROUP BY plugin_id").fetchall()
            counts.update({r["plugin_id"]: int(r["n"]) for r in rows})
        except Exception as e:  # noqa: BLE001
            _tiger_failed("count", e)
    with _lock:
        counts.update(_mem)
        out = {k: v for k, v in counts.items() if v > 0}
        _cache = (time.monotonic(), out)
        return dict(out)
