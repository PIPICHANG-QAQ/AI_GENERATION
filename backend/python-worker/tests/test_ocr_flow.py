import os
import subprocess
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException
from starlette.datastructures import Headers, UploadFile

from app.ocr_flow import MineruOcrProvider, OcrFlowRuntime
from app import worker_base


class MineruOcrProviderTest(unittest.TestCase):
    def _write_local_mineru(self, app_root: Path, content: str) -> Path:
        command = app_root / ".venv" / "bin" / "mineru"
        command.parent.mkdir(parents=True)
        command.write_text(content, encoding="utf-8")
        command.chmod(0o755)
        return command

    def test_version_probe_timeout_does_not_disable_available_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            command_path = self._write_local_mineru(app_root, "#!/bin/sh\nexit 0\n")
            provider = MineruOcrProvider(app_root, 1)

            with patch(
                "app.ocr_flow.subprocess.run",
                side_effect=subprocess.TimeoutExpired([str(command_path), "--version"], 1),
            ):
                command, resolution = provider.resolve_command()

        self.assertIsNotNone(command)
        self.assertEqual("local-venv-script", command.source)
        self.assertIsNone(resolution["version"])
        self.assertTrue(resolution["candidates"][0]["valid"])
        self.assertFalse(resolution["candidates"][0]["versionProbeOk"])
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
            provider = MineruOcrProvider(app_root, 1)
            job = {"id": "job-1", "status": "pending"}
            runtime = OcrFlowRuntime(
                output_root=app_root / "outputs",
                timeout_seconds=30,
                now_iso=lambda: "2026-07-08T00:00:00+00:00",
                read_job=lambda _job_id: job,
                write_job=lambda _job: None,
                collect_outputs=lambda _job_id: {"questions": []},
                mark_step=lambda current, *_args: current,
            )

            with patch.dict(os.environ, {"MINERU_API_URL": "http://127.0.0.1:8002"}), patch(
                "app.ocr_flow.subprocess.run",
                return_value=subprocess.CompletedProcess([str(command_path)], 0, "", ""),
            ) as run:
                provider.run("job-1", "paper.pdf", runtime)

        mineru_cmd = run.call_args.args[0]
        self.assertIn("--api-url", mineru_cmd)
        self.assertIn("http://127.0.0.1:8002", mineru_cmd)
        self.assertEqual("http://127.0.0.1:8002", job["mineruApiUrl"])

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
