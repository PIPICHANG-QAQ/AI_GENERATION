#!/usr/bin/env python3
"""Capture and compare deterministic OCR Flow golden payloads."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from typing import Any, Sequence


TEMPORAL_FIELDS = {
    "createdAt",
    "updatedAt",
    "startedAt",
    "finishedAt",
    "traceId",
}
REQUIRED_CONTROLLED_FEATURES = {
    "option-images",
    "cross-page-options",
    "composite-questions",
    "child-question-images",
    "answer-duplicate-questions",
    "tables",
    "two-column",
    "formula",
    "header-noise",
}
REPLAY_RUNNER = "java-question-processing"
TOOL_ROOT = Path(__file__).resolve().parents[1]
BUILTIN_MANIFEST = Path("tests/ocrflow-golden/manifest.json")
DEFAULT_RUNNER_TIMEOUT_SECONDS = 120.0
MAX_RUNNER_TIMEOUT_SECONDS = 3600.0
RANDOM_ID_PATH_PATTERN = re.compile(
    r"[A-Za-z_][A-Za-z0-9_-]*(?:\[(?:\*|[0-9]+)\])*"
    r"(?:\.[A-Za-z_][A-Za-z0-9_-]*(?:\[(?:\*|[0-9]+)\])*)*"
)


class ReplayRunnerTimeout(RuntimeError):
    """Raised when the deterministic Java replay exceeds its configured deadline."""


def _path_matches(pattern: str, path: str) -> bool:
    escaped = re.escape(pattern)
    escaped = escaped.replace(r"\[\*\]", r"\[\d+\]")
    escaped = escaped.replace(r"\[\]", r"\[\d+\]")
    return re.fullmatch(escaped, path) is not None


def _is_random_id_path(path: str, patterns: Sequence[str]) -> bool:
    return any(_path_matches(pattern, path) for pattern in patterns)


def _validate_random_id_path_syntax(pattern: Any) -> str | None:
    if not isinstance(pattern, str) or not pattern.strip():
        return "random ID path must be a non-empty string"
    if pattern == "$":
        return "random ID path must not select the root"
    if RANDOM_ID_PATH_PATTERN.fullmatch(pattern) is None:
        return f"invalid random ID path syntax: {pattern}"
    if re.search(r"\[(?:\*|[0-9]+)\]$", pattern):
        return f"random ID path must select a scalar field, not an array item: {pattern}"
    return None


def _path_tokens(pattern: str) -> list[str | int]:
    tokens: list[str | int] = []
    for field, index in re.findall(r"([A-Za-z_][A-Za-z0-9_-]*)|\[(\*|[0-9]+)\]", pattern):
        if field:
            tokens.append(field)
        elif index == "*":
            tokens.append("*")
        else:
            tokens.append(int(index))
    return tokens


def _validate_random_id_leaf_paths(payload: Any, patterns: Sequence[str]) -> None:
    for pattern in patterns:
        syntax_error = _validate_random_id_path_syntax(pattern)
        if syntax_error:
            raise ValueError(syntax_error)
        values = [payload]
        for token in _path_tokens(pattern):
            next_values: list[Any] = []
            for value in values:
                if isinstance(token, str) and token != "*" and isinstance(value, dict):
                    if token in value:
                        next_values.append(value[token])
                elif token == "*" and isinstance(value, list):
                    next_values.extend(value)
                elif isinstance(token, int) and isinstance(value, list) and token < len(value):
                    next_values.append(value[token])
            values = next_values
        if not values:
            raise ValueError(f"random ID path does not resolve to a value: {pattern}")
        if any(isinstance(value, (dict, list)) for value in values):
            raise ValueError(f"random ID path must resolve only to scalar leaves: {pattern}")


def compare_payloads(
    expected: Any,
    actual: Any,
    random_id_paths: Sequence[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return exact recursive differences after narrowly scoped normalization."""
    differences: dict[str, dict[str, Any]] = {}
    patterns = tuple(random_id_paths or ())
    _validate_random_id_leaf_paths(expected, patterns)
    _validate_random_id_leaf_paths(actual, patterns)

    def add(path: str, kind: str, left: Any, right: Any) -> None:
        differences[path or "$[root]"] = {
            "kind": kind,
            "expected": left,
            "actual": right,
        }

    def visit(left: Any, right: Any, path: str, field_name: str | None = None) -> None:
        if field_name in TEMPORAL_FIELDS or _is_random_id_path(path, patterns):
            return
        if type(left) is not type(right):
            add(path, "type", left, right)
            return
        if isinstance(left, dict):
            for key in left.keys() - right.keys():
                child = f"{path}.{key}" if path else str(key)
                add(child, "missing", left[key], None)
            for key in right.keys() - left.keys():
                child = f"{path}.{key}" if path else str(key)
                add(child, "unexpected", None, right[key])
            for key in left.keys() & right.keys():
                child = f"{path}.{key}" if path else str(key)
                visit(left[key], right[key], child, str(key))
            return
        if isinstance(left, list):
            shared = min(len(left), len(right))
            for index in range(shared):
                visit(left[index], right[index], f"{path}[{index}]")
            for index in range(shared, len(left)):
                add(f"{path}[{index}]", "missing", left[index], None)
            for index in range(shared, len(right)):
                add(f"{path}[{index}]", "unexpected", None, right[index])
            return
        if left != right:
            add(path, "value", left, right)

    visit(expected, actual, "")
    return differences


