"""Offline tests for /stats/impact, /stats/domain/{domain}, the payment-refusal counter and
GET /auth/me. Tiger Data is mocked (fake connection or patched store functions), no network."""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import impact, routes_call, routes_data
from api.schema import Payment, ScanResult
from data import tiger_store

SHARED = Path(__file__).resolve().parent.parent / "shared"
FTC_2024 = ("https://www.ftc.gov/news-events/news/press-releases/2025/03/"
            "new-ftc-data-show-big-jump-reported-losses-fraud-125-billion-2024")
FTC_TEXT = ("https://www.ftc.gov/news-events/news/press-releases/2025/04/"
            "new-ftc-data-show-top-text-message-scams-2024-overall-losses-text-scams-hit-470-million")
T1 = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 11, 14, 19, 30, tzinfo=timezone.utc)


def malicious(**kw) -> ScanResult:
    data = json.loads((SHARED / "mock_malicious.json").read_text())
    data.update(kw)
    return ScanResult(**data)


def scam_payment(amount=0.01, verified=False) -> ScanResult:
    pay = Payment(recipient="Scam111111111111111111111111111111111111111", amount_sol=amount,
                  label="Peachtree Parking Co.", merchant_verified=verified)
    return malicious(scan_id="pay123abc456", url="solana:x", domain=None, scam_type="fake_payment_app",
                     verdict="safe" if verified else "malicious", payment=pay, scan_ms=None)


@pytest.fixture(autouse=True)
def _fresh_caches(monkeypatch):
    routes_data._impact_cache.clear()
    routes_data._domain_cache.clear()
    monkeypatch.delenv("IMPACT_LOSS_PER_SCAM_USD", raising=False)
    monkeypatch.setattr(tiger_store, "_refusals_table_ready", False)


@pytest.fixture
def tiger_env(monkeypatch):
    monkeypatch.setenv("TIGER_DATABASE_URL", "postgresql://u:p@db.invalid:5432/x")


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes_data.router)
    app.include_router(routes_call.router)
    return TestClient(app)


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakeConn:
    """Answers by matching a fragment of the SQL; records (sql, params) for every statement."""

    def __init__(self, answers: dict):
        self.answers, self.executed = answers, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        for fragment, rows in self.answers.items():
            if fragment in sql:
                return FakeCursor(rows)
        return FakeCursor([])


# ---------- the estimate ----------

def test_default_estimate_is_110_with_ftc_sources():
    loss = impact.loss_per_scam_usd()
    assert loss == 110 and isinstance(loss, int)
    m = impact.est_method(loss)
    assert m["loss_per_scam_usd"] == 110
    assert m["explanation"] == ("In 2024, 11% of fraud reports about scams that began with a text involved a "
                                "loss, and the median loss was $1,000, so each blocked scam avoids about $110 "
                                "on average (estimate).")
    assert m["sources"][:2] == [FTC_2024, FTC_TEXT]
    assert all(s.startswith("https://www.ftc.gov/") for s in m["sources"])


def test_money_saved_math():
    assert impact.money_saved_usd(0, 380) == 0
    assert impact.money_saved_usd(7, 380) == 2660
    assert impact.money_saved_usd(3, 412.5) == 1237.5
    assert impact.money_saved_usd(-4, 380) == 0       # never negative


@pytest.mark.parametrize("raw,expected", [("380", 380), (" 412.50 ", 412.5), ("0", 0),
                                          ("abc", 110), ("-5", 110), ("nan", 110), ("inf", 110), ("", 110)])
def test_loss_override_env(monkeypatch, raw, expected):
    monkeypatch.setenv("IMPACT_LOSS_PER_SCAM_USD", raw)
    assert impact.loss_per_scam_usd() == expected


def test_override_rewrites_the_explanation(monkeypatch):
    m = impact.est_method(380)
    assert m["loss_per_scam_usd"] == 380
    assert "$380" in m["explanation"] and "$110" not in m["explanation"]


@pytest.mark.parametrize("amount,stored", [(0.01, 0.01), (5, 5.0), (0, None), (-1, None), (math.nan, None),
                                           (math.inf, None), (5000, None), ("x", None), (None, None)])
def test_refused_amount_is_sane(amount, stored):
    assert impact.refused_amount_sol(amount) == stored


# ---------- Tiger queries ----------

