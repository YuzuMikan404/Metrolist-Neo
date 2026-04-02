#!/usr/bin/env bash
# scripts/fetch-source.sh <tag>
#
# 指定タグの upstream Metrolist ソースを取得し、
# このリポジトリ固有のファイル（scripts/, .github/, icon.png）を復元する。
#
# 堅牢化ポイント:
#   - BACKUP_DIR のクリーンアップを trap で保証
#   - upstream remote の重複追加を回避
#   - checkout 失敗時はエラーメッセージを明示して終了
set -euo pipefail

TAG="${1:?Usage: fetch-source.sh <tag>}"

git config user.name  "Action"
git config user.email "action@github.com"

# ── バックアップ（checkout で上書きされる前に保存） ───────────
BACKUP_DIR="$(mktemp -d)"
trap 'rm -rf "$BACKUP_DIR"' EXIT  # 成功・失敗どちらでもクリーンアップ

[ -d scripts ]  && cp -r scripts  "$BACKUP_DIR/"
[ -d .github ]  && cp -r .github  "$BACKUP_DIR/"
[ -f icon.png ] && cp    icon.png "$BACKUP_DIR/"
echo "Backed up repo files to $BACKUP_DIR"

# ── upstream を fetch ─────────────────────────────────────────
if git remote | grep -q '^upstream$'; then
  echo "Remote 'upstream' already exists — skipping add."
else
  git remote add upstream https://github.com/mostafaalagamy/Metrolist.git
fi

git fetch upstream --tags --force

# ── 指定タグを checkout ───────────────────────────────────────
echo "Checking out tag: $TAG"
if ! git checkout "$TAG"; then
  echo "ERROR: Tag '$TAG' not found in upstream." >&2
  exit 1
fi

# ブランチ名が既に存在していても安全に作成
BRANCH="build-$TAG"
if git rev-parse --verify "$BRANCH" &>/dev/null; then
  git branch -D "$BRANCH"
fi
git checkout -b "$BRANCH"

# ── 復元（upstream のファイルを上書き） ───────────────────────
[ -d "$BACKUP_DIR/scripts" ] && cp -r "$BACKUP_DIR/scripts" .
[ -d "$BACKUP_DIR/.github" ] && cp -r "$BACKUP_DIR/.github" .
[ -f "$BACKUP_DIR/icon.png" ] && cp   "$BACKUP_DIR/icon.png" .

echo "Source ready at $TAG"
