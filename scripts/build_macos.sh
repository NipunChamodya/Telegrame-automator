#!/bin/bash
set -euo pipefail
TGM_PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TGM_CONFIGURATION="${1:-Debug}"
case "$TGM_CONFIGURATION" in Debug|Release) ;; *) echo 'Usage: scripts/build_macos.sh [Debug|Release]' >&2; exit 2;; esac
xcodebuild -project "$TGM_PROJECT_ROOT/macos/TelegramManager.xcodeproj" \
  -scheme TelegramManager -configuration "$TGM_CONFIGURATION" \
  -destination 'platform=macOS,arch=arm64' -derivedDataPath "$TGM_PROJECT_ROOT/macos/build" \
  -jobs 2 CODE_SIGNING_ALLOWED=NO CLANG_MODULE_CACHE_PATH="${TMPDIR:-/private/tmp}/tgm-clang-module-cache" build
printf '\nBuilt: %s\n' "$TGM_PROJECT_ROOT/macos/build/Build/Products/$TGM_CONFIGURATION/TelegramManager.app"
