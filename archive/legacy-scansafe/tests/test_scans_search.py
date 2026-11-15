"""Offline tests for the Typesense `scans` collection (search over the Tiger scan log).
Typesense and Tiger Data are mocked, no network."""
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import recent_scans, routes_data
from api.schema import ScanResult
from data import scan_search, setup, sync_scans, tiger_store, typesense_store

SHARED = Path(__file__).resolve().parent.parent / "shared"


def result(**kw) -> ScanResult:
    data = json.loads((SHARED / "mock_malicious.json").read_text())
    data.update(kw)
    return ScanResult(**data)


@pytest.fixture
def no_env(monkeypatch):
    for var in ("TYPESENSE_HOST", "TYPESENSE_API_KEY", "TIGER_DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def ts(no_env, monkeypatch):
    """Typesense configured and mocked. `ts.reply` maps (method, path) -> Response; `ts.seen` logs requests."""
    monkeypatch.setenv("TYPESENSE_HOST", "https://ts.example.test")
    monkeypatch.setenv("TYPESENSE_API_KEY", "test-key")

    class State:
        seen: list[httpx.Request] = []
        reply: dict = {}

    state = State()
    state.seen, state.reply = [], {}

    def handler(request: httpx.Request) -> httpx.Response:
        state.seen.append(request)
        hit = state.reply.get((request.method, request.url.path))
        if callable(hit):
            return hit(request)
        return hit or httpx.Response(201, json={})

    real = httpx.Client
    monkeypatch.setattr(typesense_store.httpx, "Client",
                        lambda *a, **k: real(*a, **{**k, "transport": httpx.MockTransport(handler)}))
    return state


SEARCH_PATH = "/collections/scans/documents/search"


# ---------- documents ----------

def test_live_doc_and_backfilled_row_share_the_id():
    r = result(scan_ms=4200)
    t, domain, verdict, scam_type, jev, ms = tiger_store.scan_row(r)
    # What psycopg hands back for that row: an aware datetime and the same values.
    row = {"time": t.astimezone(timezone.utc), "domain": domain, "verdict": verdict,
           "scam_type": scam_type, "jev_score": jev, "scan_ms": ms}
    assert scan_search.result_document(r)["id"] == scan_search.row_document(row)["id"]
    assert scan_search.doc_id(row) == scan_search.doc_id(dict(row))           # deterministic
    assert scan_search.doc_id({**row, "scan_ms": 4201}) != scan_search.doc_id(row)


def test_row_document_has_only_tiger_fields():
    row = {"time": datetime(2026, 11, 14, 17, 10, 6, tzinfo=timezone.utc), "domain": None,
           "verdict": "safe", "scam_type": "none", "jev_score": 0.035, "scan_ms": None}
    doc = scan_search.row_document(row)
    assert doc["domain"] == "" and doc["scanned_at"] == 1794676206
    assert set(doc) == {"id", "domain", "verdict", "scam_type", "jev_score", "scanned_at"}


def test_result_document_strips_query_and_never_has_location():
    r = result(url="https://user:pw@Dogwood-Meter-Pay.xyz/pay/spot?plate=ABC123&email=a@b.c#x",
               final_url="https://dogwood-meter-pay.xyz:8443/checkout?session=secret",
               page_title="Pay for parking", location=[33.7925, -84.324])
    doc = scan_search.result_document(r)
    assert doc["url"] == "https://dogwood-meter-pay.xyz/pay/spot"
    assert doc["final_url"] == "https://dogwood-meter-pay.xyz:8443/checkout"
    assert doc["page_title"] == "Pay for parking"
    assert "location" not in doc
    assert set(doc) <= {"id", "domain", "verdict", "scam_type", "jev_score", "scan_ms", "scanned_at",
                        "url", "final_url", "page_title", "explanation"}


@pytest.mark.parametrize("raw, stored", [
    ("WIFI:S:HomeNet;T:WPA;P:hunter2;;", None),
    ("BEGIN:VCARD\nFN:Jane Doe\nTEL:555\nEND:VCARD", None),
    ("mailto:jane@example.com", None),
    ("just some text", None),
    ("solana:7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU?amount=1&memo=hi", "solana:7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"),
    ("https://en.wikipedia.org/wiki/Atlanta", "https://en.wikipedia.org/wiki/Atlanta"),
    ("http://example.com", "http://example.com/"),
    ("https://example.com:99999/x", None),   # invalid port
])
def test_clean_url(raw, stored):
    assert scan_search.clean_url(raw) == stored


# ---------- writes ----------

def test_index_scan_emplaces(ts):
    doc = scan_search.index_scan(result())
    req = ts.seen[0]
    assert (req.method, req.url.path) == ("POST", "/collections/scans/documents")
    assert req.url.params["action"] == "emplace"
    assert json.loads(req.content) == doc
    assert req.headers["X-TYPESENSE-API-KEY"] == "test-key"


def test_record_scan_indexes_even_if_tiger_fails(ts, monkeypatch):
    monkeypatch.setenv("TIGER_DATABASE_URL", "postgresql://u:p@db.invalid:5432/x")
    monkeypatch.setattr(tiger_store, "log_scan", lambda r: (_ for _ in ()).throw(RuntimeError("db down")))
    routes_data.record_scan(result())
    assert [r.url.path for r in ts.seen] == ["/collections/scans/documents"]


def test_record_scan_never_raises_when_typesense_fails(ts, monkeypatch):
    logged = []
    monkeypatch.setenv("TIGER_DATABASE_URL", "postgresql://u:p@db.invalid:5432/x")
    monkeypatch.setattr(tiger_store, "log_scan", logged.append)
    ts.reply[("POST", "/collections/scans/documents")] = httpx.Response(500, json={})
    routes_data.record_scan(result())   # must not raise
    assert len(logged) == 1             # Tiger still got the row

    def boom(request):
        raise httpx.ConnectError("down")
    ts.reply[("POST", "/collections/scans/documents")] = boom
    routes_data.record_scan(result())


def test_record_scan_skips_typesense_without_config(no_env, monkeypatch):
    called = []
    monkeypatch.setattr(scan_search, "index_scan", called.append)
    routes_data.record_scan(result())
    assert called == []


def test_set_location_patches_rounded_point(ts):
    r = result(location=[33.792549, -84.324049])
    assert scan_search.set_location(r) is True
    req = ts.seen[0]
    assert req.method == "PATCH"
    assert req.url.path == f"/collections/scans/documents/{scan_search.result_document(r)['id']}"
    assert json.loads(req.content) == {"location": [33.793, -84.324]}
    ts.seen.clear()
    assert scan_search.set_location(result(location=None)) is False and ts.seen == []


def test_import_documents_counts_failures(ts):
    ts.reply[("POST", "/collections/scans/documents/import")] = httpx.Response(
        200, text='{"success":true}\n{"success":false,"error":"Bad field"}\n')
    ok, errors = scan_search.import_documents([{"id": "a"}, {"id": "b"}])
    assert ok == 1 and errors == ["Bad field"]
    req = ts.seen[0]
    assert req.url.params["action"] == "emplace"
    assert [json.loads(line)["id"] for line in req.content.decode().splitlines()] == ["a", "b"]


def test_ensure_collection_schema(ts):
    ts.reply[("GET", "/collections/scans")] = httpx.Response(404, json={})
    assert scan_search.ensure_collection() is True
    body = json.loads(ts.seen[1].content)
    assert body["name"] == "scans" and body["default_sorting_field"] == "scanned_at"
    fields = {f["name"]: f for f in body["fields"]}
    assert fields["verdict"]["facet"] and fields["scam_type"]["facet"] and fields["domain"]["facet"]
    assert fields["location"] == {"name": "location", "type": "geopoint", "optional": True}
    assert "." in body["token_separators"]


def test_setup_creates_both_collections(ts, capsys):
    ts.reply[("GET", "/collections/scam_pins")] = httpx.Response(200, json={})
    ts.reply[("GET", "/collections/scans")] = httpx.Response(404, json={})
    assert setup.main() == 1   # Tiger isn't configured here
    out = capsys.readouterr().out
    assert "OK   Typesense: scam_pins exists" in out and "OK   Typesense: created scans" in out
    assert "SKIP Tiger Data" in out and "test-key" not in out


# ---------- backfill ----------

class FakeConn:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self): return self
    def __exit__(self, *a): return False

    def execute(self, sql, params=None):
        assert sql == sync_scans.SELECT_SQL
        rows = list(self.rows)

        class Cur:
            def fetchmany(self, n):
                out = rows[:n]
                del rows[:n]
                return out
        return Cur()


