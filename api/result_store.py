"""Finished checks saved for a week, so the link in the follow-up text (scansafe.nyc/r/<id>)
works later and survives restarts. One small JSON file per scan_id in RESULT_DIR (chmod 700).

Anyone with the link can see that one result, like a shared photo link: scan ids are random
12-hex-char values (48 bits), and there is no listing endpoint.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

from api.schema import ScanResult

RESULT_DIR = Path(os.getenv("SCANSAFE_RESULT_DIR", os.path.expanduser("~/.scansafe-results")))
TTL_S = 7 * 24 * 3600
ID_RE = re.compile(r"^[a-f0-9]{6,32}$")
_saves = 0


def _path(scan_id: str) -> Path | None:
    return RESULT_DIR / f"{scan_id}.json" if ID_RE.match(scan_id or "") else None


def save(result: ScanResult) -> None:
    """Never raises: a failed save only means the text link won't work for this scan."""
    global _saves
    p = _path(result.scan_id or "")
    if p is None:
        return
    try:
        RESULT_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(result.model_dump_json())
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
        _saves += 1
        if _saves % 100 == 1:
            prune()
    except OSError:
        pass


def get(scan_id: str) -> ScanResult | None:
    p = _path(scan_id)
    if p is None or not p.exists():
        return None
    try:
        if time.time() - p.stat().st_mtime > TTL_S:
            p.unlink(missing_ok=True)
            return None
        return ScanResult.model_validate_json(p.read_text())
    except (OSError, ValueError):
        return None


def prune() -> int:
    n, now = 0, time.time()
    for p in RESULT_DIR.glob("*.json"):
        try:
            if now - p.stat().st_mtime > TTL_S:
                p.unlink()
                n += 1
        except OSError:
            pass
    return n
