#!/usr/bin/env bash
# ScanSafe health check. Run from your Mac:   ./deploy/check.sh
# Read-only: it restarts nothing and prints no secrets (only status codes, states and log lines).
# Override the hosts with AGENT_HOST=... SANDBOX_HOST=... if the servers move.
set -u
AGENT_HOST=${AGENT_HOST:-root@144.202.25.65}
SANDBOX_HOST=${SANDBOX_HOST:-root@64.177.45.84}
SSH=(ssh -o ConnectTimeout=8 -o BatchMode=yes)

echo "================ agent server ($AGENT_HOST) ================"
"${SSH[@]}" "$AGENT_HOST" 'bash -s' <<'REMOTE' || echo "!! could not reach the agent server"
cd /root/HackEmory-2026 2>/dev/null || { echo "!! /root/HackEmory-2026 missing"; exit 1; }
code() { curl -s -m "${2:-10}" -o /dev/null -w '%{http_code}' "$1"; }

echo "-- services (state / enabled / restarts since start)"
for u in scansafe-api scansafe-agent scansafe-chert caddy; do
  printf '  %-15s %-9s %-9s restarts=%s\n' "$u" "$(systemctl is-active $u)" "$(systemctl is-enabled $u 2>/dev/null)" \
    "$(systemctl show -p NRestarts --value $u)"
done

echo "-- git"
GIT_TERMINAL_PROMPT=0 timeout 15 git fetch -q origin 2>/dev/null || echo "  (git fetch failed; showing last known origin/main)"
echo "  HEAD $(git rev-parse --short HEAD) ($(git log -1 --format=%s | cut -c1-60))"
echo "  behind origin/main: $(git rev-list --count HEAD..origin/main)  ahead: $(git rev-list --count origin/main..HEAD)  dirty files: $(git status --porcelain | wc -l)"

echo "-- api"
echo "  local  /health  $(code http://127.0.0.1:8000/health 5)  $(curl -s -m 5 http://127.0.0.1:8000/health)"
echo "  public /health  $(code https://api.scansafe.nyc/health 10)"
echo "  /pins (Typesense)        $(code 'http://127.0.0.1:8000/pins?lat=33.749&lng=-84.388&radius_km=5' 15)"
echo "  /stats/summary (Tiger)   $(code http://127.0.0.1:8000/stats/summary 15)"

echo "-- sandbox, as the API sees it"
SB=$(grep -E '^SANDBOX_URL=' .env | tail -1 | cut -d= -f2- | tr -d '"'"'"' ')
if [ -n "$SB" ]; then echo "  SANDBOX_URL/health  $(code "$SB/health" 8)"; else echo "  SANDBOX_URL not set (API runs in mock mode)"; fi

echo "-- FaceTime agent (last worker lines)"
journalctl -u scansafe-agent --since "-6 h" --no-pager -o cat 2>/dev/null \
  | grep -E '"message": "(registered worker|received job request|worker failed|exiting forcefully|drain timed out)' \
  | tail -3 | python3 -c '
import sys, json
for l in sys.stdin:
    try:
        j = json.loads(l); print("  " + j.get("timestamp", "")[:19].replace("T", " ") + "  " + j.get("message", "")[:80])
    except Exception:
        print("  " + l.strip()[:100])'

echo "-- Chert bridge (last relevant line)"
journalctl -u scansafe-chert --since "-24 h" --no-pager -o 'short-iso' 2>/dev/null \
  | grep -E 'waiting room|NOT|Call ended|Incoming|Answered|Reconnect|expired|login|unreachable|Could not|Stopped|error|Error' \
  | tail -1 | cut -c1-220 | sed 's/^/  /'

echo "-- host"
echo "  uptime: $(uptime -p)   load: $(cut -d' ' -f1-3 /proc/loadavg)"
df -h / | awk 'NR==2 {print "  disk /: " $3 " used of " $2 " (" $5 ")"}'
free -m | awk '/^Mem:/ {print "  mem: " $3 " MB used, " $7 " MB available of " $2 " MB"}'
REMOTE

echo
echo "================ sandbox server ($SANDBOX_HOST) ================"
"${SSH[@]}" "$SANDBOX_HOST" 'bash -s' <<'REMOTE' || echo "!! could not reach the sandbox server"
echo "-- services"
for u in scansafe-sandbox docker netfilter-persistent; do
  printf '  %-21s %-9s %-9s\n' "$u" "$(systemctl is-active $u)" "$(systemctl is-enabled $u 2>/dev/null)"
done
echo "  local /health $(curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/health)   scan containers running: $(docker ps -q 2>/dev/null | wc -l)"
echo "  docker network scansafe-net: $(docker network inspect -f '{{.Name}}' scansafe-net >/dev/null 2>&1 && echo present || echo MISSING)"
echo "  egress guard, DROP rules on scansafe0: DOCKER-USER $(iptables -S DOCKER-USER 2>/dev/null | grep -c 'scansafe0.*DROP') (expect 11), INPUT $(iptables -S INPUT 2>/dev/null | grep -c 'scansafe0.*DROP') (expect 2)"
echo "-- host"
echo "  uptime: $(uptime -p)   load: $(cut -d' ' -f1-3 /proc/loadavg)"
df -h / | awk 'NR==2 {print "  disk /: " $3 " used of " $2 " (" $5 ")"}'
free -m | awk '/^Mem:/ {print "  mem: " $3 " MB used, " $7 " MB available of " $2 " MB"}'
REMOTE
