#!/usr/bin/env bash
# scripts/collect-apks.sh
#
# ビルド成果物の APK を output_apks/ にコピーし、わかりやすい名前に整理する。
#
# 対応フレーバー: gms / foss
# 例: app-gms-release-unsigned.apk → Metrolist-Neo-gms.apk
#     app-foss-release-unsigned.apk → Metrolist-Neo-foss.apk
set -euo pipefail

mkdir -p output_apks

found=0
while IFS= read -r apk; do
  filename="$(basename "$apk")"

  # フレーバーを抽出（gms / foss / その他）
  if [[ "$filename" == *gms* ]]; then
    flavor="gms"
  elif [[ "$filename" == *foss* ]]; then
    flavor="foss"
  else
    flavor="release"
  fi

  newname="Metrolist-Neo-${flavor}.apk"
  cp "$apk" "output_apks/$newname"
  echo "Collected: $newname  ← $apk"
  found=$((found + 1))
done < <(find app/build/outputs/apk -name "*.apk" -type f | sort)

if [ "$found" -eq 0 ]; then
  echo "ERROR: No APK files found under app/build/outputs/apk/" >&2
  exit 1
fi

echo ""
echo "--- output_apks/ ---"
ls -lh output_apks/
