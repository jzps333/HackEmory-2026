# ScanSafe API contract for the web UI

For whoever builds the UI (and their AI assistant). Every shape below is taken from the route code:
`api/main.py`, `api/routes_data.py`, `api/routes_call.py`, `api/routes_pay.py`, `api/routes_result.py`.
If this file and the code disagree, the code wins. Please tell the backend owner.

- **Base URL:** `https://api.scansafe.nyc`. CORS is open (`*`, any method or header), so call it straight from the browser.
- JSON in, JSON out (`Content-Type: application/json`). Times are unix seconds (`scanned_at`) or ISO-8601 UTC strings (`hour`, `first_seen`, `generated_at`).
- **Auth:** only `/call-me` and `/auth/me` read a token, sent as `Authorization: Bearer <token>`. Every other endpoint is public.
- Treat page-derived text (`page_title`, `explanation`, `url`) as plain text. Never render it as HTML. The only exception is `/scans/search` `highlight`, which is escaped and contains only `<mark>` tags.

## Error shapes (they differ by router)

| Where | Status | Body |
|---|---|---|
| Data and stats (`/report`, `/pins`, `/search`, `/scans/search`, `/stats/*`) | 503 | `{"detail": {"error": "typesense_not_configured" \| "tiger_not_configured", "service": "typesense" \| "tiger_data", "message": "..."}}` |
| same | 502 | `{"detail": {"error": "typesense_error" \| "tiger_data_error", "service": "...", "message": "... request failed, try again."}}` |
| same, bad input we check ourselves | 422 | `{"detail": {"error": "bad_location" \| "bad_domain", "message": "..."}}` |
| Phone sign-in, `/call-me` | 400 / 403 / 429 / 502 / 503 / 504 | `{"detail": "<human-readable string>"}` |
| `/result/{scan_id}` | 404 | `{"detail": "We couldn't find this check. It may have expired."}` |
| `/pay` | 400 / 403 / 502 / 503 | `{"ok": false, "error": "<code>", "message": "..."}` |
| Any route, body or params that fail validation | 422 | FastAPI default: `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}` |

## 1. Phone sign-in (reverse OTP)

The user texts us a code from their phone, so no SMS provider is involved. The token you get back is what `/call-me` trusts.

```
1. POST /auth/phone/start   {"phone": "+14045559861"}
   -> 200 {"code": "K7QM2X", "request_id": "<secret>", "line": "+16504444331",
           "sms_body": "Hi ScanSafe! My sign-in code is K7QM2X"}
2. Open the SMS composer:  sms:+16504444331?&body=<encodeURIComponent(sms_body)>
   (also show the code and the number, in case the link doesn't open)
3. Poll every 3 s:  POST /auth/phone/verify  {"phone": "+14045559861", "request_id": "<secret>"}
   -> 200 {"verified": false}                                   (keep polling)
   -> 200 {"verified": true, "phone": "+14045559861", "token": "<token>"}   (stop, store the token)
4. GET /auth/me  with  Authorization: Bearer <token>
   -> 200 {"signed_in": true, "phone_masked": "•••9861"}  or  {"signed_in": false}
```

- `phone` must be E.164 (`+` and 7 to 15 digits, spaces are stripped). Anything else gets 400 `"phone must be in international format, e.g. +14045550123"`.
- `request_id` is a secret. Keep it in memory and never show or log it. Verify **without** it gives 400 `"request_id from /auth/phone/start is required"`.
- A pending code expires after **15 minutes**. Stop polling then and offer "Send a new code".
- Each request id yields a token **once**. Replaying a verified request returns `{"verified": false}`.
- The text must come from a number ending in the same 4 digits as `phone` and contain the code (case-insensitive).
- Start rate limits (429, `detail` is a string): 5 starts a minute per device/IP (`"too many sign-ins from this device; try again in a minute"`), one start per phone every 10 s (`"please wait a few seconds"`), at most 10 pending codes per device, plus a global backstop.
- **Token:** valid for 30 days. Store it in `localStorage`. On app load call `/auth/me`. If it returns `{"signed_in": false}`, drop the stored token and show "Sign in". Sign-out happens on the client: forget the token. There is no server revoke endpoint, so the token stays valid until it expires.
- `/auth/me` always answers 200. A missing, malformed, unknown or expired token gives `{"signed_in": false}`. It never returns the full number. The response has `Cache-Control: no-store`.

## 2. Scanning

