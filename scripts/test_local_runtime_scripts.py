#!/usr/bin/env python3
"""Regression tests for local runtime start/stop scripts."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent
DEPLOY_LOCAL_SCRIPT = SCRIPTS_DIR / "deploy_local.sh"
START_JAVA_SCRIPT = SCRIPTS_DIR / "start_java_backend.sh"
STOP_LOCAL_SCRIPT = SCRIPTS_DIR / "stop_local.sh"
LOCAL_PROCESS_IDENTITY_SCRIPT = SCRIPTS_DIR / "local_process_identity.sh"
RECOVERY_PLAN = SCRIPTS_DIR.parent / "docs" / "superpowers" / "plans" / (
    "2026-07-15-production-recovery-and-ocr-readiness.md"
)


class LocalRuntimeScriptsTest(unittest.TestCase):
    def test_task6_uses_canonical_worker_health_endpoint(self) -> None:
        plan_text = RECOVERY_PLAN.read_text(encoding="utf-8")
        task6 = plan_text.split("## Task 6", 1)[1].split("## Task 7", 1)[0]

        self.assertIn("http://127.0.0.1:8001/api/health", task6)
        self.assertNotIn("http://127.0.0.1:8001/health", task6)

    def test_stop_local_script_is_executable(self) -> None:
        self.assertTrue(STOP_LOCAL_SCRIPT.is_file())
        self.assertTrue(os.access(STOP_LOCAL_SCRIPT, os.X_OK))
        self.assertTrue(LOCAL_PROCESS_IDENTITY_SCRIPT.is_file())
        self.assertTrue(os.access(LOCAL_PROCESS_IDENTITY_SCRIPT, os.X_OK))

    def test_java_start_cleans_stale_compiled_classes_before_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_bin = Path(tmp) / "bin"
            fake_bin.mkdir()
            fake_mvn = fake_bin / "mvn"
            fake_mvn.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$*\"\n", encoding="utf-8")
            fake_mvn.chmod(0o755)
            completed = subprocess.run(
                ["bash", str(START_JAVA_SCRIPT)],
                env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(
            "clean spring-boot:run -Dspring-boot.run.profiles=test",
            completed.stdout.strip(),
        )

    def _temporary_stop_script(self, root: Path) -> Path:
        self.assertTrue(STOP_LOCAL_SCRIPT.is_file(), "scripts/stop_local.sh is required")
        scripts_dir = root / "scripts"
        scripts_dir.mkdir()
        copied_script = scripts_dir / STOP_LOCAL_SCRIPT.name
        shutil.copy2(STOP_LOCAL_SCRIPT, copied_script)
        copied_script.chmod(0o755)
        if LOCAL_PROCESS_IDENTITY_SCRIPT.is_file():
            copied_identity = scripts_dir / LOCAL_PROCESS_IDENTITY_SCRIPT.name
            shutil.copy2(LOCAL_PROCESS_IDENTITY_SCRIPT, copied_identity)
            copied_identity.chmod(0o755)
        (root / ".run" / "pids").mkdir(parents=True)
        return copied_script

    @staticmethod
    def _start_sleep(cwd: Path) -> subprocess.Popen[bytes]:
        return subprocess.Popen(["sleep", "30"], cwd=cwd)

    @staticmethod
    def _start_signature_process(root: Path, service: str, *, cwd: Path | None = None) -> subprocess.Popen[bytes]:
        if service == "python-worker":
            executable = root / "backend" / "python-worker" / ".venv" / "bin" / "python"
            args = ["-m", "uvicorn", "app.main:app", "--app-dir", "backend/python-worker"]
            process_cwd = cwd or root
        elif service == "java-backend":
            executable = root / "bin" / "mvn"
            args = ["clean", "spring-boot:run"]
            process_cwd = cwd or root
        elif service == "frontend":
            executable = root / "local-platform" / "node_modules" / ".bin" / "vite"
            args = ["--host", "127.0.0.1"]
            process_cwd = cwd or root / "local-platform"
        else:
            raise AssertionError(f"unsupported service: {service}")
        executable.parent.mkdir(parents=True, exist_ok=True)
        process_cwd.mkdir(parents=True, exist_ok=True)
        executable.write_text(
            "#!/usr/bin/env bash\ntrap 'exit 0' TERM INT\nwhile :; do sleep 1; done\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
        return subprocess.Popen([str(executable), *args], cwd=process_cwd)

    @staticmethod
    def _process_start_identity(pid: int) -> str:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart="],
            env={**os.environ, "LC_ALL": "C", "TZ": "UTC"},
            text=True,
            capture_output=True,
            timeout=2,
            check=True,
        )
        return " ".join(completed.stdout.split())

    def _write_versioned_pid_record(
        self,
        path: Path,
        process: subprocess.Popen[bytes],
        service: str,
        *,
        start_identity: str | None = None,
    ) -> None:
        identity = start_identity or self._process_start_identity(process.pid)
        path.write_text(
            f"version=1\npid={process.pid}\nservice={service}\nstart={identity}\n",
            encoding="utf-8",
        )

    @staticmethod
    def _terminate_process(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=2)

    @staticmethod
    def _wait_for_exit(process: subprocess.Popen[bytes], timeout: float = 3) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return
            time.sleep(0.02)
        raise AssertionError(f"process {process.pid} did not exit")

    def test_stop_local_refuses_legacy_same_cwd_process_without_service_signature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = self._temporary_stop_script(root)
            process = self._start_sleep(root)
            self.addCleanup(self._terminate_process, process)
            (root / ".run" / "pids" / "python-worker.pid").write_text(
                f"{process.pid}\n", encoding="utf-8"
            )

            completed = subprocess.run(
                ["bash", str(script)],
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertIsNone(process.poll())
            self.assertTrue((root / ".run" / "pids" / "python-worker.pid").is_file())

        self.assertNotEqual(0, completed.returncode)
        self.assertNotIn("Local services stopped.", completed.stdout)

    def test_stop_local_terminates_legacy_pid_only_with_matching_service_signature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = self._temporary_stop_script(root)
            process = self._start_signature_process(root, "python-worker")
            self.addCleanup(self._terminate_process, process)
            pid_file = root / ".run" / "pids" / "python-worker.pid"
            pid_file.write_text(f"{process.pid}\n", encoding="utf-8")

            completed = subprocess.run(
                ["bash", str(script)],
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self._wait_for_exit(process)
            self.assertFalse(pid_file.exists())

        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_stop_local_refuses_pid_owned_by_external_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as project_tmp, tempfile.TemporaryDirectory() as external_tmp:
            root = Path(project_tmp)
            script = self._temporary_stop_script(root)
            process = self._start_sleep(Path(external_tmp))
            self.addCleanup(self._terminate_process, process)
            (root / ".run" / "pids" / "python-worker.pid").write_text(
                f"{process.pid}\n", encoding="utf-8"
            )

            completed = subprocess.run(
                ["bash", str(script)],
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )

            self.assertIsNone(process.poll())

        self.assertNotEqual(0, completed.returncode)
        self.assertIn("refusing to stop non-project PID", completed.stderr)

    def test_deploy_wrappers_write_versioned_pid_record_immediately_before_exec(self) -> None:
        deploy_text = DEPLOY_LOCAL_SCRIPT.read_text(encoding="utf-8")
        self.assertTrue(LOCAL_PROCESS_IDENTITY_SCRIPT.is_file())
        for service, next_function in (
            ("python-worker", "start_java_backend()"),
            ("java-backend", "start_frontend()"),
            ("frontend", "start_detached()"),
        ):
            function_name = service.replace("-", "_")
            section = deploy_text.split(f"start_{function_name}()", 1)[1].split(next_function, 1)[0]
            record_call = f'write_pid_record_atomic "${{PID_DIR}}/{service}.pid" "{service}" \\$\\$'
            self.assertIn(record_call, section)
            self.assertLess(section.index(record_call), section.index("exec "))

    def test_deploy_fails_closed_when_port_stop_fails_before_port_appears_free(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            scripts_dir = root / "scripts"
            scripts_dir.mkdir()
            deploy = scripts_dir / "deploy_local.sh"
            identity = scripts_dir / "local_process_identity.sh"
            shutil.copy2(DEPLOY_LOCAL_SCRIPT, deploy)
            shutil.copy2(LOCAL_PROCESS_IDENTITY_SCRIPT, identity)
            deploy.chmod(0o755)
            identity.chmod(0o755)
            stop = scripts_dir / "stop_local.sh"
            stop.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            stop.chmod(0o755)

            worker_python = root / "backend" / "python-worker" / ".venv" / "bin" / "python"
            worker_python.parent.mkdir(parents=True)
            worker_python.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            worker_python.chmod(0o755)

            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            port_reads = root / "port-reads"
            identity_reads = root / "identity-reads"
            start_calls = root / "start-calls"
            (fake_bin / "lsof").write_text(
                f"""#!/usr/bin/env bash
