import subprocess
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException
from starlette.datastructures import Headers, UploadFile

from app.ocr_flow import MineruOcrProvider
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


if __name__ == "__main__":
    unittest.main()
