#!/usr/bin/env bash
set -euo pipefail
sudo apt-get update
sudo apt-get install -y --no-install-recommends nginx xvfb x11vnc x11-utils websockify gpg
python -m pip install --user --break-system-packages playwright websocket-client
python -m playwright install --with-deps chromium
mkdir -p /workspaces/.codespace-private-state
chmod 700 /workspaces/.codespace-private-state
mkdir -p /workspaces/.codespace-private-state/profile
chmod 700 /workspaces/.codespace-private-state/profile
echo "CODESPACES_BROWSER_DEPENDENCIES=INSTALLED"
