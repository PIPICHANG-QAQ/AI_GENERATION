#!/usr/bin/env python3
"""Executable regression tests for the Docker server launcher."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("start_server_docker.sh").resolve()
COMPOSE_PATH = SCRIPT_PATH.parents[1] / "docker-compose.server.yml"


class StartServerDockerTest(unittest.TestCase):
    def run_bash(self, body: str, *, timeout: float = 10) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-c", f'source "{SCRIPT_PATH}"\n{body}'],
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )

    def start_http_server(self, handler: type[BaseHTTPRequestHandler]) -> ThreadingHTTPServer:
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def test_default_host_venv_drives_every_mineru_command(self) -> None:
        completed = self.run_bash(
            """
            ROOT_DIR=/tmp/question-engine
            unset HOST_MINERU_VENV MINERU_HOST_COMMAND MINERU_COMMAND MINERU_API_COMMAND
            configure_mineru_environment
            printf '%s\n' "$HOST_MINERU_VENV" "$MINERU_HOST_COMMAND" "$MINERU_COMMAND" "$MINERU_API_COMMAND"
            """
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        venv = "/tmp/question-engine/vendor/mineru-venv"
        self.assertEqual(
            [venv, f"{venv}/bin/mineru", f"{venv}/bin/mineru", f"{venv}/bin/mineru-api"],
            completed.stdout.splitlines(),
        )

    def test_custom_host_venv_is_made_absolute_and_exported(self) -> None:
        completed = self.run_bash(
            """
            ROOT_DIR=/tmp/question-engine
            HOST_MINERU_VENV=custom/mineru
            unset MINERU_HOST_COMMAND MINERU_COMMAND MINERU_API_COMMAND
            configure_mineru_environment
            env | grep -E '^(HOST_MINERU_VENV|MINERU_COMMAND|MINERU_API_COMMAND)=' | sort
            """
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        venv = "/tmp/question-engine/custom/mineru"
        self.assertEqual(
            [
                f"HOST_MINERU_VENV={venv}",
                f"MINERU_API_COMMAND={venv}/bin/mineru-api",
                f"MINERU_COMMAND={venv}/bin/mineru",
            ],
            completed.stdout.splitlines(),
        )

    def test_mismatched_host_command_is_rejected(self) -> None:
        completed = self.run_bash(
            """
            ROOT_DIR=/tmp/question-engine
            HOST_MINERU_VENV=/tmp/question-engine/vendor/mineru-venv
            MINERU_HOST_COMMAND=/some/other/venv/bin/mineru
            configure_mineru_environment
            """
        )
        self.assertEqual(1, completed.returncode)
        self.assertIn("MINERU_HOST_COMMAND", completed.stderr)
        self.assertIn("HOST_MINERU_VENV", completed.stderr)

    def test_ocr_predicate_requires_explicit_boolean_api_mode(self) -> None:
        disabled = json.dumps(
            {"providerStatus": {"installed": True, "runtimeProbeOk": True, "apiEnabled": False, "apiReady": False}}
        )
        enabled = json.dumps(
            {"providerStatus": {"installed": True, "runtimeProbeOk": True, "apiEnabled": True, "apiReady": False}}
        )
        missing = json.dumps({"providerStatus": {"installed": True, "runtimeProbeOk": True, "apiReady": True}})
        null_mode = json.dumps(
            {"providerStatus": {"installed": True, "runtimeProbeOk": True, "apiEnabled": None, "apiReady": True}}
        )
        wrong_type = json.dumps(
            {"providerStatus": {"installed": True, "runtimeProbeOk": True, "apiEnabled": "false", "apiReady": True}}
        )
        completed = self.run_bash(
            f"""
            export PYTHONOPTIMIZE=1
            printf '%s' '{disabled}' | ocr_runtime_payload_is_ready
            disabled_status=$?
            enabled_status=0
            printf '%s' '{enabled}' | ocr_runtime_payload_is_ready || enabled_status=$?
            missing_status=0
            printf '%s' '{missing}' | ocr_runtime_payload_is_ready || missing_status=$?
            null_status=0
            printf '%s' '{null_mode}' | ocr_runtime_payload_is_ready || null_status=$?
            type_status=0
            printf '%s' '{wrong_type}' | ocr_runtime_payload_is_ready || type_status=$?
            printf '%s %s %s %s %s\n' "$disabled_status" "$enabled_status" "$missing_status" "$null_status" "$type_status"
            """
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("0 1 1 1 1", completed.stdout.strip())

    def test_readiness_retries_java_and_ocr_under_one_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            java_count = Path(temp_dir) / "java-count"
            ocr_count = Path(temp_dir) / "ocr-count"
            completed = self.run_bash(
                f"""
                java_health_ready() {{
                  n=0; [[ -f '{java_count}' ]] && n=$(cat '{java_count}')
                  n=$((n + 1)); printf '%s' "$n" >'{java_count}'
                  [[ "$n" -ge 2 ]]
                }}
                ocr_runtime_ready() {{
                  n=0; [[ -f '{ocr_count}' ]] && n=$(cat '{ocr_count}')
                  n=$((n + 1)); printf '%s' "$n" >'{ocr_count}'
                  [[ "$n" -ge 3 ]]
                }}
                QUESTION_ENGINE_STARTUP_TIMEOUT_SECONDS=5
                QUESTION_ENGINE_STARTUP_POLL_SECONDS=0.01
                wait_for_server_readiness
                printf '%s %s\n' "$(cat '{java_count}')" "$(cat '{ocr_count}')"
                """
            )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("3 3", completed.stdout.strip())

    def test_timeout_reports_diagnostics_and_removes_failed_service(self) -> None:
        completed = self.run_bash(
            """
            server_readiness_probe() { return 1; }
            show_startup_diagnostics() { printf 'diagnostics-called\n' >&2; }
            cleanup_failed_service() { printf 'cleanup-called\n' >&2; }
            QUESTION_ENGINE_STARTUP_TIMEOUT_SECONDS=0
            QUESTION_ENGINE_STARTUP_POLL_SECONDS=0
            status=0
            require_server_readiness || status=$?
            printf 'status=%s\n' "$status"
            """
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("status=1", completed.stdout.strip())
        self.assertIn("diagnostics-called", completed.stderr)
        self.assertIn("cleanup-called", completed.stderr)

    def test_default_deadline_is_600_seconds(self) -> None:
        completed = self.run_bash(
            """
            unset QUESTION_ENGINE_STARTUP_TIMEOUT_SECONDS
            printf '%s\n' "$(startup_timeout_seconds)"
            """
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("600", completed.stdout.strip())

    def test_api_enabled_is_normalized_case_insensitively_and_invalid_values_fail(self) -> None:
        completed = self.run_bash(
            """
            set +e
            MINERU_API_ENABLED=TRUE
            normalize_mineru_api_enabled true
            upper_status=$?
            upper_value=$MINERU_API_ENABLED
            MINERU_API_ENABLED=False
            normalize_mineru_api_enabled true
            mixed_status=$?
            mixed_value=$MINERU_API_ENABLED
            MINERU_API_ENABLED=maybe
            normalize_mineru_api_enabled true
            invalid_status=$?
            printf '%s %s %s %s %s\n' "$upper_status" "$upper_value" "$mixed_status" "$mixed_value" "$invalid_status"
            """
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("0 true 0 false 1", completed.stdout.strip())
        self.assertIn("MINERU_API_ENABLED", completed.stderr)

    def test_hard_deadline_bounds_hanging_http_and_cleanup_runs(self) -> None:
        class HangingHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                time.sleep(10)

            def log_message(self, _format, *_args):
                return

        server = self.start_http_server(HangingHandler)
        with tempfile.TemporaryDirectory() as temp_dir:
            cleanup_log = Path(temp_dir) / "cleanup.log"
            url = f"http://127.0.0.1:{server.server_port}/hang"
            body = f"""
