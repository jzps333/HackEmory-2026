# Chert Community Plugins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Community plugins for Chert that are listed on a Chert-dashboard clone, stored as files in this repo's `plugins/` folder, verified by admins, and actually used by the FaceTime agent on live calls.

**Architecture:** Plugins are data (`plugin.yaml` + `README.md`) parsed and validated by one Python module (`api/plugins_index.py`). The FastAPI app serves the index, search (Typesense), install counts (Tiger) and the demo enabled-set. The agent fetches the enabled set at call start and exposes `use_plugin` plus per-plugin tools. A separate Next.js app (`community/`) clones the Chert console look and makes only the Community plugins section work.

**Tech Stack:** Python 3.12, FastAPI, PyYAML (`yaml.safe_load`), httpx, livekit-agents 1.8.12 (`Agent.update_instructions`), Typesense (httpx, existing `data/typesense_store._client`), Tiger/Postgres (psycopg, `TIGER_DATABASE_URL`), Next.js 16 + React 19, Vercel.

**Spec:** `docs/superpowers/specs/2026-11-14-chert-community-plugins-design.md`

## Global Constraints

- Feature freeze 3:00 AM EST. Every task keeps the full suite green: `/tmp/ssvenv/bin/python -m pytest -q tests` (count must not drop; 0 failed).
- Do not edit anything under `app/` (teammate's phone UI).
- Plugin text is never executed; tools are wired by name from our code only.
- Tool allowlist, exactly: `camera, speak, screen, memory, safe_browser, scam_check, plugin_search, solana_pay, parking`. Unverified plugins never get `solana_pay` or `parking`.
- Plugin id: `^[a-z0-9][a-z0-9-]{1,39}$`, equal to its folder name.
- Verified = `plugins/verified.json[id].sha256 == sha256(plugin.yaml bytes + b"\n" + README.md bytes)`.
- Clone footer copy (exact): "Community plugins demo for EmoryHacks 2026, built with Chert's permission. Not the official Chert console."
- No real personal data in the clone: project name "ScanSafe demo", no real email/phone/call log.
- No new GitHub repo, no GoDaddy. The dashboard deploys to its own `*.vercel.app` project.
- Never print or commit secrets (Gemini, Typesense, Tiger, AGENT_INTERNAL_KEY).

## Review Focus

1. A malformed `plugin.yaml` (bad YAML, unknown tool, id ≠ folder) is skipped with a reason; `/plugins` still answers and the agent never loads it. (Task 1 test `test_bad_plugins_are_skipped_with_reasons`, Task 2 test `test_plugins_endpoint_survives_a_broken_plugin`.)
2. An unverified plugin listing `solana_pay`/`parking` gets those tools stripped everywhere. (Task 1 `test_unverified_plugins_lose_money_tools`, Task 3 `test_unverified_plugin_never_exposes_payment_tools`.)
3. The API is unreachable when a call starts: the agent behaves exactly as today (QR flow, parking, voice pay). (Task 3 `test_no_plugins_when_api_down_keeps_todays_agent`.)
4. README/summary containing HTML or `<script>` renders as text on the dashboard. (Task 4 check: no `dangerouslySetInnerHTML` anywhere in `community/`.)
5. A verified plugin edited after approval shows and runs as unverified. (Task 1 `test_edit_after_approval_is_unverified`.)

---

### Task 1: Plugin format, index module, starter plugins, verification, PR check

**Files:**
- Create: `api/plugins_index.py`
- Create: `plugins/README.md` (how to write and submit a plugin; the format; verified vs unverified)
- Create: `plugins/{qr-checker,safe-browser,solana-pay,parking,squat-coach,plugin-finder}/plugin.yaml` and `README.md`
- Create: `plugins/verified.json`, `.github/CODEOWNERS`, `.github/workflows/plugins-check.yml`, `plugins/review.py`
- Modify: `requirements.txt` (add `PyYAML>=6`)
- Test: `tests/test_plugins_index.py`

**Interfaces:**
- Produces (in `api/plugins_index.py`):
  - `TOOLS: frozenset[str]` (the allowlist), `MONEY_TOOLS = frozenset({"solana_pay", "parking"})`
  - `@dataclass Plugin: id, name, summary, author, version: int, kind: str, runs_on: str ("server"|"vm"), phrases: list[str], qr: bool, tools: list[str], permissions: str, instructions: str, readme: str, sha256: str, verified: bool`
  - `def content_hash(folder: Path) -> str`
  - `def validate(data: dict, folder_name: str) -> list[str]` (error strings; empty = valid)
  - `def load_plugins(root: Path) -> tuple[list[Plugin], dict[str, str]]` (valid plugins sorted by id; `{folder: reason}` for skipped)
  - `def effective_tools(p: Plugin) -> list[str]` (drops `MONEY_TOOLS` when not verified)
  - `def to_public(p: Plugin, installs: int = 0) -> dict` (JSON for API; includes `effective_tools`, omits nothing secret)
  - `PLUGINS_DIR = Path(os.getenv("PLUGINS_DIR") or <repo>/plugins)`
  - CLI: `python -m api.plugins_index --check` (exit 1 on any invalid plugin), `--hash <id>` (print hash)

- [ ] **Step 1: Write the failing tests** in `tests/test_plugins_index.py` using `tmp_path` plugin folders:
  - `test_valid_plugin_loads_with_fields` — loads `squat-coach` style yaml; asserts `p.tools == ["camera","speak","screen","memory"]`, `p.kind == "live"`.
  - `test_bad_plugins_are_skipped_with_reasons` — folders with invalid YAML, tool `"shell"`, id ≠ folder → all three in `skipped`, none in plugins.
  - `test_verified_needs_matching_hash` / `test_edit_after_approval_is_unverified` — write verified.json with `content_hash`; edit README → `verified is False`.
  - `test_unverified_plugins_lose_money_tools` — unverified plugin with `solana_pay` → `effective_tools` lacks it; verified keeps it.
  - `test_repo_plugins_are_all_valid_and_verified` — `load_plugins(PLUGINS_DIR)` has the six starter ids, no skipped, all verified.
- [ ] **Step 2: Run** `/tmp/ssvenv/bin/python -m pytest -q tests/test_plugins_index.py` → FAIL (module missing). (Install PyYAML into `/tmp/ssvenv` first: `/tmp/ssvenv/bin/pip install -q 'PyYAML>=6'`.)
- [ ] **Step 3: Implement `api/plugins_index.py`** with `yaml.safe_load`; caps: name ≤ 60, summary ≤ 200, permissions ≤ 300, instructions ≤ 2000 chars, ≤ 8 phrases.
- [ ] **Step 4: Write the six starter plugins.** `instructions` describe behaviour in plain words; tools: qr-checker `[camera, speak, screen, scam_check, safe_browser]`, qr:true; safe-browser `[speak, screen, safe_browser]`, runs_on vm; solana-pay `[speak, screen, solana_pay]`; parking `[speak, screen, safe_browser, parking]`, runs_on vm; squat-coach `[camera, speak, screen, memory]`; plugin-finder `[speak, plugin_search]`. Squat coach instructions: watch the person, give one short cue per rep (depth, knees out, chest up, slow down), call `coach_cue` with the cue so it shows on screen, never claim precise rep counts. Author: `scansafe-team`.
- [ ] **Step 5: Generate `plugins/verified.json`** with `python -m api.plugins_index --hash <id>` for each, `"by": "jzps333"`. `.github/CODEOWNERS`: `/plugins/verified.json @jzps333` and `/.github/ @jzps333`.
- [ ] **Step 6: `.github/workflows/plugins-check.yml`** on `pull_request` paths `plugins/**`: setup Python 3.12, `pip install PyYAML httpx`, run `python -m api.plugins_index --check`; then, only if `secrets.GEMINI_API_KEY` is set, run `python plugins/review.py` which sends each changed plugin's yaml+README to Gemini (`gemini-2.5-flash`, REST via httpx) asking for a 0–100 safety score + 3 reasons, and posts one PR comment via `gh pr comment` with `GITHUB_TOKEN`. Permissions: `contents: read`, `pull-requests: write`.
- [ ] **Step 7: Run** the new tests and the full suite → PASS. **Commit:** `git add api/plugins_index.py plugins .github requirements.txt tests/test_plugins_index.py && git commit -m "Plugins: format, index, six starter plugins, verified list, PR check"`

### Task 2: Plugins API (index, search, enabled set, installs)

**Files:**
- Create: `api/routes_plugins.py`, `data/plugins_store.py`
- Modify: `api/main.py` (include router), `api/session.py` (no code change needed if `CORS_EXTRA_ORIGINS` is used; document it)
- Test: `tests/test_plugins_api.py`

**Interfaces:**
- Consumes: Task 1 `load_plugins`, `to_public`, `PLUGINS_DIR`.
- Produces (HTTP, all JSON):
  - `GET /plugins` → `{"plugins": [to_public...], "skipped": {folder: reason}, "enabled": [ids]}`
  - `GET /plugins/{id}` → `to_public(p)` + `"readme"`; 404 unknown
  - `GET /plugins/search?q=` → `{"plugins": [...]}` (Typesense collection `plugins`; substring fallback over name/summary/phrases when Typesense isn't configured or errors)
  - `GET /plugins/enabled` → `{"plugins": [to_public of enabled, with "instructions", "permissions", "phrases", "qr"]}` (what the agent reads)
  - `POST /plugins/{id}/enable` and `/disable` → `{"enabled": [ids]}`; 404 unknown
- Produces (in `data/plugins_store.py`): `get_enabled() -> list[str]`, `set_enabled(ids: list[str]) -> None` (JSON file at `PLUGINS_STATE_FILE`, default `~/.scansafe-plugins/enabled.json`, atomic write, default set = all six starter ids), `record_install(plugin_id: str) -> None`, `install_counts() -> dict[str,int]` (Tiger table `plugin_installs(plugin_id text, at timestamptz default now())` when `TIGER_DATABASE_URL` is set, else in-memory; never raises).

- [ ] **Step 1: Write failing tests** (TestClient, `PLUGINS_DIR` and `PLUGINS_STATE_FILE` monkeypatched to tmp):
  - `test_list_shows_verified_and_enabled`, `test_detail_and_404`, `test_enable_disable_round_trip_and_counts`,
  - `test_search_falls_back_without_typesense` (`q=squat` → squat-coach first),
  - `test_plugins_endpoint_survives_a_broken_plugin` (one broken folder → 200, listed in `skipped`),
  - `test_enabled_feed_has_agent_fields` (instructions/permissions present; unverified money tools absent from `effective_tools`).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** router + store; Typesense index built lazily on first search (`ensure` collection with fields id, name, summary, author, phrases[], verified bool) using `data.typesense_store._client`. Load plugins per request (folder is small) so a `git pull` shows up without restart.
- [ ] **Step 4: Run** new tests + full suite → PASS. **Commit:** `git commit -m "Plugins API: list, detail, search, enabled set, install counts"`

### Task 3: Agent loads plugins; use_plugin; squat coach card

**Files:**
- Create: `chert/plugins.py`
- Modify: `chert/agent_integration.py` (ScanSafeAgent tools + call setup), `chert/status_video.py` (card screen)
- Test: `tests/test_agent_plugins.py`

**Interfaces:**
- Consumes: Task 2 `GET /plugins/enabled` via `voice_pay.api_url()` (same base the agent already uses) with header `X-Agent-Key`.
- Produces (in `chert/plugins.py`):
  - `async def fetch_enabled(timeout: float = 3.0) -> list[dict]` (returns `[]` on any error)
  - `class PluginSession: __init__(plugins: list[dict]); active: Optional[dict]; find(name: str) -> Optional[dict]` (matches id, name or any phrase, case-insensitive); `allows(tool: str) -> bool` (True when no plugins are loaded, i.e. today's behaviour; else the active plugin's `effective_tools` contains it); `menu() -> str` (one line per enabled plugin for the instructions); `first_run(plugin_id) -> bool`
  - `def instructions_for(base: str, session: PluginSession) -> str`
- Produces (in `chert/status_video.py`): `StatusVideo.set_card(title: str, body: str) -> None` (state `"card"`, big title + wrapped body, uses `_clip`; part of `_frame_key`), cleared by `reset()`.
- Produces (agent tools on `ScanSafeAgent`): `use_plugin(name: str) -> str`, `coach_cue(text: str) -> str` (needs `screen`), `find_plugin(query: str) -> str` (needs `plugin_search`; calls `GET /plugins/search`).

- [ ] **Step 1: Write failing tests:**
  - `test_no_plugins_when_api_down_keeps_todays_agent` — `fetch_enabled` with a failing transport → `[]`; `PluginSession([]).allows("scam_check") is True`.
  - `test_use_plugin_switches_and_reads_permissions_once` — fake session/call: `use_plugin("coach my squats")` returns text containing the plugin's permissions the first time, not the second; `update_instructions` called with text containing the squat coach instructions; `video.set_card` called with "Squat coach".
  - `test_unverified_plugin_never_exposes_payment_tools` — plugin dict with `verified: False`, tools incl. `solana_pay` (and `effective_tools` without it) → `allows("solana_pay") is False`.
  - `test_coach_cue_needs_screen_and_clips` — 500-char cue → card body ≤ 120 chars; refused when active plugin lacks `screen`.
  - `test_card_screen_renders` — `set_card` then `_render` returns W*H*4 bytes and `_frame_key` changes with body.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** In the call entrypoint, before `AgentSession.start`, `plugins = await fetch_enabled()`, store `call.plugins = PluginSession(plugins)`, and append `session.menu()` to the agent instructions when non-empty ("You also have these community plugins; when the caller asks for one, call use_plugin."). `use_plugin` calls `await self.update_instructions(instructions_for(base, session))`. Existing tools (`check_qr_code`, payment tools) keep working when `allows()` is True; when a plugin is active that doesn't list the tool, return a short refusal line. Meter/ParkMobile entry points are unchanged.
- [ ] **Step 4: Run** new tests + full suite → PASS. **Commit:** `git commit -m "Agent: community plugins (use_plugin, coach_cue, find_plugin, card screen)"`

### Task 4: Chert dashboard clone with working Community plugins

**Files:**
- Create: `community/` (Next.js 16 app router, TypeScript, plain CSS modules; no Tailwind needed): `package.json`, `next.config.ts`, `app/layout.tsx` (sidebar shell + footer note), `app/page.tsx` (redirect to `/overview`), `app/overview/page.tsx` (static demo cards), `app/[section]/page.tsx` (static placeholder for Lines, Calls, Messages, Agents, Developer, Billing, Members and settings, Quickstart and docs), `app/plugins/page.tsx` (list, search, filter, enable toggle), `app/plugins/[id]/page.tsx` (detail), `lib/api.ts`, `.env.example` (`NEXT_PUBLIC_API_URL=https://api.scansafe.nyc`)

**Interfaces:**
- Consumes: Task 2 HTTP endpoints (no credentials needed).
- Produces: a deployable app; Vercel project root `community`.

- [ ] **Step 1: Scaffold** with `npx create-next-app@16 community --ts --app --no-tailwind --eslint --use-npm --no-src-dir --import-alias "@/*"`.
- [ ] **Step 2: Shell matching the screenshot:** left sidebar ~276px, light grey `#f4f4f3`, Chert wordmark (text + simple orange/blue mark drawn in CSS, not their image file), project switcher "ScanSafe demo · Free trial", nav items with outline icons in order: Overview, Lines (1), Calls, Messages, Agents, Developer, Billing, Members and settings, Quickstart and docs, **Community plugins**; account box "Demo account". Page titles in a serif (Google Fonts "Source Serif 4"), body Inter, numbers in a mono ("IBM Plex Mono"); white rounded cards with 1px `#e7e7e5` borders; links `#1d4f91`. Footer note text exactly as in Global Constraints.
- [ ] **Step 3: Community plugins page:** header "Community plugins" + subtitle "Open-source skills for your Chert agent. Unverified until an admin verifies them."; search box (debounced 250 ms → `/plugins/search`); filter pills All / Verified / Unverified; cards (name, summary, author, badge Verified/Unverified, "Runs on server" or "Runs in locked-down VM", install count, Enable/Enabled toggle → POST enable/disable, optimistic with rollback on error); buttons **Submit a plugin** → `https://github.com/jzps333/HackEmory-2026/new/main/plugins` and **Open in Coder** → `process.env.NEXT_PUBLIC_CODER_URL || "https://coder.com"`.
- [ ] **Step 4: Detail page:** permissions (quoted), tools as chips (unverified money tools shown struck through with "needs verification"), README as plain text in a `<pre>`-like block with wrapping, the raw `plugin.yaml` fields. All page-derived text rendered as React text.
- [ ] **Step 5: Verify:** `cd community && npm run build` succeeds; `grep -R "dangerouslySetInnerHTML" community/app community/lib` returns nothing; run `npm run dev` and screenshot `/plugins` at 1280px and 390px.
- [ ] **Step 6: Commit:** `git add community && git commit -m "Community: Chert dashboard clone with working Community plugins"`

### Task 5: Merge, deploy, live check

- [ ] Merge `community-plugins` into `main` (full suite green), push.
- [ ] Agent/API server: `git pull`, `pip install 'PyYAML>=6'` (system python used by the services), add the Vercel URL to `CORS_EXTRA_ORIGINS` in `.env`, restart `scansafe-api` and (no live call) `scansafe-agent`. Check `curl https://api.scansafe.nyc/plugins` lists six verified plugins.
- [ ] Vercel: new project `chert-community`, root `community`, env `NEXT_PUBLIC_API_URL`; deploy; open `/plugins` and toggle squat-coach.
- [ ] Live: call the demo line, say "coach my squats" → agent reads permissions once, card shows cues; hold up a QR → ScanSafe flow unchanged.
