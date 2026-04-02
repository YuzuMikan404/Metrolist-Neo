#!/usr/bin/env bash
# scripts/check-updates.sh
#
# 新しい upstream リリースをビルドすべきか判定する。
# 出力: GITHUB_OUTPUT に trigger (true/false) と tag を書き込む。
#
# 堅牢化ポイント:
#   - upstream API 失敗時は trigger=false で安全に終了
#   - 手動トリガーでのリリース/タグ削除は失敗してもワークフローを止めない
#   - GITHUB_OUTPUT が未設定の場合でもエラーにならないよう保護
set -euo pipefail

GITHUB_OUTPUT="${GITHUB_OUTPUT:-/dev/null}"

# upstream の最新リリースタグを取得
UPSTREAM_TAG="$(gh api repos/mostafaalagamy/Metrolist/releases/latest --jq .tag_name 2>/dev/null || true)"

if [ -z "${UPSTREAM_TAG:-}" ]; then
  echo "ERROR: Failed to fetch upstream tag. Skipping build." >&2
  echo "trigger=false" >> "$GITHUB_OUTPUT"
  exit 0
fi

echo "Upstream tag: $UPSTREAM_TAG"

if [ "${GITHUB_EVENT_NAME:-}" = "workflow_dispatch" ]; then
  echo "Manual trigger — force rebuilding $UPSTREAM_TAG"

  # 既存リリースとタグを削除（失敗しても続行）
  gh release delete "$UPSTREAM_TAG" --yes --cleanup-tag 2>/dev/null || true
  git push --delete origin "$UPSTREAM_TAG" 2>/dev/null || true

  echo "trigger=true"  >> "$GITHUB_OUTPUT"
  echo "tag=$UPSTREAM_TAG" >> "$GITHUB_OUTPUT"

elif [ -z "$(git ls-remote --tags origin "refs/tags/$UPSTREAM_TAG" 2>/dev/null)" ]; then
  echo "New version detected: $UPSTREAM_TAG"
  echo "trigger=true"  >> "$GITHUB_OUTPUT"
  echo "tag=$UPSTREAM_TAG" >> "$GITHUB_OUTPUT"

else
  echo "Already built: $UPSTREAM_TAG — skipping."
  echo "trigger=false" >> "$GITHUB_OUTPUT"
fi