def test_impact_counts_queries_and_shape(monkeypatch):
    conn = FakeConn({
        "FROM scans_hourly": [{"verdict": "safe", "total": 40}, {"verdict": "malicious", "total": 7},
                              {"verdict": "suspicious", "total": 3}, {"verdict": None, "total": 1}],
        "INTERVAL '24 hours'": [{"total": 12}],
        "GROUP BY domain": [{"domain": "peachtree-parking-pay.xyz", "times_checked": 5, "times_flagged": 5,
                             "first_seen": T1, "last_seen": T2, "scam_type": "fake_parking_or_toll"},
                            {"domain": "odd.example", "times_checked": 2, "times_flagged": 2,
                             "first_seen": T1, "last_seen": T1, "scam_type": None}],
        "to_regclass": [{"present": True}],
        "FROM payment_refusals": [{"count": 2, "sol_total": 0.03}],
    })
    monkeypatch.setattr(tiger_store, "_connect", lambda: conn)
    out = tiger_store.impact_counts()
    assert out["by_verdict"] == {"safe": 40, "suspicious": 3, "malicious": 7}
    assert out["scans_total"] == 50 and out["scans_24h"] == 12
    assert out["payments_refused"] == {"count": 2, "sol_total": 0.03}
    assert out["repeat_scams"][0] == {"domain": "peachtree-parking-pay.xyz", "times_checked": 5,
                                      "times_flagged": 5, "first_seen": "2026-11-14T15:00:00+00:00",
                                      "last_seen": "2026-11-14T19:30:00+00:00",
                                      "scam_type": "fake_parking_or_toll"}
    assert out["repeat_scams"][1]["scam_type"] == "other"
    # The repeat-scam query is parameterized (verdict list and limit), nothing is interpolated.
    sql, params = next((s, p) for s, p in conn.executed if "GROUP BY domain" in s)
    assert params == {"flagged": ["malicious", "suspicious"], "limit": 10}
    assert "%(flagged)s" in sql and "%(limit)s" in sql and "HAVING count(*) > 1" in sql


def test_impact_counts_without_refusals_table(monkeypatch):
    conn = FakeConn({"to_regclass": [{"present": False}]})
    monkeypatch.setattr(tiger_store, "_connect", lambda: conn)
    out = tiger_store.impact_counts()
    assert out["by_verdict"] == {"safe": 0, "suspicious": 0, "malicious": 0}
    assert out["scans_total"] == 0 and out["repeat_scams"] == []
    assert out["payments_refused"] == {"count": 0, "sol_total": 0.0}
    assert not any("FROM payment_refusals" in s for s, _ in conn.executed)   # no query on a missing table


def test_domain_stats_is_parameterized(monkeypatch):
    conn = FakeConn({"WHERE domain = %s": [{"times_checked": 4, "safe": 1, "suspicious": 1, "malicious": 2,
                                            "first_seen": T1, "last_seen": T2}]})
    monkeypatch.setattr(tiger_store, "_connect", lambda: conn)
    out = tiger_store.domain_stats("peachtree-parking-pay.xyz")
    assert out == {"domain": "peachtree-parking-pay.xyz", "times_checked": 4, "times_flagged": 3,
                   "first_seen": "2026-11-14T15:00:00+00:00", "last_seen": "2026-11-14T19:30:00+00:00",
                   "verdicts": {"safe": 1, "suspicious": 1, "malicious": 2}}
    sql, params = conn.executed[0]
    assert params == ("peachtree-parking-pay.xyz",) and "peachtree" not in sql


def test_domain_stats_never_seen(monkeypatch):
    conn = FakeConn({"WHERE domain = %s": [{"times_checked": 0, "safe": 0, "suspicious": 0, "malicious": 0,
                                            "first_seen": None, "last_seen": None}]})
    monkeypatch.setattr(tiger_store, "_connect", lambda: conn)
    out = tiger_store.domain_stats("new.example")
    assert out["times_checked"] == 0 and out["times_flagged"] == 0
    assert out["first_seen"] is None and out["verdicts"] == {"safe": 0, "suspicious": 0, "malicious": 0}


