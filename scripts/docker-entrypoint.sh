#!/usr/bin/env bash
set -euo pipefail

mkdir -p /data/uploads /data/outputs /data/jobs /data/import_uploads /data/exports /data/bank_question_images /data/java_files
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
export ENABLE_LLM_SPLIT="${ENABLE_LLM_SPLIT:-true}"

pids=()

terminate() {
  if [[ "${#pids[@]}" -gt 0 ]]; then
    kill -TERM "${pids[@]}" 2>/dev/null || true
    wait "${pids[@]}" 2>/dev/null || true
  fi
}

trap terminate INT TERM

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

wait -n "${pids[@]}"
status="$?"
terminate
exit "${status}"
