# Data layer: Typesense + Tiger Data (Person 3)

Code: `data/typesense_store.py` (`scam_pins`), `data/scan_search.py` (`scans`), `data/sync_scans.py`, `data/tiger_store.py`,
`data/setup.py`. HTTP routes: `api/routes_data.py`.
Both stores are optional. The API starts and `/scan` works without either of them (see section 4).
**No secrets in this file or in git.** Keys live only in the repo `.env` on the agent server.

**Status (Sat Nov 14, evening):** Tiger Data is configured on the agent server, and `/stats/*` returns real scans.
Typesense runs **self-hosted on the agent server for now** (Docker, localhost only, section 3b) with both collections, so
`/pins`, `/search`, `/report` and `/scans/search` work. The plan is to switch to **Typesense Cloud** (section 3a). After
changing the keys in `.env`, run `data.setup` + `data.sync_scans` and restart the backend, or the new cluster is empty.

## For AI coding assistants (Claude Code etc.)

- **Read first:** `data/typesense_store.py`, `data/scan_search.py`, `data/tiger_store.py`, `data/setup.py`, `api/routes_data.py`,
  `api/schema.py`, `shared/scan_result.example.json`.
- **Hard rules:** never commit `.env` and never print, log or paste keys or connection strings (use placeholders).
  Don't change the ScanResult shape or the Typesense/Tiger schemas without telling the team first. Location stays
  rounded to ~100 m (3 decimals). The demo uses made-up businesses only (Peachtree Parking Co., Magnolia Diner).
- **Run:** `pip install -r requirements.txt`, then `python3 -m data.setup` and `python3 -m data.sync_scans` (need keys,
  section 3) and the offline tests `python3 -m pytest -q tests` (no keys or network needed).
- **Live backend:** `https://api.scansafe.nyc` (endpoints in section 5).

## 1. What each store is for

| Store | Holds | Powers |
|---|---|---|
| **Typesense** (`scam_pins` collection) | One pin per *reported* scan, only if it is malicious and has a location | Scam map (geosearch), the map's search box (typo-tolerant text search), "Reported nearby N times before" on the result screen |
| **Typesense** (`scans` collection) | One doc per Tiger `scans` row (a search mirror of the scan log), plus URL, title and explanation for scans indexed live | `GET /scans/search`: typo-tolerant search over every scan, with verdict / scam_type facets |
| **Tiger Data** (`scans` hypertable + `scans_hourly` continuous aggregate) | One row per scan, any verdict, reported or not. **Source of truth** for the scan log | `/dashboard`: totals, scans per hour, top scam types, average check time |

```
POST /scan  (web app, Chert agent)                                api/main.py
  scan() -> ScanResult                     location rounded to 3 decimals (~100 m) in api/scan.py
  result.flagged_before = flagged_before() -> Typesense: count pins with domain:=<domain>,
                                              within 5 km if the scan has a location. Never raises; 0 on error.
  background task: record_scan(result)     -> Tiger: INSERT INTO scans, after the response is sent
                                           -> then Typesense: emplace into `scans` (scan_search.index_scan)
                                              Two independent best-effort steps. Never raises.

"Report scam" (app/src/components/ResultView.tsx) -> POST /report with the whole ScanResult
  -> Typesense upsert into scam_pins (only if verdict == "malicious" and location is set; doc id = scan_id)
  -> and PATCH the same rounded location onto that scan's `scans` doc (best effort)

python3 -m data.sync_scans                 -> backfill: every Tiger row -> Typesense `scans` (idempotent)

app /map        -> GET /pins?lat&lng&radius_km=5, GET /search?q=          (Typesense scam_pins)
app (scan log)  -> GET /scans/search?q=&verdict=&scam_type=&page=        (Typesense scans)
app /dashboard  -> GET /stats/summary + GET /stats/hourly?hours=24, every 30 s   (Tiger)
```
`POST /scan/stream` (branch `live-stream-and-calls`) uses the same `_finish()`: `flagged_before`, then
`record_scan` after the last NDJSON line. If the sandbox fails there, the fallback result is **not** logged.

