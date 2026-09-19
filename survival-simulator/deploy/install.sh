#!/usr/bin/env bash
# One-shot deployment of the survival-simulator agent endpoint on a fresh Ubuntu 22.04/24.04 host.
# Usage (as a sudo-capable user):  curl -fsSL https://raw.githubusercontent.com/WenBiming/Nordic-AI-Cup-2026/survival-simulator/survival-simulator/deploy/install.sh | bash -s -- [PRESET]
# Result: systemd service `survival-agent` (agent_server.py --preset PRESET on 127.0.0.1:9052) behind nginx on port 80.
set -euo pipefail
PRESET="${1:-14a}"
APP="$HOME/Nordic-AI-Cup-2026"
export DEBIAN_FRONTEND=noninteractive

sudo apt-get -qq update && sudo apt-get -qq install -y git nginx python3-venv python3-pip >/dev/null
if [ -d "$APP/.git" ]; then git -C "$APP" fetch -q && git -C "$APP" checkout -q survival-simulator && git -C "$APP" pull -q
else git clone -q -b survival-simulator https://github.com/WenBiming/Nordic-AI-Cup-2026.git "$APP"; fi
cd "$APP/survival-simulator"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r requirements.txt

sed -e "s|/home/wenbiming/Nordic-AI-Cup-2026|$APP|g" -e "s|User=wenbiming|User=$USER|" -e "s|--preset [^ ]*|--preset $PRESET|" \
    deploy/survival-agent.service | sudo tee /etc/systemd/system/survival-agent.service >/dev/null
sudo systemctl daemon-reload && sudo systemctl enable -q survival-agent && sudo systemctl restart survival-agent
sudo cp deploy/nginx-survival-agent.conf /etc/nginx/sites-available/survival-agent
sudo ln -sf /etc/nginx/sites-available/survival-agent /etc/nginx/sites-enabled/survival-agent
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
sleep 3
echo "service: $(systemctl is-active survival-agent)"; curl -s http://127.0.0.1/ ; echo
echo "RTT to the platform host:"; for i in 1 2 3; do curl -s -o /dev/null -w "  %{time_connect}s\n" -m 5 --insecure https://46.62.240.126/; done
