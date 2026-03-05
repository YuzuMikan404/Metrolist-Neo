#!/usr/bin/env bash
# .github/scripts/check-updates.sh
# Detects whether a new upstream release needs to be built.
# Outputs: trigger (true/false) and tag to GITHUB_OUTPUT.
set -euo pipefail

UPSTREAM_TAG=$(gh api repos/mostafaalagamy/Metrolist/releases/latest --jq .tag_name)
echo "Upstream tag: $UPSTREAM_TAG"

if [ "${GITHUB_EVENT_NAME:-}" = "workflow_dispatch" ]; then
  echo "Manual trigger — force rebuilding $UPSTREAM_TAG"
  gh release delete "$UPSTREAM_TAG" --yes --cleanup-tag || true
  git push --delete origin "$UPSTREAM_TAG" || true
  echo "trigger=true" >> "$GITHUB_OUTPUT"
  echo "tag=$UPSTREAM_TAG" >> "$GITHUB_OUTPUT"
elif [ -z "$(git ls-remote --tags origin "refs/tags/$UPSTREAM_TAG")" ]; then
  echo "New version detected: $UPSTREAM_TAG"
  echo "trigger=true"  >> "$GITHUB_OUTPUT"
  echo "tag=$UPSTREAM_TAG" >> "$GITHUB_OUTPUT"
else
  echo "Already built: $UPSTREAM_TAG — skipping."
  echo "trigger=false" >> "$GITHUB_OUTPUT"
fi

