#!/usr/bin/env bash
set -euo pipefail

pids=()
mineru_api_pid=""

normalize_mineru_api_enabled() {
  local default_value="$1"
  local normalized
  normalized="$(printf '%s' "${MINERU_API_ENABLED:-${default_value}}" | tr '[:upper:]' '[:lower:]')"
  case "${normalized}" in
    true|false)
      export MINERU_API_ENABLED="${normalized}"
      ;;
    *)
      echo "MINERU_API_ENABLED must be true or false." >&2
      return 1
      ;;
  esac
}

configure_environment() {
  mkdir -p /data/uploads /data/outputs /data/jobs /data/import_uploads /data/exports /data/bank_question_images /data/java_files
  mkdir -p /root/.cache/modelscope
  mkdir -p /app/backend/storage /run/nginx

  export SERVER_PORT="${SERVER_PORT:-8018}"
  export PYTHON_WORKER_PORT="${PYTHON_WORKER_PORT:-8000}"
  export PYTHON_WORKER_ENABLED="${PYTHON_WORKER_ENABLED:-true}"
  export PYTHON_WORKER_BASE_URL="${PYTHON_WORKER_BASE_URL:-http://127.0.0.1:${PYTHON_WORKER_PORT}}"
  export PYTHON_WORKER_STORAGE_ROOT="${PYTHON_WORKER_STORAGE_ROOT:-/data}"
  export SPRING_PROFILES_ACTIVE="${SPRING_PROFILES_ACTIVE:-test}"
  export DB_URL="${DB_URL:-jdbc:h2:file:/data/java_library;MODE=MySQL;DATABASE_TO_LOWER=TRUE;CASE_INSENSITIVE_IDENTIFIERS=TRUE}"
  export JAVA_STORAGE_LOCAL_ROOT="${JAVA_STORAGE_LOCAL_ROOT:-/data/java_files}"
  export JAVA_DOMAIN_LIBRARY_STORE_PATH="${JAVA_DOMAIN_LIBRARY_STORE_PATH:-/data/library_store.json}"
  export OCR_FLOW_PROVIDER="${OCR_FLOW_PROVIDER:-mineru}"
  export MINERU_COMMAND="${MINERU_COMMAND:-/opt/question-engine/venv/bin/mineru}"
  normalize_mineru_api_enabled false
  export MINERU_API_HOST="${MINERU_API_HOST:-127.0.0.1}"
  export MINERU_API_PORT="${MINERU_API_PORT:-8002}"
  export MINERU_API_URL="${MINERU_API_URL:-http://${MINERU_API_HOST}:${MINERU_API_PORT}}"
  export MINERU_API_ENABLE_VLM_PRELOAD="${MINERU_API_ENABLE_VLM_PRELOAD:-false}"
  if [[ -z "${MINERU_API_COMMAND:-}" ]]; then
    if [[ "${MINERU_COMMAND}" == */mineru ]]; then
      export MINERU_API_COMMAND="${MINERU_COMMAND%/mineru}/mineru-api"
    else
      export MINERU_API_COMMAND="/opt/question-engine/venv/bin/mineru-api"
    fi
  fi
  export ENABLE_LLM_SPLIT="${ENABLE_LLM_SPLIT:-true}"
}

terminate_children() {
  local grace_seconds="${TERMINATION_GRACE_SECONDS:-10}"
  local poll_seconds="${TERMINATION_POLL_SECONDS:-0.2}"
  local deadline
  local pid
  local -a remaining=()

  for pid in "${pids[@]}"; do
    if kill -0 "${pid}" 2>/dev/null; then
      remaining+=("${pid}")
    fi
  done
  if [[ "${#remaining[@]}" -gt 0 ]]; then
    kill -TERM "${remaining[@]}" 2>/dev/null || true
  fi

  deadline=$((SECONDS + grace_seconds))
  while [[ "${#remaining[@]}" -gt 0 && "${SECONDS}" -lt "${deadline}" ]]; do
    sleep "${poll_seconds}"
    remaining=()
    for pid in "${pids[@]}"; do
      if kill -0 "${pid}" 2>/dev/null; then
        remaining+=("${pid}")
      fi
    done
  done

  if [[ "${#remaining[@]}" -gt 0 ]]; then
    kill -KILL "${remaining[@]}" 2>/dev/null || true
  fi
  for pid in "${pids[@]}"; do
    wait "${pid}" 2>/dev/null || true
  done
  pids=()
}