### POST /scan
Body `{"url": "<whatever the QR contained>", "lat": 33.79, "lng": -84.32}`. Send `lat`/`lng` only if the user agreed to share location. The server rounds them to 3 decimals (~100 m). Returns one **ScanResult** (below). It can take up to about 60 s, so use a 90 s client timeout. If the sandbox fails, `/scan` can return a 500, so prefer `/scan/stream`.

### POST /scan/stream (NDJSON, live view)
Same body. Response is `application/x-ndjson`, one JSON object per line, in this order:
```
{"type": "nav",   "url": "https://bit.ly/x"}                        # main frame navigated (0..n)
{"type": "frame", "jpeg": "<base64 JPEG, no data: prefix>", "t_ms": 1234}   # live screenshot, at most ~8/s (0..n)
{"type": "result", "data": <ScanResult>}                            # ALWAYS exactly one, always last
{"type": "result", "data": <ScanResult>, "error": "sandbox_timeout"}  # ...or this, if the sandbox failed
```
- Show a frame with `src = "data:image/jpeg;base64," + jpeg`. Frames are max 540x1170.
- Every stream ends with one `result` line. If it has an `error` key, the result is a cautious **suspicious** fallback ("We couldn't finish checking this one...") and was not logged to stats. Error codes: `no_result`, `sandbox_error`, `sandbox_timeout`, `sandbox_http_<status>`, `sandbox_unreachable`, `scan_failed`.
- Payment codes (`solana:`) and mock mode send only the `result` line.
- Read it with `fetch()` plus `res.body.getReader()`, splitting on `\n`. EventSource doesn't support POST.

### ScanResult (shared/scan_result.example.json)
```json
{"scan_id": "3f9a1c2b7d4e", "url": "https://bit.ly/peachtree-park-42",
 "final_url": "https://peachtree-parking-pay.xyz/meter/42", "redirect_chain": ["https://bit.ly/...", "..."],
 "domain": "peachtree-parking-pay.xyz", "page_title": "Peachtree Parking Co. - Pay Your Meter",
 "verdict": "malicious", "jev_score": 0.94, "scam_type": "fake_parking_or_toll",
 "explanation": "Don't pay this. ...",
 "checks": {"impersonates": "fake_parking_or_toll", "impersonates_p": 0.91, "asks_password_p": 0.08,
            "asks_payment_p": 0.97, "prompt_injection_p": 0.03, "malicious_p": 0.94},
 "screenshots": ["..."], "flagged_before": 3, "payment": null, "location": [33.793, -84.324],
 "scanned_at": 1794672000, "scan_ms": 4200}
```
- `verdict`: `safe` | `suspicious` | `malicious`. `scam_type`: `none`, `fake_bank`, `fake_payment_app`, `fake_parking_or_toll`, `fake_delivery`, `fake_government`, `tech_support`, `fake_login_other`, `malware_download`, `other`.
- `flagged_before`: number of reported map pins for this domain within 5 km. It is 0 for payment codes.
- `payment` (Solana Pay codes only): `{"recipient", "amount_sol", "label", "message", "reference", "merchant_verified", "tx_signature"}`. `domain` and `scan_ms` are null for payment codes.

### GET /result/{scan_id}: the follow-up text's page
Follow-up texts link to **`https://scansafe.nyc/r/<scan_id>`. That page doesn't exist yet and needs building.** It should call `GET https://api.scansafe.nyc/result/<scan_id>`, which returns the same ScanResult JSON, or 404 `{"detail": "We couldn't find this check. It may have expired."}`. Results are kept **7 days**. Real ids are 12 lowercase hex characters. The demo mock id `mock-mal-001` always gives 404. Show verdict, explanation, domain and time. A good companion line on that page comes from `/stats/domain/{domain}`.

## 3. FaceTime walkthrough

