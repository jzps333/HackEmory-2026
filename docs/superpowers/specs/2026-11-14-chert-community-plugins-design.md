# Chert Community Plugins: design

Date: 2026-11-14 (EmoryHacks 2026). Feature freeze 3:00 AM EST, demo recording 5:00 AM, Devpost 7:00 AM.

## Intent

Pivot the ScanSafe pitch into **community plugins for Chert**: open, shareable skills that run on a
Chert FaceTime agent. Anyone can contribute a plugin through GitHub; plugins stay **unverified**
until an admin (our team) verifies them. ScanSafe's QR checker is the first plugin, and every
sponsor track we opted into becomes a plugin or a piece of the hub. The main selling point is
open-sourcing and sharing skills. The plugins must actually work on a real Chert FaceTime call.

The Chert founding engineer has said yes to us cloning the Chert dashboard look for this.

## Goals

1. A **clone of the Chert dashboard** (the console at facetime.trychert.com: sidebar with Overview,
   Lines, Calls, Messages, Agents, Developer, Billing, Members and settings, Quickstart and docs)
   with a new **Community plugins** item directly under "Quickstart and docs".
   Only Community plugins works. Every other item is a static look-alike page or does nothing.
2. **Plugins live in this repo** under `plugins/` (jzps333/HackEmory-2026 is public). Each plugin is
   a folder with `plugin.yaml` and `README.md`. Contributions are pull requests to that folder.
3. **Verified vs unverified**: `plugins/verified.json` lists approved plugin ids with the git commit
   they were approved at. Only admins may change it (`.github/CODEOWNERS`). Anything not listed, or
   changed since approval, shows and runs as unverified.
4. The **FaceTime agent loads plugins**: a person turns plugins on in the Community plugins page and
   the next Chert call uses them. Starter plugins that work live by 3 AM: QR checker, safe browser,
   Solana pay, parking, squat coach (cues only; see constraints), plugin finder.
5. Sponsor tracks shown on the page: Typesense search over plugins, install counts in Tiger Data,
   "Open in Coder" for writing a plugin, Vultr for the locked-down VM, Gemini for the agent and the
   plugin review, Solana for payments.

## Non-goals

