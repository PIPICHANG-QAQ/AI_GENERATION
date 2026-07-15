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
import sys
from typing import Callable


GIB = 1024**3
DEFAULT_INSTALL_TIMEOUT = 3600
DEFAULT_CHECK_TIMEOUT = 300
PYTHON_ENV_KEYS = {
    "PYTHONHOME",
    "PYTHONPATH",
    "PYTHONSTARTUP",
    "PYTHONINSPECT",
    "VIRTUAL_ENV",
    "__PYVENV_LAUNCHER__",
}
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
JOURNAL_PHASES = {
    "prepared",
    "active_moved",
    "new_active",
    "active_verified",
    "rollback_started",
    "rollback_new_saved",
}


def _rename(source: Path, target: Path) -> None:
    source.rename(target)


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


def _reject_symlink_components(path: Path, label: str) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise ValueError(f"{label} parent path contains symlink component: {current}")


def _validate_static_request(paths: BuildPaths, check_script: Path, keep_backups: int) -> None:
    if not paths.active.is_absolute():
        raise ValueError("target must be absolute")
    if len(paths.active.parts) < 4 or ".." in paths.active.parts:
        raise ValueError(f"unsafe target path: {paths.active}")
    if not check_script.is_absolute():
        raise ValueError("check-script must be absolute")
    if keep_backups < 0:
        raise ValueError("keep-backups must be zero or greater")
    _reject_symlink_components(paths.active.parent, "target")
    if paths.active.is_symlink():
        raise ValueError(f"target must not be a symlink: {paths.active}")
    if paths.active.exists() and not paths.active.is_dir():
        raise ValueError(f"target must be a directory when it exists: {paths.active}")
    if not paths.active.parent.is_dir():
        raise ValueError(f"target parent must be an existing directory: {paths.active.parent}")
    if check_script.is_symlink():
        raise ValueError(f"check-script must not be a symlink: {check_script}")
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


def transaction_journal_path(target: Path) -> Path:
    return target.with_name(f".{target.name}.rebuild-journal.json")


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def rename_and_sync(
    source: Path,
    target: Path,
    *,
    rename: Rename = _rename,
    sync_directory: Callable[[Path], None] = _fsync_directory,
) -> None:
    rename(source, target)
    sync_directory(source.parent)
    if target.parent != source.parent:
        sync_directory(target.parent)


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    if path.is_symlink():
        raise ValueError(f"journal must not be a symlink: {path}")
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}-{secrets.token_hex(4)}")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()


def write_transaction_journal(paths: BuildPaths, phase: str, *, had_active: bool) -> Path:
    if phase not in JOURNAL_PHASES:
        raise ValueError(f"invalid transaction journal phase: {phase}")
    journal = transaction_journal_path(paths.active)
    payload = {
        "schemaVersion": 1,
        "active": str(paths.active),
        "staging": str(paths.staging),
        "backup": str(paths.backup),
        "phase": phase,
        "hadActive": had_active,
    }
    _atomic_write_json(journal, payload)
    return journal


def _clear_transaction_journal(target: Path) -> None:
    journal = transaction_journal_path(target)
    if journal.is_symlink():
        raise ValueError(f"journal must not be a symlink: {journal}")
    if journal.exists():
        journal.unlink()
        _fsync_directory(journal.parent)