TIGER_ROWS = [
    {"time": datetime(2026, 11, 14, 17, 10, i, tzinfo=timezone.utc), "domain": d, "verdict": v,
     "scam_type": s, "jev_score": j, "scan_ms": 4800 + i}
    for i, (d, v, s, j) in enumerate([
        ("en.wikipedia.org", "safe", "none", 0.03), ("example.com", "safe", "none", 0.02),
        ("scansafe-demo-sites.vercel.app", "malicious", "fake_parking_or_toll", 0.98)])
]


def test_sync_is_idempotent(ts, monkeypatch, capsys):
    monkeypatch.setenv("TIGER_DATABASE_URL", "postgresql://u:p@db.invalid:5432/x")
    monkeypatch.setattr(tiger_store, "_connect", lambda: FakeConn(TIGER_ROWS))
    ts.reply[("GET", "/collections/scans")] = httpx.Response(200, json={"num_documents": 3})

    def imported(request):
        n = len(request.content.decode().splitlines())
        return httpx.Response(200, text="\n".join(['{"success":true}'] * n))
    ts.reply[("POST", "/collections/scans/documents/import")] = imported

    def run():
        ts.seen.clear()
        assert sync_scans.main([]) == 0
        bodies = [r.content.decode() for r in ts.seen if r.url.path.endswith("/import")]
        return [json.loads(line) for body in bodies for line in body.splitlines()], len(bodies)

    first, batches = run()
    assert batches == 1
    second, _ = run()
    assert [d["id"] for d in first] == [d["id"] for d in second]     # same ids every run
    assert len({d["id"] for d in first}) == 3
    assert first[0]["domain"] == "en.wikipedia.org" and "url" not in first[0]
    out = capsys.readouterr().out
    assert "OK   synced 3 Tiger rows -> 3 docs" in out and "invalid" not in out


