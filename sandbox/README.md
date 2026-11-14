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

`url, final_url, domain, redirect_chain, page_title, page_text, form_fields, downloads, screenshots, error`

## Isolation

Each scan is a fresh container: `--rm`, read-only filesystem, no Linux capabilities,
no new privileges, 1 GB memory, 1 CPU, 45 second limit, downloads blocked, runs as a non-root user.
