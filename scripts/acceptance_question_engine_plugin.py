#!/usr/bin/env python3
"""Platform-level acceptance checks for the question-engine delivery package."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any


TERMINAL = {"WAITING_REVIEW", "PARTIAL_COMPLETED", "COMPLETED", "FAILED", "RETRYABLE"}
SUCCESSFUL = {"WAITING_REVIEW", "PARTIAL_COMPLETED", "COMPLETED"}
PROCESSING_TEXT = {"处理中", "processing", ""}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("QUESTION_ENGINE_BASE_URL", "http://localhost:8018"))
    parser.add_argument("--paper-file", type=Path)
    parser.add_argument("--answer-file", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--poll-seconds", type=float, default=2)
    parser.add_argument("--skip-ai", action="store_true")
    parser.add_argument("--skip-callback", action="store_true")
    parser.add_argument("--callback-url")
    parser.add_argument("--callback-secret", default="question-engine-acceptance-secret")
    parser.add_argument("--large-file-mb", type=int, default=0)
    parser.add_argument("--headers", action="append", default=[], help="extra header, format Name:Value")
    return parser.parse_args()


class Client:
    def __init__(self, base_url: str, headers: dict[str, str]):
        self.base_url = base_url.rstrip("/")
        self.headers = headers

    def request(
            self,
            method: str,
            path: str,
            payload: bytes | dict[str, Any] | None = None,
            headers: dict[str, str] | None = None,
            timeout: int = 60,
            expect_error: bool = False,
    ) -> tuple[int, Any, dict[str, str]]:
        body: bytes | None
        merged = dict(self.headers)
        merged.update(headers or {})
        if isinstance(payload, bytes):
            body = payload
        elif payload is None:
            body = None
        else:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            merged.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(self.base_url + path, data=body, headers=merged, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                parsed = parse_body(raw, resp.headers.get("content-type", ""))
                return resp.status, parsed, dict(resp.headers)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            parsed = parse_body(raw, exc.headers.get("content-type", ""))
            if expect_error:
                return exc.code, parsed, dict(exc.headers)
            raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {raw[:800]!r}") from exc


def parse_body(raw: bytes, content_type: str) -> Any:
    if "application/json" in content_type:
        return json.loads(raw.decode("utf-8") or "{}")
    return raw


def ok(name: str, condition: bool, detail: Any = "") -> None:
    if not condition:
        raise AssertionError(f"{name} failed: {detail}")
    print(f"OK {name}")


def extra_headers(items: list[str]) -> dict[str, str]:
    headers = {
        "X-Tenant-Id": "acceptance-tenant",
        "X-Operator-Id": "acceptance-operator",
        "X-Source-App": "question-engine-acceptance",
        "X-Trace-Id": "acceptance-" + uuid.uuid4().hex,
    }
    for item in items:
        if ":" not in item:
            raise SystemExit(f"invalid --headers value: {item}")
        name, value = item.split(":", 1)
        headers[name.strip()] = value.strip()
    return headers


def multipart(fields: dict[str, str], files: dict[str, Path]) -> tuple[bytes, str]:
    boundary = "----question-engine-acceptance-" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        chunks.append(str(value).encode("utf-8"))
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


def create_sample_paper(workdir: Path, large_file_mb: int) -> Path:
    path = workdir / "acceptance-paper.md"
    text = (
        "# 脱敏验收样卷\n\n"
        "1. 已知 $x+1=2$，求 $x$。\n\n"
        "A. 0\nB. 1\nC. 2\nD. 3\n\n"
        "2. 已知 $y=2x$，当 $x=3$ 时，求 $y$。\n"
    )
    if large_file_mb > 0:
        target = large_file_mb * 1024 * 1024
        repeated = text
        while len(repeated.encode("utf-8")) < target:
            repeated += "\n" + text
        text = repeated
    path.write_text(text, encoding="utf-8")
    return path


def create_sample_answer(workdir: Path) -> Path:
    path = workdir / "acceptance-answer.md"
    path.write_text("# 脱敏答案\n\n1. B\n2. 6\n", encoding="utf-8")
    return path


def create_job(client: Client, paper: Path, answer: Path | None) -> dict[str, Any]:
    files = {"paperFile": paper}
    if answer is not None:
        files["answerFile"] = answer
    body, content_type = multipart(
        {
            "stage": "高中",
            "subject": "数学",
            "grade": "高一",
            "region": "验收",
            "year": "2026",
            "title": "QuestionEngineAcceptance_" + uuid.uuid4().hex[:8],
        },
        files,
    )
    _, job, _ = client.request(
        "POST",
        "/api/capabilities/question-processing/jobs",
        body,
        {"Content-Type": content_type},
        timeout=120,
    )
    ok("create processing job", bool(job.get("jobId")), job)
    return job


def wait_job(client: Client, job_id: str, timeout_seconds: int, poll_seconds: float) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last: dict[str, Any] = {}
    while time.time() < deadline:
        _, job, _ = client.request("GET", f"/api/capabilities/question-processing/jobs/{job_id}", timeout=90)
        last = job
        processing_status = str(job.get("processingStatus") or "")
        local_status = str(job.get("status") or "")
        if processing_status in TERMINAL or local_status not in PROCESSING_TEXT:
            ok("processing job reached non-processing state", True, processing_status or local_status)
            return job
        time.sleep(poll_seconds)
    raise AssertionError(f"job polling timed out: {last}")


def upload_question_image(client: Client, job_id: str, question_id: str, workdir: Path) -> None:
    image = workdir / "acceptance-image.png"
    image.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFBQIAhL9k4QAAAABJRU5ErkJggg=="))
    body, content_type = multipart({}, {"files": image})
    _, result, _ = client.request(
        "POST",
        f"/api/import-tasks/{job_id}/questions/{question_id}/images",
        body,
        {"Content-Type": content_type},
        timeout=90,
    )
    ok("question image upload", "uploaded" in result or "images" in result, result)


class CallbackRecorder(BaseHTTPRequestHandler):
    received: list[dict[str, Any]] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length)
        CallbackRecorder.received.append({
            "path": self.path,
            "headers": dict(self.headers),
            "body": body,
            "bodyText": body.decode("utf-8", errors="replace"),
        })
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


def callback_url_from_server() -> tuple[HTTPServer, str]:
    server = HTTPServer(("127.0.0.1", 0), CallbackRecorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}/callback"


def callback_check(client: Client, callback_url: str, secret: str) -> None:
    _, event, _ = client.request(
        "POST",
        "/api/capabilities/callback-flow/test",
        {
            "callbackUrl": callback_url,
            "eventType": "acceptance.test",
            "aggregateType": "acceptance",
            "aggregateId": "acceptance-" + uuid.uuid4().hex[:8],
            "idempotencyKey": "acceptance-" + uuid.uuid4().hex,
            "secret": secret,
            "payload": {"message": "question-engine acceptance"},
        },
        timeout=60,
    )
    ok("callback event created", bool(event.get("id") or event.get("eventId")), event)
    _, events, _ = client.request("GET", "/api/capabilities/callback-flow/events", timeout=60)
    ok("callback events query", isinstance(events, dict) and "items" in events, events)


def invalid_file_check(client: Client, workdir: Path) -> None:
    invalid = workdir / "invalid.exe"
    invalid.write_text("not a supported question file", encoding="utf-8")
    body, content_type = multipart(
        {"title": "InvalidFileAcceptance", "subject": "数学"},
        {"paperFile": invalid},
    )
    status, payload, _ = client.request(
        "POST",
        "/api/capabilities/question-processing/jobs",
        body,
        {"Content-Type": content_type},
        timeout=60,
        expect_error=True,
    )
    ok("invalid file rejected", status >= 400, {"status": status, "payload": payload})


def question_package_shape_check(package: dict[str, Any]) -> str:
    questions = package.get("questions") or []
    ok("question package has questions", len(questions) >= 1, package)
    first = questions[0]
    required_fields = [
        "questionId",
        "stemMarkdown",
        "options",
        "images",
        "mathValidation",
        "sourceEvidence",
    ]
    missing = [field for field in required_fields if field not in first]
    ok("question package first question required fields", not missing, {"missing": missing, "question": first})
    first_question_id = str(first.get("questionId") or first.get("id") or "")
    ok("first question id", bool(first_question_id), first)
    return first_question_id


def source_preview_check(client: Client, job_id: str) -> None:
    _, source, headers = client.request("GET", f"/api/import-tasks/{job_id}/source/paper", timeout=90)
    ok("source preview response", isinstance(source, bytes) and len(source) > 0, headers)


def callback_signature_check(received: dict[str, Any], secret: str) -> None:
    signature = received["headers"].get("X-Question-Engine-Signature")
    ok("callback signature header", bool(signature and signature.startswith("sha256=")), received["headers"])
    expected = hmac.new(secret.encode("utf-8"), received["body"], hashlib.sha256).hexdigest()
    ok(
        "callback signature hmac",
        hmac.compare_digest(signature.removeprefix("sha256="), expected),
        {"expected": "sha256=" + expected, "actual": signature},
    )


def main() -> None:
    args = parse_args()
    client = Client(args.base_url, extra_headers(args.headers))
    with tempfile.TemporaryDirectory(prefix="question-engine-acceptance-") as tmp:
        workdir = Path(tmp)
        paper = args.paper_file or create_sample_paper(workdir, args.large_file_mb)
        answer = args.answer_file or create_sample_answer(workdir)

        _, health, _ = client.request("GET", "/api/java/health")
        ok("java health", health.get("success") is True or health.get("status") == "ok", health)
        _, worker, _ = client.request("GET", "/api/java/worker")
        ok("worker reachable", worker.get("data", {}).get("reachable") is True or worker.get("reachable") is True, worker)
        _, capabilities, _ = client.request("GET", "/api/capabilities")
        ok("capability catalog includes question-processing", any(item.get("code") == "question-processing" for item in capabilities), capabilities)
        _, interfaces, _ = client.request("GET", "/api/engine/interfaces")
        ok("engine interfaces", isinstance(interfaces, list) and len(interfaces) > 0, interfaces)
        _, ocr_runtime, _ = client.request("GET", "/api/capabilities/ocr-flow/runtime")
        if isinstance(ocr_runtime, dict):
            provider = ocr_runtime.get("provider") or ocr_runtime.get("selectedProvider")
            provider_status = ocr_runtime.get("providerStatus", {})
        else:
            provider = None
            provider_status = {}
        ok(
            "ocr runtime",
            bool(provider) and provider_status.get("installed") is not False,
            ocr_runtime,
        )

        job = create_job(client, paper, answer)
        job_id = str(job["jobId"])
        final_job = wait_job(client, job_id, args.timeout_seconds, args.poll_seconds)
        ok("job status is usable", str(final_job.get("processingStatus")) in SUCCESSFUL or str(final_job.get("status")) in {"待校验", "部分完成", "已完成"}, final_job)

        _, package, _ = client.request("GET", f"/api/capabilities/question-processing/jobs/{job_id}/question-package", timeout=90)
        ok("question package version", package.get("packageVersion") == "question-package.v1", package)
        first_question_id = question_package_shape_check(package)
        source_preview_check(client, job_id)
        questions = package.get("questions") or []

        _, image_library, _ = client.request("GET", f"/api/import-tasks/{job_id}/image-library", timeout=60)
        ok("image library response", isinstance(image_library, dict) and "items" in image_library, image_library)
        upload_question_image(client, job_id, first_question_id, workdir)

        if not args.skip_ai:
            _, standardized, _ = client.request(
                "POST",
                f"/api/import-tasks/{job_id}/questions/{first_question_id}/standardize/ai",
                {"markdown": questions[0].get("stemMarkdown") or "1. 已知 x+1=2，求 x。"},
                timeout=120,
            )
            ok("ai standardize response", "markdown" in standardized or "jobId" in standardized, standardized)

        if not args.skip_callback:
            server = None
            callback_url = args.callback_url
            if not callback_url:
                server, callback_url = callback_url_from_server()
            try:
                callback_check(client, callback_url, args.callback_secret)
                if server is not None:
                    time.sleep(1)
                    ok("local callback received", len(CallbackRecorder.received) >= 1, CallbackRecorder.received)
                    callback_signature_check(CallbackRecorder.received[-1], args.callback_secret)
            finally:
                if server is not None:
                    server.shutdown()

        invalid_file_check(client, workdir)

    print("question-engine plugin acceptance passed.")


if __name__ == "__main__":
    main()
