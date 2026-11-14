"""The money estimate behind GET /stats/impact, plus a tiny TTL cache for the stats routes.

est_money_saved_usd = scams_blocked x loss_per_scam_usd. Refused payments are reported in SOL
only: the payment demo runs on Solana devnet (test tokens with no market value), so there is no
defensible USD price to convert them with.
"""
from __future__ import annotations

import logging
import math
import os
import threading
import time
from collections import OrderedDict
from typing import Any, Callable

log = logging.getLogger("scansafe.impact")

DEFAULT_LOSS_PER_SCAM_USD = 110
EXPLANATION = ("In 2024, 11% of fraud reports about scams that began with a text involved a loss, and the "
               "median loss was $1,000, so each blocked scam avoids about $110 on average (estimate).")
SOURCES = [
    "https://www.ftc.gov/news-events/news/press-releases/2025/03/new-ftc-data-show-big-jump-reported-losses-fraud-125-billion-2024",
    "https://www.ftc.gov/news-events/news/press-releases/2025/04/new-ftc-data-show-top-text-message-scams-2024-overall-losses-text-scams-hit-470-million",
    # The $1,000 median for text-initiated scams is in this table (p. 12, "Amount Lost by Contact Method").
    "https://www.ftc.gov/system/files/ftc_gov/pdf/csn-annual-data-book-2024.pdf",
]
# A crafted QR code can ask for any amount: refused amounts above this aren't added to sol_total.
MAX_REFUSED_SOL = 1000.0


def _whole(x: float) -> int | float:
    return int(x) if float(x).is_integer() else x


def loss_per_scam_usd() -> int | float:
    """IMPACT_LOSS_PER_SCAM_USD if it is a finite number >= 0, else the default (110)."""
    raw = os.getenv("IMPACT_LOSS_PER_SCAM_USD", "").strip()
    if not raw:
        return DEFAULT_LOSS_PER_SCAM_USD
    try:
        v = float(raw)
    except ValueError:
        v = math.nan
    if not math.isfinite(v) or v < 0:
        log.warning("IMPACT_LOSS_PER_SCAM_USD is not a number >= 0; using %s", DEFAULT_LOSS_PER_SCAM_USD)
        return DEFAULT_LOSS_PER_SCAM_USD
    return _whole(round(v, 2))


def est_method(loss: int | float) -> dict:
    if loss == DEFAULT_LOSS_PER_SCAM_USD:
        explanation = EXPLANATION
    else:   # the operator overrode the figure, so the $110 sentence would be wrong
        explanation = (f"Each blocked scam is counted as avoiding about ${loss:,} on average (estimate set by "
                       "the operator). For reference, 11% of 2024 text-scam reports involved a loss and the median "
                       "loss for scams that began with a text was $1,000.")
    return {"loss_per_scam_usd": loss, "explanation": explanation, "sources": list(SOURCES)}


def money_saved_usd(scams_blocked: int, loss: int | float) -> int | float:
    return _whole(round(max(0, int(scams_blocked)) * float(loss), 2))


def refused_amount_sol(amount: Any) -> float | None:
    """The amount to store for a refused payment, or None (still counted, not summed)."""
    try:
        v = float(amount)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and 0 < v <= MAX_REFUSED_SOL else None


class TTLCache:
    """Results kept `ttl` seconds, at most `max_items`. Errors are never cached."""

    def __init__(self, ttl: float, max_items: int = 1024):
        self.ttl, self.max_items = ttl, max_items
        self._lock = threading.Lock()
        self._items: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()

    def get_or_set(self, key: str, compute: Callable[[], Any]) -> Any:
        now = time.monotonic()
        with self._lock:
            hit = self._items.get(key)
            if hit and now - hit[0] < self.ttl:
                return hit[1]
        value = compute()   # outside the lock: a slow query doesn't block other keys
        with self._lock:
            self._items[key] = (time.monotonic(), value)
            self._items.move_to_end(key)
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)
        return value

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