def _normalize_payload(payload: Any, random_id_paths: Sequence[str]) -> Any:
    _validate_random_id_leaf_paths(payload, random_id_paths)
    normalized = copy.deepcopy(payload)

    def visit(value: Any, path: str, field_name: str | None = None) -> None:
        if field_name in TEMPORAL_FIELDS or _is_random_id_path(path, random_id_paths):
            return
        if isinstance(value, dict):
            for key in list(value):
                child = f"{path}.{key}" if path else str(key)
                if key in TEMPORAL_FIELDS or _is_random_id_path(child, random_id_paths):
                    value[key] = "<normalized>"
                else:
                    visit(value[key], child, str(key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                child = f"{path}[{index}]"
                if _is_random_id_path(child, random_id_paths):
                    value[index] = "<normalized>"
                else:
                    visit(item, child)

    visit(normalized, "")
    return normalized


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _resolve_manifest_path(manifest_path: Path, value: str) -> Path:
    supplied = Path(value)
    if supplied.is_absolute():
        return supplied
    builtin_path = (TOOL_ROOT / BUILTIN_MANIFEST).resolve()
    base = TOOL_ROOT if manifest_path.resolve() == builtin_path else manifest_path.resolve().parent
    return base / supplied


def _load_manifest(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    try:
        manifest = _read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"cannot read manifest {path}: {exc}"]
    if not isinstance(manifest, dict):
        return None, ["manifest root must be an object"]
    if manifest.get("schemaVersion") != "ocrflow-golden.v1":
        errors.append("manifest schemaVersion must be ocrflow-golden.v1")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append("manifest cases must be a non-empty array")
        cases = []
    random_paths = manifest.get("randomIdPaths", [])
    if not isinstance(random_paths, list) or not all(isinstance(item, str) for item in random_paths):
        errors.append("manifest randomIdPaths must be an array of strings")
        random_paths = []
    for random_path in random_paths:
        syntax_error = _validate_random_id_path_syntax(random_path)
        if syntax_error:
            errors.append(f"manifest randomIdPaths: {syntax_error}")
    ids: set[str] = set()
    for index, case in enumerate(cases):
        prefix = f"cases[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{prefix} must be an object")
            continue
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id:
            errors.append(f"{prefix}.id must be a non-empty string")
        elif case_id in ids:
            errors.append(f"duplicate case id: {case_id}")
        else:
            ids.add(case_id)
        for field in ("paper", "expected", "replayInput"):
            value = case.get(field)
            if not isinstance(value, str) or not value:
                errors.append(f"{prefix}.{field} is required")
            elif not _resolve_manifest_path(path, value).is_file():
                errors.append(f"{prefix}.{field} does not exist: {value}")
        if case.get("runner") != REPLAY_RUNNER:
            errors.append(f"{prefix}.runner must be {REPLAY_RUNNER}")
        answer = case.get("answer")
        if answer is not None and (
            not isinstance(answer, str) or not _resolve_manifest_path(path, answer).is_file()
        ):
            errors.append(f"{prefix}.answer does not exist: {answer}")
        expected = case.get("expected")
        replay_input = case.get("replayInput")
        if isinstance(expected, str) and isinstance(replay_input, str):
            expected_path = _resolve_manifest_path(path, expected)
            replay_path = _resolve_manifest_path(path, replay_input)
            if expected_path.resolve() == replay_path.resolve():
                errors.append(f"{prefix}.replayInput must not be the expected file")
            elif expected_path.is_file() and replay_path.is_file():
                if _sha256(expected_path) == _sha256(replay_path):
                    errors.append(f"{prefix}.replayInput and expected must not have the same SHA-256")
            if expected_path.is_file():
                try:
                    expected_payload = _read_json(expected_path)
                except json.JSONDecodeError:
                    pass
                else:
                    try:
                        _validate_random_id_leaf_paths(expected_payload, random_paths)
                    except ValueError as exc:
                        errors.append(f"{prefix}.randomIdPaths: {exc}")
    return manifest, errors


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_controlled_corpus(
    root: str | Path | None,
    *,
    release: bool,
) -> dict[str, Any]:
    """Validate structure, metadata, normalization paths, and hashes for a controlled corpus."""
    if root is None or not Path(root).is_dir():
        if not release:
            raise unittest.SkipTest("OCRFLOW_GOLDEN_ROOT is not configured; controlled corpus skipped")
        return {
            "valid": False,
            "caseCount": 0,
            "errors": ["OCRFLOW_GOLDEN_ROOT is required for release validation"],
        }

    corpus_root = Path(root)
    case_directories = sorted(path for path in corpus_root.iterdir() if path.is_dir())
    errors: list[str] = []
    features: set[str] = set()
    if len(case_directories) < 20:
        errors.append(f"controlled corpus must contain at least 20 cases; found {len(case_directories)}")

    for case_directory in case_directories:
        case_file = case_directory / "case.json"
        paper_directory = case_directory / "paper"
        answer_directory = case_directory / "answer"
        provider_directory = case_directory / "provider-output"
        expected_file = case_directory / "expected" / "question-package.json"
        prefix = case_directory.name
        for directory_name, directory, optional in (
            ("paper", paper_directory, False),
            ("answer", answer_directory, True),
            ("provider-output", provider_directory, False),
        ):
            if optional and not directory.exists():
                continue
            if not directory.is_dir() or not any(path.is_file() for path in directory.rglob("*")):
                errors.append(f"{prefix}/{directory_name} must be a non-empty directory")
        if not expected_file.is_file():
            errors.append(f"{prefix}/expected/question-package.json is required")
        try:
            metadata = _read_json(case_file)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{prefix}/case.json is invalid: {exc}")
            continue
        if not isinstance(metadata, dict):
            errors.append(f"{prefix}/case.json must be an object")
            continue
        if metadata.get("schemaVersion") != "ocrflow-controlled-case.v1":
            errors.append(f"{prefix}/case.json has unsupported schemaVersion")
        if metadata.get("id") != prefix:
            errors.append(f"{prefix}/case.json id must equal directory name")
        if metadata.get("runner") != REPLAY_RUNNER:
            errors.append(f"{prefix}/case.json runner must be {REPLAY_RUNNER}")
        replay_input = metadata.get("replayInput")
        if not isinstance(replay_input, str) or not replay_input:
            errors.append(f"{prefix}/case.json replayInput is required")
        else:
            replay_relative = Path(replay_input)
            replay_file = case_directory / replay_relative
            if replay_relative.is_absolute() or ".." in replay_relative.parts:
                errors.append(f"{prefix}/case.json replayInput must be a safe relative path")
            elif not replay_input.startswith("provider-output/") or not replay_file.is_file():
                errors.append(
                    f"{prefix}/case.json replayInput must select a file under provider-output/"
                )
            elif expected_file.is_file() and _sha256(replay_file) == _sha256(expected_file):
                errors.append(f"{prefix} replayInput and expected must not have the same SHA-256")
        random_paths = metadata.get("randomIdPaths", [])
        if not isinstance(random_paths, list) or not all(
            isinstance(item, str) for item in random_paths
        ):
            errors.append(f"{prefix}/case.json randomIdPaths must be an array of strings")
        else:
            for random_path in random_paths:
                syntax_error = _validate_random_id_path_syntax(random_path)
                if syntax_error:
                    errors.append(f"{prefix}/case.json randomIdPaths: {syntax_error}")
            if expected_file.is_file():
                try:
                    expected_payload = _read_json(expected_file)
                except json.JSONDecodeError:
                    pass
                else:
                    try:
                        _validate_random_id_leaf_paths(expected_payload, random_paths)
                    except ValueError as exc:
                        errors.append(f"{prefix}/case.json randomIdPaths: {exc}")
        case_features = metadata.get("features", [])
        if not isinstance(case_features, list) or not all(isinstance(item, str) for item in case_features):
            errors.append(f"{prefix}/case.json features must be an array of strings")
        else:
            features.update(case_features)
        declared_hashes = metadata.get("sha256")
        if not isinstance(declared_hashes, dict) or not all(
            isinstance(path, str) and isinstance(digest, str)
            for path, digest in (declared_hashes.items() if isinstance(declared_hashes, dict) else [])
        ):
            errors.append(f"{prefix}/case.json sha256 must map relative paths to digests")
            continue
        actual_files = {
            path.relative_to(case_directory).as_posix(): path
            for path in case_directory.rglob("*")
            if path.is_file() and path != case_file
        }
        if set(declared_hashes) != set(actual_files):
            missing = sorted(set(actual_files) - set(declared_hashes))
            extra = sorted(set(declared_hashes) - set(actual_files))
            errors.append(
                f"{prefix}/case.json SHA-256 file list mismatch; missing={missing}, extra={extra}"
            )
        for relative_path in sorted(set(declared_hashes) & set(actual_files)):
            if not re.fullmatch(r"[0-9a-f]{64}", declared_hashes[relative_path]):
                errors.append(f"{prefix}/{relative_path} has invalid SHA-256 digest")
            elif _sha256(actual_files[relative_path]) != declared_hashes[relative_path]:
                errors.append(f"{prefix}/{relative_path} SHA-256 mismatch")

    missing_features = sorted(REQUIRED_CONTROLLED_FEATURES - features)
    if missing_features:
        errors.append(f"controlled corpus is missing required features: {missing_features}")
    return {
        "valid": not errors,
        "caseCount": len(case_directories),
        "features": sorted(features),
        "errors": errors,
    }


def _controlled_status(release: bool) -> dict[str, Any]:
    root = os.environ.get("OCRFLOW_GOLDEN_ROOT")
    try:
        return validate_controlled_corpus(root, release=release)
    except unittest.SkipTest as exc:
        return {"valid": None, "skipped": True, "reason": str(exc)}


def _manifest_case_descriptors(path: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    random_paths = manifest.get("randomIdPaths", [])
    return [
        {
            "id": case["id"],
            "scope": "manifest",
            "runner": case["runner"],
            "input": _resolve_manifest_path(path, case["replayInput"]),
            "expected": _resolve_manifest_path(path, case["expected"]),
            "randomIdPaths": random_paths,
        }
        for case in manifest["cases"]
    ]


def _controlled_case_descriptors(root: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for case_directory in sorted(path for path in root.iterdir() if path.is_dir()):
        metadata = _read_json(case_directory / "case.json")
        cases.append({
            "id": metadata["id"],
            "scope": "controlled",
            "runner": metadata["runner"],
            "input": case_directory / metadata["replayInput"],
            "expected": case_directory / "expected" / "question-package.json",
            "randomIdPaths": metadata.get("randomIdPaths", []),
        })
    return cases


def _case_descriptors(path: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    cases = _manifest_case_descriptors(path, manifest)
    controlled_root = os.environ.get("OCRFLOW_GOLDEN_ROOT")
    if controlled_root:
        cases.extend(_controlled_case_descriptors(Path(controlled_root)))
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("manifest and controlled corpus case ids must be unique")
    return cases


def _runner_timeout_seconds() -> float:
    raw = os.environ.get(
        "OCRFLOW_GOLDEN_RUNNER_TIMEOUT_SECONDS",
        str(DEFAULT_RUNNER_TIMEOUT_SECONDS),
    )
    try:
        timeout = float(raw)
    except ValueError as exc:
        raise RuntimeError(
            "OCRFLOW_GOLDEN_RUNNER_TIMEOUT_SECONDS must be a number"
        ) from exc
    if not math.isfinite(timeout) or timeout <= 0 or timeout > MAX_RUNNER_TIMEOUT_SECONDS:
        raise RuntimeError(
            "OCRFLOW_GOLDEN_RUNNER_TIMEOUT_SECONDS must be greater than 0 "
            f"and at most {MAX_RUNNER_TIMEOUT_SECONDS:g}"
        )
    return timeout


def _run_replay_cases(cases: Sequence[dict[str, Any]]) -> dict[str, Any]:
    repository = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="ocrflow-replay-") as directory:
        temporary = Path(directory)
        request_cases = []
        outputs: dict[str, Path] = {}
        for index, case in enumerate(cases):
            output = temporary / "candidates" / f"{index:04d}.json"
            outputs[case["id"]] = output
            request_cases.append({
                "id": case["id"],
                "input": str(Path(case["input"]).resolve()),
                "output": str(output.resolve()),
            })
        request_path = temporary / "request.json"
        _write_json(request_path, {
            "schemaVersion": "ocrflow-replay-request.v1",
            "cases": request_cases,
        })
        command = [
            "mvn",
            "-q",
            "-f",
            str(repository / "backend" / "pom.xml"),
            "-Dtest=OcrFlowReplayRunnerTest",
            f"-Docrflow.replay.request={request_path}",
            "test",
        ]
        timeout = _runner_timeout_seconds()
        try:
            completed = subprocess.run(
                command,
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise ReplayRunnerTimeout(
                f"{REPLAY_RUNNER} exceeded {timeout:g} seconds"
            ) from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(
                f"{REPLAY_RUNNER} exited {completed.returncode}: {detail[-4000:]}"
            )
        candidates: dict[str, Any] = {}
        for case_id, output in outputs.items():
            if not output.is_file():
                raise RuntimeError(f"{REPLAY_RUNNER} did not produce candidate for {case_id}")
            try:
                candidates[case_id] = _read_json(output)
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    f"{REPLAY_RUNNER} produced invalid candidate for {case_id}: {exc}"
                ) from exc
        return candidates


def _preflight_replay_inputs(cases: Sequence[dict[str, Any]]) -> tuple[str, str] | None:
    for case in cases:
        try:
            _read_json(Path(case["input"]))
        except (OSError, json.JSONDecodeError) as exc:
            return case["id"], str(exc)
    return None


def _compare_manifest(path: Path, release: bool) -> tuple[int, dict[str, Any]]:
    controlled = _controlled_status(release)
    if controlled.get("valid") is False:
        return 2, {"status": "controlled_corpus_invalid", "controlledCorpus": controlled}
    manifest, errors = _load_manifest(path)
    if errors or manifest is None:
        return 2, {"status": "manifest_invalid", "errors": errors, "controlledCorpus": controlled}
    try:
        cases = _case_descriptors(path, manifest)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return 2, {
            "status": "case_configuration_invalid",
            "message": str(exc),
            "controlledCorpus": controlled,
        }
    replay_error = _preflight_replay_inputs(cases)
    if replay_error:
        return 2, {
            "status": "replay_invalid",
            "caseId": replay_error[0],
            "message": replay_error[1],
            "controlledCorpus": controlled,
        }
    try:
        candidates = _run_replay_cases(cases)
    except ReplayRunnerTimeout as exc:
        return 2, {
            "status": "runner_timeout",
            "runner": REPLAY_RUNNER,
            "message": str(exc),
            "controlledCorpus": controlled,
        }
    except Exception as exc:
        return 2, {
            "status": "runner_failed",
            "runner": REPLAY_RUNNER,
            "message": str(exc),
            "controlledCorpus": controlled,
        }
    case_reports: list[dict[str, Any]] = []
    difference_count = 0
    for case in cases:
        try:
            expected = _read_json(Path(case["expected"]))
        except (OSError, json.JSONDecodeError) as exc:
            return 2, {
                "status": "expected_invalid",
                "caseId": case["id"],
                "message": str(exc),
                "controlledCorpus": controlled,
            }
        try:
            if case["id"] not in candidates:
                raise KeyError(f"candidate is missing for {case['id']}")
            differences = compare_payloads(
                expected,
                candidates[case["id"]],
                case["randomIdPaths"],
            )
        except KeyError as exc:
            return 2, {
                "status": "candidate_invalid",
                "caseId": case["id"],
                "message": str(exc),
                "controlledCorpus": controlled,
            }
        except ValueError as exc:
            return 2, {
                "status": "normalization_invalid",
                "caseId": case["id"],
                "message": str(exc),
                "controlledCorpus": controlled,
            }
        difference_count += len(differences)
        case_reports.append({
            "id": case["id"],
            "scope": case["scope"],
            "status": "equal" if not differences else "different",
            "differences": differences,
        })
    status = "equal" if difference_count == 0 else "different"
    return (0 if difference_count == 0 else 1), {
        "status": status,
        "mode": "manifest-replay",
        "differenceCount": difference_count,
        "cases": case_reports,
        "controlledCorpus": controlled,
    }


def _capture_manifest(path: Path, output: Path, release: bool) -> tuple[int, dict[str, Any]]:
    controlled = _controlled_status(release)
    if controlled.get("valid") is False:
        return 2, {"status": "controlled_corpus_invalid", "controlledCorpus": controlled}
    manifest, errors = _load_manifest(path)
    if errors or manifest is None:
        return 2, {"status": "manifest_invalid", "errors": errors, "controlledCorpus": controlled}
    try:
        descriptors = _case_descriptors(path, manifest)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return 2, {
            "status": "case_configuration_invalid",
            "message": str(exc),
            "controlledCorpus": controlled,
        }
    replay_error = _preflight_replay_inputs(descriptors)
    if replay_error:
        return 2, {
            "status": "replay_invalid",
            "caseId": replay_error[0],
            "message": replay_error[1],
            "controlledCorpus": controlled,
        }
    try:
        candidates = _run_replay_cases(descriptors)
    except ReplayRunnerTimeout as exc:
        return 2, {
            "status": "runner_timeout",
            "runner": REPLAY_RUNNER,
            "message": str(exc),
            "controlledCorpus": controlled,
        }
    except Exception as exc:
        return 2, {
            "status": "runner_failed",
            "runner": REPLAY_RUNNER,
            "message": str(exc),
            "controlledCorpus": controlled,
        }

    if release:
        release_reports = []
        difference_count = 0
        for case in descriptors:
            try:
                expected = _read_json(Path(case["expected"]))
            except (OSError, json.JSONDecodeError) as exc:
                return 2, {
                    "status": "expected_invalid",
                    "caseId": case["id"],
                    "message": str(exc),
                    "controlledCorpus": controlled,
                }
            if case["id"] not in candidates:
                return 2, {
                    "status": "candidate_invalid",
                    "caseId": case["id"],
                    "message": f"candidate is missing for {case['id']}",
                    "controlledCorpus": controlled,
                }
            try:
                differences = compare_payloads(
                    expected,
                    candidates[case["id"]],
                    case["randomIdPaths"],
                )
            except ValueError as exc:
                return 2, {
                    "status": "normalization_invalid",
                    "caseId": case["id"],
                    "message": str(exc),
                    "controlledCorpus": controlled,
                }
            difference_count += len(differences)
            release_reports.append({
                "id": case["id"],
                "scope": case["scope"],
                "status": "equal" if not differences else "different",
                "differences": differences,
            })
        if difference_count:
            return 1, {
                "status": "different",
                "mode": "release-capture-gate",
                "differenceCount": difference_count,
                "cases": release_reports,
                "controlledCorpus": controlled,
            }

    cases = []
    for case in descriptors:
        if case["id"] not in candidates:
            return 2, {
                "status": "candidate_invalid",
                "caseId": case["id"],
                "message": f"candidate is missing for {case['id']}",
                "controlledCorpus": controlled,
            }
        try:
            payload = _normalize_payload(candidates[case["id"]], case["randomIdPaths"])
        except ValueError as exc:
            return 2, {
                "status": "normalization_invalid",
                "caseId": case["id"],
                "message": str(exc),
                "controlledCorpus": controlled,
            }
        cases.append({
            "id": case["id"],
            "scope": case["scope"],
            "payload": payload,
        })

    captured = {
        "schemaVersion": "ocrflow-golden-capture.v1",
        "mode": "replay",
        "normalization": {
            "temporalFields": sorted(TEMPORAL_FIELDS),
            "randomIdPaths": list(manifest.get("randomIdPaths", [])),
        },
        "cases": cases,
    }
    try:
        _write_json(output, captured)
    except OSError as exc:
        return 2, {
            "status": "output_write_failed",
            "output": str(output),
            "message": str(exc),
            "controlledCorpus": controlled,
        }
    return 0, {
        "status": "captured",
        "mode": "replay",
        "caseCount": len(cases),
        "output": str(output),
        "controlledCorpus": controlled,
    }


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    compare = subparsers.add_parser("compare")
    compare.add_argument("--manifest")
    compare.add_argument("--baseline")
    compare.add_argument("--candidate")
    compare.add_argument("--release", action="store_true")
    capture = subparsers.add_parser("capture")
    capture.add_argument("--manifest")
    capture.add_argument("--mode")
    capture.add_argument("--output")
    capture.add_argument("--release", action="store_true")
    return parser


def _invalid_arguments(message: str) -> int:
    print(json.dumps({"status": "invalid_arguments", "message": message}, ensure_ascii=False))
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _argument_parser().parse_args(argv)
    except SystemExit:
        return _invalid_arguments("unable to parse arguments")
    if args.command == "compare":
        manifest_mode = bool(args.manifest)
        pair_mode = bool(args.baseline or args.candidate)
        if manifest_mode == pair_mode:
            return _invalid_arguments(
                "use either --manifest or the --baseline/--candidate pair"
            )
        if pair_mode and not (args.baseline and args.candidate):
            return _invalid_arguments("--baseline and --candidate are both required")
        if pair_mode and args.release:
            return _invalid_arguments("--release is only valid with --manifest")
        if manifest_mode:
            code, report = _compare_manifest(Path(args.manifest), args.release)
        else:
            try:
                baseline = _read_json(Path(args.baseline))
                candidate = _read_json(Path(args.candidate))
            except (OSError, json.JSONDecodeError) as exc:
                print(json.dumps({"status": "input_invalid", "message": str(exc)}, ensure_ascii=False))
                return 2
            differences = compare_payloads(baseline, candidate)
            code = 0 if not differences else 1
            report = {
                "status": "equal" if not differences else "different",
                "mode": "captured-pair",
                "differenceCount": len(differences),
                "differences": differences,
            }
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return code
    if args.command == "capture":
        if not args.manifest or not args.output or args.mode != "replay":
            return _invalid_arguments(
                "capture requires --manifest, --mode replay, and --output"
            )
        code, report = _capture_manifest(Path(args.manifest), Path(args.output), args.release)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return code
    return _invalid_arguments("a command is required")


if __name__ == "__main__":
    sys.exit(main())