if [[ "$*" == *'-tiTCP:8000'* ]]; then
  reads=0
  if [[ -f "$PORT_READS" ]]; then reads="$(<\"$PORT_READS\")"; fi
  reads=$((reads + 1))
  printf '%s\\n' "$reads" > "$PORT_READS"
  if (( reads <= 3 )); then printf '4242\\n'; fi
  exit 0
fi
if [[ "$*" == *'-d cwd'* ]]; then printf 'p4242\\nn{root}\\n'; fi
""",
                encoding="utf-8",
            )
            (fake_bin / "ps").write_text(
                f"""#!/usr/bin/env bash
case "$*" in
  *'stat='*) printf 'S\\n' ;;
  *'lstart='*)
    reads=0
    if [[ -f "$IDENTITY_READS" ]]; then reads="$(<\"$IDENTITY_READS\")"; fi
    reads=$((reads + 1))
    printf '%s\\n' "$reads" > "$IDENTITY_READS"
    if (( reads == 1 )); then printf 'Mon Jan 1 00:00:00 2024\\n'; fi
    ;;
  *'command='*) printf '%s\\n' '{root}/backend/python-worker/.venv/bin/python -m uvicorn app.main:app --app-dir backend/python-worker' ;;
esac
""",
                encoding="utf-8",
            )
            (fake_bin / "kill").write_text(
                "#!/usr/bin/env bash\n[[ \"$1\" == \"-0\" ]] && exit 0\nexit 1\n",
                encoding="utf-8",
            )
            (fake_bin / "screen").write_text(
                """#!/usr/bin/env bash
