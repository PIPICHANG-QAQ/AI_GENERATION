#!/usr/bin/env python3
"""Basic deployment smoke checks.

This script verifies that the local deployment is up and wired together. It
does not require MinerU or an LLM API key.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


BASE_URL = os.environ.get("AI_GENERATION_BASE_URL", "http://localhost:8018").rstrip("/")
FRONTEND_URL = os.environ.get("AI_GENERATION_FRONTEND_URL", "http://localhost:5173").rstrip("/")
PYTHON_WORKER_URL = os.environ.get("PYTHON_WORKER_URL", "http://127.0.0.1:8000").rstrip("/")


def request_json(url: str, timeout: int = 20) -> Any:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type:
            return json.loads(raw.decode("utf-8") or "{}")
        return raw.decode("utf-8", errors="replace")


def ok(name: str, condition: bool, detail: Any = "") -> None:
    if not condition:
        raise AssertionError(f"{name} failed: {detail}")
    print(f"OK {name}")


def check_frontend() -> None:
    if not FRONTEND_URL:
        print("SKIP frontend reachable")
        return
    body = request_json(FRONTEND_URL)
    ok("frontend reachable", isinstance(body, str) and "<div id=\"root\"></div>" in body)


def main() -> None:
    worker_health = request_json(f"{PYTHON_WORKER_URL}/api/health")
    ok("python worker health", isinstance(worker_health, dict) and worker_health.get("status") == "ok", worker_health)

    java_health = request_json(f"{BASE_URL}/api/java/health")
    ok("java health", java_health.get("data", {}).get("status") == "ok", java_health)

    worker_bridge = request_json(f"{BASE_URL}/api/java/worker")
    ok("java worker bridge", worker_bridge.get("data", {}).get("reachable") is True, worker_bridge)

    engine = request_json(f"{BASE_URL}/api/engine")
    ok("engine catalog", engine.get("code") == "question-engine", engine)

    capabilities = request_json(f"{BASE_URL}/api/capabilities")
    ok("capability catalog", isinstance(capabilities, list) and len(capabilities) >= 8, capabilities)

    import_tasks = request_json(f"{BASE_URL}/api/import-tasks")
    ok("import task bridge list", isinstance(import_tasks, dict) and isinstance(import_tasks.get("items"), list), import_tasks)

    check_frontend()
    print("basic deployment smoke passed")


if __name__ == "__main__":
    main()
