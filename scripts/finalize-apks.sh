#!/usr/bin/env bash
# scripts/finalize-apks.sh
#
# 署名済み APK のリネームと一時ファイルの削除を行う。
# sign-android-release アクションは *-signed.apk を生成するので、
# -signed サフィックスを除去して最終的なファイル名にする。
set -euo pipefail

TARGET_DIR="${1:-output_apks}"
cd "$TARGET_DIR"

renamed=0
for f in *-signed.apk; do
  [ -e "$f" ] || continue
  dest="${f/-signed/}"
  mv "$f" "$dest"
  echo "Renamed: $f → $dest"
  renamed=$((renamed + 1))
done

# 未署名・一時ファイルを削除
rm -f *-unsigned.apk *-temp.apk

if [ "$renamed" -eq 0 ]; then
  echo "WARNING: No *-signed.apk files found. Check signing step output." >&2
fi

echo ""
echo "--- final $TARGET_DIR/ ---"
ls -lh