def test_sync_batches_and_prunes(ts, monkeypatch):
    monkeypatch.setenv("TIGER_DATABASE_URL", "postgresql://u:p@db.invalid:5432/x")
    monkeypatch.setattr(tiger_store, "_connect", lambda: FakeConn(TIGER_ROWS))
    ts.reply[("GET", "/collections/scans")] = httpx.Response(200, json={"num_documents": 3})
    ts.reply[("POST", "/collections/scans/documents/import")] = lambda req: httpx.Response(
        200, text="\n".join(['{"success":true}'] * len(req.content.decode().splitlines())))
    keep = scan_search.row_document(TIGER_ROWS[0])["id"]
    ts.reply[("GET", "/collections/scans/documents/export")] = httpx.Response(
        200, text=json.dumps({"id": keep}) + "\n" + json.dumps({"id": "gone-from-tiger"}))
    s = sync_scans.sync(batch=2, prune=True)
    assert sum(r.url.path.endswith("/import") for r in ts.seen) == 2
    assert s["rows"] == 3 and s["ok"] == 3 and s["failed"] == 0 and s["pruned"] == 1
    deleted = [r.url.path for r in ts.seen if r.method == "DELETE"]
    assert deleted == ["/collections/scans/documents/gone-from-tiger"]


def test_sync_skips_without_config(no_env, capsys):
    assert sync_scans.main([]) == 1
    assert "SKIP" in capsys.readouterr().out


def test_sync_failure_prints_type_only(ts, monkeypatch, capsys):
    monkeypatch.setenv("TIGER_DATABASE_URL", "postgresql://u:secretpw@db.invalid:5432/x")

    def boom():
        raise RuntimeError("could not connect to postgresql://u:secretpw@db.invalid")
    monkeypatch.setattr(tiger_store, "_connect", boom)
    assert sync_scans.main([]) == 1
    out = capsys.readouterr().out
    assert "FAIL sync_scans: RuntimeError" in out and "secretpw" not in out


# ---------- search ----------

def test_browse_params_newest_first():
    p = scan_search.search_params(q="  ")
    assert p["q"] == "*" and p["sort_by"] == "scanned_at:desc" and "filter_by" not in p
    assert p["facet_by"] == "verdict,scam_type"
    assert p["query_by"] == "domain,url,final_url,page_title,explanation"
    assert scan_search.search_params(q="*")["q"] == "*"


def test_text_and_filter_params():
    p = scan_search.search_params(q="wikipedia", verdict="malicious", scam_type="fake_parking_or_toll",
                                  lat=33.79, lng=-84.32, radius_km=2, page=2, per_page=10)
    assert p["q"] == "wikipedia"
    assert p["sort_by"] == "_text_match:desc,scanned_at:desc,location(33.79, -84.32):asc"
    assert p["filter_by"] == ("verdict:=`malicious` && scam_type:=`fake_parking_or_toll` && "
                              "location:(33.79, -84.32, 2 km)")
    assert (p["page"], p["per_page"]) == (2, 10)


SEARCH_REPLY = {
    "found": 2, "out_of": 40,
    "facet_counts": [
        {"field_name": "verdict", "counts": [{"value": "safe", "count": 9}, {"value": "malicious", "count": 2}]},
        {"field_name": "scam_type", "counts": [{"value": "none", "count": 9}]},
    ],
    "hits": [
        {"document": {"id": "a1", "domain": "en.wikipedia.org", "verdict": "safe", "scam_type": "none",
                      "jev_score": 0.03, "scanned_at": 1794675006, "url": "https://en.wikipedia.org/wiki/Atlanta",
                      "page_title": "<img src=x onerror=alert(1)> Atlanta"},
         "highlight": {
             "domain": {"matched_tokens": ["wikipedia"], "snippet": "en.[[ss-mark]]wikipedia[[/ss-mark]].org"},
             "page_title": {"matched_tokens": ["Atl"],
                            "snippet": "<img src=x onerror=alert(1)> [[ss-mark]]Atl[[/ss-mark]]anta"},
             "explanation": {"matched_tokens": [], "snippet": "nothing"}}},
        {"document": {"id": "b2", "domain": "x.test", "verdict": "malicious", "scam_type": "other",
                      "jev_score": 0.9, "scanned_at": 1, "location": [33.79, -84.32]},
         "geo_distance_meters": {"location": 120}},
    ],
}


