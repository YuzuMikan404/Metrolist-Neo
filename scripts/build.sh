#!/usr/bin/env bash
# .github/scripts/build.sh
# Runs the Gradle release build.
#
# --no-build-cache  Prevents stale cached outputs (e.g. old protobuf-generated
#                   sources) from being used.  generateProto and all other tasks
#                   always run fresh.
set -euo pipefail

chmod +x gradlew

echo "Starting Gradle build..."
./gradlew clean assembleRelease \
  --no-configuration-cache \
  --no-build-cache \
  --stacktrace \
  --no-daemon \
  --warning-mode all

