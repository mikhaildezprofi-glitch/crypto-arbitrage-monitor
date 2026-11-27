#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="/workspaces/.codespace-private-state"
PROFILE_DIR="$STATE_DIR/profile"
mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"
if [ ! -d "$PROFILE_DIR" ]; then
  mkdir -p "$PROFILE_DIR"
  chmod 700 "$PROFILE_DIR"
fi
rm -rf /tmp/eid-chromium-profile
ln -s "$PROFILE_DIR" /tmp/eid-chromium-profile
export CODESPACES_MODE=1
export TARGET=auth_only
export GITHUB_WORKSPACE="$ROOT"
export GITHUB_RUN_ID="codespaces-${CODESPACE_NAME:-manual}"
echo "CODESPACES_BROWSER_MODE=AUTH_ONLY"
echo "CODESPACES_COLLECTION=DISABLED"
echo "CODESPACES_PROFILE_STORAGE=$PROFILE_DIR"
set +e
bash "$ROOT/scripts/keep_browser_and_tunnel_alive.sh"
BROWSER_EXIT=$?
set -e
if [ -n "${CHROMIUM_PROFILE_PASSPHRASE:-}" ]; then
  bash "$ROOT/.devcontainer/save-private-profile.sh"
else
  echo "CODESPACES_PROFILE_NOT_ENCRYPTED: configure CHROMIUM_PROFILE_PASSPHRASE as a Codespaces secret"
  exit 2
fi
exit "$BROWSER_EXIT"
