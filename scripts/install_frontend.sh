#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [[ ! -f "${ROOT_DIR}/local-platform/package.json" ]]; then
  echo "local-platform is not included in this checkout or delivery package." >&2
  exit 1
fi

cd "${ROOT_DIR}/local-platform"

if [[ -f package-lock.json ]]; then
  npm ci
else
  npm install
fi

echo "Frontend dependencies installed in local-platform/node_modules"
