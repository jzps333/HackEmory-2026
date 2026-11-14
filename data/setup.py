"""One-time setup: `python -m data.setup` creates the Typesense collection and Tiger Data schema.

Prints OK / FAIL / SKIP per service. Never prints keys or connection strings.
"""
from __future__ import annotations

import sys

from data import tiger_store, typesense_store


def _run(name: str, configured: bool, fn) -> bool:
    if not configured:
        print(f"SKIP {name}: not configured (see data/README.md for env vars)")
        return False
    try:
        msg = fn()
        print(f"OK   {name}{': ' + msg if msg else ''}")
        return True
    except Exception as e:  # report the error type only; messages can echo URLs with secrets
        status = getattr(getattr(e, "response", None), "status_code", None)
        print(f"FAIL {name}: {type(e).__name__}{f' (HTTP {status})' if status else ''}")
        return False


def main() -> int:
    ok_ts = _run("Typesense", typesense_store.is_configured(),
                 lambda: "created scam_pins" if typesense_store.ensure_collection() else "scam_pins exists")
    ok_tg = _run("Tiger Data", tiger_store.is_configured(),
                 lambda: (tiger_store.ensure_schema(), "scans + scans_hourly ready")[1])
    return 0 if ok_ts and ok_tg else 1


if __name__ == "__main__":
    sys.exit(main())
