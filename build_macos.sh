#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

echo
echo " === Balancelab macOS Build ==="
echo

"$PYTHON" -m PyInstaller --clean Balancelab.spec

echo
echo "[DONE] dist/Balancelab"