## 2. Schemas (verbatim from the code)

### Typesense: `scam_pins` (`typesense_store.SCHEMA`)
`default_sorting_field: reported_at`. Document `id` = `scan_id`, so tapping Report twice upserts one pin.
No field is `optional`, so every document needs all seven fields.

| Field | Type | Facet | Filled from (`pin_document`) |
|---|---|---|---|
| `url` | `string` | | `final_url or url` |
| `domain` | `string` | yes | `domain`, else hostname of the URL, lowercased (`""` for `solana:` codes) |
| `scam_type` | `string` | yes | `scam_type` |
| `jev_score` | `float` | | `jev_score` |
| `explanation` | `string` | | `explanation` |
| `location` | `geopoint` | | `[lat, lng]`, each rounded to 3 decimals |
| `reported_at` | `int64` | | server time (unix seconds) when reported |

### Typesense: `scans` (`scan_search.SCHEMA`)
Search mirror of the Tiger `scans` table. `default_sorting_field: scanned_at`,
`token_separators: [".", "-", "/", ":", "_"]` (so `wikipedia` matches `en.wikipedia.org` and URL path words are searchable).
Document `id` = first 24 hex chars of sha256 over the Tiger row `[time, domain, verdict, scam_type, jev_score, scan_ms]`
(`scan_search.doc_id`). Tiger has no scan_id, so the live path and the backfill both derive it from the row and land on
the same doc. Both write with `action=emplace` (create or merge), so a backfill never wipes fields a live scan added.

| Field | Type | Facet | Optional | Filled from |
|---|---|---|---|---|
| `domain` | `string` | yes | | Tiger `domain` (lowercased hostname; `""` for payment codes) |
| `verdict` | `string` | yes | | Tiger `verdict` |
| `scam_type` | `string` | yes | | Tiger `scam_type` |
| `jev_score` | `float` | | | Tiger `jev_score` |
| `scan_ms` | `int32` | | yes | Tiger `scan_ms` (null for payment codes, so omitted) |
| `scanned_at` | `int64` | | | Tiger `time` as unix seconds (= ScanResult `scanned_at`) |
| `url`, `final_url` | `string` | | yes | **Live scans only.** http/https: `scheme://host[:port]/path`, with query string, fragment and `user:pw@` removed. `solana:` keeps only the recipient. Any other QR content (WIFI:, vCard, mailto:, plain text) is **not stored** |
| `page_title` | `string` | | yes | **Live scans only.** Sandbox page title, max 300 chars |
| `explanation` | `string` | | yes | **Live scans only.** Gemini explanation, max 2000 chars |
| `location` | `geopoint` | | yes | **Only after Report** on a malicious scan: the same 3-decimal point as its pin. Unreported scans never get one |

Docs backfilled from Tiger have only the Tiger fields (Tiger never kept URL, title or explanation). Identical Tiger rows
(same second and same values, e.g. a payment code submitted twice) collapse into one doc, so the doc count can be a
little below the row count.

### Tiger Data (`tiger_store.SCHEMA_SQL`)
```sql
CREATE TABLE IF NOT EXISTS scans (
    time      TIMESTAMPTZ NOT NULL,
    domain    TEXT,
    verdict   TEXT,
    scam_type TEXT,
    jev_score DOUBLE PRECISION,
    scan_ms   INTEGER
);
SELECT create_hypertable('scans', 'time', if_not_exists => TRUE);
CREATE MATERIALIZED VIEW IF NOT EXISTS scans_hourly
    WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
    SELECT time_bucket(INTERVAL '1 hour', time) AS hour,
           scam_type,
           verdict,
           count(*)       AS total,
           avg(jev_score) AS avg_score,
           avg(scan_ms)   AS avg_scan_ms
    FROM scans
    GROUP BY hour, scam_type, verdict
    WITH NO DATA;
SELECT add_continuous_aggregate_policy('scans_hourly',
    start_offset      => INTERVAL '3 days',
    end_offset        => INTERVAL '1 minute',
    schedule_interval => INTERVAL '5 minutes',
    if_not_exists     => TRUE);
```
- Hypertable column: `time` = `scanned_at` from the ScanResult (UTC). Default chunk interval (7 days).
- Indexes: none created explicitly. `create_hypertable` adds its default index on `time DESC` (`scans_time_idx`).
- `scans_hourly`: 1-hour buckets per `(scam_type, verdict)`. Real-time (`materialized_only = false`), so rows
  newer than the last refresh still show up. The policy runs every 5 min and refreshes `[now - 3 days, now - 1 min]`.
