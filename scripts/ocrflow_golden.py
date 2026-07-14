#!/usr/bin/env python3
"""Capture and compare deterministic OCR Flow golden payloads."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
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


def _path_matches(pattern: str, path: str) -> bool:
    escaped = re.escape(pattern)
    escaped = escaped.replace(r"\[\*\]", r"\[\d+\]")
    escaped = escaped.replace(r"\[\]", r"\[\d+\]")
    return re.fullmatch(escaped, path) is not None


def _is_random_id_path(path: str, patterns: Sequence[str]) -> bool:
    return any(_path_matches(pattern, path) for pattern in patterns)


def compare_payloads(
    expected: Any,
    actual: Any,
    random_id_paths: Sequence[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return exact recursive differences after narrowly scoped normalization."""
    differences: dict[str, dict[str, Any]] = {}
    patterns = tuple(random_id_paths or ())

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


def _repository_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _resolve_manifest_path(manifest_path: Path, value: str) -> Path:
    supplied = Path(value)
    if supplied.is_absolute():
        return supplied
    repository = _repository_root(manifest_path.resolve().parent)
    if repository is not None and (repository / supplied).exists():
        return repository / supplied
    return manifest_path.resolve().parent / supplied


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
        for field in ("paper", "expected", "providerOutput"):
            value = case.get(field)
            if not isinstance(value, str) or not value:
                errors.append(f"{prefix}.{field} is required")
            elif not _resolve_manifest_path(path, value).is_file():
                errors.append(f"{prefix}.{field} does not exist: {value}")
        answer = case.get("answer")
        if answer is not None and (
            not isinstance(answer, str) or not _resolve_manifest_path(path, answer).is_file()
        ):
            errors.append(f"{prefix}.answer does not exist: {answer}")
        expected = case.get("expected")
        provider_output = case.get("providerOutput")
        if isinstance(expected, str) and isinstance(provider_output, str):
            if _resolve_manifest_path(path, expected).resolve() == _resolve_manifest_path(
                path, provider_output
            ).resolve():
                errors.append(f"{prefix}.providerOutput must not be the expected file")
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
    """Validate an externally mounted controlled corpus without reading its content."""
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


def _compare_manifest(path: Path, release: bool) -> tuple[int, dict[str, Any]]:
    controlled = _controlled_status(release)
    if controlled.get("valid") is False:
        return 2, {"status": "controlled_corpus_invalid", "controlledCorpus": controlled}
    manifest, errors = _load_manifest(path)
    if errors or manifest is None:
        return 2, {"status": "manifest_invalid", "errors": errors, "controlledCorpus": controlled}
    random_paths = manifest.get("randomIdPaths", [])
    case_reports: list[dict[str, Any]] = []
    difference_count = 0
    for case in manifest["cases"]:
        try:
            expected = _read_json(_resolve_manifest_path(path, case["expected"]))
        except (OSError, json.JSONDecodeError) as exc:
            return 2, {
                "status": "expected_invalid",
                "caseId": case["id"],
                "message": str(exc),
                "controlledCorpus": controlled,
            }
        try:
            actual = _read_json(_resolve_manifest_path(path, case["providerOutput"]))
        except (OSError, json.JSONDecodeError) as exc:
            return 2, {
                "status": "replay_invalid",
                "caseId": case["id"],
                "message": str(exc),
                "controlledCorpus": controlled,
            }
        differences = compare_payloads(expected, actual, random_paths)
        difference_count += len(differences)
        case_reports.append({
            "id": case["id"],
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
    random_paths = manifest.get("randomIdPaths", [])
    cases = []
    for case in manifest["cases"]:
        try:
            replay = _read_json(_resolve_manifest_path(path, case["providerOutput"]))
        except (OSError, json.JSONDecodeError) as exc:
            return 2, {
                "status": "replay_invalid",
                "caseId": case["id"],
                "message": str(exc),
                "controlledCorpus": controlled,
            }
        cases.append({"id": case["id"], "payload": _normalize_payload(replay, random_paths)})
    captured = {
        "schemaVersion": "ocrflow-golden-capture.v1",
        "mode": "replay",
        "normalization": {
            "temporalFields": sorted(TEMPORAL_FIELDS),
            "randomIdPaths": list(random_paths),
        },
        "cases": cases,
    }
    _write_json(output, captured)
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
