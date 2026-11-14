# ScanSafe API contract for the web UI

For whoever builds the UI (and their AI assistant). Every shape below is taken from the route code:
`api/main.py`, `api/routes_data.py`, `api/routes_call.py`, `api/routes_pay.py` (+ `api/meter_pay.py`), `api/routes_result.py`,
`api/routes_accounts.py`, `api/dogwood.py`, `api/lithic_cards.py`, `api/session.py`.
If this file and the code disagree, the code wins. Please tell the backend owner.

- **Base URL:** `https://api.scansafe.nyc`. CORS is an **allowlist with credentials**: `https://scansafe.nyc`, `https://app.scansafe.nyc`, `https://scansafe-demo-sites.vercel.app`, `http://localhost:3000`, `:3300`, `:3400` (plus the old alias `https://app-blond-xi-88.vercel.app`; more via server env `CORS_EXTRA_ORIGINS`). Other origins get no CORS headers.
- JSON in, JSON out (`Content-Type: application/json`). Times are unix seconds (`scanned_at`) or ISO-8601 UTC strings (`hour`, `first_seen`, `generated_at`).
- **Auth:** the phone sign-in token, sent as `Authorization: Bearer <token>` **or** the `ss_session` cookie (set by `/auth/phone/verify`; use `fetch(..., {credentials: "include"})`). Read by `/call-me`, `/auth/me`, `/auth/logout`, `/me*`, `/link/dogwood/*`, `/pay` with a virtual card, and (optionally) `/pay/quote`. Everything else is public. Section 9.
- Treat page-derived text (`page_title`, `explanation`, `url`) as plain text. Never render it as HTML. The only exception is `/scans/search` `highlight`, which is escaped and contains only `<mark>` tags.

## Error shapes (they differ by router)

