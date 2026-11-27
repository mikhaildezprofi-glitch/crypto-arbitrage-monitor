#!/usr/bin/env bash
set -euo pipefail
STATE_DIR="/workspaces/.codespace-private-state"
PROFILE_DIR="/tmp/eid-chromium-profile"
ARCHIVE="$STATE_DIR/chromium-profile.tar.gz.gpg"
trap 'rm -f "$STATE_DIR/chromium-profile.tar.gz"' EXIT
mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"
if [ -s "$ARCHIVE" ] && [ -n "${CHROMIUM_PROFILE_PASSPHRASE:-}" ]; then
  mkdir -p "$PROFILE_DIR"
  chmod 700 "$PROFILE_DIR"
  exec 3<<<"$CHROMIUM_PROFILE_PASSPHRASE"
  gpg --batch --yes --pinentry-mode loopback --passphrase-fd 3 \
    --output "$STATE_DIR/chromium-profile.tar.gz" --decrypt "$ARCHIVE"
  if tar -tzf "$STATE_DIR/chromium-profile.tar.gz" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
    echo "CODESPACES_PROFILE_ARCHIVE_UNSAFE"
    exit 1
  fi
  rm -rf "$PROFILE_DIR"
  mkdir -p "$PROFILE_DIR"
  tar -xzf "$STATE_DIR/chromium-profile.tar.gz" -C "$PROFILE_DIR"
  rm -f "$STATE_DIR/chromium-profile.tar.gz"
  chmod -R go-rwx "$PROFILE_DIR"
  echo "CODESPACES_PROFILE=RESTORED_FROM_ENCRYPTED_ARCHIVE"
elif [ -s "$ARCHIVE" ]; then
  echo "CODESPACES_PROFILE_PASSPHRASE_REQUIRED"
  exit 1
else
  echo "CODESPACES_PROFILE=FIRST_AUTHENTICATION_REQUIRED"
fi
