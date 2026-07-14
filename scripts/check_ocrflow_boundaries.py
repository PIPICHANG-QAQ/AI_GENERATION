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
    def __init__(self, constants: Mapping[str, str] | None = None) -> None:
        self.values: list[str] = []
        self.constants = dict(constants or {})

    def _append_static_value(self, node: ast.AST) -> bool:
        raw_value = _static_python_string(node, {})
        value = _static_python_string(node, self.constants)
        if value is None:
            return False
        if raw_value is not None and _normalized_api_suffix(raw_value, PYTHON_WORKER_API_PREFIXES) is not None:
            self.values.append(raw_value)
        else:
            self.values.append(value)
        return True

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            self.values.append(node.value)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self._append_static_value(node)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        self._append_static_value(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if not self._append_static_value(node):
            self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if not self._append_static_value(node):
            self.generic_visit(node)

def _static_python_string(node: ast.AST, constants: Mapping[str, str] | None = None) -> str | None:
    if isinstance(node, ast.Name) and constants is not None:
        return constants.get(node.id)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                resolved = _static_python_string(value.value, constants)
                parts.append(resolved if resolved is not None else "{" + ast.unparse(value.value) + "}")
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_python_string(node.left, constants)
        right = _static_python_string(node.right, constants)
        return left + right if left is not None and right is not None else None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        template = _static_python_string(node.func.value, constants)
        if template is None:
            return None
        try:
            args = [_static_python_format_value(argument, constants) for argument in node.args]
            kwargs = {
                keyword.arg: _static_python_format_value(keyword.value, constants)
                for keyword in node.keywords
                if keyword.arg
            }
            if len(kwargs) != len(node.keywords):
                return None
            return template.format(*args, **kwargs)
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            return None
    return None


def _static_python_format_value(node: ast.AST, constants: Mapping[str, str] | None) -> object:
    resolved = _static_python_string(node, constants)
    return resolved if resolved is not None else ast.literal_eval(node)


class _PythonLegacyCallCollector(ast.NodeVisitor):
    def __init__(self, constants: Mapping[str, str], import_module_names: set[str]) -> None:
        self.patterns: list[str] = []
        self.constants = constants
        self.import_module_names = import_module_names

    def visit_Call(self, node: ast.Call) -> None:
        is_dynamic_import = False
        if isinstance(node.func, ast.Name):
            is_dynamic_import = node.func.id == "__import__" or node.func.id in self.import_module_names
        elif isinstance(node.func, ast.Attribute):
            is_dynamic_import = node.func.attr == "import_module"
        if is_dynamic_import and node.args:
            imported = _static_python_string(node.args[0], self.constants)
            if imported and "legacy" in imported.lstrip(".").split("."):
                self.patterns.append(imported)
        self.generic_visit(node)


class _PythonAssignedNameCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.names.add(alias.asname or alias.name.split(".", 1)[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self.names.add(alias.asname or alias.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return


def _python_assigned_names(node: ast.AST) -> set[str]:
    collector = _PythonAssignedNameCollector()
    collector.visit(node)
    return collector.names


def _python_target_names(target: ast.AST) -> set[str]:
    return _python_assigned_names(target)


class _PythonScopeScanner:
    """Track only deterministic string assignments within one lexical scope."""

    _CONTROL_FLOW_TYPES = (
        ast.If,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.Try,
        ast.With,
        ast.AsyncWith,
        ast.Match,
    ) + ((ast.TryStar,) if hasattr(ast, "TryStar") else ())

    def __init__(self) -> None:
        self.string_values: list[str] = []
        self.legacy_imports: list[str] = []

    def scan(self, tree: ast.AST) -> None:
        if isinstance(tree, ast.Module):
            self._scan_statements(tree.body, {}, {"import_module"})

    def _scan_expression(
        self,
        node: ast.AST | None,
        constants: Mapping[str, str],
        import_module_names: set[str],
    ) -> None:
        if node is None:
            return
        string_collector = _PythonStringCollector(constants)
        string_collector.visit(node)
        self.string_values.extend(string_collector.values)
        legacy_collector = _PythonLegacyCallCollector(constants, import_module_names)
        legacy_collector.visit(node)
        self.legacy_imports.extend(legacy_collector.patterns)

    def _scan_statements(
        self,
        statements: list[ast.stmt],
        constants: dict[str, str],
        import_module_names: set[str],
    ) -> None:
        for statement in statements:
            self._scan_statement(statement, constants, import_module_names)

    def _update_assignment(
        self,
        targets: list[ast.AST],
        value_node: ast.AST,
        constants: dict[str, str],
        import_module_names: set[str],
    ) -> None:
        self._scan_expression(value_node, constants, import_module_names)
        value = _static_python_string(value_node, constants)
        names: set[str] = set()
        simple_targets = True
        for target in targets:
            target_names = _python_target_names(target)
            names.update(target_names)
            simple_targets = simple_targets and isinstance(target, ast.Name)
        for name in names:
            import_module_names.discard(name)
            if value is not None and simple_targets:
                constants[name] = value
            else:
                constants.pop(name, None)

    def _scan_function(
        self,
        statement: ast.FunctionDef | ast.AsyncFunctionDef,
        constants: dict[str, str],
        import_module_names: set[str],
    ) -> None:
        for expression in [*statement.decorator_list, *statement.args.defaults, *statement.args.kw_defaults]:
            self._scan_expression(expression, constants, import_module_names)
        if statement.returns is not None:
            self._scan_expression(statement.returns, constants, import_module_names)
        local_constants = dict(constants)
        local_import_names = set(import_module_names)
        arguments = [
            *statement.args.posonlyargs,
            *statement.args.args,
            *statement.args.kwonlyargs,
        ]
        if statement.args.vararg is not None:
            arguments.append(statement.args.vararg)
        if statement.args.kwarg is not None:
            arguments.append(statement.args.kwarg)
        for argument in arguments:
            local_constants.pop(argument.arg, None)
            local_import_names.discard(argument.arg)
        self._scan_statements(statement.body, local_constants, local_import_names)
        constants.pop(statement.name, None)
        import_module_names.discard(statement.name)

    def _scan_control_flow(
        self,
        statement: ast.stmt,
        constants: dict[str, str],
        import_module_names: set[str],
    ) -> None:
        if isinstance(statement, (ast.If, ast.While)):
            self._scan_expression(statement.test, constants, import_module_names)
        elif isinstance(statement, (ast.For, ast.AsyncFor)):
            self._scan_expression(statement.iter, constants, import_module_names)
        elif isinstance(statement, (ast.With, ast.AsyncWith)):
            for item in statement.items:
                self._scan_expression(item.context_expr, constants, import_module_names)
        elif isinstance(statement, ast.Match):
            self._scan_expression(statement.subject, constants, import_module_names)

        changed_names = _python_assigned_names(statement)
        branch_constants = dict(constants)
        branch_import_names = set(import_module_names)

        blocks = [
            getattr(statement, field)
            for field in ("orelse", "finalbody")
            if getattr(statement, field, None)
        ]
        if isinstance(statement, (ast.For, ast.AsyncFor)):
            target_names = _python_target_names(statement.target)
            elements = statement.iter.elts if isinstance(statement.iter, (ast.List, ast.Tuple)) else None
            values = (
                [_static_python_string(element, constants) for element in elements]
                if elements is not None
                else None
            )
            if isinstance(statement.target, ast.Name) and values is not None and all(value is not None for value in values):
                for value in values:
                    loop_constants = dict(branch_constants)
                    loop_constants[statement.target.id] = value
                    loop_import_names = set(branch_import_names)
                    loop_import_names.discard(statement.target.id)
                    self._scan_statements(statement.body, loop_constants, loop_import_names)
            else:
                loop_constants = dict(branch_constants)
                loop_import_names = set(branch_import_names)
                for name in target_names:
                    loop_constants.pop(name, None)
                    loop_import_names.discard(name)
                self._scan_statements(statement.body, loop_constants, loop_import_names)
        elif getattr(statement, "body", None):
            blocks.insert(0, statement.body)
        for handler in getattr(statement, "handlers", []):
            self._scan_expression(handler.type, branch_constants, branch_import_names)
            blocks.append(handler.body)
        for case in getattr(statement, "cases", []):
            self._scan_expression(case.pattern, branch_constants, branch_import_names)
            self._scan_expression(case.guard, branch_constants, branch_import_names)
            blocks.append(case.body)
        for block in blocks:
            self._scan_statements(block, dict(branch_constants), set(branch_import_names))

        for name in changed_names:
            constants.pop(name, None)
            import_module_names.discard(name)

    def _scan_statement(
        self,
        statement: ast.stmt,
        constants: dict[str, str],
        import_module_names: set[str],
    ) -> None:
        if isinstance(statement, ast.Assign):
            self._update_assignment(statement.targets, statement.value, constants, import_module_names)
        elif isinstance(statement, ast.AnnAssign):
            if statement.value is not None:
                self._update_assignment([statement.target], statement.value, constants, import_module_names)
            else:
                for name in _python_target_names(statement.target):
                    constants.pop(name, None)
                    import_module_names.discard(name)
        elif isinstance(statement, (ast.AugAssign, ast.Delete)):
            self._scan_expression(getattr(statement, "value", None), constants, import_module_names)
            for name in _python_assigned_names(statement):
                constants.pop(name, None)
                import_module_names.discard(name)
        elif isinstance(statement, ast.Import):
            for alias in statement.names:
                if "legacy" in alias.name.split("."):
                    self.legacy_imports.append(alias.name)
                assigned = alias.asname or alias.name.split(".", 1)[0]
                constants.pop(assigned, None)
                import_module_names.discard(assigned)
        elif isinstance(statement, ast.ImportFrom):
            module = "." * statement.level + (statement.module or "")
            for alias in statement.names:
                imported = f"{module}.{alias.name}" if module else alias.name
                if "legacy" in imported.lstrip(".").split("."):
                    self.legacy_imports.append(imported)
                assigned = alias.asname or alias.name
                constants.pop(assigned, None)
                import_module_names.discard(assigned)
                if statement.module == "importlib" and alias.name == "import_module":
                    import_module_names.add(assigned)
        elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._scan_function(statement, constants, import_module_names)
        elif isinstance(statement, ast.ClassDef):
            for expression in [*statement.decorator_list, *statement.bases, *[keyword.value for keyword in statement.keywords]]:
                self._scan_expression(expression, constants, import_module_names)
            self._scan_statements(statement.body, dict(constants), set(import_module_names))
            constants.pop(statement.name, None)
            import_module_names.discard(statement.name)
        elif isinstance(statement, self._CONTROL_FLOW_TYPES):
            self._scan_control_flow(statement, constants, import_module_names)
        else:
            self._scan_expression(statement, constants, import_module_names)


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
        scanner = _PythonScopeScanner()
        scanner.scan(tree)
        for value in scanner.string_values:
            pattern = _normalized_api_suffix(value, PYTHON_WORKER_API_PREFIXES)
            if pattern is not None:
                _record(violations, "python-worker-business-api", relative_path, pattern)


JAVA_STRING_RE = re.compile(r'"((?:\\.|[^"\\])*)"')
JAVA_STATIC_CONCAT_RE = re.compile(r'"(?:\\.|[^"\\])*"(?:\s*\+\s*"(?:\\.|[^"\\])*")+')
JAVA_STRING_SOURCE = r'"(?:\\.|[^"\\])*"'
JAVA_IDENTIFIER_SOURCE = r"[A-Za-z_$][A-Za-z0-9_$]*"
JAVA_STATIC_TOKEN_SOURCE = rf"(?:{JAVA_STRING_SOURCE}|{JAVA_IDENTIFIER_SOURCE})"
JAVA_STATIC_TOKEN_RE = re.compile(JAVA_STATIC_TOKEN_SOURCE)
JAVA_STATIC_EXPRESSION_RE = re.compile(rf"\s*{JAVA_STATIC_TOKEN_SOURCE}(?:\s*\+\s*{JAVA_STATIC_TOKEN_SOURCE})*\s*\Z")
JAVA_FINAL_STRING_DECLARATION_RE = re.compile(
    rf"\b(?:(?:public|protected|private)\s+)?(?:static\s+)?final\s+String\s+"
    rf"({JAVA_IDENTIFIER_SOURCE})\s*=\s*([^;]+);"
)
JAVA_SEGMENT_CALL_SOURCE = (
    rf'\.(?:resolve|path|pathSegment|segment)\(\s*({JAVA_STATIC_TOKEN_SOURCE}'
    rf'(?:\s*,\s*{JAVA_STATIC_TOKEN_SOURCE})*)\s*\)'
)
JAVA_SEGMENT_CALL_RE = re.compile(JAVA_SEGMENT_CALL_SOURCE)
JAVA_SEGMENT_CHAIN_RE = re.compile(rf'(?:{JAVA_SEGMENT_CALL_SOURCE}\s*)+')


def _java_string_value(raw_value: str) -> str:
    try:
        return json.loads(f'"{raw_value}"')
    except json.JSONDecodeError:
        return raw_value


def _java_static_value(expression: str, constants: Mapping[str, str]) -> str | None:
    if JAVA_STATIC_EXPRESSION_RE.fullmatch(expression) is None:
        return None
    values: list[str] = []
    for match in JAVA_STATIC_TOKEN_RE.finditer(expression):
        token = match.group(0)
        if token.startswith('"'):
            string_match = JAVA_STRING_RE.fullmatch(token)
            if string_match is None:
                return None
            values.append(_java_string_value(string_match.group(1)))
        elif token in constants:
            values.append(constants[token])
        else:
            return None
    return "".join(values)


def _java_string_constants(source: str) -> dict[str, str]:
    declarations = [
        (name, expression)
        for name, expression in JAVA_FINAL_STRING_DECLARATION_RE.findall(source)
        if len(re.findall(rf"\b{re.escape(name)}\s*=(?!=)", source)) == 1
    ]
    constants: dict[str, str] = {}
    for _ in range(len(declarations)):
        changed = False
        for name, expression in declarations:
            if name in constants:
                continue
            value = _java_static_value(expression, constants)
            if value is not None:
                constants[name] = value
                changed = True
        if not changed:
            break
    return constants


def _java_static_strings(source: str) -> Iterable[str]:
    concatenated_spans: list[tuple[int, int]] = []
    for concat_match in JAVA_STATIC_CONCAT_RE.finditer(source):
        concatenated_spans.append(concat_match.span())
        yield "".join(_java_string_value(match.group(1)) for match in JAVA_STRING_RE.finditer(concat_match.group(0)))
    for match in JAVA_STRING_RE.finditer(source):
        if any(start <= match.start() and match.end() <= end for start, end in concatenated_spans):
            continue
        yield _java_string_value(match.group(1))


def _java_segmented_api_paths(source: str, constants: Mapping[str, str]) -> Iterable[str]:
    for chain_match in JAVA_SEGMENT_CHAIN_RE.finditer(source):
        values: list[str] = []
        unresolved = False
        for call_match in JAVA_SEGMENT_CALL_RE.finditer(chain_match.group(0)):
            for token_match in JAVA_STATIC_TOKEN_RE.finditer(call_match.group(1)):
                value = _java_static_value(token_match.group(0), constants)
                if value is None:
                    unresolved = True
                    break
                values.append(value)
            if unresolved:
                break
        if unresolved:
            compact_chain = re.sub(r"\s+", " ", chain_match.group(0)).strip()
            yield f"dynamic URI chain: {compact_chain}"
            continue
        if any(_normalized_api_suffix(value) is not None for value in values):
            continue
        path = "/" + "/".join(value.strip("/") for value in values if value.strip("/"))
        if path.startswith("/api/"):
            yield path


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
        constants = _java_string_constants(source)
        for value in _java_static_strings(source):
            pattern = _normalized_api_suffix(value)
            if pattern is not None:
                _record(violations, "java-ocrflow-python-api", relative_path, pattern)
        for pattern in _java_segmented_api_paths(source, constants):
            _record(violations, "java-ocrflow-python-api", relative_path, pattern)


JS_IMPORT_RES = (
    re.compile(r"\bfrom\s*['\"]([^'\"]+)['\"]"),
    re.compile(r"\bimport\s*['\"]([^'\"]+)['\"]"),
    re.compile(r"\b(?:import|require)\s*\(\s*['\"]([^'\"]+)['\"]\s*\)"),
)


def _strip_js_literals_and_comments(source: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(source):
        character = source[index]
        if character in {"'", '"', "`"}:
            quote = character
            index += 1
            while index < len(source):
                if source[index] == "\\":
                    index += 2
                    continue
                if source[index] == quote:
                    index += 1
                    break
                if source[index] == "\n":
                    output.append("\n")
                index += 1
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index + 2)
            if newline < 0:
                break
            output.append("\n")
            index = newline + 1
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            comment_end = len(source) if end < 0 else end + 2
            output.extend("\n" for character in source[index:comment_end] if character == "\n")
            index = comment_end
            continue
        output.append(character)
        index += 1
    return "".join(output)


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
        source_without_literals = _strip_js_literals_and_comments(source)
        dom_source = source_without_literals + "\n" + "\n".join(
            _strip_js_literals_and_comments(expression) for expression in template_expressions
        )
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
    scanner = _PythonScopeScanner()
    scanner.scan(tree)
    yield from scanner.legacy_imports


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
    if not selected_ref:
        shallow_result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-shallow-repository"],
            capture_output=True,
            text=True,
        )
        if shallow_result.returncode == 0 and shallow_result.stdout.strip() == "true":
            return [], [
                "protected baseline unavailable: shallow repository history cannot establish the config introduction "
                f"commit. Supply --baseline-config PATH, {BASELINE_CONFIG_ENV}=PATH, --baseline-ref REF, or "
                f"{BASELINE_REF_ENV}=REF"
            ]
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