handle_signal() {
  local status="$1"
  trap - INT TERM
  terminate_children
  exit "${status}"
}

install_signal_handlers() {
  trap 'handle_signal 130' INT
  trap 'handle_signal 143' TERM
}

mineru_runtime_preflight() {
  /opt/question-engine/venv/bin/python /app/scripts/check_mineru.py --json --skip-api
}

mineru_api_readiness_probe() {
  /opt/question-engine/venv/bin/python /app/scripts/check_mineru.py --json --check-api
}

start_mineru_api_process() {
  "${MINERU_API_COMMAND}" \
    --host "${MINERU_API_HOST}" \
    --port "${MINERU_API_PORT}" \
    --enable-vlm-preload "${MINERU_API_ENABLE_VLM_PRELOAD}" &
  mineru_api_pid="$!"
  pids+=("${mineru_api_pid}")
}

wait_for_mineru_api() {
  local max_attempts="${MINERU_API_MAX_ATTEMPTS:-90}"
  local poll_seconds="${MINERU_API_POLL_SECONDS:-2}"
  local attempt
  local status

  for ((attempt = 1; attempt <= max_attempts; attempt += 1)); do
    if mineru_api_readiness_probe; then
      return 0
    fi
    if ! kill -0 "${mineru_api_pid}" 2>/dev/null; then
      status=0
      wait "${mineru_api_pid}" || status=$?
      if [[ "${status}" -eq 0 ]]; then
        status=1
      fi
      echo "MinerU API exited before readiness (status ${status})" >&2
      return "${status}"
    fi
    if [[ "${attempt}" -lt "${max_attempts}" ]]; then
      sleep "${poll_seconds}"
    fi
  done
  echo "MinerU API readiness failed after ${max_attempts} attempts" >&2
  return 1
}

start_optional_mineru_api() {
  if [[ "${MINERU_API_ENABLED}" != "true" ]]; then
    return 0
  fi
  mineru_runtime_preflight
  start_mineru_api_process
  wait_for_mineru_api
}

start_managed_services() {
  /opt/question-engine/venv/bin/uvicorn app.main:app \
    --app-dir /app/backend/python-worker \
    --host 127.0.0.1 \
    --port "${PYTHON_WORKER_PORT}" &
  pids+=("$!")

  (
    cd /app/backend
    exec java -jar /app/backend/app.jar
  ) &
  pids+=("$!")

  nginx -g "daemon off;" &
  pids+=("$!")
}

supervise_children() {
  local poll_seconds="${SUPERVISOR_POLL_SECONDS:-0.2}"
  local pid
  local status=0

  if help wait 2>/dev/null | grep -q -- '-n'; then
    wait -n "${pids[@]}" || status=$?
    if [[ "${status}" -eq 0 ]]; then
      status=1
    fi
    terminate_children
    return "${status}"
  fi

  while true; do
    for pid in "${pids[@]}"; do
      if ! kill -0 "${pid}" 2>/dev/null; then
        status=0
        wait "${pid}" || status=$?
        if [[ "${status}" -eq 0 ]]; then
          status=1
        fi
        terminate_children
        return "${status}"
      fi
    done
    sleep "${poll_seconds}"
  done
}

main() {
  local status=0
  configure_environment
  install_signal_handlers

  start_optional_mineru_api || status=$?
  if [[ "${status}" -ne 0 ]]; then
    terminate_children
    return "${status}"
  fi

  start_managed_services
  supervise_children
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
