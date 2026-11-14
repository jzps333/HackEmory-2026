# Data (Person 3)

## Typesense: scam map + search (`scam_pins` collection)
Fields: `url`, `domain` (facet), `scam_type` (facet), `jev_score` (float), `explanation`,
`location` (geopoint `[lat, lng]`, rounded to ~100 m), `reported_at` (int64).
- Nearby: `filter_by: location:(LAT, LNG, 1 km)`, `sort_by: location(LAT, LNG):asc`
- Search: `q=parking`, `query_by=explanation,domain,url` (typo tolerant)
- "Flagged before": filter by `domain:=<domain>` near the user before running the sandbox.
Only pin **malicious** scans, only when the user taps Report, never store who reported.

## Tiger Data: every scan over time (`scans` hypertable)
Schema lives in `data/tiger_store.py` (`scans` hypertable + `scans_hourly` continuous aggregate
bucketed by hour, scam_type, verdict with count / avg jev_score / avg scan_ms, real-time, refreshed every 5 min).
Dashboard: scans per hour (safe vs malicious), top scam types, average sandbox time, Jev score spread.
Connection string goes in `.env` as `TIGER_DATABASE_URL`, never in git.

## Setup and endpoints
Env: `TYPESENSE_HOST` (full https URL), `TYPESENSE_API_KEY`, `TIGER_DATABASE_URL`.
Run once: `python -m data.setup` (prints OK / FAIL / SKIP per service, never secrets).
Endpoints (`api/routes_data.py`): `POST /report`, `GET /pins?lat&lng&radius_km`, `GET /search?q`,
`GET /stats/hourly?hours`, `GET /stats/summary`. 503 if a service isn't configured, 502 if it errors.
