#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"

if ! command -v npx &>/dev/null; then
  echo "ERROR: Node.js/npx not found." >&2
  exit 1
fi

cd "$root"
unset ELECTRON_RUN_AS_NODE
npx electron .
