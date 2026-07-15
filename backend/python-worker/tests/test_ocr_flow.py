import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import BackgroundTasks, HTTPException
from starlette.datastructures import Headers, UploadFile

from app.ocr.contracts import CanonicalOcrBundle
from app.ocr_flow import MineruOcrProvider, OcrProviderRequest, OcrProviderResult, ProviderCommand
from app import ocr_execution
from app import worker_base


class MineruOcrProviderTest(unittest.TestCase):
    RUNTIME_IMPORT_PROBE = (
        "from markupsafe import Markup\n"
        "from jinja2 import Environment\n"
        "import transformers\n"
        "from mineru.cli.common import read_fn"
    )

    def setUp(self):
        with MineruOcrProvider._runtime_probe_lock:
            MineruOcrProvider._runtime_probe_cache.clear()

    def _temporary_artifact_root(self) -> str:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return directory.name

    def _write_local_mineru(self, app_root: Path, content: str) -> Path:
        command = app_root / ".venv" / "bin" / "mineru"
        command.parent.mkdir(parents=True)
        command.write_text(content, encoding="utf-8")
        command.chmod(0o755)
        return command

    def _write_runtime_python(self, command_path: Path) -> Path:
        python = command_path.parent / "python"
        python.parent.mkdir(parents=True, exist_ok=True)
        python.write_bytes(b"\x7fELFpython-test-stub")
        python.chmod(0o755)
        return python

    def _write_python_executable(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x7fELFpython-test-stub")
        path.chmod(0o755)
        return path

    def _write_python_mineru(self, command_path: Path) -> Path:
        command_path.parent.mkdir(parents=True, exist_ok=True)
        python = self._write_runtime_python(command_path)
        command_path.write_text(f"#!{python.absolute()}\n", encoding="utf-8")
        command_path.chmod(0o755)
        return python

    def _write_local_python_mineru(self, app_root: Path) -> tuple[Path, Path]:
        command = app_root / ".venv" / "bin" / "mineru"
        return command, self._write_python_mineru(command)

    def _provider_command(self, command_path: Path, source: str = "local-venv-script") -> ProviderCommand:
        return ProviderCommand(args=[str(command_path)], display=str(command_path), source=source)

    def _runtime_probe(self, provider: MineruOcrProvider):
        probe = getattr(provider, "_probe_runtime", None)
        self.assertIsNotNone(probe, "MineruOcrProvider must implement _probe_runtime")
        return probe

    def _probe_completed_process(self, runtime_returncode: int = 0, runtime_error: str = ""):
        def run(args, **_kwargs):
            if args[-1] == "--version":
                return subprocess.CompletedProcess(args, 0, "3.4.2\n", "")
            if len(args) == 3 and args[1] == "-c":
                return subprocess.CompletedProcess(args, runtime_returncode, "", runtime_error)
            self.fail(f"Unexpected subprocess invocation: {args}")

        return run

    @staticmethod
    def _healthy_resolution(command: ProviderCommand) -> dict[str, object]:
        return {
            "selectedSource": command.source,
            "selectedCommand": command.display,
            "version": "3.4.2",
            "versionProbeOk": True,
            "runtimeProbeOk": True,
            "runtimePython": str(command.args[0]),
            "candidates": [],
        }

    @staticmethod
    def _openapi_response(
        payload: bytes,
        status: int = 200,
        url: str = "http://127.0.0.1:8002/openapi.json",
    ):
        response = BytesIO(payload)
        response.status = status
        response.geturl = lambda: url
        return response

    def _write_non_utf8_runtime(self, app_root: Path) -> tuple[ProviderCommand, Path]:
        runtime_python = app_root / "env" / "bin" / "python"
        runtime_python.parent.mkdir(parents=True)
        runtime_python.symlink_to(Path(sys.executable))
        fake_modules = app_root / "fake-modules"
        fake_modules.mkdir()
        (fake_modules / "markupsafe.py").write_text(
            "import os\n"
            "os.write(2, b'\\xffbad-runtime\\n')\n"
            "raise ImportError('broken markupsafe')\n",
            encoding="utf-8",
        )
        return (
            ProviderCommand(
                args=[str(runtime_python), "-m", "mineru"],
                display=f"{runtime_python} -m mineru",
                source="MINERU_COMMAND",
            ),
            fake_modules,
        )

    @staticmethod
    def _healthy_version_probe(command: ProviderCommand) -> dict[str, object]:
        return {
            "source": command.source,
            "command": command.display,
            "returncode": 0,
            "version": "3.4.2",
            "valid": True,
            "versionProbeOk": True,
            "error": None,
        }

    def test_absolute_script_runtime_probe_uses_verified_shebang_and_exact_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path, runtime_python = self._write_local_python_mineru(app_root)
            provider = MineruOcrProvider(app_root, 20)
            command = self._provider_command(command_path)

            with patch("app.ocr_flow.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
                probe = self._runtime_probe(provider)(command)

        self.assertTrue(probe["runtimeProbeOk"])
        self.assertEqual(str(runtime_python.absolute()), probe["runtimePython"])
        self.assertEqual(
            [str(runtime_python.absolute()), "-c", self.RUNTIME_IMPORT_PROBE],
            run.call_args.args[0],
        )
        self.assertEqual(15, run.call_args.kwargs["timeout"])
        self.assertTrue(run.call_args.kwargs["capture_output"])
        self.assertTrue(run.call_args.kwargs["text"])
        self.assertEqual("utf-8", run.call_args.kwargs.get("encoding"))
        self.assertEqual("replace", run.call_args.kwargs.get("errors"))
        self.assertFalse(run.call_args.kwargs["check"])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_status_selects_command_when_runtime_probe_is_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path, runtime_python = self._write_local_python_mineru(app_root)
            command = self._provider_command(command_path)
            provider = MineruOcrProvider(app_root, 5)

            with patch.object(provider, "_command_candidates", return_value=[command]), patch(
                "app.ocr_flow.subprocess.run",
                side_effect=self._probe_completed_process(),
            ):
                status = provider.status()

        self.assertTrue(status["installed"])
        self.assertEqual([str(command_path)], status["command"])
        self.assertEqual("local-venv-script", status["source"])
        self.assertTrue(status["versionProbeOk"])
        self.assertTrue(status["runtimeProbeOk"])
        self.assertEqual(str(runtime_python.absolute()), status["runtimePython"])
        self.assertIsNone(status["error"])

    def test_status_check_api_accepts_valid_openapi_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path, _runtime_python = self._write_local_python_mineru(app_root)
            command = self._provider_command(command_path)
            provider = MineruOcrProvider(app_root, 5)
            response = self._openapi_response(b'{"openapi":"3.1.0","paths":{}}')

            with patch.dict(
                os.environ,
                {"MINERU_API_ENABLED": "true", "MINERU_API_URL": "http://127.0.0.1:8002/"},
                clear=False,
            ), patch.object(
                provider,
                "resolve_command",
                return_value=(command, self._healthy_resolution(command)),
            ), patch.object(urllib.request, "urlopen", return_value=response) as urlopen:
                status = provider.status(check_api=True)

        self.assertTrue(status["installed"])
        self.assertTrue(status["runtimeProbeOk"])
        self.assertTrue(status["apiEnabled"])
        self.assertTrue(status["apiReady"])
        self.assertEqual("http://127.0.0.1:8002/openapi.json", status["apiUrl"])
        self.assertIsNone(status["apiError"])
        urlopen.assert_called_once_with("http://127.0.0.1:8002/openapi.json", timeout=3.0)

    def test_api_probe_rejects_invalid_json_paths_and_http_status(self):
        cases = [
            (b"not-json", 200),
            (b"[]", 200),
            (b'{"paths":[]}', 200),
            (b'{"paths":{}}', 503),
        ]
        for payload, http_status in cases:
            with self.subTest(payload=payload, http_status=http_status), tempfile.TemporaryDirectory() as tmp:
                provider = MineruOcrProvider(Path(tmp), 5)
                response = self._openapi_response(payload, http_status)
                with patch.dict(
                    os.environ,
                    {"MINERU_API_URL": "http://127.0.0.1:8002"},
                    clear=False,
                ), patch.object(urllib.request, "urlopen", return_value=response):
                    probe = provider._probe_api()

                self.assertFalse(probe["apiReady"])
                self.assertIn("apiEnabled", probe)
                self.assertEqual("http://127.0.0.1:8002/openapi.json", probe["apiUrl"])
                self.assertTrue(probe["apiError"])

    def test_api_probe_reports_connection_refusal(self):
        provider = MineruOcrProvider(Path("."), 5)
        refused = urllib.error.URLError(ConnectionRefusedError("connection refused"))

        with patch.dict(
            os.environ,
            {"MINERU_API_URL": "http://127.0.0.1:8002"},
            clear=False,
        ), patch.object(urllib.request, "urlopen", side_effect=refused):
            probe = provider._probe_api()

        self.assertFalse(probe["apiReady"])
        self.assertIn("apiEnabled", probe)
        self.assertIn("connection refused", probe["apiError"])

    def test_api_probe_rejects_redirected_openapi_response(self):
        provider = MineruOcrProvider(Path("."), 5)
        response = self._openapi_response(
            b'{"paths":{}}',
            url="http://127.0.0.1:8002/docs/openapi.json",
        )

        with patch.dict(
            os.environ,
            {"MINERU_API_ENABLED": "true", "MINERU_API_URL": "http://127.0.0.1:8002"},
            clear=False,
        ), patch.object(urllib.request, "urlopen", return_value=response):
            probe = provider._probe_api()

        self.assertFalse(probe["apiReady"])
        self.assertIn("redirect", probe["apiError"].lower())

    def test_api_probe_rejects_non_http_url_without_request(self):
        provider = MineruOcrProvider(Path("."), 5)

        with patch.dict(
            os.environ,
            {"MINERU_API_ENABLED": "true", "MINERU_API_URL": "file:///tmp/mineru"},
            clear=False,
        ), patch.object(urllib.request, "urlopen") as urlopen:
            probe = provider._probe_api()

        self.assertFalse(probe["apiReady"])
        self.assertIn("http", probe["apiError"].lower())
        urlopen.assert_not_called()

    def test_api_probe_reports_malformed_response_attributes(self):
        provider = MineruOcrProvider(Path("."), 5)
        response = BytesIO(b'{"paths":{}}')

        with patch.dict(
            os.environ,
            {"MINERU_API_ENABLED": "true", "MINERU_API_URL": "http://127.0.0.1:8002"},
            clear=False,
        ), patch.object(urllib.request, "urlopen", return_value=response):
            try:
                probe = provider._probe_api()
            except Exception as exc:
                self.fail(f"malformed HTTP response escaped API probe: {exc!r}")

        self.assertFalse(probe["apiReady"])
        self.assertTrue(probe["apiError"])

    def test_status_check_api_false_skips_http_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path, _runtime_python = self._write_local_python_mineru(app_root)
            command = self._provider_command(command_path)
            provider = MineruOcrProvider(app_root, 5)

            with patch.dict(
                os.environ,
                {"MINERU_API_ENABLED": "true", "MINERU_API_URL": "http://127.0.0.1:8002"},
                clear=False,
            ), patch.object(
                provider,
                "resolve_command",
                return_value=(command, self._healthy_resolution(command)),
            ), patch.object(urllib.request, "urlopen") as urlopen:
                status = provider.status(check_api=False)

        self.assertTrue(status["installed"])
        self.assertTrue(status["runtimeProbeOk"])
        self.assertTrue(status["apiEnabled"])
        self.assertFalse(status["apiReady"])
        urlopen.assert_not_called()

    def test_status_api_mode_is_authoritative_even_when_check_is_forced(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path, _runtime_python = self._write_local_python_mineru(app_root)
            command = self._provider_command(command_path)
            provider = MineruOcrProvider(app_root, 5)

            with patch.dict(
                os.environ,
                {"MINERU_API_ENABLED": "false", "MINERU_API_URL": "http://127.0.0.1:8002"},
                clear=False,
            ), patch.object(
                provider,
                "resolve_command",
                return_value=(command, self._healthy_resolution(command)),
            ), patch.object(urllib.request, "urlopen") as urlopen:
                disabled_status = provider.status(check_api=True)

            response = self._openapi_response(b'{"paths":{}}')
            with patch.dict(
                os.environ,
                {"MINERU_API_ENABLED": "true", "MINERU_API_URL": "http://127.0.0.1:8002"},
                clear=False,
            ), patch.object(
                provider,
                "resolve_command",
                return_value=(command, self._healthy_resolution(command)),
            ), patch.object(urllib.request, "urlopen", return_value=response) as enabled_urlopen:
                enabled_status = provider.status()

        self.assertTrue(disabled_status["installed"])
        self.assertFalse(disabled_status["apiEnabled"])
        urlopen.assert_not_called()
        self.assertTrue(enabled_status["installed"])
        self.assertTrue(enabled_status["apiEnabled"])
        self.assertTrue(enabled_status["apiReady"])
        enabled_urlopen.assert_called_once()

    def test_required_api_failure_marks_uninstalled_but_keeps_runtime_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path, runtime_python = self._write_local_python_mineru(app_root)
            command = self._provider_command(command_path)
            provider = MineruOcrProvider(app_root, 5)
            refused = urllib.error.URLError(ConnectionRefusedError("connection refused"))

            with patch.dict(
                os.environ,
                {"MINERU_API_ENABLED": "true", "MINERU_API_URL": "http://127.0.0.1:8002"},
                clear=False,
            ), patch.object(
                provider,
                "resolve_command",
                return_value=(command, self._healthy_resolution(command)),
            ), patch.object(urllib.request, "urlopen", side_effect=refused):
                status = provider.status(check_api=True)

        self.assertFalse(status["installed"])
        self.assertTrue(status["runtimeProbeOk"])
        self.assertEqual(str(command_path), status["command"][0])
        self.assertEqual(str(command_path), status["runtimePython"])
        self.assertFalse(status["apiReady"])
        self.assertIn("connection refused", status["apiError"])
        self.assertIn("connection refused", status["error"])

    def test_status_rejects_command_when_runtime_import_probe_fails(self):
        runtime_error = "ImportError: cannot import name 'Markup' from 'markupsafe'"
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path, _runtime_python = self._write_local_python_mineru(app_root)
            command = self._provider_command(command_path)
            provider = MineruOcrProvider(app_root, 5)

            with patch.object(provider, "_command_candidates", return_value=[command]), patch(
                "app.ocr_flow.subprocess.run",
                side_effect=self._probe_completed_process(1, runtime_error),
            ):
                status = provider.status()

        self.assertFalse(status["installed"])
        self.assertFalse(status["runtimeProbeOk"])
        self.assertIn("Markup", status["error"])
        self.assertIn("Markup", status["candidates"][0]["runtimeError"])

    def test_status_rejects_command_when_runtime_probe_times_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path, runtime_python = self._write_local_python_mineru(app_root)
            command = self._provider_command(command_path)
            provider = MineruOcrProvider(app_root, 5)

            def run(args, **_kwargs):
                if args[-1] == "--version":
                    return subprocess.CompletedProcess(args, 0, "3.4.2\n", "")
                raise subprocess.TimeoutExpired(args, 5)

            with patch.object(provider, "_command_candidates", return_value=[command]), patch(
                "app.ocr_flow.subprocess.run",
                side_effect=run,
            ):
                status = provider.status()

        self.assertFalse(status["installed"])
        self.assertFalse(status["runtimeProbeOk"])
        self.assertEqual(str(runtime_python.absolute()), status["runtimePython"])
        self.assertIn("timed out", status["error"])

    def test_status_rejects_venv_command_without_sibling_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path = self._write_local_mineru(app_root, f"#!{sys.executable}\n")
            command = self._provider_command(command_path)
            provider = MineruOcrProvider(app_root, 5)

            with patch.object(provider, "_command_candidates", return_value=[command]), patch(
                "app.ocr_flow.subprocess.run",
                side_effect=self._probe_completed_process(),
            ) as run:
                status = provider.status()

        self.assertFalse(status["installed"])
        self.assertFalse(status["runtimeProbeOk"])
        self.assertIsNone(status["runtimePython"])
        self.assertIn(str(command_path.parent / "python"), status["error"])
        self.assertEqual(1, run.call_count)

    def test_run_aborts_before_ocr_subprocess_when_runtime_is_broken(self):
        runtime_error = "ImportError: cannot import name 'Markup' from 'markupsafe'"
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path, _runtime_python = self._write_local_python_mineru(app_root)
            command = self._provider_command(command_path)
            provider = MineruOcrProvider(app_root, 5)
            request = OcrProviderRequest(
                document_id="job-1",
                input_path="paper.pdf",
                output_dir=app_root / "outputs" / "job-1",
                timeout_seconds=30,
            )

            with patch.object(provider, "_command_candidates", return_value=[command]), patch(
                "app.ocr_flow.subprocess.run",
                side_effect=self._probe_completed_process(1, runtime_error),
            ) as run:
                result = provider.run(request)

        self.assertFalse(result.success)
        self.assertIn("Markup", result.error)
        self.assertFalse(request.output_dir.exists())
        self.assertEqual(2, run.call_count)
        self.assertFalse(any("-p" in call.args[0] for call in run.call_args_list))

    def test_status_uses_healthy_later_candidate_after_broken_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            first_command_path = app_root / "first" / "bin" / "mineru"
            first_python = self._write_python_mineru(first_command_path)
            second_command_path = app_root / "second" / "bin" / "mineru"
            second_python = self._write_python_mineru(second_command_path)
            first = self._provider_command(first_command_path, "first")
            second = self._provider_command(second_command_path, "second")
            provider = MineruOcrProvider(app_root, 5)

            def run(args, **_kwargs):
                if args[-1] == "--version":
                    return subprocess.CompletedProcess(args, 0, "3.4.2\n", "")
                if args[0] == str(first_python.absolute()):
                    return subprocess.CompletedProcess(args, 1, "", "ImportError: broken first runtime")
                if args[0] == str(second_python.absolute()):
                    return subprocess.CompletedProcess(args, 0, "", "")
                self.fail(f"Unexpected subprocess invocation: {args}")

            with patch.object(provider, "_command_candidates", return_value=[first, second]), patch(
                "app.ocr_flow.subprocess.run",
                side_effect=run,
            ):
                status = provider.status()

        self.assertTrue(status["installed"])
        self.assertEqual([str(second_command_path)], status["command"])
        self.assertEqual("second", status["source"])
        self.assertEqual(2, len(status["candidates"]))
        self.assertIn("broken first runtime", status["candidates"][0]["runtimeError"])

    def test_runtime_probe_cache_reuses_success_and_failure_within_sixty_seconds(self):
        for runtime_returncode in (0, 1):
            with self.subTest(runtime_returncode=runtime_returncode), tempfile.TemporaryDirectory() as tmp:
                app_root = Path(tmp)
                command_path, _runtime_python = self._write_local_python_mineru(app_root)
                command = self._provider_command(command_path)
                provider = MineruOcrProvider(app_root, 5)
                provider._monotonic = Mock(side_effect=[100.0, 100.0, 159.9])

                with patch(
                    "app.ocr_flow.subprocess.run",
                    return_value=subprocess.CompletedProcess([], runtime_returncode, "", "ImportError: cached failure"),
                ) as run:
                    first = self._runtime_probe(provider)(command)
                    second = self._runtime_probe(provider)(command)

                self.assertEqual(first, second)
                self.assertEqual(1, run.call_count)

    def test_runtime_probe_cache_reprobes_at_ttl_expiry(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path, _runtime_python = self._write_local_python_mineru(app_root)
            command = self._provider_command(command_path)
            provider = MineruOcrProvider(app_root, 5)
            provider._monotonic = Mock(side_effect=[100.0, 100.0, 160.0, 160.0])

            with patch(
                "app.ocr_flow.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ) as run:
                self._runtime_probe(provider)(command)
                self._runtime_probe(provider)(command)

        self.assertEqual(2, run.call_count)

    def test_runtime_probe_cache_ttl_starts_when_long_probe_completes(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path, _runtime_python = self._write_local_python_mineru(app_root)
            command = self._provider_command(command_path)
            provider = MineruOcrProvider(app_root, 5)
            clock = [100.0]
            provider._monotonic = lambda: clock[0]

            def run(_args, **_kwargs):
                clock[0] += 50.0
                return subprocess.CompletedProcess([], 0, "", "")

            with patch("app.ocr_flow.subprocess.run", side_effect=run) as subprocess_run:
                provider._probe_runtime(command)
                clock[0] = 209.9
                provider._probe_runtime(command)

        self.assertEqual(1, subprocess_run.call_count)

    def test_runtime_probe_cache_is_reused_across_provider_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path, _runtime_python = self._write_local_python_mineru(app_root)
            command = self._provider_command(command_path)
            first_provider = MineruOcrProvider(app_root, 5)
            first_provider._monotonic = Mock(return_value=100.0)
            second_provider = MineruOcrProvider(app_root, 5)
            second_provider._monotonic = Mock(return_value=110.0)

            with patch(
                "app.ocr_flow.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ) as run:
                self._runtime_probe(first_provider)(command)
                self._runtime_probe(second_provider)(command)

        self.assertEqual(1, run.call_count)

    def test_runtime_probe_cache_single_flight_across_concurrent_provider_instances(self):
        callers = 6
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path, _runtime_python = self._write_local_python_mineru(app_root)
            command = self._provider_command(command_path)
            providers = [MineruOcrProvider(app_root, 5) for _ in range(callers)]
            start = threading.Barrier(callers)
            second_probe_started = threading.Event()
            count_lock = threading.Lock()
            subprocess_calls = 0

            def run(_args, **_kwargs):
                nonlocal subprocess_calls
                with count_lock:
                    subprocess_calls += 1
                    if subprocess_calls >= 2:
                        second_probe_started.set()
                second_probe_started.wait(timeout=0.3)
                return subprocess.CompletedProcess([], 0, "", "")

            def probe(provider):
                start.wait(timeout=2)
                return provider._probe_runtime(command)

            with patch("app.ocr_flow.subprocess.run", side_effect=run):
                with ThreadPoolExecutor(max_workers=callers) as executor:
                    results = list(executor.map(probe, providers, timeout=3))

        self.assertTrue(all(result["runtimeProbeOk"] for result in results))
        self.assertEqual(1, subprocess_calls)

    def test_runtime_probe_cache_replaces_entry_when_mtime_churns(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path, _runtime_python = self._write_local_python_mineru(app_root)
            command = self._provider_command(command_path)
            provider = MineruOcrProvider(app_root, 5)
            provider._monotonic = Mock(return_value=100.0)

            with patch(
                "app.ocr_flow.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ) as run:
                for _ in range(12):
                    provider._probe_runtime(command)
                    stat = command_path.stat()
                    os.utime(command_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

        self.assertEqual(12, run.call_count)
        self.assertEqual(1, len(MineruOcrProvider._runtime_probe_cache))

    def test_runtime_probe_cache_is_bounded_to_thirty_two_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            provider = MineruOcrProvider(app_root, 5)
            provider._monotonic = Mock(return_value=100.0)

            with patch(
                "app.ocr_flow.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ) as run:
                for index in range(40):
                    command_path = app_root / f"env-{index}" / "bin" / "mineru"
                    self._write_python_mineru(command_path)
                    provider._probe_runtime(self._provider_command(command_path))

        self.assertEqual(40, run.call_count)
        self.assertEqual(32, len(MineruOcrProvider._runtime_probe_cache))

    def test_runtime_probe_lock_is_released_after_unexpected_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path, _runtime_python = self._write_local_python_mineru(app_root)
            provider = MineruOcrProvider(app_root, 5)
            provider._monotonic = Mock(side_effect=[RuntimeError("unexpected clock failure"), 100.0, 100.0])

            with patch(
                "app.ocr_flow.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ) as run:
                with self.assertRaisesRegex(RuntimeError, "unexpected clock failure"):
                    provider._probe_runtime(self._provider_command(command_path))

                original_lock = MineruOcrProvider._runtime_probe_lock
                lock_released = original_lock.acquire(timeout=0.2)
                if lock_released:
                    original_lock.release()
                else:
                    MineruOcrProvider._runtime_probe_lock = threading.Lock()
                probe = provider._probe_runtime(self._provider_command(command_path))

        self.assertTrue(lock_released)
        self.assertTrue(probe["runtimeProbeOk"])
        self.assertEqual(1, run.call_count)

    def test_runtime_probe_cache_invalidates_when_command_or_interpreter_mtime_changes(self):
        for changed_file in ("command", "interpreter"):
            with self.subTest(changed_file=changed_file), tempfile.TemporaryDirectory() as tmp:
                app_root = Path(tmp)
                command_path, runtime_python = self._write_local_python_mineru(app_root)
                command = self._provider_command(command_path)
                provider = MineruOcrProvider(app_root, 5)
                provider._monotonic = Mock(side_effect=[100.0, 100.0, 101.0, 101.0])
                target = command_path if changed_file == "command" else runtime_python

                with patch(
                    "app.ocr_flow.subprocess.run",
                    return_value=subprocess.CompletedProcess([], 0, "", ""),
                ) as run:
                    self._runtime_probe(provider)(command)
                    stat = target.stat()
                    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
                    self._runtime_probe(provider)(command)

                self.assertEqual(2, run.call_count)

    def test_path_script_uses_python_shebang_from_resolved_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path, runtime_python = self._write_local_python_mineru(app_root)
            provider = MineruOcrProvider(app_root, 5)
            command = ProviderCommand(
                args=["mineru", "--config", "safe.json"],
                display="mineru --config safe.json",
                source="MINERU_COMMAND",
            )

            with patch("app.ocr_flow.shutil.which", return_value=str(command_path)), patch(
                "app.ocr_flow.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ) as run:
                probe = self._runtime_probe(provider)(command)

        self.assertTrue(probe["runtimeProbeOk"])
        self.assertEqual(str(runtime_python.absolute()), run.call_args.args[0][0])

    def test_relative_script_uses_python_from_resolved_script_environment(self):
        original_cwd = Path.cwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                app_root = Path(tmp)
                command_path = app_root / "env" / "bin" / "mineru"
                runtime_python = self._write_python_mineru(command_path)
                provider = MineruOcrProvider(app_root, 5)
                command = ProviderCommand(
                    args=["env/bin/mineru", "--config", "safe.json"],
                    display="env/bin/mineru --config safe.json",
                    source="MINERU_COMMAND",
                )
                os.chdir(app_root)

                with patch(
                    "app.ocr_flow.subprocess.run",
                    return_value=subprocess.CompletedProcess([], 0, "", ""),
                ) as run:
                    probe = self._runtime_probe(provider)(command)
        finally:
            os.chdir(original_cwd)

        self.assertTrue(probe["runtimeProbeOk"])
        self.assertEqual(str(runtime_python.absolute()), run.call_args.args[0][0])
        self.assertEqual(self.RUNTIME_IMPORT_PROBE, run.call_args.args[0][2])

    def test_path_symlinked_script_uses_target_script_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            target = app_root / "env" / "bin" / "mineru"
            runtime_python = self._write_python_mineru(target)
            launcher = app_root / "launcher" / "bin" / "mineru"
            launcher.parent.mkdir(parents=True)
            launcher.symlink_to(target)
            provider = MineruOcrProvider(app_root, 5)
            command = ProviderCommand(args=["mineru", "--flag"], display="mineru --flag", source="PATH")

            with patch("app.ocr_flow.shutil.which", return_value=str(launcher)), patch(
                "app.ocr_flow.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ) as run:
                probe = self._runtime_probe(provider)(command)

        self.assertTrue(probe["runtimeProbeOk"])
        self.assertEqual(str(runtime_python.absolute()), probe["runtimePython"])
        self.assertEqual(str(runtime_python.absolute()), run.call_args.args[0][0])

    def test_absolute_python3_module_command_uses_exact_resolved_python3(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            bin_dir = app_root / "env" / "bin"
            bin_dir.mkdir(parents=True)
            sibling_python = bin_dir / "python"
            self._write_python_executable(sibling_python)
            python3 = bin_dir / "python3"
            self._write_python_executable(python3)
            provider = MineruOcrProvider(app_root, 5)
            command = ProviderCommand(
                args=[str(python3), "-m", "mineru", "--config", "safe.json"],
                display=f"{python3} -m mineru --config safe.json",
                source="MINERU_COMMAND",
            )

            with patch(
                "app.ocr_flow.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ) as run:
                probe = self._runtime_probe(provider)(command)

        self.assertTrue(probe["runtimeProbeOk"])
        self.assertEqual(str(python3.absolute()), probe["runtimePython"])
        self.assertEqual(str(python3.absolute()), run.call_args.args[0][0])
        self.assertNotEqual(str(sibling_python.absolute()), run.call_args.args[0][0])

    def test_path_python3_module_command_uses_resolved_python3(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            python3 = app_root / "env" / "bin" / "python3"
            self._write_python_executable(python3)
            provider = MineruOcrProvider(app_root, 5)
            command = ProviderCommand(
                args=["python3", "-m", "mineru", "--flag"],
                display="python3 -m mineru --flag",
                source="MINERU_COMMAND",
            )

            with patch("app.ocr_flow.shutil.which", return_value=str(python3)), patch(
                "app.ocr_flow.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ) as run:
                probe = self._runtime_probe(provider)(command)

        self.assertTrue(probe["runtimeProbeOk"])
        self.assertEqual(str(python3.absolute()), run.call_args.args[0][0])

    def test_relative_python_module_commands_use_exact_relative_interpreter(self):
        original_cwd = Path.cwd()
        try:
            for executable_name in ("python", "python3"):
                with self.subTest(executable_name=executable_name), tempfile.TemporaryDirectory() as tmp:
                    app_root = Path(tmp)
                    relative_python = Path("env") / "bin" / executable_name
                    self._write_python_executable(app_root / relative_python)
                    provider = MineruOcrProvider(app_root, 5)
                    command = ProviderCommand(
                        args=[str(relative_python), "-m", "mineru", "--flag"],
                        display=f"{relative_python} -m mineru --flag",
                        source="MINERU_COMMAND",
                    )
                    os.chdir(app_root)
                    expected_python = relative_python.absolute()

                    with patch(
                        "app.ocr_flow.subprocess.run",
                        return_value=subprocess.CompletedProcess([], 0, "", ""),
                    ) as run:
                        probe = provider._probe_runtime(command)

                    os.chdir(original_cwd)
                    self.assertTrue(probe["runtimeProbeOk"])
                    self.assertEqual(str(expected_python), probe["runtimePython"])
                    self.assertEqual(
                        [str(expected_python), "-c", self.RUNTIME_IMPORT_PROBE],
                        run.call_args.args[0],
                    )
        finally:
            os.chdir(original_cwd)

    def test_python_named_shell_wrapper_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            python3 = app_root / "env" / "bin" / "python3"
            python3.parent.mkdir(parents=True)
            python3.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            python3.chmod(0o755)
            provider = MineruOcrProvider(app_root, 5)
            command = ProviderCommand(
                args=[str(python3), "-m", "mineru"],
                display=f"{python3} -m mineru",
                source="MINERU_COMMAND",
            )

            with patch("app.ocr_flow.subprocess.run") as run:
                probe = provider._probe_runtime(command)

        run.assert_not_called()
        self.assertFalse(probe["runtimeProbeOk"])
        self.assertIn("wrapper", probe["runtimeError"].lower())

    def test_script_rejects_shebang_from_different_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path = app_root / "env-a" / "bin" / "mineru"
            command_path.parent.mkdir(parents=True)
            own_python = self._write_runtime_python(command_path)
            other_python = app_root / "env-b" / "bin" / "python"
            self._write_python_executable(other_python)
            command_path.write_text(f"#!{other_python.absolute()}\n", encoding="utf-8")
            command_path.chmod(0o755)
            provider = MineruOcrProvider(app_root, 5)
            command = self._provider_command(command_path)

            with patch("app.ocr_flow.subprocess.run") as run:
                probe = self._runtime_probe(provider)(command)

        self.assertFalse(probe["runtimeProbeOk"])
        self.assertIsNone(probe["runtimePython"])
        self.assertIn("mismatch", probe["runtimeError"].lower())
        self.assertIn(str(own_python.absolute()), probe["runtimeError"])
        run.assert_not_called()

    def test_script_rejects_ambiguous_or_non_python_wrapper(self):
        invalid_scripts = {
            "env": "#!/usr/bin/env python3\n",
            "shell": "#!/bin/sh\n",
            "malformed": "not a shebang\n",
        }
        for label, content in invalid_scripts.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                app_root = Path(tmp)
                command_path = self._write_local_mineru(app_root, content)
                self._write_runtime_python(command_path)
                provider = MineruOcrProvider(app_root, 5)

                with patch("app.ocr_flow.subprocess.run") as run:
                    probe = self._runtime_probe(provider)(self._provider_command(command_path))

                self.assertFalse(probe["runtimeProbeOk"])
                self.assertIsNone(probe["runtimePython"])
                self.assertIn("shebang", probe["runtimeError"].lower())
                run.assert_not_called()

    def test_run_rejects_non_utf8_runtime_output_without_starting_ocr(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command, fake_modules = self._write_non_utf8_runtime(app_root)
            provider = MineruOcrProvider(app_root, 5)
            request = OcrProviderRequest(
                document_id="job-invalid-utf8",
                input_path="paper.pdf",
                output_dir=app_root / "outputs" / "job-invalid-utf8",
                timeout_seconds=30,
            )
            real_subprocess_run = subprocess.run
            invocations: list[list[str]] = []

            def recording_run(args, **kwargs):
                invocations.append(list(args))
                return real_subprocess_run(args, **kwargs)

            try:
                with patch.dict(os.environ, {"PYTHONPATH": str(fake_modules)}), patch.object(
                    provider,
                    "_command_candidates",
                    return_value=[command],
                ), patch.object(
                    provider,
                    "_probe_command",
                    return_value=self._healthy_version_probe(command),
                ), patch(
                    "app.ocr_flow.subprocess.run",
                    side_effect=recording_run,
                ):
                    result = provider.run(request)
            except Exception as exc:
                self.fail(f"runtime decoding failure escaped provider.run(): {exc!r}")

            self.assertFalse(result.success)
            self.assertIn("\ufffd", result.error)
            self.assertFalse(request.output_dir.exists())
            self.assertEqual(1, len(invocations))
            self.assertNotIn("-p", invocations[0])

    def test_status_rejects_non_utf8_runtime_output_without_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command, fake_modules = self._write_non_utf8_runtime(app_root)
            provider = MineruOcrProvider(app_root, 5)
            real_subprocess_run = subprocess.run
            invocations: list[list[str]] = []

            def recording_run(args, **kwargs):
                invocations.append(list(args))
                return real_subprocess_run(args, **kwargs)

            with patch.dict(os.environ, {"PYTHONPATH": str(fake_modules)}), patch.object(
                provider,
                "_command_candidates",
                return_value=[command],
            ), patch.object(
                provider,
                "_probe_command",
                return_value=self._healthy_version_probe(command),
            ), patch(
                "app.ocr_flow.subprocess.run",
                side_effect=recording_run,
            ):
                status = provider.status()

        self.assertFalse(status["installed"])
        self.assertFalse(status["runtimeProbeOk"])
        self.assertIn("\ufffd", status["error"])
        self.assertEqual(1, len(invocations))

    def test_runtime_subprocess_error_becomes_unavailable_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path, _runtime_python = self._write_local_python_mineru(app_root)
            provider = MineruOcrProvider(app_root, 5)

            try:
                with patch(
                    "app.ocr_flow.subprocess.run",
                    side_effect=subprocess.SubprocessError("runtime decoder failed"),
                ):
                    probe = provider._probe_runtime(self._provider_command(command_path))
            except Exception as exc:
                self.fail(f"runtime subprocess failure escaped probe: {exc!r}")

        self.assertFalse(probe["runtimeProbeOk"])
        self.assertIn("runtime decoder failed", probe["runtimeError"])

    def test_python_entrypoint_runtime_probe_uses_current_interpreter(self):
        provider = MineruOcrProvider(Path("."), 5)
        command = ProviderCommand(
            args=[sys.executable, "-c", "raise SystemExit(0)"],
            display=f"{sys.executable} -c <mineru:test>",
            source="python-entrypoint",
        )

        with patch(
            "app.ocr_flow.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, "", ""),
        ) as run:
            probe = self._runtime_probe(provider)(command)

        self.assertTrue(probe["runtimeProbeOk"])
        self.assertEqual(str(Path(sys.executable).absolute()), run.call_args.args[0][0])

    def test_python_entrypoint_rejects_alias_of_current_interpreter(self):
        with tempfile.TemporaryDirectory() as tmp:
            alias = Path(tmp) / "python"
            alias.symlink_to(Path(sys.executable))
            provider = MineruOcrProvider(Path(tmp), 5)
            command = ProviderCommand(
                args=[str(alias), "-c", "raise SystemExit(0)"],
                display=f"{alias} -c <mineru:test>",
                source="python-entrypoint",
            )

            with patch("app.ocr_flow.subprocess.run") as run:
                probe = self._runtime_probe(provider)(command)

        run.assert_not_called()
        self.assertFalse(probe["runtimeProbeOk"])
        self.assertIn("current worker interpreter", probe["runtimeError"])

    def test_version_probe_timeout_does_not_disable_available_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path, _runtime_python = self._write_local_python_mineru(app_root)
            provider = MineruOcrProvider(app_root, 1)
            command_candidate = self._provider_command(command_path)

            def run(args, **_kwargs):
                if args[-1] == "--version":
                    raise subprocess.TimeoutExpired(args, 1)
                return subprocess.CompletedProcess(args, 0, "", "")

            with patch.object(provider, "_command_candidates", return_value=[command_candidate]), patch(
                "app.ocr_flow.subprocess.run",
                side_effect=run,
            ):
                command, resolution = provider.resolve_command()

        self.assertIsNotNone(command)
        self.assertEqual("local-venv-script", command.source)
        self.assertIsNone(resolution["version"])
        self.assertTrue(resolution["candidates"][0]["valid"])
        self.assertFalse(resolution["candidates"][0]["versionProbeOk"])
        self.assertIn("runtimeProbeOk", resolution["candidates"][0])
        self.assertTrue(resolution["candidates"][0]["runtimeProbeOk"])
        self.assertIn("timed out", resolution["candidates"][0]["error"])

    def test_missing_script_interpreter_disables_copied_venv_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            missing_python = app_root / "missing" / "python"
            self._write_local_mineru(app_root, f"#!{missing_python}\nprint('bad')\n")
            provider = MineruOcrProvider(app_root, 1)

            with patch.object(provider, "_entrypoint_command_candidate", return_value=None):
                command, resolution = provider.resolve_command()

        self.assertIsNone(command)
        self.assertFalse(resolution["candidates"][0]["valid"])
        self.assertIn("Script interpreter does not exist", resolution["candidates"][0]["error"])

    def test_run_uses_configured_mineru_api_url_when_api_is_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path, _runtime_python = self._write_local_python_mineru(app_root)
            provider = MineruOcrProvider(app_root, 1)
            request = OcrProviderRequest(
                document_id="job-1",
                input_path="paper.pdf",
                output_dir=app_root / "outputs" / "job-1",
                timeout_seconds=30,
            )
            request.output_dir.mkdir(parents=True)
            (request.output_dir / "paper.md").write_text("1. 题目", encoding="utf-8")

            response = self._openapi_response(b'{"paths":{}}')
            with patch.dict(
                os.environ,
                {"MINERU_API_ENABLED": "true", "MINERU_API_URL": "http://127.0.0.1:8002"},
            ), patch.object(
                urllib.request,
                "urlopen",
                return_value=response,
            ) as urlopen, patch(
                "app.ocr_flow.subprocess.run",
                return_value=subprocess.CompletedProcess([str(command_path)], 0, "", ""),
            ) as run:
                result = provider.run(request)

        mineru_cmd = run.call_args.args[0]
        self.assertIn("--api-url", mineru_cmd)
        self.assertIn("http://127.0.0.1:8002", mineru_cmd)
        self.assertEqual("http://127.0.0.1:8002", result.metadata["mineruApiUrl"])
        self.assertTrue(result.success)
        self.assertIsNotNone(result.bundle)
        urlopen.assert_called_once_with("http://127.0.0.1:8002/openapi.json", timeout=3.0)

    def test_run_ignores_configured_api_url_when_api_is_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path, _runtime_python = self._write_local_python_mineru(app_root)
            command = self._provider_command(command_path)
            provider = MineruOcrProvider(app_root, 5)
            request = OcrProviderRequest(
                document_id="job-api-down",
                input_path="paper.pdf",
                output_dir=app_root / "outputs" / "job-api-down",
                timeout_seconds=30,
            )
            request.output_dir.mkdir(parents=True)
            (request.output_dir / "paper.md").write_text("1. 题目", encoding="utf-8")

            with patch.dict(
                os.environ,
                {"MINERU_API_ENABLED": "false", "MINERU_API_URL": "http://127.0.0.1:8002"},
                clear=False,
            ), patch.object(
                provider,
                "resolve_command",
                return_value=(command, self._healthy_resolution(command)),
            ), patch.object(
                urllib.request,
                "urlopen",
            ) as urlopen, patch(
                "app.ocr_flow.subprocess.run",
                return_value=subprocess.CompletedProcess([str(command_path)], 0, "", ""),
            ) as run:
                result = provider.run(request)

        self.assertTrue(result.success)
        self.assertNotIn("--api-url", run.call_args.args[0])
        self.assertIsNone(result.metadata["mineruApiUrl"])
        urlopen.assert_not_called()

    def test_run_aborts_before_output_and_ocr_when_enabled_api_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path, _runtime_python = self._write_local_python_mineru(app_root)
            command = self._provider_command(command_path)
            provider = MineruOcrProvider(app_root, 5)
            request = OcrProviderRequest(
                document_id="job-api-down",
                input_path="paper.pdf",
                output_dir=app_root / "outputs" / "job-api-down",
                timeout_seconds=30,
            )
            refused = urllib.error.URLError(ConnectionRefusedError("connection refused"))

            with patch.dict(
                os.environ,
                {"MINERU_API_ENABLED": "true", "MINERU_API_URL": "http://127.0.0.1:8002"},
                clear=False,
            ), patch.object(
                provider,
                "resolve_command",
                return_value=(command, self._healthy_resolution(command)),
            ), patch.object(
                urllib.request,
                "urlopen",
                side_effect=refused,
            ) as urlopen, patch(
                "app.ocr_flow.subprocess.run",
            ) as run:
                result = provider.run(request)

        self.assertFalse(result.success)
        self.assertIn("connection refused", result.error)
        self.assertFalse(request.output_dir.exists())
        run.assert_not_called()
        urlopen.assert_called_once_with("http://127.0.0.1:8002/openapi.json", timeout=3.0)

    def test_provider_success_only_generates_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path, _runtime_python = self._write_local_python_mineru(app_root)
            provider = MineruOcrProvider(app_root, 1)
            request = OcrProviderRequest(
                document_id="job-1",
                input_path="paper.pdf",
                output_dir=app_root / "outputs" / "job-1",
                timeout_seconds=30,
            )
            request.output_dir.mkdir(parents=True)
            (request.output_dir / "paper.md").write_text("1. 题目", encoding="utf-8")

            with patch(
                "app.ocr_flow.subprocess.run",
                return_value=subprocess.CompletedProcess([str(command_path)], 0, "", ""),
            ):
                result = provider.run(request)

        self.assertTrue(result.success)
        self.assertEqual("mineru", result.metadata["ocrProvider"])
        self.assertIsInstance(result.bundle, CanonicalOcrBundle)

    def test_orchestrator_runs_postprocess_after_provider_artifacts_exist(self):
        job = {"id": "job-1", "status": "running"}
        provider = Mock()
        bundle = CanonicalOcrBundle(
            document_id="job-1",
            input_sha256="sha",
            canonical_markdown="1. 题目",
            artifact_root=self._temporary_artifact_root(),
        )
        provider.run.return_value = OcrProviderResult(success=True, bundle=bundle, metadata={"ocrProvider": "external"})
        written_jobs: list[dict] = []

        with patch.object(ocr_execution, "read_job", side_effect=lambda _job_id: job), \
                patch.object(ocr_execution, "selected_provider_name", return_value="mineru"), \
                patch.object(ocr_execution, "selected_ocr_provider", return_value=provider), \
                patch.object(ocr_execution, "run_postprocess_bundle", return_value={"questions": [{"id": "1"}]}) as postprocess, \
                patch.object(ocr_execution, "write_job", side_effect=lambda current: written_jobs.append(dict(current))):
            ocr_execution.run_ocr_provider_job("job-1", "paper.pdf")

        request = provider.run.call_args.args[0]
        self.assertEqual("job-1", request.document_id)
        self.assertEqual("paper.pdf", request.input_path)
        self.assertEqual("external", job["ocrProvider"])
        postprocess.assert_called_once_with(bundle)
        self.assertEqual("success", job["status"])
        self.assertEqual({"questions": [{"id": "1"}]}, job["outputs"])
        self.assertTrue(written_jobs)

    def test_orchestrator_marks_job_failed_when_postprocess_rejects_artifacts(self):
        job = {"id": "job-1", "status": "running"}
        provider = Mock()
        bundle = CanonicalOcrBundle(
            document_id="job-1",
            input_sha256="sha",
            canonical_markdown="1. 题目",
            artifact_root=self._temporary_artifact_root(),
        )
        provider.run.return_value = OcrProviderResult(success=True, bundle=bundle)

        with patch.object(ocr_execution, "read_job", side_effect=lambda _job_id: job), \
                patch.object(ocr_execution, "selected_provider_name", return_value="mineru"), \
                patch.object(ocr_execution, "selected_ocr_provider", return_value=provider), \
                patch.object(ocr_execution, "run_postprocess_bundle", side_effect=ValueError("invalid OCR bundle")), \
                patch.object(ocr_execution, "write_job") as write:
            ocr_execution.run_ocr_provider_job("job-1", "paper.pdf")

        self.assertEqual("failed", job["status"])
        self.assertEqual("invalid OCR bundle", job["error"])
        self.assertGreaterEqual(write.call_count, 1)
        self.assertEqual(job, write.call_args.args[0])

    def test_orchestrator_marks_job_failed_when_provider_raises(self):
        job = {"id": "job-1", "status": "running"}
        provider = Mock()
        provider.run.side_effect = RuntimeError("provider crashed")

        with patch.object(ocr_execution, "read_job", side_effect=lambda _job_id: job), \
                patch.object(ocr_execution, "selected_provider_name", return_value="external"), \
                patch.object(ocr_execution, "selected_ocr_provider", return_value=provider), \
                patch.object(ocr_execution, "write_job"):
            ocr_execution.run_ocr_provider_job("job-1", "paper.pdf")

        self.assertEqual("failed", job["status"])
        self.assertEqual("provider crashed", job["error"])

    def test_orchestrator_rejects_bundle_for_another_job(self):
        job = {"id": "job-1", "status": "running"}
        provider = Mock()
        wrong_bundle = CanonicalOcrBundle(
            document_id="job-2",
            input_sha256="sha",
            canonical_markdown="1. 错题",
            artifact_root=self._temporary_artifact_root(),
        )
        provider.run.return_value = OcrProviderResult(success=True, bundle=wrong_bundle)

        with patch.object(ocr_execution, "read_job", side_effect=lambda _job_id: job), \
                patch.object(ocr_execution, "selected_provider_name", return_value="external"), \
                patch.object(ocr_execution, "selected_ocr_provider", return_value=provider), \
                patch.object(ocr_execution, "run_postprocess_bundle") as postprocess, \
                patch.object(ocr_execution, "write_job"):
            ocr_execution.run_ocr_provider_job("job-1", "paper.pdf")

        postprocess.assert_not_called()
        self.assertEqual("failed", job["status"])
        self.assertIn("does not match", job["error"])

    def test_pdf_job_fails_before_persisting_when_provider_is_unavailable(self):
        class MissingProvider:
            def status(self):
                return {"installed": False, "error": "No valid MinerU command found."}

        with tempfile.TemporaryDirectory() as tmp:
            upload_root = Path(tmp)
            upload = UploadFile(
                file=BytesIO(b"%PDF"),
                filename="paper.pdf",
                headers=Headers({"content-type": "application/pdf"}),
            )

            with patch.object(worker_base, "selected_ocr_provider", return_value=MissingProvider()):
                with self.assertRaises(HTTPException) as raised:
                    worker_base.create_ocr_job_record(BackgroundTasks(), upload, upload_root)

            self.assertEqual([], list(upload_root.iterdir()))
            self.assertEqual(503, raised.exception.status_code)
            self.assertIn("OCR provider is unavailable", raised.exception.detail)

    def test_markdown_job_does_not_require_ocr_provider(self):
        class MissingProvider:
            def status(self):
                return {"installed": False, "error": "No valid MinerU command found."}

        with tempfile.TemporaryDirectory() as tmp:
            upload_root = Path(tmp)
            upload = UploadFile(
                file=BytesIO(b"# paper"),
                filename="paper.md",
                headers=Headers({"content-type": "text/markdown"}),
            )

            with patch.object(worker_base, "selected_ocr_provider", return_value=MissingProvider()), \
                    patch.object(worker_base, "write_job"):
                job = worker_base.create_ocr_job_record(BackgroundTasks(), upload, upload_root)

        self.assertEqual("pending", job["status"])
        self.assertEqual("paper.md", job["filename"])

    def test_summarize_repairs_stale_running_step_after_later_success(self):
        flow = worker_base.build_ocr_flow("2026-07-06T11:34:06+00:00")
        steps = {step["id"]: step for step in flow["steps"]}
        steps["llm-boundary-refine"].update(
            {
                "status": "running",
                "startedAt": "2026-07-06T11:37:17+00:00",
                "finishedAt": None,
                "message": "正在让大模型确认边界，不改写题干",
            }
        )
        steps["question-structure-build"].update(
            {
                "status": "success",
                "startedAt": "2026-07-06T11:38:48+00:00",
                "finishedAt": "2026-07-06T11:38:49+00:00",
                "message": "已生成 24 道父题",
            }
        )

        summarized = worker_base.summarize_ocr_flow(flow)

        repaired = next(step for step in summarized["steps"] if step["id"] == "llm-boundary-refine")
        self.assertEqual("skipped", repaired["status"])
        self.assertEqual("2026-07-06T11:38:48+00:00", repaired["finishedAt"])
        self.assertIn("自动结束", repaired["message"])


if __name__ == "__main__":
    unittest.main()
