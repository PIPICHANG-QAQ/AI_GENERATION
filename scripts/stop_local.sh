#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd -P)"
RUN_DIR="${ROOT_DIR}/.run"
PID_DIR="${RUN_DIR}/pids"
DEPLOY_ENV="${RUN_DIR}/deploy.env"
SERVICES=(frontend java-backend python-worker)

# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/local_process_identity.sh"

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

stop_pid_file() {
  local file="$1"
  local service="$2"
  [[ -f "${file}" && ! -L "${file}" ]] || return 0

  if ! read_pid_record "${file}" "${service}"; then
    rm -f -- "${file}"
    return 0
  fi

  local pid="${PID_RECORD_PID}"
  local recorded_start="${PID_RECORD_START}"
  local versioned="${PID_RECORD_IS_VERSIONED}"
  if ! local_pid_is_running "${pid}"; then
    rm -f -- "${file}"
    return 0
  fi

  if [[ "${versioned}" == "true" ]]; then
    local current_start
    current_start="$(process_start_identity "${pid}" || true)"
    if [[ -z "${current_start}" || "${current_start}" != "${recorded_start}" ]]; then
      echo "refusing to stop PID ${pid}: start identity mismatch" >&2
      return 1
    fi
  fi

  if ! pid_matches_service "${service}" "${pid}" "${ROOT_DIR}"; then
    echo "refusing to stop non-project PID ${pid}: ${service} service identity mismatch" >&2
    return 1
  fi

  if ! terminate_pid_verified "${pid}"; then
    echo "could not stop project process ${pid} for ${service}" >&2
    return 1
  fi
  rm -f -- "${file}"
}

stop_pid_files() {
  [[ -d "${PID_DIR}" ]] || return 0
  local file name service result=0
  local pattern='^(frontend|java-backend|python-worker)( [1-9][0-9]*)?\.pid$'
  while IFS= read -r -d '' file; do
    [[ "${file%/*}" == "${PID_DIR}" ]] || continue
    [[ -f "${file}" && ! -L "${file}" ]] || continue
    name="${file##*/}"
    [[ "${name}" =~ ${pattern} ]] || continue
    service="${BASH_REMATCH[1]}"
    if ! stop_pid_file "${file}" "${service}"; then
      result=1
    fi
  done < <(find "${PID_DIR}" -type f -print0)
  return "${result}"
}

stop_screen_sessions() {
  local service="$1"
  command -v screen >/dev/null 2>&1 || return 0
  local session_name="$(screen_prefix)_${service//-/_}"
  local session_id session_pid result=0
  while IFS= read -r session_id; do
    [[ -n "${session_id}" ]] || continue
    session_pid="${session_id%%.*}"
    if [[ ! "${session_pid}" =~ ^[1-9][0-9]*$ ]] || \
       ! screen_pid_matches_service "${service}" "${session_pid}" "${ROOT_DIR}" "${session_name}"; then
      echo "refusing to stop non-project screen session ${session_id}" >&2
      result=1
      continue
    fi
    if ! screen -S "${session_id}" -X quit >/dev/null 2>&1; then
      echo "could not stop project screen session ${session_id}" >&2
      result=1
      continue
    fi
    if ! terminate_pid_verified "${session_pid}"; then
      echo "could not stop project process ${session_pid} for ${service}" >&2
      result=1
    fi
  done < <(
    screen -ls 2>/dev/null | awk -v suffix=".${session_name}" '
      $1 ~ /^[0-9]+\./ && substr($1, length($1) - length(suffix) + 1) == suffix { print $1 }
    '
  )
  return "${result}"
}

pids_on_port() {
  lsof -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null || true
}

stop_service_pids_on_port() {
  local service="$1"
  local port="$2"
  local pid result=0
  while IFS= read -r pid; do
    [[ -n "${pid}" ]] || continue
    if ! pid_matches_service "${service}" "${pid}" "${ROOT_DIR}"; then
      echo "leaving unrelated listener PID ${pid} on port ${port}" >&2
      continue
    fi
    if ! terminate_pid_verified "${pid}"; then
      echo "could not stop project process ${pid} for ${service}" >&2
      result=1
    fi
  done < <(pids_on_port "${port}")
  return "${result}"
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

  local failures=0 service
  for service in "${SERVICES[@]}"; do
    if ! stop_screen_sessions "${service}"; then
      failures=1
    fi
  done
  if ! stop_pid_files; then
    failures=1
  fi

  if ! stop_service_pids_on_port "python-worker" "$(configured_port PYTHON_WORKER_PORT 8000)"; then
    failures=1
  fi
  if ! stop_service_pids_on_port "java-backend" "$(configured_port JAVA_BACKEND_PORT 8018)"; then
    failures=1
  fi
  if ! stop_service_pids_on_port "frontend" "$(configured_port FRONTEND_PORT 5173)"; then
    failures=1
  fi

  if (( failures != 0 )); then
    echo "Local stop incomplete." >&2
    return 1
  fi
  echo "Local services stopped."
}

main "$@"