health_url='{url}'
ocr_runtime_url='{url}'
COMPOSE_FILE=docker-compose.server.yml
docker() {{ printf '%s\n' "$*" >>'{cleanup_log}'; }}
QUESTION_ENGINE_STARTUP_TIMEOUT_SECONDS=1
QUESTION_ENGINE_STARTUP_POLL_SECONDS=0.01
status=0
require_server_readiness || status=$?
printf 'status=%s\n' "$status"
"""
            command = ["bash", "-c", f'source "{SCRIPT_PATH}"\n{body}']
            started = time.monotonic()
            process = subprocess.Popen(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            timed_out = False
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate(timeout=2)
            elapsed = time.monotonic() - started

            self.assertFalse(timed_out, f"launcher exceeded hard deadline: {stderr}")
            self.assertEqual(0, process.returncode, stderr)
            self.assertEqual("status=1", stdout.strip())
            self.assertLess(elapsed, 5)
            self.assertTrue(cleanup_log.exists(), "cleanup did not run after readiness timeout")
            cleanup = cleanup_log.read_text(encoding="utf-8")
            self.assertIn("stop question-engine", cleanup)
            self.assertIn("rm -f question-engine", cleanup)

    def test_real_http_readiness_retries_then_succeeds_before_deadline(self) -> None:
        request_counts = {"/api/java/health": 0, "/api/capabilities/ocr-flow/runtime": 0}

        class RetryHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                request_counts[self.path] += 1
                if request_counts[self.path] == 1:
                    self.send_response(503)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                if self.path.endswith("/runtime"):
                    self.wfile.write(
                        b'{"providerStatus":{"installed":true,"runtimeProbeOk":true,'
                        b'"apiEnabled":false,"apiReady":false}}'
                    )
                else:
                    self.wfile.write(b'{"status":"ok"}')

            def log_message(self, _format, *_args):
                return

        server = self.start_http_server(RetryHandler)
        base_url = f"http://127.0.0.1:{server.server_port}"
        completed = self.run_bash(
            f"""
            health_url='{base_url}/api/java/health'
            ocr_runtime_url='{base_url}/api/capabilities/ocr-flow/runtime'
            QUESTION_ENGINE_STARTUP_TIMEOUT_SECONDS=5
            QUESTION_ENGINE_STARTUP_POLL_SECONDS=0.05
            wait_for_server_readiness
            """,
            timeout=8,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertGreaterEqual(request_counts["/api/java/health"], 2)
        self.assertGreaterEqual(request_counts["/api/capabilities/ocr-flow/runtime"], 2)

    def test_compose_derives_commands_only_from_the_mounted_host_venv(self) -> None:
        compose = COMPOSE_PATH.read_text(encoding="utf-8")
        effective_venv = "${HOST_MINERU_VENV:-${PWD}/vendor/mineru-venv}"
        values = {
            line.strip().split(":", 1)[0]: line.strip().split(":", 1)[1].strip().strip('"')
            for line in compose.splitlines()
            if line.strip().startswith(("MINERU_COMMAND:", "MINERU_API_COMMAND:"))
        }
        volume_template = next(
            line.strip().removeprefix("- ").strip('"')
            for line in compose.splitlines()
            if line.strip().startswith(f'- "{effective_venv}:')
        )
        self.assertEqual(f"{effective_venv}/bin/mineru", values["MINERU_COMMAND"])
        self.assertEqual(f"{effective_venv}/bin/mineru-api", values["MINERU_API_COMMAND"])
        self.assertEqual(f"{effective_venv}:{effective_venv}:ro", volume_template)
        self.assertNotIn("${MINERU_COMMAND", compose)
        self.assertNotIn("${MINERU_API_COMMAND", compose)

        mounted_venv = "/srv/question-engine/vendor/mineru-venv"
        stray_command = "/unmounted/venv/bin/mineru"
        stray_api_command = "/another/venv/bin/mineru-api"
        resolved_command = values["MINERU_COMMAND"].replace(effective_venv, mounted_venv)
        resolved_api_command = values["MINERU_API_COMMAND"].replace(effective_venv, mounted_venv)
        resolved_volume = volume_template.replace(effective_venv, mounted_venv)
        self.assertEqual(f"{mounted_venv}/bin/mineru", resolved_command)
        self.assertEqual(f"{mounted_venv}/bin/mineru-api", resolved_api_command)
        self.assertEqual(f"{mounted_venv}:{mounted_venv}:ro", resolved_volume)
        self.assertNotEqual(stray_command, resolved_command)
        self.assertNotEqual(stray_api_command, resolved_api_command)

    def test_compose_health_command_is_valid_and_uses_conditional_api_predicate(self) -> None:
        lines = COMPOSE_PATH.read_text(encoding="utf-8").splitlines()
        marker = next(index for index, line in enumerate(lines) if line.strip() == "- >-")
        command_parts: list[str] = []
        for line in lines[marker + 1 :]:
            if line.startswith("      interval:"):
                break
            command_parts.append(line.strip())
        command = " ".join(command_parts)
        self.assertNotIn("assert ", command)
        syntax = subprocess.run(["bash", "-n"], input=command, text=True, capture_output=True, check=False)
        self.assertEqual(0, syntax.returncode, syntax.stderr)

        with tempfile.TemporaryDirectory() as temp_dir:
            curl = Path(temp_dir) / "curl"
            curl.write_text(
                """#!/usr/bin/env python3