def test_log_payment_refusal_creates_table_once_and_dedupes(monkeypatch):
    conn = FakeConn({})
    monkeypatch.setattr(tiger_store, "_connect", lambda: conn)
    tiger_store.log_payment_refusal("abc", "merchant_not_verified", 0.01, "scan")
    tiger_store.log_payment_refusal("def", "merchant_not_verified", None, "scan")
    creates = [s for s, _ in conn.executed if s.startswith("CREATE TABLE IF NOT EXISTS payment_refusals")]
    inserts = [(s, p) for s, p in conn.executed if s.startswith("INSERT INTO payment_refusals")]
    assert len(creates) == 1 and len(inserts) == 2
    assert "ON CONFLICT (scan_id) DO NOTHING" in inserts[0][0]
    assert inserts[0][1] == ("abc", "merchant_not_verified", 0.01, "scan")
    assert tiger_store.PAYMENT_REFUSALS_SQL in tiger_store.SCHEMA_SQL     # data.setup creates it too


# ---------- payment refusals from scans ----------

def test_scam_payment_scan_is_counted(tiger_env, monkeypatch):
    seen = []
    monkeypatch.setattr(tiger_store, "log_payment_refusal", lambda *a: seen.append(a))
    routes_data.record_payment_refusal(scam_payment(amount=0.01))
    assert seen == [("pay123abc456", "merchant_not_verified", 0.01, "scan")]
    seen.clear()
    routes_data.record_payment_refusal(scam_payment(amount=1e12))    # crafted amount: counted, not summed
    assert seen[0][2] is None


def test_only_refused_payments_are_counted(tiger_env, monkeypatch):
    seen = []
    monkeypatch.setattr(tiger_store, "log_payment_refusal", lambda *a: seen.append(a))
    routes_data.record_payment_refusal(scam_payment(verified=True))   # real merchant
    routes_data.record_payment_refusal(malicious())                   # a web scam, no payment
    assert seen == []


