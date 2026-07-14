#!/usr/bin/env python3
"""Unit tests for the OCR Flow golden-corpus tooling."""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from ocrflow_golden import (
    compare_payloads,
    main,
    validate_controlled_corpus,
)


class ComparatorTest(unittest.TestCase):
    def test_normalizes_temporal_trace_and_configured_random_ids(self) -> None:
        expected = {
            "job": {
                "jobId": "job-expected",
                "createdAt": "2026-01-01T00:00:00",
                "updatedAt": "2026-01-01T00:01:00",
                "startedAt": "2026-01-01T00:02:00",
                "finishedAt": "2026-01-01T00:03:00",
                "traceId": "trace-expected",
            },
            "questions": [{"questionId": "question-expected", "content": "same"}],
        }
        actual = {
            "job": {
                "jobId": "job-actual",
                "createdAt": "2026-07-14T00:00:00",
                "updatedAt": "2026-07-14T00:01:00",
                "startedAt": "2026-07-14T00:02:00",
                "finishedAt": "2026-07-14T00:03:00",
                "traceId": "trace-actual",
            },
            "questions": [{"questionId": "question-actual", "content": "same"}],
        }

        differences = compare_payloads(
            expected,
            actual,
            random_id_paths=["job.jobId", "questions[*].questionId"],
        )

        self.assertEqual({}, differences)

    def test_unconfigured_random_id_is_not_normalized(self) -> None:
        differences = compare_payloads({"jobId": "a"}, {"jobId": "b"})

        self.assertIn("jobId", differences)

    def test_rejects_option_and_placement_changes_with_precise_paths(self) -> None:
        expected = {
            "questions": [{
                "id": "q1",
                "options": [{"label": "A", "content": "甲"}],
                "imagePlacements": [{
                    "imageId": "i1",
                    "target": {"kind": "option", "optionLabel": "A"},
                }],
            }],
        }
        actual = {
            "questions": [{
                "id": "q1",
                "options": [{"label": "A", "content": "乙"}],
                "imagePlacements": [{"imageId": "i1", "target": {"kind": "stem"}}],
            }],
        }

        differences = compare_payloads(expected, actual)

        self.assertIn("questions[0].options[0].content", differences)
        self.assertIn("questions[0].imagePlacements[0].target.kind", differences)

    def test_rejects_order_images_warnings_and_validation_changes(self) -> None:
        expected = {
            "questions": [{"id": "q1"}, {"id": "q2"}],
            "images": [{"id": "image-1", "url": "/one.png"}],
            "warnings": [{"code": "W1"}],
            "validation": {"status": "ok"},
        }
        actual = {
            "questions": [{"id": "q2"}, {"id": "q1"}],
            "images": [{"id": "image-1", "url": "/two.png"}],
            "warnings": [{"code": "W2"}],
            "validation": {"status": "review"},
        }

        differences = compare_payloads(expected, actual)

        self.assertIn("questions[0].id", differences)
        self.assertIn("questions[1].id", differences)
        self.assertIn("images[0].url", differences)
        self.assertIn("warnings[0].code", differences)
        self.assertIn("validation.status", differences)