def _journal_paths(target: Path, payload: object) -> tuple[BuildPaths, str, bool]:
    if not isinstance(payload, dict):
        raise ValueError("journal must contain a JSON object")
    expected_keys = {"schemaVersion", "active", "staging", "backup", "phase", "hadActive"}
    if set(payload) != expected_keys or payload.get("schemaVersion") != 1:
        raise ValueError("journal has an unsupported schema")
    if not all(isinstance(payload.get(key), str) for key in ("active", "staging", "backup", "phase")):
        raise ValueError("journal paths and phase must be strings")
    if not isinstance(payload.get("hadActive"), bool):
        raise ValueError("journal hadActive must be a boolean")

    paths = BuildPaths(
        active=Path(payload["active"]),
        staging=Path(payload["staging"]),
        backup=Path(payload["backup"]),
    )
    phase = payload["phase"]
    if phase not in JOURNAL_PHASES:
        raise ValueError(f"journal has invalid phase: {phase}")
    if paths.active != target or not target.is_absolute():
        raise ValueError("journal active path does not match target")
    if paths.staging.parent != target.parent or paths.backup.parent != target.parent:
        raise ValueError("journal paths must be target siblings")
    staging_prefix = f"{target.name}.new-"
    backup_prefix = f"{target.name}.bak-"
    if not paths.staging.name.startswith(staging_prefix) or not paths.backup.name.startswith(backup_prefix):
        raise ValueError("journal paths do not match target naming")
    staging_suffix = paths.staging.name[len(staging_prefix) :]
    backup_suffix = paths.backup.name[len(backup_prefix) :]
    if not staging_suffix or staging_suffix != backup_suffix:
        raise ValueError("journal staging and backup timestamps do not match")
    for path in (paths.active, paths.staging, paths.backup):
        if ".." in path.parts or path.is_symlink():
            raise ValueError(f"journal path is unsafe: {path}")
    return paths, phase, payload["hadActive"]


def _load_transaction_journal(target: Path) -> tuple[BuildPaths, str, bool] | None:
    journal = transaction_journal_path(target)
    if journal.is_symlink():
        raise ValueError(f"journal must not be a symlink: {journal}")
    if not journal.exists():
        return None
    try:
        payload = json.loads(journal.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"journal is not valid UTF-8 JSON: {journal}") from exc
    return _journal_paths(target, payload)


def recover_transaction(target: Path, *, rename: Rename = _rename) -> BuildPaths | None:
    loaded = _load_transaction_journal(target)
    if loaded is None:
        return None
    paths, _phase, had_active = loaded
    active_exists = paths.active.exists()
    staging_exists = paths.staging.exists()
    backup_exists = paths.backup.exists()

    if had_active:
        if backup_exists:
            if active_exists and staging_exists:
                raise RuntimeError("journal recovery found ambiguous active, staging, and backup paths")
            if active_exists:
                write_transaction_journal(paths, "rollback_started", had_active=True)
                rename_and_sync(paths.active, paths.staging, rename=rename)
                active_exists = False
                staging_exists = True
            if not staging_exists:
                raise RuntimeError("journal recovery cannot preserve the failed new environment")
            write_transaction_journal(paths, "rollback_new_saved", had_active=True)
            rename_and_sync(paths.backup, paths.active, rename=rename)
        elif not (active_exists and staging_exists):
            raise RuntimeError("journal recovery cannot prove the old active environment is present")
    else:
        if backup_exists:
            raise RuntimeError("journal recovery found an unexpected backup")
        if active_exists and not staging_exists:
            write_transaction_journal(paths, "rollback_started", had_active=False)
            rename_and_sync(paths.active, paths.staging, rename=rename)
        elif active_exists or not staging_exists:
            raise RuntimeError("journal recovery found an ambiguous no-active transaction state")

    _clear_transaction_journal(target)
    return paths


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


def prune_failed_staging(target: Path, keep_failed_staging: int) -> list[Path]:
    if keep_failed_staging < 0:
        raise ValueError("keep-failed-staging must be zero or greater")
    name_pattern = re.compile(
        rf"{re.escape(target.name)}\.new-\d{{8}}T\d{{6}}\.\d{{6}}Z-[0-9a-f]{{8}}"
    )
    candidates: list[tuple[int, str, Path]] = []
    for path in target.parent.iterdir():
        if name_pattern.fullmatch(path.name) is None:
            continue
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(metadata.st_mode):
            candidates.append((metadata.st_mtime_ns, path.name, path))
    candidates.sort(key=lambda item: (item[0], item[1]))
    ordered = [path for _modified, _name, path in candidates]
    remove = ordered[:-keep_failed_staging] if keep_failed_staging else ordered
    for staging in remove:
        shutil.rmtree(staging)
    return remove


