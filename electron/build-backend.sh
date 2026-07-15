#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"

python_candidates=(
  "${PETRELHACKER_PYTHON:-}"
  "$root/.venv/bin/python"
  "$root/../.venv/bin/python"
  "python3"
)

python_exe=""
for candidate in "${python_candidates[@]}"; do
  [ -z "$candidate" ] && continue
  if [ "$candidate" = "python3" ] && command -v python3 &>/dev/null; then
    python_exe="python3"
    break
  elif [ -x "$candidate" ]; then
    python_exe="$candidate"
    break
  fi
done

if [ -z "$python_exe" ]; then
  echo "ERROR: Python not found. Set PETRELHACKER_PYTHON or create .venv." >&2
  exit 1
fi

echo "Using Python: $python_exe"

build_root="$root/build-electron"
backend_dist="$build_root/backend"
backend_work="$build_root/pyinstaller-work"

mkdir -p "$build_root" "$backend_dist" "$backend_work"

# Clean previous build
rm -rf "$backend_dist/petrelhacker-backend" "$backend_work/petrelhacker-backend"

cd "$root"
"$python_exe" -m PyInstaller \
  --noconfirm \
  --clean \
  --name petrelhacker-backend \
  --distpath "$backend_dist" \
  --workpath "$backend_work" \
  --specpath "$build_root" \
  --exclude-module PySide6 \
  --exclude-module matplotlib \
  --exclude-module scipy \
  --exclude-module numba \
  --exclude-module IPython \
  --exclude-module jedi \
  --exclude-module PIL \
  --exclude-module tkinter \
  --exclude-module zmq \
  --exclude-module pytest \
  web_backend/cli.py

backend_bin="$backend_dist/petrelhacker-backend/petrelhacker-backend"
if [ ! -x "$backend_bin" ]; then
  echo "ERROR: Backend binary not found: $backend_bin" >&2
  exit 1
fi

echo "Backend binary: $backend_bin"