def test_refusal_counter_never_raises_and_skips_without_tiger(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(tiger_store, "log_payment_refusal", boom)
    monkeypatch.setenv("TIGER_DATABASE_URL", "postgresql://u:p@db.invalid:5432/x")
    routes_data.record_payment_refusal(scam_payment())     # must not raise
    monkeypatch.delenv("TIGER_DATABASE_URL")
    monkeypatch.setattr(tiger_store, "log_payment_refusal", lambda *a: pytest.fail("called without Tiger"))
    routes_data.record_payment_refusal(scam_payment())


def test_record_scan_also_counts_the_refusal(tiger_env, monkeypatch):
    seen = []
    monkeypatch.setattr(tiger_store, "log_scan", lambda r: seen.append("scan"))
    monkeypatch.setattr(tiger_store, "log_payment_refusal", lambda *a: seen.append("refusal"))
    monkeypatch.delenv("TYPESENSE_HOST", raising=False)
    routes_data.record_scan(scam_payment())
    assert seen == ["scan", "refusal"]


# ---------- routes ----------

COUNTS = {"by_verdict": {"safe": 40, "suspicious": 3, "malicious": 7}, "scans_total": 50, "scans_24h": 12,
          "repeat_scams": [{"domain": "peachtree-parking-pay.xyz", "times_checked": 5, "times_flagged": 5,
                            "first_seen": "2026-11-14T15:00:00+00:00", "last_seen": "2026-11-14T19:30:00+00:00",
                            "scam_type": "fake_parking_or_toll"}],
          "payments_refused": {"count": 2, "sol_total": 0.03}}


def test_stats_routes_503_when_not_configured(client, monkeypatch):
    monkeypatch.delenv("TIGER_DATABASE_URL", raising=False)
    for path in ("/stats/impact", "/stats/domain/example.com"):
        r = client.get(path)
        assert r.status_code == 503
        assert r.json() == {"detail": {"error": "tiger_not_configured", "service": "tiger_data",
                                       "message": "Stats are unavailable: set TIGER_DATABASE_URL."}}


def test_stats_impact_route(client, tiger_env, monkeypatch):
    calls = []
    monkeypatch.setattr(tiger_store, "impact_counts", lambda: calls.append(1) or COUNTS)
    r = client.get("/stats/impact")
    assert r.status_code == 200
    j = r.json()
    assert {k: j[k] for k in ("scans_total", "scans_24h", "scams_blocked", "warned", "safe")} == \
        {"scans_total": 50, "scans_24h": 12, "scams_blocked": 7, "warned": 3, "safe": 40}
    assert j["est_money_saved_usd"] == 7 * 380
    assert j["est_method"]["loss_per_scam_usd"] == 380 and j["est_method"]["sources"][:2] == [FTC_2024, FTC_TEXT]
    assert j["payments_refused"]["count"] == 2 and j["payments_refused"]["sol_total"] == 0.03
    assert "USD" in j["payments_refused"]["note"]
    assert j["repeat_scams"] == COUNTS["repeat_scams"]
    assert datetime.fromisoformat(j["generated_at"]).tzinfo is not None
    # Cached: polling again within 15 s doesn't hit Tiger.
    assert client.get("/stats/impact").json() == j and calls == [1]


def test_stats_impact_env_override(client, tiger_env, monkeypatch):
    monkeypatch.setenv("IMPACT_LOSS_PER_SCAM_USD", "110")
    monkeypatch.setattr(tiger_store, "impact_counts", lambda: COUNTS)
    j = client.get("/stats/impact").json()
    assert j["est_money_saved_usd"] == 770 and j["est_method"]["loss_per_scam_usd"] == 110


def test_stats_impact_error_is_502_and_not_cached(client, tiger_env, monkeypatch):
    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(tiger_store, "impact_counts", boom)
    r = client.get("/stats/impact")
    assert r.status_code == 502 and r.json()["detail"]["error"] == "tiger_data_error"
    monkeypatch.setattr(tiger_store, "impact_counts", lambda: COUNTS)
    assert client.get("/stats/impact").status_code == 200


def test_stats_domain_route(client, tiger_env, monkeypatch):
    calls = []

    def fake(domain):
        calls.append(domain)
        return {"domain": domain, "times_checked": 4, "times_flagged": 3, "first_seen": "2026-11-14T15:00:00+00:00",
                "last_seen": "2026-11-14T19:30:00+00:00", "verdicts": {"safe": 1, "suspicious": 1, "malicious": 2}}
    monkeypatch.setattr(tiger_store, "domain_stats", fake)
    r = client.get("/stats/domain/Peachtree-Parking-Pay.XYZ")     # case-insensitive
    assert r.status_code == 200 and r.json()["domain"] == "peachtree-parking-pay.xyz"
    assert r.json()["times_checked"] == 4
    client.get("/stats/domain/peachtree-parking-pay.xyz")
    assert calls == ["peachtree-parking-pay.xyz"]                  # second call served from the cache


@pytest.mark.parametrize("bad", ["exa_mple.com", "-start.com", "end-.com", "a" * 254, "evil.com%27%3B--",
                                 "sp ace.com", "xn--caf%C3%A9.com", ".dot.com"])
def test_stats_domain_rejects_non_hostnames(client, tiger_env, monkeypatch, bad):
    monkeypatch.setattr(tiger_store, "domain_stats", lambda d: pytest.fail("bad domain reached Tiger"))
    r = client.get(f"/stats/domain/{bad}")
    assert r.status_code == 422 and r.json()["detail"]["error"] == "bad_domain"


# ---------- GET /auth/me ----------

@pytest.fixture
def consent(monkeypatch, tmp_path):
    monkeypatch.setattr(routes_call, "CONSENT_FILE", str(tmp_path / "consent.json"))


def test_auth_me_signed_out(client, consent):
    assert client.get("/auth/me").json() == {"signed_in": False}
    assert client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"}).json() == \
        {"signed_in": False}
    assert client.get("/auth/me", headers={"Authorization": "Basic abc"}).json() == {"signed_in": False}


def test_auth_me_signed_in_masks_the_phone(client, consent):
    token = routes_call._issue_token("+14045559861")
    for scheme in ("Bearer", "bearer"):
        r = client.get("/auth/me", headers={"Authorization": f"{scheme} {token}"})
        assert r.json() == {"signed_in": True, "phone_masked": "•••9861"}
        assert "4045559861" not in r.text and "+1404" not in r.text
        assert r.headers["cache-control"] == "no-store"


def test_auth_me_expired_token(client, consent, monkeypatch):
    token = routes_call._issue_token("+14045559861")
    monkeypatch.setattr(routes_call, "TOKEN_TTL_S", -1)
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json() == {"signed_in": False}


def test_bearer_token_parsing():
    assert routes_call.bearer_token("Bearer abc") == "abc"
    assert routes_call.bearer_token("  bearer   abc  ") == "abc"
    assert routes_call.bearer_token("abc") == "" and routes_call.bearer_token("") == ""
    assert routes_call.mask_phone("+14045559861") == "•••9861"
