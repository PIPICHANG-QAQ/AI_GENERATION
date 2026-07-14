#!/usr/bin/env python3
"""Reject new dependencies that cross OCR Flow module boundaries."""

from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "ocrflow-boundaries.json"

PYTHON_WORKER_API_PREFIXES = (
    "/api/import-tasks",
    "/api/question-bank",
    "/api/papers",
    "/api/knowledge-points",
    "/api/ocr",
    "/api/markdown",
    "/api/ai",
)
REVIEW_CORE_SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".mjs", ".cjs"}
REVIEW_CORE_FORBIDDEN_MODULES = ("react", "react-dom")
REVIEW_CORE_DOM_IDENTIFIERS = ("document", "window", "HTMLElement", "Document", "DOMParser")
WORKER_ALGORITHM_DIRECTORIES = ("ocr", "ai", "standardization", "canonicalization")
WORKER_ALGORITHM_FILES = {
    "choice_layout_assignment.py",
    "image_placement.py",
    "image_placement_multimodal.py",
    "llm_splitter.py",
    "math_normalizer.py",
    "ocr_execution.py",
    "ocr_flow.py",
    "ocr_processing.py",
    "question_boundary.py",
    "question_canonicalization.py",
    "question_layout.py",
    "question_markdown.py",
    "visual_repair.py",
}
RULES = {
    "python-worker-business-api",
    "java-ocrflow-python-api",
    "review-core-ui-dependency",
    "worker-algorithm-legacy-import",
}
ENTRY_KEYS = ("rule", "path", "pattern")


class _PythonStringCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.values: list[str] = []

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            self.values.append(node.value)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                parts.append("{" + ast.unparse(value.value) + "}")
        self.values.append("".join(parts))


def _relative_files(root: Path, directory: str, suffixes: set[str]) -> Iterable[tuple[str, Path]]:
    source_root = root / directory
    if not source_root.is_dir():
        return
    for path in sorted(source_root.rglob("*")):
        if path.is_file() and path.suffix in suffixes:
            yield path.relative_to(root).as_posix(), path


def _python_tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _record(counter: Counter[tuple[str, str, str]], rule: str, relative_path: str, pattern: str) -> None:
    counter[(rule, relative_path, pattern)] += 1


def _discover_python_worker_apis(root: Path, violations: Counter[tuple[str, str, str]], failures: list[str]) -> None:
    for relative_path, path in _relative_files(root, "backend/python-worker/app", {".py"}):
        try:
            tree = _python_tree(path)
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            failures.append(f"boundary scan could not parse {relative_path}: {exc}")
            continue
        collector = _PythonStringCollector()
        collector.visit(tree)
        for value in collector.values:
            if value.startswith(PYTHON_WORKER_API_PREFIXES):
                _record(violations, "python-worker-business-api", relative_path, value)


JAVA_STRING_RE = re.compile(r'"((?:\\.|[^"\\])*)"')


def _discover_java_ocrflow_apis(root: Path, violations: Counter[tuple[str, str, str]], failures: list[str]) -> None:
    for relative_path, path in _relative_files(root, "backend/src/main/java", {".java"}):
        if "/ocrflow/" not in f"/{relative_path}":
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            failures.append(f"boundary scan could not read {relative_path}: {exc}")
            continue
        for match in JAVA_STRING_RE.finditer(source):
            value = match.group(1)
            if value.startswith("/api/"):
                _record(violations, "java-ocrflow-python-api", relative_path, value)