- Any other dashboard page working (Lines, Calls, Billing, ...). They are static.
- Real Chert sign-in, or reading the user's real Chert project. The clone shows demo data.
- A new GitHub repo. A GoDaddy domain or the GoDaddy track.
- The app that runs plugins on a person's own computer (pitch only).
- Building whole products from one text (pitch or stretch, not tonight's demo backbone).

## Anti-goals (a failure even if it works)

- The clone could pass for the real Chert console: it must carry a visible footer note
  ("Community plugins demo for EmoryHacks 2026, built with Chert's permission. Not the official
  Chert console."), must not offer a Chert sign-in form, and must not live on a Chert-like domain.
- Real personal data in the clone (the user's email, name or real call log). Use "ScanSafe demo".
- An unverified plugin getting payments, parking-operator access or anything personal.
- Plugin text being run as code. A plugin is data: instructions plus a list of allowed tools.
- Secrets in the repo or in plugin files.

## Constraints

- About 5 to 6 hours of work time. Two-vCPU agent server; Gemini Live sees about 1 frame/second.
- The teammate owns the phone UI in `app/`. This work must not edit `app/`.
- Existing infra stays as is: agent (`chert/agent_integration.py`), API (`api/`, api.scansafe.nyc),
  sandbox VM (Vultr), voice-confirmed payments, ParkMobile/Dogwood adapters, Typesense, Tiger.

## Approaches considered

Site:
1. **Dashboard clone where only Community plugins works (picked by the user).** Matches what a Chert
   developer actually sees; small surface; nearly all time goes into working plugins.
2. Rebuild the marketing site plus a plugins tab: more copying, goes stale, not what was asked.
3. Mirror Chert's compiled site files and inject a tab: brittle and hard to edit.

Plugin storage:
1. **`plugins/` folder in this public repo (picked; a new repo is not allowed).** Real open-source
   mechanics: pull requests, history, credit, CODEOWNERS for verification.
2. Our own database only: no open-source story.

## Design

### Plugin format (`plugins/<id>/plugin.yaml`)

```yaml
id: squat-coach                 # folder name, a-z0-9-
name: Squat coach
summary: Watches your squats on FaceTime and calls out form cues.
author: github-handle
version: 1
kind: live                      # runs on the FaceTime call
runs_on: server                 # server | vm   (vm = locked-down sandbox)
triggers:
  phrases: ["coach my squats", "squat coach"]
  qr: false                     # true: a QR code on camera starts it
tools: [camera, speak, screen, memory]   # must be from the allowlist below
permissions: >                  # read aloud before the first run
  This plugin watches your camera and saves your rep counts.
instructions: >                 # what the agent does while this plugin is active (plain text)
  Watch the person squat. After each rep give one short cue ...
```

Tool allowlist (the only capabilities a plugin can ask for):

| Tool | What it does | Unverified may use |
|---|---|---|
| `camera` | the agent sees the caller's video | yes |
| `speak` | talks on the call | yes |
| `screen` | shows text/cards on the video we send back | yes |
| `memory` | saves small per-person records (Tiger) | yes |
| `safe_browser` | opens a link in the locked-down VM, live on the call | yes |
| `scam_check` | ScanSafe verdict for a link | yes |
| `plugin_search` | finds plugins by voice (Typesense) | yes |
| `solana_pay` | voice-confirmed devnet payment | **no** |
| `parking` | operates Dogwood/ParkMobile up to the pay step | **no** |

A plugin's `instructions` are passed to the agent as text, never executed. Tools are wired from our
own code by name; a name not in the allowlist is rejected at load and in review.

### Verification

- `plugins/verified.json`: `{"<id>": {"sha256": "<hash of plugin.yaml + README.md>", "by": "<admin>"}}`.
- `.github/CODEOWNERS`: `plugins/verified.json @jzps333` (plus teammates the user names).
- A plugin is verified only when its current files hash to the listed value.
- Review on pull requests (GitHub Action): validate `plugin.yaml` against the schema and allowlist,
  then post an AI review comment (Gemini) with a safety score and reasons. The Gemini key is a repo
  secret the user adds; without it the Action runs only the schema check.

### Backend (FastAPI, `api/routes_plugins.py`)

- `GET /plugins`: plugin index (read from the deployed repo's `plugins/` folder on the API server,
  refreshed by `git pull` at deploy), each with `verified`, `install_count`, `runs_on`, `tools`.
- `GET /plugins/{id}`: full plugin plus README text.
- `GET /plugins/search?q=`: Typesense collection `plugins` (indexed at startup / on refresh).
- `POST /plugins/{id}/enable`, `/disable`: which plugins the demo agent uses. For the hackathon the
  set is global for the demo project (no Chert auth in the clone); a signed-in ScanSafe phone gets
  its own set when one exists. Install counts in Tiger (`plugin_installs`).

### Agent (`chert/plugins.py`, wired into `chert/agent_integration.py`)

- At call start, load enabled plugins from the API. Compose the agent instructions: base
  instructions + a short list of available plugins + the active plugin's `instructions`.
- Tool `use_plugin(name)` switches the active plugin when the caller asks ("coach my squats").
- Tools are exposed per active plugin from its `tools` list; unverified plugins never get
  `solana_pay` or `parking`.
- Before a plugin's first run on a call, the agent reads its `permissions` aloud.
- Existing flows become plugins without rewriting them: QR checker = the current QR flow;
  safe browser = `check_now` on a spoken or texted link; parking = meter/ParkMobile flows;
  Solana pay = voice pay.
- Squat coach: Gemini Live watches the video and gives cues; the video shows a "Squat coach" card
  with the latest cue. A rep counter from body tracking is a stretch goal.

### Dashboard clone (`community/`, a separate Next.js app and Vercel project)

- Visual match to the screenshot: light sidebar, serif page titles, Inter body, mono numbers,
  rounded white cards, blue links. Sidebar items as in Chert plus **Community plugins** under
  "Quickstart and docs".
- Overview: static demo cards ("ScanSafe demo" project, demo line and activity).
- Other items: a simple static page or no-op.
- Community plugins: search box (Typesense via the API), filter All / Verified / Unverified, plugin
  cards (name, summary, author, badge, install count, where it runs), a detail panel (permissions,
  tools, README, recipe), an **Enable for my agent** toggle, **Submit a plugin** (opens the GitHub
  new-file / PR page for `plugins/`), **Open in Coder**.
- Footer note per the anti-goals. Deployed to its own `*.vercel.app` address.

### Tracks (opted in, GoDaddy dropped)

Security (main): QR checker + verification + unverified plugins locked down. Chert: the hub and
plugins on Chert calls. Vultr: the locked-down VM plugin. MLH Gemini: the agent, squat coach, AI
review. Typesense: plugin search. Tiger Data: install counts and plugin memory. Solana: pay plugin.
Coder for Good: Open in Coder. Entire, A-Team, DEV: requirements unknown (A-Team is a raffle opt-in).

## Calls made after the builder check (correct any of these)

1. **No mid-call tool swapping.** At call start the agent loads the enabled plugins once and
   registers the tools any of them needs (unverified plugins never contribute `solana_pay` or
   `parking`). `use_plugin(name)` only changes the active plugin's instructions
   (`Agent.update_instructions`, livekit-agents 1.8); each tool also checks that the active plugin
   lists it and politely refuses otherwise. No session restarts.
2. **Parking and Solana pay keep their existing entry points.** They start the way they do today
   (scanning a parking code in the app, which places the outbound call). Enabling the plugin
   switches them on for that agent; an inbound "pay my meter" voice request is not added tonight.
3. **One demo enabled-set**, shared by every caller of the demo line (judges included). The agent
   reads it at call start from `GET https://api.scansafe.nyc/plugins/enabled` with the existing
   `X-Agent-Key`. A per-phone set is left for later.
4. **Plugin files on the servers**: the agent/API server deploys by `git pull` of this repo (no
   containers), so it reads `plugins/` from its checkout. The dashboard reads plugins from the API.
5. **Verification uses a content hash, not a commit**: `verified.json` stores
   `sha256(plugin.yaml + README.md)`. It works without git history and catches any edit after
   approval.

## Left to the builder

Exact styling details of the clone, the Coder workspace template, Typesense collection fields, the
JSON schema file, how the demo enabled-set is stored, and the squat coach's prompt wording.

## Open items for the user

- GitHub admins for CODEOWNERS besides @jzps333.
- Whether to add the Gemini key as a GitHub Actions secret for the AI review (else schema check only).
- The Coder deployment URL / template for "Open in Coder" (else the button links to a placeholder).
- What the Entire and DEV tracks require.
