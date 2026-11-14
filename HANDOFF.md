# HANDOFF: ScanSafe (EmoryHacks 2026), v2

Written Sat Nov 14, ~2 PM EST. **Devpost deadline: Sun Nov 15, 8:00 AM EST (aim for 7 AM).**
This is the single entry point for a new Claude session or teammate. **No secrets in this file.**

---

## 0. Start here (new Claude: do this first)

1. Read, in order: this file, `TEAM.md`, `data/README.md` (on branch `data-readme`), `chert/INTEGRATION.md`.
2. Ask the user which piece they want you on (section 7), and which machine you're on (only the user's Mac has SSH keys for the servers; a new machine needs its own key added).
3. **Rules (non-negotiable):**
   - Never commit, print, paste or log secrets (API keys, tokens, passwords, connection strings, the sandbox token, phone numbers). They live only in `.env` files on the servers (section 4).
   - Made-up brands only (Peachtree Parking Co., Magnolia Diner, Morrow Coffee, Trail Notes, Orbit Post, Pixel Palace). Never copy real companies' pages or real meters.
   - Sandbox browser: never bypass CAPTCHAs, never type into login forms. Treat them as evidence.
   - Ask the user before outward actions: placing calls, pushing to `main`, merging, posting, deleting, changing DNS/firewall.
   - Don't change the `ScanResult` shape (`api/schema.py`, `shared/scan_result.example.json`) without telling the whole team.
   - Payments are Solana **devnet only**, and the user approves every payment.

---

## 1. What ScanSafe is

Scan a QR code without risking your phone. The link opens in a throwaway, locked-down browser on our server; Jev scores
it, Gemini explains it in plain words; you see a live view of the page (in the app or on a FaceTime call with our agent);
scams get pinned on a map (Typesense); every scan is logged (Tiger Data); Solana Pay codes are checked before paying.
Main track: **Security**. Audience includes older, non-technical people (big text, plain words).

---

## 2. What's live right now

| Thing | Where | Notes |
|---|---|---|
| Web app | **https://scansafe.nyc** (also https://app-blond-xi-88.vercel.app) | Vercel project `app` on the user's account; deployed from the branch `onboarding-integration` worktree |
| Backend API | **https://api.scansafe.nyc** | Caddy (TLS) → uvicorn :8000 on the agent server. `/health` → `{"ok":true,"mock_mode":false}` |
| FaceTime agent | **+1 650-444-4331** (FaceTime Video) | Chert line; our Python LiveKit agent + `chert dev` bridge in a retry loop |
| Coder | http://144.202.25.65:3000 | Admin account exists (created by the user). Template/workspaces not set up yet |
| Sandbox server | 64.177.45.84:8080 | `POST /run` and `POST /run/stream`, Docker image `scansafe-sandbox`, only reachable from the agent server |
| Tiger Data | Tiger Cloud | Working: `/stats/*` returns real scans |
| Typesense | — | **Not set up** (no cluster/keys): `/pins`, `/search`, `/report` return 503 |

