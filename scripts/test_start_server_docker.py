#!/usr/bin/env python3
"""Executable regression tests for the Docker server launcher."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
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

    def test_ocr_predicate_ignores_api_readiness_only_when_api_is_disabled(self) -> None:
        disabled = json.dumps(
            {"providerStatus": {"installed": True, "runtimeProbeOk": True, "apiEnabled": False, "apiReady": False}}
        )
        enabled = json.dumps(
            {"providerStatus": {"installed": True, "runtimeProbeOk": True, "apiEnabled": True, "apiReady": False}}
        )
        completed = self.run_bash(
            f"""
            printf '%s' '{disabled}' | ocr_runtime_payload_is_ready
            disabled_status=$?
            enabled_status=0
            printf '%s' '{enabled}' | ocr_runtime_payload_is_ready || enabled_status=$?
            printf '%s %s\n' "$disabled_status" "$enabled_status"
            """
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("0 1", completed.stdout.strip())

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

    def test_compose_uses_the_exported_venv_and_commands(self) -> None:
        compose = COMPOSE_PATH.read_text(encoding="utf-8")
        effective_venv = "${HOST_MINERU_VENV:-${PWD}/vendor/mineru-venv}"
        self.assertIn(f"MINERU_COMMAND: ${{MINERU_COMMAND:-{effective_venv}/bin/mineru}}", compose)
        self.assertIn(f"MINERU_API_COMMAND: ${{MINERU_API_COMMAND:-{effective_venv}/bin/mineru-api}}", compose)
        self.assertIn(f'"{effective_venv}:{effective_venv}:ro"', compose)

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
            disabled = subprocess.run(
                ["bash", "-c", host_command],
                env={**base_env, "OCR_PAYLOAD": disabled_payload},
                capture_output=True,
                check=False,
            )
            enabled = subprocess.run(
                ["bash", "-c", host_command],
                env={**base_env, "OCR_PAYLOAD": enabled_payload},
                capture_output=True,
                check=False,
            )
        self.assertEqual(0, disabled.returncode, disabled.stderr.decode(errors="replace"))
        self.assertEqual(1, enabled.returncode, enabled.stderr.decode(errors="replace"))


if __name__ == "__main__":
    unittest.main()