- Row mapping (`scan_row`): `domain` = `domain`, else hostname of `final_url or url`, lowercased. No scan_id, no URL path, no location.

## 3. Env vars

| Var | Format | Where to get it |
|---|---|---|
| `TYPESENSE_HOST` | Full URL including the protocol (no trailing slash). Cloud: `https://<cluster-host>.a1.typesense.net` (no port). Self-hosted on the agent server: `http://127.0.0.1:8108` | Cloud: your cluster's page (node hostname). Self-hosted: fixed, see 3b |
| `TYPESENSE_API_KEY` | The **Admin** API key. A search-only key can't create collections or write docs | Cloud: cluster page, "Generate API Keys". Self-hosted: generated on the server, see 3b |
| `TIGER_DATABASE_URL` | `postgres://tsdbadmin:<password>@<host>:<port>/tsdb?sslmode=require` | Copy the value of `TIMESCALE_SERVICE_URL` from the downloaded `tiger-cloud-db-…-credentials.env` |

- Typesense counts as configured only if **both** of its vars are set.
- Keys go only in the repo-root `.env` (copy of `.env.example`, gitignored). On the agent server that is
  `~/HackEmory-2026/.env` (chmod 600, written by `scripts/setup_agent_server.sh`). Never commit it, never paste keys in chat.
- `.env` is read once at import, so **restart the backend after editing it**.

The code only reads the two vars, so Cloud and self-hosted work the same way: switching is editing `.env`, running
setup + sync, and restarting the backend.

### 3a. Typesense Cloud (primary)
```bash
# 1. cloud.typesense.org: launch the smallest cluster, wait until it's ready, Generate API Keys (admin key + host)
ssh root@144.202.25.65
cd ~/HackEmory-2026 && nano .env   # TYPESENSE_HOST=https://<cluster-host>.a1.typesense.net   TYPESENSE_API_KEY=<your-typesense-admin-key>
python3 -m data.setup              # expect: OK   Typesense: created scam_pins   /   OK   Typesense: created scans
python3 -m data.sync_scans         # expect: OK   synced N Tiger rows -> M docs (... 0 failed ...)
tmux kill-session -t api; tmux new -d -s api "cd ~/HackEmory-2026 && uvicorn api.main:app --host 0.0.0.0 --port 8000 2>&1 | tee /root/api.log"
curl -s "https://api.scansafe.nyc/pins?lat=33.79&lng=-84.32&radius_km=5"   # {"count":0,"pins":[]} instead of a 503
curl -s -G "https://api.scansafe.nyc/scans/search" --data-urlencode q=wikipedia   # "found": > 0
```
Moving from self-hosted to Cloud: `data.sync_scans` rebuilds `scans` from Tiger, but URL, title and explanation exist
only for scans indexed live, and pins exist only in `scam_pins`. To keep them, copy both collections before restarting:
`curl -s "$OLD/collections/<c>/documents/export" -H "X-TYPESENSE-API-KEY: $OLD_KEY" | curl -s -X POST
"$NEW/collections/<c>/documents/import?action=upsert" -H "X-TYPESENSE-API-KEY: $NEW_KEY" --data-binary @-`
(with `<c>` = `scam_pins`, then `scans`; run setup on the new cluster first; load keys with `read -rs`, section 6).
Afterwards the self-hosted container can be stopped (3b).

