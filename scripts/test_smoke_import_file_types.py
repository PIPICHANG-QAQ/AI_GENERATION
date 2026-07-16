#!/usr/bin/env python3
"""Regression tests for portable file-type smoke sample generation."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import smoke_import_file_types


class SmokeImportFileTypesTest(unittest.TestCase):
    def test_make_doc_uses_soffice_when_textutil_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "sample.doc"

            def which(command: str) -> str | None:
                return "/usr/bin/soffice" if command == "soffice" else None

            def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                self.assertEqual(
                    [
                        "/usr/bin/soffice",
                        "--headless",
                        "--convert-to",
                        "doc",
                        "--outdir",
                        str(output.parent),
                        str(output.with_suffix(".rtf")),
                    ],
                    command,
                )
                output.write_bytes(b"generated doc")
                return subprocess.CompletedProcess(command, 0, "converted", "")

            with mock.patch.object(shutil, "which", side_effect=which), mock.patch.object(
                smoke_import_file_types.subprocess,
                "run",
                side_effect=run,
            ):
                smoke_import_file_types.make_doc(output)

            self.assertEqual(b"generated doc", output.read_bytes())


if __name__ == "__main__":
    unittest.main()
