#!/usr/bin/env bash
# .github/scripts/collect-apks.sh
# Copies all built APKs into output_apks/ with clean filenames.
set -euo pipefail

mkdir -p output_apks

find app/build/outputs/apk -name "*.apk" -type f | while read -r apk; do
  filename=$(basename "$apk")
  newname=$(echo "$filename" \
    | sed -e 's/^app/Metrolist-Neo/' \
          -e 's/-unsigned//' \
          -e 's/-release//')
  cp "$apk" "output_apks/$newname"
  echo "Collected: $newname"
done

echo "--- output_apks/ ---"
ls -lh output_apks/

