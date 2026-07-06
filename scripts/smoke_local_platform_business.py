#!/usr/bin/env python3
"""本地小平台基础业务冒烟测试。

该脚本只依赖 Python 标准库，面向本地开发环境：

- Java backend: http://localhost:8018
- Python worker: http://127.0.0.1:8000
- local-platform: http://localhost:5173

它会创建临时导入任务、知识点、题库题和试卷，并在完成后清理测试数据。
"""

from __future__ import annotations

import json
import mimetypes
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


BASE_URL = os.environ.get("AI_GENERATION_BASE_URL", "http://localhost:8018").rstrip("/")
FRONTEND_URL = os.environ.get("AI_GENERATION_FRONTEND_URL", "http://localhost:5173").rstrip("/")


def request(method: str, path: str, payload: Any = None, headers: dict[str, str] | None = None, timeout: int = 30):
    body = None
    merged_headers = dict(headers or {})
    if payload is not None:
        if isinstance(payload, bytes):
            body = payload
        else:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            merged_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(BASE_URL + path, data=body, headers=merged_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            content_type = resp.headers.get("content-type", "")
            if "application/json" in content_type:
                return resp.status, json.loads(raw.decode("utf-8") or "{}"), dict(resp.headers)
            return resp.status, raw, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} -> {exc.code}: {raw[:800]}") from exc


def multipart(fields: dict[str, str], files: dict[str, Path]) -> tuple[bytes, str]:
    boundary = "----question-engine-" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")
    for name, path in files.items():
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{path.name}"\r\n'.encode()
        )
        chunks.append(f"Content-Type: {content_type}\r\n\r\n".encode())
        chunks.append(path.read_bytes())
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def assert_true(name: str, condition: bool, detail: Any = ""):
    if not condition:
        raise AssertionError(f"{name} failed: {detail}")
    print(f"OK {name}")


def wait_import_ready(task_id: str) -> dict[str, Any]:
    last = {}
    for _ in range(30):
        _, detail, _ = request("GET", f"/api/import-tasks/{task_id}")
        last = detail
        status = str(detail.get("status", ""))
        if status not in {"处理中", "processing", ""}:
            return detail
        time.sleep(1)
    return last


