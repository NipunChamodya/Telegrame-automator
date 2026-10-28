#!/bin/bash
set -euo pipefail
TGM_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TGM_STYLE="${1:-light}"
case "$TGM_STYLE" in light|dark) ;; *) echo 'Usage: macos/screenshots.sh [light|dark]' >&2; exit 2;; esac
TGM_SIZE="${2:-standard}"
case "$TGM_SIZE" in compact|standard|large) ;; *) echo "Choose compact, standard, or large" >&2; exit 2;; esac
TGM_RESULT="$TGM_ROOT/macos/build/UI-$TGM_STYLE-$(date +%Y%m%d-%H%M%S).xcresult"
TGM_SCREENSHOT_APPEARANCE="$TGM_STYLE" TGM_TEST_MODE=1 TGM_NO_AUTO_CONNECT=1 \
xcodebuild -project "$TGM_ROOT/macos/TelegramManager.xcodeproj" -scheme TelegramManager \
 -configuration Debug -destination 'platform=macOS,arch=arm64' -derivedDataPath "$TGM_ROOT/macos/build" \
 -only-testing:TelegramManagerUITests -resultBundlePath "$TGM_RESULT" -jobs 2 \
 TGM_SCREENSHOT_SIZE="$TGM_SIZE" TGM_SCREENSHOT_APPEARANCE="$TGM_STYLE" CODE_SIGNING_ALLOWED=YES CODE_SIGN_IDENTITY=- CODE_SIGN_STYLE=Manual DEVELOPMENT_TEAM= \
 CLANG_MODULE_CACHE_PATH="${TMPDIR:-/private/tmp}/tgm-clang-module-cache" test
mkdir -p "$TGM_ROOT/docs/assets/screenshots/$TGM_STYLE/$TGM_SIZE"
xcrun xcresulttool export attachments --path "$TGM_RESULT" --output-path "$TGM_ROOT/docs/assets/screenshots/$TGM_STYLE/$TGM_SIZE"
printf 'Real XCTest screenshot attachments exported to docs/assets/screenshots/%s/%s\n' "$TGM_STYLE" "$TGM_SIZE"