JS_IMPORT_RES = (
    re.compile(r"\bfrom\s*['\"]([^'\"]+)['\"]"),
    re.compile(r"\bimport\s*['\"]([^'\"]+)['\"]"),
    re.compile(r"\b(?:import|require)\s*\(\s*['\"]([^'\"]+)['\"]\s*\)"),
)
JS_COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)
JS_STRING_RE = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`", re.DOTALL)


def _is_forbidden_review_module(module: str) -> bool:
    return any(module == forbidden or module.startswith(forbidden + "/") for forbidden in REVIEW_CORE_FORBIDDEN_MODULES)


def _discover_review_core_dependencies(
    root: Path, violations: Counter[tuple[str, str, str]], failures: list[str]
) -> None:
    for relative_path, path in _relative_files(root, "question-engine/review-core", REVIEW_CORE_SOURCE_SUFFIXES):
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            failures.append(f"boundary scan could not read {relative_path}: {exc}")
            continue
        for import_re in JS_IMPORT_RES:
            for match in import_re.finditer(source):
                module = match.group(1)
                if _is_forbidden_review_module(module):
                    _record(violations, "review-core-ui-dependency", relative_path, module)
        source_without_literals = JS_STRING_RE.sub("", JS_COMMENT_RE.sub("", source))
        for identifier in REVIEW_CORE_DOM_IDENTIFIERS:
            count = len(re.findall(rf"\b{re.escape(identifier)}\b", source_without_literals))
            if count:
                violations[("review-core-ui-dependency", relative_path, f"DOM global: {identifier}")] += count


def _is_worker_algorithm_path(relative_path: str) -> bool:
    prefix = "backend/python-worker/app/"
    if not relative_path.startswith(prefix):
        return False
    nested_path = relative_path[len(prefix) :]
    first_part = nested_path.split("/", 1)[0]
    return first_part in WORKER_ALGORITHM_DIRECTORIES or nested_path in WORKER_ALGORITHM_FILES


def _legacy_import_patterns(tree: ast.AST) -> Iterable[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "legacy" in alias.name.split("."):
                    yield alias.name
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            for alias in node.names:
                imported = f"{module}.{alias.name}" if module else alias.name
                if "legacy" in imported.lstrip(".").split("."):
                    yield imported


def _discover_worker_legacy_imports(
    root: Path, violations: Counter[tuple[str, str, str]], failures: list[str]
) -> None:
    for relative_path, path in _relative_files(root, "backend/python-worker/app", {".py"}):
        if not _is_worker_algorithm_path(relative_path):
            continue
        try:
            tree = _python_tree(path)
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            failures.append(f"boundary scan could not parse {relative_path}: {exc}")
            continue
        for pattern in _legacy_import_patterns(tree):
            _record(violations, "worker-algorithm-legacy-import", relative_path, pattern)


def discover_violations(root: Path) -> tuple[Counter[tuple[str, str, str]], list[str]]:
    violations: Counter[tuple[str, str, str]] = Counter()
    failures: list[str] = []
    _discover_python_worker_apis(root, violations, failures)
    _discover_java_ocrflow_apis(root, violations, failures)
    _discover_review_core_dependencies(root, violations, failures)
    _discover_worker_legacy_imports(root, violations, failures)
    return violations, failures


def _entry_key(entry: dict) -> tuple[str, str, str]:
    return tuple(entry[key] for key in ENTRY_KEYS)  # type: ignore[return-value]


def _is_exact_scanned_file(rule: str, path: str) -> bool:
    if rule == "python-worker-business-api":
        return path.startswith("backend/python-worker/app/") and path.endswith(".py")
    if rule == "java-ocrflow-python-api":
        return path.startswith("backend/src/main/java/") and "/ocrflow/" in path and path.endswith(".java")
    if rule == "review-core-ui-dependency":
        return path.startswith("question-engine/review-core/") and Path(path).suffix in REVIEW_CORE_SOURCE_SUFFIXES
    if rule == "worker-algorithm-legacy-import":
        return path.endswith(".py") and _is_worker_algorithm_path(path)
    return False


def _validate_entry(entry: object, section: str, index: int) -> list[str]:
    location = f"{section}[{index}]"
    if not isinstance(entry, dict):
        return [f"boundary config {location} must be an object"]
    failures: list[str] = []
    for key in (*ENTRY_KEYS, "count"):
        if key not in entry:
            failures.append(f"boundary config {location} is missing {key}")
    if failures:
        return failures
    rule = entry["rule"]
    path = entry["path"]
    pattern = entry["pattern"]
    count = entry["count"]
    if rule not in RULES:
        failures.append(f"boundary config {location} has unknown rule {rule!r}")
    if not isinstance(path, str) or not path or path.startswith("/") or ".." in Path(path).parts:
        failures.append(f"boundary config {location} path must be a repo-relative file")
    elif any(character in path for character in "*?[]"):
        failures.append(f"boundary config {location} path must name one exact file, not a glob or directory ignore")
    elif isinstance(rule, str) and not _is_exact_scanned_file(rule, path):
        failures.append(f"boundary config {location} path must name one exact file scanned by rule {rule!r}")
    if not isinstance(pattern, str) or not pattern:
        failures.append(f"boundary config {location} pattern must be one exact non-empty scanned value")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        failures.append(f"boundary config {location} count must be a positive integer")
    return failures


def _load_config(config_path: Path) -> tuple[list[dict], list[dict], list[str]]:
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [], [], [f"boundary config could not be loaded from {config_path}: {exc}"]
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return [], [], ["boundary config must be an object with version 1"]
    frozen = payload.get("frozenAllowlist")
    current = payload.get("allowlist")
    if not isinstance(frozen, list) or not isinstance(current, list):
        return [], [], ["boundary config frozenAllowlist and allowlist must be arrays"]
    failures: list[str] = []
    for section, entries in (("frozenAllowlist", frozen), ("allowlist", current)):
        seen: set[tuple[str, str, str]] = set()
        for index, entry in enumerate(entries):
            entry_failures = _validate_entry(entry, section, index)
            failures.extend(entry_failures)
            if entry_failures:
                continue
            key = _entry_key(entry)
            if key in seen:
                failures.append(f"boundary config {section}[{index}] duplicates {key}")
            seen.add(key)
    return frozen, current, failures


def _validate_allowlist_growth(frozen: list[dict], current: list[dict]) -> list[str]:
    frozen_counts = {_entry_key(entry): entry["count"] for entry in frozen}
    failures: list[str] = []
    for entry in current:
        key = _entry_key(entry)
        if key not in frozen_counts:
            failures.append(f"boundary allowlist entry is not present in frozen allowlist: {key}")
        elif entry["count"] > frozen_counts[key]:
            failures.append(
                f"boundary allowlist count exceeds frozen allowlist for {key}: "
                f"{entry['count']} > {frozen_counts[key]}"
            )
    return failures


def check_boundaries(root: Path = ROOT, config_path: Path | None = None) -> list[str]:
    root = Path(root).resolve()
    config_path = Path(config_path) if config_path is not None else root / "config" / "ocrflow-boundaries.json"
    frozen, current, config_failures = _load_config(config_path)
    if config_failures:
        return config_failures
    growth_failures = _validate_allowlist_growth(frozen, current)
    violations, scan_failures = discover_violations(root)
    failures = growth_failures + scan_failures
    allowed_counts = {_entry_key(entry): entry["count"] for entry in current}
    for key, actual_count in sorted(violations.items()):
        if key not in allowed_counts:
            failures.append(f"boundary violation: unallowlisted {key[0]}: {key[1]}: {key[2]} (found {actual_count})")
    for key, expected_count in sorted(allowed_counts.items()):
        actual_count = violations.get(key, 0)
        if actual_count != expected_count:
            failures.append(
                f"boundary violation: {key[0]}: {key[1]}: {key[2]}: "
                f"expected {expected_count} occurrence(s), found {actual_count}"
            )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root to scan")
    parser.add_argument("--config", type=Path, help="boundary config; defaults to <root>/config/ocrflow-boundaries.json")
    args = parser.parse_args(argv)
    failures = check_boundaries(args.root, args.config)
    if failures:
        for failure in failures:
            print(failure)
        return 1
    print("OCR Flow boundary check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
