#!/usr/bin/env python3
"""Archive and compare deterministic OCR Flow performance baselines."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import resource
import statistics
import subprocess
import sys
import time
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_SCHEMA = "ocrflow-benchmark.v1"
DEFAULT_GATES = ROOT / "tests/ocrflow-golden/gates.json"
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")

sys.path.insert(0, str(ROOT / "scripts"))
import ocrflow_golden  # noqa: E402


class BaselineValidationError(RuntimeError):
    """Raised when a published baseline cannot be trusted."""


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("at least one run is required")
    ordered = sorted(float(value) for value in values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * percentile) - 1))
    return ordered[index]


def _peak_rss_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    # macOS reports bytes; Linux reports KiB.
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return round(float(usage) / divisor, 3)


def summarize_runs(case_id: str, runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not runs:
        raise ValueError("runs must not be empty")
    durations = [float(run["durationMs"]) for run in runs]
    peak_rss = [float(run.get("peakRssMb", 0)) for run in runs]
    ocr_calls = [int(run.get("ocrProviderCalls", 0)) for run in runs]
    llm_calls = [int(run.get("llmProviderCalls", 0)) for run in runs]
    cache_hits = [int(run.get("cacheHits", 0)) for run in runs]
    total_duration = sum(durations)
    return {
        "caseId": case_id,
        "runs": len(runs),
        "p50Ms": _percentile(durations, 0.50),
        "p95Ms": _percentile(durations, 0.95),
        "throughputPerMinute": round(len(runs) * 60000 / max(total_duration, 0.001), 3),
        "peakRssMb": max(peak_rss),
        "ocrProviderCalls": sum(ocr_calls),
        "llmProviderCalls": sum(llm_calls),
        "cacheHits": sum(cache_hits),
        "normalizedContentDiff": int(sum(int(run.get("normalizedContentDiff", 0)) for run in runs)),
    }


def _ratio(candidate: Any, baseline: Any) -> float:
    baseline_value = float(baseline)
    if baseline_value == 0:
        return 1.0 if float(candidate) == 0 else float("inf")
    return float(candidate) / baseline_value


def compare_reports(baseline: dict[str, Any], candidate: dict[str, Any], gates: dict[str, Any]) -> dict[str, Any]:
    failures: dict[str, Any] = {}
    warnings: dict[str, Any] = {}
    warning_gates = gates.get("warning", {})
    failure_gates = gates.get("failure", {})
    ratios = {
        "p50Ms": _ratio(candidate.get("p50Ms", 0), baseline.get("p50Ms", 0)),
        "p95Ms": _ratio(candidate.get("p95Ms", 0), baseline.get("p95Ms", 0)),
        "throughputPerMinute": _ratio(candidate.get("throughputPerMinute", 0), baseline.get("throughputPerMinute", 0)),
        "peakRssMb": _ratio(candidate.get("peakRssMb", 0), baseline.get("peakRssMb", 0)),
    }
    if ratios["p50Ms"] > float(warning_gates.get("p50RatioMax", float("inf"))):
        warnings["p50Ms"] = ratios["p50Ms"]
    if ratios["p95Ms"] > float(warning_gates.get("p95RatioMax", float("inf"))):
        warnings["p95Ms"] = ratios["p95Ms"]
    if ratios["throughputPerMinute"] < float(warning_gates.get("throughputRatioMin", 0)):
        warnings["throughputPerMinute"] = ratios["throughputPerMinute"]
    if ratios["p95Ms"] > float(failure_gates.get("p95RatioMax", float("inf"))):
        failures["p95Ms"] = ratios["p95Ms"]
    if ratios["throughputPerMinute"] < float(failure_gates.get("throughputRatioMin", 0)):
        failures["throughputPerMinute"] = ratios["throughputPerMinute"]
    if ratios["peakRssMb"] > float(failure_gates.get("peakRssRatioMax", float("inf"))):
        failures["peakRssMb"] = ratios["peakRssMb"]
    for metric in ("ocrProviderCalls", "llmProviderCalls"):
        delta = int(candidate.get(metric, 0)) - int(baseline.get(metric, 0))
        if delta > int(gates.get("providerCallDeltaMax", 0)):
            failures[metric] = delta
    diff = int(candidate.get("normalizedContentDiff", 0))
    if diff > int(gates.get("normalizedContentDiffMax", 0)):
        failures["normalizedContentDiff"] = diff
    return {"passed": not failures, "ratios": ratios, "warnings": warnings, "failures": failures}


def _environment_fingerprint() -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:
        commit = ""
    return {
        "gitCommit": commit,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "mode": "replay",
    }


def _payload_metrics(payload: Any, expected: Any, random_id_paths: Sequence[str]) -> dict[str, int]:
    metrics = payload.get("llmMetrics") if isinstance(payload, dict) else None
    if not isinstance(metrics, dict) and isinstance(payload, dict):
        metrics = (payload.get("outputs") or {}).get("llmMetrics")
    if not isinstance(metrics, dict):
        metrics = {}
    calls = metrics.get("calls") or []
    llm_calls = sum(1 for call in calls if isinstance(call, dict) and call.get("cacheHit") is not True)
    differences = ocrflow_golden.compare_payloads(expected, payload, random_id_paths)
    return {
        "ocrProviderCalls": int(payload.get("ocrProviderCalls", 0)) if isinstance(payload, dict) else 0,
        "llmProviderCalls": llm_calls,
        "cacheHits": int(metrics.get("cacheHitCount", 0)),
        "normalizedContentDiff": len(differences),
    }


def run_replay_case(case: dict[str, Any], runs: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for _ in range(runs):
        started = time.perf_counter()
        result = ocrflow_golden._run_replay_cases([case])
        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        payload = result[case["id"]]
        try:
            expected = _read_json(Path(case["expected"]))
        except (OSError, json.JSONDecodeError) as exc:
            raise BaselineValidationError(f"expected invalid for {case['id']}: {exc}") from exc
        candidates.append({
            "durationMs": duration_ms,
            "peakRssMb": _peak_rss_mb(),
            **_payload_metrics(payload, expected, case.get("randomIdPaths", [])),
        })
    return candidates


def _manifest_cases(manifest_path: Path) -> list[dict[str, Any]]:
    manifest, errors = ocrflow_golden._load_manifest(manifest_path)
    if errors or manifest is None:
        raise BaselineValidationError("manifest invalid: " + "; ".join(errors))
    return ocrflow_golden._case_descriptors(manifest_path, manifest)


def build_baseline(manifest_path: Path, runs: int) -> dict[str, Any]:
    if runs < 1 or runs > 100:
        raise BaselineValidationError("runs must be between 1 and 100")
    cases = _manifest_cases(manifest_path)
    summaries = [summarize_runs(case["id"], run_replay_case(case, runs)) for case in cases]
    return {
        "schemaVersion": ARTIFACT_SCHEMA,
        "mode": "replay",
        "provider": {"name": "java-question-processing", "model": "deterministic", "version": "current"},
        "runsPerCase": runs,
        "goldenManifestSha256": _sha256(manifest_path),
        "environment": _environment_fingerprint(),
        "rssScope": "batch",
        "cases": summaries,
    }


def _validate_artifact(payload: Any, *, name: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schemaVersion") != ARTIFACT_SCHEMA:
        raise BaselineValidationError(f"{name} schemaVersion must be {ARTIFACT_SCHEMA}")
    if payload.get("mode") != "replay":
        raise BaselineValidationError(f"{name} mode must be replay")
    if not isinstance(payload.get("goldenManifestSha256"), str) or not HEX_SHA256.fullmatch(payload["goldenManifestSha256"]):
        raise BaselineValidationError(f"{name} golden manifest SHA-256 is missing or invalid")
    environment = payload.get("environment")
    if (
        not isinstance(environment, dict)
        or not re.fullmatch(r"[0-9a-f]{40}", str(environment.get("gitCommit", "")))
        or not environment.get("python")
        or not environment.get("platform")
        or environment.get("mode") != payload.get("mode")
    ):
        raise BaselineValidationError(f"{name} environment fingerprint is missing")
    provider = payload.get("provider")
    if not isinstance(provider, dict) or not all(provider.get(key) for key in ("name", "model", "version")):
        raise BaselineValidationError(f"{name} provider/model/version is missing")
    runs_per_case = payload.get("runsPerCase")
    if type(runs_per_case) is not int or runs_per_case < 1:
        raise BaselineValidationError(f"{name} runsPerCase must be a positive integer")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise BaselineValidationError(f"{name} cases must be a non-empty array")
    required_metrics = (
        "p50Ms", "p95Ms", "throughputPerMinute", "peakRssMb",
        "ocrProviderCalls", "llmProviderCalls", "cacheHits", "normalizedContentDiff",
    )
    integer_metrics = {"ocrProviderCalls", "llmProviderCalls", "cacheHits", "normalizedContentDiff"}
    seen: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("caseId"), str) or case["caseId"] in seen:
            raise BaselineValidationError(f"{name} has an invalid or duplicate case")
        seen.add(case["caseId"])
        for metric in required_metrics:
            value = case.get(metric)
            if metric in integer_metrics:
                valid = type(value) is int and value >= 0
            else:
                valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) and float(value) >= 0
            if not valid:
                raise BaselineValidationError(f"{name} has invalid {metric} for {case['caseId']}")
        if type(case.get("runs")) is not int or case["runs"] != runs_per_case:
            raise BaselineValidationError(f"{name} runs does not match runsPerCase for {case['caseId']}")
    return payload


def archive_baseline(input_path: Path, store_root: Path, ref_path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    if not input_path.is_file():
        raise BaselineValidationError(f"baseline does not exist: {input_path}")
    payload = _validate_artifact(_read_json(input_path), name="baseline")
    digest = _sha256(input_path)
    artifact_id = digest
    artifact = store_root / "artifacts" / f"{artifact_id}.json"
    artifact_bytes = input_path.read_bytes()
    if artifact.exists() and artifact.read_bytes() != artifact_bytes:
        raise BaselineValidationError(f"artifact id already exists with different bytes: {artifact_id}")
    manifest_sha = metadata.get("goldenManifestSha256")
    if manifest_sha != payload["goldenManifestSha256"] or not HEX_SHA256.fullmatch(str(manifest_sha)):
        raise BaselineValidationError("archive manifest fingerprint must match the artifact")
    if metadata.get("environment") != payload["environment"]:
        raise BaselineValidationError("archive environment fingerprint must match the artifact")
    if metadata.get("provider") != payload["provider"]:
        raise BaselineValidationError("archive provider fingerprint must match the artifact")
    artifact.parent.mkdir(parents=True, exist_ok=True)
    if not artifact.exists():
        artifact.write_bytes(artifact_bytes)
    ref = {
        "schemaVersion": "ocrflow-baseline-ref.v1",
        "artifactId": artifact_id,
        "sha256": digest,
        "artifact": f"artifacts/{artifact_id}.json",
        "goldenManifestSha256": payload["goldenManifestSha256"],
        "environment": payload["environment"],
        "provider": payload["provider"],
    }
    _write_json(ref_path, ref)
    return ref


def restore_baseline(ref_path: Path, store_root: Path, output_path: Path) -> dict[str, Any]:
    try:
        ref = _read_json(ref_path)
        if ref.get("status") == "pending-controlled-baseline":
            raise BaselineValidationError("baseline ref is not populated")
        if ref.get("schemaVersion") != "ocrflow-baseline-ref.v1":
            raise BaselineValidationError("baseline ref schema mismatch")
        expected_sha = ref.get("sha256")
        if not isinstance(expected_sha, str) or not HEX_SHA256.fullmatch(expected_sha) or ref.get("artifactId") != expected_sha:
            raise BaselineValidationError("baseline ref artifactId/SHA-256 is invalid")
        if ref.get("artifact") != f"artifacts/{expected_sha}.json":
            raise BaselineValidationError("baseline ref artifact path is not content-addressed")
        if not HEX_SHA256.fullmatch(str(ref.get("goldenManifestSha256", ""))):
            raise BaselineValidationError("baseline ref manifest fingerprint is missing")
        if not isinstance(ref.get("environment"), dict) or not isinstance(ref.get("provider"), dict):
            raise BaselineValidationError("baseline ref provenance is missing")
        artifact = store_root / ref["artifact"]
        if artifact.resolve().parent != (store_root / "artifacts").resolve():
            raise BaselineValidationError("baseline ref escapes artifact store")
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise BaselineValidationError(f"invalid baseline ref: {exc}") from exc
    if not artifact.is_file() or _sha256(artifact) != expected_sha:
        raise BaselineValidationError("baseline artifact is missing or SHA-256 does not match ref")
    payload = _validate_artifact(_read_json(artifact), name="baseline artifact")
    if ref["goldenManifestSha256"] != payload.get("goldenManifestSha256"):
        raise BaselineValidationError("baseline manifest fingerprint does not match ref")
    if ref["environment"] != payload.get("environment"):
        raise BaselineValidationError("baseline environment fingerprint does not match ref")
    if ref["provider"] != payload.get("provider"):
        raise BaselineValidationError("baseline provider fingerprint does not match ref")
    _write_json(output_path, payload)
    return {"status": "restored", "output": str(output_path), "artifactId": ref.get("artifactId")}


def _load_gates(path: Path) -> dict[str, Any]:
    try:
        gates = _read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise BaselineValidationError(f"gates invalid: {exc}") from exc
    performance = gates.get("performance", {})
    if performance.get("status") == "pending-task-2":
        raise BaselineValidationError("performance gates are not finalized")
    required = {
        "warning": ("p50RatioMax", "p95RatioMax", "throughputRatioMin"),
        "failure": ("p95RatioMax", "throughputRatioMin", "peakRssRatioMax"),
    }
    for section, keys in required.items():
        values = performance.get(section)
        if not isinstance(values, dict) or any(
            key not in values or not isinstance(values[key], (int, float))
            or not math.isfinite(float(values[key])) for key in keys
        ):
            raise BaselineValidationError(f"performance gates missing valid {section} thresholds")
    for key in ("providerCallDeltaMax", "normalizedContentDiffMax"):
        if not isinstance(performance.get(key), int) or performance[key] < 0:
            raise BaselineValidationError(f"performance gate {key} is missing or invalid")
    return performance


def _find_cases(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise BaselineValidationError("compare requires a non-empty cases array")
    result: dict[str, dict[str, Any]] = {}
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("caseId"), str):
            raise BaselineValidationError("each benchmark case must have a caseId")
        if case["caseId"] in result:
            raise BaselineValidationError(f"duplicate benchmark case: {case['caseId']}")
        result[case["caseId"]] = case
    return result


def compare_payload_reports(
    baseline_payload: dict[str, Any], candidate_payload: dict[str, Any], gates: dict[str, Any]
) -> dict[str, Any]:
    baseline_cases = _find_cases(baseline_payload)
    candidate_cases = _find_cases(candidate_payload)
    if set(baseline_cases) != set(candidate_cases):
        raise BaselineValidationError("baseline and candidate case ids do not match")
    case_results: dict[str, Any] = {}
    failures: dict[str, Any] = {}
    warnings: dict[str, Any] = {}
    for case_id in sorted(baseline_cases):
        result = compare_reports(baseline_cases[case_id], candidate_cases[case_id], gates)
        case_results[case_id] = result
        failures.update({f"{case_id}.{key}": value for key, value in result["failures"].items()})
        warnings.update({f"{case_id}.{key}": value for key, value in result["warnings"].items()})
    return {"passed": not failures, "cases": case_results, "failures": failures, "warnings": warnings}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    baseline = sub.add_parser("baseline")
    baseline.add_argument("--manifest", required=True, type=Path)
    baseline.add_argument("--runs", required=True, type=int)
    baseline.add_argument("--output", required=True, type=Path)
    archive = sub.add_parser("archive")
    archive.add_argument("--input", required=True, type=Path)
    archive.add_argument("--store-root", required=True, type=Path)
    archive.add_argument("--ref", required=True, type=Path)
    archive.add_argument("--golden-manifest-sha", required=True)
    restore = sub.add_parser("restore")
    restore.add_argument("--ref", required=True, type=Path)
    restore.add_argument("--store-root", required=True, type=Path)
    restore.add_argument("--output", required=True, type=Path)
    compare = sub.add_parser("compare")
    compare.add_argument("--baseline", type=Path)
    compare.add_argument("--candidate", type=Path)
    compare.add_argument("--manifest", type=Path, default=ROOT / "tests/ocrflow-golden/manifest.json")
    compare.add_argument("--runs", type=int, default=5)
    compare.add_argument("--output", type=Path, default=ROOT / ".artifacts/ocrflow-baseline/candidate.json")
    compare.add_argument("--gates", type=Path, default=DEFAULT_GATES)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        print(json.dumps({"status": "invalid_arguments", "message": "unable to parse benchmark arguments"}, ensure_ascii=False))
        return 2
    try:
        if args.command == "baseline":
            payload = build_baseline(args.manifest, args.runs)
            _write_json(args.output, payload)
            report = {"status": "baseline", "output": str(args.output), "caseCount": len(payload["cases"])}
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "archive":
            report = archive_baseline(args.input, args.store_root, args.ref, {
                "goldenManifestSha256": args.golden_manifest_sha,
                "environment": _environment_fingerprint(),
                "provider": {"name": "java-question-processing", "model": "deterministic", "version": "current"},
            })
            print(json.dumps({"status": "archived", **report}, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "restore":
            print(json.dumps(restore_baseline(args.ref, args.store_root, args.output), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "compare":
            if bool(args.baseline) != bool(args.candidate):
                raise BaselineValidationError("compare requires both --baseline and --candidate when either is supplied")
            if not args.baseline and not args.candidate:
                args.baseline = ROOT / ".artifacts/ocrflow-baseline/restored.json"
                args.candidate = args.output
                if not args.baseline.is_file():
                    raise BaselineValidationError(f"restored baseline does not exist: {args.baseline}")
                candidate_payload = build_baseline(args.manifest, args.runs)
                _write_json(args.candidate, candidate_payload)
            baseline_payload = _validate_artifact(_read_json(args.baseline), name="baseline")
            candidate_payload = _validate_artifact(_read_json(args.candidate), name="candidate")
            for field in ("mode", "goldenManifestSha256", "runsPerCase", "provider", "rssScope"):
                if baseline_payload.get(field) != candidate_payload.get(field):
                    raise BaselineValidationError(f"baseline and candidate {field} do not match")
            for field in ("python", "platform", "mode"):
                if baseline_payload["environment"].get(field) != candidate_payload["environment"].get(field):
                    raise BaselineValidationError(f"baseline and candidate environment {field} do not match")
            gates = _load_gates(args.gates)
            result = compare_payload_reports(baseline_payload, candidate_payload, gates)
            print(json.dumps({"status": "equal" if result["passed"] else "different", **result}, ensure_ascii=False, sort_keys=True))
            return 0 if result["passed"] else 1
        print(json.dumps({"status": "invalid_arguments", "message": "a command is required"}, ensure_ascii=False))
        return 2
    except (OSError, json.JSONDecodeError, BaselineValidationError, KeyError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "invalid", "message": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
