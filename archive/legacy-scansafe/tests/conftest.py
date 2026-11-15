"""Shared test setup: no test ever makes a real domain-age (RDAP) lookup."""
import pytest

from api import signals


@pytest.fixture(autouse=True)
def _no_rdap(monkeypatch):
    monkeypatch.setattr(signals, "_fetch_registered", lambda site: None)
    with signals._lock:
        signals._cache.clear()
        signals._inflight.clear()
    yield
    with signals._lock:
        signals._cache.clear()
        signals._inflight.clear()


@pytest.fixture(autouse=True)
def _fresh_pay_state():
    """Parking quotes and payment statuses (api/meter_pay.py) never leak between tests."""
    from api import meter_pay
    meter_pay.clear()
    yield
    meter_pay.clear()