class CliTest(unittest.TestCase):
    def run_cli(self, *args: str) -> tuple[int, dict[str, object]]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = main(list(args))
        return code, json.loads(output.getvalue())

    def test_compare_requires_exactly_one_complete_mode(self) -> None:
        for args in (
            ("compare",),
            ("compare", "--baseline", "a.json"),
            ("compare", "--candidate", "b.json"),
            (
                "compare", "--manifest", "manifest.json",
                "--baseline", "a.json", "--candidate", "b.json",
            ),
        ):
            with self.subTest(args=args):
                code, report = self.run_cli(*args)
                self.assertNotEqual(0, code)
                self.assertEqual("invalid_arguments", report["status"])

    def test_baseline_compare_outputs_machine_readable_diff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline.json"
            candidate = root / "candidate.json"
            baseline.write_text(json.dumps({"questions": [{"content": "甲"}]}), encoding="utf-8")
            candidate.write_text(json.dumps({"questions": [{"content": "乙"}]}), encoding="utf-8")

            code, report = self.run_cli(
                "compare", "--baseline", str(baseline), "--candidate", str(candidate)
            )

            self.assertEqual(1, code)
            self.assertEqual("different", report["status"])
            self.assertIn("questions[0].content", report["differences"])

    def test_capture_replay_uses_provider_output_not_expected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = root / "expected.json"
            replay = root / "provider.json"
            manifest = root / "manifest.json"
            output = root / "capture.json"
            expected.write_text(json.dumps({"value": "expected"}), encoding="utf-8")
            replay.write_text(json.dumps({"value": "replayed-current-output"}), encoding="utf-8")
            manifest.write_text(json.dumps({
                "schemaVersion": "ocrflow-golden.v1",
                "randomIdPaths": [],
                "cases": [{
                    "id": "case-1",
                    "paper": "paper.md",
                    "expected": "expected.json",
                    "providerOutput": "provider.json",
                }],
            }), encoding="utf-8")
            (root / "paper.md").write_text("paper", encoding="utf-8")

            code, report = self.run_cli(
                "capture", "--manifest", str(manifest), "--mode", "replay",
                "--output", str(output),
            )

            self.assertEqual(0, code)
            self.assertEqual("captured", report["status"])
            captured = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                {"value": "replayed-current-output"},
                captured["cases"][0]["payload"],
            )

    def test_capture_rejects_expected_as_provider_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "payload.json"
            manifest = root / "manifest.json"
            payload.write_text("{}", encoding="utf-8")
            (root / "paper.md").write_text("paper", encoding="utf-8")
            manifest.write_text(json.dumps({
                "schemaVersion": "ocrflow-golden.v1",
                "cases": [{
                    "id": "case-1",
                    "paper": "paper.md",
                    "expected": "payload.json",
                    "providerOutput": "payload.json",
                }],
            }), encoding="utf-8")

            code, report = self.run_cli(
                "capture", "--manifest", str(manifest), "--mode", "replay",
                "--output", str(root / "capture.json"),
            )

            self.assertNotEqual(0, code)
            self.assertEqual("manifest_invalid", report["status"])

    def test_compare_manifest_reports_malformed_replay_as_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            (root / "paper.md").write_text("paper", encoding="utf-8")
            (root / "expected.json").write_text("{}", encoding="utf-8")
            (root / "provider.json").write_text("not-json", encoding="utf-8")
            manifest.write_text(json.dumps({
                "schemaVersion": "ocrflow-golden.v1",
                "cases": [{
                    "id": "case-1",
                    "paper": "paper.md",
                    "expected": "expected.json",
                    "providerOutput": "provider.json",
                }],
            }), encoding="utf-8")

            code, report = self.run_cli("compare", "--manifest", str(manifest))

            self.assertNotEqual(0, code)
            self.assertEqual("replay_invalid", report["status"])

    def test_release_mode_rejects_missing_controlled_root(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            code, report = self.run_cli(
                "compare", "--manifest", "missing.json", "--release"
            )

        self.assertNotEqual(0, code)
        self.assertEqual("controlled_corpus_invalid", report["status"])


class ControlledCorpusTest(unittest.TestCase):
    def test_missing_root_is_an_explicit_local_skip(self) -> None:
        with self.assertRaises(unittest.SkipTest):
            validate_controlled_corpus(None, release=False)

    def test_release_rejects_incomplete_and_bad_hash_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = root / "case-01"
            (case / "paper").mkdir(parents=True)
            (case / "provider-output").mkdir()
            (case / "expected").mkdir()
            (case / "paper" / "paper.md").write_text("paper", encoding="utf-8")
            (case / "provider-output" / "result.json").write_text("{}", encoding="utf-8")
            (case / "expected" / "question-package.json").write_text("{}", encoding="utf-8")
            (case / "case.json").write_text(json.dumps({
                "schemaVersion": "ocrflow-controlled-case.v1",
                "id": "case-01",
                "features": ["formula"],
                "sha256": {
                    "paper/paper.md": "bad",
                    "provider-output/result.json": "bad",
                    "expected/question-package.json": "bad",
                },
            }), encoding="utf-8")

            result = validate_controlled_corpus(root, release=True)

            self.assertFalse(result["valid"])
            self.assertTrue(any("at least 20" in error for error in result["errors"]))
            self.assertTrue(any("SHA-256" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
