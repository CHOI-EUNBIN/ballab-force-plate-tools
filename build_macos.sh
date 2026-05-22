#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

echo
echo " === BALLAB macOS Build ==="
echo

"$PYTHON" -m PyInstaller --clean BALLAB.spec

echo
echo "[DONE] dist/BALLAB"
