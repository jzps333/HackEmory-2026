#!/usr/bin/env bash
# Installs Coder on the agent server so the team builds ScanSafe in Coder workspaces.
# Run as root on the agent server:
#   curl -fsSL https://raw.githubusercontent.com/jzps333/HackEmory-2026/main/scripts/setup_coder.sh | bash
# Then open http://<server-ip>:3000, create the admin account, add the "Docker Containers"
# starter template, and invite teammates. Docs: https://coder.com/docs
set -euo pipefail

IP="$(curl -s -4 ifconfig.me)"
echo "== Installing Coder =="
curl -fsSL https://coder.com/install.sh | sh

echo "== Configuring Coder at http://$IP:3000 =="
mkdir -p /etc/coder.d
touch /etc/coder.d/coder.env
grep -q '^CODER_ACCESS_URL=' /etc/coder.d/coder.env \
  && sed -i "s|^CODER_ACCESS_URL=.*|CODER_ACCESS_URL=http://$IP:3000|" /etc/coder.d/coder.env \
  || echo "CODER_ACCESS_URL=http://$IP:3000" >> /etc/coder.d/coder.env
# The package ships an empty CODER_HTTP_ADDRESS= line; Coder refuses to start without it.
grep -q '^CODER_HTTP_ADDRESS=' /etc/coder.d/coder.env \
  && sed -i "s|^CODER_HTTP_ADDRESS=.*|CODER_HTTP_ADDRESS=0.0.0.0:3000|" /etc/coder.d/coder.env \
  || echo "CODER_HTTP_ADDRESS=0.0.0.0:3000" >> /etc/coder.d/coder.env
# Open the port if ufw is on (Vultr images ship with ufw allowing only SSH).
command -v ufw >/dev/null && ufw allow 3000/tcp >/dev/null || true

# Coder's Docker template needs Docker access.
command -v docker >/dev/null || apt-get install -y -qq docker.io
id coder >/dev/null 2>&1 && usermod -aG docker coder || true

systemctl enable --now coder
systemctl restart coder
sleep 5
systemctl --no-pager --lines=5 status coder || true
echo
echo "Open http://$IP:3000 to create the admin account."
echo "Then: Templates -> Create -> Docker Containers, and Users -> invite teammates."
