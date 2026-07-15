import os
import subprocess
import sys
import tempfile
import unittest
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
        python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        python.chmod(0o755)
        return python

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

    def test_runtime_probe_uses_sibling_python_and_exact_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path = self._write_local_mineru(app_root, "#!/bin/sh\nexit 0\n")
            runtime_python = self._write_runtime_python(command_path)
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
        self.assertFalse(run.call_args.kwargs["check"])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_status_selects_command_when_runtime_probe_is_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path = self._write_local_mineru(app_root, "#!/bin/sh\nexit 0\n")
            runtime_python = self._write_runtime_python(command_path)
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

    def test_status_rejects_command_when_runtime_import_probe_fails(self):
        runtime_error = "ImportError: cannot import name 'Markup' from 'markupsafe'"
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path = self._write_local_mineru(app_root, "#!/bin/sh\nexit 0\n")
            self._write_runtime_python(command_path)
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
            command_path = self._write_local_mineru(app_root, "#!/bin/sh\nexit 0\n")
            runtime_python = self._write_runtime_python(command_path)
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
            command_path = self._write_local_mineru(app_root, "#!/bin/sh\nexit 0\n")
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
            command_path = self._write_local_mineru(app_root, "#!/bin/sh\nexit 0\n")
            self._write_runtime_python(command_path)
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
            first_command_path.parent.mkdir(parents=True)
            first_command_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            first_command_path.chmod(0o755)
            first_python = self._write_runtime_python(first_command_path)
            second_command_path = app_root / "second" / "bin" / "mineru"
            second_command_path.parent.mkdir(parents=True)
            second_command_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            second_command_path.chmod(0o755)
            second_python = self._write_runtime_python(second_command_path)
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
                command_path = self._write_local_mineru(app_root, "#!/bin/sh\nexit 0\n")
                self._write_runtime_python(command_path)
                command = self._provider_command(command_path)
                provider = MineruOcrProvider(app_root, 5)
                provider._monotonic = Mock(side_effect=[100.0, 159.9])

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
            command_path = self._write_local_mineru(app_root, "#!/bin/sh\nexit 0\n")
            self._write_runtime_python(command_path)
            command = self._provider_command(command_path)
            provider = MineruOcrProvider(app_root, 5)
            provider._monotonic = Mock(side_effect=[100.0, 160.0])

            with patch(
                "app.ocr_flow.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ) as run:
                self._runtime_probe(provider)(command)
                self._runtime_probe(provider)(command)

        self.assertEqual(2, run.call_count)

    def test_runtime_probe_cache_is_reused_across_provider_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path = self._write_local_mineru(app_root, "#!/bin/sh\nexit 0\n")
            self._write_runtime_python(command_path)
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

    def test_runtime_probe_cache_invalidates_when_command_or_interpreter_mtime_changes(self):
        for changed_file in ("command", "interpreter"):
            with self.subTest(changed_file=changed_file), tempfile.TemporaryDirectory() as tmp:
                app_root = Path(tmp)
                command_path = self._write_local_mineru(app_root, "#!/bin/sh\nexit 0\n")
                runtime_python = self._write_runtime_python(command_path)
                command = self._provider_command(command_path)
                provider = MineruOcrProvider(app_root, 5)
                provider._monotonic = Mock(side_effect=[100.0, 101.0])
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

    def test_configured_command_uses_python_sibling_of_resolved_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path = self._write_local_mineru(app_root, "#!/bin/sh\nexit 0\n")
            runtime_python = self._write_runtime_python(command_path)
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

    def test_version_probe_timeout_does_not_disable_available_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path = self._write_local_mineru(app_root, "#!/bin/sh\nexit 0\n")
            self._write_runtime_python(command_path)
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

    def test_run_uses_configured_mineru_api_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path = self._write_local_mineru(app_root, "#!/bin/sh\nexit 0\n")
            self._write_runtime_python(command_path)
            provider = MineruOcrProvider(app_root, 1)
            request = OcrProviderRequest(
                document_id="job-1",
                input_path="paper.pdf",
                output_dir=app_root / "outputs" / "job-1",
                timeout_seconds=30,
            )
            request.output_dir.mkdir(parents=True)
            (request.output_dir / "paper.md").write_text("1. 题目", encoding="utf-8")

            with patch.dict(os.environ, {"MINERU_API_URL": "http://127.0.0.1:8002"}), patch(
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

    def test_provider_success_only_generates_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path = self._write_local_mineru(app_root, "#!/bin/sh\nexit 0\n")
            self._write_runtime_python(command_path)
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
