# ScanSafe Factory

**Tell your Chert assistant what you want it to do. Build a reusable capability, try it, and share a version others can install.**

ScanSafe's QR checker is now the first capability produced by a small skill factory. The same catalog also builds a workout-summary capability. The remote browser, AI checks and Chert connection are reusable infrastructure; parking purchases, financial dashboards and the old standalone product are archived.

## What this commit implements

- Build private capability manifests from plain-English requests using two tested templates: QR/link investigation and workout summaries.
- Run registered tools with validated inputs. QR checking reuses the isolated browser + Jev + Gemini pipeline; workout summaries calculate duration and lifting volume locally.
- Publish immutable releases to a shared catalog and download a ZIP containing `SKILL.md` and `manifest.json`.
- Install a specific published version. New releases do not silently update existing installations.
- Suggest improvements; authors review suggestions and accept them through a new private revision with an optimistic version check.
- Web workspace with build, test, publish, install and contribution flows.
- Signed Chert inbound-message adapter using the same durable catalog, plus an opt-in provider reply adapter.
- LiveKit voice-agent tools for building, browsing, installing, running and publishing these capabilities during an inbound Chert call.

This is a constrained factory, not a general code generator. Requests choose from registered templates; model-written or contributor-written text is never executed. Revised instructions change the assistant guidance, not the registered runner's Python behavior. Adding a new runner requires an ordinary reviewed code change and tests.

## Try it locally

Python 3.11+ and Node 20.9+:

```bash
cp .env.example .env
python -m pip install -r requirements.txt
uvicorn api.main:app --reload
```

In another terminal:

```bash
cd app
npm ci
npm run dev
```

Open http://localhost:3000. Request **"Analyze my workouts"**, run the example input, then publish it. A different browser workspace can install the published release and run it. Suggestions appear in the author's review panel; edit the instructions and accept a suggestion to create version 2.

The frontend proxies `/api/factory/*` to the server-only `FACTORY_API_URL` (default `http://127.0.0.1:8000`). No provider keys go to the browser. Mount the Python API separately for Chert webhooks.

### QR capability

Set `SANDBOX_URL`, `SANDBOX_TOKEN` and `JEV_API_KEY` on the backend. `GEMINI_API_KEY` is optional for explanations and second opinions. The existing worker runs on a separate host; see [sandbox/README.md](sandbox/README.md). Without this configuration, running a QR skill returns **503**, never a sample favorable verdict. No payments are supported by the active application.

### Chert messages and calls

Set `CHERT_WEBHOOK_SECRET` and point signed message events to `POST /chert/webhook` on the Python API. The adapter accepts the existing `message.received` event shape (`data.message.sender`, `data.message.parts`); confirm your subscription emits that shape before connecting it. Signature failures are rejected, timestamps are checked and event IDs are claimed durably before execution.

Commands:

```text
BUILD Check if QR codes are scams
BUILD Analyze my workouts
LIBRARY
PUBLISH <skill-id> 1
INSTALL <skill-id> 1
RUN <skill-id> 1 {"sessions":[{"exercise":"Walk","minutes":30}]}
```

By default the webhook returns its result as JSON without sending a message. To enable provider replies to the signed event's verified sender, set `FACTORY_SEND_REPLIES=1` and configure `CHERT_API_KEY`, `CHERT_PROJECT_ID`, and `CHERT_LINE_ID`. Delivery status is recorded with the result. Retries return the stored response; a failed delivery does not silently run the skill again. Provider account restrictions still apply. No messages or calls are sent during tests.

For an inbound voice walkthrough, install `chert/requirements.txt` in addition to the root requirements, configure LiveKit/Google credentials and the existing Chert bridge, and run:

```bash
python -m chert.agent_integration dev
```

The agent registers the approved factory tools and explains each build. Installations work through the generic `run_skill` tool; bundles require this runtime and are not standalone Chert plugins. Trusted job dispatch can pass `factory_owner` to share a catalog identity; otherwise calls use a room-scoped workspace. Browser, message-sender and room workspaces are separate until an explicit account-linking flow is built. **Automatic outbound FaceTime callbacks and arbitrary program generation are not implemented in this release.** The new voice adapter and provider delivery require live integration verification.

## Data and permissions

SQLite (`FACTORY_DB`, default `var/factory.sqlite3`) stores manifests, owners, releases, pinned installations, suggestions and webhook deduplication results. Mount this file on persistent storage. Browser workspaces use an unguessable HttpOnly cookie; there is no recovery/account system yet. Clearing cookies loses access to drafts. Published manifests/instructions are public. Raw build prompts are not published. Session inputs are not persisted by the web runner; signed messaging results are stored for replay protection.

Installation is explicit; QR capabilities disclose remote browsing/external analysis, workout capabilities require no external provider. Manifests cannot select arbitrary Python imports or shell commands. The product is a single-instance prototype; public rollout still needs quotas, retention management, account recovery, verified linking across channels and infrastructure isolation review.

## API

| Method | Path | Action |
|---|---|---|
| GET | `/factory/templates` | Supported builders and dependencies |
| POST | `/factory/build` | `{idea}` → private version 1 |
| GET | `/factory/workspace` | Own builds and installed versions |
| GET | `/factory/library` | Latest published releases |
| POST | `/factory/skills/{id}/publish` | `{version}` |
| POST | `/factory/skills/{id}/install` | `{version}` |
| POST | `/factory/skills/{id}/run` | `{version,input}` |
| POST / GET | `/factory/skills/{id}/suggestions` | Propose / author review |
| POST | `/factory/skills/{id}/revisions` | `{expected_version,instructions,suggestion_id?}` |
| GET | `/factory/skills/{id}/versions/{v}/bundle` | Download manifest and instructions |

## Verification

```bash
python -m unittest discover -s tests -v
cd app
npm run typecheck
npm run build
```

Offline backend tests exercise cross-workspace access, private drafts, published installs, executable workout summaries, immutable releases, stale revisions, suggestion acceptance, download bundles, QR configuration failure, signed webhook replay and retirement of payment routes.

## Repository

| Path | Responsibility |
|---|---|
| `factory/` | Catalog, SQLite persistence, lifecycle and registered runners |
| `api/` | API entrypoint and retained QR analysis |
| `app/` | Factory web UI and same-origin API proxy |
| `chert/` | Signed messaging adapter, optional replies and voice tools |
| `sandbox/` | Retained isolated browser worker (public operator route removed) |
| `tests/` | Active factory/runtime regression tests |
| `archive/legacy-scansafe/` | Retired product, payments, map/data UI, old deployment instructions and tests |

See [archive/README.md](archive/README.md) for what moved and how to recover it. This commit does not deploy or alter running servers.