if [[ "$1" == "-dmS" ]]; then printf '%s\n' "$*" >> "$START_CALLS"; fi
exit 0
""",
                encoding="utf-8",
            )
            (fake_bin / "curl").write_text(
                "#!/usr/bin/env bash\nprintf '{\"reachable\":true}\\n'\n",
                encoding="utf-8",
            )
            for command in ("python", "mvn", "sleep"):
                (fake_bin / command).write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            for path in fake_bin.iterdir():
                path.chmod(0o755)
            bash_env = root / "bash-env"
            bash_env.write_text("enable -n kill\n", encoding="utf-8")

            completed = subprocess.run(
                ["bash", str(deploy), "--strict-ports", "--skip-smoke"],
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                    "BASH_ENV": str(bash_env),
                    "PORT_READS": str(port_reads),
                    "IDENTITY_READS": str(identity_reads),
                    "START_CALLS": str(start_calls),
                    "STOP_LOCAL_WAIT_ATTEMPTS": "1",
                    "STOP_LOCAL_WAIT_INTERVAL": "0",
                },
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )

            self.assertNotEqual(0, completed.returncode)
            self.assertFalse(start_calls.exists())
            self.assertNotIn("Deploy OK", completed.stdout)

    def test_pid_record_writer_uses_version_and_atomic_replace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "python-worker.pid"
            completed = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$IDENTITY_SCRIPT"; write_pid_record_atomic "$PID_FILE" python-worker "$$"',
                ],
                env={
                    **os.environ,
                    "IDENTITY_SCRIPT": str(LOCAL_PROCESS_IDENTITY_SCRIPT),
                    "PID_FILE": str(pid_file),
                },
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
            content = pid_file.read_text(encoding="utf-8") if pid_file.is_file() else ""

            identities = []
            for timezone in ("UTC", "Asia/Shanghai"):
                identity = subprocess.run(
                    [
                        "bash",
                        "-c",
                        'source "$IDENTITY_SCRIPT"; process_start_identity "$TARGET_PID"',
                    ],
                    env={
                        **os.environ,
                        "IDENTITY_SCRIPT": str(LOCAL_PROCESS_IDENTITY_SCRIPT),
                        "TARGET_PID": str(os.getpid()),
                        "TZ": timezone,
                    },
                    text=True,
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
                self.assertEqual(0, identity.returncode, identity.stderr)
                identities.append(identity.stdout.strip())

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("version=1\n", content)
        self.assertIn("service=python-worker\n", content)
        self.assertRegex(content, r"(?m)^pid=[1-9][0-9]*$")
        self.assertRegex(content, r"(?m)^start=\S.+$")
        self.assertEqual(identities[0], identities[1])

    def test_stop_local_terminates_versioned_records_for_every_service_signature(self) -> None:
        for service in ("python-worker", "java-backend", "frontend"):
            with self.subTest(service=service), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                script = self._temporary_stop_script(root)
                process = self._start_signature_process(root, service)
                self.addCleanup(self._terminate_process, process)
                pid_file = root / ".run" / "pids" / f"{service}.pid"
                self._write_versioned_pid_record(pid_file, process, service)

                completed = subprocess.run(
                    ["bash", str(script)],
                    text=True,
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                self._wait_for_exit(process)
                self.assertFalse(pid_file.exists())

            self.assertEqual(0, completed.returncode, completed.stderr)

    def test_stop_local_refuses_versioned_record_with_start_identity_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = self._temporary_stop_script(root)
            process = self._start_signature_process(root, "python-worker")
            self.addCleanup(self._terminate_process, process)
            pid_file = root / ".run" / "pids" / "python-worker.pid"
            self._write_versioned_pid_record(pid_file, process, "python-worker", start_identity="mismatched start")

            completed = subprocess.run(
                ["bash", str(script)],
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )

            self.assertIsNone(process.poll())
            self.assertTrue(pid_file.is_file())

        self.assertNotEqual(0, completed.returncode)
        self.assertIn("start identity mismatch", completed.stderr)

    def test_stop_local_removes_duplicate_stale_and_invalid_pid_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = self._temporary_stop_script(root)
            exited = self._start_sleep(root)
            exited.terminate()
            exited.wait(timeout=2)
            stale_file = root / ".run" / "pids" / "frontend 2.pid"
            invalid_file = root / ".run" / "pids" / "java-backend 3.pid"
            stale_file.write_text(f"{exited.pid}\n", encoding="utf-8")
            invalid_file.write_text("12 invalid\n", encoding="utf-8")

            completed = subprocess.run(
                ["bash", str(script)],
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )

            self.assertFalse(stale_file.exists())
            self.assertFalse(invalid_file.exists())

        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_stop_local_terminates_project_process_from_duplicate_pid_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = self._temporary_stop_script(root)
            process = self._start_signature_process(root, "python-worker")
            self.addCleanup(self._terminate_process, process)
            pid_file = root / ".run" / "pids" / "python-worker 7.pid"
            pid_file.write_text(f"{process.pid}\n", encoding="utf-8")

            completed = subprocess.run(
                ["bash", str(script)],
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self._wait_for_exit(process)
            self.assertFalse(pid_file.exists())

        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_stop_local_refuses_external_process_from_duplicate_pid_file(self) -> None:
        with tempfile.TemporaryDirectory() as project_tmp, tempfile.TemporaryDirectory() as external_tmp:
            root = Path(project_tmp)
            script = self._temporary_stop_script(root)
            process = self._start_sleep(Path(external_tmp))
            self.addCleanup(self._terminate_process, process)
            pid_file = root / ".run" / "pids" / "frontend 9.pid"
            pid_file.write_text(f"{process.pid}\n", encoding="utf-8")

            completed = subprocess.run(
                ["bash", str(script)],
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )

            self.assertIsNone(process.poll())
            self.assertTrue(pid_file.is_file())

        self.assertNotEqual(0, completed.returncode)
        self.assertIn("refusing to stop non-project PID", completed.stderr)

    def test_stop_local_ignores_unrelated_files_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = self._temporary_stop_script(root)
            pid_dir = root / ".run" / "pids"
            unrelated = [
                pid_dir / "frontend-evil.pid",
                pid_dir / "frontend 0.pid",
                pid_dir / "frontend 01.pid",
                pid_dir / "notes with spaces.txt",
            ]
            for path in unrelated:
                path.write_text("invalid\n", encoding="utf-8")
            target = pid_dir / "external-target.pid"
            target.write_text("invalid\n", encoding="utf-8")
            symlink = pid_dir / "java-backend 2.pid"
            symlink.symlink_to(target)

            completed = subprocess.run(
                ["bash", str(script)],
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )

            self.assertTrue(all(path.is_file() for path in unrelated))
            self.assertTrue(symlink.is_symlink())
            self.assertEqual("invalid\n", target.read_text(encoding="utf-8"))

        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_stop_local_stops_matching_screen_and_refuses_same_cwd_false_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = self._temporary_stop_script(root)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            screen_daemon = root / "daemon" / "SCREEN"
            screen_daemon.parent.mkdir()
            screen_daemon.write_text(
                "#!/usr/bin/env bash\ntrap 'exit 0' TERM INT\nwhile :; do sleep 1; done\n",
                encoding="utf-8",
            )
            screen_daemon.chmod(0o755)
            wrapper = root / ".run" / "python-worker.sh"
            wrapper.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            matching = subprocess.Popen(
                [str(screen_daemon), "-dmS", "ai_test_python_worker", "bash", str(wrapper)],
                cwd=root,
            )
            unrelated = self._start_sleep(root)
            self.addCleanup(self._terminate_process, matching)
            self.addCleanup(self._terminate_process, unrelated)
            calls = root / "screen-calls"
            fake_screen = fake_bin / "screen"
            fake_screen.write_text(
                f"""#!/usr/bin/env bash
