#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_WORKER_DIR="${ROOT_DIR}/backend/python-worker"
PYTHON_WORKER_VENV="${PYTHON_WORKER_DIR}/.venv"

python_worker_venv_python() {
  printf "%s/bin/python" "${PYTHON_WORKER_VENV}"
}

python_worker_venv_can_run() {
  local python_bin
  python_bin="$(python_worker_venv_python)"
  [[ -x "${python_bin}" ]] || return 1
  "${python_bin}" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
}

python_worker_console_script_has_valid_shebang() {
  local script="$1"
  [[ -f "${script}" ]] || return 0

  local first_line interpreter
  IFS= read -r first_line < "${script}" || return 0
  [[ "${first_line}" == '#!'* ]] || return 0

  interpreter="${first_line#\#!}"
  interpreter="${interpreter%% *}"
  [[ "${interpreter}" == "/usr/bin/env" ]] && return 0
  [[ -x "${interpreter}" ]]
}

python_worker_venv_console_scripts_are_valid() {
  local script_name
  for script_name in uvicorn mineru mineru-api; do
    python_worker_console_script_has_valid_shebang "${PYTHON_WORKER_VENV}/bin/${script_name}" || return 1
  done
}

python_worker_venv_is_usable() {
  python_worker_venv_can_run && python_worker_venv_console_scripts_are_valid
}

ensure_python_worker_venv() {
  cd "${PYTHON_WORKER_DIR}"

  if [[ -d "${PYTHON_WORKER_VENV}" ]] && ! python_worker_venv_is_usable; then
    echo "Detected unusable backend/python-worker/.venv; recreating it for this machine." >&2
    rm -rf "${PYTHON_WORKER_VENV}"
  fi

  uv venv --allow-existing
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  ensure_python_worker_venv
fi
