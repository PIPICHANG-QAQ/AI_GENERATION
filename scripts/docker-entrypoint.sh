#!/usr/bin/env bash
set -euo pipefail

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
export MINERU_API_ENABLED="${MINERU_API_ENABLED:-false}"
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

pids=()

terminate() {
  if [[ "${#pids[@]}" -gt 0 ]]; then
    kill -TERM "${pids[@]}" 2>/dev/null || true
    wait "${pids[@]}" 2>/dev/null || true
  fi
}

trap terminate INT TERM

if [[ "${MINERU_API_ENABLED}" == "true" ]]; then
  /opt/question-engine/venv/bin/python /app/scripts/check_mineru.py --json --skip-api
  "${MINERU_API_COMMAND}" \
    --host "${MINERU_API_HOST}" \
    --port "${MINERU_API_PORT}" \
    --enable-vlm-preload "${MINERU_API_ENABLE_VLM_PRELOAD}" &
  pids+=("$!")
  for attempt in $(seq 1 90); do
    if /opt/question-engine/venv/bin/python /app/scripts/check_mineru.py --json --check-api; then
      break
    fi
    if [[ "${attempt}" -eq 90 ]]; then
      echo "MinerU API readiness failed" >&2
      terminate
      exit 1
    fi
    sleep 2
  done
fi

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

status=0
wait -n "${pids[@]}" || status=$?
terminate
exit "${status}"
