# Handoff: where ScanSafe stands (Saturday Nov 14, 2026)

Read this first if you're a new Claude Code session or a teammate picking up the work.
No secrets in this file. Keys live only in `.env` files on the servers.

## The project
ScanSafe, EmoryHacks 2026 (Atlanta, Nov 13–15). **Devpost deadline: Sunday 8:00 AM EST** (aim for 7 AM).
Scan a QR code without risking your phone: the link opens in a throwaway sandbox on a server, Jev scores
it, Gemini explains it, a Chert FaceTime agent speaks the verdict and sends an iMessage, scams get pinned
on a Typesense map, every scan is logged to Tiger Data, and Solana Pay codes are checked before paying
(devnet only). Main track: **Security**. See `TEAM.md` for roles, checkpoints and the Devpost checklist.

## Servers (Vultr, Atlanta, Ubuntu 24.04)
| Server | IP | Runs | Status |
|---|---|---|---|
| scansafe-sandbox (4 vCPU / 8 GB) | 64.177.45.84 | `sandbox/server.py` on :8080 in tmux `sandbox`, Docker image `scansafe-sandbox`, network `scansafe-net` with iptables egress blocks, ufw: 8080 only from the agent server | **Done and tested** |
| scansafe-agent (2 vCPU / 4 GB) | 144.202.25.65 | Backend (:8000, tmux `api`), Chert FaceTime agent, Coder (:3000) | **Created, not set up yet** |

Vultr credit: ~$99.70; both servers ≈ $72/mo. **Destroy both after the hackathon.** Also pause/delete the
Tiger Data service afterward.

## Accounts already set up
- Grok Bot reviews every push (`.github/workflows/grok-review.yml`, secrets saved in GitHub).
- Domain: `scansafe.nyc` (GoDaddy via MLH; `.nyc` has an NYC-residency rule, keep `scansafe.vercel.app` as backup).
- Tiger Data service created (connection string in the downloaded `tiger-cloud-db-…-credentials.env`).
- Chert FaceTime line **+1 650-444-4331**, project `a84bec72-3b8b-4bd5-89f7-b3827d3a623d`, free trial
  (50 FaceTime min/day, resets 00:00 UTC). Trial can only text a phone back within 24 h of that phone texting the line.
- LiveKit project "hack emory 2026".
- Jev runs through the **OpenRouter** key from the Relay project (`typesafe/jev-1.14`).
- Coder team confirmed: building with Coder (team dev workspaces) is enough for the Coder prize.

## Next steps, in order
1. **Agent server** (one command, asks for keys with hidden input):
   `ssh root@144.202.25.65` then
   `curl -fsSL https://raw.githubusercontent.com/jzps333/HackEmory-2026/main/scripts/setup_agent_server.sh | bash`
   Expect `/health` → `"mock_mode": false` and a real verdict for example.com.
2. **Coder**: `curl -fsSL https://raw.githubusercontent.com/jzps333/HackEmory-2026/main/scripts/setup_coder.sh | bash`,
   then open http://144.202.25.65:3000, create admin, add the Docker Containers template, invite teammates.
   Screenshot workspaces for Devpost.
3. **Chert agent**: follow `chert/INTEGRATION.md` on the agent server. Text the line from the demo iPhone first.
   If the agent never sees video, ask Chert to enable caller video for the line.
4. **Typesense**: create a free cluster, put host + admin key in the agent server's `.env`, run `python3 -m data.setup`.
5. **Vercel**: import the repo, Root Directory = `app`, env `NEXT_PUBLIC_API_URL` = the backend URL (needs HTTPS
   for the browser camera: put the backend behind HTTPS, e.g. Caddy on the agent server with a subdomain).
   Also host `fixtures/site/` publicly (the sandbox refuses localhost on purpose).
6. **Devnet wallets**: `scripts/README.md`. Replace the placeholder Peachtree wallet in `api/scan.py`
   `KNOWN_MERCHANTS` with your own, regenerate QR codes with `scripts/make_demo_qr.py`.
7. Claim MLH codes (Entire, SpaceXSI), install the Entire CLI, code in Cursor.
8. **Midnight checkpoint**: one real end-to-end scan. 3 AM feature freeze. 5 AM record the demo. 7 AM submit.

## Open decisions / gotchas
- Teammate sreenn's README (top half) is a pre-code plan with different folder names and an async scan API.
  The built code uses `api/ sandbox/ chert/ data/ app/ shared/` and a synchronous `POST /scan`. Agree as a
  team, then update the README's top half (name, status, layout, API list).
- Demo uses only made-up brands (Peachtree Parking Co., Magnolia Diner) and our own printed QR codes on a prop.
  Never real meters, never copies of real companies' pages.
- Payments are devnet only, user approves every payment; reports are user-submitted.
- Don't paste keys into chat or commit them. `.env`, `.env.local` are gitignored.

## Repo map
`api/` FastAPI (scan, Jev, verdict, data + pay + Chert webhook routers) · `sandbox/` Playwright in locked-down
Docker + netguard · `chert/` FaceTime agent (LiveKit + Gemini Live) + iMessage · `data/` Typesense + Tiger Data ·
`app/` Next.js PWA · `shared/` scan_result contract + mocks · `fixtures/` demo pages + QR codes · `scripts/`
setup scripts, demo QR generator · `tests/` 147 offline tests (`python3 -m pytest -q`).
