#!/usr/bin/env python3
"""Tests for the OCR Flow performance baseline CLI."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import benchmark_ocrflow


class BenchmarkMathTest(unittest.TestCase):
    def test_summarize_runs_records_percentiles_and_provider_metrics(self):
        report = benchmark_ocrflow.summarize_runs(
            "case-1",
            [
                {"durationMs": 10, "peakRssMb": 2, "ocrProviderCalls": 1, "llmProviderCalls": 2, "cacheHits": 1},
                {"durationMs": 30, "peakRssMb": 4, "ocrProviderCalls": 1, "llmProviderCalls": 0, "cacheHits": 3},
                {"durationMs": 20, "peakRssMb": 3, "ocrProviderCalls": 1, "llmProviderCalls": 1, "cacheHits": 2},
            ],
        )

        self.assertEqual("case-1", report["caseId"])
        self.assertEqual(20, report["p50Ms"])
        self.assertEqual(30, report["p95Ms"])
        self.assertEqual(4, report["peakRssMb"])
        self.assertEqual(3, report["ocrProviderCalls"])
        self.assertEqual(3, report["llmProviderCalls"])
        self.assertEqual(6, report["cacheHits"])

    def test_compare_enforces_provider_and_content_gates(self):
        baseline = {
            "caseId": "case-1", "p50Ms": 100, "p95Ms": 100, "throughputPerMinute": 10,
            "peakRssMb": 100, "ocrProviderCalls": 1, "llmProviderCalls": 2,
            "cacheHits": 0, "normalizedContentDiff": 0,
        }
        candidate = {**baseline, "p95Ms": 104, "llmProviderCalls": 3}
        gates = {
            "warning": {"p50RatioMax": 1.02, "p95RatioMax": 1.00, "throughputRatioMin": 1.00},
            "failure": {"p95RatioMax": 1.03, "throughputRatioMin": 0.97, "peakRssRatioMax": 1.05},
            "providerCallDeltaMax": 0,
            "normalizedContentDiffMax": 0,
        }

        result = benchmark_ocrflow.compare_reports(baseline, candidate, gates)

        self.assertFalse(result["passed"])
        self.assertIn("llmProviderCalls", result["failures"])

    def test_fractional_count_metrics_are_rejected(self):
        payload = {
            "schemaVersion": "ocrflow-benchmark.v1", "mode": "replay",
            "provider": {"name": "java-question-processing", "model": "deterministic", "version": "current"},
            "runsPerCase": 1, "goldenManifestSha256": "a" * 64,
            "environment": {"gitCommit": "a" * 40, "python": "3.10", "platform": "test", "mode": "replay"},
            "cases": [{"caseId": "x", "runs": 1, "p50Ms": 1, "p95Ms": 1, "throughputPerMinute": 1,
                       "peakRssMb": 1, "ocrProviderCalls": 0.5, "llmProviderCalls": 0,
                       "cacheHits": 0, "normalizedContentDiff": 0}],
        }
        with self.assertRaises(benchmark_ocrflow.BaselineValidationError):
            benchmark_ocrflow._validate_artifact(payload, name="candidate")

        payload["runsPerCase"] = True
        with self.assertRaises(benchmark_ocrflow.BaselineValidationError):
            benchmark_ocrflow._validate_artifact(payload, name="candidate")


class BenchmarkArchiveTest(unittest.TestCase):
    def test_archive_restore_is_content_addressed_and_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "current.json"
            ref = root / "baseline-ref.json"
            store = root / "publish"
            payload = {
                "schemaVersion": "ocrflow-benchmark.v1",
                "mode": "replay",
                "goldenManifestSha256": "a" * 64,
                "environment": {"mode": "replay", "gitCommit": "a" * 40, "python": "3.10", "platform": "test"},
                "provider": {"name": "java-question-processing", "model": "deterministic", "version": "current"},
                "runsPerCase": 1,
                "cases": [{
                    "caseId": "case-1", "runs": 1, "p50Ms": 10, "p95Ms": 10,
                    "throughputPerMinute": 10, "peakRssMb": 1,
                    "ocrProviderCalls": 0, "llmProviderCalls": 0,
                    "cacheHits": 0, "normalizedContentDiff": 0,
                }],
            }
            artifact.write_text(json.dumps(payload), encoding="utf-8")

            archive = benchmark_ocrflow.archive_baseline(
                artifact,
                store,
                ref,
                {
                    "goldenManifestSha256": "a" * 64,
                    "environment": {"mode": "replay", "gitCommit": "a" * 40, "python": "3.10", "platform": "test"},
                    "provider": {"name": "java-question-processing", "model": "deterministic", "version": "current"},
                },
            )
            self.assertTrue(archive["artifactId"])
            restored = root / "restored.json"
            result = benchmark_ocrflow.restore_baseline(ref, store, restored)

            self.assertEqual("restored", result["status"])
            self.assertEqual(payload, json.loads(restored.read_text(encoding="utf-8")))

            (store / "artifacts" / f"{archive['artifactId']}.json").write_text(
                json.dumps({"changed": True}), encoding="utf-8"
            )
            with self.assertRaises(benchmark_ocrflow.BaselineValidationError):
                benchmark_ocrflow.restore_baseline(ref, store, root / "bad.json")

    def test_restore_rejects_path_escape_and_missing_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = root / "store"
            (store / "artifacts").mkdir(parents=True)
            outside = root / "outside.json"
            outside.write_text(json.dumps({"schemaVersion": "ocrflow-benchmark.v1"}), encoding="utf-8")
            ref = root / "ref.json"
            ref.write_text(json.dumps({
                "schemaVersion": "ocrflow-baseline-ref.v1",
                "artifactId": "0" * 64,
                "sha256": "0" * 64,
                "artifact": "../outside.json",
                "goldenManifestSha256": "a" * 64,
                "environment": {"gitCommit": "x"},
                "provider": {"name": "x", "model": "x", "version": "x"},
            }), encoding="utf-8")
            with self.assertRaises(benchmark_ocrflow.BaselineValidationError):
                benchmark_ocrflow.restore_baseline(ref, store, root / "restored.json")


class BenchmarkCliTest(unittest.TestCase):
    @staticmethod
    def artifact(environment: dict[str, str]) -> dict[str, object]:
        case = {
            "caseId": "case-1", "runs": 5, "p50Ms": 10, "p95Ms": 10,
            "throughputPerMinute": 10, "peakRssMb": 1, "ocrProviderCalls": 0,
            "llmProviderCalls": 0, "cacheHits": 0, "normalizedContentDiff": 0,
        }
        return {
            "schemaVersion": "ocrflow-benchmark.v1", "mode": "replay",
            "provider": {"name": "java-question-processing", "model": "deterministic", "version": "current"},
            "runsPerCase": 5, "goldenManifestSha256": "a" * 64,
            "environment": environment, "rssScope": "batch", "cases": [case],
        }

    def test_baseline_command_requires_replay_and_writes_machine_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"schemaVersion": "ocrflow-golden.v1", "cases": []}), encoding="utf-8")
            output = root / "baseline.json"
            fake_runs = [{"durationMs": 5, "peakRssMb": 1, "ocrProviderCalls": 1, "llmProviderCalls": 0, "cacheHits": 0}]
            stream = io.StringIO()
            case = {"id": "case-1", "input": root / "input.json", "expected": root / "expected.json", "randomIdPaths": []}
            root.joinpath("input.json").write_text("{}", encoding="utf-8")
            root.joinpath("expected.json").write_text("{}", encoding="utf-8")
            with (
                mock.patch.object(benchmark_ocrflow, "_manifest_cases", return_value=[case]),
                mock.patch.object(benchmark_ocrflow, "run_replay_case", return_value=fake_runs),
                contextlib.redirect_stdout(stream),
            ):
                code = benchmark_ocrflow.main([
                    "baseline", "--manifest", str(manifest), "--runs", "1", "--output", str(output),
                ])

            self.assertEqual(0, code)
            self.assertEqual("baseline", json.loads(stream.getvalue())["status"])
            self.assertTrue(output.is_file())

    def test_compare_fails_closed_when_baseline_or_gates_is_missing(self):
        code = benchmark_ocrflow.main(["compare", "--baseline", "missing.json", "--candidate", "missing.json"])
        self.assertEqual(2, code)

    def test_default_compare_always_rebuilds_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            restored = root / ".artifacts" / "ocrflow-baseline" / "restored.json"
            candidate = root / ".artifacts" / "ocrflow-baseline" / "candidate.json"
            gates = root / "gates.json"
            environment = {"gitCommit": "a" * 40, "python": "3.10", "platform": "test", "mode": "replay"}
            restored.parent.mkdir(parents=True)
            restored.write_text(json.dumps(self.artifact(environment)), encoding="utf-8")
            candidate.write_text(json.dumps(self.artifact(environment)), encoding="utf-8")
            gates.write_text(json.dumps({"performance": {
                "status": "active",
                "warning": {"p50RatioMax": 2, "p95RatioMax": 2, "throughputRatioMin": 0},
                "failure": {"p95RatioMax": 3, "throughputRatioMin": 0, "peakRssRatioMax": 3},
                "providerCallDeltaMax": 0, "normalizedContentDiffMax": 0,
            }}), encoding="utf-8")
            rebuilt = self.artifact(environment)
            with mock.patch.object(benchmark_ocrflow, "ROOT", root), mock.patch.object(
                benchmark_ocrflow, "build_baseline", return_value=rebuilt
            ) as build:
                code = benchmark_ocrflow.main(["compare", "--gates", str(gates)])
            self.assertEqual(0, code)
            build.assert_called_once()


if __name__ == "__main__":
    unittest.main()