### 3b. Self-hosted on the agent server (fallback, running now)
- Container `typesense`, image **`typesense/typesense:30.2`** (pinned), `--restart unless-stopped`, published on
  **`127.0.0.1:8108` only**: it is not reachable from the internet, only from processes on the box (the backend). Never
  publish it on `0.0.0.0` (Docker skips ufw for published ports).
- Data: `/root/typesense-data` (mounted at `/data`). Limits: `--memory 768m --cpus 1`, `--thread-pool-size 8`,
  `--cache-num-entries 200`, logs capped at 3 x 10 MB. Idle it uses ~30 MB.
- Key: generated on the server with `openssl rand -hex 24`. It lives **only** in `~/HackEmory-2026/.env`
  (`TYPESENSE_API_KEY`, with `TYPESENSE_HOST=http://127.0.0.1:8108`). The container gets it via the `TYPESENSE_API_KEY`
  env var at `docker run` time, never on the command line.
```bash
curl -s localhost:8108/health                  # {"ok":true}  (no key needed)
docker ps --filter name=typesense              # status
docker logs --tail 50 typesense                # logs
docker restart typesense                       # restart (keeps data and key)
docker stop typesense                          # stop (keeps data); docker start typesense to bring it back
# Recreate from scratch (same data dir; reads the key from .env without printing it):
docker rm -f typesense
TYPESENSE_API_KEY="$(grep '^TYPESENSE_API_KEY=' ~/HackEmory-2026/.env | cut -d= -f2-)" \
docker run -d --name typesense --restart unless-stopped -p 127.0.0.1:8108:8108 \
  -v /root/typesense-data:/data -e TYPESENSE_API_KEY --memory 768m --memory-swap 768m --cpus 1 \
  --log-opt max-size=10m --log-opt max-file=3 \
  typesense/typesense:30.2 --data-dir /data --thread-pool-size 8 --cache-num-entries 200
```
If you rotate the key, change it in `.env`, recreate the container, then restart the backend.

The tmux line above is the one the backend runs under (`setup_agent_server.sh` uses the same one without the `tee`).
If the backend was started differently, restart it that way.

## 4. Setup and running locally

```bash
pip install -r requirements.txt     # httpx, python-dotenv, psycopg[binary], ...
python3 -m data.setup               # from the repo root
```
It creates the `scam_pins` collection (if missing) and the `scans` table, hypertable, `scans_hourly` view and
refresh policy. **Idempotent**: everything is `IF NOT EXISTS` / `if_not_exists`, and an existing collection
(HTTP 200 or 409) is left alone. **Not a migration tool**: it never changes an existing table, view or collection (section 7).

| Output | Meaning |
|---|---|
| `OK   Typesense: created scam_pins` / `scam_pins exists` | Map collection is ready |
| `OK   Typesense: created scans` / `scans exists` | Scan-log search collection is ready (fill it with `data.sync_scans`) |
| `OK   Tiger Data: scans + scans_hourly ready` | Schema is ready |
| `SKIP <service>: not configured` | Env vars missing. Nothing was attempted |
| `FAIL <service>: <ErrorType> (HTTP <code>)` | Only the error type is printed, because messages can contain secrets |

Exit code is 0 only if all three say OK (a SKIP gives 1). Common FAILs: `HTTPStatusError (HTTP 401)` = wrong or
search-only key; `UnsupportedProtocol` = host is missing `https://`; `ConnectError` = wrong host;
`OperationalError` = bad Tiger URL or the service is paused; `ModuleNotFoundError` = run the pip install.

