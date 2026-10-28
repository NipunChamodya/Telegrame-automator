#!/bin/bash
set -euo pipefail
TGM_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$TGM_ROOT/scripts/build_macos.sh" "${1:-Debug}"