if [[ "$1" == "-ls" ]]; then
  printf '  {matching.pid}.ai_test_python_worker\\t(Detached)\\n'
  printf '  {unrelated.pid}.ai_test_python_worker\\t(Detached)\\n'
  exit 0
fi
printf '%s\\n' "$*" >> "$SCREEN_CALLS"
/bin/kill "${{2%%.*}}"
""",
                encoding="utf-8",
            )
            fake_screen.chmod(0o755)
            (root / ".run" / "deploy.env").write_text(
                "SCREEN_PREFIX=ai_test\n", encoding="utf-8"
            )

            completed = subprocess.run(
                ["bash", str(script)],
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                    "SCREEN_CALLS": str(calls),
                },
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            screen_calls = calls.read_text(encoding="utf-8").splitlines()
            self._wait_for_exit(matching)
            self.assertIsNone(unrelated.poll())

        self.assertNotEqual(0, completed.returncode)
        self.assertEqual(
            [
                f"-S {matching.pid}.ai_test_python_worker -X quit",
            ],
            screen_calls,
        )
        self.assertIn("refusing to stop non-project screen session", completed.stderr)

    def test_stop_local_returns_nonzero_and_retains_record_when_kill_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = self._temporary_stop_script(root)
            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            pid_file = root / ".run" / "pids" / "python-worker.pid"
            start_identity = "Mon Jan 1 00:00:00 2024"
            pid_file.write_text(
                f"version=1\npid=4242\nservice=python-worker\nstart={start_identity}\n",
                encoding="utf-8",
            )
            fake_ps = fake_bin / "ps"
            fake_ps.write_text(
                f"""#!/usr/bin/env bash