import json, os, sys
url = sys.argv[-1]
if url.endswith('/api/java/health'):
    print('{}')
else:
    print(os.environ['OCR_PAYLOAD'])
""",
                encoding="utf-8",
            )
            curl.chmod(0o755)
            host_command = command.replace("/opt/question-engine/venv/bin/python", sys.executable)
            base_env = {**os.environ, "PATH": f"{temp_dir}:{os.environ['PATH']}"}
            disabled_payload = json.dumps(
                {
                    "providerStatus": {
                        "installed": True,
                        "runtimeProbeOk": True,
                        "apiEnabled": False,
                        "apiReady": False,
                    }
                }
            )
            enabled_payload = json.dumps(
                {
                    "providerStatus": {
                        "installed": True,
                        "runtimeProbeOk": True,
                        "apiEnabled": True,
                        "apiReady": False,
                    }
                }
            )
            missing_payload = json.dumps(
                {"providerStatus": {"installed": True, "runtimeProbeOk": True, "apiReady": True}}
            )
            wrong_type_payload = json.dumps(
                {
                    "providerStatus": {
                        "installed": True,
                        "runtimeProbeOk": True,
                        "apiEnabled": "false",
                        "apiReady": True,
                    }
                }
            )
            disabled = subprocess.run(
                ["bash", "-c", host_command],
                env={**base_env, "OCR_PAYLOAD": disabled_payload, "PYTHONOPTIMIZE": "1"},
                capture_output=True,
                check=False,
            )
            enabled = subprocess.run(
                ["bash", "-c", host_command],
                env={**base_env, "OCR_PAYLOAD": enabled_payload, "PYTHONOPTIMIZE": "1"},
                capture_output=True,
                check=False,
            )
            missing = subprocess.run(
                ["bash", "-c", host_command],
                env={**base_env, "OCR_PAYLOAD": missing_payload, "PYTHONOPTIMIZE": "1"},
                capture_output=True,
                check=False,
            )
            wrong_type = subprocess.run(
                ["bash", "-c", host_command],
                env={**base_env, "OCR_PAYLOAD": wrong_type_payload, "PYTHONOPTIMIZE": "1"},
                capture_output=True,
                check=False,
            )
        self.assertEqual(0, disabled.returncode, disabled.stderr.decode(errors="replace"))
        self.assertEqual(1, enabled.returncode, enabled.stderr.decode(errors="replace"))
        self.assertEqual(1, missing.returncode, missing.stderr.decode(errors="replace"))
        self.assertEqual(1, wrong_type.returncode, wrong_type.stderr.decode(errors="replace"))


if __name__ == "__main__":
    unittest.main()
