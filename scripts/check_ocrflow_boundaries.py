#!/usr/bin/env python3
"""Reject new dependencies that cross OCR Flow module boundaries."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
BASELINE_CONFIG_ENV = "OCRFLOW_BOUNDARY_BASELINE_CONFIG"
BASELINE_REF_ENV = "OCRFLOW_BOUNDARY_BASELINE_REF"

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
REVIEW_CORE_DOM_GLOBALS = ("document", "window")
REVIEW_CORE_DOM_TYPE_RE = re.compile(
    r"\b(?:HTML[A-Za-z0-9]*Element|SVG[A-Za-z0-9]*Element|Document|Window|DOMParser|NodeList(?:Of)?|EventTarget|CSSStyleDeclaration)\b"
)
REVIEW_CORE_COMPUTED_GLOBAL_RE = re.compile(
    r"\b(globalThis|window)\s*\[\s*(['\"])(document|window)\2\s*\]"
)
REVIEW_CORE_JSX_RE = re.compile(r"(?:</?[A-Za-z][A-Za-z0-9_.:-]*(?:\s|/?>)|<>|</>)")
TEMPLATE_EXPRESSION_RE = re.compile(r"\$\{(.*?)\}", re.DOTALL)
WORKER_NON_ALGORITHM_DIRECTORIES = {"routes", "runtime", "contracts", "legacy"}
WORKER_NON_ALGORITHM_FILES = {
    "__init__.py",
    "main.py",
    "worker_routes.py",
    "worker_base.py",
    "import_services.py",
    "export_service.py",
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
        value = _static_python_string(node)
        if value is not None:
            self.values.append(value)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        value = _static_python_string(node)
        if value is not None:
            self.values.append(value)
        else:
            self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        value = _static_python_string(node)
        if value is not None:
            self.values.append(value)
        else:
            self.generic_visit(node)


def _static_python_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                parts.append("{" + ast.unparse(value.value) + "}")
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_python_string(node.left)
        right = _static_python_string(node.right)
        return left + right if left is not None and right is not None else None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        template = _static_python_string(node.func.value)
        if template is None:
            return None
        try:
            args = [ast.literal_eval(argument) for argument in node.args]
            kwargs = {keyword.arg: ast.literal_eval(keyword.value) for keyword in node.keywords if keyword.arg}
            if len(kwargs) != len(node.keywords):
                return None
            return template.format(*args, **kwargs)
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            return None
    return None


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


def _normalized_api_suffix(value: str, prefixes: tuple[str, ...] | None = None) -> str | None:
    candidates = prefixes or ("/api/",)
    matches = [value.find(prefix) for prefix in candidates]
    indexes = [index for index in matches if index >= 0]
    if not indexes:
        return None
    return value[min(indexes) :]


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
            pattern = _normalized_api_suffix(value, PYTHON_WORKER_API_PREFIXES)
            if pattern is not None:
                _record(violations, "python-worker-business-api", relative_path, pattern)


JAVA_STRING_RE = re.compile(r'"((?:\\.|[^"\\])*)"')
JAVA_STATIC_CONCAT_RE = re.compile(r'"(?:\\.|[^"\\])*"(?:\s*\+\s*"(?:\\.|[^"\\])*")+')


def _java_string_value(raw_value: str) -> str:
    try:
        return json.loads(f'"{raw_value}"')
    except json.JSONDecodeError:
        return raw_value


def _java_static_strings(source: str) -> Iterable[str]:
    concatenated_spans: list[tuple[int, int]] = []
    for concat_match in JAVA_STATIC_CONCAT_RE.finditer(source):
        concatenated_spans.append(concat_match.span())
        yield "".join(_java_string_value(match.group(1)) for match in JAVA_STRING_RE.finditer(concat_match.group(0)))
    for match in JAVA_STRING_RE.finditer(source):
        if any(start <= match.start() and match.end() <= end for start, end in concatenated_spans):
            continue
        yield _java_string_value(match.group(1))


def _is_java_worker_transport_context(relative_path: str, source: str) -> bool:
    if "/ocrflow/adapter/worker/" in f"/{relative_path}":
        return True
    filename = Path(relative_path).stem
    if "/ocrflow/adapter/" in f"/{relative_path}" and re.search(r"worker|client|transport", filename, re.IGNORECASE):
        return True
    return bool(
        re.search(r"PythonWorker|pythonWorker", source)
        and re.search(r"HttpClient|WebClient|RestClient|URI|URL", source)
    )


def _discover_java_ocrflow_apis(root: Path, violations: Counter[tuple[str, str, str]], failures: list[str]) -> None:
    for relative_path, path in _relative_files(root, "backend/src/main/java", {".java"}):
        if "/ocrflow/" not in f"/{relative_path}":
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            failures.append(f"boundary scan could not read {relative_path}: {exc}")
            continue
        if not _is_java_worker_transport_context(relative_path, source):
            continue
        for value in _java_static_strings(source):
            pattern = _normalized_api_suffix(value)
            if pattern is not None:
                _record(violations, "java-ocrflow-python-api", relative_path, pattern)


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
        for match in REVIEW_CORE_COMPUTED_GLOBAL_RE.finditer(source):
            pattern = f'DOM global: {match.group(1)}["{match.group(3)}"]'
            _record(violations, "review-core-ui-dependency", relative_path, pattern)
        template_expressions = TEMPLATE_EXPRESSION_RE.findall(source)
        source_without_literals = JS_STRING_RE.sub("", JS_COMMENT_RE.sub("", source))
        dom_source = source_without_literals + "\n" + "\n".join(template_expressions)
        for identifier in REVIEW_CORE_DOM_GLOBALS:
            count = len(re.findall(rf"\b{re.escape(identifier)}\b", dom_source))
            if count:
                violations[("review-core-ui-dependency", relative_path, f"DOM global: {identifier}")] += count
        for match in REVIEW_CORE_DOM_TYPE_RE.finditer(dom_source):
            _record(violations, "review-core-ui-dependency", relative_path, f"DOM type: {match.group(0)}")
        if path.suffix in {".tsx", ".jsx"}:
            jsx_count = len(REVIEW_CORE_JSX_RE.findall(source_without_literals))
            if jsx_count:
                violations[("review-core-ui-dependency", relative_path, "JSX syntax")] += jsx_count


def _is_worker_algorithm_path(relative_path: str) -> bool:
    prefix = "backend/python-worker/app/"
    if not relative_path.startswith(prefix):
        return False
    nested_path = relative_path[len(prefix) :]
    first_part = nested_path.split("/", 1)[0]
    if first_part in WORKER_NON_ALGORITHM_DIRECTORIES:
        return False
    return nested_path not in WORKER_NON_ALGORITHM_FILES


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
        elif isinstance(node, ast.Call) and node.args:
            function_name = ""
            if isinstance(node.func, ast.Name):
                function_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                function_name = node.func.attr
            if function_name not in {"import_module", "__import__"}:
                continue
            imported = _static_python_string(node.args[0])
            if imported and "legacy" in imported.lstrip(".").split("."):
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


def _load_allowlist_payload(payload: object, source: str) -> tuple[list[dict], list[str]]:
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return [], [f"{source} must be an object with version 1"]
    allowlist = payload.get("allowlist")
    if not isinstance(allowlist, list):
        return [], [f"{source} allowlist must be an array"]
    failures: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for index, entry in enumerate(allowlist):
        entry_failures = _validate_entry(entry, f"{source} allowlist", index)
        failures.extend(entry_failures)
        if entry_failures:
            continue
        key = _entry_key(entry)
        if key in seen:
            failures.append(f"{source} allowlist[{index}] duplicates {key}")
        seen.add(key)
    return allowlist, failures


def _load_allowlist_file(config_path: Path, source: str) -> tuple[list[dict], list[str]]:
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [], [f"{source} could not be loaded from {config_path}: {exc}"]
    return _load_allowlist_payload(payload, source)


def _git_baseline_payload(root: Path, baseline_ref: str | None) -> tuple[object | None, str, list[str]]:
    config_relative_path = "config/ocrflow-boundaries.json"
    if baseline_ref:
        ref = baseline_ref
        source = f"protected baseline at git ref {ref}"
    else:
        result = subprocess.run(
            ["git", "-C", str(root), "log", "--follow", "--diff-filter=A", "--format=%H", "--", config_relative_path],
            capture_output=True,
            text=True,
        )
        commits = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if result.returncode != 0 or not commits:
            detail = result.stderr.strip() or "config has no introduction commit"
            return None, "protected baseline", [detail]
        ref = commits[-1]
        source = f"protected baseline from config introduction commit {ref}"
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{ref}:{config_relative_path}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None, source, [result.stderr.strip() or f"git ref {ref} does not contain {config_relative_path}"]
    try:
        return json.loads(result.stdout), source, []
    except json.JSONDecodeError as exc:
        return None, source, [f"invalid JSON: {exc}"]


def _load_protected_baseline(
    root: Path,
    current_config_path: Path,
    baseline_config_path: Path | None,
    baseline_ref: str | None,
    environment: Mapping[str, str],
) -> tuple[list[dict], list[str]]:
    configured_path = baseline_config_path or (
        Path(environment[BASELINE_CONFIG_ENV]) if environment.get(BASELINE_CONFIG_ENV) else None
    )
    if configured_path is not None:
        configured_path = configured_path.expanduser().resolve()
        if configured_path == current_config_path.resolve():
            return [], ["protected baseline must be independent from the current boundary config"]
        return _load_allowlist_file(configured_path, "protected baseline")

    selected_ref = baseline_ref or environment.get(BASELINE_REF_ENV)
    payload, source, git_failures = _git_baseline_payload(root, selected_ref)
    if git_failures:
        guidance = (
            "protected baseline unavailable: "
            + "; ".join(git_failures)
            + f". Bootstrap with --baseline-config PATH or {BASELINE_CONFIG_ENV}=PATH; "
            "the baseline must be an independently protected read-only file"
        )
        return [], [guidance]
    return _load_allowlist_payload(payload, source)


def _validate_allowlist_growth(baseline: list[dict], current: list[dict]) -> list[str]:
    baseline_counts = {_entry_key(entry): entry["count"] for entry in baseline}
    failures: list[str] = []
    for entry in current:
        key = _entry_key(entry)
        if key not in baseline_counts:
            failures.append(f"boundary allowlist entry is not present in protected baseline: {key}")
        elif entry["count"] > baseline_counts[key]:
            failures.append(
                f"boundary allowlist count exceeds protected baseline for {key}: "
                f"{entry['count']} > {baseline_counts[key]}"
            )
    return failures


def check_boundaries(
    root: Path = ROOT,
    config_path: Path | None = None,
    *,
    baseline_config_path: Path | None = None,
    baseline_ref: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> list[str]:
    root = Path(root).resolve()
    config_path = Path(config_path) if config_path is not None else root / "config" / "ocrflow-boundaries.json"
    current, config_failures = _load_allowlist_file(config_path, "boundary config")
    if config_failures:
        return config_failures
    baseline, baseline_failures = _load_protected_baseline(
        root,
        config_path,
        baseline_config_path,
        baseline_ref,
        os.environ if environment is None else environment,
    )
    if baseline_failures:
        return baseline_failures
    growth_failures = _validate_allowlist_growth(baseline, current)
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
    parser.add_argument("--baseline-config", type=Path, help=f"protected read-only baseline (or set {BASELINE_CONFIG_ENV})")
    parser.add_argument("--baseline-ref", help=f"git ref containing the protected baseline (or set {BASELINE_REF_ENV})")
    args = parser.parse_args(argv)
    failures = check_boundaries(
        args.root,
        args.config,
        baseline_config_path=args.baseline_config,
        baseline_ref=args.baseline_ref,
    )
    if failures:
        for failure in failures:
            print(failure)
        return 1
    print("OCR Flow boundary check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
