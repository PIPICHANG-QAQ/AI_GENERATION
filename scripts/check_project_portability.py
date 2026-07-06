#!/usr/bin/env python3
"""Check whether the project can be moved to another machine cleanly."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from package_question_engine_delivery import EXCLUDE_PARTS, ROOT, iter_files, validate


ABSOLUTE_LOCAL_PATH_RE = re.compile(
    "|".join(
        [
            "/" + r"Users/[^\\s`'\"<>]+",
            "/" + r"home/[^\\s`'\"<>]+",
            "/" + r"var/folders/[^\\s`'\"<>]+",
            "/" + r"opt/homebrew/[^\\s`'\"<>]+",
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

        match = ABSOLUTE_LOCAL_PATH_RE.search(text)
        if match:
            failures.append(f"absolute local path leaked into portable file: {rel}: {match.group(0)}")

        lines = text.splitlines()
        first_line = lines[0] if lines else ""
        if first_line.startswith("#!") and not first_line.startswith(ALLOWED_SHEBANG_PREFIXES):
            failures.append(f"non-portable shebang in packaged file: {rel}: {first_line}")


def check_source_tree_symlinks(failures: list[str]) -> None:
    for path in ROOT.rglob("*"):
        relative_parts = path.relative_to(ROOT).parts
        if set(relative_parts) & EXCLUDE_PARTS:
            continue
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


def main() -> int:
    failures: list[str] = []
    check_packaged_files(iter_files(include_local_platform=False), failures)
    check_packaged_files(iter_files(include_local_platform=True), failures)
    check_packaged_files(iter_files(include_local_platform=True, include_mineru_wheelhouse=True), failures)
    check_source_tree_symlinks(failures)
    check_local_install_state(failures)

    if failures:
        for failure in failures:
            print(failure)
        return 1

    print("project portability check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