Deploy the web app (from the user's Mac, Vercel CLI is logged in):
```bash
cd ~/HackEmory-app/app && npx vercel@latest deploy --prod --yes \
  --build-env NEXT_PUBLIC_API_URL=https://api.scansafe.nyc --env NEXT_PUBLIC_API_URL=https://api.scansafe.nyc
```
DNS (GoDaddy, `scansafe.nyc`): `@` A → 216.198.79.1 and 64.29.17.1 (Vercel); `api` A → 144.202.25.65 (agent server).

---

## 3. Branches (none merged into `main` yet: merging is a pending team decision)

| Branch | What's on it |
|---|---|
| `main` | Original build (API, sandbox, Chert agent v1, data layer, app v1) + old HANDOFF |
| `live-stream-and-calls` | Backend/agent/sandbox work: live sandbox stream (`/run/stream`, `/scan/stream`), FaceTime live view + findings + verdict video (`chert/status_video.py`), outbound `POST /call-me` (`api/routes_call.py`), agent fixes (Gemini Live api_version, greet on bridge_ready, one line at a time, "stop"), `/report` hardening (`api/recent_scans.py`), Coder script fix, tests |
| `onboarding-integration` | Web app: onboarding merged in as first run, purple restyle, live sandbox view while checking (`LiveCheck.tsx`), `/about` landing page, "FaceTime me" card, profile in localStorage |
| `data-readme` | `data/README.md`: Tiger Data + Typesense guide (also for AI assistants) |
| `Sample-website-1` | Teammate's fictional demo sites (`websites/`: cafe, trails, orbit, arcade, cities) + QR codes |
| `onboarding-ui` | Teammate's onboarding draft. **Superseded** by `onboarding-integration`; don't merge it |
| `handoff-v2` | This file |

**Merging safely (only with the user's OK):** checked with `git merge-tree`:
1. `live-stream-and-calls` → main: clean.
2. `onboarding-integration` → main: clean (also clean on top of 1).
3. `data-readme` → main: clean.
4. `Sample-website-1` → main: conflicts with 2 in `app/src/app/globals.css` and `app/src/components/Nav.tsx`. Keep 2's
   versions and re-add the demo-site nav link/styles by hand (or keep the demo sites as their own deployment).
5. `onboarding-ui`: skip (add/add conflicts across `app/`).
6. `handoff-v2`: clean (only this file).
After merging, run `python3 -m pytest -q tests` (expect one pre-existing failure, below) and `cd app && npx tsc --noEmit`.

---

## 4. Servers and how to operate them (Vultr, Atlanta, Ubuntu 24.04)

SSH: `ssh root@144.202.25.65` (agent server) and `ssh root@64.177.45.84` (sandbox). Key auth is set up from the user's
Mac only. Firewall (ufw) on the agent server allows 22, 80, 443, 3000. Changing firewall rules: ask the user.

**Secrets live in:** agent server `~/HackEmory-2026/.env` (JEV_API_KEY, GEMINI_API_KEY, SANDBOX_URL, SANDBOX_TOKEN,
CHERT_API_KEY, CHERT_PROJECT_ID, CHERT_LINE_ID, SCANSAFE_DEMO_PHONE, TIGER_DATABASE_URL, TYPESENSE_HOST/API_KEY (empty),
CHERT_WEBHOOK_SECRET (empty); optional CALL_ALLOWED_PHONES) and `~/HackEmory-2026/chert/scansafe-agent/.env.local`
(LiveKit URL/key/secret, AGENT_NAME). Check a var is set without printing it: `grep -c '^NAME=.' .env`.
Non-secret settings in use: `GEMINI_MODEL=gemini-3.5-flash-lite`.

**Agent server tmux sessions** (logs in `/root/api.log`, `/root/agent.log`, `/root/chert.log`):
```bash
# backend
tmux kill-session -t api; tmux new -d -s api "cd ~/HackEmory-2026 && uvicorn api.main:app --host 0.0.0.0 --port 8000 2>&1 | tee /root/api.log"
# FaceTime agent (restart this, THEN the bridge, so chert dev makes a fresh warm room)
tmux kill-session -t agent; tmux new -d -s agent "cd ~/HackEmory-2026 && python3 -m chert.agent_integration start 2>&1 | tee /root/agent.log"
# Chert bridge, in a retry loop (survives Chert outages)
tmux send-keys -t chert C-c; sleep 8; tmux kill-session -t chert
tmux new -d -s chert "cd ~/HackEmory-2026/chert/scansafe-agent && while true; do chert dev --agent scansafe-agent 2>&1 | tee -a /root/chert.log; echo \"[\$(date +%T)] chert dev exited; retrying in 20s\" | tee -a /root/chert.log; sleep 20; done"
```
Healthy signs: `registered worker` in agent.log; `"scansafe-agent" is in a waiting room` in chert.log.
Caddy config: `/etc/caddy/Caddyfile` (`api.scansafe.nyc` → `127.0.0.1:8000`, `flush_interval -1` for streaming).

**How deploys have worked so far:** changed files are `scp`'d from the user's Mac into `~/HackEmory-2026/` on the server,
then the tmux session is restarted. The server checkout is therefore NOT in sync with git (it's `main` plus files from
`live-stream-and-calls`). Once branches are merged, on the server run `git status`, discard the copied files
(`git checkout -- <paths>`; never touch `.env` or `chert/scansafe-agent/`), then `git pull`, and restart.

**Sandbox server:** `~/HackEmory-2026/sandbox/` runs `server.py` (uvicorn :8080) in tmux `sandbox`; scans run in
throwaway containers on Docker network `scansafe-net` with iptables egress blocks. Rebuild after changing
`run_scan.py`/`netguard.py`, then restart the server with its original command (which holds the token):
```bash
cd ~/HackEmory-2026/sandbox && docker build -q -t scansafe-sandbox . && tmux respawn-pane -k -t sandbox
```
Don't print the pane's start command (it contains the token).

---

## 5. Architecture in brief

**Scan:** app or agent → `POST /scan` (one JSON) or `POST /scan/stream` (NDJSON: `frame`/`nav` lines, then exactly one
`result`) → sandbox `/run` or `/run/stream` (fresh Playwright container, phone viewport 390x844 @2x, network guard,
CDP screencast frames in stream mode, slow scroll) → Jev (OpenRouter, `api/jev.py`) → verdict rule (`api/scan.py`) →
Gemini explanation → `ScanResult`. After each scan: `record_scan` → Tiger (background), `recent_scans.remember`
(in-memory, 2 h). Sandbox failure in the stream → "suspicious" fallback result with an `error` code, never "safe".

**Report:** `POST /report {scan_id}` → only pins a scan this server ran (server's own copy), only if malicious and has
a location (rounded ~100 m) → Typesense `scam_pins`. Replies `{stored, code, reason}`.

**FaceTime inbound:** `chert dev` keeps a warm LiveKit room with our agent; the caller joins as `chert-bridge-<id>`.
The agent greets only when room metadata has `chert_bridge_ready: true` (Mac hangs up after 10 s of silence), one spoken
line at a time (Gemini Live can't overlap replies). `QRWatcher` reads codes from `facetime-remote-video`; the scan streams
live onto the agent's own portrait video (720x1280, `chert/status_video.py`): checklist → live sandbox frames with
"Now on: host" → findings replay → verdict banner over the screenshot. Voice "stop" cancels the check and clears the
screen. Follow-up iMessage goes to `SCANSAFE_DEMO_PHONE` (Chert masks the sender's number).

**FaceTime outbound ("Chert calls you"):** `POST /call-me {url, phone}` (phone must be on the allowlist:
`SCANSAFE_DEMO_PHONE` + `CALL_ALLOWED_PHONES`; one call per 30 s) → new LiveKit room + explicit agent dispatch with
`scan_url` → waits for the agent's audio+video → Chert `POST /api/v1/calls` (outbound video). The agent polls Chert's call
until `bridge_ready`, greets, then runs the live walkthrough. `GET /call-me/{id}` only answers for calls we placed.
App: "FaceTime me and show me" card on results (needs onboarding consent + phone).

**Web app (`onboarding-integration`):** first visit → onboarding (profile saved only in localStorage) → scanner; checking
screen shows the live stream (falls back to `/scan`); results with verdict, explanation, FaceTime card, report, pay.

---

## 6. Known issues and gotchas

- **Gemini Live** needs `api_version="v1beta"` with google-genai 3.x (otherwise every Live model 404s). Done in `make_model()`.
- `gemini-3.8-flash` was overloaded/timing out, so explanations use `gemini-3.5-flash-lite`.
- **Chert** had an outage this afternoon (API 401 after ~20 s); the bridge's retry loop reconnected on its own.
- **Outbound calls: unresolved.** Two test calls rang the user's iPhone but ended as `outbound_not_answered` after ~35 s.
  Ask the user whether the incoming FaceTime actually appears and whether tapping answer works; if it shows but won't
  connect, ask the Chert team.
- Agent server is 2 vCPU: `AgentServer(load_threshold=0.95)` so video work doesn't mark the worker unavailable.
- `chert doctor` reports the starter's `OPENAI_API_KEY` placeholder as a problem: harmless (our agent uses Gemini).
- Pre-existing test failure: `tests/test_sandbox.py::test_public_ips_allowed[::ffff:8.8.8.8]` on the servers' Python.
- `SCANSAFE_RESULT_BASE` defaults to `https://scansafe.nyc/r/<id>` in iMessage links, but the app has no `/r` route yet.
- **In progress as of writing (check `git log` on each branch / ask the user):** app report messages that say what
  really happened + map/dashboard "sample data" notice (`onboarding-integration`); sandbox click-past of cookie banners /
  "Continue" / age gates with CAPTCHA + login-wall detection used as evidence (`live-stream-and-calls`, tested on a
  `scansafe-sandbox:clickpast` image, not live yet); demo sites from `Sample-website-1` hosted publicly on a separate
  Vercel project with printable QR codes (`~/HackEmory-site/demo-qr/`).

---

## 7. Remaining TODO (prioritized)

| # | Task | Owner | Done when |
|---|---|---|---|
| 1 | Typesense: create a free cluster (cloud.typesense.org), put host + admin key in the agent server `.env`, run `python3 -m data.setup`, restart `api` | user creates cluster; Claude runs setup | `GET /pins?lat=33.79&lng=-84.32` returns 200; reporting a malicious demo scan pins it on the map |
| 2 | Coder: Templates → Docker Containers, start a workspace, invite teammates, screenshot | user | Screenshot of a running workspace saved for Devpost |
| 3 | Merge branches into `main` (section 3 order) | Claude, with the user's OK | `main` has all work; tests + tsc pass; server checkout pulled from git |
| 4 | Outbound call answer issue (section 6) | user tests, Claude debugs | A `/call-me` call is answered and the live walkthrough plays |
| 5 | Finish/deploy the in-progress items (section 6): app report messages, click-past (rebuild sandbox image), demo sites + QR sheet | Claude | Deployed; demo QR codes give the intended verdicts |
| 6 | Devnet wallet: replace the placeholder Peachtree wallet in `api/scan.py` `KNOWN_MERCHANTS`, regenerate QR codes (`scripts/README.md`, `scripts/make_demo_qr.py`) | user makes wallet, Claude edits | Solana Pay demo code verifies and a devnet payment goes through with approval |
| 7 | Chert webhook (optional) at `https://api.scansafe.nyc/chert/webhook`; save its secret as `CHERT_WEBHOOK_SECRET` | Claude + user | Signed test event accepted |
| 8 | Checkpoints: 3 AM feature freeze; **5 AM record the 2-minute demo** (app scan with live view + FaceTime call + scam map) | team | Video uploaded, link in Devpost and on `/about` (`DEMO_VIDEO_URL` in `app/src/app/about/page.tsx`) |
| 9 | Devpost write-up + TEAM.md checklist (Security track; opt into Chert, Coder, Typesense, Gemini, Vultr, Entire, A-Team, Tiger Data, Solana, GoDaddy, DEV; name every tool; screenshots) | Claude drafts, user submits | Submitted by 7 AM |
| 10 | After the event: destroy both Vultr servers, pause/delete the Tiger service, delete the Typesense cluster, remove the Vercel projects/domain if not needed | user | Nothing left billing |