case "$*" in
  *'stat='*) printf 'S\\n' ;;
  *'lstart='*) printf '{start_identity}\\n' ;;
  *'command='*) printf '%s\\n' '{root}/backend/python-worker/.venv/bin/python -m uvicorn app.main:app --app-dir backend/python-worker' ;;
esac
""",
                encoding="utf-8",
            )
            fake_lsof = fake_bin / "lsof"
            fake_lsof.write_text(
                f"#!/usr/bin/env bash\nif [[ \"$*\" == *'-d cwd'* ]]; then printf 'p4242\\nn{root}\\n'; fi\n",
                encoding="utf-8",
            )
            fake_kill = fake_bin / "kill"
            fake_kill.write_text(
                "#!/usr/bin/env bash\n[[ \"$1\" == \"-0\" ]] && exit 0\nexit 1\n",
                encoding="utf-8",
            )
            (fake_bin / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            (fake_bin / "screen").write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
            for path in fake_bin.iterdir():
                path.chmod(0o755)
            bash_env = root / "bash-env"
            bash_env.write_text("enable -n kill\n", encoding="utf-8")

            completed = subprocess.run(
                ["bash", str(script)],
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                    "BASH_ENV": str(bash_env),
                    "STOP_LOCAL_WAIT_ATTEMPTS": "1",
                    "STOP_LOCAL_WAIT_INTERVAL": "0",
                },
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )

            self.assertTrue(pid_file.is_file())

        self.assertNotEqual(0, completed.returncode)
        self.assertNotIn("Local services stopped.", completed.stdout)
        self.assertIn("could not stop project process", completed.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            state = root / "process-state"
            state.write_text("original\n", encoding="utf-8")
            kill_calls = root / "kill-calls"
            original_start = "Mon Jan 1 00:00:00 2024"
            reused_start = "Mon Jan 1 00:00:01 2024"
            (fake_bin / "ps").write_text(
                f"""#!/usr/bin/env bash
