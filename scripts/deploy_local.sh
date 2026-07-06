#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="${ROOT_DIR}/.run"
LOG_DIR="${RUN_DIR}/logs"
PID_DIR="${RUN_DIR}/pids"
DEPLOY_ENV="${RUN_DIR}/deploy.env"

WITH_MINERU="false"
WITH_AI="false"
STRICT_PORTS="false"
DEV_RELOAD="${DEV_RELOAD:-false}"
SKIP_SMOKE="${SKIP_SMOKE:-false}"
AUTO_PORT="${AUTO_PORT:-true}"

usage() {
  cat <<'USAGE'
Usage: ./scripts/deploy_local.sh [options]

Options:
  --with-mineru    Install/check MinerU and run OCR smoke.
  --with-ai        Require LLM API key and run AI smoke.
  --strict-ports   Fail if configured ports are occupied by another project.
  --dev-reload     Start Python worker with uvicorn --reload.
  --skip-smoke     Start services without running smoke checks.
  -h, --help       Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-mineru)
      WITH_MINERU="true"
      ;;
    --with-ai)
      WITH_AI="true"
      ;;
    --strict-ports)
      STRICT_PORTS="true"
      AUTO_PORT="false"
      ;;
    --dev-reload)
      DEV_RELOAD="true"
      ;;
    --skip-smoke)
      SKIP_SMOKE="true"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

mkdir -p "${LOG_DIR}" "${PID_DIR}"

PROJECT_SLUG="$(basename "${ROOT_DIR}" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '_' | sed 's/_$//')"
PROJECT_SLUG="${PROJECT_SLUG:-ai_generation}"
SCREEN_PREFIX="ai_${PROJECT_SLUG}"