**Backfill:** `python3 -m data.sync_scans` reads every Tiger row (batches of 500) and emplaces it into `scans`. Safe to
re-run any time (same ids, merges). Prints `OK   synced <rows> Tiger rows -> <docs> docs (<n> written, <n> failed, <n> pruned); ...`
with the collection's doc count, or `SKIP` / `FAIL <ErrorType>` like setup. `--prune` also deletes docs whose Tiger
row is gone (run it after deleting test scans from Tiger, section 6). Live scans are indexed by `record_scan`, so you
only need the backfill once per cluster, or after Typesense was down for a while.

**Without keys** (nothing degrades silently on the server; the web app does fall back to mocks):
- `/scan` works (mock results if `SANDBOX_URL` is empty). `flagged_before` = 0, `record_scan` does nothing.
- `/report`, `/pins`, `/search`, `/scans/search` return 503 `typesense_not_configured`. `/stats/*` returns 503 `tiger_not_configured`.
- `psycopg` is imported lazily, so the API starts even if it isn't installed.
- Web app: with `NEXT_PUBLIC_API_URL` unset it runs in demo mode on `app/src/lib/mockData.ts`. If it is set and a
  data call fails (503, 502, timeout), `getPins`, `searchPins` and `getStats` quietly show mock data with a "Demo" badge.
  **A Demo badge on the live site means that endpoint failed.** A failed `report()` shows "We couldn't send your report".
- Offline tests (both services mocked): `python3 -m pytest -q tests/test_data.py tests/test_scans_search.py`

**Pointing at real services:** put the three vars in your local `.env` and run `uvicorn api.main:app --reload`.
Careful: the Tiger service *is* the demo dashboard. Every local scan lands on it, including mock-mode scans of the
fake Peachtree page, and rows have no scan_id or environment column to filter them out later. For throwaway work, use Docker:
```bash
docker run -d --name ts -p 8108:8108 typesense/typesense:27.1 --data-dir /tmp --api-key=<local-dev-key>
docker run -d --name tsdb -p 5432:5432 -e POSTGRES_PASSWORD=<local-password> timescale/timescaledb:latest-pg16
# .env: TYPESENSE_HOST=http://localhost:8108  TYPESENSE_API_KEY=<local-dev-key>
#       TIGER_DATABASE_URL=postgres://postgres:<local-password>@localhost:5432/postgres
python3 -m data.setup && uvicorn api.main:app --reload    # app/.env.local: NEXT_PUBLIC_API_URL=http://localhost:8000
```

## 5. Endpoints

| Method | Path | Params / body | 200 response |
|---|---|---|---|
| POST | `/report` | Body: the whole ScanResult JSON, exactly as `/scan` returned it | `{"stored": true, "pin": {…}}` or `{"stored": false, "reason": "…"}` |
| GET | `/pins` | `lat` (required, -90..90), `lng` (required, -180..180), `radius_km` (default 1.0, max 100), `limit` (default 100, 1..250) | `{"count": n, "pins": [pin + "distance_m"]}`, nearest first |
| GET | `/search` | `q` (required, 1..200 chars), `limit` (default 20, 1..100) | `{"count": n, "results": [pin]}` |
| GET | `/scans/search` | `q` (default `""`, max 200; `""` or `*` = browse), `verdict`, `scam_type`, `lat`+`lng` (both or neither), `radius_km` (default 5, max 100), `page` (default 1, 1..100), `per_page` (default 20, 1..100) | see below |
| GET | `/stats/hourly` | `hours` (default 24, 1..720) | `{"hours": 24, "rows": [{"hour", "scam_type", "verdict", "total", "avg_score", "avg_scan_ms"}]}` |
| GET | `/stats/summary` | none | see below |

- Errors: 503 `{"detail": {"error": "typesense_not_configured" | "tiger_not_configured", "service", "message"}}`;
  502 `{"detail": {"error": "typesense_error" | "tiger_data_error", ...}}`; 422 for bad params or a body that isn't a valid ScanResult.
