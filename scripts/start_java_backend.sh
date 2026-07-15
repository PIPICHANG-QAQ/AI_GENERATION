#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../backend"

if command -v /usr/libexec/java_home >/dev/null 2>&1; then
  export JAVA_HOME="${JAVA_BACKEND_JAVA_HOME:-$(/usr/libexec/java_home -v 17)}"
fi

export SPRING_PROFILES_ACTIVE="${JAVA_BACKEND_PROFILE:-test}"
export SERVER_PORT="${JAVA_BACKEND_PORT:-${SERVER_PORT:-8018}}"
export PYTHON_WORKER_ENABLED="${PYTHON_WORKER_ENABLED:-true}"
export PYTHON_WORKER_BASE_URL="${PYTHON_WORKER_BASE_URL:-http://127.0.0.1:8000}"
export PYTHON_WORKER_HEALTH_PATH="${PYTHON_WORKER_HEALTH_PATH:-/api/health}"

exec mvn clean spring-boot:run -Dspring-boot.run.profiles="${SPRING_PROFILES_ACTIVE}"
