# Sandbox (Person 1)

Runs on its **own** Vultr server, separate from the agent/backend server. It holds **no API keys**.

## Set up the sandbox server

```bash
# On a fresh Ubuntu 24.04 Vultr VM, as root:
apt update && apt install -y docker.io python3-pip python3-venv git
git clone https://github.com/jzps333/HackEmory-2026.git && cd HackEmory-2026/sandbox
docker build -t scansafe-sandbox .

# Test one scan (prints JSON):
docker run --rm scansafe-sandbox https://example.com

# Run the HTTP service the backend calls:
python3 -m venv .venv && . .venv/bin/activate && pip install fastapi uvicorn
export SANDBOX_TOKEN=$(openssl rand -hex 24)   # put the same value in the backend's .env
tmux new -s sandbox 'uvicorn server:app --host 0.0.0.0 --port 8080'
```

Then in the backend's `.env`: `SANDBOX_URL=http://<sandbox-ip>:8080` and the same `SANDBOX_TOKEN`.

In the Vultr firewall, allow port 8080 **only from the agent/backend server's IP**.

## What one scan returns

| Field | Notes |
|---|---|
| `url`, `final_url`, `domain` | submitted URL, where the browser ended up |
| `redirect_chain` | every main-frame URL (HTTP 3xx and JavaScript redirects) |
| `status_codes` | per hop: `{url, status, ip}` (`ip` = server address Chromium actually connected to) |
| `page_title`, `page_text` | visible text, capped at 4000 chars |
| `hidden_text` | text a person can't see but a model could (display:none, visibility:hidden, opacity 0, tiny font, off-screen, clipped, same colour as background, HTML comments), capped at 1500 chars, `[reason] text \| ...`. `hidden_text_items` is the same as a list of `{reason, text}` |
| `form_fields` | max 25: `{type, name, placeholder, autocomplete, label, form_action}` |
| `downloads`, `popups` | attempted downloads (cancelled, never saved) and popup windows (closed) |
| `blocked_requests` | max 30: `{url, reason, type}` for every request the network guard refused |
| `screenshots` | one JPEG data URL, 390 px wide, quality 60 (about 20 to 40 KB) |
| `timings` | ms: `browser_ready_ms, first_load_ms, settled_ms, collected_ms, total_ms` |
| `error` | null on success. Starts with `blocked:` if the destination itself was refused or a hop was served from a non-public IP; the backend must treat that as "Could not complete check" or worse, never as safe |

## Network guard (SSRF protection)

`netguard.py` is pure Python (no Playwright) and is used twice:

1. `server.py` rejects the QR URL with HTTP 400 before starting a container.
2. `run_scan.py` checks **every** browser request through `context.route("**/*")`: the first URL,
   each redirect hop, subresources, iframes and popups. Service workers and WebSockets are blocked
   so nothing goes around the route. DNS prefetch and WebRTC UDP are disabled.

A request is allowed only if the scheme is `http`/`https`, there are no `user:pass@` credentials,
the host isn't `localhost`/`*.local`/`*.internal`/metadata names, and **every** A/AAAA answer is a
public unicast address. Blocked: loopback, RFC1918, link-local (incl. `169.254.169.254`), CGNAT
`100.64/10`, `0.0.0.0/8`, multicast, reserved, IPv6 `::1`, `fc00::/7`, `fe80::/10`, and IPv4
hidden inside IPv6 (`::ffff:`, NAT64 `64:ff9b::`, 6to4, Teredo). Numeric tricks such as
`2130706433`, `0x7f000001`, `0177.0.0.1`, `127.1` are parsed the way browsers parse them.
Host decisions are cached per scan, so a host can't flip to a private IP mid-scan.

Tests: `python3 -m pytest -q tests/test_sandbox.py` (offline, fake resolver).

**Limit:** Chromium resolves the hostname again after our check, so a DNS-rebinding server could
still win the race. `run_scan.py` flags any hop whose server IP is non-public, but the real fix
is the host firewall below. Do both.

## Host firewall (defense in depth, do this on the sandbox VM)

Give scan containers their own bridge so the rules only hit them:

```bash
docker network create --driver bridge \
  -o com.docker.network.bridge.name=scansafe0 \
  -o com.docker.network.bridge.enable_icc=false scansafe-net
export SANDBOX_NETWORK=scansafe-net        # server.py then runs containers with --network
```

iptables (`DOCKER-USER` is evaluated before Docker's own rules and survives Docker restarts):

```bash
for net in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16 100.64.0.0/10 \
           127.0.0.0/8 0.0.0.0/8 224.0.0.0/4 240.0.0.0/4 192.0.0.0/24 198.18.0.0/15; do
  iptables -I DOCKER-USER -i scansafe0 -d "$net" -j DROP
done
# replies to connections the container opened to public hosts
iptables -I DOCKER-USER -i scansafe0 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
# block containers from talking to the VM itself (sandbox API on :8080, sshd, etc.)
iptables -I INPUT -i scansafe0 -p tcp -j DROP
iptables -I INPUT -i scansafe0 -p udp ! --dport 53 -j DROP

# IPv6: simplest is no IPv6 on the scan network at all (the network above has none by
# default). If you enable it, also:
ip6tables -I DOCKER-USER -i scansafe0 -d ::1/128 -j DROP
ip6tables -I DOCKER-USER -i scansafe0 -d fc00::/7 -j DROP
ip6tables -I DOCKER-USER -i scansafe0 -d fe80::/10 -j DROP
ip6tables -I DOCKER-USER -i scansafe0 -d ff00::/8 -j DROP
ip6tables -I DOCKER-USER -i scansafe0 -d 64:ff9b::/96 -j DROP

apt install -y iptables-persistent && netfilter-persistent save   # keep after reboot
```

Equivalent nftables:

```bash
nft add table inet scansafe
nft add chain inet scansafe fwd '{ type filter hook forward priority -10; }'
nft add rule inet scansafe fwd iifname scansafe0 ip daddr '{ 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16, 100.64.0.0/10, 127.0.0.0/8, 0.0.0.0/8, 224.0.0.0/4, 240.0.0.0/4 }' drop
nft add rule inet scansafe fwd iifname scansafe0 ip6 daddr '{ ::1/128, fc00::/7, fe80::/10, ff00::/8, 64:ff9b::/96 }' drop
nft add chain inet scansafe in '{ type filter hook input priority -10; }'
nft add rule inet scansafe in iifname scansafe0 udp dport 53 accept
nft add rule inet scansafe in iifname scansafe0 drop
```

Check it from a container (each should fail/time out):

```bash
docker run --rm --network scansafe-net curlimages/curl -m 3 http://169.254.169.254/
docker run --rm --network scansafe-net curlimages/curl -m 3 http://172.17.0.1:8080/health
```

On Vultr, also note the metadata service is at `169.254.169.254`; the rules above cover it.

## Isolation

Each scan is a fresh container: `--rm` (plus `docker rm -f` if it times out), `--init`,
read-only filesystem, no Linux capabilities, no new privileges, 1 GB memory, 1 CPU, 256 pids,
45 second limit, downloads cancelled, popups closed, max 10 redirects and 300 requests, runs as a
non-root user. The container holds no keys.

Chromium's own sandbox is off by default (Playwright's default inside Docker). To turn it on, run
the container with Playwright's seccomp profile and `-e CHROMIUM_SANDBOX=1`
(see https://playwright.dev/docs/docker). Not required for the demo, recommended before public scanning.

`CHROMIUM_PATH` overrides the browser binary for local testing only.

Fixture pages for the demo are in `../fixtures/`. They must be on a public host to scan;
`localhost` is refused by design.
