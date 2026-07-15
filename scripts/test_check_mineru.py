#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import io
import json
import os
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
            check_mineru.subprocess,
            "run",
        ) as run:
            exit_code = check_mineru.main(["--json", "--skip-api"])

        self.assertEqual(0, exit_code)
        run.assert_not_called()

    def test_entrypoint_reexec_forwards_arguments_and_streams(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker_python = Path(tmp) / "python"
            worker_python.touch()
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=7,
                stdout='{"installed":false}\n',
                stderr="runtime failed\n",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            argv = ["--json", "--check-api"]
            with mock.patch.object(check_mineru, "WORKER_PYTHON", worker_python), mock.patch.dict(
                os.environ,
                {"CHECK_MINERU_IN_WORKER_VENV": "0"},
                clear=False,
            ), mock.patch.object(
                check_mineru.subprocess,
                "run",
                return_value=completed,
            ) as run, mock.patch(
                "sys.stdout",
                stdout,
            ), mock.patch(
                "sys.stderr",
                stderr,
            ):
                exit_code = check_mineru.entrypoint(argv)

        self.assertEqual(7, exit_code)
        self.assertEqual('{"installed":false}\n', stdout.getvalue())
        self.assertEqual("runtime failed\n", stderr.getvalue())
        self.assertEqual(
            [str(worker_python), str(SCRIPT_PATH.resolve()), *argv],
            run.call_args.args[0],
        )
        self.assertEqual("1", run.call_args.kwargs["env"]["CHECK_MINERU_IN_WORKER_VENV"])

    def test_entrypoint_never_treats_traceback_as_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker_python = Path(tmp) / "python"
            worker_python.touch()
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="",
                stderr="Traceback (most recent call last):\nRuntimeError: broken\n",
            )
            with mock.patch.object(check_mineru, "WORKER_PYTHON", worker_python), mock.patch.dict(
                os.environ,
                {"CHECK_MINERU_IN_WORKER_VENV": "0"},
                clear=False,
            ), mock.patch.object(
                check_mineru.subprocess,
                "run",
                return_value=completed,
            ), mock.patch("sys.stderr", io.StringIO()):
                exit_code = check_mineru.entrypoint(["--json", "--skip-api"])

        self.assertEqual(1, exit_code)

    def test_provider_exception_is_failure_not_traceback_success(self):
        output = io.StringIO()
        with mock.patch.object(
            check_mineru,
            "provider_status",
            side_effect=RuntimeError("provider traceback"),
        ), mock.patch("sys.stdout", output):
            exit_code = check_mineru.main(["--json", "--skip-api"])

        self.assertEqual(1, exit_code)
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["installed"])
        self.assertFalse(payload["runtimeProbeOk"])
        self.assertIn("provider traceback", payload["error"])


if __name__ == "__main__":
    unittest.main()
