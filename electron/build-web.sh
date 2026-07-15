#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"

if ! command -v node &>/dev/null; then
  echo "ERROR: Node.js not found. Install Node.js first." >&2
  exit 1
fi

echo "Using Node: $(node --version)"

# Build backend first
bash "$(dirname "$0")/build-backend.sh"

cd "$root"
npx electron-builder --mac --arm64 --publish never
