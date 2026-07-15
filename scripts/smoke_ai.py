#!/usr/bin/env python3
"""AI smoke check for a deployed local question-engine."""

from __future__ import annotations

import json
import mimetypes
import os
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any


BASE_URL = os.environ.get("AI_GENERATION_BASE_URL", "http://localhost:8018").rstrip("/")


def request(method: str, path: str, payload: bytes | dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: int = 90) -> Any:
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
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if "application/json" in resp.headers.get("content-type", ""):
            return json.loads(raw.decode("utf-8") or "{}")
        return raw


def multipart(fields: dict[str, str], files: dict[str, Path]) -> tuple[bytes, str]:
    boundary = "----ai-smoke-" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        chunks.append(value.encode("utf-8"))
        chunks.append(b"\r\n")
    for name, path in files.items():
        content_type = mimetypes.guess_type(path.name)[0] or "text/markdown"
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
    for _ in range(30):
        detail = request("GET", f"/api/import-tasks/{task_id}", timeout=30)
        last = detail
        status = str(detail.get("status", ""))
        if status not in {"处理中", "processing", ""}:
            return detail
        time.sleep(1)
    return last


def wait_standardization_job(
    task_id: str,
    job_id: str,
    timeout_seconds: float = 180,
    poll_interval_seconds: float = 1,
) -> dict[str, Any]:
    active_statuses = {"queued", "running", "cancelling", "pending", "processing"}
    successful_statuses = {"completed", "partial_review"}
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] = {}
    while True:
        payload = request(
            "GET",
            f"/api/import-tasks/{task_id}/standardization-jobs/{job_id}",
            timeout=30,
        )
        last = payload if isinstance(payload, dict) else {"payload": payload}
        status = str(last.get("status") or "").strip().lower()
        if status not in active_statuses:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError(f"global standardization timed out; last payload: {last}")
        time.sleep(poll_interval_seconds)

    completed_items = int(last.get("completedItems") or 0)
    total_items = int(last.get("totalItems") or 0)
    failed_items = int(last.get("failedItems") or 0)
    if status in successful_statuses and completed_items == total_items and failed_items == 0:
        return last
    raise AssertionError(f"global standardization failed; last payload: {last}")


def main() -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as file:
        file.write("# AI 冒烟试卷\n\n1. 已知 $x+1=2$，求 $x$。\n\nA. 0\nB. 1\nC. 2\nD. 3\n")
        paper_path = Path(file.name)
    try:
        body, content_type = multipart(
            {
                "stage": "高中",
                "subject": "数学",
                "grade": "高一",
                "region": "本地",
                "year": "2026",
                "title": "AiSmoke_" + uuid.uuid4().hex[:8],
            },
            {"paperFile": paper_path},
        )
        task = request("POST", "/api/import-tasks", body, {"Content-Type": content_type}, timeout=60)
        task_id = str(task.get("id") or "")
        ok("ai task create", bool(task_id), task)
    finally:
        paper_path.unlink(missing_ok=True)

    detail = wait_import_ready(task_id)
    questions = detail.get("questions") or []
    ok("ai task questions", len(questions) >= 1, detail)

    question = questions[0]
    question_id = str(question.get("id") or "")
    markdown = str(question.get("manualMarkdown") or question.get("stemMarkdown") or "")

    # The workbench always previews canonical structure before it starts the
    # durable global standardization batch.  Keep this route in the AI smoke
    # because it must be handled by Java rather than the legacy Python API
    # proxy.
    canonical_preview = request(
        "POST",
        f"/api/import-tasks/{task_id}/canonicalization/preview",
        timeout=60,
    )
    ok("canonicalization preview", bool(canonical_preview.get("applyToken")), canonical_preview)
    ok("canonicalization has no blockers", not canonical_preview.get("blockingIssues"), canonical_preview)

    standardized = request(
        "POST",
        f"/api/import-tasks/{task_id}/questions/{question_id}/standardize/ai",
        {"markdown": markdown},
        timeout=90,
    )
    ok("ai standardize", "markdown" in standardized, standardized)

    analysis = request(
        "POST",
        f"/api/import-tasks/{task_id}/questions/{question_id}/analysis",
        {"manualMarkdown": markdown, "answer": "B", "type": question.get("type", "")},
        timeout=90,
    )
    ok("ai analysis", "analysis" in analysis, analysis)

    global_job = request(
        "POST",
        f"/api/import-tasks/{task_id}/standardization-jobs",
        timeout=60,
    )
    global_job_id = str(global_job.get("id") or "")
    ok("global standardization starts", bool(global_job_id), global_job)
    ok("global standardization item count", int(global_job.get("totalItems") or 0) >= 1, global_job)
    completed_job = wait_standardization_job(task_id, global_job_id)
    ok("global standardization completed", True, completed_job)
    print("ai smoke passed")


if __name__ == "__main__":
    main()
