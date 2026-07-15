#!/usr/bin/env python3
"""Build, validate, and atomically activate a server MinerU virtualenv."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
from typing import Callable


GIB = 1024**3
RUNTIME_IMPORT_PROBE = "\n".join(
    (
        "from markupsafe import Markup",
        "from jinja2 import Environment",
        "import transformers",
        "from mineru.cli.common import read_fn",
        "assert Markup and Environment and transformers and read_fn",
    )
)
ACTIVATION_FILE_NAMES = (
    "activate",
    "activate.csh",
    "activate.fish",
    "Activate.ps1",
    "activate.ps1",
    "activate.bat",
    "activate.nu",
    "activate.xsh",
    "activate_this.py",
)
MINERU_VERSION_LINE = re.compile(
    r"^\s*mineru\s*,\s*version\s+(\S+)\s*$",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class BuildPaths:
    active: Path
    staging: Path
    backup: Path


Rename = Callable[[Path, Path], None]


def build_paths(target: Path, timestamp: str) -> BuildPaths:
    return BuildPaths(
        active=target,
        staging=target.with_name(f"{target.name}.new-{timestamp}"),
        backup=target.with_name(f"{target.name}.bak-{timestamp}"),
    )


def required_free_bytes(active_size: int) -> int:
    return active_size + 5 * GIB


def utc_timestamp(now: datetime | None = None, token: str | None = None) -> str:
    instant = now or datetime.now(timezone.utc)
    instant = instant.astimezone(timezone.utc)
    suffix = token or secrets.token_hex(4)
    return f"{instant.strftime('%Y%m%dT%H%M%S.%fZ')}-{suffix}"


def _validate_static_request(paths: BuildPaths, check_script: Path, keep_backups: int) -> None:
    if not paths.active.is_absolute():
        raise ValueError("target must be absolute")
    if len(paths.active.parts) < 4 or ".." in paths.active.parts:
        raise ValueError(f"unsafe target path: {paths.active}")
    if not check_script.is_absolute():
        raise ValueError("check-script must be absolute")
    if keep_backups < 0:
        raise ValueError("keep-backups must be zero or greater")
    if paths.active.is_symlink():
        raise ValueError(f"target must not be a symlink: {paths.active}")
    if paths.active.exists() and not paths.active.is_dir():
        raise ValueError(f"target must be a directory when it exists: {paths.active}")
    if not paths.active.parent.is_dir():
        raise ValueError(f"target parent must be an existing directory: {paths.active.parent}")
    if not check_script.is_file():
        raise ValueError(f"check-script must be an existing file: {check_script}")


def validate_request(paths: BuildPaths, check_script: Path, keep_backups: int) -> None:
    _validate_static_request(paths, check_script, keep_backups)
    if paths.staging.exists() or paths.staging.is_symlink():
        raise FileExistsError(f"staging path already exists: {paths.staging}")
    if paths.backup.exists() or paths.backup.is_symlink():
        raise FileExistsError(f"backup path already exists: {paths.backup}")


def directory_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for root, _directories, files in os.walk(path, followlinks=False):
        root_path = Path(root)
        for filename in files:
            candidate = root_path / filename
            if not candidate.is_symlink():
                total += candidate.stat().st_size
    return total


def ensure_disk_space(
    paths: BuildPaths,
    directory_size: Callable[[Path], int] = directory_size_bytes,
    disk_usage: Callable[[Path], object] = shutil.disk_usage,
) -> None:
    active_size = directory_size(paths.active)
    required = required_free_bytes(active_size)
    free = int(getattr(disk_usage(paths.active.parent), "free"))
    if free < required:
        raise RuntimeError(f"Insufficient disk space: free={free} required={required}")


@contextmanager
def rebuild_lock(target: Path):
    lock_path = target.with_name(f".{target.name}.rebuild.lock")
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"MinerU venv rebuild already in progress: {lock_path}") from exc
        try:
            yield lock_path
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def prune_backups(target: Path, keep_backups: int) -> list[Path]:
    if keep_backups < 0:
        raise ValueError("keep-backups must be zero or greater")
    prefix = f"{target.name}.bak-"
    backups = sorted(
        (
            path
            for path in target.parent.iterdir()
            if path.name.startswith(prefix) and path.is_dir() and not path.is_symlink()
        ),
        key=lambda path: path.name,
    )
    remove = backups[:-keep_backups] if keep_backups else backups
    for backup in remove:
        shutil.rmtree(backup)
    return remove


def build_install_commands(source_python: Path, staging: Path, mineru_version: str) -> list[list[str]]:
    staging_python = staging / "bin" / "python"
    return [
        [str(source_python), "-m", "venv", str(staging)],
        [
            str(staging_python),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "pip",
            "setuptools",
            "wheel",
        ],
        [
            str(staging_python),
            "-m",
            "pip",
            "install",
            f"mineru[all]=={mineru_version}",
            "MarkupSafe==3.0.3",
        ],
    ]


def _regular_file_mode(path: Path) -> int | None:
    if path.is_symlink():
        return None
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return None
    return mode if stat.S_ISREG(mode) else None


def _rewrite_utf8_file(path: Path, old: str, new: str) -> bool:
    text = _read_utf8_regular_file(path)
    if text is None or old not in text:
        return False
    path.write_text(text.replace(old, new), encoding="utf-8")
    return True


def _read_utf8_regular_file(path: Path) -> str | None:
    if _regular_file_mode(path) is None:
        return None
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return None


def _executable_bin_files(venv: Path):
    bin_dir = venv / "bin"
    if not bin_dir.is_dir():
        return
    for path in sorted(bin_dir.iterdir(), key=lambda item: item.name):
        mode = _regular_file_mode(path)
        if mode is not None and mode & 0o111:
            yield path


def _relocation_text_files(venv: Path) -> list[Path]:
    candidates = [
        venv / "pyvenv.cfg",
        *(venv / "bin" / name for name in ACTIVATION_FILE_NAMES),
    ]
    for root, _directories, files in os.walk(venv, followlinks=False):
        root_path = Path(root)
        candidates.extend(
            root_path / filename
            for filename in files
            if filename.endswith((".pth", ".egg-link"))
        )
    return sorted(set(candidates), key=lambda item: item.as_posix())


def relocate_venv(staging: Path, active: Path) -> list[Path]:
    old = str(staging)
    new = str(active)
    rewritten: list[Path] = []
    for path in _executable_bin_files(staging):
        first_line = path.read_bytes().splitlines()[:1]
        if first_line and first_line[0].startswith(b"#!") and os.fsencode(old) in first_line[0]:
            if _rewrite_utf8_file(path, old, new):
                rewritten.append(path)

    for path in _relocation_text_files(staging):
        if _rewrite_utf8_file(path, old, new):
            rewritten.append(path)
    return rewritten


def assert_relocated(staging: Path, active: Path) -> None:
    staging_bytes = os.fsencode(str(staging))
    for path in _executable_bin_files(staging):
        first_line = path.read_bytes().splitlines()[:1]
        if first_line and first_line[0].startswith(b"#!") and staging_bytes in first_line[0]:
            raise RuntimeError(f"executable retains staging shebang: {path}")

    for path in _relocation_text_files(staging):
        text = _read_utf8_regular_file(path)
        if text is not None and str(staging) in text:
            raise RuntimeError(f"activation/config text retains staging prefix: {path}")

    expected = f"#!{active / 'bin' / 'python'}"
    for name in ("mineru", "mineru-api"):
        path = staging / "bin" / name
        mode = _regular_file_mode(path)
        if mode is None or not mode & 0o111:
            raise RuntimeError(f"required executable is missing: {path}")
        first_line = path.read_bytes().splitlines()[:1]
        try:
            shebang = first_line[0].decode("utf-8") if first_line else ""
        except UnicodeDecodeError as exc:
            raise RuntimeError(f"invalid {name} shebang: {path}") from exc
        if shebang != expected:
            raise RuntimeError(f"{name} shebang does not point to active interpreter: {shebang}")


def _validation_env(base_env: dict[str, str], venv: Path) -> dict[str, str]:
    env = dict(base_env)
    env.update(
        {
            "MINERU_COMMAND": str(venv / "bin" / "mineru"),
            "MINERU_API_ENABLED": "false",
            "CHECK_MINERU_IN_WORKER_VENV": "1",
        }
    )
    return env


def _run_checked(
    command: list[str],
    env: dict[str, str],
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> subprocess.CompletedProcess[str]:
    return runner(
        command,
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )


def _require_version(completed: subprocess.CompletedProcess[str], expected_version: str) -> None:
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    versions = [
        match.group(1)
        for line in output.splitlines()
        if (match := MINERU_VERSION_LINE.fullmatch(line)) is not None
    ]
    if len(versions) != 1:
        raise RuntimeError(
            f"MinerU version check expected exactly one version line for {expected_version}, "
            f"found {len(versions)}: {output or '<empty>'}"
        )
    actual_version = versions[0]
    if actual_version != expected_version:
        raise RuntimeError(f"MinerU version check expected {expected_version}, got {actual_version}")


def write_manifest(venv: Path, mineru_version: str, package_list: str) -> Path:
    manifest = venv / "mineru-venv-manifest.json"
    payload = {
        "manifestVersion": 1,
        "mineruVersion": mineru_version,
        "packageListSha256": hashlib.sha256(package_list.encode("utf-8")).hexdigest(),
    }
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def validate_staging(
    venv: Path,
    check_script: Path,
    expected_version: str,
    *,
    base_env: dict[str, str],
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Path:
    python = str(venv / "bin" / "python")
    mineru = str(venv / "bin" / "mineru")
    env = _validation_env(base_env, venv)
    _run_checked([python, str(check_script), "--json", "--skip-api"], env, runner)
    _run_checked([python, "-c", RUNTIME_IMPORT_PROBE], env, runner)
    version = _run_checked([mineru, "--version"], env, runner)
    _require_version(version, expected_version)
    packages = _run_checked([python, "-m", "pip", "freeze", "--all"], env, runner)
    return write_manifest(venv, expected_version, packages.stdout or "")


def validate_active(
    venv: Path,
    check_script: Path,
    expected_version: str,
    *,
    base_env: dict[str, str],
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    env = _validation_env(base_env, venv)
    _run_checked(
        [str(venv / "bin" / "python"), str(check_script), "--json", "--skip-api"],
        env,
        runner,
    )
    version = _run_checked([str(venv / "bin" / "mineru"), "--version"], env, runner)
    _require_version(version, expected_version)


def _rename(source: Path, target: Path) -> None:
    source.rename(target)


def activate(paths: BuildPaths, rename: Rename = _rename) -> None:
    moved_active = False
    try:
        if paths.active.exists():
            rename(paths.active, paths.backup)
            moved_active = True
        rename(paths.staging, paths.active)
    except BaseException:
        if moved_active and not paths.active.exists() and paths.backup.exists():
            rename(paths.backup, paths.active)
        raise


def _rollback_failed_active(paths: BuildPaths, rename: Rename) -> None:
    if paths.active.exists() or paths.active.is_symlink():
        if paths.staging.exists() or paths.staging.is_symlink():
            raise FileExistsError(f"cannot preserve failed active venv; staging path exists: {paths.staging}")
        rename(paths.active, paths.staging)
    if paths.backup.exists() or paths.backup.is_symlink():
        rename(paths.backup, paths.active)


def rebuild_venv(
    target: Path,
    source_python: Path,
    mineru_version: str,
    check_script: Path,
    keep_backups: int,
    *,
    timestamp: str | None = None,
    base_env: dict[str, str] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    disk_usage: Callable[[Path], object] = shutil.disk_usage,
    directory_size: Callable[[Path], int] = directory_size_bytes,
    rename: Rename = _rename,
    prune: Callable[[Path, int], list[Path]] = prune_backups,
) -> BuildPaths:
    paths = build_paths(target, timestamp or utc_timestamp())
    _validate_static_request(paths, check_script, keep_backups)
    env = dict(os.environ if base_env is None else base_env)
    with rebuild_lock(target):
        validate_request(paths, check_script, keep_backups)
        ensure_disk_space(paths, directory_size=directory_size, disk_usage=disk_usage)
        for command in build_install_commands(source_python, paths.staging, mineru_version):
            _run_checked(command, env, runner)
        validate_staging(
            paths.staging,
            check_script,
            mineru_version,
            base_env=env,
            runner=runner,
        )
        relocate_venv(paths.staging, paths.active)
        assert_relocated(paths.staging, paths.active)
        activate(paths, rename=rename)
        try:
            validate_active(
                paths.active,
                check_script,
                mineru_version,
                base_env=env,
                runner=runner,
            )
        except BaseException:
            _rollback_failed_active(paths, rename)
            raise
        prune(paths.active, keep_backups)
    return paths


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--mineru-version", default="3.4.2")
    parser.add_argument("--check-script", type=Path, required=True)
    parser.add_argument("--keep-backups", type=int, default=2)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = rebuild_venv(
        args.target,
        args.python,
        args.mineru_version,
        args.check_script,
        args.keep_backups,
    )
    print(f"Activated MinerU venv: {paths.active}")
    if paths.backup.exists():
        print(f"Previous MinerU venv backup: {paths.backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
