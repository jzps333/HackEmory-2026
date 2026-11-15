# Deploy and operate ScanSafe

Everything runs under systemd on two Vultr boxes (Atlanta, Ubuntu 24.04). Services restart on
crash (`Restart=always`, no give-up limit) and start on boot. Logs go to journald.

| Server | Unit | What it runs | Port |
|---|---|---|---|
| agent `144.202.25.65` | `scansafe-api` | `uvicorn api.main:app` (Caddy: `https://api.scansafe.nyc` → here) | `127.0.0.1:8000` |
| agent | `scansafe-agent` | `python3 -m chert.agent_integration start --drain-timeout 5`: the FaceTime agent, a LiveKit worker named `scansafe-agent` | `:8081` (its health server; only one worker fits on the box) |
| agent | `scansafe-chert` | `chert dev --agent scansafe-agent` from `chert/scansafe-agent/`: holds the Chert line and keeps a warm room with the agent in it | none |
| sandbox `64.177.45.84` | `scansafe-sandbox` | `.venv/bin/uvicorn server:app` in `sandbox/`; one throwaway container per scan on Docker network `scansafe-net` | `0.0.0.0:8080` |

Caddy, Coder and Docker are separate system services; these units don't touch them.
The unit files live in `deploy/systemd/`. The apps read their own `.env` files, so only the sandbox
unit has an `EnvironmentFile` (`/etc/scansafe/sandbox.env`, `chmod 600`, one line `SANDBOX_TOKEN=...`,
the same value as `SANDBOX_TOKEN` in the agent server's `.env`).

## Health

```bash
./deploy/check.sh        # from the Mac: services, git state, api/sandbox health, Tiger + Typesense, Chert bridge, disk/mem
```

## Deploy (agent server)

The agent server's checkout is a clean `main` (`git status` empty, `pull.ff=only`). Merge to `main`, push, then:

```bash
ssh root@144.202.25.65 'cd ~/HackEmory-2026 && git pull && systemctl restart scansafe-api scansafe-agent'
./deploy/check.sh
```

Never copy files to the server by hand again: that's what put it out of sync with git.
`chert/scansafe-agent/` and the `.env` files are untracked/ignored, so `git pull` never touches them.

What a restart costs:
- **api:** ~2 s of 502s from Caddy. Streams still open get 10 s to finish.
- **agent:** it stops taking jobs, waits 5 s, and is killed at 8 s (it holds no state). It's back
  ("registered worker") ~4 s later. The Chert bridge notices and makes a fresh warm room on its own,
  ~15-20 s after that. **So FaceTime calls can be declined for ~25 s after an agent restart.** A call in
  progress gets cut. Before restarting, check that nobody is on a call:
  `journalctl -u scansafe-chert -n 5` (an `Incoming FaceTime` with no `Call ended` after it means a live call).

**When to restart `scansafe-chert`** (`systemctl restart scansafe-chert`, ~7 s with the line down):
- you changed `chert/scansafe-agent/.env.local` (LiveKit keys) or updated the `chert` CLI, or ran `chert login` again;
- `journalctl -u scansafe-chert` keeps saying `"scansafe-agent" is NOT in the waiting room` while the agent is up;
- right after an agent restart, if you want a fresh warm room now rather than in ~20 s.

Stop chert only with `systemctl stop|restart` (SIGTERM, then it releases the line). Never `kill -9`
it: the line stays held until its lease runs out. Don't run `chert dev` or the agent by hand
(tmux) while the units are up: there can be only one bridge per line and one worker per box.
If Chert's backend is down, chert exits and systemd retries every 20 s (as the old loop did).
The Chert login in `~/.chert/credentials.json` expires 2026-12-14; after that the bridge fails
with `login_required` until someone runs `chert login` on the server.

## Deploy (sandbox server)

The sandbox checkout is not tracked like the agent server: copy or pull only `sandbox/`.
- `server.py` changed: `systemctl restart scansafe-sandbox` (~2 s).
- `run_scan.py`, `netguard.py` or `Dockerfile` changed: they are baked into the image, so rebuild first:
  `cd ~/HackEmory-2026/sandbox && docker build -q -t scansafe-sandbox . && systemctl restart scansafe-sandbox`.
- New token: write `SANDBOX_TOKEN=<value>` into `/etc/scansafe/sandbox.env` (and the agent `.env`),
  then restart `scansafe-sandbox` and `scansafe-api`.

The egress guard (iptables `DOCKER-USER` + `INPUT` drops on `scansafe0`) is loaded at boot by
`netfilter-persistent` from `/etc/iptables/rules.v4`; `check.sh` counts the rules.

## Logs

```bash
journalctl -u scansafe-api -f                 # also: -u scansafe-agent, -u scansafe-chert
journalctl -u scansafe-api --since "-30 min" | grep failed        # e.g. record_scan failed
journalctl -u scansafe-agent -o cat | grep -E 'registered worker|received job request|worker failed'
journalctl -u scansafe-chert -n 20 -o cat     # "is in a waiting room" = ready for calls
ssh root@64.177.45.84 journalctl -u scansafe-sandbox -f
```

`/root/api.log`, `/root/agent.log` and `/root/chert.log` are the old tmux logs (up to 2026-11-14 21:30 UTC)
and no longer grow.

## Install or change a unit

```bash
scp deploy/systemd/scansafe-{api,agent,chert}.service root@144.202.25.65:/etc/systemd/system/
ssh root@144.202.25.65 'systemctl daemon-reload && systemctl enable scansafe-api scansafe-agent scansafe-chert && systemctl restart <the changed unit>'
scp deploy/systemd/scansafe-sandbox.service root@64.177.45.84:/etc/systemd/system/
ssh root@64.177.45.84 'systemctl daemon-reload && systemctl enable --now scansafe-sandbox'
```

The units are copies, so a `git pull` does not change them: re-copy after editing `deploy/systemd/`.

## Roll back

**Bad code on the agent server.** Go back to the last good commit, then return to `main` once it's fixed:

```bash
ssh root@144.202.25.65
cd ~/HackEmory-2026 && git log --oneline -10
git reset --hard <good-sha> && systemctl restart scansafe-api scansafe-agent
# later, after the fix is on main:
git pull && systemctl restart scansafe-api scansafe-agent      # fast-forwards from <good-sha>
```

**The pre-git server state** (scp'd files from before the switch to git) is saved, with its `.env`, in
`/root/backup-pre-git-20261114-212443/HackEmory-2026/` (+ `git-state-before.txt`). Restore with
`rsync -a --delete --exclude .git /root/backup-pre-git-20261114-212443/HackEmory-2026/ /root/HackEmory-2026/`, then restart.

**Back to tmux** (only if systemd itself is the problem):

```bash
systemctl disable --now scansafe-chert scansafe-agent scansafe-api
tmux new -d -s api   "cd ~/HackEmory-2026 && uvicorn api.main:app --host 0.0.0.0 --port 8000 2>&1 | tee /root/api.log"
tmux new -d -s agent "cd ~/HackEmory-2026 && python3 -m chert.agent_integration start 2>&1 | tee /root/agent.log"
tmux new -d -s chert "cd ~/HackEmory-2026/chert/scansafe-agent && while true; do chert dev --agent scansafe-agent 2>&1 | tee -a /root/chert.log; sleep 20; done"
# sandbox server:
systemctl disable --now scansafe-sandbox
cd ~/HackEmory-2026/sandbox && tmux new -d -s sandbox 'set -a; . /etc/scansafe/sandbox.env; set +a; SANDBOX_NETWORK=scansafe-net .venv/bin/uvicorn server:app --host 0.0.0.0 --port 8080'
```
