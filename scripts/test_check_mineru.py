#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).with_name("check_mineru.py")
SPEC = importlib.util.spec_from_file_location("check_mineru", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - import guard
    raise RuntimeError(f"Unable to load {SCRIPT_PATH}")
check_mineru = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_mineru)


class CheckMineruCliTest(unittest.TestCase):
    RUNTIME_READY = {
        "installed": True,
        "runtimeProbeOk": True,
        "apiEnabled": False,
        "apiReady": False,
        "error": None,
    }

    def test_exit_one_when_runtime_probe_fails(self):
        status = {
            "installed": False,
            "runtimeProbeOk": False,
            "apiEnabled": False,
            "apiReady": False,
            "error": "cannot import Markup",
        }
        with mock.patch.object(check_mineru, "provider_status", return_value=status) as provider_status:
            self.assertEqual(1, check_mineru.main(["--json", "--skip-api"]))
            provider_status.assert_called_once_with(check_api=False)

    def test_check_api_failure_and_success_exit_codes(self):
        failed = {
            **self.RUNTIME_READY,
            "installed": True,
            "apiEnabled": True,
            "apiReady": False,
            "apiError": "connection refused",
            "error": "connection refused",
        }
        ready = {
            **self.RUNTIME_READY,
            "apiEnabled": True,
            "apiReady": True,
            "apiError": None,
        }

        with mock.patch.object(check_mineru, "provider_status", return_value=failed) as provider_status:
            self.assertEqual(1, check_mineru.main(["--json", "--check-api"]))
            provider_status.assert_called_once_with(check_api=True)

        with mock.patch.object(check_mineru, "provider_status", return_value=ready) as provider_status:
            self.assertEqual(0, check_mineru.main(["--json", "--check-api"]))
            provider_status.assert_called_once_with(check_api=True)

    def test_check_api_requires_readiness_when_api_mode_is_disabled(self):
        with mock.patch.object(check_mineru, "provider_status", return_value=self.RUNTIME_READY):
            self.assertEqual(1, check_mineru.main(["--json", "--check-api"]))

    def test_check_api_succeeds_for_forced_ready_disabled_mode(self):
        forced_ready = {**self.RUNTIME_READY, "apiReady": True}
        with mock.patch.object(check_mineru, "provider_status", return_value=forced_ready):
            self.assertEqual(0, check_mineru.main(["--json", "--check-api"]))

    def test_skip_api_succeeds_without_api_readiness(self):
        with mock.patch.object(check_mineru, "provider_status", return_value=self.RUNTIME_READY):
            self.assertEqual(0, check_mineru.main(["--skip-api"]))

    def test_json_output_is_exactly_one_line(self):
        output = io.StringIO()
        with mock.patch.object(check_mineru, "provider_status", return_value=self.RUNTIME_READY), mock.patch(
            "sys.stdout",
            output,
        ):
            exit_code = check_mineru.main(["--json", "--skip-api"])

        self.assertEqual(0, exit_code)
        lines = output.getvalue().splitlines()
        self.assertEqual(1, len(lines))
        self.assertEqual(self.RUNTIME_READY, json.loads(lines[0]))

    def test_mutually_exclusive_api_flags_exit_two(self):
        with self.assertRaises(SystemExit) as raised:
            check_mineru.main(["--skip-api", "--check-api"])

        self.assertEqual(2, raised.exception.code)

    def test_calling_main_with_argv_does_not_reexec(self):
        with mock.patch.object(check_mineru, "provider_status", return_value=self.RUNTIME_READY), mock.patch.object(
            check_mineru.os,
            "execve",
        ) as execve:
            exit_code = check_mineru.main(["--json", "--skip-api"])

        self.assertEqual(0, exit_code)
        execve.assert_not_called()

    def test_entrypoint_execves_worker_python_with_exact_arguments_and_environment(self):
        class ExecCalled(RuntimeError):
            pass

        with tempfile.TemporaryDirectory() as tmp:
            worker_python = Path(tmp) / "python"
            worker_python.touch()
            argv = ["--json", "--check-api"]
            with mock.patch.object(check_mineru, "WORKER_PYTHON", worker_python), mock.patch.dict(
                os.environ,
                {"CHECK_MINERU_IN_WORKER_VENV": "0"},
                clear=False,
            ), mock.patch.object(
                check_mineru.os,
                "execve",
                side_effect=ExecCalled("exec invoked"),
            ) as execve:
                with self.assertRaisesRegex(ExecCalled, "exec invoked"):
                    check_mineru.entrypoint(argv)

        self.assertEqual(
            [str(worker_python), str(SCRIPT_PATH.resolve()), *argv],
            execve.call_args.args[1],
        )
        self.assertEqual(str(worker_python), execve.call_args.args[0])
        self.assertEqual("1", execve.call_args.args[2]["CHECK_MINERU_IN_WORKER_VENV"])

    def test_entrypoint_returns_one_only_when_exec_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker_python = Path(tmp) / "python"
            worker_python.touch()
            error_output = io.StringIO()
            with mock.patch.object(check_mineru, "WORKER_PYTHON", worker_python), mock.patch.dict(
                os.environ,
                {"CHECK_MINERU_IN_WORKER_VENV": "0"},
                clear=False,
            ), mock.patch.object(
                check_mineru.os,
                "execve",
                side_effect=OSError("exec format error"),
            ), mock.patch("sys.stderr", error_output):
                exit_code = check_mineru.entrypoint(["--json", "--skip-api"])

        self.assertEqual(1, exit_code)
        self.assertIn("exec format error", error_output.getvalue())

    def test_entrypoint_exec_preserves_binary_streams_and_signal_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script_dir = root / "scripts"
            script_dir.mkdir()
            copied_script = script_dir / "check_mineru.py"
            shutil.copy2(SCRIPT_PATH, copied_script)
            worker_python = root / "backend" / "python-worker" / ".venv" / "bin" / "python"
            worker_python.parent.mkdir(parents=True)
            worker_python.write_text(
                "#!/bin/sh\n"
                "printf '\\377stdout\\n'\n"
                "printf '\\376stderr\\n' >&2\n"
                "kill -TERM $$\n",
                encoding="utf-8",
            )
            worker_python.chmod(0o755)
            env = os.environ.copy()
            env.pop("CHECK_MINERU_IN_WORKER_VENV", None)

            completed = subprocess.run(
                [sys.executable, str(copied_script), "--json", "--skip-api"],
                env=env,
                capture_output=True,
                check=False,
            )

        self.assertEqual(b"\xffstdout\n", completed.stdout)
        self.assertEqual(b"\xfestderr\n", completed.stderr)
        self.assertEqual(-signal.SIGTERM, completed.returncode)

    def test_provider_exception_is_failure_not_traceback_success(self):
        output = io.StringIO()
        error_output = io.StringIO()
        with mock.patch.object(
            check_mineru,
            "provider_status",
            side_effect=RuntimeError("provider traceback"),
        ), mock.patch("sys.stdout", output), mock.patch("sys.stderr", error_output):
            exit_code = check_mineru.main(["--json", "--skip-api"])

        self.assertEqual(1, exit_code)
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["installed"])
        self.assertFalse(payload["runtimeProbeOk"])
        self.assertIn("provider traceback", payload["error"])
        self.assertNotIn("Traceback", error_output.getvalue())


if __name__ == "__main__":
    unittest.main()
