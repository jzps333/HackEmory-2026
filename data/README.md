# Data (Person 3)

## Typesense: scam map + search (`scam_pins` collection)
Fields: `url`, `domain` (facet), `scam_type` (facet), `jev_score` (float), `explanation`,
`location` (geopoint `[lat, lng]`, rounded to ~100 m), `reported_at` (int64).
- Nearby: `filter_by: location:(LAT, LNG, 1 km)`, `sort_by: location(LAT, LNG):asc`
- Search: `q=parking`, `query_by=explanation,domain,url` (typo tolerant)
- "Flagged before": filter by `domain:=<domain>` near the user before running the sandbox.
Only pin **malicious** scans, only when the user taps Report, never store who reported.

## Tiger Data: every scan over time (`scans` hypertable)
```sql
CREATE TABLE scans (time TIMESTAMPTZ NOT NULL, domain TEXT, verdict TEXT, scam_type TEXT,
                    jev_score DOUBLE PRECISION, scan_ms INTEGER);
SELECT create_hypertable('scans', 'time');
CREATE MATERIALIZED VIEW scans_hourly WITH (timescaledb.continuous) AS
SELECT time_bucket('1 hour', time) AS hour, scam_type, count(*) AS total, avg(jev_score) AS avg_score
FROM scans GROUP BY hour, scam_type;
```
Dashboard: scans per hour (safe vs malicious), top scam types, average sandbox time, Jev score spread.
Connection string goes in `.env` as `TIGER_DATABASE_URL`, never in git.
