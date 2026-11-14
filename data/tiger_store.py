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
]


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