case "$*" in
  *'stat='*) printf 'S\\n' ;;
  *'lstart='*)
    if [[ "$(<\"$PROCESS_STATE\")" == "original" ]]; then
      printf '{original_start}\\n'
    else
      printf '{reused_start}\\n'
    fi
    ;;
  *'command='*) printf '%s\\n' '{root}/backend/python-worker/.venv/bin/python -m uvicorn app.main:app --app-dir backend/python-worker' ;;
esac
""",
                encoding="utf-8",
            )
            (fake_bin / "lsof").write_text(
                f"#!/usr/bin/env bash\nprintf 'p4242\\nn{root}\\n'\n",
                encoding="utf-8",
            )
            (fake_bin / "kill").write_text(
                """#!/usr/bin/env bash
if [[ "$1" == "-0" ]]; then exit 0; fi
printf '%s\n' "$*" >> "$KILL_CALLS"
if [[ "$1" == "4242" ]]; then printf 'reused\n' > "$PROCESS_STATE"; fi
exit 0
""",
                encoding="utf-8",
            )
            (fake_bin / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            for path in fake_bin.iterdir():
                path.chmod(0o755)
            bash_env = root / "bash-env"
            bash_env.write_text("enable -n kill\n", encoding="utf-8")

            reused = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$IDENTITY_SCRIPT"; terminate_pid_verified 4242 python-worker "$ROOT"',
                ],
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                    "BASH_ENV": str(bash_env),
                    "IDENTITY_SCRIPT": str(LOCAL_PROCESS_IDENTITY_SCRIPT),
                    "ROOT": str(root.resolve()),
                    "PROCESS_STATE": str(state),
                    "KILL_CALLS": str(kill_calls),
                    "STOP_LOCAL_WAIT_ATTEMPTS": "1",
                    "STOP_LOCAL_WAIT_INTERVAL": "0",
                },
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )

            self.assertEqual(0, reused.returncode, reused.stderr)
            self.assertEqual(["4242"], kill_calls.read_text(encoding="utf-8").splitlines())

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            sentinel = root / "injected"
            kill_calls = root / "kill-calls"
            (fake_bin / "ps").write_text(
                f"""#!/usr/bin/env bash
