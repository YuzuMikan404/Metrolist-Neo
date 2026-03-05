#!/usr/bin/env bash
# .github/scripts/finalize-apks.sh
# Renames *-signed.apk → *.apk and removes temp files.
set -euo pipefail

cd output_apks

for f in *-signed.apk; do
  [ -e "$f" ] || continue
  mv "$f" "${f/-signed/}"
  echo "Renamed: ${f/-signed/}"
done

rm -f *-temp.apk

echo "--- final output_apks/ ---"
ls -lh

