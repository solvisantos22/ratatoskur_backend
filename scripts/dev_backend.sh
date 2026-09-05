#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
if [[ ! -x .venv/bin/python ]]; then
  "${PYTHON_BIN:-python3.12}" -m venv .venv
fi
.venv/bin/python -m pip install --quiet --disable-pip-version-check -r backend/requirements.txt
.venv/bin/python scripts/setup_local.py
exec .venv/bin/python -m uvicorn backend.main:app --host "${BACKEND_HOST:-127.0.0.1}" --port "${BACKEND_PORT:-8000}" --env-file backend/.env
