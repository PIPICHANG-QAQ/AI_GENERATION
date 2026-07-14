#!/usr/bin/env python3
"""Unit tests for the OCR Flow golden-corpus tooling."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import ocrflow_golden
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

    def test_rejects_empty_root_and_container_random_id_paths(self) -> None:
        payload = {"questions": [{"questionId": "q1"}]}

        for path in ("", "$", "questions[*]"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                compare_payloads(payload, payload, random_id_paths=[path])

    def test_rejects_candidate_container_at_configured_scalar_leaf(self) -> None:
        expected = {"job": {"jobId": "expected"}}
        actual = {"job": {"jobId": {"value": "candidate"}}}

        with self.assertRaises(ValueError):
            compare_payloads(expected, actual, random_id_paths=["job.jobId"])

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

    def test_pair_compare_rejects_release_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory) / "payload.json"
            payload.write_text("{}", encoding="utf-8")

            code, report = self.run_cli(
                "compare", "--baseline", str(payload), "--candidate", str(payload),
                "--release",
            )

        self.assertNotEqual(0, code)
        self.assertEqual("invalid_arguments", report["status"])

    def test_release_capture_rejects_controlled_candidate_difference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paper = root / "paper.md"
            replay = root / "processing-job.json"
            expected = root / "expected.json"
            manifest = root / "manifest.json"
            output = root / "capture.json"
            paper.write_text("paper", encoding="utf-8")
            replay.write_text('{"rawJob":"input"}', encoding="utf-8")
            expected.write_text('{"value":"expected"}', encoding="utf-8")
            manifest.write_text(json.dumps({
                "schemaVersion": "ocrflow-golden.v1",
                "cases": [{
                    "id": "manifest-case",
                    "paper": "paper.md",
                    "expected": "expected.json",
                    "runner": "java-question-processing",
                    "replayInput": "processing-job.json",
                }],
            }), encoding="utf-8")
            controlled_case = {
                "id": "controlled-case",
                "scope": "controlled",
                "runner": "java-question-processing",
                "input": replay,
                "expected": expected,
                "randomIdPaths": [],
            }

            with mock.patch.object(
                ocrflow_golden,
                "_controlled_status",
                return_value={"valid": True, "caseCount": 20, "errors": []},
            ), mock.patch.object(
                ocrflow_golden,
                "_case_descriptors",
                return_value=[controlled_case],
            ), mock.patch.object(
                ocrflow_golden,
                "_run_replay_cases",
                return_value={"controlled-case": {"value": "actual"}},
            ):
                code, report = self.run_cli(
                    "capture", "--manifest", str(manifest), "--mode", "replay",
                    "--output", str(output), "--release",
                )
                output_exists = output.exists()

        self.assertEqual(1, code)
        self.assertEqual("different", report["status"])
        self.assertFalse(output_exists)

    def test_capture_executes_runner_on_raw_replay_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = root / "expected.json"
            replay = root / "processing-job.json"
            manifest = root / "manifest.json"
            output = root / "capture.json"
            expected.write_text(json.dumps({"value": "expected"}), encoding="utf-8")
            replay.write_text(json.dumps({"rawJob": "input"}), encoding="utf-8")
            manifest.write_text(json.dumps({
                "schemaVersion": "ocrflow-golden.v1",
                "randomIdPaths": [],
                "cases": [{
                    "id": "case-1",
                    "paper": "paper.md",
                    "expected": "expected.json",
                    "runner": "java-question-processing",
                    "replayInput": "processing-job.json",
                }],
            }), encoding="utf-8")
            (root / "paper.md").write_text("paper", encoding="utf-8")

            with mock.patch.object(
                ocrflow_golden,
                "_run_replay_cases",
                create=True,
                return_value={"case-1": {"value": "runner-candidate"}},
            ) as runner:
                code, report = self.run_cli(
                    "capture", "--manifest", str(manifest), "--mode", "replay",
                    "--output", str(output),
                )

            self.assertEqual(0, code)
            self.assertEqual("captured", report["status"])
            runner.assert_called_once()
            captured = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                {"value": "runner-candidate"},
                captured["cases"][0]["payload"],
            )

    def test_compare_manifest_executes_runner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "paper.md").write_text("paper", encoding="utf-8")
            (root / "expected.json").write_text('{"value":"candidate"}', encoding="utf-8")
            (root / "processing-job.json").write_text('{"rawJob":"input"}', encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "schemaVersion": "ocrflow-golden.v1",
                "cases": [{
                    "id": "case-1",
                    "paper": "paper.md",
                    "expected": "expected.json",
                    "runner": "java-question-processing",
                    "replayInput": "processing-job.json",
                }],
            }), encoding="utf-8")

            with mock.patch.object(
                ocrflow_golden,
                "_run_replay_cases",
                create=True,
                return_value={"case-1": {"value": "candidate"}},
            ) as runner:
                code, report = self.run_cli("compare", "--manifest", str(manifest))

            self.assertEqual(0, code)
            self.assertEqual("equal", report["status"])
            runner.assert_called_once()

    def test_manifest_requires_explicit_runner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "paper.md").write_text("paper", encoding="utf-8")
            (root / "expected.json").write_text('{"value":"expected"}', encoding="utf-8")
            (root / "processing-job.json").write_text('{"rawJob":"input"}', encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "schemaVersion": "ocrflow-golden.v1",
                "cases": [{
                    "id": "case-1",
                    "paper": "paper.md",
                    "expected": "expected.json",
                    "replayInput": "processing-job.json",
                }],
            }), encoding="utf-8")

            code, report = self.run_cli("compare", "--manifest", str(manifest))

        self.assertNotEqual(0, code)
        self.assertEqual("manifest_invalid", report["status"])
        self.assertTrue(any("runner" in error for error in report["errors"]))

    def test_runner_failure_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "paper.md").write_text("paper", encoding="utf-8")
            (root / "expected.json").write_text('{"value":"expected"}', encoding="utf-8")
            (root / "processing-job.json").write_text('{"rawJob":"input"}', encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "schemaVersion": "ocrflow-golden.v1",
                "cases": [{
                    "id": "case-1",
                    "paper": "paper.md",
                    "expected": "expected.json",
                    "runner": "java-question-processing",
                    "replayInput": "processing-job.json",
                }],
            }), encoding="utf-8")

            with mock.patch.object(
                ocrflow_golden,
                "_run_replay_cases",
                create=True,
                side_effect=RuntimeError("runner crashed"),
            ):
                code, report = self.run_cli("compare", "--manifest", str(manifest))

        self.assertNotEqual(0, code)
        self.assertEqual("runner_failed", report["status"])

    def test_manifest_rejects_random_id_path_that_selects_expected_container(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "paper.md").write_text("paper", encoding="utf-8")
            (root / "expected.json").write_text(
                '{"job":{"jobId":"expected"}}', encoding="utf-8"
            )
            (root / "processing-job.json").write_text('{"rawJob":"input"}', encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "schemaVersion": "ocrflow-golden.v1",
                "randomIdPaths": ["job"],
                "cases": [{
                    "id": "case-1",
                    "paper": "paper.md",
                    "expected": "expected.json",
                    "runner": "java-question-processing",
                    "replayInput": "processing-job.json",
                }],
            }), encoding="utf-8")

            with mock.patch.object(
                ocrflow_golden,
                "_run_replay_cases",
                create=True,
                return_value={"case-1": {"job": {"jobId": "candidate"}}},
            ) as runner:
                code, report = self.run_cli("compare", "--manifest", str(manifest))

        self.assertNotEqual(0, code)
        self.assertEqual("manifest_invalid", report["status"])
        runner.assert_not_called()

    def test_capture_rejects_expected_as_replay_input_even_at_different_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = root / "expected.json"
            replay = root / "processing-job.json"
            manifest = root / "manifest.json"
            expected.write_text("{}", encoding="utf-8")
            replay.write_text("{}", encoding="utf-8")
            (root / "paper.md").write_text("paper", encoding="utf-8")
            manifest.write_text(json.dumps({
                "schemaVersion": "ocrflow-golden.v1",
                "cases": [{
                    "id": "case-1",
                    "paper": "paper.md",
                    "expected": "expected.json",
                    "runner": "java-question-processing",
                    "replayInput": "processing-job.json",
                }],
            }), encoding="utf-8")

            code, report = self.run_cli(
                "capture", "--manifest", str(manifest), "--mode", "replay",
                "--output", str(root / "capture.json"),
            )

            self.assertNotEqual(0, code)
            self.assertEqual("manifest_invalid", report["status"])
            self.assertTrue(any("same SHA-256" in error for error in report["errors"]))

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
                    "runner": "java-question-processing",
                    "replayInput": "provider.json",
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
    REQUIRED_FEATURES = [
        "option-images",
        "cross-page-options",
        "composite-questions",
        "child-question-images",
        "answer-duplicate-questions",
        "tables",
        "two-column",
        "formula",
        "header-noise",
    ]

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

    def test_release_rejects_valid_corpus_when_runner_candidate_differs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            corpus = root / "corpus"
            repository = Path(__file__).resolve().parents[1]
            raw_replay = (
                repository / "backend/src/test/resources/golden/ocrflow/processing-job.json"
            ).read_text(encoding="utf-8")
            current_expected = json.loads((
                repository / "backend/src/test/resources/golden/ocrflow/question-package.json"
            ).read_text(encoding="utf-8"))
            mismatched_expected = dict(current_expected)
            mismatched_expected["packageVersion"] = "intentionally-different"
            for index in range(20):
                case = corpus / f"controlled-{index:02d}"
                (case / "paper").mkdir(parents=True)
                (case / "provider-output").mkdir()
                (case / "expected").mkdir()
                files = {
                    "paper/paper.md": "paper",
                    "provider-output/processing-job.json": raw_replay,
                    "expected/question-package.json": json.dumps(
                        mismatched_expected, ensure_ascii=False
                    ),
                }
                for relative, content in files.items():
                    (case / relative).write_text(content, encoding="utf-8")
                (case / "case.json").write_text(json.dumps({
                    "schemaVersion": "ocrflow-controlled-case.v1",
                    "id": case.name,
                    "runner": "java-question-processing",
                    "replayInput": "provider-output/processing-job.json",
                    "features": self.REQUIRED_FEATURES,
                    "sha256": {
                        relative: hashlib.sha256(content.encode("utf-8")).hexdigest()
                        for relative, content in files.items()
                    },
                }), encoding="utf-8")

            (root / "paper.md").write_text("paper", encoding="utf-8")
            (root / "processing-job.json").write_text(raw_replay, encoding="utf-8")
            (root / "expected.json").write_text(
                json.dumps(current_expected, ensure_ascii=False), encoding="utf-8"
            )
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "schemaVersion": "ocrflow-golden.v1",
                "cases": [{
                    "id": "manifest-case",
                    "paper": "paper.md",
                    "expected": "expected.json",
                    "runner": "java-question-processing",
                    "replayInput": "processing-job.json",
                }],
            }), encoding="utf-8")

            with mock.patch.dict(os.environ, {"OCRFLOW_GOLDEN_ROOT": str(corpus)}):
                output = io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                    code = main(["compare", "--manifest", str(manifest), "--release"])
                report = json.loads(output.getvalue())

        self.assertEqual(1, code, report)
        self.assertEqual("different", report["status"])
        controlled = next(case for case in report["cases"] if case["id"] == "controlled-00")
        self.assertIn("packageVersion", controlled["differences"])


if __name__ == "__main__":
    unittest.main()
