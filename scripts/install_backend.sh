#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../backend/python-worker"

source ../../scripts/ensure_python_worker_venv.sh

install_worker_dependencies() {
  ensure_python_worker_venv
  uv pip install --python .venv/bin/python -e .
}

worker_dependencies_can_import() {
  .venv/bin/python - <<'PY' >/dev/null 2>&1
import fastapi
import httpx
import uvicorn
PY
}

install_worker_dependencies
if ! worker_dependencies_can_import; then
  echo "Python worker dependencies are incomplete after install; recreating backend/python-worker/.venv." >&2
  rm -rf .venv
  install_worker_dependencies
fi

if ! worker_dependencies_can_import; then
  echo "Python worker dependencies are still incomplete after recreating .venv." >&2
  exit 1
fi

echo "Python worker dependencies installed in backend/python-worker/.venv"