- `/report` checks the config first (503 even for safe scans), then returns `stored: false` for non-malicious or no-location scans.
- `/stats/hourly`: one row per `(hour, scam_type, verdict)`, sorted by hour. `hour` is ISO UTC. **Hours with no scans
  have no row**, so fill gaps on the client if you need a continuous axis. The app sums rows per hour into `{hour, total, malicious}`.
- `/stats/summary` returns `by_verdict` (`{"safe": {"total", "last_24h"}, ...}`, only verdicts that have rows; `total`
  is all-time), `top_scam_types_24h` (`[{"scam_type", "total"}]`, max 5, excludes `none`), `scans_24h`, `avg_scan_ms_24h`, `avg_score_24h`.

**`GET /scans/search`** searches every logged scan (Typesense `scans`):
```json
{"found": 9, "out_of": 50, "page": 1, "per_page": 20,
 "hits": [{"id": "327769ecbdb76cd136633f94", "url": "https://example.com/", "final_url": "https://example.com/",
           "domain": "example.com", "verdict": "safe", "scam_type": "none", "jev_score": 0.0,
           "explanation": "…", "page_title": "Example Domain", "scanned_at": 1794684751, "scan_ms": 5256,
           "reported": false,
           "highlight": {"domain": "<mark>example</mark>.<mark>com</mark>", "page_title": "<mark>Example</mark> Domain"}}],
 "facets": {"verdict": {"safe": 43, "malicious": 6}, "scam_type": {"none": 43, "fake_payment_app": 4}}}
```
- Typo tolerant (up to 2 typos) and prefix matching on the last word, over `domain, url, final_url, page_title,
  explanation` (weighted in that order). `q=examp` finds example.com, `q=wikipeda` finds the Wikipedia scans.
- Order: text queries by relevance, then newest. Browse (`q` empty or `*`): newest first.
- `verdict` must be `safe|suspicious|malicious`, `scam_type` one of the ScanResult values (else 422). Facet counts are
  for the current result set, filters included. For filter chips that keep all counts, take them from a call without
  `verdict` / `scam_type`.
- Every hit has every key above. `url`, `final_url`, `page_title`, `explanation` are `null` for scans backfilled from Tiger
  (logged before live indexing existed) and `url` is null for non-web QR content. `scan_ms` is null for payment codes.
- `reported` is true when the scan was reported (it then has a location). `lat`+`lng` filter to scans within `radius_km`,
  so **they only match reported scans**, and those hits get `distance_m`.
- `highlight` (only on text queries, only for fields that matched): HTML-escaped snippets where the only tags are
  `<mark>…</mark>`, so it's safe to render as HTML. Page titles come from scanned (possibly hostile) pages; render every
  other field as plain text.
- Errors: 503 `typesense_not_configured`, 502 `typesense_error` (also when the `scans` collection is missing: run setup),
  422 `{"detail": {"error": "bad_location", ...}}` for only one of lat/lng.

```bash
BASE=https://api.scansafe.nyc
curl -s -G "$BASE/scans/search" --data-urlencode q=wikipedia
curl -s "$BASE/scans/search?verdict=malicious&per_page=5"
curl -s "$BASE/stats/summary"
curl -s "$BASE/stats/hourly?hours=24"
curl -s "$BASE/pins?lat=33.79&lng=-84.32&radius_km=5"
curl -s -G "$BASE/search" --data-urlencode "q=parking"
# Adds a REAL pin to the live map (the fake Peachtree example, id mock-mal-001; running it again upserts the same pin)
curl -s -X POST "$BASE/report" -H 'Content-Type: application/json' -d @shared/scan_result.example.json
```

## 6. Handy queries