### POST /call-me
```
POST /call-me   Authorization: Bearer <token>
{"url": "https://example.com/pay", "lat": 33.79, "lng": -84.32}     # lat/lng optional
-> 200 {"call_id": "...", "room": "scansafe-out-...", "status": "allocated"}
```
- The number that gets called is **the token's phone**. When you send a valid token, you can leave `phone` out of the body; it is ignored anyway. Without a token, the body needs `"phone"` and only the server's demo allowlist works (anyone else gets 403).
- Only `http(s)` URLs (400 `"only web links (http/https) can be walked through on a call"`). One call at a time server-wide: 429 `"one call at a time: try again in N s"` (gap of about 30 s).
- 403 `"sign in with your phone first: ..."` means no or invalid token and the number isn't allowlisted, so send the user to sign-in. 503 means calling isn't configured on the server. 504 means the agent didn't get ready (about 20 s). 502 means LiveKit or Chert failed. The request itself can take 20 to 40 s, so use a 45 s client timeout.
- Status: `GET /call-me/{call_id}` returns `{"call_id", "status", "answered", "terminal_reason", "events": [...]}` (404 for ids this server didn't place).

## 4. Map, reports, scan log

| Call | Response |
|---|---|
| `POST /report` `{"scan_id": "..."}` (sending the whole ScanResult is fine, only `scan_id` is read) | `{"stored": true, "code": "pinned", "pin": {...}}` or `{"stored": false, "code": "unknown_scan" \| "not_malicious" \| "no_location" \| "not_pinned", "reason": "<show this>"}`. Only scans this server ran in the last 2 h can be reported. |
| `GET /pins?lat=&lng=&radius_km=1&limit=100` (radius max 100, limit 1 to 250) | `{"count": n, "pins": [{"id", "url", "domain", "scam_type", "jev_score", "explanation", "location": [lat, lng], "reported_at", "distance_m"}]}`, nearest first |
| `GET /search?q=parking&limit=20` (q 1 to 200 chars) | `{"count": n, "results": [pin]}` (typo-tolerant, no `distance_m`) |
| `GET /scans/search?q=&verdict=&scam_type=&lat=&lng=&radius_km=5&page=1&per_page=20` | `{"found", "out_of", "page", "per_page", "hits": [{"id", "url", "final_url", "domain", "verdict", "scam_type", "jev_score", "explanation", "page_title", "scanned_at", "scan_ms", "reported", "highlight"?, "distance_m"?}], "facets": {"verdict": {...}, "scam_type": {...}}}` |

`/scans/search`: an empty `q` or `*` browses newest first. `lat` and `lng` must come together (else 422 `bad_location`) and only match reported scans. `url`, `final_url`, `page_title` and `explanation` can be null (older rows). Details are in `data/README.md` section 5.

## 5. Stats (poll every 30 s)

All of these return 503 `tiger_not_configured` when Tiger Data isn't set up, and 502 `tiger_data_error` on a database hiccup. Show a "Demo" or stale badge then and keep the last good numbers.

### GET /stats/summary
`{"by_verdict": {"safe": {"total": 41, "last_24h": 12}, "malicious": {...}, "suspicious": {...}}, "top_scam_types_24h": [{"scam_type": "fake_parking_or_toll", "total": 4}], "scans_24h": 17, "avg_scan_ms_24h": 5120.4, "avg_score_24h": 0.31}`. Only verdicts that have rows appear. `total` is all-time.

### GET /stats/hourly?hours=24 (1 to 720)
`{"hours": 24, "rows": [{"hour": "2026-11-14T19:00:00+00:00", "scam_type": "none", "verdict": "safe", "total": 5, "avg_score": 0.04, "avg_scan_ms": 4800.0}]}`. One row per (hour, scam_type, verdict). **Hours with no scans have no row**, so fill the gaps yourself.

### GET /stats/impact (new)
```json
{"scans_total": 54, "scans_24h": 17, "scams_blocked": 9, "warned": 4, "safe": 41,
 "est_money_saved_usd": 3420,
 "est_method": {"loss_per_scam_usd": 380,
   "explanation": "38% of 2024 fraud reports involved a loss and the median loss for scams that began with a text was $1,000, so each blocked scam avoids about $380 on average (estimate).",
   "sources": ["https://www.ftc.gov/news-events/news/press-releases/2025/03/new-ftc-data-show-big-jump-reported-losses-fraud-125-billion-2024",
               "https://www.ftc.gov/news-events/news/press-releases/2025/04/new-ftc-data-show-top-text-message-scams-2024-overall-losses-text-scams-hit-470-million",
               "https://www.ftc.gov/system/files/ftc_gov/pdf/csn-annual-data-book-2024.pdf"]},
 "payments_refused": {"count": 2, "sol_total": 0.02,
   "note": "Solana Pay codes refused because the wallet didn't match the merchant. Devnet test SOL, not converted to USD."},
 "repeat_scams": [{"domain": "peachtree-parking-pay.xyz", "times_checked": 5, "times_flagged": 5,
                   "first_seen": "2026-11-14T15:02:11+00:00", "last_seen": "2026-11-14T19:41:05+00:00",
                   "scam_type": "fake_parking_or_toll"}],
 "generated_at": "2026-11-14T20:43:39.363453+00:00"}
```
- Counts are **all-time** except `scans_24h`. `scams_blocked` counts malicious checks, `warned` counts suspicious ones. Each check counts, so the same scam checked twice counts twice.
- `est_money_saved_usd` = `scams_blocked` x `est_method.loss_per_scam_usd`. **Always label it as an estimate** and show `explanation` and `sources` behind an info icon. The server can change the per-scam figure (env `IMPACT_LOSS_PER_SCAM_USD`), and the explanation text then changes with it, so render both from the response and never hard-code $380.
- `payments_refused`: scam payment codes ScanSafe refused, one per scan. `sol_total` is **devnet test SOL** and is never converted to dollars. Amounts over 1000 SOL count toward `count` but not `sol_total`.
- `repeat_scams`: up to 10 domains checked more than once whose checks were mostly flagged, most-checked first. `scam_type` is the most common flagged type (`"other"` if none).
- Cached for 15 s on the server, and `generated_at` says when the numbers were computed. Totals come from the hourly aggregate, so they can lag a deletion by up to 5 min.

### GET /stats/domain/{domain} (new): the "checked N times" line
```json
{"domain": "peachtree-parking-pay.xyz", "times_checked": 5, "times_flagged": 5,
 "first_seen": "2026-11-14T15:02:11+00:00", "last_seen": "2026-11-14T19:41:05+00:00",
 "verdicts": {"safe": 0, "suspicious": 1, "malicious": 4}}
```
- Pass `result.domain`. Matching ignores case. It must be a hostname (a-z, 0-9, dots, dashes, labels not starting or ending with `-`, at most 253 characters). Anything else gets 422 `{"detail": {"error": "bad_domain", ...}}`. Skip the call when `domain` is null (payment codes).
- Never seen: `times_checked: 0`, `first_seen`/`last_seen: null`, all verdicts 0.
- **It counts checks, not people.** No user, device or IP is stored. Write "Checked 5 times on ScanSafe, flagged 5 times", not "5 people".
- The current scan is logged just after its response is sent, and results are cached 15 s per domain. Right after a scan, the count may or may not include it yet.

## 6. Payments (devnet) and health

- `POST /pay` `{"scan_id", "payment": <ScanResult.payment>, "approved": true}` returns `{"ok": true, "scan_id", "signature", "explorer_url", "payment": {..., "tx_signature"}}`. Call it only after the user taps confirm, and only when `verdict == "safe"` and `payment.merchant_verified`. Errors use the `{"ok": false, "error", "message"}` shape. Codes: `not_approved`, `merchant_not_verified` (403); `bad_amount`, `over_cap` (0.05 SOL cap), `bad_address` (400); `not_devnet` (403); `rpc_unreachable`, `rpc_error` (502); `no_wallet`, `bad_wallet`, `payer_unfunded` (503).
- `GET /health` returns `{"ok": true, "mock_mode": false}`.

## 7. curl

```bash
B=https://api.scansafe.nyc
curl -s $B/health
curl -s -X POST $B/scan -H 'Content-Type: application/json' -d '{"url":"https://example.com"}'
curl -sN -X POST $B/scan/stream -H 'Content-Type: application/json' -d '{"url":"https://example.com"}' | cut -c1-120
curl -s $B/result/<scan_id>

# sign-in (use your own phone; then text sms_body to +1 650-444-4331 from it)
curl -s -X POST $B/auth/phone/start  -H 'Content-Type: application/json' -d '{"phone":"+14045550123"}'
curl -s -X POST $B/auth/phone/verify -H 'Content-Type: application/json' -d '{"phone":"+14045550123","request_id":"<request_id>"}'
curl -s $B/auth/me -H "Authorization: Bearer $TOKEN"
# rings the signed-in phone for real
curl -s -X POST $B/call-me -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"url":"https://example.com"}'

curl -s $B/stats/summary
curl -s "$B/stats/hourly?hours=24"
curl -s $B/stats/impact
curl -s $B/stats/domain/peachtree-parking-pay.xyz
curl -s -G $B/scans/search --data-urlencode q=wikipedia
curl -s "$B/pins?lat=33.79&lng=-84.32&radius_km=5"
curl -s -G $B/search --data-urlencode q=parking
curl -s -X POST $B/report -H 'Content-Type: application/json' -d '{"scan_id":"<scan_id from /scan>"}'
```
