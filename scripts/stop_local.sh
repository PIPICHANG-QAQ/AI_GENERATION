#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd -P)"
RUN_DIR="${ROOT_DIR}/.run"
PID_DIR="${RUN_DIR}/pids"
DEPLOY_ENV="${RUN_DIR}/deploy.env"
SERVICES=(frontend java-backend python-worker)

deploy_value() {
  local key="$1"
  [[ -f "${DEPLOY_ENV}" ]] || return 0
  awk -F= -v key="${key}" '$1 == key { print substr($0, index($0, "=") + 1); exit }' "${DEPLOY_ENV}"
}

project_slug() {
  local slug
  slug="$(basename "${ROOT_DIR}" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '_' | sed 's/_$//')"
  printf '%s\n' "${slug:-ai_generation}"
}

screen_prefix() {
  local configured
  configured="$(deploy_value SCREEN_PREFIX)"
  if [[ "${configured}" =~ ^[a-zA-Z0-9_]+$ ]]; then
    printf '%s\n' "${configured}"
  else
    printf 'ai_%s\n' "$(project_slug)"
  fi
}

pid_is_running() {
  local pid="$1"
  kill -0 "${pid}" 2>/dev/null || return 1
  local state
  state="$(ps -p "${pid}" -o stat= 2>/dev/null || true)"
  [[ -n "${state}" && "${state}" != Z* ]]
}

pid_belongs_to_project() {
  local pid="$1"
  pid_is_running "${pid}" || return 1
  local cwd
  cwd="$(lsof -a -p "${pid}" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1)"
  [[ "${cwd}" == "${ROOT_DIR}" || "${cwd}" == "${ROOT_DIR}/"* ]]
}

stop_pid() {
  local pid="$1"
  if ! pid_is_running "${pid}"; then
    return 0
  fi
  if ! pid_belongs_to_project "${pid}"; then
    echo "refusing to stop non-project PID ${pid}" >&2
    return 1
  fi

  kill "${pid}" 2>/dev/null || true
  for _ in $(seq 1 30); do
    pid_is_running "${pid}" || return 0
    sleep 0.2
  done
  kill -9 "${pid}" 2>/dev/null || true
}

stop_pid_file() {
  local service="$1"
  local file="${PID_DIR}/${service}.pid"
  [[ -f "${file}" ]] || return 0

  local pid
  pid="$(tr -dc '0-9' < "${file}")"
  if [[ -z "${pid}" ]]; then
    rm -f "${file}"
    return 0
  fi
  if stop_pid "${pid}"; then
    rm -f "${file}"
  fi
}

stop_screen_sessions() {
  local service="$1"
  command -v screen >/dev/null 2>&1 || return 0
  local session_name="$(screen_prefix)_${service//-/_}"
  local session_id
  while IFS= read -r session_id; do
    [[ -n "${session_id}" ]] || continue
    local session_pid="${session_id%%.*}"
    if [[ ! "${session_pid}" =~ ^[0-9]+$ ]] || ! pid_belongs_to_project "${session_pid}"; then
      echo "refusing to stop non-project screen session ${session_id}" >&2
      continue
    fi
    screen -S "${session_id}" -X quit >/dev/null 2>&1 || true
  done < <(
    screen -ls 2>/dev/null | awk -v suffix=".${session_name}" '
      $1 ~ /^[0-9]+\./ && substr($1, length($1) - length(suffix) + 1) == suffix { print $1 }
    '
  )
}

pids_on_port() {
  lsof -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null || true
}

stop_project_pids_on_port() {
  local port="$1"
  local pid
  while IFS= read -r pid; do
    [[ -n "${pid}" ]] || continue
    pid_belongs_to_project "${pid}" || continue
    stop_pid "${pid}" || true
  done < <(pids_on_port "${port}")
}

configured_port() {
  local key="$1"
  local fallback="$2"
  local configured
  configured="$(deploy_value "${key}")"
  if [[ "${configured}" =~ ^[0-9]+$ ]] && (( configured >= 1 && configured <= 65535 )); then
    printf '%s\n' "${configured}"
  else
    printf '%s\n' "${fallback}"
  fi
}

main() {
  command -v lsof >/dev/null 2>&1 || {
    echo "Missing required command: lsof" >&2
    return 1
  }

  local service
  for service in "${SERVICES[@]}"; do
    stop_screen_sessions "${service}"
  done
  for service in "${SERVICES[@]}"; do
    stop_pid_file "${service}"
  done

  local ports=(
    "$(configured_port PYTHON_WORKER_PORT 8000)"
    "$(configured_port JAVA_BACKEND_PORT 8018)"
    "$(configured_port FRONTEND_PORT 5173)"
  )
  local port
  for port in "${ports[@]}"; do
    stop_project_pids_on_port "${port}"
  done

  echo "Local services stopped."
}

main "$@"
