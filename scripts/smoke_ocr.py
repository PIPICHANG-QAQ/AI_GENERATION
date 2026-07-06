#!/usr/bin/env python3
"""OCR smoke check for a deployed local question-engine."""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any


BASE_URL = os.environ.get("AI_GENERATION_BASE_URL", "http://localhost:8018").rstrip("/")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKER_PYTHON = PROJECT_ROOT / "backend" / "python-worker" / ".venv" / "bin" / "python"


def ensure_worker_python() -> None:
    if not WORKER_PYTHON.exists():
        return
    if Path(sys.executable) != WORKER_PYTHON:
        os.execv(str(WORKER_PYTHON), [str(WORKER_PYTHON), *sys.argv])


def request(method: str, path: str, payload: bytes | dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: int = 60) -> Any:
    body: bytes | None
    merged_headers = dict(headers or {})
    if isinstance(payload, bytes):
        body = payload
    elif payload is None:
        body = None
    else:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        merged_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(BASE_URL + path, data=body, headers=merged_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if "application/json" in resp.headers.get("content-type", ""):
                return json.loads(raw.decode("utf-8") or "{}")
            return raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {raw[:800]}") from exc


def multipart(fields: dict[str, str], files: dict[str, Path]) -> tuple[bytes, str]:
    boundary = "----ocr-smoke-" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        chunks.append(value.encode("utf-8"))
        chunks.append(b"\r\n")
    for name, path in files.items():
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(f'Content-Disposition: form-data; name="{name}"; filename="{path.name}"\r\n'.encode())
        chunks.append(f"Content-Type: {content_type}\r\n\r\n".encode())
        chunks.append(path.read_bytes())
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def ok(name: str, condition: bool, detail: Any = "") -> None:
    if not condition:
        raise AssertionError(f"{name} failed: {detail}")
    print(f"OK {name}")


def wait_import_ready(task_id: str) -> dict[str, Any]:
    last: dict[str, Any] = {}
    for _ in range(45):
        detail = request("GET", f"/api/import-tasks/{task_id}", timeout=30)
        last = detail
        status = str(detail.get("status", ""))
        if status not in {"处理中", "processing", ""}:
            return detail
        time.sleep(2)
    return last


def make_image(path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    question_text = "1. x + 1 = 2, find x.\nA. 0\nB. 1\nC. 2\nD. 3\n"
    image = Image.new("RGB", (1400, 900), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 56)
    except Exception:
        font = ImageFont.load_default()
    y = 90
    for line in question_text.splitlines():
        draw.text((80, y), line, fill="black", font=font)
        y += 90
    image.save(path, format="PNG")


def main() -> None:
    ensure_worker_python()

    runtime = request("GET", "/api/capabilities/ocr-flow/runtime", timeout=30)
    provider_status = runtime.get("providerStatus") or {}
    ok("ocr provider executable", provider_status.get("installed") is True and not provider_status.get("error"), runtime)

    with tempfile.NamedTemporaryFile("wb", suffix=".png", delete=False) as file:
        image_path = Path(file.name)
    make_image(image_path)
    try:
        body, content_type = multipart(
            {
                "stage": "高中",
                "subject": "数学",
                "grade": "高一",
                "region": "本地",
                "year": "2026",
                "title": "OcrSmoke_" + uuid.uuid4().hex[:8],
            },
            {"paperFile": image_path},
        )
        task = request("POST", "/api/import-tasks", body, {"Content-Type": content_type}, timeout=90)
        task_id = str(task.get("id") or "")
        ok("ocr task create", bool(task_id), task)
        detail = wait_import_ready(task_id)
        ok("ocr task finished", detail.get("paperOcrStatus") == "success" and detail.get("status") in {"待校验", "部分完成", "已完成"}, detail)
    finally:
        image_path.unlink(missing_ok=True)

    print("ocr smoke passed")


if __name__ == "__main__":
    main()