def build_install_commands(source_python: Path, staging: Path, mineru_version: str) -> list[list[str]]:
    staging_python = staging / "bin" / "python"
    return [
        [str(source_python), "-m", "venv", str(staging)],
        [
            str(staging_python),
            "-m",
            "pip",
            "--isolated",
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
            "--isolated",
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
    env = sanitized_environment(base_env)
    env.update(
        {
            "MINERU_COMMAND": str(venv / "bin" / "mineru"),
            "MINERU_API_ENABLED": "false",
            "CHECK_MINERU_IN_WORKER_VENV": "1",
        }
    )
    return env


def sanitized_environment(base_env: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in base_env.items()
        if key not in PYTHON_ENV_KEYS and not key.startswith("PIP_")
    }


def _run_install(
    command: list[str],
    env: dict[str, str],
    timeout: int,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> subprocess.CompletedProcess[str]:
    return runner(
        command,
        check=True,
        env=env,
        timeout=timeout,
    )


def _run_validation(
    command: list[str],
    env: dict[str, str],
    timeout: int,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> subprocess.CompletedProcess[str]:
    return runner(
        command,
        check=True,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def build_runtime_import_probe(venv: Path, expected_version: str) -> str:
    expected_prefix = str(venv)
    return "\n".join(
        (
            "import importlib.metadata as metadata",
            "import json",
            "from pathlib import Path",
            "import platform",
            "import sys",
            "import markupsafe",
            "from markupsafe import Markup",
            "import jinja2",
            "from jinja2 import Environment",
            "import transformers",
            "import mineru",
            "import mineru.cli.common as mineru_common",
            "from mineru.cli.common import read_fn",
            f"expected_prefix = Path({expected_prefix!r}).resolve()",
            "actual_prefix = Path(sys.prefix).resolve()",
            "if actual_prefix != expected_prefix:",
            "    raise RuntimeError(f'Python prefix outside target venv: {actual_prefix}')",
            "modules = {'markupsafe': markupsafe, 'jinja2': jinja2, 'transformers': transformers, "
            "'mineru': mineru, 'mineru.cli.common': mineru_common}",
            "module_paths = {}",
            "for name, module in modules.items():",
            "    source = Path(module.__file__).resolve()",
            "    try:",
            "        source.relative_to(expected_prefix)",
            "    except ValueError as exc:",
            "        raise RuntimeError(f'{name} imported outside target venv: {source}') from exc",
            "    module_paths[name] = str(source)",
            "mineru_version = metadata.version('mineru')",
            "markupsafe_version = metadata.version('MarkupSafe')",
            f"if mineru_version != {expected_version!r}:",
            f"    raise RuntimeError(f'MinerU metadata expected {expected_version}, got {{mineru_version}}')",
            "if markupsafe_version != '3.0.3':",
            "    raise RuntimeError(f'MarkupSafe metadata expected 3.0.3, got {markupsafe_version}')",
            "assert Markup and Environment and transformers and read_fn",
            "print(json.dumps({'mineruVersion': mineru_version, 'markupSafeVersion': markupsafe_version, "
            "'pythonVersion': platform.python_version(), 'pythonExecutable': sys.executable, "
            "'pythonPrefix': str(actual_prefix), 'modulePaths': module_paths}, sort_keys=True))",
        )
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


def _require_venv_executables(venv: Path) -> None:
    for name in ("python", "mineru", "mineru-api"):
        executable = venv / "bin" / name
        if not executable.exists() or not os.access(executable, os.X_OK):
            raise RuntimeError(f"required venv executable is missing or not executable: {executable}")


def _json_result(completed: subprocess.CompletedProcess[str], label: str) -> dict[str, object]:
    try:
        payload = json.loads(completed.stdout or "")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} validation did not return JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} validation must return a JSON object")
    return payload


def _readiness_result(completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
    payload = _json_result(completed, "readiness")
    if payload.get("installed") is not True or payload.get("runtimeProbeOk") is not True:
        raise RuntimeError("readiness validation facts are not healthy")
    return payload


def _runtime_result(
    completed: subprocess.CompletedProcess[str],
    venv: Path,
    expected_version: str,
) -> dict[str, object]:
    payload = _json_result(completed, "runtime import")
    if payload.get("mineruVersion") != expected_version:
        raise RuntimeError("runtime import MinerU metadata version is inconsistent")
    if payload.get("markupSafeVersion") != "3.0.3":
        raise RuntimeError("runtime import MarkupSafe metadata version is inconsistent")
    if not isinstance(payload.get("pythonVersion"), str) or not payload["pythonVersion"]:
        raise RuntimeError("runtime import result is missing Python version")
    if payload.get("pythonExecutable") != str(venv / "bin" / "python"):
        raise RuntimeError("runtime import Python executable is outside the target venv")
    expected_modules = {"markupsafe", "jinja2", "transformers", "mineru", "mineru.cli.common"}
    module_paths = payload.get("modulePaths")
    if not isinstance(module_paths, dict) or set(module_paths) != expected_modules:
        raise RuntimeError("runtime import result is missing required module paths")
    for name, value in module_paths.items():
        if not isinstance(value, str):
            raise RuntimeError(f"runtime import path for {name} is invalid")
        try:
            Path(value).resolve().relative_to(venv.resolve())
        except ValueError as exc:
            raise RuntimeError(f"runtime import path for {name} is outside the target venv") from exc
    return payload


def normalize_package_list(package_list: str) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for raw_line in package_list.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        pinned = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)", line)
        direct = re.fullmatch(r"([A-Za-z0-9_.-]+)\s*@\s*.+", line)
        editable = re.search(r"[#&]egg=([A-Za-z0-9_.-]+)", line)
        if pinned:
            name, version = pinned.groups()
        elif direct:
            name, version = direct.group(1), "<direct-reference>"
        elif editable:
            name, version = editable.group(1), "<direct-reference>"
        else:
            name, version = "<redacted-entry>", "<unparsed>"
        canonical_name = re.sub(r"[-_.]+", "-", name).lower()
        normalized.append({"name": canonical_name, "version": version})
    return sorted(normalized, key=lambda item: (item["name"], item["version"]))


def _package_list_digest(packages: list[dict[str, str]]) -> str:
    canonical = json.dumps(packages, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_manifest(
    venv: Path,
    mineru_version: str,
    package_list: str,
    *,
    active_venv: Path,
    readiness: dict[str, object],
    runtime: dict[str, object],
    validated_at: str | None = None,
) -> Path:
    manifest = venv / "mineru-venv-manifest.json"
    packages = normalize_package_list(package_list)
    timestamp = validated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    payload = {
        "manifestVersion": 2,
        "targetMineruVersion": mineru_version,
        "packages": packages,
        "packageListSha256": _package_list_digest(packages),
        "python": {
            "version": runtime["pythonVersion"],
            "executable": str(active_venv / "bin" / "python"),
        },
        "validation": {
            "validatedAt": timestamp,
            "readiness": readiness.get("installed") is True and readiness.get("runtimeProbeOk") is True,
            "runtimeImports": True,
            "metadataVersions": True,
            "versionCommand": True,
            "mineruVersion": runtime["mineruVersion"],
            "markupSafeVersion": runtime["markupSafeVersion"],
        },
    }
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _verify_manifest(
    venv: Path,
    expected_version: str,
    package_list: str,
    runtime: dict[str, object],
) -> None:
    manifest = venv / "mineru-venv-manifest.json"
    if manifest.is_symlink() or not manifest.is_file():
        raise RuntimeError(f"manifest is missing or unsafe: {manifest}")
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"manifest is not valid UTF-8 JSON: {manifest}") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "manifestVersion",
        "targetMineruVersion",
        "packages",
        "packageListSha256",
        "python",
        "validation",
    }:
        raise RuntimeError("manifest has missing or unexpected fields")
    packages = payload.get("packages")
    if not isinstance(packages, list) or packages != normalize_package_list(package_list):
        raise RuntimeError("manifest package list does not match active environment")
    if payload.get("packageListSha256") != _package_list_digest(packages):
        raise RuntimeError("manifest package-list hash is invalid")
    if payload.get("manifestVersion") != 2 or payload.get("targetMineruVersion") != expected_version:
        raise RuntimeError("manifest target version is inconsistent")
    python = payload.get("python")
    if not isinstance(python, dict) or python != {
        "version": runtime["pythonVersion"],
        "executable": str(venv / "bin" / "python"),
    }:
        raise RuntimeError("manifest Python facts are inconsistent")
    validation = payload.get("validation")
    required_facts = {
        "readiness": True,
        "runtimeImports": True,
        "metadataVersions": True,
        "versionCommand": True,
        "mineruVersion": expected_version,
        "markupSafeVersion": "3.0.3",
    }
    if (
        not isinstance(validation, dict)
        or set(validation) != {*required_facts, "validatedAt"}
        or any(validation.get(key) != value for key, value in required_facts.items())
    ):
        raise RuntimeError("manifest validation facts are inconsistent")
    validated_at = validation.get("validatedAt")
    try:
        if not isinstance(validated_at, str):
            raise ValueError
        datetime.strptime(validated_at, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        raise RuntimeError("manifest validation timestamp is invalid")


def validate_staging(
    venv: Path,
    check_script: Path,
    expected_version: str,
    *,
    base_env: dict[str, str],
    active_venv: Path | None = None,
    check_timeout: int = DEFAULT_CHECK_TIMEOUT,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Path:
    _require_venv_executables(venv)
    python = str(venv / "bin" / "python")
    mineru = str(venv / "bin" / "mineru")
    env = _validation_env(base_env, venv)
    readiness_completed = _run_validation(
        [python, "-I", str(check_script), "--json", "--skip-api"], env, check_timeout, runner
    )
    readiness = _readiness_result(readiness_completed)
    runtime_completed = _run_validation(
        [python, "-I", "-c", build_runtime_import_probe(venv, expected_version)],
        env,
        check_timeout,
        runner,
    )
    runtime = _runtime_result(runtime_completed, venv, expected_version)
    version = _run_validation([mineru, "--version"], env, check_timeout, runner)
    _require_version(version, expected_version)
    packages = _run_validation([python, "-I", "-m", "pip", "freeze", "--all"], env, check_timeout, runner)
    return write_manifest(
        venv,
        expected_version,
        packages.stdout or "",
        active_venv=active_venv or venv,
        readiness=readiness,
        runtime=runtime,
    )


def validate_active(
    venv: Path,
    check_script: Path,
    expected_version: str,
    *,
    base_env: dict[str, str],
    check_timeout: int = DEFAULT_CHECK_TIMEOUT,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    _require_venv_executables(venv)
    env = _validation_env(base_env, venv)
    python = str(venv / "bin" / "python")
    readiness_completed = _run_validation(
        [python, "-I", str(check_script), "--json", "--skip-api"],
        env,
        check_timeout,
        runner,
    )
    _readiness_result(readiness_completed)
    runtime_completed = _run_validation(
        [python, "-I", "-c", build_runtime_import_probe(venv, expected_version)],
        env,
        check_timeout,
        runner,
    )
    runtime = _runtime_result(runtime_completed, venv, expected_version)
    version = _run_validation(
        [str(venv / "bin" / "mineru"), "--version"],
        env,
        check_timeout,
        runner,
    )
    _require_version(version, expected_version)
    packages = _run_validation(
        [python, "-I", "-m", "pip", "freeze", "--all"],
        env,
        check_timeout,
        runner,
    )
    _verify_manifest(venv, expected_version, packages.stdout or "", runtime)


def verify_active_venv(
    target: Path,
    check_script: Path,
    expected_version: str,
    *,
    base_env: dict[str, str] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    check_timeout: int = DEFAULT_CHECK_TIMEOUT,
) -> None:
    paths = build_paths(target, "verify-only")
    _validate_static_request(paths, check_script, keep_backups=0)
    if not target.is_dir():
        raise ValueError(f"target must be an existing active venv: {target}")
    validate_active(
        target,
        check_script,
        expected_version,
        base_env=dict(os.environ if base_env is None else base_env),
        check_timeout=check_timeout,
        runner=runner,
    )


def activate(paths: BuildPaths, rename: Rename = _rename) -> None:
    had_active = paths.active.exists()
    write_transaction_journal(paths, "prepared", had_active=had_active)
    try:
        if had_active:
            rename_and_sync(paths.active, paths.backup, rename=rename)
        write_transaction_journal(paths, "active_moved", had_active=had_active)
        rename_and_sync(paths.staging, paths.active, rename=rename)
        write_transaction_journal(paths, "new_active", had_active=had_active)
    except BaseException:
        recover_transaction(paths.active, rename=rename)
        raise


def _rollback_failed_active(paths: BuildPaths, rename: Rename) -> None:
    loaded = _load_transaction_journal(paths.active)
    had_active = loaded[2] if loaded is not None else paths.backup.exists()
    write_transaction_journal(paths, "rollback_started", had_active=had_active)
    if paths.active.exists() or paths.active.is_symlink():
        if paths.staging.exists() or paths.staging.is_symlink():
            raise FileExistsError(f"cannot preserve failed active venv; staging path exists: {paths.staging}")
        rename_and_sync(paths.active, paths.staging, rename=rename)
        write_transaction_journal(paths, "rollback_new_saved", had_active=had_active)
    if paths.backup.exists() or paths.backup.is_symlink():
        rename_and_sync(paths.backup, paths.active, rename=rename)
    _clear_transaction_journal(paths.active)


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
    prune_failed: Callable[[Path, int], list[Path]] = prune_failed_staging,
    keep_failed_staging: int = 2,
    install_timeout: int = DEFAULT_INSTALL_TIMEOUT,
    check_timeout: int = DEFAULT_CHECK_TIMEOUT,
) -> BuildPaths:
    if keep_failed_staging < 0:
        raise ValueError("keep-failed-staging must be zero or greater")
    paths = build_paths(target, timestamp or utc_timestamp())
    _validate_static_request(paths, check_script, keep_backups)
    env = sanitized_environment(dict(os.environ if base_env is None else base_env))
    with rebuild_lock(target):
        recover_transaction(target, rename=rename)
        validate_request(paths, check_script, keep_backups)
        ensure_disk_space(paths, directory_size=directory_size, disk_usage=disk_usage)
        for command in build_install_commands(source_python, paths.staging, mineru_version):
            _run_install(command, env, install_timeout, runner)
        validate_staging(
            paths.staging,
            check_script,
            mineru_version,
            base_env=env,
            active_venv=paths.active,
            check_timeout=check_timeout,
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
                check_timeout=check_timeout,
                runner=runner,
            )
        except BaseException:
            _rollback_failed_active(paths, rename)
            raise
        loaded = _load_transaction_journal(paths.active)
        if loaded is None:
            raise RuntimeError("activation transaction journal disappeared before commit")
        write_transaction_journal(paths, "active_verified", had_active=loaded[2])
        _clear_transaction_journal(paths.active)
        try:
            prune(paths.active, keep_backups)
        except Exception as exc:
            print(f"WARNING: MinerU backup pruning failed after healthy activation: {exc}", file=sys.stderr)
        try:
            prune_failed(paths.active, keep_failed_staging)
        except Exception as exc:
            print(f"WARNING: MinerU failed-staging pruning failed after healthy activation: {exc}", file=sys.stderr)
    return paths


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("timeout must be a positive integer")
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--mineru-version", default="3.4.2")
    parser.add_argument("--check-script", type=Path, required=True)
    parser.add_argument("--keep-backups", type=int, default=2)
    parser.add_argument("--keep-failed-staging", type=_nonnegative_int, default=2)
    parser.add_argument("--install-timeout", type=_positive_int, default=DEFAULT_INSTALL_TIMEOUT)
    parser.add_argument("--check-timeout", type=_positive_int, default=DEFAULT_CHECK_TIMEOUT)
    args = parser.parse_args(argv)
    if not args.verify_only and args.python is None:
        parser.error("--python is required unless --verify-only is used")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.verify_only:
            verify_active_venv(
                args.target,
                args.check_script,
                args.mineru_version,
                check_timeout=args.check_timeout,
            )
            print(f"Verified MinerU venv: {args.target}")
            return 0
        paths = rebuild_venv(
            args.target,
            args.python,
            args.mineru_version,
            args.check_script,
            args.keep_backups,
            keep_failed_staging=args.keep_failed_staging,
            install_timeout=args.install_timeout,
            check_timeout=args.check_timeout,
        )
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        print(f"MinerU venv operation failed: {exc}", file=sys.stderr)
        for detail in (getattr(exc, "stdout", None), getattr(exc, "stderr", None), getattr(exc, "output", None)):
            if detail:
                print(detail, file=sys.stderr)
        return 1
    print(f"Activated MinerU venv: {paths.active}")
    if paths.backup.exists():
        print(f"Previous MinerU venv backup: {paths.backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
