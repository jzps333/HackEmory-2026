#!/usr/bin/env bash
# One-command setup for the ScanSafe AGENT server (backend + FaceTime agent + Coder).
# Run on a fresh Ubuntu 24.04 Vultr VM as root:
#   curl -fsSL https://raw.githubusercontent.com/jzps333/HackEmory-2026/main/scripts/setup_agent_server.sh | bash
# It asks for each key with hidden input. Keys go only into ~/HackEmory-2026/.env (chmod 600).
set -euo pipefail

SANDBOX_IP="${SANDBOX_IP:-64.177.45.84}"
REPO_DIR="$HOME/HackEmory-2026"
ask() {  # ask VAR "Prompt" [hidden]
  local var="$1" prompt="$2" hidden="${3:-}" val=""
  if [ -n "$hidden" ]; then read -r -s -p "$prompt: " val </dev/tty; echo; else read -r -p "$prompt: " val </dev/tty; fi
  printf -v "$var" '%s' "$val"
}
setenv() {  # setenv KEY VALUE  (only writes non-empty values)
  [ -z "$2" ] && return 0
  python3 - "$REPO_DIR/.env" "$1" "$2" <<'PY'
import sys, re
path, key, val = sys.argv[1:]
lines = open(path).read().splitlines()
out, done = [], False
for l in lines:
    if re.match(rf"^{re.escape(key)}=", l):
        out.append(f"{key}={val}"); done = True
    else:
        out.append(l)
if not done: out.append(f"{key}={val}")
open(path, "w").write("\n".join(out) + "\n")
PY
}

echo "== 1/6 Installing packages (2-3 min) =="
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-pip python3-venv git tmux docker.io curl >/dev/null

echo "== 2/6 Getting the code =="
if [ -d "$REPO_DIR/.git" ]; then git -C "$REPO_DIR" pull -q; else git clone -q https://github.com/jzps333/HackEmory-2026.git "$REPO_DIR"; fi
cd "$REPO_DIR"
pip install -q --break-system-packages -r requirements.txt

echo "== 3/6 Checking the sandbox at $SANDBOX_IP =="
if curl -fsS -m 5 "http://$SANDBOX_IP:8080/health" >/dev/null; then echo "Sandbox reachable"; else
  echo "WARNING: can't reach the sandbox. Check it's running and its firewall allows this server's IP."; fi

echo "== 4/6 Your keys (typing is hidden; press Enter to skip any) =="
[ -f .env ] || cp .env.example .env
chmod 600 .env
ask JEV "OpenRouter key (for Jev)" hidden
ask GEM "Gemini API key" hidden
ask TOK "SANDBOX_TOKEN you saved from the sandbox" hidden
ask TIGER "Tiger Data connection string (postgres://...)" hidden
ask TSH "Typesense host URL (https://..., Enter to skip)"
ask TSK "Typesense admin API key (Enter to skip)" hidden
setenv JEV_API_KEY "$JEV"; setenv GEMINI_API_KEY "$GEM"; setenv SANDBOX_TOKEN "$TOK"
setenv SANDBOX_URL "http://$SANDBOX_IP:8080"; setenv TIGER_DATABASE_URL "$TIGER"
setenv TYPESENSE_HOST "$TSH"; setenv TYPESENSE_API_KEY "$TSK"
unset JEV GEM TOK TIGER TSK
echo "Saved to $REPO_DIR/.env (only root can read it)"

echo "== 5/6 Setting up databases =="
python3 -m data.setup || echo "(A service said FAIL or SKIP above. Fine for now if you skipped its key.)"

echo "== 6/6 Starting the backend =="
tmux kill-session -t api 2>/dev/null || true
tmux new -d -s api "cd $REPO_DIR && uvicorn api.main:app --host 0.0.0.0 --port 8000"
sleep 4
echo "--- /health ---"; curl -s localhost:8000/health; echo
echo "--- test scan of https://example.com ---"
curl -s -m 90 -X POST localhost:8000/scan -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com"}' | python3 -c 'import sys,json; r=json.load(sys.stdin); print("verdict:", r.get("verdict"), "| score:", r.get("jev_score"), "|", r.get("explanation"))' \
  || echo "Scan failed: run  tmux attach -t api  to see the error"
echo
echo "Done. Backend: http://$(curl -s -4 ifconfig.me 2>/dev/null || echo THIS_SERVER_IP):8000/health"
echo "See the backend log any time:  tmux attach -t api   (leave with Ctrl+B then D)"
