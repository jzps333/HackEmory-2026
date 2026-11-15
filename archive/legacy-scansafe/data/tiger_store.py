"""Tiger Data (TimescaleDB): every scan over time, for the dashboard.

Config (env): TIGER_DATABASE_URL (postgres connection string). Never log it.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from urllib.parse import urlparse

from dotenv import load_dotenv

from api.schema import ScanResult

load_dotenv()

CONNECT_TIMEOUT = 5

# Scam payment requests ScanSafe refused (wallet doesn't match the merchant). One row per scan_id.
# Also created on first use by log_payment_refusal, so a server that ran setup before this
# table existed doesn't need setup again.
PAYMENT_REFUSALS_SQL = """CREATE TABLE IF NOT EXISTS payment_refusals (
    time       TIMESTAMPTZ NOT NULL DEFAULT now(),
    scan_id    TEXT PRIMARY KEY,
    reason     TEXT NOT NULL,
    amount_sol DOUBLE PRECISION,
    source     TEXT NOT NULL
)"""

SCHEMA_SQL = [
    """CREATE TABLE IF NOT EXISTS scans (
        time      TIMESTAMPTZ NOT NULL,
        domain    TEXT,
        verdict   TEXT,
        scam_type TEXT,
        jev_score DOUBLE PRECISION,
        scan_ms   INTEGER
    )""",
    "SELECT create_hypertable('scans', 'time', if_not_exists => TRUE)",
    """CREATE MATERIALIZED VIEW IF NOT EXISTS scans_hourly
        WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
        SELECT time_bucket(INTERVAL '1 hour', time) AS hour,
               scam_type,
               verdict,
               count(*)       AS total,
               avg(jev_score) AS avg_score,
               avg(scan_ms)   AS avg_scan_ms
        FROM scans
        GROUP BY hour, scam_type, verdict
        WITH NO DATA""",
    """SELECT add_continuous_aggregate_policy('scans_hourly',
        start_offset      => INTERVAL '3 days',
        end_offset        => INTERVAL '1 minute',
        schedule_interval => INTERVAL '5 minutes',
        if_not_exists     => TRUE)""",
    # /stats/domain/{domain} and repeat_scams look scans up by domain. Additive; queries work without it.
    "CREATE INDEX IF NOT EXISTS scans_domain_time_idx ON scans (domain, time DESC)",
    PAYMENT_REFUSALS_SQL,
]

FLAGGED = ["malicious", "suspicious"]
VERDICTS = ("safe", "suspicious", "malicious")


class NotConfigured(RuntimeError):
    """Raised when TIGER_DATABASE_URL is missing."""


def is_configured() -> bool:
    return bool(os.getenv("TIGER_DATABASE_URL"))


def _connect():
    url = os.getenv("TIGER_DATABASE_URL", "")
    if not url:
        raise NotConfigured("Tiger Data is not configured (set TIGER_DATABASE_URL)")
    import psycopg  # imported lazily so the API still starts without it
    from psycopg.rows import dict_row
    # autocommit: continuous aggregates can't be created inside a transaction block
    return psycopg.connect(url, autocommit=True, connect_timeout=CONNECT_TIMEOUT, row_factory=dict_row)


def ensure_schema() -> None:
    with _connect() as conn:
        for sql in SCHEMA_SQL:
            conn.execute(sql)


def scan_row(result: ScanResult) -> tuple:
    domain = result.domain or urlparse(result.final_url or result.url).hostname or None
    return (
        datetime.fromtimestamp(result.scanned_at, tz=timezone.utc),
        domain.lower() if domain else None,
        result.verdict,
        result.scam_type,
        float(result.jev_score),
        result.scan_ms,
    )


def log_scan(result: ScanResult) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO scans (time, domain, verdict, scam_type, jev_score, scan_ms) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            scan_row(result),
        )


def _jsonable(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        out.append({k: (v.isoformat() if isinstance(v, datetime) else
                        float(v) if v is not None and not isinstance(v, (int, float, str, bool)) else v)
                    for k, v in row.items()})
    return out


def hourly_stats(hours: int = 24) -> list[dict]:
    """Rows from the continuous aggregate: hour, scam_type, verdict, total, avg_score, avg_scan_ms."""
    hours = max(1, min(int(hours), 24 * 30))
    with _connect() as conn:
        rows = conn.execute(
            "SELECT hour, scam_type, verdict, total, avg_score, avg_scan_ms FROM scans_hourly "
            "WHERE hour >= now() - make_interval(hours => %s) ORDER BY hour, verdict, scam_type",
            (hours,),
        ).fetchall()
    return _jsonable(rows)


def summary() -> dict:
    """Totals by verdict (all time and 24h), top scam types (24h), avg scan time (24h)."""
    with _connect() as conn:
        by_verdict = conn.execute(
            "SELECT verdict, count(*) AS total, "
            "count(*) FILTER (WHERE time >= now() - INTERVAL '24 hours') AS last_24h "
            "FROM scans GROUP BY verdict ORDER BY total DESC").fetchall()
        top_types = conn.execute(
            "SELECT scam_type, count(*) AS total FROM scans "
            "WHERE time >= now() - INTERVAL '24 hours' AND scam_type IS NOT NULL AND scam_type <> 'none' "
            "GROUP BY scam_type ORDER BY total DESC LIMIT 5").fetchall()
        avg = conn.execute(
            "SELECT avg(scan_ms) AS avg_scan_ms, avg(jev_score) AS avg_score, count(*) AS total "
            "FROM scans WHERE time >= now() - INTERVAL '24 hours'").fetchone() or {}
    return {
        "by_verdict": {r["verdict"]: {"total": r["total"], "last_24h": r["last_24h"]} for r in by_verdict},
        "top_scam_types_24h": _jsonable(top_types),
        "scans_24h": avg.get("total", 0),
        "avg_scan_ms_24h": float(avg["avg_scan_ms"]) if avg.get("avg_scan_ms") is not None else None,
        "avg_score_24h": float(avg["avg_score"]) if avg.get("avg_score") is not None else None,
    }


# ---------- impact (/stats/impact, /stats/domain/{domain}) ----------

_refusals_table_ready = False


def log_payment_refusal(scan_id: str, reason: str, amount_sol: float | None, source: str) -> None:
    """One refused scam payment request. A scan_id is counted once (ON CONFLICT DO NOTHING)."""
    global _refusals_table_ready
    with _connect() as conn:
        if not _refusals_table_ready:
            conn.execute(PAYMENT_REFUSALS_SQL)
            _refusals_table_ready = True
        conn.execute(
            "INSERT INTO payment_refusals (scan_id, reason, amount_sol, source) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (scan_id) DO NOTHING",
            (scan_id, reason, amount_sol, source),
        )


def impact_counts(repeat_limit: int = 10) -> dict:
    """Numbers behind /stats/impact. All-time verdict totals come from the scans_hourly continuous
    aggregate; the exact 24 h count uses the time index; repeat scams need the raw rows (domain)."""
    repeat_limit = max(1, min(int(repeat_limit), 50))
    with _connect() as conn:
        by_verdict = conn.execute(
            "SELECT verdict, sum(total)::bigint AS total FROM scans_hourly GROUP BY verdict").fetchall()
        last_24h = conn.execute(
            "SELECT count(*) AS total FROM scans WHERE time >= now() - INTERVAL '24 hours'").fetchone() or {}
        # A domain counts as a repeat scam when it was checked more than once and most of its
        # checks were flagged, so one false alarm on a popular site doesn't put it on the list.
        repeats = conn.execute(
            "SELECT domain, count(*) AS times_checked, "
            "count(*) FILTER (WHERE verdict = ANY(%(flagged)s)) AS times_flagged, "
            "min(time) AS first_seen, max(time) AS last_seen, "
            "mode() WITHIN GROUP (ORDER BY scam_type) "
            "  FILTER (WHERE verdict = ANY(%(flagged)s) AND scam_type IS NOT NULL AND scam_type <> 'none') "
            "  AS scam_type "
            "FROM scans WHERE domain IS NOT NULL AND domain <> '' "
            "GROUP BY domain "
            "HAVING count(*) > 1 AND 2 * count(*) FILTER (WHERE verdict = ANY(%(flagged)s)) > count(*) "
            "ORDER BY times_checked DESC, last_seen DESC, domain LIMIT %(limit)s",
            {"flagged": FLAGGED, "limit": repeat_limit},
        ).fetchall()
        present = conn.execute(
            "SELECT to_regclass('payment_refusals') IS NOT NULL AS present").fetchone() or {}
        refused = {}
        if present.get("present"):
            refused = conn.execute(
                "SELECT count(*) AS count, coalesce(sum(amount_sol), 0) AS sol_total "
                "FROM payment_refusals").fetchone() or {}
    totals = {v: 0 for v in VERDICTS}
    for r in by_verdict:
        if r.get("verdict") is not None:
            totals[r["verdict"]] = int(r["total"] or 0)
    repeat_rows = []
    for r in _jsonable(repeats):
        repeat_rows.append({"domain": r["domain"], "times_checked": int(r["times_checked"]),
                            "times_flagged": int(r["times_flagged"]), "first_seen": r["first_seen"],
                            "last_seen": r["last_seen"], "scam_type": r.get("scam_type") or "other"})
    return {
        "by_verdict": totals,
        "scans_total": sum(totals.values()),
        "scans_24h": int(last_24h.get("total") or 0),
        "repeat_scams": repeat_rows,
        "payments_refused": {"count": int(refused.get("count") or 0),
                             "sol_total": round(float(refused.get("sol_total") or 0), 9)},
    }


def domain_stats(domain: str) -> dict:
    """How often one (already validated, lowercase) domain was checked, and with which verdicts."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT count(*) AS times_checked, "
            "count(*) FILTER (WHERE verdict = 'safe') AS safe, "
            "count(*) FILTER (WHERE verdict = 'suspicious') AS suspicious, "
            "count(*) FILTER (WHERE verdict = 'malicious') AS malicious, "
            "min(time) AS first_seen, max(time) AS last_seen "
            "FROM scans WHERE domain = %s",
            (domain,),
        ).fetchone() or {}
    row = _jsonable([row])[0] if row else {}
    verdicts = {v: int(row.get(v) or 0) for v in VERDICTS}
    return {
        "domain": domain,
        "times_checked": int(row.get("times_checked") or 0),
        "times_flagged": verdicts["suspicious"] + verdicts["malicious"],
        "first_seen": row.get("first_seen"),
        "last_seen": row.get("last_seen"),
        "verdicts": verdicts,
    }
