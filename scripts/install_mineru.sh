#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -n "${MINERU_VENV_TARGET:-}" ]]; then
  python3 "${ROOT_DIR}/scripts/rebuild_mineru_venv.py" \
    --target "${MINERU_VENV_TARGET}" \
    --python "${MINERU_PYTHON:-python3}" \
    --mineru-version "${MINERU_VERSION:-3.4.2}" \
    --check-script "${ROOT_DIR}/scripts/check_mineru.py" \
    --keep-backups "${MINERU_KEEP_BACKUPS:-2}"
  exit 0
fi

cd "${ROOT_DIR}/backend/python-worker"

source "${ROOT_DIR}/scripts/ensure_python_worker_venv.sh"

MINERU_WHEELHOUSE="${MINERU_WHEELHOUSE:-${ROOT_DIR}/vendor/mineru-wheelhouse}"
if [[ "${MINERU_WHEELHOUSE}" != /* ]]; then
  MINERU_WHEELHOUSE="${ROOT_DIR}/${MINERU_WHEELHOUSE}"
fi

wheelhouse_available() {
  [[ -d "${MINERU_WHEELHOUSE}" ]] && find "${MINERU_WHEELHOUSE}" -maxdepth 1 -type f \( -name '*.whl' -o -name '*.tar.gz' -o -name '*.zip' \) -print -quit | grep -q .
}

install_mineru_dependencies() {
  ensure_python_worker_venv
  if wheelhouse_available; then
    echo "Installing MinerU from offline wheelhouse: ${MINERU_WHEELHOUSE}"
    uv pip install --python .venv/bin/python --no-index --find-links "${MINERU_WHEELHOUSE}" -e .
    uv pip install --python .venv/bin/python --no-index --find-links "${MINERU_WHEELHOUSE}" "mineru[all]"
  else
    uv pip install --python .venv/bin/python -e .
    uv pip install --python .venv/bin/python -U "mineru[all]"
  fi
}

mineru_dependencies_can_import() {
  .venv/bin/python - <<'PY' >/dev/null 2>&1
import fastapi
import httpx
import uvicorn
import app.ocr_flow
PY
  [[ -x .venv/bin/mineru ]]
}

install_mineru_dependencies
if ! mineru_dependencies_can_import; then
  echo "MinerU or Python worker dependencies are incomplete after install; recreating backend/python-worker/.venv." >&2
  rm -rf .venv
  install_mineru_dependencies
fi

if ! mineru_dependencies_can_import; then
  echo "MinerU dependencies are still incomplete after recreating .venv." >&2
  exit 1
fi

echo "MinerU installed in backend/python-worker/.venv"
echo "Activate it with: source backend/python-worker/.venv/bin/activate"
echo "Verify it with: python scripts/check_mineru.py"
