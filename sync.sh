#!/usr/bin/env bash
# justice install.sh - sync .just/ modules from private GitHub repo via SSH
# Usage: curl -fsSL https://raw.githubusercontent.com/mainulngr/justice/main/install.sh | bash -s <repo>

set -e

REPO="${1:-git@github.com:mainulngr/justice.git}"
TARGET_DIR="${2:-.}"
TMP=$(mktemp -d)

echo ">>> Syncing .just/ from $REPO to $TARGET_DIR..."
git clone --depth=1 --filter=blob:none --sparse "$REPO" "$TMP"
git -C "$TMP" sparse-checkout set .just
mkdir -p "$TARGET_DIR/.just"
rsync -av "$TMP/.just/" "$TARGET_DIR/.just/"
rm -rf "$TMP"
echo "✓ .just/ synced to $TARGET_DIR"
