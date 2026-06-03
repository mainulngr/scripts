#!/usr/bin/env bash
# justice install.sh - sync .just/ modules from private GitHub repo via SSH
# Usage: curl -fsSL https://raw.githubusercontent.com/mainulngr/justice/main/install.sh | bash -s <repo>

set -e

REPO="${1:-git@github.com:mainulngr/justice.git}"
TMP=$(mktemp -d)

echo ">>> Syncing .just/ from $REPO..."
git clone --depth=1 --filter=blob:none --sparse "$REPO" "$TMP"
git -C "$TMP" sparse-checkout set .just
mkdir -p .just
rsync -av "$TMP/.just/" .just/
rm -rf "$TMP"
echo "✓ .just/ synced"
