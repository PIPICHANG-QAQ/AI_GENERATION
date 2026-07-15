#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="docker-compose.server.yml"

load_environment() {
  if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
  fi
}

need_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "缺少命令：$1" >&2
    return 1
  fi
}

normalize_mineru_api_enabled() {
  local normalized
  if [[ -z "${MINERU_API_ENABLED-}" ]]; then
    normalized=false
  else
    normalized="$(printf '%s' "${MINERU_API_ENABLED}" | tr '[:upper:]' '[:lower:]')"
  fi
  case "${normalized}" in
    true|false)
      export MINERU_API_ENABLED="${normalized}"
      ;;
    *)
      printf "MINERU_API_ENABLED must be exactly true or false (case-insensitive) without surrounding whitespace; got '%s'.\n" \
        "${MINERU_API_ENABLED}" >&2
      return 1
      ;;
  esac
}

absolute_from_root() {
  local value="$1"
  if [[ "${value}" != /* ]]; then
    value="${ROOT_DIR}/${value}"
  fi
  python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "${value}"
}

configure_mineru_environment() {
  local configured_venv="${HOST_MINERU_VENV:-${ROOT_DIR}/vendor/mineru-venv}"
  local expected_command
  local configured_command

  HOST_MINERU_VENV="$(absolute_from_root "${configured_venv}")"
  expected_command="${HOST_MINERU_VENV}/bin/mineru"
  configured_command="${MINERU_HOST_COMMAND:-${expected_command}}"
  configured_command="$(absolute_from_root "${configured_command}")"
  if [[ "${configured_command}" != "${expected_command}" ]]; then
    echo "MINERU_HOST_COMMAND must equal HOST_MINERU_VENV/bin/mineru: ${expected_command}" >&2
    return 1
  fi

  export HOST_MINERU_VENV
  export MINERU_HOST_COMMAND="${expected_command}"
  export MINERU_COMMAND="${expected_command}"
  export MINERU_API_COMMAND="${HOST_MINERU_VENV}/bin/mineru-api"
}

host_mineru_preflight() {
  if [[ "${MINERU_API_ENABLED}" != "true" ]]; then
    return 0
  fi
  echo "==> 检查宿主机 MinerU runtime"
  python3 scripts/check_mineru.py --json --skip-api
}

ocr_runtime_payload_is_ready() {
  python3 -c '
import json
import sys

try:
    status = json.load(sys.stdin)["providerStatus"]
    api_enabled = status.get("apiEnabled")
    ready = (
        status.get("installed") is True
        and status.get("runtimeProbeOk") is True
        and (
            api_enabled is False
            or (api_enabled is True and status.get("apiReady") is True)
        )
    )
except (KeyError, TypeError, ValueError):
    ready = False
raise SystemExit(0 if ready else 1)
'
}

java_health_ready() {
  local request_timeout="$1"
  curl -fsS --connect-timeout "${request_timeout}" --max-time "${request_timeout}" "${health_url}" >/dev/null 2>&1
}

ocr_runtime_ready() {
  local request_timeout="$1"
  curl -fsS --connect-timeout "${request_timeout}" --max-time "${request_timeout}" "${ocr_runtime_url}" 2>/dev/null \
    | ocr_runtime_payload_is_ready
}

server_readiness_probe() {
  local deadline="$1"
  local java_status=0
  local ocr_status=0
  local request_timeout

  request_timeout="$(request_timeout_for_deadline "${deadline}")" || return 1
  java_health_ready "${request_timeout}" || java_status=$?
  request_timeout="$(request_timeout_for_deadline "${deadline}")" || return 1
  ocr_runtime_ready "${request_timeout}" || ocr_status=$?
  [[ "${java_status}" -eq 0 && "${ocr_status}" -eq 0 ]]
}

startup_timeout_seconds() {
  printf '%s\n' "${QUESTION_ENGINE_STARTUP_TIMEOUT_SECONDS:-600}"
}

remaining_deadline_seconds() {
  local deadline="$1"
  local remaining=$((deadline - $(date +%s)))
  printf '%s\n' "${remaining}"
}

request_timeout_for_deadline() {
  local deadline="$1"
  local remaining
  remaining="$(remaining_deadline_seconds "${deadline}")"
  if [[ "${remaining}" -le 0 ]]; then
    return 1
  fi
  if [[ "${remaining}" -gt 5 ]]; then
    remaining=5
  fi
  printf '%s\n' "${remaining}"
}

wait_for_server_readiness() {
  local timeout_seconds
  local poll_seconds="${QUESTION_ENGINE_STARTUP_POLL_SECONDS:-2}"
  local deadline

  timeout_seconds="$(startup_timeout_seconds)"
  if [[ ! "${timeout_seconds}" =~ ^[0-9]+$ ]]; then
    echo "QUESTION_ENGINE_STARTUP_TIMEOUT_SECONDS must be a non-negative integer" >&2
    return 2
  fi
  deadline=$(( $(date +%s) + timeout_seconds ))
  while true; do
    if [[ "$(remaining_deadline_seconds "${deadline}")" -le 0 ]]; then
      return 1
    fi
    if server_readiness_probe "${deadline}"; then
      return 0
    fi
    local remaining
    remaining="$(remaining_deadline_seconds "${deadline}")"
    if [[ "${remaining}" -le 0 ]]; then
      return 1
    fi
    local sleep_seconds
    sleep_seconds="$(awk -v poll="${poll_seconds}" -v remaining="${remaining}" \
      'BEGIN { print (poll < remaining ? poll : remaining) }')"
    sleep "${sleep_seconds}"
  done
}

show_startup_diagnostics() {
  echo "Java health response:" >&2
  curl -sS --connect-timeout 1 --max-time 1 "${health_url}" >&2 || true
  echo >&2
  echo "OCR runtime response:" >&2
  curl -sS --connect-timeout 1 --max-time 1 "${ocr_runtime_url}" >&2 || true
  echo >&2
  docker compose -f "${COMPOSE_FILE}" ps >&2 || true
  docker compose -f "${COMPOSE_FILE}" logs --tail=120 question-engine >&2 || true
}

cleanup_failed_service() {
  docker compose -f "${COMPOSE_FILE}" stop question-engine >/dev/null 2>&1 || true
  docker compose -f "${COMPOSE_FILE}" rm -f question-engine >/dev/null 2>&1 || true
}

require_server_readiness() {
  local status=0
  wait_for_server_readiness || status=$?
  if [[ "${status}" -eq 0 ]]; then
    return 0
  fi
  echo "服务未在统一启动期限内就绪（Java + OCR runtime）" >&2
  cleanup_failed_service
  show_startup_diagnostics || true
  return "${status}"
}

configure_public_urls() {
  HTTP_PORT="${APP_HTTP_PORT:-80}"
  PUBLIC_HOST="${APP_PUBLIC_HOST:-${SERVER_PUBLIC_HOST:-}}"
  if [[ -z "${PUBLIC_HOST}" ]]; then
    PUBLIC_HOST="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  fi
  if [[ -z "${PUBLIC_HOST}" ]]; then
    PUBLIC_HOST="服务器IP"
  fi
  health_url="http://127.0.0.1:${HTTP_PORT}/api/java/health"
  ocr_runtime_url="http://127.0.0.1:${HTTP_PORT}/api/capabilities/ocr-flow/runtime"
}

build_server_artifacts() {
  echo "==> 构建 Java backend jar"
  if command -v mvn >/dev/null 2>&1; then
    if ! (cd backend && mvn clean -DskipTests package); then
      echo "Java backend 构建失败，拒绝使用 backend/target 下的旧 jar。" >&2
      return 1
    fi
  else
    echo "未找到 mvn，跳过 Java 构建；将使用 backend/target 下已有 jar。"
  fi

  if ! ls backend/target/ai-question-bank-*.jar >/dev/null 2>&1; then
    echo "缺少 backend/target/ai-question-bank-*.jar，Docker 镜像无法构建。" >&2
    echo "请先安装 Maven 并执行：(cd backend && mvn clean -DskipTests package)" >&2
    return 1
  fi

  echo "==> 构建 local-platform 静态资源"
  if [[ ! -d local-platform/node_modules ]]; then
    (cd local-platform && npm install)
  fi
  (cd local-platform && npm run build)
}

main() {
  cd "${ROOT_DIR}"
  load_environment
  MINERU_API_ENABLED="${MINERU_API_ENABLED:-true}"
  normalize_mineru_api_enabled

  need_command docker
  need_command curl
  need_command npm
  need_command python3
  if ! docker compose version >/dev/null 2>&1; then
    echo "当前 Docker 不支持 'docker compose'。请安装 Docker Compose v2。" >&2
    return 1
  fi

  configure_mineru_environment
  configure_public_urls
  host_mineru_preflight
  build_server_artifacts

  echo "==> 启动 question-engine Docker 服务"
  docker compose -f "${COMPOSE_FILE}" up -d --build question-engine

  echo "==> 等待 Java + OCR runtime 健康检查"
  require_server_readiness

  echo
  echo "启动完成。"
  echo "前端页面： http://${PUBLIC_HOST}:${HTTP_PORT}/"
  echo "健康检查： http://${PUBLIC_HOST}:${HTTP_PORT}/api/java/health"
  echo "OCR-Flow： http://${PUBLIC_HOST}:${HTTP_PORT}/api/capabilities/ocr-flow/runtime"
  echo
  echo "如果 HTTP_PORT=80，浏览器可省略端口："
  echo "http://${PUBLIC_HOST}/"
  echo
  echo "查看日志："
  echo "docker compose -f ${COMPOSE_FILE} logs -f question-engine"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
