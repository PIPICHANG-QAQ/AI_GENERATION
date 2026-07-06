#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WHEELHOUSE_DIR="${MINERU_WHEELHOUSE_DIR:-${ROOT_DIR}/vendor/mineru-wheelhouse}"
PYTHON_BIN="${PYTHON_BIN:-python}"

if ! "${PYTHON_BIN}" -m pip --version >/dev/null 2>&1; then
  "${PYTHON_BIN}" -m ensurepip --upgrade
fi

rm -rf "${WHEELHOUSE_DIR}"
mkdir -p "${WHEELHOUSE_DIR}"

REQ_FILE="$(mktemp)"
trap 'rm -f "${REQ_FILE}"' EXIT
cat > "${REQ_FILE}" <<'REQ'
setuptools>=68
fastapi>=0.115.0
httpx[socks]>=0.28.0
python-multipart>=0.0.9
uvicorn[standard]>=0.30.0
mineru[all]
REQ

"${PYTHON_BIN}" -m pip download \
  --dest "${WHEELHOUSE_DIR}" \
  --requirement "${REQ_FILE}"

WHEELHOUSE_DIR_ENV="${WHEELHOUSE_DIR}" "${PYTHON_BIN}" - <<'PY'
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(os.environ["WHEELHOUSE_DIR_ENV"])
files = sorted(path for path in root.iterdir() if path.is_file() and path.name != "MANIFEST.json")
payload = {
    "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    "python": sys.version.split()[0],
    "platform": platform.platform(),
    "machine": platform.machine(),
    "requirements": [
        "setuptools>=68",
        "fastapi>=0.115.0",
        "httpx[socks]>=0.28.0",
        "python-multipart>=0.0.9",
        "uvicorn[standard]>=0.30.0",
        "mineru[all]",
    ],
    "fileCount": len(files),
    "totalBytes": sum(path.stat().st_size for path in files),
    "files": [path.name for path in files],
}
(root / "MANIFEST.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"created {root}")
print(f"files={payload['fileCount']}")
print(f"bytes={payload['totalBytes']}")
PY