**Tiger** (on the agent server; `apt-get install -y postgresql-client` if `psql` is missing):
```bash
cd ~/HackEmory-2026 && export TIGER_DATABASE_URL="$(grep '^TIGER_DATABASE_URL=' .env | cut -d= -f2-)"  # loads it, prints nothing
psql "$TIGER_DATABASE_URL" -c "SELECT time, domain, verdict, scam_type, jev_score, scan_ms FROM scans ORDER BY time DESC LIMIT 20;"
psql "$TIGER_DATABASE_URL" -c "SELECT scam_type, count(*) FROM scans WHERE verdict <> 'safe' GROUP BY 1 ORDER BY 2 DESC;"
psql "$TIGER_DATABASE_URL" -c "SELECT * FROM scans_hourly WHERE hour > now() - INTERVAL '24 hours' ORDER BY hour, verdict;"
psql "$TIGER_DATABASE_URL" -c "SELECT job_id, proc_name, schedule_interval FROM timescaledb_information.jobs;"
# Remove test scans (run the matching SELECT first!), then rebuild the aggregate:
psql "$TIGER_DATABASE_URL" -c "DELETE FROM scans WHERE time > now() - INTERVAL '1 hour' AND domain = '<test-domain>';"
psql "$TIGER_DATABASE_URL" -c "CALL refresh_continuous_aggregate('scans_hourly', NULL, NULL);"
```

**Typesense** (`read -rs` keeps the key out of your shell history). Self-hosted: run these on the agent server with
`TS=http://127.0.0.1:8108` and load the key with
`KEY="$(grep '^TYPESENSE_API_KEY=' ~/HackEmory-2026/.env | cut -d= -f2-)"` (prints nothing).
```bash
TS=https://<cluster-host>.a1.typesense.net; read -rs -p "Typesense admin key: " KEY; echo
H="X-TYPESENSE-API-KEY: $KEY"; S="$TS/collections/scam_pins/documents/search"
curl -s -G "$S" -H "$H" --data-urlencode 'q=*' --data-urlencode 'query_by=domain' \
  --data-urlencode 'filter_by=location:(33.79, -84.32, 5 km)' --data-urlencode 'sort_by=location(33.79, -84.32):asc'   # nearby
curl -s -G "$S" -H "$H" --data-urlencode 'q=parkng' --data-urlencode 'query_by=explanation,domain,url'               # text, typo ok
curl -s -G "$S" -H "$H" --data-urlencode 'q=*' --data-urlencode 'query_by=domain' --data-urlencode 'per_page=0' \
  --data-urlencode 'filter_by=domain:=`peachtree-parking-pay.xyz`'                                                  # flagged count
curl -s "$TS/collections/scam_pins" -H "$H"                                   # schema + num_documents
curl -s "$TS/collections/scam_pins/documents/export" -H "$H"                  # every pin, JSONL
curl -s -X DELETE "$TS/collections/scam_pins/documents/<scan_id>" -H "$H"     # remove one pin
curl -s "$TS/collections/scans" -H "$H"                                       # scan-log index: schema + num_documents
curl -s -G "$TS/collections/scans/documents/search" -H "$H" --data-urlencode 'q=*' --data-urlencode 'query_by=domain' \
  --data-urlencode 'facet_by=verdict,scam_type' --data-urlencode 'per_page=0'                                    # facet counts
```

## 7. Gotchas

- **Location**: rounded to 3 decimals (~100 m) in `api/scan.py` and again in `pin_document`. Tiger never stores location.
- **What is stored**: Tiger keeps `time, domain, verdict, scam_type, jev_score, scan_ms`. Typesense `scam_pins` keeps the
  seven pin fields plus `id`. Typesense `scans` keeps Tiger's fields, plus (live scans only) the URL without its query
  string, `page_title` and `explanation`, plus a location only once a scan is reported. **Never stored anywhere**:
  screenshots, page text (not in ScanResult at all), URL query strings in `scans`, non-web QR content (WIFI:, vCard...),
  the location of unreported scans, `redirect_chain`, `checks`, `payment`, and who scanned or reported (there is no user,
  device or IP field).
- `/scans/search` is public, like `/pins`: anyone can browse every scan's domain, URL path and time. Fine for the demo. `/report` receives the
  whole ScanResult, screenshots included, and drops everything except the pin fields.