case "$*" in
  *'stat='*) printf 'S\\n' ;;
  *'lstart='*) printf 'Mon Jan 1 00:00:00 2024\\n' ;;
  *'command='*) printf '%s\\n' '{root}/backend/python-worker/.venv/bin/python -m uvicorn app.main:app --app-dir backend/python-worker' ;;
esac
""",
                encoding="utf-8",
            )
            (fake_bin / "lsof").write_text(
                f"#!/usr/bin/env bash\nprintf 'p4242\\nn{root}\\n'\n",
                encoding="utf-8",
            )
            (fake_bin / "kill").write_text(
                """#!/usr/bin/env bash
if [[ "$1" == "-0" ]]; then exit 0; fi
printf '%s\n' "$*" >> "$KILL_CALLS"
exit 0
""",
                encoding="utf-8",
            )
            (fake_bin / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            for path in fake_bin.iterdir():
                path.chmod(0o755)
            bash_env = root / "bash-env"
            bash_env.write_text("enable -n kill\n", encoding="utf-8")
            invalid_configs = (
                {"STOP_LOCAL_WAIT_ATTEMPTS": ""},
                {"STOP_LOCAL_WAIT_ATTEMPTS": "0"},
                {"STOP_LOCAL_WAIT_ATTEMPTS": "-1"},
                {"STOP_LOCAL_WAIT_ATTEMPTS": "1.5"},
                {"STOP_LOCAL_WAIT_ATTEMPTS": "1000000"},
                {"STOP_LOCAL_WAIT_ATTEMPTS": '$(touch "$SENTINEL")'},
                {"STOP_LOCAL_WAIT_INTERVAL": ""},
                {"STOP_LOCAL_WAIT_INTERVAL": "-1"},
                {"STOP_LOCAL_WAIT_INTERVAL": "+1"},
                {"STOP_LOCAL_WAIT_INTERVAL": "nan"},
                {"STOP_LOCAL_WAIT_INTERVAL": "1000000"},
            )
            for config in invalid_configs:
                with self.subTest(config=config):
                    sentinel.unlink(missing_ok=True)
                    kill_calls.unlink(missing_ok=True)
                    invalid = subprocess.run(
                        [
                            "bash",
                            "-c",
                            'source "$IDENTITY_SCRIPT"; terminate_pid_verified 4242 python-worker "$ROOT"',
                        ],
                        env={
                            **os.environ,
                            "PATH": f"{fake_bin}:{os.environ['PATH']}",
                            "BASH_ENV": str(bash_env),
                            "IDENTITY_SCRIPT": str(LOCAL_PROCESS_IDENTITY_SCRIPT),
                            "ROOT": str(root),
                            "KILL_CALLS": str(kill_calls),
                            "SENTINEL": str(sentinel),
                            **config,
                        },
                        text=True,
                        capture_output=True,
                        timeout=10,
                        check=False,
                    )
                    self.assertNotEqual(0, invalid.returncode)
                    self.assertFalse(kill_calls.exists())
                    self.assertFalse(sentinel.exists())

    def test_stop_local_retains_record_when_post_term_identity_becomes_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = self._temporary_stop_script(root)
            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            pid_file = root / ".run" / "pids" / "python-worker.pid"
            start_identity = "Mon Jan 1 00:00:00 2024"
            pid_file.write_text(
                f"version=1\npid=4242\nservice=python-worker\nstart={start_identity}\n",
                encoding="utf-8",
            )
            identity_reads = root / "identity-reads"
            term_sent = root / "term-sent"
            kill_calls = root / "kill-calls"
            (fake_bin / "ps").write_text(
                f"""#!/usr/bin/env bash
case "$*" in
  *'stat='*) printf 'S\\n' ;;
  *'lstart='*)
    reads=0
    if [[ -f "$IDENTITY_READS" ]]; then reads="$(<\"$IDENTITY_READS\")"; fi
    reads=$((reads + 1))
    printf '%s\\n' "$reads" > "$IDENTITY_READS"
    if [[ -f "$TERM_SENT" && "$reads" -eq 4 ]]; then exit 0; fi
    printf '{start_identity}\\n'
    ;;
  *'command='*) printf '%s\\n' '{root}/backend/python-worker/.venv/bin/python -m uvicorn app.main:app --app-dir backend/python-worker' ;;
