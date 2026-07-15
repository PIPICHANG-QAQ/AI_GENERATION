#!/usr/bin/env python3
from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("docker-entrypoint.sh").resolve()
SOURCE_GUARD = 'if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then'


class DockerEntrypointLifecycleTest(unittest.TestCase):
    def setUp(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn(SOURCE_GUARD, source, "entrypoint must be sourceable for lifecycle harnesses")

    def _run_harness(
        self,
        body: str,
        *,
        extra_env: dict[str, str] | None = None,
        timeout: float = 8,
    ) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "ENTRYPOINT_SCRIPT": str(SCRIPT_PATH), **(extra_env or {})}
        return subprocess.run(
            ["bash", "-c", 'source "$ENTRYPOINT_SCRIPT"\n' + body],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    @staticmethod
    def _pid_is_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True

    @staticmethod
    def _wait_for_file(path: Path, timeout: float = 3) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.exists():
                return
            time.sleep(0.01)
        raise AssertionError(f"timed out waiting for {path}")

    def test_early_api_death_fails_immediately_and_preserves_nonzero_status(self):
        for child_status, expected in ((0, 1), (17, 17)):
            with self.subTest(child_status=child_status):
                completed = self._run_harness(
                    f"""
set +e
mineru_api_readiness_probe() {{ return 1; }}
bash -c 'exit {child_status}' &
mineru_api_pid=$!
pids=("$mineru_api_pid")
sleep 0.1
MINERU_API_MAX_ATTEMPTS=90
MINERU_API_POLL_SECONDS=0
wait_for_mineru_api
exit $?
"""
                )

                self.assertEqual(expected, completed.returncode, completed.stderr)
                self.assertIn("exited before readiness", completed.stderr)

    def test_signal_handlers_cleanup_children_and_exit_with_shell_signal_codes(self):
        for sent_signal, expected in ((signal.SIGINT, 130), (signal.SIGTERM, 143)):
            with self.subTest(sent_signal=sent_signal), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                ready = root / "ready"
                child_pids = root / "children"
                env = {
                    **os.environ,
                    "ENTRYPOINT_SCRIPT": str(SCRIPT_PATH),
                    "READY_FILE": str(ready),
                    "CHILD_PIDS_FILE": str(child_pids),
                }
                harness = """
source "$ENTRYPOINT_SCRIPT"
TERMINATION_GRACE_SECONDS=1
TERMINATION_POLL_SECONDS=0.05
sleep 30 & first=$!
sleep 30 & second=$!
pids=("$first" "$second")
printf '%s %s\n' "$first" "$second" > "$CHILD_PIDS_FILE"
install_signal_handlers
printf 'ready\n' > "$READY_FILE"
supervise_children
"""
                process = subprocess.Popen(
                    ["bash", "-c", harness],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                try:
                    self._wait_for_file(ready)
                    pids = [int(value) for value in child_pids.read_text(encoding="utf-8").split()]
                    process.send_signal(sent_signal)
                    _stdout, stderr = process.communicate(timeout=5)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=2)

                self.assertEqual(expected, process.returncode, stderr)
                self.assertTrue(all(not self._pid_is_alive(pid) for pid in pids))

    def test_steady_state_clean_exit_is_failure_and_cleans_other_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            child_pid_file = Path(tmp) / "child"
            completed = self._run_harness(
                """
set +e
TERMINATION_GRACE_SECONDS=1
TERMINATION_POLL_SECONDS=0.05
bash -c 'sleep 0.1; exit 0' & first=$!
sleep 30 & second=$!
printf '%s\n' "$second" > "$CHILD_PID_FILE"
pids=("$first" "$second")
supervise_children
exit $?
""",
                extra_env={"CHILD_PID_FILE": str(child_pid_file)},
            )

            child_pid = int(child_pid_file.read_text(encoding="utf-8"))
            self.assertEqual(1, completed.returncode, completed.stderr)
            self.assertFalse(self._pid_is_alive(child_pid))

    def test_steady_state_nonzero_exit_is_preserved_and_cleans_other_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            child_pid_file = Path(tmp) / "child"
            completed = self._run_harness(
                """
set +e
TERMINATION_GRACE_SECONDS=1
TERMINATION_POLL_SECONDS=0.05
bash -c 'sleep 0.1; exit 23' & first=$!
sleep 30 & second=$!
printf '%s\n' "$second" > "$CHILD_PID_FILE"
pids=("$first" "$second")
supervise_children
exit $?
""",
                extra_env={"CHILD_PID_FILE": str(child_pid_file)},
            )

            child_pid = int(child_pid_file.read_text(encoding="utf-8"))
            self.assertEqual(23, completed.returncode, completed.stderr)
            self.assertFalse(self._pid_is_alive(child_pid))

    def test_cleanup_escalates_from_term_to_kill_within_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            child_pid_file = Path(tmp) / "child"
            started = time.monotonic()
            completed = self._run_harness(
                """
TERMINATION_GRACE_SECONDS=1
TERMINATION_POLL_SECONDS=0.05
bash -c 'trap "" TERM; while :; do sleep 1; done' & child=$!
pids=("$child")
printf '%s\n' "$child" > "$CHILD_PID_FILE"
terminate_children
""",
                extra_env={"CHILD_PID_FILE": str(child_pid_file)},
            )
            elapsed = time.monotonic() - started

            child_pid = int(child_pid_file.read_text(encoding="utf-8"))
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertLess(elapsed, 4)
            self.assertFalse(self._pid_is_alive(child_pid))

    def test_api_disabled_skips_preflight_start_and_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = Path(tmp) / "calls"
            completed = self._run_harness(
                """
mineru_runtime_preflight() { printf 'preflight\n' >> "$CALLS_FILE"; }
start_mineru_api_process() { printf 'start\n' >> "$CALLS_FILE"; }
wait_for_mineru_api() { printf 'wait\n' >> "$CALLS_FILE"; }
MINERU_API_ENABLED=false
start_optional_mineru_api
""",
                extra_env={"CALLS_FILE": str(calls)},
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertFalse(calls.exists())

    def test_api_enabled_is_normalized_case_insensitively_and_invalid_values_fail(self):
        completed = self._run_harness(
            """
set +e
MINERU_API_ENABLED=TRUE
normalize_mineru_api_enabled false
upper_status=$?
upper_value=$MINERU_API_ENABLED
MINERU_API_ENABLED=False
normalize_mineru_api_enabled false
mixed_status=$?
mixed_value=$MINERU_API_ENABLED
MINERU_API_ENABLED=invalid
normalize_mineru_api_enabled false
invalid_status=$?
printf '%s %s %s %s %s\n' "$upper_status" "$upper_value" "$mixed_status" "$mixed_value" "$invalid_status"
"""
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("0 true 0 false 1", completed.stdout.strip())
        self.assertIn("MINERU_API_ENABLED", completed.stderr)

    def test_readiness_timeout_cleans_api_process_before_main_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            child_pid_file = Path(tmp) / "api-child"
            completed = self._run_harness(
                """
set +e
configure_environment() { MINERU_API_ENABLED=true; }
install_signal_handlers() { :; }
mineru_runtime_preflight() { :; }
mineru_api_readiness_probe() { return 1; }
start_mineru_api_process() {
  sleep 30 & mineru_api_pid=$!
  pids=("$mineru_api_pid")
  printf '%s\n' "$mineru_api_pid" > "$CHILD_PID_FILE"
}
start_managed_services() { printf 'unexpected service start\n' >&2; return 99; }
MINERU_API_MAX_ATTEMPTS=1
MINERU_API_POLL_SECONDS=0
TERMINATION_GRACE_SECONDS=1
TERMINATION_POLL_SECONDS=0.05
main
exit $?
""",
                extra_env={"CHILD_PID_FILE": str(child_pid_file)},
            )

            child_pid = int(child_pid_file.read_text(encoding="utf-8"))
            self.assertEqual(1, completed.returncode, completed.stderr)
            self.assertIn("readiness failed", completed.stderr)
            self.assertNotIn("unexpected service start", completed.stderr)
            self.assertFalse(self._pid_is_alive(child_pid))


if __name__ == "__main__":
    unittest.main()