- Pins store the **full** final URL (path and query), and for `solana:` codes the whole payment request. `/pins` returns it.
- Only malicious scans with a location get pinned. The app also offers "Report scam" on suspicious results and
  "Report scam anyway" on safe ones. The server answers 200 `{"stored": false}`, and the app still says it was added to the map.
- `/report` trusts the request body (verdict, location, explanation) and never checks that the scan_id was really scanned.
  Anyone can add pins, or overwrite one by reusing its scan_id. Fine for the demo, but don't claim more than that.
- Mock mode: `shared/mock_malicious.json` has `location: [33.7925, -84.324]`, so mock scans have a location even when the
  user shared none, and reports pin there. Mock scans are logged to Tiger too (`scan_ms` 4200).
- `flagged_before` needs `result.domain` (always 0 for payment codes). It counts pins for that domain within 5 km, or
  anywhere if the scan has no location. It only goes above 0 once someone has tapped Report.
- `scan_ms` times the whole check (sandbox + Jev + Gemini), not only the sandbox as the schema comment says. It is null
  for payment codes, which also have a null `domain`.
- Dashboard tiles mix time windows: total, malicious and suspicious are **all-time**; average time, top types and the chart are **24 h**.
- `record_scan` swallows errors. If the dashboard stops moving, run `tmux attach -t api` (or `grep failed /root/api.log`)
  and look for `record_scan failed: <Type>`; for scan-log search, `index_scan failed: <Type>`. Fix it, then re-run
  `python3 -m data.sync_scans` to catch up (scans missed while Typesense was down come back without URL/title/explanation).
- Each call opens a new connection (no pool). Timeouts: Tiger connect 5 s, Typesense 10 s.

### How to add a field
1. If it touches the ScanResult shape, **tell the whole team first** (TEAM.md). Update `api/schema.py`,
   `app/src/lib/types.ts`, and the mocks in `shared/` and `app/src/mock/` (keep both copies identical; `mock_result` loads them).
2. Typesense: add it to `SCHEMA` and `pin_document()` in `typesense_store.py`, and to `Pin` in `types.ts`. Add it to `query_by`
   in `search()` if it should be searchable. For the `scans` collection: `SCHEMA`, `row_document()` / `result_document()`
   and `HIT_FIELDS` in `scan_search.py` (`QUERY_BY` to make it searchable). The live collection won't change on its own: run
   `curl -X PATCH "$TS/collections/scam_pins" -H "$H" -H 'Content-Type: application/json' -d '{"fields":[{"name":"<field>","type":"string","optional":true}]}'`.
3. Tiger: add the column to `CREATE TABLE` in `SCHEMA_SQL` (for fresh setups), to `scan_row()` and to the `INSERT` in `log_scan()`.
   On the live service: `ALTER TABLE scans ADD COLUMN <field> <type>;`. To use it in `scans_hourly`, edit the view SQL, then
   `DROP MATERIALIZED VIEW scans_hourly;`, `python3 -m data.setup`, and `CALL refresh_continuous_aggregate('scans_hourly', NULL, NULL);`.
4. Update `tests/test_data.py`, run `python3 -m pytest -q`, and update this README.

## 8. Cleanup after the hackathon

1. Optional export: `psql "$TIGER_DATABASE_URL" -c "\copy scans TO 'scans.csv' CSV HEADER"` and
   `curl -s "$TS/collections/scam_pins/documents/export" -H "$H" > pins.jsonl`.
2. **Tiger Cloud** console, open the ScanSafe service: **Pause** it (keeps the data, stops compute) or **Delete** it (permanent).
3. **Typesense Cloud**, open the cluster: terminate it (permanent; deletes the API keys too).
   Self-hosted: `docker rm -f typesense && rm -rf /root/typesense-data` on the agent server (permanent).
4. Delete the data vars from `~/HackEmory-2026/.env` and any local `.env`, and delete the downloaded
   `tiger-cloud-db-…-credentials.env`. Then destroy the Vultr servers (HANDOFF.md).
