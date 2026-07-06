#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -q -r requirements.txt 2>/dev/null || {
  pip install -q fastapi "uvicorn[standard]" pillow numpy python-multipart
  pip install -q tensorflow
}

echo "Starting Kisan Mitra at http://localhost:8000"
cd backend && python main.py
