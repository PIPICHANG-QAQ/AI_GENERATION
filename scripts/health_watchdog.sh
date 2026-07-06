#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="${ROOT_DIR}/.run"
PID_DIR="${RUN_DIR}/pids"
LOG_DIR="${RUN_DIR}/logs"
DEPLOY_ENV="${RUN_DIR}/deploy.env"

INTERVAL_SECONDS="${WATCHDOG_INTERVAL_SECONDS:-30}"
ONCE="false"
RESTART="false"
WITH_MINERU="false"
WITH_AI="false"

usage() {
  cat <<'USAGE'
Usage: ./scripts/health_watchdog.sh [options]

Options:
  --once          Run one health check and exit.
  --interval N    Seconds between checks in watch mode. Default: 30.
  --restart       Restart the local deployment when a check fails.
  --with-mineru   Include OCR runtime readiness in the check/restart flags.
  --with-ai       Preserve --with-ai when restarting.
  -h, --help      Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --once)
      ONCE="true"
      ;;
    --interval)
      shift
      INTERVAL_SECONDS="${1:-30}"
      ;;
    --restart)
      RESTART="true"
      ;;
    --with-mineru)
      WITH_MINERU="true"
      ;;
    --with-ai)
      WITH_AI="true"
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

load_runtime_env() {
  if [[ ! -f "${DEPLOY_ENV}" ]]; then
    echo "Missing ${DEPLOY_ENV}; run ./scripts/deploy_local.sh first." >&2
    return 1
  fi
  set -a
  # shellcheck disable=SC1090
  source "${DEPLOY_ENV}"
  set +a
}

pid_ok() {
  local service="$1"
  local file="${PID_DIR}/${service}.pid"
  if [[ ! -f "${file}" ]]; then
    echo "FAIL ${service} pid file missing: ${file}" >&2
    return 1
  fi
  local pid
  pid="$(cat "${file}" 2>/dev/null || true)"
  if [[ -z "${pid}" ]] || ! kill -0 "${pid}" 2>/dev/null; then
    echo "FAIL ${service} process not running: ${pid:-empty}" >&2
    return 1
  fi
  echo "OK ${service} pid ${pid}"
}

url_ok() {
  local label="$1"
  local url="$2"
  if curl -fsS --max-time 10 "${url}" >/dev/null 2>&1; then
    echo "OK ${label} ${url}"
    return 0
  fi
  echo "FAIL ${label} ${url}" >&2
  return 1
}

json_contains_ok() {
  local label="$1"
  local url="$2"
  local pattern="$3"
  local body
  body="$(curl -fsS --max-time 15 "${url}" 2>/dev/null || true)"
  if [[ "${body}" == *"${pattern}"* ]]; then
    echo "OK ${label} ${url}"
    return 0
  fi
  echo "FAIL ${label} ${url}" >&2
  return 1
}

tail_failed_logs() {
  for service in python-worker java-backend frontend; do
    local log_file="${LOG_DIR}/${service}.log"
    if [[ -f "${log_file}" ]]; then
      echo "---- ${log_file} (last 40 lines) ----" >&2
      tail -n 40 "${log_file}" >&2 || true
    fi
  done
}

restart_deployment() {
  local args=()
  if [[ "${WITH_MINERU}" == "true" ]]; then
    args+=(--with-mineru)
  fi
  if [[ "${WITH_AI}" == "true" ]]; then
    args+=(--with-ai)
  fi
  echo "Restarting local deployment: ./scripts/deploy_local.sh ${args[*]}" >&2
  (cd "${ROOT_DIR}" && ./scripts/deploy_local.sh "${args[@]}")
}

run_check() {
  local failed=0
  load_runtime_env || return 1

  pid_ok "python-worker" || failed=1
  pid_ok "java-backend" || failed=1
  if [[ -n "${FRONTEND_URL:-}" ]]; then
    pid_ok "frontend" || failed=1
  fi

  url_ok "python worker health" "${PYTHON_WORKER_URL}/api/health" || failed=1
  url_ok "java actuator health" "${JAVA_BACKEND_URL}/actuator/health" || failed=1
  json_contains_ok "java worker bridge" "${JAVA_BACKEND_URL}/api/java/worker" '"reachable":true' || failed=1
  if [[ -n "${FRONTEND_URL:-}" ]]; then
    url_ok "frontend" "${FRONTEND_URL}/" || failed=1
  fi
  if [[ "${WITH_MINERU}" == "true" ]]; then
    json_contains_ok "ocr runtime" "${JAVA_BACKEND_URL}/api/capabilities/ocr-flow/runtime" '"providerConfigured":true' || failed=1
  fi

  if [[ "${failed}" -eq 0 ]]; then
    echo "Watchdog OK $(date '+%Y-%m-%d %H:%M:%S')"
    return 0
  fi
  tail_failed_logs
  return 1
}

while true; do
  if ! run_check; then
    if [[ "${RESTART}" == "true" ]]; then
      restart_deployment
    else
      exit 1
    fi
  fi
  if [[ "${ONCE}" == "true" ]]; then
    exit 0
  fi
  sleep "${INTERVAL_SECONDS}"
done