def check_frontend():
    req = urllib.request.Request(FRONTEND_URL, method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        assert_true("frontend reachable", resp.status == 200 and "<div id=\"root\"></div>" in body)


def main():
    created_import_task = ""
    created_knowledge = ""
    created_question = ""
    created_paper = ""

    try:
        _, health, _ = request("GET", "/api/java/health")
        assert_true("java health", health["data"]["status"] == "ok")

        _, worker, _ = request("GET", "/api/java/worker")
        assert_true("python worker reachable", worker["data"]["reachable"] is True)

        _, engine, _ = request("GET", "/api/engine")
        assert_true("engine catalog", engine["code"] == "question-engine")

        _, capabilities, _ = request("GET", "/api/capabilities")
        assert_true("capability catalog", len(capabilities) >= 8)

        _, ocr_runtime, _ = request("GET", "/api/capabilities/ocr-flow/runtime")
        provider_status = ocr_runtime.get("providerStatus") or {}
        assert_true(
            "ocr provider executable",
            provider_status.get("installed") is True and not provider_status.get("error"),
            provider_status,
        )

        check_frontend()

        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as file:
            file.write(
                "# 冒烟试卷\n\n"
                "1. 已知 $x+1=2$，求 $x$。\n\nA. 0\nB. 1\nC. 2\nD. 3\n\n"
                "2. 已知 $y=2x$，当 $x=3$ 时，求 $y$。\n"
            )
            paper_path = Path(file.name)
        try:
            body, content_type = multipart(
                {
                    "stage": "高中",
                    "subject": "数学",
                    "grade": "高一",
                    "region": "本地",
                    "year": "2026",
                    "title": "LocalPlatformBusinessSmoke",
                },
                {"paperFile": paper_path},
            )
            _, task, _ = request(
                "POST",
                "/api/import-tasks",
                body,
                headers={"Content-Type": content_type},
                timeout=60,
            )
            created_import_task = task["id"]
            assert_true("import task create", bool(created_import_task))
        finally:
            paper_path.unlink(missing_ok=True)

        detail = wait_import_ready(created_import_task)
        assert_true("import task ready", detail.get("status") in {"待校验", "部分完成", "已完成"})
        assert_true("import task questions", len(detail.get("questions", [])) >= 2)

        source_status, source_body, _ = request("GET", f"/api/import-tasks/{created_import_task}/source/paper")
        assert_true("source preview", source_status == 200 and isinstance(source_body, bytes) and len(source_body) > 0)

        first_question = detail["questions"][0]
        qid = first_question["id"]
        updated = dict(first_question)
        updated["answer"] = "B"
        updated["analysis"] = "由 $x+1=2$ 得 $x=1$。"
        _, saved_question, _ = request("PUT", f"/api/import-tasks/{created_import_task}/questions/{qid}", updated)
        saved_question_body = saved_question.get("question", saved_question)
        assert_true("import question save", saved_question_body.get("answer") == "B")

        second_question = detail["questions"][1]
        with tempfile.NamedTemporaryFile("wb", suffix=".png", delete=False) as image_file:
            image_file.write(b"png-smoke-bytes")
            image_path = Path(image_file.name)
        try:
            body, content_type = multipart({}, {"files": image_path})
            _, upload_result, _ = request(
                "POST",
                f"/api/import-tasks/{created_import_task}/questions/{qid}/images",
                body,
                headers={"Content-Type": content_type},
                timeout=60,
            )
            assert_true("import question image upload", len(upload_result.get("uploaded", [])) == 1)

            _, image_library, _ = request("GET", f"/api/import-tasks/{created_import_task}/image-library")
            library_items = image_library.get("items", [])
            assert_true("import task image library", len(library_items) >= 1)
            image_id = str(library_items[0].get("imageId") or library_items[0].get("id") or "")
            assert_true("import task image library id", bool(image_id))

            _, selected_images, _ = request(
                "POST",
                f"/api/import-tasks/{created_import_task}/questions/{second_question['id']}/images/select",
                {"imageIds": [image_id]},
                timeout=60,
            )
            assert_true("import question image select", len(selected_images.get("images", [])) >= 1)
        finally:
            image_path.unlink(missing_ok=True)

        _, ai_standardized, _ = request(
            "POST",
            f"/api/import-tasks/{created_import_task}/questions/{qid}/standardize/ai",
            {"markdown": saved_question.get("manualMarkdown") or saved_question.get("stemMarkdown")},
            timeout=60,
        )
        assert_true("import question ai standardize", "markdown" in ai_standardized)

        _, ai_analysis, _ = request(
            "POST",
            f"/api/import-tasks/{created_import_task}/questions/{qid}/analysis",
            {
                "manualMarkdown": saved_question.get("manualMarkdown") or saved_question.get("stemMarkdown"),
                "answer": "B",
                "type": saved_question.get("type", ""),
            },
            timeout=60,
        )
        assert_true("import question ai analysis", "analysis" in ai_analysis)

        _, kp, _ = request(
            "POST",
            "/api/knowledge-points",
            {"name": "冒烟知识点", "subject": "数学", "grade": "高一", "description": "smoke"},
        )
        created_knowledge = kp["id"]
        assert_true("knowledge create", bool(created_knowledge))

        _, kp_updated, _ = request(
            "PUT",
            f"/api/knowledge-points/{created_knowledge}",
            {"name": "冒烟知识点更新", "subject": "数学", "grade": "高一", "description": "smoke"},
        )
        assert_true("knowledge update", kp_updated["name"] == "冒烟知识点更新")

        question_payload = {
            "title": "冒烟题目",
            "stage": "高中",
            "subject": "数学",
            "grade": "高一",
            "region": "本地",
            "year": "2026",
            "type": "choice",
            "stemMarkdown": "已知 $x+1=2$，求 $x$。",
            "manualMarkdown": "已知 $x+1=2$，求 $x$。",
            "answer": "B",
            "analysis": "移项得 $x=1$。",
            "knowledgePointIds": [created_knowledge],
            "knowledgePoints": ["冒烟知识点更新"],
            "difficulty": "easy",
            "score": 2,
            "options": [{"label": "A", "content": "0"}, {"label": "B", "content": "1"}],
        }
        _, question, _ = request("POST", "/api/question-bank/questions", question_payload)
        created_question = question["id"]
        assert_true("question create", question["answer"] == "B")

        _, question_detail, _ = request("GET", f"/api/question-bank/questions/{created_question}")
        assert_true("question detail", question_detail["id"] == created_question)

        _, question_list, _ = request("GET", "/api/question-bank/questions?keyword=" + urllib.parse.quote("冒烟"))
        assert_true("question search", question_list.get("total", 0) >= 1)

        paper_payload = {
            "title": "冒烟试卷",
            "subject": "数学",
            "grade": "高一",
            "questionIds": [created_question],
            "header": {"subject": "数学", "grade": "高一"},
            "scores": {created_question: 2},
            "answerDisplay": "teacher",
        }
        _, paper, _ = request("POST", "/api/papers", paper_payload)
        created_paper = paper["id"]
        assert_true("paper create", bool(created_paper))

        _, paper_detail, _ = request("GET", f"/api/papers/{created_paper}")
        assert_true("paper detail", created_question in paper_detail.get("questionIds", []))

        status, export_body, _ = request("GET", f"/api/papers/{created_paper}/export?format=docx&variant=teacher", timeout=90)
        assert_true("paper export", status == 200 and isinstance(export_body, bytes) and len(export_body) > 0)

        _, package, _ = request("GET", f"/api/capabilities/question-processing/jobs/{created_import_task}/question-package")
        assert_true("question package", package["packageVersion"] == "question-package.v1")

        print("本地小平台基础业务冒烟测试通过")
    finally:
        cleanup = [
            ("DELETE", f"/api/papers/{created_paper}") if created_paper else None,
            ("DELETE", f"/api/question-bank/questions/{created_question}") if created_question else None,
            ("DELETE", f"/api/knowledge-points/{created_knowledge}") if created_knowledge else None,
            ("DELETE", f"/api/import-tasks/{created_import_task}") if created_import_task else None,
        ]
        for item in cleanup:
            if item is None:
                continue
            try:
                request(*item)
            except Exception as exc:
                print(f"WARN cleanup failed {item[1]}: {exc}")


if __name__ == "__main__":
    main()
