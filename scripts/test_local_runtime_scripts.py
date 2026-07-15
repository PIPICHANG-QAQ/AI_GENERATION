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
START_JAVA_SCRIPT = SCRIPTS_DIR / "start_java_backend.sh"
STOP_LOCAL_SCRIPT = SCRIPTS_DIR / "stop_local.sh"
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
        (root / ".run" / "pids").mkdir(parents=True)
        return copied_script

    @staticmethod
    def _start_sleep(cwd: Path) -> subprocess.Popen[bytes]:
        return subprocess.Popen(["sleep", "30"], cwd=cwd)

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

    def test_stop_local_terminates_pid_owned_by_project_cwd(self) -> None:
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
            self._wait_for_exit(process)

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

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("refusing to stop non-project PID", completed.stderr)

    def test_stop_local_stops_every_duplicate_screen_session_by_full_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as external_tmp:
            root = Path(tmp)
            script = self._temporary_stop_script(root)
            first = self._start_sleep(root)
            second = self._start_sleep(root)
            external = self._start_sleep(Path(external_tmp))
            self.addCleanup(self._terminate_process, first)
            self.addCleanup(self._terminate_process, second)
            self.addCleanup(self._terminate_process, external)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            calls = root / "screen-calls"
            fake_screen = fake_bin / "screen"
            fake_screen.write_text(
                f"""#!/usr/bin/env bash
if [[ "$1" == "-ls" ]]; then
  printf '  {first.pid}.ai_test_python_worker\\t(Detached)\\n'
  printf '  {second.pid}.ai_test_python_worker\\t(Detached)\\n'
  printf '  {external.pid}.ai_test_python_worker\\t(Detached)\\n'
  exit 0
fi
printf '%s\\n' "$*" >> "$SCREEN_CALLS"
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

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(
            [
                f"-S {first.pid}.ai_test_python_worker -X quit",
                f"-S {second.pid}.ai_test_python_worker -X quit",
            ],
            screen_calls,
        )
        self.assertIsNone(external.poll())
        self.assertIn("refusing to stop non-project screen session", completed.stderr)


if __name__ == "__main__":
    unittest.main()
