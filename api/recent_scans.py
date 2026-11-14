"""Results of checks this server actually ran, kept briefly in memory.

/report only accepts a scan_id that is in here and pins the server's own copy, so a client
can't invent a scam pin (any verdict, any place) or overwrite someone else's by reusing its id.
In memory is enough for a demo; a restart only means older results can't be reported.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict

from api.schema import ScanResult

TTL_S = 2 * 60 * 60
MAX_ITEMS = 2000

_lock = threading.Lock()
_items: "OrderedDict[str, tuple[float, ScanResult]]" = OrderedDict()


def remember(result: ScanResult) -> None:
    if not result.scan_id:
        return
    with _lock:
        _items[result.scan_id] = (time.monotonic(), result.model_copy(deep=True))
        _items.move_to_end(result.scan_id)
        while len(_items) > MAX_ITEMS:
            _items.popitem(last=False)


def get(scan_id: str) -> ScanResult | None:
    with _lock:
        item = _items.get(scan_id)
        if not item:
            return None
        at, result = item
        if time.monotonic() - at > TTL_S:
            _items.pop(scan_id, None)
            return None
        return result.model_copy(deep=True)


def clear() -> None:  # tests
    with _lock:
        _items.clear()