source_env_file() {
  if [[ -f "${ROOT_DIR}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${ROOT_DIR}/.env"
    set +a
  fi
}

source_env_file

PYTHON_WORKER_PORT="${PYTHON_WORKER_PORT:-8000}"
JAVA_BACKEND_PORT="${JAVA_BACKEND_PORT:-8018}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

FRONTEND_AVAILABLE="false"
if [[ -f "${ROOT_DIR}/local-platform/package.json" ]]; then
  FRONTEND_AVAILABLE="true"
fi

require_command() {
  local command_name="$1"
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Missing required command: ${command_name}" >&2
    exit 1
  fi
}

pids_on_port() {
  local port="$1"
  lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true
}

port_is_free() {
  [[ -z "$(pids_on_port "$1")" ]]
}

pid_command() {
  ps -p "$1" -o command= 2>/dev/null || true
}

pid_belongs_to_project() {
  local pid="$1"
  local command
  command="$(pid_command "${pid}")"
  [[ "${command}" == *"${ROOT_DIR}"* ]]
}

stop_pid() {
  local pid="$1"
  if ! kill -0 "${pid}" 2>/dev/null; then
    return
  fi
  kill "${pid}" 2>/dev/null || true
  for _ in $(seq 1 30); do
    if ! kill -0 "${pid}" 2>/dev/null; then
      return
    fi
    sleep 0.2
  done
  kill -9 "${pid}" 2>/dev/null || true
}

stop_pid_file() {
  local service="$1"
  local file="${PID_DIR}/${service}.pid"
  if [[ ! -f "${file}" ]]; then
    return
  fi
  local pid
  pid="$(cat "${file}" 2>/dev/null || true)"
  if [[ -n "${pid}" ]]; then
    stop_pid "${pid}"
  fi
  rm -f "${file}"
}

stop_screen_session() {
  local service="$1"
  local session="${SCREEN_PREFIX}_${service//-/_}"
  if command -v screen >/dev/null 2>&1 && screen -ls | grep -q "[.]${session}[[:space:]]"; then
    screen -S "${session}" -X quit || true
  fi
}

stop_current_project_pids() {
  stop_screen_session "frontend"
  stop_screen_session "java-backend"
  stop_screen_session "python-worker"
  stop_pid_file "frontend"
  stop_pid_file "java-backend"
  stop_pid_file "python-worker"
}

stop_project_pids_on_port() {
  local port="$1"
  local pids
  pids="$(pids_on_port "${port}")"
  [[ -n "${pids}" ]] || return 0
  while IFS= read -r pid; do
    [[ -z "${pid}" ]] && continue
    if pid_belongs_to_project "${pid}"; then
      stop_pid "${pid}"
    fi
  done <<< "${pids}"
}

all_port_pids_belong_to_project() {
  local port="$1"
  local pids
  pids="$(pids_on_port "${port}")"
  [[ -n "${pids}" ]] || return 1
  while IFS= read -r pid; do
    [[ -z "${pid}" ]] && continue
    pid_belongs_to_project "${pid}" || return 1
  done <<< "${pids}"
  return 0
}

find_free_port() {
  local start_port="$1"
  local port="${start_port}"
  while [[ "${port}" -le 65535 ]]; do
    if port_is_free "${port}"; then
      echo "${port}"
      return 0
    fi
    port=$((port + 1))
  done
  return 1
}

resolve_port() {
  local label="$1"
  local requested="$2"
  if port_is_free "${requested}"; then
    echo "${requested}"
    return
  fi

  if all_port_pids_belong_to_project "${requested}"; then
    echo "Port ${requested} for ${label} is used by this project; restarting it." >&2
    stop_project_pids_on_port "${requested}"
    sleep 1
    echo "${requested}"
    return
  fi

  if [[ "${STRICT_PORTS}" == "true" || "${AUTO_PORT}" == "false" ]]; then
    echo "Port ${requested} for ${label} is occupied by another process:" >&2
    lsof -nP -iTCP:"${requested}" -sTCP:LISTEN >&2 || true
    exit 1
  fi

  local next_port
  next_port="$(find_free_port "$((requested + 1))")"
  if [[ -z "${next_port}" ]]; then
    echo "No free port found for ${label} after ${requested}." >&2
    exit 1
  fi
  echo "Port ${requested} for ${label} is occupied by another project; using ${next_port}." >&2
  echo "${next_port}"
}

worker_base_deps_ok() {
  local python_bin="${ROOT_DIR}/backend/python-worker/.venv/bin/python"
  [[ -x "${python_bin}" ]] || return 1
  "${python_bin}" - <<'PY' >/dev/null 2>&1
import fastapi
import uvicorn
PY
}

frontend_deps_ok() {
  [[ "${FRONTEND_AVAILABLE}" != "true" ]] || [[ -d "${ROOT_DIR}/local-platform/node_modules" ]]
}

mineru_ok() {
  python "${ROOT_DIR}/scripts/check_mineru.py" >/dev/null 2>&1
}

ai_key_configured() {
  [[ -n "${DASHSCOPE_API_KEY:-}" || -n "${ALIYUN_LLM_API_KEY:-}" ]]
}

install_dependencies() {
  if ! worker_base_deps_ok; then
    require_command uv
    echo "Installing Python worker dependencies..."
    (cd "${ROOT_DIR}" && ./scripts/install_backend.sh)
  fi

  if [[ "${WITH_MINERU}" == "true" ]] && ! mineru_ok; then
    require_command uv
    echo "Installing MinerU dependencies..."
    (cd "${ROOT_DIR}" && ./scripts/install_mineru.sh)
  fi

  if ! frontend_deps_ok; then
    require_command npm
    echo "Installing frontend dependencies..."
    (cd "${ROOT_DIR}" && ./scripts/install_frontend.sh)
  fi

  if [[ "${WITH_AI}" == "true" ]] && ! ai_key_configured; then
    echo "--with-ai requires DASHSCOPE_API_KEY or ALIYUN_LLM_API_KEY in the environment or .env." >&2
    exit 1
  fi
}

tail_log() {
  local service="$1"
  local log_file="${LOG_DIR}/${service}.log"
  if [[ -f "${log_file}" ]]; then
    echo "---- ${log_file} (last 80 lines) ----" >&2
    tail -n 80 "${log_file}" >&2 || true
  fi
}

fail_with_logs() {
  local message="$1"
  echo "${message}" >&2
  tail_log "python-worker"
  tail_log "java-backend"
  tail_log "frontend"
  exit 1
}

wait_for_url() {
  local label="$1"
  local url="$2"
  local timeout_seconds="${3:-90}"
  local deadline=$((SECONDS + timeout_seconds))
  while [[ "${SECONDS}" -lt "${deadline}" ]]; do
    if curl -fsS "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  fail_with_logs "Timed out waiting for ${label}: ${url}"
}

wait_for_worker_bridge() {
  local url="$1"
  local deadline=$((SECONDS + 90))
  while [[ "${SECONDS}" -lt "${deadline}" ]]; do
    if curl -fsS "${url}" 2>/dev/null | grep -q '"reachable"[[:space:]]*:[[:space:]]*true'; then
      return 0
    fi
    sleep 2
  done
  fail_with_logs "Timed out waiting for Java worker bridge: ${url}"
}

start_python_worker() {
  local log_file="${LOG_DIR}/python-worker.log"
  local command_file="${RUN_DIR}/python-worker.sh"
  : > "${log_file}"
  cat > "${command_file}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
echo \$\$ > "${PID_DIR}/python-worker.pid"
cd "${ROOT_DIR}"
if [[ -f "${ROOT_DIR}/.env" ]]; then set -a; source "${ROOT_DIR}/.env"; set +a; fi
args=(backend/python-worker/.venv/bin/python -m uvicorn app.main:app --app-dir backend/python-worker --host 127.0.0.1 --port "${PYTHON_WORKER_PORT}")
if [[ "${DEV_RELOAD}" == "true" ]]; then
  args+=(--reload --reload-dir backend/python-worker/app --reload-include '*.py')
fi
exec "\${args[@]}" >> "${log_file}" 2>&1
EOF
  chmod +x "${command_file}"
  start_detached "python-worker" "${command_file}"
}

start_java_backend() {
  local log_file="${LOG_DIR}/java-backend.log"
  local command_file="${RUN_DIR}/java-backend.sh"
  : > "${log_file}"
  cat > "${command_file}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
echo \$\$ > "${PID_DIR}/java-backend.pid"
cd "${ROOT_DIR}"
if [[ -f "${ROOT_DIR}/.env" ]]; then set -a; source "${ROOT_DIR}/.env"; set +a; fi
export JAVA_BACKEND_PORT="${JAVA_BACKEND_PORT}"
export SERVER_PORT="${JAVA_BACKEND_PORT}"
export PYTHON_WORKER_BASE_URL="${PYTHON_WORKER_URL}"
exec ./scripts/start_java_backend.sh >> "${log_file}" 2>&1
EOF
  chmod +x "${command_file}"
  start_detached "java-backend" "${command_file}"
}

start_frontend() {
  local log_file="${LOG_DIR}/frontend.log"
  local command_file="${RUN_DIR}/frontend.sh"
  : > "${log_file}"
  cat > "${command_file}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
echo \$\$ > "${PID_DIR}/frontend.pid"
cd "${ROOT_DIR}/local-platform"
if [[ -f "${ROOT_DIR}/.env" ]]; then set -a; source "${ROOT_DIR}/.env"; set +a; fi
export VITE_API_BASE="${JAVA_BACKEND_URL}"
export VITE_API_BASE_URL="${JAVA_BACKEND_URL}"
exec npm run dev -- --host 0.0.0.0 --port "${FRONTEND_PORT}" --strictPort >> "${log_file}" 2>&1
EOF
  chmod +x "${command_file}"
  start_detached "frontend" "${command_file}"
}

start_detached() {
  local service="$1"
  local command_file="$2"
  local session="${SCREEN_PREFIX}_${service//-/_}"
  if command -v screen >/dev/null 2>&1; then
    stop_screen_session "${service}"
    screen -dmS "${session}" bash "${command_file}"
  else
    nohup bash "${command_file}" >/dev/null 2>&1 &
  fi
}

write_deploy_env() {
  {
    echo "PROJECT_SLUG=${PROJECT_SLUG}"
    echo "SCREEN_PREFIX=${SCREEN_PREFIX}"
    echo "PYTHON_WORKER_PORT=${PYTHON_WORKER_PORT}"
    echo "JAVA_BACKEND_PORT=${JAVA_BACKEND_PORT}"
    if [[ "${FRONTEND_AVAILABLE}" == "true" ]]; then
      echo "FRONTEND_PORT=${FRONTEND_PORT}"
    fi
    echo "PYTHON_WORKER_URL=${PYTHON_WORKER_URL}"
    echo "JAVA_BACKEND_URL=${JAVA_BACKEND_URL}"
    if [[ "${FRONTEND_AVAILABLE}" == "true" ]]; then
      echo "FRONTEND_URL=${FRONTEND_URL}"
    fi
    echo "WITH_MINERU=${WITH_MINERU}"
    echo "WITH_AI=${WITH_AI}"
    echo "DEV_RELOAD=${DEV_RELOAD}"
  } > "${DEPLOY_ENV}"
}

run_smoke_checks() {
  if [[ "${SKIP_SMOKE}" == "true" ]]; then
    return
  fi
  echo "Running basic deployment smoke..."
  AI_GENERATION_BASE_URL="${JAVA_BACKEND_URL}" \
  AI_GENERATION_FRONTEND_URL="${FRONTEND_URL:-}" \
  PYTHON_WORKER_URL="${PYTHON_WORKER_URL}" \
    python "${ROOT_DIR}/scripts/smoke_deploy_basic.py"

  if [[ "${WITH_MINERU}" == "true" ]]; then
    echo "Running OCR smoke..."
    AI_GENERATION_BASE_URL="${JAVA_BACKEND_URL}" \
      python "${ROOT_DIR}/scripts/smoke_ocr.py"
  fi

  if [[ "${WITH_AI}" == "true" ]]; then
    echo "Running AI smoke..."
    AI_GENERATION_BASE_URL="${JAVA_BACKEND_URL}" \
      python "${ROOT_DIR}/scripts/smoke_ai.py"
  fi
}

require_command lsof
require_command curl
require_command python
require_command mvn
if [[ "${FRONTEND_AVAILABLE}" == "true" ]]; then
  require_command npm
fi

install_dependencies

stop_current_project_pids

PYTHON_WORKER_PORT="$(resolve_port "Python worker" "${PYTHON_WORKER_PORT}")"
JAVA_BACKEND_PORT="$(resolve_port "Java backend" "${JAVA_BACKEND_PORT}")"
if [[ "${FRONTEND_AVAILABLE}" == "true" ]]; then
  FRONTEND_PORT="$(resolve_port "frontend" "${FRONTEND_PORT}")"
fi

PYTHON_WORKER_URL="http://127.0.0.1:${PYTHON_WORKER_PORT}"
JAVA_BACKEND_URL="http://localhost:${JAVA_BACKEND_PORT}"
if [[ "${FRONTEND_AVAILABLE}" == "true" ]]; then
  FRONTEND_URL="http://localhost:${FRONTEND_PORT}"
fi

write_deploy_env

start_python_worker
wait_for_url "Python worker" "${PYTHON_WORKER_URL}/api/health" 90

start_java_backend
wait_for_url "Java backend" "${JAVA_BACKEND_URL}/actuator/health" 120
wait_for_worker_bridge "${JAVA_BACKEND_URL}/api/java/worker"

if [[ "${FRONTEND_AVAILABLE}" == "true" ]]; then
  start_frontend
  wait_for_url "frontend" "${FRONTEND_URL}/" 90
fi

run_smoke_checks

echo
echo "Deploy OK"
echo
if [[ "${FRONTEND_AVAILABLE}" == "true" ]]; then
  printf "Frontend:      %s\n" "${FRONTEND_URL}"
else
  printf "Frontend:      skipped, local-platform is not included\n"
fi
printf "Java backend:  %s\n" "${JAVA_BACKEND_URL}"
printf "Python worker: %s\n" "${PYTHON_WORKER_URL}"
echo
echo "Checks:"
echo "- frontend: $([[ "${FRONTEND_AVAILABLE}" == "true" ]] && echo ok || echo skipped)"
echo "- java health: ok"
echo "- worker reachable: ok"
echo "- OCR provider: $([[ "${WITH_MINERU}" == "true" ]] && echo ok || echo skipped)"
echo "- AI: $([[ "${WITH_AI}" == "true" ]] && echo ok || echo skipped)"
if [[ "${WITH_MINERU}" != "true" ]]; then
  echo
  echo "OCR imports for PDF/image/Office files require: ./scripts/deploy_local.sh --with-mineru"
fi
echo
echo "Logs: ${LOG_DIR}"
echo "Runtime env: ${DEPLOY_ENV}"
