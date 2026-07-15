#!/usr/bin/env python3
"""Check whether the project can be moved to another machine cleanly."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from check_ocrflow_boundaries import check_boundaries
from package_question_engine_delivery import EXCLUDE_PARTS, ROOT, iter_files, validate


ABSOLUTE_LOCAL_PATH_RE = re.compile(
    "|".join(
        [
            r"/Users/[^\s`'\"<>]+",
            r"/home/[^\s`'\"<>]+",
            r"/var/folders/[^\s`'\"<>]+",
            r"/opt/homebrew/[^\s`'\"<>]+",
        ]
    )
)

ALLOWED_SHEBANG_PREFIXES = (
    "#!/usr/bin/env ",
    "#!/bin/sh",
    "#!/bin/bash",
    "#!/usr/bin/bash",
)

BINARY_PACKAGE_SUFFIXES = (".whl", ".zip", ".gz", ".tgz", ".bz2", ".xz")

ALLOWED_ABSOLUTE_LOCAL_PATH_PREFIXES = (
    "/home/user/AI_GENERATION_DOCKER",
)

ALLOWED_ABSOLUTE_LOCAL_PATH_FILES = {
    "README.md",
    "docker-compose.server.yml",
    "docs/CHANGELOG.md",
    "docs/delivery/OPERATIONS_GUIDE.md",
    "docs/server/CHANGELOG.md",
    "docs/server/README.md",
    "docs/server/RUNBOOK.md",
    "docs/superpowers/plans/2026-07-06-ocr-flow-llm-efficiency.md",
}

ABSOLUTE_PATH_PATTERN_SOURCE_FILES = {
    "scripts/check_project_portability.py",
}


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None
    except Exception:
        return None


def check_packaged_files(files: list[Path], failures: list[str]) -> None:
    failures.extend(validate(files))

    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        if path.suffix in BINARY_PACKAGE_SUFFIXES or path.name.endswith(".tar.gz"):
            continue
        text = read_text(path)
        if text is None:
            continue

        if rel not in ABSOLUTE_PATH_PATTERN_SOURCE_FILES:
            match = ABSOLUTE_LOCAL_PATH_RE.search(text)
            if match and not is_allowed_absolute_local_path(rel, match.group(0)):
                failures.append(f"absolute local path leaked into portable file: {rel}: {match.group(0)}")

        lines = text.splitlines()
        first_line = lines[0] if lines else ""
        if first_line.startswith("#!") and not first_line.startswith(ALLOWED_SHEBANG_PREFIXES):
            failures.append(f"non-portable shebang in packaged file: {rel}: {first_line}")


def is_allowed_absolute_local_path(relative_path: str, matched_path: str) -> bool:
    """Allow documented server deployment paths while still rejecting accidental local leaks."""
    return (
        relative_path in ALLOWED_ABSOLUTE_LOCAL_PATH_FILES
        and any(matched_path.startswith(prefix) for prefix in ALLOWED_ABSOLUTE_LOCAL_PATH_PREFIXES)
    )


def iter_source_tree_paths(root: Path = ROOT):
    """Yield source tree paths while pruning local dependency/build directories."""
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in EXCLUDE_PARTS]
        current_path = Path(current)
        for name in dirnames:
            yield current_path / name
        for name in filenames:
            yield current_path / name


def check_source_tree_symlinks(failures: list[str]) -> None:
    for path in iter_source_tree_paths(ROOT):
        if not path.is_symlink():
            continue
        if not path.exists():
            failures.append(f"broken symlink in portable source tree: {path.relative_to(ROOT).as_posix()} -> {os.readlink(path)}")


def check_local_install_state(failures: list[str]) -> None:
    venv = ROOT / "backend" / "python-worker" / ".venv"
    if venv.exists():
        python_bin = venv / "bin" / "python"
        if not python_bin.exists():
            failures.append("backend/python-worker/.venv exists but bin/python is missing; run ./scripts/install_backend.sh")
        else:
            result = subprocess.run([str(python_bin), "--version"], capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                failures.append("backend/python-worker/.venv exists but bin/python cannot run; run ./scripts/install_backend.sh")
        for script_name in ("uvicorn", "mineru", "mineru-api"):
            script = venv / "bin" / script_name
            if not script.exists():
                continue
            lines = read_text(script)
            first_line = lines.splitlines()[0] if lines else ""
            if first_line.startswith("#!"):
                interpreter = first_line[2:].split(" ", 1)[0]
                if interpreter != "/usr/bin/env" and not Path(interpreter).exists():
                    failures.append(
                        f"backend/python-worker/.venv/bin/{script_name} points to missing interpreter {interpreter}; "
                        "run ./scripts/install_backend.sh or ./scripts/install_mineru.sh"
                    )

    package_json = ROOT / "local-platform" / "package.json"
    node_modules = ROOT / "local-platform" / "node_modules"
    if package_json.exists() and not node_modules.exists():
        failures.append("local-platform/package.json exists but node_modules is missing; run ./scripts/install_frontend.sh")


def check_architecture_boundaries(failures: list[str]) -> None:
    failures.extend(check_boundaries(ROOT))


def main() -> int:
    failures: list[str] = []
    check_packaged_files(iter_files(include_local_platform=False), failures)
    check_packaged_files(iter_files(include_local_platform=True), failures)
    check_packaged_files(iter_files(include_local_platform=True, include_mineru_wheelhouse=True), failures)
    check_source_tree_symlinks(failures)
    check_local_install_state(failures)
    check_architecture_boundaries(failures)

    if failures:
        for failure in failures:
            print(failure)
        return 1

    print("project portability check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