def test_search_shapes_hits_and_facets(ts):
    ts.reply[("GET", SEARCH_PATH)] = httpx.Response(200, json=SEARCH_REPLY)
    out = scan_search.search(q="wikipedia")
    assert out["found"] == 2 and out["out_of"] == 40 and out["page"] == 1 and out["per_page"] == 20
    assert out["facets"] == {"verdict": {"safe": 9, "malicious": 2}, "scam_type": {"none": 9}}
    a, b = out["hits"]
    assert a["url"] == "https://en.wikipedia.org/wiki/Atlanta" and a["final_url"] is None
    assert a["reported"] is False and "distance_m" not in a
    assert a["highlight"]["domain"] == "en.<mark>wikipedia</mark>.org"
    assert a["highlight"]["page_title"] == "&lt;img src=x onerror=alert(1)&gt; <mark>Atl</mark>anta"
    assert "explanation" not in a["highlight"]
    assert b["reported"] is True and b["distance_m"] == 120 and "highlight" not in b
    assert "location" not in b


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes_data.router)
    return TestClient(app)


def test_route_503_when_not_configured(client, no_env):
    r = client.get("/scans/search", params={"q": "x"})
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert detail["error"] == "typesense_not_configured" and detail["service"] == "typesense"
    assert detail["message"].startswith("Scan search is unavailable")


def test_route_validates_params(client, ts):
    assert client.get("/scans/search", params={"verdict": "evil"}).status_code == 422
    assert client.get("/scans/search", params={"scam_type": "nope"}).status_code == 422
    assert client.get("/scans/search", params={"per_page": 500}).status_code == 422
    r = client.get("/scans/search", params={"lat": 33.79})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "bad_location"
    assert ts.seen == []


def test_route_200_passes_filters(client, ts):
    ts.reply[("GET", SEARCH_PATH)] = httpx.Response(200, json=SEARCH_REPLY)
    r = client.get("/scans/search", params={"q": "examp", "verdict": "safe", "page": 2, "per_page": 5})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"found", "out_of", "page", "per_page", "hits", "facets"}
    params = ts.seen[0].url.params
    assert params["q"] == "examp" and params["filter_by"] == "verdict:=`safe`"
    assert params["page"] == "2" and params["per_page"] == "5"
    # Empty q browses.
    client.get("/scans/search")
    assert ts.seen[1].url.params["q"] == "*" and ts.seen[1].url.params["sort_by"] == "scanned_at:desc"


def test_route_502_on_typesense_error(client, ts):
    ts.reply[("GET", SEARCH_PATH)] = httpx.Response(404, json={"message": "Not found"})
    r = client.get("/scans/search", params={"q": "x"})
    assert r.status_code == 502 and r.json()["detail"]["error"] == "typesense_error"


def test_report_adds_location_to_scan_doc(client, ts):
    recent_scans.clear()
    r = result(location=[33.792549, -84.324049])
    recent_scans.remember(r)
    resp = client.post("/report", json={"scan_id": r.scan_id})
    assert resp.status_code == 200 and resp.json()["stored"] is True
    patches = [q for q in ts.seen if q.method == "PATCH"]
    assert len(patches) == 1 and json.loads(patches[0].content) == {"location": [33.793, -84.324]}
    # A scan that was never indexed (404) still reports fine.
    ts.reply[("PATCH", patches[0].url.path)] = httpx.Response(404, json={})
    assert client.post("/report", json={"scan_id": r.scan_id}).json()["stored"] is True
    recent_scans.clear()


def test_safe_scans_index_only_domain_not_url_or_title():
    from api.schema import ScanResult
    import json
    from pathlib import Path
    data = json.loads((Path(__file__).resolve().parent.parent / "shared" / "mock_safe.json").read_text())
    data.update(verdict="safe", url="https://docs.example.com/d/SECRET-DOC-ID/edit",
                final_url="https://docs.example.com/d/SECRET-DOC-ID/edit", page_title="My private doc")
    doc = scan_search.result_document(ScanResult(**data))
    assert "url" not in doc and "final_url" not in doc and "page_title" not in doc
    assert "SECRET-DOC-ID" not in json.dumps(doc)
