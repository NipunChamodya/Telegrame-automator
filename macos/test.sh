#!/bin/bash
set -euo pipefail
TGM_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
xcodebuild -project "$TGM_ROOT/macos/TelegramManager.xcodeproj" -scheme TelegramManager \
  -configuration Debug -destination 'platform=macOS,arch=arm64' -derivedDataPath "$TGM_ROOT/macos/build" \
  -jobs 2 CODE_SIGNING_ALLOWED=YES CODE_SIGN_IDENTITY=- CODE_SIGN_STYLE=Manual DEVELOPMENT_TEAM= CLANG_MODULE_CACHE_PATH="${TMPDIR:-/private/tmp}/tgm-clang-module-cache" build-for-testing
# Direct XCTest avoids dependency on testmanagerd (restricted in some CI sandboxes).
# Unit tests use synthetic Python child processes and never authenticate Telegram.
TGM_TEST_MODE=1 TGM_NO_AUTO_CONNECT=1 TGM_DATA_DIR="${TMPDIR:-/private/tmp}/tgm-swift-test-storage" \
  xcrun xctest "$TGM_ROOT/macos/build/Build/Products/Debug/TelegramManager.app/Contents/PlugIns/TelegramManagerTests.xctest"
