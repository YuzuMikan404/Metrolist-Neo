#!/usr/bin/env bash
# scripts/build.sh
#
# Gradle リリースビルドを実行する。
#
# フレーバー対応:
#   upstream Metrolist は gms / foss の 2 フレーバーを持つ。
#   assembleRelease だけでは両方ビルドされるが、GMS フレーバーは
#   google-services.json が不要な構成になっている (v13.2.1+)。
#
# オプション:
#   --no-build-cache  キャッシュ起因のビルド汚染を防ぐ
#   --stacktrace      エラー時のスタックトレース出力
#   --no-daemon       CI では毎回クリーンなデーモンで動かす
set -euo pipefail

chmod +x gradlew

echo "Starting Gradle build..."
./gradlew \
  clean \
  assembleGmsRelease \
  assembleFossRelease \
  --no-configuration-cache \
  --no-build-cache \
  --stacktrace \
  --no-daemon \
  --warning-mode all 2>&1 | tee build_output.log

echo "Build complete."