| Where | Status | Body |
|---|---|---|
| Data and stats (`/report`, `/pins`, `/search`, `/scans/search`, `/stats/*`) | 503 | `{"detail": {"error": "typesense_not_configured" \| "tiger_not_configured", "service": "typesense" \| "tiger_data", "message": "..."}}` |
| same | 502 | `{"detail": {"error": "typesense_error" \| "tiger_data_error", "service": "...", "message": "... request failed, try again."}}` |
| same, bad input we check ourselves | 422 | `{"detail": {"error": "bad_location" \| "bad_domain", "message": "..."}}` |
| Phone sign-in, `/call-me` | 400 / 403 / 429 / 502 / 503 / 504 | `{"detail": "<human-readable string>"}` |
| `/result/{scan_id}` | 404 | `{"detail": "We couldn't find this check. It may have expired."}` |
| `/pay`, `/pay/quote`, `GET /pay/quote/{id}` | 400 / 401 / 402 / 403 / 404 / 409 / 502 / 503 | `{"ok": false, "error": "<code>", "message": "..."}` (codes in section 6, 8 and 9) |
| `/me*`, `/link/*/start`, `/operators/dogwood/app-*`, `/operators/dogwood/api/sessions` (bad input) | 400 / 401 / 403 / 404 / 409 / 502 / 503 | same `{"ok": false, "error", "message"}` shape (section 9) |
| `/operators/dogwood/oauth/*`, `/operators/dogwood/api/*` (auth) | 400 / 401 / 403 | OAuth shape `{"error": "<code>", "error_description": "..."}` |
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
- **Token:** valid for 30 days. The verify response also sets it as the cookie `ss_session` (HttpOnly, Secure, SameSite=Lax, `Domain=.scansafe.nyc`, 30 days), so pages on `*.scansafe.nyc` are signed in with `credentials: "include"` and no JS-visible token. Keeping the token in `localStorage` and sending it as Bearer still works (and is the only option from `localhost`, where the `.scansafe.nyc` cookie isn't sent). On app load call `/auth/me`. If it returns `{"signed_in": false}`, drop the stored token and show "Sign in".
- **Sign out:** `POST /auth/logout` (with the cookie and/or the Bearer token) revokes the token on the server and clears the cookie. Always 200 `{"ok": true, "signed_in": false, "revoked": true|false}`. Then forget any stored token.
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
{"scan_id": "3f9a1c2b7d4e", "url": "https://bit.ly/dogwood-meter-42",
 "final_url": "https://dogwood-meter-pay.xyz/meter/42", "redirect_chain": ["https://bit.ly/...", "..."],
 "domain": "dogwood-meter-pay.xyz", "page_title": "Dogwood Lot & Meter Co. - Pay Your Meter",
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
- Only `http(s)` URLs, or a **verified parking meter payment code** (`solana:...`, see section 8). Anything else gets 400 `"only web links (http/https) or a verified parking meter payment code can be walked through on a call"`. One call at a time server-wide: 429 `"one call at a time: try again in N s"` (gap of about 30 s).
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
 "est_method": {"loss_per_scam_usd": 110,
   "explanation": "In 2024, 11% of fraud reports about scams that began with a text involved a loss, and the median loss was $1,000, so each blocked scam avoids about $110 on average (estimate).",
   "sources": ["https://www.ftc.gov/news-events/news/press-releases/2025/03/new-ftc-data-show-big-jump-reported-losses-fraud-125-billion-2024",
               "https://www.ftc.gov/news-events/news/press-releases/2025/04/new-ftc-data-show-top-text-message-scams-2024-overall-losses-text-scams-hit-470-million",
               "https://www.ftc.gov/system/files/ftc_gov/pdf/csn-annual-data-book-2024.pdf"]},
 "payments_refused": {"count": 2, "sol_total": 0.02,
   "note": "Solana Pay codes refused because the wallet didn't match the merchant. Devnet test SOL, not converted to USD."},
 "repeat_scams": [{"domain": "dogwood-meter-pay.xyz", "times_checked": 5, "times_flagged": 5,
                   "first_seen": "2026-11-14T15:02:11+00:00", "last_seen": "2026-11-14T19:41:05+00:00",
                   "scam_type": "fake_parking_or_toll"}],
 "generated_at": "2026-11-14T20:43:39.363453+00:00"}
```
- Counts are **all-time** except `scans_24h`. `scams_blocked` counts malicious checks, `warned` counts suspicious ones. Each check counts, so the same scam checked twice counts twice.
- `est_money_saved_usd` = `scams_blocked` x `est_method.loss_per_scam_usd`. **Always label it as an estimate** and show `explanation` and `sources` behind an info icon. The server can change the per-scam figure (env `IMPACT_LOSS_PER_SCAM_USD`), and the explanation text then changes with it, so render both from the response and never hard-code the figure (currently $110).
- `payments_refused`: scam payment codes ScanSafe refused, one per scan. `sol_total` is **devnet test SOL** and is never converted to dollars. Amounts over 1000 SOL count toward `count` but not `sol_total`.
- `repeat_scams`: up to 10 domains checked more than once whose checks were mostly flagged, most-checked first. `scam_type` is the most common flagged type (`"other"` if none).
- Cached for 15 s on the server, and `generated_at` says when the numbers were computed. Totals come from the hourly aggregate, so they can lag a deletion by up to 5 min.

### GET /stats/domain/{domain} (new): the "checked N times" line
```json
{"domain": "dogwood-meter-pay.xyz", "times_checked": 5, "times_flagged": 5,
 "first_seen": "2026-11-14T15:02:11+00:00", "last_seen": "2026-11-14T19:41:05+00:00",
 "verdicts": {"safe": 0, "suspicious": 1, "malicious": 4}}
```
- Pass `result.domain`. Matching ignores case. It must be a hostname (a-z, 0-9, dots, dashes, labels not starting or ending with `-`, at most 253 characters). Anything else gets 422 `{"detail": {"error": "bad_domain", ...}}`. Skip the call when `domain` is null (payment codes).
- Never seen: `times_checked: 0`, `first_seen`/`last_seen: null`, all verdicts 0.
- **It counts checks, not people.** No user, device or IP is stored. Write "Checked 5 times on ScanSafe, flagged 5 times", not "5 people".
- The current scan is logged just after its response is sent, and results are cached 15 s per domain. Right after a scan, the count may or may not include it yet.

## 6. Payments (devnet) and health

- `POST /pay` `{"scan_id", "approved": true}` returns `{"ok": true, "scan_id", "signature", "explorer_url", "payment": {..., "tx_signature"}, "amount_sol", "hours"}`. Call it only after the user taps confirm, and only when `verdict == "safe"` and `payment.merchant_verified`. The server pays from **its own copy of the scan** (`scan_id`). Sending `"payment": <ScanResult.payment>` still works (it's only used if the server no longer has that scan), but the server never trusts its `amount_sol` for parking meters or its `merchant_verified` for anyone. Parking meters **require** `"hours"` (section 8). One payment per `scan_id`. Optional `"payment_method": "solana_devnet"` (default) or `"virtual_card"` (a one-time Lithic sandbox card, signed in with Dogwood linked; section 9).
- Errors use the `{"ok": false, "error", "message"}` shape. Codes: `not_approved`, `merchant_not_verified` (403); `unknown_scan` (404); `not_a_payment`, `hours_required`, `bad_hours`, `bad_amount`, `over_cap` (0.05 SOL cap), `bad_address` (400); `already_paid`, `payment_in_progress` (409); `not_devnet` (403); `rpc_unreachable`, `rpc_error` (502); `no_wallet`, `bad_wallet`, `payer_unfunded` (503).
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
curl -s $B/stats/domain/dogwood-meter-pay.xyz
curl -s -G $B/scans/search --data-urlencode q=wikipedia
curl -s "$B/pins?lat=33.79&lng=-84.32&radius_km=5"
curl -s -G $B/search --data-urlencode q=parking
curl -s -X POST $B/report -H 'Content-Type: application/json' -d '{"scan_id":"<scan_id from /scan>"}'
```

## 8. Parking meter: pay by the hour

Demo merchant **Dogwood Lot & Meter Co.** (`fixtures/qr/real_meter.png`, a Solana Pay code on **devnet**) sells parking by the hour: **0.01 test SOL per hour, 1 to 4 hours**. The server sets the price. **The app never sends its own amount**: it sends `hours`, and the server computes rate x hours. Fixed-price codes (Magnolia Diner) work exactly as before (section 6) and have no hours picker.

### User flow

1. **Scan** the meter's QR code (`POST /scan` or `/scan/stream`, body `{"url": "solana:..."}`). The ScanResult has `verdict: "safe"`, `payment.merchant_verified: true`, `payment.label: "Dogwood Lot & Meter Co."` and a `scan_id`. Keep the `scan_id`: every call below uses it.
2. **Result screen:** show the verified merchant ("Dogwood Lot & Meter Co. · verified wallet"), and right away call `POST /pay/quote {"scan_id", "hours": 1}`. Its answer tells you it's a meter (`rate_per_hour_sol`, `min_hours`, `max_hours`). Show the rate ("0.01 test SOL per hour"), an **hours picker 1 to 4** (from `min_hours`/`max_hours`), and the **total from the quote's `amount_sol`** (don't compute it yourself). If the quote answers 400 `not_a_meter`, it's a fixed-price code: show `payment.amount_sol` and no picker.
3. **Optional "Watch on FaceTime"** button (only when signed in): `POST /call-me` with `Authorization: Bearer <token>` and `{"url": "<the solana: code exactly as scanned>", "scan_id": "<scan_id>"}`. ScanSafe FaceTimes the user. The agent says who the code belongs to and the rate, and shows the meter page live on its video.
4. **Changing hours:** each change calls `POST /pay/quote {"scan_id", "hours": n}`, **debounced about 500 ms** (send only the last value after the user stops tapping). Update the total from the response. If a FaceTime call is on, the agent picks up the new hours within about 2 to 4 s, says "Okay, 3 hours, 0.03 SOL." and the live meter page on the call updates.
5. **Pay:** the Pay button opens a **confirm step** ("Pay 0.03 test SOL to Dogwood Lot & Meter Co. for 3 hours? [Cancel] [Pay]"). Only the confirm button sends `POST /pay {"scan_id", "hours": 3, "approved": true}`. Disable it while the request runs (one payment per scan; a second one gets 409).
6. **Receipt:** from the `/pay` response: hours, `amount_sol`, merchant, and a link to `explorer_url` ("View on Solana Explorer (devnet)"). `GET /pay/status/{scan_id}` gives the same facts later (e.g. after a reload). On a call, the agent says "Paid. 3 hours on meter 42. Your receipt is in the app." and its video shows a green "Paid" banner.

The agent never pays and can't change the hours. Only the app's confirm button pays.

### POST /pay/quote
```
POST /pay/quote
{"scan_id": "3f9a1c2b7d4e", "hours": 3}
-> 200 {"scan_id": "3f9a1c2b7d4e", "merchant": "Dogwood Lot & Meter Co.",
        "rate_per_hour_sol": 0.01, "hours": 3, "amount_sol": 0.03,
        "min_hours": 1, "max_hours": 4,
        "meter_url": "https://scansafe-demo-sites.vercel.app/fixtures/meter/index.html",
        "updated_at": 1794672123.456}
```
- `scan_id` must be a scan this server ran (kept 2 h in memory, 7 days on disk). The latest quote per `scan_id` is kept in memory (2 h; an API restart forgets it, so just quote again).
- A quote is only "what the user is looking at": it gives you the total to show and drives the FaceTime agent's live view. **`/pay` never reads it.** Always send the confirmed `hours` to `/pay`.
- `hours` must be a whole number from `min_hours` to `max_hours` (JSON number; `3` or `3.0`, not `"3"`).
- `updated_at` is unix seconds (float).

### GET /pay/quote/{scan_id}
Returns the latest quote (same JSON as above), or 404 `{"ok": false, "error": "no_quote", ...}` if no hours were picked yet. The FaceTime agent polls this; the app normally doesn't need it.

### POST /pay (meter)
```
POST /pay
{"scan_id": "3f9a1c2b7d4e", "hours": 3, "approved": true}
-> 200 {"ok": true, "scan_id": "3f9a1c2b7d4e",
        "signature": "5Kx...", "explorer_url": "https://explorer.solana.com/tx/5Kx...?cluster=devnet",
        "amount_sol": 0.03, "hours": 3,
        "payment": {"recipient": "6jQGteA52iYssC8A8ss3tsnfGtPCAGPaDH5Z1o8X66TL", "amount_sol": 0.03,
                    "label": "Dogwood Lot & Meter Co.", "message": "Meter 42 - 3 hours",
                    "reference": "...", "merchant_verified": true, "tx_signature": "5Kx..."}}
```
- `hours` is **required** for meters: the hours the user confirmed. Without it: 400 `hours_required` (`"hours is required: pick 1 to 4 hours."`). The server never falls back to the stored quote. (Fixed-price codes ignore `hours`.)
- Do **not** send `amount_sol`. If a `payment` object is sent anyway, its amount is ignored for meters and its recipient is ignored whenever the server has the scan.
- Takes a few seconds (devnet). Use a 30 s client timeout.

### GET /pay/status/{scan_id}
```
-> 200 {"scan_id": "3f9a1c2b7d4e", "state": "none"}
-> 200 {"scan_id": "...", "state": "paid", "signature": "5Kx...", "explorer_url": "https://explorer.solana.com/tx/...?cluster=devnet",
        "amount_sol": 0.03, "hours": 3, "merchant": "Dogwood Lot & Meter Co."}
-> 200 {"scan_id": "...", "state": "failed", "error": "payer_unfunded", "message": "...", "amount_sol": 0.03, "hours": 3, "merchant": "..."}
```
Always 200. `state` is `none` (not paid, or unknown id), `paid`, or `failed` (the last attempt failed; the user may try again, and a success replaces it). `hours` is `null` for fixed-price codes. Kept in memory for 2 h.

### POST /call-me (meter code)
```
POST /call-me   Authorization: Bearer <token>
{"url": "solana:6jQGteA52iYssC8A8ss3tsnfGtPCAGPaDH5Z1o8X66TL?amount=0.01&reference=...&label=Dogwood%20Lot%20%26%20Meter%20Co.&message=Meter%2042",
 "scan_id": "3f9a1c2b7d4e"}
-> 200 {"call_id": "...", "room": "scansafe-out-...", "status": "allocated", "scan_id": "3f9a1c2b7d4e"}
```
- `url` is the code exactly as scanned. Only codes that pay a **verified** merchant **that sells by the hour** are accepted. A fake sticker, a fixed-price code or any other `solana:` code gets 400 (string `detail`, see section 3).
- `scan_id` should be the app's scan of this code, so the agent follows *your* quotes and payment. If you leave it out, the server makes its own scan and returns its `scan_id`: use that one for quotes and `/pay`.
- 404 `"we couldn't find that scan; scan the meter code again"` (unknown or expired `scan_id`), 400 `"scan_id belongs to a different code"`. Other errors as in section 3.

### Errors and what to show (plain words)

| Status | `error` | Show |
|---|---|---|
| 400 | `hours_required` | Bug in the app: `/pay` for a meter was sent without `hours` |
| 400 | `bad_hours` | "Pick 1 to 4 hours." (the `message` says the exact range) |
| 400 | `not_a_meter` | Not an error: fixed-price code, hide the hours picker |
| 400 | `not_a_payment` | "This code isn't a payment." |
| 404 | `unknown_scan` | "This scan expired. Please scan the meter code again." |
| 403 | `merchant_not_verified` | "Don't pay this. The money wouldn't go to Dogwood Lot & Meter Co." (red, no Pay button) |
| 403 | `not_approved` | Bug in the app: `/pay` was sent without the confirm step |
| 409 | `already_paid` | "Already paid. Here's your receipt." then load `GET /pay/status/{scan_id}` |
| 409 | `payment_in_progress` | "Paying..." (keep the button disabled, poll `/pay/status` in 2 s) |
| 400 | `over_cap` | "This demo only pays up to 0.05 test SOL." |
| 503 | `payer_unfunded` | "The demo wallet is out of test money. Please tell the ScanSafe team." |
| 502 / 503 | `rpc_unreachable`, `rpc_error`, `no_wallet`, `bad_wallet` | "Couldn't reach the payment network. Nothing was paid. Try again in a minute." |

Show the `message` field only in a details/debug area; the table's wording is for the user.

### curl
```bash
B=https://api.scansafe.nyc
QR='solana:6jQGteA52iYssC8A8ss3tsnfGtPCAGPaDH5Z1o8X66TL?amount=0.01&label=Dogwood%20Lot%20%26%20Meter%20Co.&message=Meter%2042'
SID=$(curl -s -X POST $B/scan -H 'Content-Type: application/json' -d "{\"url\":\"$QR\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["scan_id"])')
curl -s -X POST $B/pay/quote -H 'Content-Type: application/json' -d "{\"scan_id\":\"$SID\",\"hours\":3}"
curl -s $B/pay/quote/$SID
curl -s $B/pay/status/$SID
# rings the signed-in phone for real; the agent follows the quotes above
curl -s -X POST $B/call-me -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d "{\"url\":\"$QR\",\"scan_id\":\"$SID\"}"
# pays 0.03 devnet test SOL for real (devnet only)
curl -s -X POST $B/pay -H 'Content-Type: application/json' -d "{\"scan_id\":\"$SID\",\"hours\":3,\"approved\":true}"
```

## 9. Saved accounts, linked Dogwood, one-time virtual cards

**Test money only.** Payments are Solana **devnet** test SOL or a **one-time virtual card from Lithic's SANDBOX** (no real card network, no real money). **Dogwood Lot & Meter Co. is a fictional operator**: ScanSafe hosts its demo OAuth server and API under `/operators/dogwood`, and its pages live on `https://scansafe-demo-sites.vercel.app/dogwood/...`. Label those screens "Demo" / "Sandbox".

Everything here needs the phone sign-in (section 1): the `ss_session` cookie (`fetch(url, {credentials: "include"})`) or `Authorization: Bearer <token>`. A cookie only counts for POST/PUT/DELETE when the request comes from an allowlisted origin. **Linking Dogwood needs the cookie** (the callback is a browser redirect, which carries cookies but never a Bearer header), so link from a page on `*.scansafe.nyc`. Errors are `{"ok": false, "error": "<code>", "message": "<plain words>"}`; the table at the end says what to show.

### Flows

```
Accounts page (app.scansafe.nyc/accounts)
  GET /me                                       -> profile + linked accounts + which payment methods work
  PUT /me {"plate": "gx 4242"}                  -> saved as "GX 4242"
  PUT /me {"preferred_payment": "virtual_card"} -> preselects the card on the pay sheet

Connect Dogwood (demo OAuth, authorization code)
  1. fetch GET /link/dogwood/start (credentials: "include")
                                                -> {"authorize_url": "https://scansafe-demo-sites.vercel.app/dogwood/authorize?..."}
                                                   + sets cookie ss_link_nonce (Path=/link, 10 min)
  2. window.location.href = authorize_url       (same tab; the consent page is the other team's)
  3. consent page -> POST /operators/dogwood/oauth/authorize -> browser goes to api.scansafe.nyc/link/dogwood/callback
  4. the callback checks the nonce cookie + that this browser is signed in as the same person, trades the
     code for a Dogwood token, stores it encrypted, and 302s to
     APP_BASE_URL/accounts?linked=dogwood        (or ?link_error=<code>&provider=dogwood)

Disconnect: DELETE /me/linked/dogwood

Pay sheet (scan -> result -> pay)
  POST /pay/quote {"scan_id","hours"}           -> amount_sol AND amount_usd (the virtual-card price)
  POST /pay {"scan_id","hours","approved":true,"payment_method":"solana_devnet"|"virtual_card"}
    virtual_card: the server mints a SINGLE_USE Lithic sandbox card capped at exactly amount_usd, Dogwood
    charges it server to server (simulated authorization + clearing in Lithic's sandbox), the card is closed.

FaceTime agent's live Dogwood app (agent + demo-sites, not the ScanSafe app)
  agent:   POST /operators/dogwood/app-session {"scan_id"}  (X-Agent-Key) -> {"app_url", "plate", "linked"}
  browser: GET  /operators/dogwood/app-state?s=<token>       -> meter, plate, hours, amount, status, receipt
  browser: POST /operators/dogwood/app-state?s=<token> {"hours": 3}
```

`APP_BASE_URL` is a server setting (`https://app.scansafe.nyc`). If it isn't set, link callbacks go to `https://scansafe.nyc/?linked=...` instead.

### App routes to build (teammate)

**`app.scansafe.nyc/accounts`**
- Signed out (`GET /me` gives `{"signed_in": false}`): "Sign in with your phone" (section 1).
- Profile: masked phone (`phone_masked`), **plate** input (2 to 10 letters, numbers, spaces or dashes; show it uppercased; save with `PUT /me {"plate"}`; empty clears it), **preferred payment**: "Devnet wallet (test SOL)" or "One-time virtual card" (`PUT /me {"preferred_payment": "solana_devnet" | "virtual_card"}`; disable the card option when `payment_methods.virtual_card` is false).
- **Linked accounts**: Dogwood Parking row. Linked: `display` + "linked <date>" (`linked_at`) + **Disconnect** (`DELETE /me/linked/dogwood`, then reload `/me`). Not linked: **Connect Dogwood** (`fetch("/link/dogwood/start", {credentials: "include"})`, then `location.href = authorize_url`).
- On load, read `?linked=dogwood` ("Dogwood Parking connected.") or `?link_error=<code>&provider=dogwood` (table below), show a toast once, remove the query with `history.replaceState`, and reload `/me`.

**Scan -> pay sheet**: after the result screen (section 8 for meters), the Pay button opens a sheet with a **method choice** preselected from `preferred_payment`:
- **"Pay with devnet wallet"**: total = quote `amount_sol` ("0.03 test SOL"), exactly as in section 8.
- **"Pay with a one-time virtual card"**: only for Dogwood meters, only when `payment_methods.virtual_card` is true, Dogwood is in `linked` and `plate` is set (otherwise show what's missing with a link to `/accounts`). Total = quote `amount_usd` ("$7.50, sandbox card"). Small print: "A new card is made for exactly this amount, used once by Dogwood, then closed."
- Confirm step as in section 8, then `POST /pay` with `"payment_method"`. Always send it; when it's missing the server uses `solana_devnet`, whatever the preference. Use a 45 s client timeout for the card (several sandbox calls).
- Receipt: devnet: `explorer_url`. Card: "Paid $7.50 with a one-time virtual card ••4142 (Lithic sandbox)" from `card_last4` + `amount_usd`.

### GET /me
```
-> 200 {"signed_in": false}                       (not signed in; never an error)
-> 200 {"signed_in": true, "phone_masked": "•••9861", "plate": "GX 4242", "preferred_payment": "solana_devnet",
        "linked": [{"provider": "dogwood", "display": "Dogwood Parking", "linked_at": "2026-11-14T22:41:05.123+00:00"}],
        "providers": {"dogwood": true},
        "payment_methods": {"solana_devnet": true, "virtual_card": true},
        "virtual_card_usd_per_hour": 2.5}
```
- `plate` is null until set. `preferred_payment` is `"solana_devnet"` until set. `linked` lists only active links. `payment_methods.virtual_card` is false when Lithic isn't configured on the server.
- Errors: 503 `accounts_not_configured`, 502 `accounts_store_error`.

### PUT /me
Body `{"plate"?: string|null, "preferred_payment"?: "solana_devnet"|"virtual_card"|null}`. Fields you leave out are unchanged; `null` (or `""` for plate) clears. Returns the same JSON as `GET /me`.
- 400 `bad_plate` (`"Plates are 2 to 10 letters, numbers, spaces or dashes."`), 400 `bad_preferred_payment`, 401 `not_signed_in`. A non-string plate gets FastAPI's 422.

### GET /me/linked, DELETE /me/linked/{provider}
- `GET /me/linked` -> `{"linked": [...]}` (same items as `/me`). 401 `not_signed_in`.
- `DELETE /me/linked/dogwood` -> `{"ok": true, "provider": "dogwood", "revoked": true}` (`false`: it wasn't linked; still 200). The Dogwood token is revoked at the operator too and the stored ciphertext is wiped. 404 `unknown_provider`, 401 `not_signed_in`.

### GET /link/dogwood/start
```
-> 200 {"authorize_url": "https://scansafe-demo-sites.vercel.app/dogwood/authorize?client_id=scansafe
        &redirect_uri=https%3A%2F%2Fapi.scansafe.nyc%2Flink%2Fdogwood%2Fcallback&scope=pay_parking
        &state=<signed, 10 min>&display=%E2%80%A2%E2%80%A2%E2%80%A29861"}
   Set-Cookie: ss_link_nonce=<random>; HttpOnly; Secure; SameSite=Lax; Domain=.scansafe.nyc; Path=/link; Max-Age=600
```
- `state` is signed by the server, holds the account and sha256 of the nonce cookie, is valid 10 minutes and works once. `display` is the masked phone for the consent page.
- 401 `not_signed_in`, 503 `accounts_not_configured` (no store or no `ACCOUNT_KEY`).

### Dogwood consent page -> POST /operators/dogwood/oauth/authorize (other team's page)
```
POST /operators/dogwood/oauth/authorize
{"client_id": "scansafe", "redirect_uri": "https://api.scansafe.nyc/link/dogwood/callback",
 "scope": "pay_parking", "state": "<state from the URL>", "decision": "allow"}
-> 200 {"redirect": "https://api.scansafe.nyc/link/dogwood/callback?code=dwc_...&state=..."}
decision "deny" -> 200 {"redirect": "...callback?error=access_denied&state=..."}
scope other than pay_parking -> 200 {"redirect": "...callback?error=invalid_scope&state=..."}
```
- The page then sets `window.location.href = redirect`.
- 400 (OAuth shape, no redirect): `invalid_client` (client_id isn't `scansafe`), `invalid_redirect_uri` (anything but the exact registered URI: no prefixes, extra path, query or slash), `invalid_state` (tampered, for another purpose, or older than 10 min; `error_description` says "This link expired. Go back to ScanSafe and tap Connect again."), `invalid_request` (decision isn't allow/deny).
- The code is single use and expires after 5 minutes; reusing it revokes the token it was exchanged for. Dogwood has no login of its own: the demo account comes from the ScanSafe sign-in that started the link (`/api/me` name "Demo driver •••9861").

### GET /link/dogwood/callback?code&state (browser, from the consent page)
Links only when **all** hold, else 302 `...?link_error=<code>&provider=dogwood`: the `ss_link_nonce` cookie is present and matches the state (`invalid_state` otherwise), this browser is signed in with `ss_session` (`sign_in_first`) as the same person who started (`signed_in_as_someone_else`), and the state wasn't used before (`invalid_state`; a refused try also spends it). Then it exchanges the code in-process with the operator token endpoint (`POST /operators/dogwood/oauth/token`, form `grant_type=authorization_code&code&redirect_uri&client_id&client_secret`; also open over HTTP, answers `{"access_token", "token_type": "Bearer", "expires_in", "scope", "account_id"}`), stores the Dogwood access token **encrypted** as provider `dogwood` (meta `{"account_name": "Dogwood Parking", "scope": "pay_parking"}`), revokes any previous Dogwood link, clears the nonce cookie, and answers **302** to `APP_BASE_URL/accounts?linked=dogwood`. Never JSON.

### Dogwood operator API (Bearer = the Dogwood access token; ScanSafe keeps it encrypted)
| Call | Response |
|---|---|
| `GET /operators/dogwood/api/me` | `{"account_id": "dw_...", "name": "Demo driver •••9861"}` |
| `POST /operators/dogwood/api/sessions` `{"meter_id": "42", "plate": "GX 4242", "hours": 3}` | `{"session_id": "dws_...", "meter_id": "42", "plate": "GX 4242", "hours": 3, "amount_sol": 0.03, "amount_usd": 7.5, "status": "pending_payment"}` |
| `GET /operators/dogwood/api/sessions/{session_id}` | same object (+ `"payment"` once paid); only the account that created it, else 404 `unknown_session` |
| `POST /operators/dogwood/api/sessions/{session_id}/pay` `{"card": {"token", "pan", "cvv", "exp_month", "exp_year", "last_four"}}` (the Lithic card object) | session with `"status": "paid"`, `"payment": {"method": "virtual_card", "provider": "lithic_sandbox", "card_last4", "card_token", "authorization_token", "settled", "simulated": true, "amount_usd", "paid_at"}` |

- `/pay` runs `POST /v1/simulate/authorize {"amount": <amount_usd in cents>, "descriptor": "DOGWOOD LOT & METER", "pan", "mcc": "7523"}` on Lithic's sandbox (the card's own spend limit really applies) and then `/v1/simulate/clearing`. Dogwood keeps **only** `card_last4` + the Lithic `card_token`. The body is never echoed: bad card -> 400 `card_invalid`, a decline -> 402 `card_declined`, already paid -> 409 `already_paid`. ScanSafe's own `/pay` calls this in-process (server to server); nobody else needs to.
- 401 `{"error": "invalid_token"}` (+ `WWW-Authenticate: Bearer`) for a missing, revoked or expired token; 403 `insufficient_scope`; 404 `unknown_meter` (only meter `42`); 400 `bad_plate`, `bad_hours` (1 to 4).

### Agent live view: POST /operators/dogwood/app-session, GET/POST /operators/dogwood/app-state
```
POST /operators/dogwood/app-session      X-Agent-Key: <AGENT_INTERNAL_KEY>      (agent server only)
{"scan_id": "3f9a1c2b7d4e"}
-> 200 {"app_url": "https://scansafe-demo-sites.vercel.app/dogwood/app?s=<one-time token>",
        "plate": "GX 4242", "linked": true, "expires_in": 900}

GET /operators/dogwood/app-state?s=<token>          (the Dogwood web app polls this from the browser)
-> 200 {"meter_id": "42", "operator": "Dogwood Lot & Meter Co.", "plate": "GX 4242",
        "hours": 3, "rate_per_hour_sol": 0.01, "amount_sol": 0.03, "min_hours": 1, "max_hours": 4,
        "status": "waiting_for_approval"}
   paid with the devnet wallet -> also "payment_method": "solana_devnet",
        "receipt": {"signature": "5Kx...", "explorer_url": "https://explorer.solana.com/tx/...?cluster=devnet",
                    "paid_at": 1794696115, "method": "solana_devnet"}
   paid with a virtual card -> "payment_method": "virtual_card", "amount_usd": 7.5,
        "receipt": {"method": "virtual_card", "provider": "lithic_sandbox", "card_last4": "4142", "amount_usd": 7.5,
                    "paid_at": 1794696115, "signature": null, "explorer_url": null, "dogwood_session_id": "dws_...",
                    "text": "Paid with a one-time virtual card ••4142 (Lithic sandbox)"}

POST /operators/dogwood/app-state?s=<token>   {"hours": 2}   -> the new app-state
```
- `status`: `choose` (no hours picked yet), `waiting_for_approval` (hours picked in the ScanSafe app or the Dogwood app; waiting for the user's confirm in ScanSafe), `paid`. It mirrors `/pay/quote` and `/pay/status` for that scan. `hours`/`amount_sol` are null while `choose`. `paid_at` is unix seconds. Show `receipt.text` as is.
- `plate`/`linked`: from the saved account of the person this scan belongs to: the person `/call-me` rang for this meter code (or the first signed-in `/pay/quote` / `/pay` for it). Null/false otherwise.
- The token in `app_url` is signed, works only for that scan, lasts **15 minutes**, and a newer `app-session` for the same scan **replaces** it (the old link gets 401 `app_link_invalid`). Expired: 401 `app_link_expired`.
- `POST app-state` changes the scan's quote (what the agent says and shows). It **never pays**; only the ScanSafe app's confirm button pays, with its own hours. 409 `already_paid` once paid; 400 `bad_hours`.
- app-session errors: 401 `bad_agent_key`, 503 `agent_key_not_configured`, 404 `unknown_scan`, 400 `not_a_meter` / `not_dogwood` / `not_a_payment`, 403 `merchant_not_verified`.

### POST /pay with a one-time virtual card (Lithic sandbox)
```
POST /pay   (cookie or Bearer)
{"scan_id": "3f9a1c2b7d4e", "hours": 3, "approved": true, "payment_method": "virtual_card"}
-> 200 {"ok": true, "scan_id": "3f9a1c2b7d4e", "method": "virtual_card", "provider": "lithic_sandbox",
        "amount_usd": 7.5, "currency": "USD", "hours": 3, "merchant": "Dogwood Lot & Meter Co.",
        "card_last4": "4142", "card_token": "<lithic card token>", "authorization_token": "<lithic tx token>",
        "settled": true, "simulated": true, "card_closed": true, "dogwood_session_id": "dws_...",
        "paid_at": 1794696115, "payment": {...}}
GET /pay/status/3f9a1c2b7d4e
-> 200 {"scan_id": "...", "state": "paid", "method": "virtual_card", "provider": "lithic_sandbox",
        "card_last4": "4142", "card_token": "...", "amount_usd": 7.5, "authorization_token": "...", ...}
```
- Needs: signed in, `approved: true`, explicit `hours` (the stored quote is never used), a **verified Dogwood meter** code, **Dogwood linked** and a **plate** saved. One payment per `scan_id` whichever method (a second one gets 409 `already_paid`).
- Amount: `hours x DOGWOOD_RATE_USD` (default $2.50/h: 3 h = $7.50; the quote's `amount_usd`). The server mints a Lithic `SINGLE_USE` card with `spend_limit` = exactly that in cents (`spend_limit_duration: TRANSACTION`, memo `ScanSafe · Dogwood meter 42 · <scan_id>`), opens a Dogwood parking session for your plate, has Dogwood charge the card (above), then closes the card. The card is also closed on any failure. Demo cap $25 (`VIRTUAL_CARD_MAX_USD`).
- The card number, CVV and expiry never leave the server: they are not logged, stored or returned. Only `card_last4` and the Lithic `card_token` are kept.
- Solana's `/pay` response is unchanged; its status now also has `"method": "solana_devnet"` and `"paid_at"`.
- Errors: 401 `not_signed_in`, 403 `dogwood_not_linked`, 400 `plate_required`, 400 `not_a_meter` / `not_dogwood` (fixed-price codes: devnet wallet only), 400 `over_cap`, 400 `bad_payment_method`, 402 `card_declined` (status becomes `failed`; the user may retry, with a fresh card), 400 `card_invalid`, 409 `dogwood_relink_needed`, 503 `lithic_not_configured` / `lithic_sandbox_only`, 502 `lithic_unreachable` / `lithic_auth_failed` / `lithic_error` / `lithic_no_pan` / `dogwood_error`.

### Errors and what to show (plain words)

| Where | `error` / `link_error` | Show |
|---|---|---|
| any | `not_signed_in` (401) | "Sign in with your phone first." -> sign-in |
| `/me*`, link start | `accounts_not_configured` (503) | "Saved accounts aren't available right now." |
| `/me*` | `accounts_store_error` (502) | "We couldn't reach your saved account. Try again in a minute." |
| `PUT /me` | `bad_plate` (400) | "Plates are 2 to 10 letters, numbers, spaces or dashes." |
| `/pay` card | `dogwood_not_linked` (403) | "Connect Dogwood Parking first." (link to /accounts) |
| `/pay` card | `plate_required` (400) | "Add your plate first." (link to /accounts) |
| `/pay` card | `lithic_not_configured`, `lithic_sandbox_only` (503) | "Virtual cards aren't available right now." (hide the option) |
| `/pay` card | `card_declined` (402) | "The card was declined. Nothing was charged." |
| `/pay` card | `dogwood_relink_needed` (409) | "Please reconnect Dogwood Parking in your account." |
| `/pay` card | `lithic_*`, `dogwood_error`, `card_invalid` (502/400) | "Couldn't pay with a virtual card. Nothing was charged. Try again or use the devnet wallet." |
| callback | `access_denied` | "You didn't allow ScanSafe to use your Dogwood account." |
| callback | `sign_in_first` | "Sign in on this browser first, then tap Connect again." |
| callback | `link_expired` | "That took too long. Tap Connect again." |
| callback | `invalid_state` | "That link didn't work. Tap Connect again (in this same browser)." |
| callback | `signed_in_as_someone_else` | "You're signed in with a different phone in this browser. Sign out and try again." |
| callback | `dogwood_refused`, `dogwood_error`, `server_error` | "We couldn't connect that account. Try again." |

### Server setup (agent server `~/HackEmory-2026/.env`, never commit values, never paste them in chat)

1. **Lithic sandbox key:** sign up at the Lithic Dashboard (lithic.com, free sandbox), open Program settings / API keys **in Sandbox**, and copy the sandbox API key. It only works against `https://sandbox.lithic.com`, which is the only host the code ever calls.
2. On the server:
```bash
ssh root@144.202.25.65
cd ~/HackEmory-2026
python3 -c 'import cryptography'      # must print nothing (it's installed: 50.0.2); else pip install cryptography
# Generate on the server and append without echoing (each line prints nothing):
echo "ACCOUNT_KEY=$(python3 -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')" >> .env
echo "ACCOUNT_PEPPER=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')" >> .env
echo "AGENT_INTERNAL_KEY=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')" >> .env
echo "APP_BASE_URL=https://app.scansafe.nyc" >> .env
echo "LITHIC_ENV=sandbox" >> .env
nano .env      # paste LITHIC_API_KEY=<sandbox key>   (optional DOGWOOD_RATE_USD=2.50, VIRTUAL_CARD_MAX_USD=25)
chmod 600 .env
python3 -m data.setup       # optional: "OK   Tiger Data: accounts + linked_accounts ready" (tables are also created on first use)
systemctl restart scansafe-api scansafe-agent    # .env is read at start; the agent needs AGENT_INTERNAL_KEY too
```
- `ACCOUNT_PEPPER`: if it's missing the API generates one into `~/.scansafe-account-pepper` (chmod 600) on first use. **Never change or lose it** once accounts exist: every saved account is keyed by `sha256(phone + pepper)`, and the OAuth-state / app-link signing keys and the Dogwood demo client secret derive from it.
- `ACCOUNT_KEY`: losing or rotating it makes stored Dogwood links unreadable (users reconnect; `/pay` answers `dogwood_relink_needed`).
- `LITHIC_ENV` must be exactly `sandbox`, or card payments answer 503 `lithic_sandbox_only`.
- Dogwood operator tokens and sessions live in `~/.scansafe-dogwood-operator.json` (chmod 600, token hashes, card last4 + Lithic card tokens only); override with `DOGWOOD_OPERATOR_FILE`.
- Optional: `API_BASE_URL` (default `https://api.scansafe.nyc`, builds the redirect URI), `DOGWOOD_SITE_URL` (default `https://scansafe-demo-sites.vercel.app`), `SESSION_COOKIE_DOMAIN` (default `.scansafe.nyc`; empty = host-only, for local dev), `CORS_EXTRA_ORIGINS`, `ACCOUNTS_STORE=memory` (local dev only, forgets on restart).

### curl
```bash
B=https://api.scansafe.nyc; H="Authorization: Bearer $TOKEN"
curl -s $B/me -H "$H"
curl -s -X PUT $B/me -H "$H" -H 'Content-Type: application/json' -d '{"plate":"gx 4242","preferred_payment":"virtual_card"}'
curl -s $B/me/linked -H "$H"
curl -s -X DELETE $B/me/linked/dogwood -H "$H"
curl -s -X POST $B/auth/logout -H "$H"
# (linking Dogwood is a browser flow: it needs the ss_session + ss_link_nonce cookies)
# pays $7.50 with a one-time Lithic SANDBOX card (test money; needs Dogwood linked + a plate)
curl -s -X POST $B/pay -H "$H" -H 'Content-Type: application/json' -d "{\"scan_id\":\"$SID\",\"hours\":3,\"approved\":true,\"payment_method\":\"virtual_card\"}"
curl -s $B/pay/status/$SID
# agent server only
curl -s -X POST localhost:8000/operators/dogwood/app-session -H "X-Agent-Key: $AGENT_INTERNAL_KEY" -H 'Content-Type: application/json' -d "{\"scan_id\":\"$SID\"}"
curl -s "$B/operators/dogwood/app-state?s=<token from app_url>"
```
