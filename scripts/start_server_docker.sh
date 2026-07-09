#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

HTTP_PORT="${APP_HTTP_PORT:-80}"
PUBLIC_HOST="${APP_PUBLIC_HOST:-${SERVER_PUBLIC_HOST:-}}"

if [[ -z "$PUBLIC_HOST" ]]; then
  PUBLIC_HOST="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
fi
if [[ -z "$PUBLIC_HOST" ]]; then
  PUBLIC_HOST="服务器IP"
fi

need_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "缺少命令：$1" >&2
    exit 1
  fi
}

need_command docker
need_command curl
need_command npm

if ! docker compose version >/dev/null 2>&1; then
  echo "当前 Docker 不支持 'docker compose'。请安装 Docker Compose v2。" >&2
  exit 1
fi

echo "==> 构建 Java backend jar"
if command -v mvn >/dev/null 2>&1; then
  (cd backend && mvn -DskipTests package)
else
  echo "未找到 mvn，跳过 Java 构建；将使用 backend/target 下已有 jar。"
fi

if ! ls backend/target/ai-question-bank-*.jar >/dev/null 2>&1; then
  echo "缺少 backend/target/ai-question-bank-*.jar，Docker 镜像无法构建。" >&2
  echo "请先安装 Maven 并执行：(cd backend && mvn -DskipTests package)" >&2
  exit 1
fi

echo "==> 构建 local-platform 静态资源"
if [[ ! -d local-platform/node_modules ]]; then
  (cd local-platform && npm install)
fi
(cd local-platform && npm run build)

echo "==> 启动 question-engine Docker 服务"
docker compose -f docker-compose.server.yml up -d --build question-engine

echo "==> 等待健康检查"
health_url="http://127.0.0.1:${HTTP_PORT}/api/java/health"
for i in $(seq 1 60); do
  if curl -fsS "$health_url" >/dev/null 2>&1; then
    break
  fi
  if [[ "$i" -eq 60 ]]; then
    echo "健康检查失败：$health_url" >&2
    docker compose -f docker-compose.server.yml ps >&2 || true
    docker compose -f docker-compose.server.yml logs --tail=120 question-engine >&2 || true
    exit 1
  fi
  sleep 2
done

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
echo "docker compose -f docker-compose.server.yml logs -f question-engine"
