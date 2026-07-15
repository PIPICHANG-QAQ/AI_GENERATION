#!/usr/bin/env bash

LOCAL_PID_RECORD_VERSION=1

local_pid_is_running() {
  local pid="$1"
  kill -0 "${pid}" 2>/dev/null || return 1
  local state
  state="$(ps -p "${pid}" -o stat= 2>/dev/null || true)"
  [[ -n "${state}" && "${state}" != Z* ]]
}

process_start_identity() {
  local pid="$1"
  local identity
  identity="$(ps -p "${pid}" -o lstart= 2>/dev/null || true)"
  identity="$(printf '%s\n' "${identity}" | awk '{$1=$1; print}')"
  [[ -n "${identity}" ]] || return 1
  printf '%s\n' "${identity}"
}

process_command() {
  ps -p "$1" -o command= 2>/dev/null || true
}

process_cwd() {
  local cwd
  cwd="$(lsof -a -p "$1" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1)"
  if [[ -d "${cwd}" ]]; then
    (cd "${cwd}" && pwd -P)
  else
    printf '%s\n' "${cwd}"
  fi
}

cwd_belongs_to_project() {
  local cwd="$1"
  local root="$2"
  [[ "${cwd}" == "${root}" || "${cwd}" == "${root}/"* ]]
}

service_command_matches() {
  local service="$1"
  local command="$2"
  local cwd="$3"
  local root="$4"

  cwd_belongs_to_project "${cwd}" "${root}" || return 1
  case "${service}" in
    python-worker)
      [[ "${command}" == *uvicorn* &&
         "${command}" == *app.main:app* &&
         "${command}" == *--app-dir* &&
         "${command}" == *backend/python-worker* ]]
      ;;
    java-backend)
      [[ "${command}" == *spring-boot:run* ||
         "${command}" == *AiQuestionBankApplication* ]]
      ;;
    frontend)
      [[ "${cwd}" == "${root}/local-platform" || "${cwd}" == "${root}/local-platform/"* ]] || return 1
      [[ "${command}" == *vite* ]]
      ;;
    *)
      return 1
      ;;
  esac
}

pid_matches_service() {
  local service="$1"
  local pid="$2"
  local root="$3"
  local_pid_is_running "${pid}" || return 1
  local command cwd
  command="$(process_command "${pid}")"
  cwd="$(process_cwd "${pid}")"
  service_command_matches "${service}" "${command}" "${cwd}" "${root}"
}

screen_pid_matches_service() {
  local service="$1"
  local pid="$2"
  local root="$3"
  local session="$4"
  local_pid_is_running "${pid}" || return 1
  local command cwd wrapper
  command="$(process_command "${pid}")"
  cwd="$(process_cwd "${pid}")"
  wrapper=".run/${service}.sh"
  cwd_belongs_to_project "${cwd}" "${root}" || return 1
  [[ "${command}" == *screen* &&
     "${command}" == *"${session}"* &&
     "${command}" == *"${wrapper}"* ]]
}

write_pid_record_atomic() {
  local file="$1"
  local service="$2"
  local pid="$3"
  [[ "${pid}" =~ ^[1-9][0-9]*$ ]] || return 1
  case "${service}" in
    python-worker|java-backend|frontend) ;;
    *) return 1 ;;
  esac

  local start directory temporary
  start="$(process_start_identity "${pid}")" || return 1
  directory="${file%/*}"
  mkdir -p "${directory}"
  temporary="${file}.tmp.${pid}"
  umask 077
  if ! printf 'version=%s\npid=%s\nservice=%s\nstart=%s\n' \
    "${LOCAL_PID_RECORD_VERSION}" "${pid}" "${service}" "${start}" > "${temporary}"; then
    rm -f -- "${temporary}"
    return 1
  fi
  if ! mv -f -- "${temporary}" "${file}"; then
    rm -f -- "${temporary}"
    return 1
  fi
}

read_pid_record() {
  local file="$1"
  local expected_service="$2"
  PID_RECORD_PID=""
  PID_RECORD_START=""
  PID_RECORD_IS_VERSIONED="false"

  local content
  content="$(<"${file}")"
  if [[ "${content}" =~ ^[[:space:]]*([1-9][0-9]*)[[:space:]]*$ ]]; then
    PID_RECORD_PID="${BASH_REMATCH[1]}"
    return 0
  fi

  local version="" pid="" service="" start=""
  local version_count=0 pid_count=0 service_count=0 start_count=0 line
  while IFS= read -r line || [[ -n "${line}" ]]; do
    case "${line}" in
      version=*) version="${line#version=}"; version_count=$((version_count + 1)) ;;
      pid=*) pid="${line#pid=}"; pid_count=$((pid_count + 1)) ;;
      service=*) service="${line#service=}"; service_count=$((service_count + 1)) ;;
      start=*) start="${line#start=}"; start_count=$((start_count + 1)) ;;
      *) return 1 ;;
    esac
  done <<< "${content}"

  [[ "${version_count}" -eq 1 && "${version}" == "${LOCAL_PID_RECORD_VERSION}" ]] || return 1
  [[ "${pid_count}" -eq 1 && "${pid}" =~ ^[1-9][0-9]*$ ]] || return 1
  [[ "${service_count}" -eq 1 && "${service}" == "${expected_service}" ]] || return 1
  [[ "${start_count}" -eq 1 && -n "${start}" ]] || return 1
  PID_RECORD_PID="${pid}"
  PID_RECORD_START="${start}"
  PID_RECORD_IS_VERSIONED="true"
}

terminate_pid_verified() {
  local pid="$1"
  local attempts="${STOP_LOCAL_WAIT_ATTEMPTS:-30}"
  local interval="${STOP_LOCAL_WAIT_INTERVAL:-0.2}"
  local count
  local_pid_is_running "${pid}" || return 0

  kill "${pid}" 2>/dev/null || true
  count=0
  while (( count < attempts )); do
    local_pid_is_running "${pid}" || return 0
    sleep "${interval}"
    count=$((count + 1))
  done

  kill -9 "${pid}" 2>/dev/null || true
  count=0
  while (( count < attempts )); do
    local_pid_is_running "${pid}" || return 0
    sleep "${interval}"
    count=$((count + 1))
  done
  ! local_pid_is_running "${pid}"
}
