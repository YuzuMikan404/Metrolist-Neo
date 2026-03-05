#!/usr/bin/env bash
# .github/scripts/fetch-source.sh <tag>
# Fetches the upstream Metrolist source at the given tag,
# then restores the custom icon.png from this repo if present.
set -euo pipefail

TAG="${1:?Usage: fetch-source.sh <tag>}"

git config user.name  "Action"
git config user.email "action@github.com"

# Keep our custom icon across the branch switch
if [ -f icon.png ]; then cp icon.png /tmp/icon.png; fi

git remote add upstream https://github.com/mostafaalagamy/Metrolist.git
git fetch upstream --tags --force

echo "Checking out tag: $TAG"
git checkout "$TAG"
git checkout -b "build-$TAG"

# Restore custom icon (overwrites whatever upstream ships)
if [ -f /tmp/icon.png ]; then mv /tmp/icon.png icon.png; fi

echo "Source ready at $TAG"

