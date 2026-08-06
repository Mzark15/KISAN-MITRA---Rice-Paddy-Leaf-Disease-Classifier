#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
elif [ -f .env.example ]; then
  echo "No .env found — copy .env.example to .env and add your API keys"
fi

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -q -r requirements.txt

# Optional: local MLX STT on Apple Silicon (replaces Bhashini for voice)
if [[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]]; then
  pip install -q -r requirements-mlx.txt 2>/dev/null || echo "Note: mlx-audio not installed — voice will use Bhashini or browser fallback"
fi

echo "Starting Kisan Mitra at http://localhost:8000"
cd backend && python main.py
