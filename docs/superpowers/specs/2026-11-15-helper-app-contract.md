# Toolstone helper app ("runner"): shared contract

Three pieces built in parallel: the relay API (api/), the helper app on the user's computer
(runner/), and the FaceTime agent tools (chert/ + plugins/). This file is the contract between them.

## Why

Skills like the form filler and the Vercel connector must run on the user's own computer: their
saved info and API keys never leave it. Chert calls land on our server, and the user's laptop is
behind their Wi-Fi, so the helper app connects OUT to our relay and asks for jobs; the relay hands
FaceTime-agent requests to it and streams its screen and results back to the call.

## Security rules (all pieces)

- The helper only runs fixed job kinds: `form_fill`, `form_submit`, `vercel_status`,
  `vercel_redeploy`, `connections_list`. Unknown kinds are refused. No shell, no arbitrary code.
- API keys live only in `~/.toolstone/.env` on the user's computer (chmod 600). The helper reads
  them; they are never sent to the relay, never in results, logs, frames or prompts. Results carry
  data (deploy status), never keys. `connections_list` returns key NAMES only (e.g. "vercel").
- Saved personal info lives in `~/.toolstone/profile.json`. Form results return field LABELS and the
  profile KEY used (e.g. "email"), never the values. The values are visible only on the user's
  own screen / FaceTime video.
- `form_submit` and `vercel_redeploy` change things: the agent only sends them after the caller says
  "yes, submit" / "yes, redeploy" right after the agent's read-back (same consent pattern as voice pay).
- One runner per person (phone hash). A runner token is a random secret; only its sha256 is stored.
- Phones never appear in logs.

## Relay API (FastAPI, `api/routes_runner.py`, storage `data/runner_store.py`)

Runner auth header: `Authorization: Runner <runner_token>`. Agent auth: `X-Agent-Key` (as
`api.dogwood._agent_ok`). Person auth: phone sign-in token via `api.session.current_phone(request)`.

| Method + path | Auth | Body / query | Response |
|---|---|---|---|
| POST /runner/pair | person (Bearer) | `{"name": "<≤60, e.g. Vineet's MacBook>"}` | `{"runner_token": "<secret, shown once>", "runner_id": "<12 hex>"}`; replaces any older runner for that person |
| GET /runner/status | person | – | `{"connected": bool, "name", "last_seen": unix\|null}` (connected = seen in the last 60 s) |
| GET /runner/next | runner | `?wait=0..25` (long-poll seconds) | `{"job": null}` or `{"job": {"job_id", "kind", "args"}}`; updates last_seen |
| POST /runner/jobs/{job_id}/frame | runner | raw `image/jpeg` body ≤ 400 KB | `{"ok": true}`; keeps only the latest frame + a sequence number |
| POST /runner/jobs/{job_id}/progress | runner | `{"note": "<≤200>"}` | `{"ok": true}` (keep last 20) |
| POST /runner/jobs/{job_id}/result | runner | `{"status": "done"\|"failed", "result": {...≤16 KB JSON}, "error": "<≤200>"}` | `{"ok": true}` |
| POST /runner/jobs | agent | `{"phone", "kind", "args"}` | `{"job_id"}` · 404 `no_runner` · 409 `runner_offline` (not seen for 60 s) · 400 `bad_kind` |
| GET /runner/jobs/{job_id} | agent | – | `{"job_id", "kind", "status": "queued"\|"running"\|"done"\|"failed", "progress": [...], "result", "error", "frame_seq"}` |
| GET /runner/jobs/{job_id}/frame | agent | – | the latest JPEG (`image/jpeg`), or 204 when none yet |
| GET /demo/forms/permit | none | – | a demo HTML form (see below) |

- A job is `running` once the runner fetched it. Jobs older than 15 min are dropped.
- Storage: in memory is fine for jobs/frames (single uvicorn process); the runner pairing
  (`runner_id`, sha256(token), owner = phone_hash, name, created_at, last_seen) goes to Tiger
  table `runners` with an in-memory fallback.
- Errors: `{"ok": false, "error", "message"}`.

Demo form `GET /demo/forms/permit`: a clean, realistic "City of Atlanta · Residential Parking
Permit Application" page served by the API (inline CSS, no external assets, a strict CSP that
allows its own inline script only if needed). Labeled fields with matching `autocomplete`
attributes: Full name (name), Email (email), Phone (tel), Street address (street-address), City
(address-level2), State (address-level1, select of US states), ZIP (postal-code), License plate,
Vehicle make, Vehicle model, Vehicle color, Permit type (select: Residential / Visitor), a
checkbox "I certify this information is correct", and a Submit button. Submitting shows
"Application received (demo, nothing was sent)" on the page without leaving it; nothing is stored.

## Job kinds (args → result)

- `form_fill` `{"url": "<http(s) url, or empty for the active Chrome tab>", "profile": "default"}` →
  `{"url", "title", "filled": [{"label", "key"}], "missing": ["<label>"], "submit_found": bool}`.
  The helper opens a VISIBLE Chromium window (Playwright) on the user's computer, fills fields from
  the profile by matching `autocomplete`, `name`/`id`, `<label>`, `aria-label` and placeholder, and
  never touches password, card/CVV, SSN or file inputs or the certify checkbox. It keeps the page
  open (up to 10 minutes) for a later `form_submit`. Frames ~3/s while filling.
- `form_submit` `{"fill_job": "<job_id of the form_fill>"}` → `{"submitted": true, "message": "<page text after submit, ≤200>"}`.
  Ticks the certify checkbox only now (the caller agreed), clicks the form's own submit button.
- `vercel_status` `{"project": "<optional name>"}` → `{"projects": [{"name", "framework", "url",
  "latest": {"state", "url", "created": unix, "target", "commit_message", "creator"}}]}` (≤5, newest
  deploys first) using `VERCEL_TOKEN` (and optional `VERCEL_TEAM_ID`) from `~/.toolstone/.env`,
  Vercel REST (`/v9/projects`, `/v6/deployments`).
- `vercel_redeploy` `{"project": "<name>"}` → `{"deployment": {"id", "url", "state"}}`: redeploys
  the project's latest production deployment (`POST /v13/deployments` with `deploymentId` +
  `name` + `target: "production"`).
- `connections_list` `{}` → `{"connections": ["vercel", ...]}` (which supported keys exist).
- Missing key → `failed` with error `missing_connection:vercel` (the agent tells the caller how to
  add it: put `VERCEL_TOKEN=...` in `~/.toolstone/.env`).

## Agent tools (chert/), plugins (plugins/)

- New tool name `computer` in the allowlists (`api/plugins_index.py` TOOLS and `chert/plugins.py`),
  verified-only like money tools.
- Plugins: `form-filler` (tools: speak, screen, computer) and `vercel` (tools: speak, screen,
  computer), verified in `plugins/verified.json`, on by default in `data/plugins_store.STARTER_IDS`.
- Tools (gated by the active plugin listing `computer` and a call-confirmed phone `known_phone`):
  `fill_form(url="")`, `submit_form()` (consent), `vercel_status(project="")`,
  `vercel_redeploy(project)` (consent), `list_connections()`.
- While a job runs, the agent polls `GET /runner/jobs/{id}` and `/frame` (~3/s) and shows frames on
  the FaceTime video (status video live view, header "Your computer · <skill name>").
- No runner → tell the caller how to connect their computer (`python3 runner/toolstone_runner.py pair`).
