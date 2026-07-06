#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${ROOT_DIR}/backend/python-worker/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "backend/python-worker/.venv is missing or not usable." >&2
  echo "Run ./scripts/install_backend.sh, or ./scripts/install_mineru.sh if OCR via MinerU is required." >&2
  exit 1
fi

cd "${ROOT_DIR}"
PYTHONPATH="${ROOT_DIR}/backend/python-worker${PYTHONPATH:+:${PYTHONPATH}}" \
  "${PYTHON_BIN}" -m unittest discover -s backend/python-worker/tests
