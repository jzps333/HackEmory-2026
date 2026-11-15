# Community plugins for Chert

Open-source skills for a Chert FaceTime agent. Anyone can add one with a pull request; it shows as
**unverified** until an admin verifies it.

## Add a plugin

1. Make a folder `plugins/<id>/` (`id`: 2-40 characters, `a-z`, `0-9`, `-`).
2. Add `plugin.yaml` and a `README.md` that explains what it does.
3. Open a pull request. A check validates the file; if the repo has a Gemini key, an AI reviewer
   also posts a safety score with reasons.

```yaml
id: squat-coach
name: Squat coach
summary: Watches your squats on FaceTime and calls out form cues.
author: your-github-handle
version: 1
kind: live                  # runs on the FaceTime call
runs_on: server             # server, or vm (the locked-down browser box)
triggers:
  phrases: ["coach my squats"]
  qr: false                 # true: a QR code on camera starts it
tools: [camera, speak, screen, memory]
permissions: Read aloud before the first run.
instructions: What the agent does while this plugin is active, in plain words.
```

## Tools

| Tool | What it does | Unverified plugins |
|---|---|---|
| `camera` | the agent sees the caller's video | yes |
| `speak` | talks on the call | yes |
| `screen` | shows text on the video sent back to the caller | yes |
| `memory` | saves small per-person records | yes |
| `safe_browser` | opens a link in the locked-down VM, live on the call | yes |
| `scam_check` | ScanSafe scam verdict for a link | yes |
| `plugin_search` | searches this library by voice | yes |
| `whiteboard` | writes lesson notes step by step on the video, with side notes (Tutor) | yes |
| `solana_pay` | test-money payment after a spoken "yes, pay" | no, verified only |
| `parking` | fills in a parking site up to the pay step | no, verified only |

A plugin is data: its instructions are given to the agent as text and are never run as code.

## Verified vs unverified

`verified.json` lists each approved plugin with a SHA-256 of its `plugin.yaml` + `README.md`.
Only admins can change that file (`.github/CODEOWNERS`). Any edit to a plugin changes its hash, so
it shows and runs as unverified again until an admin re-approves it:

```bash
python -m api.plugins_index --hash <id>     # value for verified.json
python -m api.plugins_index --check         # validate every plugin
```