esac
""",
                encoding="utf-8",
            )
            (fake_bin / "lsof").write_text(
                f"""#!/usr/bin/env bash
if [[ "$*" == *'-d cwd'* ]]; then printf 'p4242\\nn{root}\\n'; fi
""",
                encoding="utf-8",
            )
            (fake_bin / "kill").write_text(
                """#!/usr/bin/env bash
if [[ "$1" == "-0" ]]; then exit 0; fi
printf '%s\n' "$*" >> "$KILL_CALLS"
if [[ "$1" == "4242" ]]; then : > "$TERM_SENT"; fi
exit 0
""",
                encoding="utf-8",
            )
            (fake_bin / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            (fake_bin / "screen").write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
            for path in fake_bin.iterdir():
                path.chmod(0o755)
            bash_env = root / "bash-env"
            bash_env.write_text("enable -n kill\n", encoding="utf-8")

            completed = subprocess.run(
                ["bash", str(script)],
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                    "BASH_ENV": str(bash_env),
                    "IDENTITY_READS": str(identity_reads),
                    "TERM_SENT": str(term_sent),
                    "KILL_CALLS": str(kill_calls),
                    "STOP_LOCAL_WAIT_ATTEMPTS": "1",
                    "STOP_LOCAL_WAIT_INTERVAL": "0",
                },
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )

            self.assertNotEqual(0, completed.returncode)
            self.assertTrue(pid_file.is_file())
            self.assertNotIn("Local services stopped.", completed.stdout)
            self.assertIn("could not stop project process", completed.stderr)
            self.assertEqual("4", identity_reads.read_text(encoding="utf-8").strip())
            self.assertEqual(["4242"], kill_calls.read_text(encoding="utf-8").splitlines())

    def test_stop_local_leaves_unrelated_port_listener_and_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = self._temporary_stop_script(root)
            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            kill_calls = root / "kill-calls"
            fake_lsof = fake_bin / "lsof"
            fake_lsof.write_text(
                f"""#!/usr/bin/env bash
if [[ "$*" == *'-tiTCP:8000'* ]]; then printf '4242\\n'; exit 0; fi
if [[ "$*" == *'-d cwd'* ]]; then printf 'p4242\\nn{root}\\n'; exit 0; fi
exit 0
""",
                encoding="utf-8",
            )
            fake_ps = fake_bin / "ps"
            fake_ps.write_text(
                """#!/usr/bin/env bash
case "$*" in
  *'stat='*) printf 'S\\n' ;;
  *'lstart='*) printf 'Mon Jan 1 00:00:00 2024\\n' ;;
  *'command='*) printf 'sleep 30\\n' ;;
esac
""",
                encoding="utf-8",
            )
            fake_kill = fake_bin / "kill"
            fake_kill.write_text(
                "#!/usr/bin/env bash\n[[ \"$1\" == \"-0\" ]] && exit 0\nprintf '%s\\n' \"$*\" >> \"$KILL_CALLS\"\nexit 1\n",
                encoding="utf-8",
            )
            (fake_bin / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            (fake_bin / "screen").write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
            for path in fake_bin.iterdir():
                path.chmod(0o755)
            bash_env = root / "bash-env"
            bash_env.write_text("enable -n kill\n", encoding="utf-8")

            completed = subprocess.run(
                ["bash", str(script)],
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                    "BASH_ENV": str(bash_env),
                    "KILL_CALLS": str(kill_calls),
                    "STOP_LOCAL_WAIT_ATTEMPTS": "1",
                    "STOP_LOCAL_WAIT_INTERVAL": "0",
                },
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertFalse(kill_calls.exists())
        self.assertIn("leaving unrelated listener PID 4242", completed.stderr)


if __name__ == "__main__":
    unittest.main()
