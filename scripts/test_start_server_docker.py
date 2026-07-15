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
ENTRYPOINT_PATH = SCRIPT_PATH.with_name("docker-entrypoint.sh")
COMPOSE_PATH = SCRIPT_PATH.parents[1] / "docker-compose.server.yml"
ENV_EXAMPLE_PATH = SCRIPT_PATH.parents[1] / ".env.example"
README_PATH = SCRIPT_PATH.parents[1] / "README.md"
OPERATIONS_GUIDE_PATH = SCRIPT_PATH.parents[1] / "docs" / "delivery" / "OPERATIONS_GUIDE.md"
DELIVERY_PACKAGE_PATH = SCRIPT_PATH.parents[1] / "docs" / "delivery" / "DELIVERY_PACKAGE.md"
RUNBOOK_PATH = SCRIPT_PATH.parents[1] / "docs" / "server" / "RUNBOOK.md"
RECOVERY_PLAN_PATH = (
    SCRIPT_PATH.parents[1]
    / "docs"
    / "superpowers"
    / "plans"
    / "2026-07-15-production-recovery-and-ocr-readiness.md"
)
HEALTH_PAYLOAD_CASES = (
    (
        "disabled",
        {"providerStatus": {"installed": True, "runtimeProbeOk": True, "apiEnabled": False, "apiReady": False}},
        0,
    ),
    (
        "disabled-without-api-ready",
        {"providerStatus": {"installed": True, "runtimeProbeOk": True, "apiEnabled": False}},
        0,
    ),
    (
        "enabled-ready",
        {"providerStatus": {"installed": True, "runtimeProbeOk": True, "apiEnabled": True, "apiReady": True}},
        0,
    ),
    (
        "enabled-not-ready",
        {"providerStatus": {"installed": True, "runtimeProbeOk": True, "apiEnabled": True, "apiReady": False}},
        1,
    ),
    (
        "enabled-missing-ready",
        {"providerStatus": {"installed": True, "runtimeProbeOk": True, "apiEnabled": True}},
        1,
    ),
    (
        "enabled-null-ready",
        {"providerStatus": {"installed": True, "runtimeProbeOk": True, "apiEnabled": True, "apiReady": None}},
        1,
    ),
    (
        "enabled-wrong-ready-type",
        {"providerStatus": {"installed": True, "runtimeProbeOk": True, "apiEnabled": True, "apiReady": "true"}},
        1,
    ),
    ("missing-mode", {"providerStatus": {"installed": True, "runtimeProbeOk": True, "apiReady": True}}, 1),
    (
        "null-mode",
        {"providerStatus": {"installed": True, "runtimeProbeOk": True, "apiEnabled": None, "apiReady": True}},
        1,
    ),
    (
        "wrong-mode-type",
        {"providerStatus": {"installed": True, "runtimeProbeOk": True, "apiEnabled": "false", "apiReady": True}},
        1,
    ),
    (
        "not-installed",
        {"providerStatus": {"installed": False, "runtimeProbeOk": True, "apiEnabled": False, "apiReady": False}},
        1,
    ),
    (
        "missing-installed",
        {"providerStatus": {"runtimeProbeOk": True, "apiEnabled": False, "apiReady": False}},
        1,
    ),
    (
        "null-installed",
        {"providerStatus": {"installed": None, "runtimeProbeOk": True, "apiEnabled": False, "apiReady": False}},
        1,
    ),
    (
        "wrong-installed-type",
        {"providerStatus": {"installed": 1, "runtimeProbeOk": True, "apiEnabled": False, "apiReady": False}},
        1,
    ),
    (
        "runtime-failed",
        {"providerStatus": {"installed": True, "runtimeProbeOk": False, "apiEnabled": False, "apiReady": False}},
        1,
    ),
    (
        "missing-runtime",
        {"providerStatus": {"installed": True, "apiEnabled": False, "apiReady": False}},
        1,
    ),
    (
        "null-runtime",
        {"providerStatus": {"installed": True, "runtimeProbeOk": None, "apiEnabled": False, "apiReady": False}},
        1,
    ),
    (
        "wrong-runtime-type",
        {"providerStatus": {"installed": True, "runtimeProbeOk": "true", "apiEnabled": False, "apiReady": False}},
        1,
    ),
    ("missing-provider-status", {}, 1),
    ("null-provider-status", {"providerStatus": None}, 1),
    ("wrong-provider-status-type", {"providerStatus": []}, 1),
)


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

    def test_server_artifact_build_cleans_maven_output_before_packaging(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            maven_args = root / "maven-args"
            completed = self.run_bash(
                f"""
                ROOT_DIR='{root}'
                mkdir -p "$ROOT_DIR/backend" "$ROOT_DIR/local-platform/node_modules"
                cd "$ROOT_DIR"
                mvn() {{
                  printf '%s\n' "$*" >'{maven_args}'
                  mkdir -p target
                  : >target/ai-question-bank-test.jar
                }}
                npm() {{ :; }}
                build_server_artifacts
                """
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual("clean -DskipTests package", maven_args.read_text(encoding="utf-8").strip())

    def test_server_artifact_build_without_maven_uses_existing_jar(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            npm_args = root / "npm-args"
            completed = self.run_bash(
                f"""
                ROOT_DIR='{root}'
                mkdir -p "$ROOT_DIR/backend/target" "$ROOT_DIR/local-platform/node_modules"
                : >"$ROOT_DIR/backend/target/ai-question-bank-existing.jar"
                cd "$ROOT_DIR"
                command() {{
                  if [[ "${{1-}}" == "-v" && "${{2-}}" == "mvn" ]]; then return 1; fi
                  builtin command "$@"
                }}
                npm() {{ printf '%s\n' "$*" >>'{npm_args}'; }}
                build_server_artifacts
                """
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual("run build", npm_args.read_text(encoding="utf-8").strip())

    def test_server_artifact_build_without_maven_or_jar_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            status_file = root / "status"
            npm_args = root / "npm-args"
            completed = self.run_bash(
                f"""
                ROOT_DIR='{root}'
                mkdir -p "$ROOT_DIR/backend/target" "$ROOT_DIR/local-platform/node_modules"
                cd "$ROOT_DIR"
                command() {{
                  if [[ "${{1-}}" == "-v" && "${{2-}}" == "mvn" ]]; then return 1; fi
                  builtin command "$@"
                }}
                npm() {{ printf '%s\n' "$*" >>'{npm_args}'; }}
                set +e
                build_server_artifacts
                printf '%s\n' "$?" >'{status_file}'
                """
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertNotEqual("0", status_file.read_text(encoding="utf-8").strip())
            self.assertFalse(npm_args.exists())

    def test_server_artifact_build_maven_failure_does_not_use_stale_jar(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            status_file = root / "status"
            npm_args = root / "npm-args"
            completed = self.run_bash(
                f"""
                ROOT_DIR='{root}'
                mkdir -p "$ROOT_DIR/backend/target" "$ROOT_DIR/local-platform/node_modules"
                : >"$ROOT_DIR/backend/target/ai-question-bank-stale.jar"
                cd "$ROOT_DIR"
                mvn() {{ return 42; }}
                npm() {{ printf '%s\n' "$*" >>'{npm_args}'; }}
                set +e
                build_server_artifacts
                printf '%s\n' "$?" >'{status_file}'
                """
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertNotEqual("0", status_file.read_text(encoding="utf-8").strip())
            self.assertFalse(npm_args.exists())

    def test_task8_java_build_cleans_preserved_target_before_packaging(self) -> None:
        plan = RECOVERY_PLAN_PATH.read_text(encoding="utf-8")
        task8 = plan.split("## Task 8", 1)[1].split("## Task 9", 1)[0]
        readme = README_PATH.read_text(encoding="utf-8")
        readme_server_docker = readme.split("## 服务器 Docker 部署", 1)[1]
        operations = OPERATIONS_GUIDE_PATH.read_text(encoding="utf-8")
        operations_server_docker = operations.split("### 5.1 单机 Docker Compose 部署", 1)[1].split("### 5.2", 1)[0]
        delivery = DELIVERY_PACKAGE_PATH.read_text(encoding="utf-8")
        delivery_server_docker = delivery.split("如果要在目标服务器使用 `docker-compose.server.yml`", 1)[1].split(
            "## 5. 迁移后启动流程", 1
        )[0]
        cases = (
            ("Task8", task8, "mvn -f backend/pom.xml clean -DskipTests package"),
            ("README server Docker", readme_server_docker, "(cd backend && mvn clean -DskipTests package)"),
            (
                "operations server Docker",
                operations_server_docker,
                "(cd backend && mvn clean -DskipTests package)",
            ),
            (
                "delivery package server Docker",
                delivery_server_docker,
                "(cd backend && mvn clean -DskipTests package)",
            ),
        )
        for name, section, command in cases:
            with self.subTest(name=name):
                self.assertIn(command, section)

    def test_task8_rollback_rebuilds_application_artifacts_before_restart(self) -> None:
        plan = RECOVERY_PLAN_PATH.read_text(encoding="utf-8")
        rollback = plan.split("### Step 8：失败回滚路径", 1)[1].split("## Task 9", 1)[0]
        commands = (
            'rsync -a --delete',
            'mvn -f backend/pom.xml clean -DskipTests package',
            'npm --prefix local-platform ci && npm --prefix local-platform run build',
            'docker compose -f docker-compose.server.yml up -d --build question-engine',
        )
        for command in commands:
            self.assertIn(command, rollback)
        positions = [rollback.index(command) for command in commands]
        self.assertEqual(sorted(positions), positions)

    def test_runbook_rebuilds_application_artifacts_before_compose_start(self) -> None:
        runbook = RUNBOOK_PATH.read_text(encoding="utf-8")
        rebuild = runbook.split("## 重建并启动服务", 1)[1].split("## 原子重建 MinerU venv", 1)[0]
        commands = (
            'mvn -f backend/pom.xml clean -DskipTests package',
            'npm --prefix local-platform ci && npm --prefix local-platform run build',
            'docker compose -f docker-compose.server.yml build question-engine',
            'docker compose -f docker-compose.server.yml up -d --force-recreate question-engine',
        )
        for command in commands:
            self.assertIn(command, rebuild)
        positions = [rebuild.index(command) for command in commands]
        self.assertEqual(sorted(positions), positions)

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

    def test_ocr_predicate_complete_matrix_with_and_without_python_optimize(self) -> None:
        for optimize in ("0", "1"):
            for name, payload, expected_status in HEALTH_PAYLOAD_CASES:
                with self.subTest(optimize=optimize, case=name):
                    completed = self.run_bash(
                        f"""
                        set +e
                        export PYTHONOPTIMIZE={optimize}
                        printf '%s' '{json.dumps(payload)}' | ocr_runtime_payload_is_ready
                        printf '%s\n' "$?"
                        """
                    )
                    self.assertEqual(0, completed.returncode, completed.stderr)
                    self.assertEqual(str(expected_status), completed.stdout.strip())

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
        with tempfile.TemporaryDirectory() as temp_dir:
            events = Path(temp_dir) / "events"
            completed = self.run_bash(
                f"""
            server_readiness_probe() {{ return 1; }}
            show_startup_diagnostics() {{ printf 'diagnostics\n' >>'{events}'; }}
            cleanup_failed_service() {{ printf 'cleanup\n' >>'{events}'; }}
            QUESTION_ENGINE_STARTUP_TIMEOUT_SECONDS=0
            QUESTION_ENGINE_STARTUP_POLL_SECONDS=0
            status=0
            require_server_readiness || status=$?
            printf 'status=%s\n' "$status"
            """
            )
            event_lines = events.read_text(encoding="utf-8").splitlines()
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("status=1", completed.stdout.strip())
        self.assertEqual(["cleanup", "diagnostics"], event_lines)

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
        cases = ((None, "false", 0), ("", "false", 0), ("true", "true", 0), ("TRUE", "true", 0),
                 ("False", "false", 0), ("invalid", "invalid", 1), (" TRUE ", " TRUE ", 1))
        for raw_value, expected_value, expected_status in cases:
            with self.subTest(raw_value=raw_value):
                assignment = "unset MINERU_API_ENABLED" if raw_value is None else f"MINERU_API_ENABLED={raw_value!r}"
                completed = self.run_bash(
                    f"""
                    set +e
                    {assignment}
                    normalize_mineru_api_enabled
                    status=$?
                    printf '%s|%s\n' "$status" "${{MINERU_API_ENABLED-<unset>}}"
                    """
                )
                self.assertEqual(0, completed.returncode, completed.stderr)
                self.assertEqual(f"{expected_status}|{expected_value}", completed.stdout.rstrip("\n"))
                if expected_status:
                    self.assertIn("MINERU_API_ENABLED", completed.stderr)
                    self.assertIn("exactly true or false", completed.stderr)
                    self.assertIn("surrounding whitespace", completed.stderr)

    def test_launcher_effective_api_mode_matches_direct_compose_default(self) -> None:
        compose = COMPOSE_PATH.read_text(encoding="utf-8")
        self.assertIn("MINERU_API_ENABLED: ${MINERU_API_ENABLED:-true}", compose)
        self.assertIn("MINERU_API_ENABLED=true", ENV_EXAMPLE_PATH.read_text(encoding="utf-8").splitlines())
        cases = (
            (None, "true", 0),
            ("", "true", 0),
            ("false", "false", 0),
            ("False", "false", 0),
            ("invalid", None, 1),
            (" TRUE ", None, 1),
        )
        for raw_value, expected_value, expected_status in cases:
            with self.subTest(raw_value=raw_value):
                assignment = "unset MINERU_API_ENABLED" if raw_value is None else f"MINERU_API_ENABLED={raw_value!r}"
                launcher = self.run_bash(
                    f"""
                    load_environment() {{ :; }}
                    need_command() {{ :; }}
                    docker() {{ :; }}
                    configure_mineru_environment() {{ :; }}
                    configure_public_urls() {{ PUBLIC_HOST=test; HTTP_PORT=80; }}
                    host_mineru_preflight() {{ printf '%s\n' "$MINERU_API_ENABLED"; }}
                    build_server_artifacts() {{ :; }}
                    require_server_readiness() {{ :; }}
                    {assignment}
                    main
                    """
                )
                direct_compose = subprocess.run(
                    [
                        "bash",
                        "-c",
                        f"""
                        source "{ENTRYPOINT_PATH}"
                        {assignment}
                        MINERU_API_ENABLED="${{MINERU_API_ENABLED:-true}}"
                        normalize_mineru_api_enabled
                        printf '%s\n' "$MINERU_API_ENABLED"
                        """,
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                )

                self.assertEqual(expected_status, launcher.returncode, launcher.stderr)
                self.assertEqual(expected_status, direct_compose.returncode, direct_compose.stderr)
                if expected_value is not None:
                    self.assertEqual(expected_value, launcher.stdout.splitlines()[0])
                    self.assertEqual(expected_value, direct_compose.stdout.strip())

    def test_hard_deadline_bounds_hanging_http_and_cleanup_runs(self) -> None:
        class HangingHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                time.sleep(10)

            def log_message(self, _format, *_args):
                return

        server = self.start_http_server(HangingHandler)
        with tempfile.TemporaryDirectory() as temp_dir:
            cleanup_log = Path(temp_dir) / "cleanup.log"
            event_log = Path(temp_dir) / "events.log"
            url = f"http://127.0.0.1:{server.server_port}/hang"
            body = f"""
health_url='{url}'
ocr_runtime_url='{url}'
COMPOSE_FILE=docker-compose.server.yml
docker() {{ printf '%s\n' "$*" >>'{cleanup_log}'; }}
record_event() {{
  python3 -c 'import sys,time; print(f"{{sys.argv[1]}} {{time.monotonic():.9f}}")' "$1" >>'{event_log}'
}}
eval "$(declare -f cleanup_failed_service | sed '1s/cleanup_failed_service/original_cleanup_failed_service/')"
eval "$(declare -f show_startup_diagnostics | sed '1s/show_startup_diagnostics/original_show_startup_diagnostics/')"
cleanup_failed_service() {{ record_event cleanup; original_cleanup_failed_service; }}
show_startup_diagnostics() {{ record_event diagnostics; original_show_startup_diagnostics; }}
QUESTION_ENGINE_STARTUP_TIMEOUT_SECONDS=1
QUESTION_ENGINE_STARTUP_POLL_SECONDS=0.01
status=0
record_event start
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
            events = {
                name: float(timestamp)
                for name, timestamp in (line.split() for line in event_log.read_text(encoding="utf-8").splitlines())
            }
            self.assertLess(events["cleanup"], events["diagnostics"])
            cleanup_delay = events["cleanup"] - events["start"]
            self.assertGreaterEqual(cleanup_delay, 0.75)
            self.assertLess(cleanup_delay, 1.75)

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
            for optimize in ("0", "1"):
                for name, payload, expected_status in HEALTH_PAYLOAD_CASES:
                    with self.subTest(optimize=optimize, case=name):
                        completed = subprocess.run(
                            ["bash", "-c", host_command],
                            env={
                                **base_env,
                                "OCR_PAYLOAD": json.dumps(payload),
                                "PYTHONOPTIMIZE": optimize,
                            },
                            capture_output=True,
                            check=False,
                        )
                        self.assertEqual(
                            expected_status,
                            completed.returncode,
                            completed.stderr.decode(errors="replace"),
                        )


if __name__ == "__main__":
    unittest.main()
