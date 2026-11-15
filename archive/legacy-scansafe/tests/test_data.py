"""Offline tests for the data layer: Typesense and Tiger Data are mocked, no network."""
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import routes_data
from api.schema import ScanResult
from data import tiger_store, typesense_store

SHARED = Path(__file__).resolve().parent.parent / "shared"


def malicious(**kw) -> ScanResult:
    data = json.loads((SHARED / "mock_malicious.json").read_text())
    data.update(kw)
    return ScanResult(**data)


@pytest.fixture
def ts_env(monkeypatch):
    monkeypatch.setenv("TYPESENSE_HOST", "https://ts.example.test")
    monkeypatch.setenv("TYPESENSE_API_KEY", "test-key")


@pytest.fixture
def ts_mock(ts_env, monkeypatch):
    """Route every Typesense call to a MockTransport; returns the list of captured requests."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"found": 3, "hits": [
                {"document": {"domain": "x.test"}, "geo_distance_meters": {"location": 42}}]})
        return httpx.Response(201, json={})

    real = httpx.Client

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(typesense_store.httpx, "Client", client)
    return seen


# ---------- Typesense ----------

def test_pin_only_for_malicious_with_location():
    assert typesense_store.pin_document(malicious(verdict="safe")) is None
    assert typesense_store.pin_document(malicious(verdict="suspicious")) is None
    assert typesense_store.pin_document(malicious(location=None)) is None
    assert typesense_store.pin_document(malicious()) is not None


def test_add_pin_skips_without_calling_typesense(ts_mock):
    assert typesense_store.add_pin(malicious(verdict="safe")) is None
    assert typesense_store.add_pin(malicious(location=None)) is None
    assert ts_mock == []


def test_location_rounded_and_no_reporter(ts_mock):
    doc = typesense_store.add_pin(malicious(location=[33.792549, -84.324049]))
    assert doc["location"] == [33.793, -84.324]
    sent = json.loads(ts_mock[0].content)
    assert sent["location"] == [33.793, -84.324]
    assert set(sent) == {"id", "url", "domain", "scam_type", "jev_score", "explanation",
                         "location", "reported_at"}
    assert ts_mock[0].url.params["action"] == "upsert"
    assert ts_mock[0].headers["X-TYPESENSE-API-KEY"] == "test-key"


def test_nearby_filter_and_sort(ts_mock):
    pins = typesense_store.nearby(33.79, -84.32, radius_km=1.0)
    params = ts_mock[0].url.params
    assert params["filter_by"] == "location:(33.79, -84.32, 1.0 km)"
    assert params["sort_by"] == "location(33.79, -84.32):asc"
    assert ts_mock[0].url.path == "/collections/scam_pins/documents/search"
    assert pins[0]["distance_m"] == 42


def test_search_query_by(ts_mock):
    typesense_store.search("parking")
    params = ts_mock[0].url.params
    assert params["q"] == "parking" and params["query_by"] == "explanation,domain,url"


def test_flagged_count_filter(ts_mock):
    n = typesense_store.flagged_count("Bad.test", 33.79, -84.32)
    assert n == 3
    assert ts_mock[0].url.params["filter_by"] == "domain:=`bad.test` && location:(33.79, -84.32, 5 km)"


def test_ensure_collection_creates_when_missing(ts_env, monkeypatch):
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(404, json={"message": "Not Found"})
        body = json.loads(request.content)
        assert body["default_sorting_field"] == "reported_at"
        assert {"name": "location", "type": "geopoint"} in body["fields"]
        return httpx.Response(201, json=body)

    real = httpx.Client
    monkeypatch.setattr(typesense_store.httpx, "Client",
                        lambda *a, **k: real(*a, **{**k, "transport": httpx.MockTransport(handler)}))
    assert typesense_store.ensure_collection() is True
    assert calls == [("GET", "/collections/scam_pins"), ("POST", "/collections")]


# ---------- Tiger Data ----------

def test_record_scan_never_raises(monkeypatch):
    monkeypatch.setenv("TIGER_DATABASE_URL", "postgresql://u:p@db.invalid:5432/x")

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(tiger_store, "_connect", boom)
    routes_data.record_scan(malicious())  # must not raise

    monkeypatch.setattr(tiger_store, "log_scan", boom)
    routes_data.record_scan(malicious())


def test_record_scan_noop_without_config(monkeypatch):
    monkeypatch.delenv("TIGER_DATABASE_URL", raising=False)
    called = []
    monkeypatch.setattr(tiger_store, "log_scan", lambda r: called.append(r))
    routes_data.record_scan(malicious())
    assert called == []


def test_log_scan_inserts_row(monkeypatch):
    executed = []

    class FakeConn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params=None): executed.append((sql, params))

    monkeypatch.setattr(tiger_store, "_connect", lambda: FakeConn())
    tiger_store.log_scan(malicious(scan_ms=4200))
    sql, params = executed[0]
    assert sql.startswith("INSERT INTO scans")
    assert params[1:] == ("dogwood-meter-pay.xyz", "malicious", "fake_parking_or_toll", 0.94, 4200)


# ---------- routes ----------

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes_data.router)
    return TestClient(app)


def test_routes_503_when_not_configured(client, monkeypatch):
    for var in ("TYPESENSE_HOST", "TYPESENSE_API_KEY", "TIGER_DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    assert client.get("/pins", params={"lat": 1, "lng": 2}).status_code == 503
    assert client.get("/search", params={"q": "x"}).status_code == 503
    assert client.get("/stats/hourly").status_code == 503
    r = client.get("/stats/summary")
    assert r.status_code == 503 and r.json()["detail"]["service"] == "tiger_data"
    from api import recent_scans
    recent_scans.remember(malicious())
    assert client.post("/report", json=malicious().model_dump()).status_code == 503


def test_report_route(client, ts_mock):
    from api import recent_scans
    recent_scans.clear()
    real = malicious()
    recent_scans.remember(real)
    r = client.post("/report", json=real.model_dump())
    assert r.status_code == 200 and r.json()["stored"] is True
    # A scan this server never ran can't be pinned, whatever the body claims.
    fake = malicious(scan_id="made-up-id")
    r = client.post("/report", json=fake.model_dump())
    assert r.json()["stored"] is False and r.json()["code"] == "unknown_scan"
    # The server's copy wins: the client can't turn a safe check into a scam pin.
    safe = malicious(scan_id="safe-1", verdict="safe")
    recent_scans.remember(safe)
    r = client.post("/report", json={**safe.model_dump(), "verdict": "malicious"})
    assert r.json()["stored"] is False and r.json()["code"] == "not_malicious"
    # Only scan_id is needed.
    r = client.post("/report", json={"scan_id": real.scan_id})
    assert r.json()["stored"] is True


def test_typesense_error_is_502(client, ts_env, monkeypatch):
    def fail(*a, **k):
        raise httpx.ConnectError("nope")
    monkeypatch.setattr(typesense_store, "nearby", fail)
    assert client.get("/pins", params={"lat": 1, "lng": 2}).status_code == 502
