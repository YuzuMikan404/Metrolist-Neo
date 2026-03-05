#!/usr/bin/env bash
# .github/scripts/fetch-source.sh <tag>
# Fetches the upstream Metrolist source at the given tag,
# then restores the custom icon.png from this repo if present.
set -euo pipefail

TAG="${1:?Usage: fetch-source.sh <tag>}"

git config user.name  "Action"
git config user.email "action@github.com"

# ── Backup our own files before switching to upstream tree ────
# git checkout replaces the working tree with upstream's content,
# so scripts/ and .github/ would be lost without this step.
BACKUP_DIR="$(mktemp -d)"
[ -d scripts ]  && cp -r scripts  "$BACKUP_DIR/"
[ -d .github ]  && cp -r .github  "$BACKUP_DIR/"
[ -f icon.png ] && cp    icon.png "$BACKUP_DIR/"
echo "Backed up repo files to $BACKUP_DIR"

# ── Fetch & checkout upstream source ─────────────────────────
git remote add upstream https://github.com/mostafaalagamy/Metrolist.git
git fetch upstream --tags --force

echo "Checking out tag: $TAG"
git checkout "$TAG"
git checkout -b "build-$TAG"

# ── Restore our files (overwrite anything upstream ships) ─────
[ -d "$BACKUP_DIR/scripts" ] && cp -r "$BACKUP_DIR/scripts" .
[ -d "$BACKUP_DIR/.github" ] && cp -r "$BACKUP_DIR/.github" .
[ -f "$BACKUP_DIR/icon.png" ] && cp   "$BACKUP_DIR/icon.png" .
rm -rf "$BACKUP_DIR"

echo "Source ready at $TAG"
