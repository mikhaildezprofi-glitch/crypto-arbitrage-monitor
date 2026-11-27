#!/usr/bin/env bash
set -euo pipefail
STATE_DIR="/workspaces/.codespace-private-state"
PROFILE_DIR="/tmp/eid-chromium-profile"
ARCHIVE="$STATE_DIR/chromium-profile.tar.gz.gpg"
trap 'rm -f "$STATE_DIR/chromium-profile.tar.gz" "$STATE_DIR/chromium-profile.tar.gz.gpg.tmp"' EXIT
if [ ! -d "$PROFILE_DIR" ]; then
  echo "CODESPACES_PROFILE_DIRECTORY_MISSING"
  exit 1
fi
if [ -z "${CHROMIUM_PROFILE_PASSPHRASE:-}" ]; then
  echo "CODESPACES_PROFILE_PASSPHRASE_REQUIRED"
  exit 1
fi
rm -f "$STATE_DIR/chromium-profile.tar.gz" "$STATE_DIR/chromium-profile.tar.gz.gpg.tmp"
tar -czf "$STATE_DIR/chromium-profile.tar.gz" -C "$PROFILE_DIR" \
  --exclude='SingletonLock' --exclude='SingletonCookie' --exclude='SingletonSocket' .
exec 3<<<"$CHROMIUM_PROFILE_PASSPHRASE"
gpg --batch --yes --pinentry-mode loopback --passphrase-fd 3 --symmetric --cipher-algo AES256 \
  --output "$STATE_DIR/chromium-profile.tar.gz.gpg.tmp" "$STATE_DIR/chromium-profile.tar.gz"
mv "$STATE_DIR/chromium-profile.tar.gz.gpg.tmp" "$ARCHIVE"
rm -f "$STATE_DIR/chromium-profile.tar.gz"
chmod 600 "$ARCHIVE"
rm -rf "$PROFILE_DIR"
echo "CODESPACES_PROFILE=ENCRYPTED_AND_SAVED; PLAINTEXT_RUNTIME_COPY_REMOVED"
