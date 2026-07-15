#!/usr/bin/env python3
"""Regression tests for atomic MinerU virtualenv rebuilds."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import subprocess
import sys
from types import SimpleNamespace
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import rebuild_mineru_venv


class AtomicMineruVenvTest(unittest.TestCase):
    def test_staging_and_backup_are_siblings_of_active_venv(self) -> None:
        paths = rebuild_mineru_venv.build_paths(Path("/srv/vendor/mineru-venv"), "20260715T120000")

        self.assertEqual(Path("/srv/vendor/mineru-venv.new-20260715T120000"), paths.staging)
        self.assertEqual(Path("/srv/vendor/mineru-venv.bak-20260715T120000"), paths.backup)

    def test_disk_guard_requires_active_size_plus_five_gib(self) -> None:
        required = rebuild_mineru_venv.required_free_bytes(active_size=10 * 1024**3)

        self.assertEqual(15 * 1024**3, required)

    def test_server_install_commands_use_only_online_resolution(self) -> None:
        commands = rebuild_mineru_venv.build_install_commands(
            Path("/usr/bin/python3"),
            Path("/srv/vendor/mineru-venv.new-1"),
            "3.4.2",
        )

        self.assertEqual(
            [
                ["/usr/bin/python3", "-m", "venv", "/srv/vendor/mineru-venv.new-1"],
                [
                    "/srv/vendor/mineru-venv.new-1/bin/python",
                    "-m",
                    "pip",
                    "install",
                    "--upgrade",
                    "pip",
                    "setuptools",
                    "wheel",
                ],
                [
                    "/srv/vendor/mineru-venv.new-1/bin/python",
                    "-m",
                    "pip",
                    "install",
                    "mineru[all]==3.4.2",
                    "MarkupSafe==3.0.3",
                ],
            ],
            commands,
        )
        flattened = " ".join(part for command in commands for part in command)
        self.assertNotIn("--find-links", flattened)
        self.assertNotIn("--no-index", flattened)
        self.assertNotIn("wheelhouse", flattened.lower())

    def test_activate_moves_active_to_backup_then_staging_to_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = rebuild_mineru_venv.build_paths(Path(tmp) / "mineru-venv", "20260715T120000")
            paths.active.mkdir()
            (paths.active / "old").write_text("old", encoding="utf-8")
            paths.staging.mkdir()
            (paths.staging / "new").write_text("new", encoding="utf-8")

            rebuild_mineru_venv.activate(paths)

            self.assertEqual("new", (paths.active / "new").read_text(encoding="utf-8"))
            self.assertEqual("old", (paths.backup / "old").read_text(encoding="utf-8"))

    def test_activate_rolls_back_when_staging_rename_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = rebuild_mineru_venv.build_paths(Path(tmp) / "mineru-venv", "20260715T120000")
            paths.active.mkdir()
            (paths.active / "old").write_text("old", encoding="utf-8")
            paths.staging.mkdir()
            calls = 0

            def flaky_rename(source: Path, target: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated activation failure")
                source.rename(target)

            with self.assertRaisesRegex(OSError, "simulated activation failure"):
                rebuild_mineru_venv.activate(paths, rename=flaky_rename)

            self.assertEqual("old", (paths.active / "old").read_text(encoding="utf-8"))
            self.assertTrue(paths.staging.is_dir())


class RebuildSafetyTest(unittest.TestCase):
    def _request_paths(self, root: Path) -> tuple[rebuild_mineru_venv.BuildPaths, Path]:
        check_script = root / "scripts" / "check_mineru.py"
        check_script.parent.mkdir()
        check_script.write_text("# readiness\n", encoding="utf-8")
        return rebuild_mineru_venv.build_paths(root / "vendor" / "mineru-venv", "fixed"), check_script

    def test_utc_timestamp_is_collision_resistant_and_injectable(self) -> None:
        timestamp = rebuild_mineru_venv.utc_timestamp(
            now=datetime(2026, 7, 15, 12, 0, 0, 123456, tzinfo=timezone.utc),
            token="a1b2c3d4",
        )

        self.assertEqual("20260715T120000.123456Z-a1b2c3d4", timestamp)

    def test_request_rejects_relative_target_and_check_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths, check_script = self._request_paths(root)

            with self.assertRaisesRegex(ValueError, "target must be absolute"):
                rebuild_mineru_venv.validate_request(
                    rebuild_mineru_venv.build_paths(Path("vendor/mineru-venv"), "fixed"),
                    check_script,
                    2,
                )
            with self.assertRaisesRegex(ValueError, "check-script must be absolute"):
                rebuild_mineru_venv.validate_request(paths, Path("scripts/check_mineru.py"), 2)

    def test_request_rejects_root_like_target(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsafe target"):
            rebuild_mineru_venv.validate_request(
                rebuild_mineru_venv.build_paths(Path("/opt/mineru-venv"), "fixed"),
                Path("/tmp/scripts/check_mineru.py"),
                2,
            )

    def test_request_rejects_parent_traversal_in_target(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsafe target"):
            rebuild_mineru_venv.validate_request(
                rebuild_mineru_venv.build_paths(Path("/srv/vendor/../mineru-venv"), "fixed"),
                Path("/tmp/scripts/check_mineru.py"),
                2,
            )

    def test_request_rejects_existing_target_that_is_not_a_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths, check_script = self._request_paths(root)
            paths.active.parent.mkdir()
            paths.active.write_text("not a venv", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "target must be a directory"):
                rebuild_mineru_venv.validate_request(paths, check_script, 2)

    def test_request_rejects_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths, check_script = self._request_paths(root)
            paths.active.parent.mkdir()
            real_venv = root / "real-venv"
            real_venv.mkdir()
            paths.active.symlink_to(real_venv, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "symlink"):
                rebuild_mineru_venv.validate_request(paths, check_script, 2)

    def test_request_rejects_staging_and_backup_collisions(self) -> None:
        for collision_name in ("staging", "backup"):
            with self.subTest(collision=collision_name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                paths, check_script = self._request_paths(root)
                paths.active.parent.mkdir()
                getattr(paths, collision_name).mkdir()

                with self.assertRaisesRegex(FileExistsError, collision_name):
                    rebuild_mineru_venv.validate_request(paths, check_script, 2)

    def test_request_rejects_negative_backup_retention(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths, check_script = self._request_paths(Path(tmp))

            with self.assertRaisesRegex(ValueError, "keep-backups"):
                rebuild_mineru_venv.validate_request(paths, check_script, -1)

    def test_disk_guard_rejects_less_than_active_size_plus_five_gib(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths, _check_script = self._request_paths(root)
            paths.active.parent.mkdir()
            paths.active.mkdir()
            active_size = 10 * 1024**3
            required = rebuild_mineru_venv.required_free_bytes(active_size)

            with self.assertRaisesRegex(RuntimeError, "Insufficient disk space"):
                rebuild_mineru_venv.ensure_disk_space(
                    paths,
                    directory_size=lambda _path: active_size,
                    disk_usage=lambda _path: SimpleNamespace(free=required - 1),
                )

            rebuild_mineru_venv.ensure_disk_space(
                paths,
                directory_size=lambda _path: active_size,
                disk_usage=lambda _path: SimpleNamespace(free=required),
            )

    def test_lock_rejects_contention_and_is_released_after_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "vendor" / "mineru-venv"
            target.parent.mkdir()

            with rebuild_mineru_venv.rebuild_lock(target):
                with self.assertRaisesRegex(RuntimeError, "already in progress"):
                    with rebuild_mineru_venv.rebuild_lock(target):
                        self.fail("contended lock was acquired")

            with self.assertRaisesRegex(RuntimeError, "simulated build failure"):
                with rebuild_mineru_venv.rebuild_lock(target):
                    raise RuntimeError("simulated build failure")

            with rebuild_mineru_venv.rebuild_lock(target):
                pass

    def test_prune_keeps_newest_backups_without_touching_other_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "vendor" / "mineru-venv"
            target.parent.mkdir()
            target.mkdir()
            staging = target.with_name(f"{target.name}.new-current")
            staging.mkdir()
            backups = [target.with_name(f"{target.name}.bak-{stamp}") for stamp in ("001", "002", "003")]
            for backup in backups:
                backup.mkdir()
            symlink_backup = target.with_name(f"{target.name}.bak-000")
            symlink_backup.symlink_to(target, target_is_directory=True)

            removed = rebuild_mineru_venv.prune_backups(target, keep_backups=2)

            self.assertEqual([backups[0]], removed)
            self.assertFalse(backups[0].exists())
            self.assertTrue(backups[1].is_dir())
            self.assertTrue(backups[2].is_dir())
            self.assertTrue(target.is_dir())
            self.assertTrue(staging.is_dir())
            self.assertTrue(symlink_backup.is_symlink())


class VenvRelocationTest(unittest.TestCase):
    @staticmethod
    def _write_entrypoint(path: Path, python: Path, body: str = "print('ok')\n") -> None:
        path.write_text(f"#!{python}\n{body}", encoding="utf-8")
        path.chmod(0o755)

    def test_relocation_rewrites_only_known_text_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = rebuild_mineru_venv.build_paths(root / "vendor" / "mineru-venv", "fixed")
            bin_dir = paths.staging / "bin"
            site_packages = paths.staging / "lib" / "python3.12" / "site-packages"
            bin_dir.mkdir(parents=True)
            site_packages.mkdir(parents=True)
            staging_python = paths.staging / "bin" / "python"
            active_python = paths.active / "bin" / "python"
            for name in ("mineru", "mineru-api", "other-tool"):
                self._write_entrypoint(bin_dir / name, staging_python)
            non_executable = bin_dir / "not-an-entrypoint"
            non_executable.write_text(f"#!{staging_python}\n", encoding="utf-8")
            binary = bin_dir / "binary-tool"
            binary.write_bytes(b"\x00\xff" + os.fsencode(paths.staging))
            binary.chmod(0o755)
            symlink_target = root / "outside-entrypoint"
            self._write_entrypoint(symlink_target, staging_python)
            (bin_dir / "linked-tool").symlink_to(symlink_target)
            pyvenv_cfg = paths.staging / "pyvenv.cfg"
            pyvenv_cfg.write_text(f"command = python -m venv {paths.staging}\n", encoding="utf-8")
            pth = site_packages / "editable.pth"
            pth.write_text(f"{paths.staging}/src\n", encoding="utf-8")
            egg_link = site_packages / "editable.egg-link"
            egg_link.write_text(f"{paths.staging}/package\n.\n", encoding="utf-8")
            binary_pth = site_packages / "binary.pth"
            binary_pth.write_bytes(b"\xff" + os.fsencode(paths.staging))

            rewritten = rebuild_mineru_venv.relocate_venv(paths.staging, paths.active)
            rebuild_mineru_venv.assert_relocated(paths.staging, paths.active)

            expected_rewritten = {
                bin_dir / "mineru",
                bin_dir / "mineru-api",
                bin_dir / "other-tool",
                pyvenv_cfg,
                pth,
                egg_link,
            }
            self.assertEqual(expected_rewritten, set(rewritten))
            for name in ("mineru", "mineru-api", "other-tool"):
                self.assertEqual(f"#!{active_python}", (bin_dir / name).read_text(encoding="utf-8").splitlines()[0])
            self.assertIn(str(paths.active), pyvenv_cfg.read_text(encoding="utf-8"))
            self.assertIn(str(paths.active), pth.read_text(encoding="utf-8"))
            self.assertIn(str(paths.active), egg_link.read_text(encoding="utf-8"))
            self.assertEqual(f"#!{staging_python}\n", non_executable.read_text(encoding="utf-8"))
            self.assertEqual(b"\x00\xff" + os.fsencode(paths.staging), binary.read_bytes())
            self.assertEqual(f"#!{staging_python}\nprint('ok')\n", symlink_target.read_text(encoding="utf-8"))
            self.assertEqual(b"\xff" + os.fsencode(paths.staging), binary_pth.read_bytes())

    def test_relocation_assertion_rejects_staging_shebang_and_wrong_required_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = rebuild_mineru_venv.build_paths(Path(tmp) / "vendor" / "mineru-venv", "fixed")
            bin_dir = paths.staging / "bin"
            bin_dir.mkdir(parents=True)
            staging_python = paths.staging / "bin" / "python"
            active_python = paths.active / "bin" / "python"
            self._write_entrypoint(bin_dir / "mineru", staging_python)
            self._write_entrypoint(bin_dir / "mineru-api", active_python)

            with self.assertRaisesRegex(RuntimeError, "staging shebang"):
                rebuild_mineru_venv.assert_relocated(paths.staging, paths.active)

            self._write_entrypoint(bin_dir / "mineru", active_python)
            self._write_entrypoint(bin_dir / "mineru-api", Path("/wrong/python"))
            with self.assertRaisesRegex(RuntimeError, "mineru-api"):
                rebuild_mineru_venv.assert_relocated(paths.staging, paths.active)

    def test_real_generated_console_script_runs_after_rewrite_and_rename(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mineru-relocate-", dir="/tmp") as tmp:
            paths = rebuild_mineru_venv.build_paths(Path(tmp).resolve() / "vendor" / "mineru-venv", "fixed")
            paths.active.parent.mkdir()
            subprocess.run(
                [sys.executable, "-m", "venv", str(paths.staging)],
                check=True,
                env=os.environ.copy(),
            )
            staging_python = paths.staging / "bin" / "python"
            site_packages = subprocess.run(
                [
                    str(staging_python),
                    "-c",
                    "import sysconfig; print(sysconfig.get_paths()['purelib'])",
                ],
                check=True,
                env=os.environ.copy(),
                capture_output=True,
                text=True,
            ).stdout.strip()
            Path(site_packages, "demo_console.py").write_text(
                "import sys\n"
                "def main():\n"
                "    print(sys.prefix)\n"
                "    return 0\n",
                encoding="utf-8",
            )
            generator = (
                "from pip._vendor.distlib.scripts import ScriptMaker\n"
                "import sys\n"
                f"maker = ScriptMaker(None, {str(paths.staging / 'bin')!r})\n"
                "maker.clobber = True\n"
                "maker.variants = {''}\n"
                "maker.executable = sys.executable\n"
                "maker.make('mineru = demo_console:main')\n"
                "maker.make('mineru-api = demo_console:main')\n"
            )
            subprocess.run(
                [str(staging_python), "-c", generator],
                check=True,
                env=os.environ.copy(),
            )
            before = subprocess.run(
                [str(paths.staging / "bin" / "mineru")],
                check=True,
                env=os.environ.copy(),
                capture_output=True,
                text=True,
            )
            self.assertEqual(paths.staging.resolve(), Path(before.stdout.strip()).resolve())

            rebuild_mineru_venv.relocate_venv(paths.staging, paths.active)
            rebuild_mineru_venv.assert_relocated(paths.staging, paths.active)
            rebuild_mineru_venv.activate(paths)

            after = subprocess.run(
                [str(paths.active / "bin" / "mineru")],
                check=True,
                env=os.environ.copy(),
                capture_output=True,
                text=True,
            )
            self.assertEqual(paths.active.resolve(), Path(after.stdout.strip()).resolve())


class VenvValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def _runner(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append((command, kwargs))
        if command[-2:] == ["--json", "--skip-api"]:
            stdout = '{"installed":true,"runtimeProbeOk":true}\n'
        elif command[-1:] == ["--version"]:
            stdout = "mineru, version 3.4.2\n"
        elif command[-3:] == ["pip", "freeze", "--all"]:
            stdout = "MarkupSafe==3.0.3\nmineru==3.4.2\n"
        else:
            stdout = ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    def test_runtime_import_probe_is_exact(self) -> None:
        self.assertEqual(
            "\n".join(
                (
                    "from markupsafe import Markup",
                    "from jinja2 import Environment",
                    "import transformers",
                    "from mineru.cli.common import read_fn",
                    "assert Markup and Environment and transformers and read_fn",
                )
            ),
            rebuild_mineru_venv.RUNTIME_IMPORT_PROBE,
        )

    def test_staging_validation_uses_exact_commands_and_explicit_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / "mineru-venv.new-fixed"
            venv.mkdir()
            check_script = Path(tmp) / "scripts" / "check_mineru.py"
            check_script.parent.mkdir()
            check_script.write_text("# check\n", encoding="utf-8")

            manifest = rebuild_mineru_venv.validate_staging(
                venv,
                check_script,
                "3.4.2",
                base_env={"PATH": "/test/bin", "UNRELATED": "kept"},
                runner=self._runner,
            )

            python = str(venv / "bin" / "python")
            mineru = str(venv / "bin" / "mineru")
            self.assertEqual(
                [
                    [python, str(check_script), "--json", "--skip-api"],
                    [python, "-c", rebuild_mineru_venv.RUNTIME_IMPORT_PROBE],
                    [mineru, "--version"],
                    [python, "-m", "pip", "freeze", "--all"],
                ],
                [command for command, _kwargs in self.calls],
            )
            for command, kwargs in self.calls:
                self.assertIsInstance(command, list)
                self.assertIs(kwargs["check"], True)
                self.assertNotIn("shell", kwargs)
                self.assertIs(kwargs["capture_output"], True)
                self.assertIs(kwargs["text"], True)
                env = kwargs["env"]
                self.assertIsInstance(env, dict)
                self.assertEqual("/test/bin", env["PATH"])
                self.assertEqual("kept", env["UNRELATED"])
                self.assertEqual(mineru, env["MINERU_COMMAND"])
                self.assertEqual("false", env["MINERU_API_ENABLED"])
                self.assertEqual("1", env["CHECK_MINERU_IN_WORKER_VENV"])
            self.assertEqual(venv / "mineru-venv-manifest.json", manifest)

    def test_manifest_hashes_package_list_without_recording_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp)
            package_list = "safe==1\nprivate @ https://user:secret-token@example.invalid/pkg.whl\n"

            manifest_path = rebuild_mineru_venv.write_manifest(venv, "3.4.2", package_list)
            manifest_text = manifest_path.read_text(encoding="utf-8")
            payload = json.loads(manifest_text)

            self.assertEqual("3.4.2", payload["mineruVersion"])
            self.assertEqual(hashlib.sha256(package_list.encode("utf-8")).hexdigest(), payload["packageListSha256"])
            self.assertNotIn("secret-token", manifest_text)
            self.assertNotIn("https://", manifest_text)
            self.assertNotIn("private", manifest_text)

    def test_staging_validation_rejects_unexpected_mineru_version(self) -> None:
        def wrong_version(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            completed = self._runner(command, **kwargs)
            if command[-1:] == ["--version"]:
                return subprocess.CompletedProcess(command, 0, stdout="mineru, version 3.4.1\n", stderr="")
            return completed

        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / "staging"
            venv.mkdir()
            check_script = Path(tmp) / "check.py"

            with self.assertRaisesRegex(RuntimeError, "expected 3.4.2"):
                rebuild_mineru_venv.validate_staging(
                    venv,
                    check_script,
                    "3.4.2",
                    base_env={},
                    runner=wrong_version,
                )

            self.assertFalse((venv / "mineru-venv-manifest.json").exists())

    def test_active_validation_rechecks_active_python_command_and_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            active = Path(tmp) / "mineru-venv"
            check_script = Path(tmp) / "scripts" / "check_mineru.py"

            rebuild_mineru_venv.validate_active(
                active,
                check_script,
                "3.4.2",
                base_env={"PATH": "/test/bin"},
                runner=self._runner,
            )

            self.assertEqual(
                [
                    [str(active / "bin" / "python"), str(check_script), "--json", "--skip-api"],
                    [str(active / "bin" / "mineru"), "--version"],
                ],
                [command for command, _kwargs in self.calls],
            )
            for _command, kwargs in self.calls:
                env = kwargs["env"]
                self.assertEqual(str(active / "bin" / "mineru"), env["MINERU_COMMAND"])
                self.assertEqual("false", env["MINERU_API_ENABLED"])
                self.assertEqual("1", env["CHECK_MINERU_IN_WORKER_VENV"])


class RebuildOrchestrationTest(unittest.TestCase):
    def _setup(self, root: Path, *, with_active: bool = True) -> tuple[rebuild_mineru_venv.BuildPaths, Path]:
        target = root / "vendor" / "mineru-venv"
        target.parent.mkdir()
        if with_active:
            target.mkdir()
            (target / "old-marker").write_text("old", encoding="utf-8")
        check_script = root / "scripts" / "check_mineru.py"
        check_script.parent.mkdir()
        check_script.write_text("# readiness\n", encoding="utf-8")
        return rebuild_mineru_venv.build_paths(target, "20260715T120000.000000Z-fixed"), check_script

    @staticmethod
    def _entrypoint(path: Path, python: Path) -> None:
        path.write_text(f"#!{python}\nprint('ok')\n", encoding="utf-8")
        path.chmod(0o755)

    def _runner(
        self,
        paths: rebuild_mineru_venv.BuildPaths,
        calls: list[tuple[list[str], dict[str, object]]],
        *,
        fail_install: bool = False,
        fail_active_readiness: bool = False,
    ):
        def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append((command, kwargs))
            if command[1:3] == ["-m", "venv"]:
                bin_dir = paths.staging / "bin"
                bin_dir.mkdir(parents=True)
                (paths.staging / "new-marker").write_text("new", encoding="utf-8")
                for name in ("mineru", "mineru-api"):
                    self._entrypoint(bin_dir / name, bin_dir / "python")
                (paths.staging / "pyvenv.cfg").write_text(
                    f"command = python -m venv {paths.staging}\n",
                    encoding="utf-8",
                )
            elif fail_install and command[1:6] == ["-m", "pip", "install", "--upgrade", "pip"]:
                raise subprocess.CalledProcessError(1, command)
            if fail_active_readiness and command == [
                str(paths.active / "bin" / "python"),
                str(paths.active.parent.parent / "scripts" / "check_mineru.py"),
                "--json",
                "--skip-api",
            ]:
                raise subprocess.CalledProcessError(1, command)
            if command[-1:] == ["--version"]:
                stdout = "mineru, version 3.4.2\n"
            elif command[-3:] == ["pip", "freeze", "--all"]:
                stdout = "MarkupSafe==3.0.3\nmineru==3.4.2\n"
            else:
                stdout = ""
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

        return run

    def test_success_builds_validates_activates_revalidates_then_prunes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths, check_script = self._setup(root)
            for stamp in ("001", "002", "003"):
                paths.active.with_name(f"{paths.active.name}.bak-{stamp}").mkdir()
            calls: list[tuple[list[str], dict[str, object]]] = []

            result = rebuild_mineru_venv.rebuild_venv(
                paths.active,
                Path("/usr/bin/python3"),
                "3.4.2",
                check_script,
                2,
                timestamp="20260715T120000.000000Z-fixed",
                base_env={"PATH": "/test/bin"},
                runner=self._runner(paths, calls),
                disk_usage=lambda _path: SimpleNamespace(free=100 * 1024**3),
            )

            self.assertEqual(paths, result)
            self.assertEqual("new", (paths.active / "new-marker").read_text(encoding="utf-8"))
            self.assertEqual("old", (paths.backup / "old-marker").read_text(encoding="utf-8"))
            self.assertTrue((paths.active / "mineru-venv-manifest.json").is_file())
            self.assertFalse(paths.active.with_name(f"{paths.active.name}.bak-001").exists())
            self.assertFalse(paths.active.with_name(f"{paths.active.name}.bak-002").exists())
            self.assertTrue(paths.active.with_name(f"{paths.active.name}.bak-003").is_dir())
            active_readiness_index = next(
                index
                for index, (command, _kwargs) in enumerate(calls)
                if command[0] == str(paths.active / "bin" / "python")
            )
            staging_freeze_index = next(
                index
                for index, (command, _kwargs) in enumerate(calls)
                if command[-3:] == ["pip", "freeze", "--all"]
            )
            self.assertGreater(active_readiness_index, staging_freeze_index)
            for command, kwargs in calls:
                self.assertIsInstance(command, list)
                self.assertIs(kwargs["check"], True)
                self.assertIn("env", kwargs)
                self.assertNotIn("shell", kwargs)

    def test_build_failure_preserves_partial_staging_and_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths, check_script = self._setup(root)
            calls: list[tuple[list[str], dict[str, object]]] = []

            with self.assertRaises(subprocess.CalledProcessError):
                rebuild_mineru_venv.rebuild_venv(
                    paths.active,
                    Path("/usr/bin/python3"),
                    "3.4.2",
                    check_script,
                    2,
                    timestamp="20260715T120000.000000Z-fixed",
                    base_env={},
                    runner=self._runner(paths, calls, fail_install=True),
                    disk_usage=lambda _path: SimpleNamespace(free=100 * 1024**3),
                )

            self.assertEqual("old", (paths.active / "old-marker").read_text(encoding="utf-8"))
            self.assertEqual("new", (paths.staging / "new-marker").read_text(encoding="utf-8"))
            self.assertFalse(paths.backup.exists())
            with rebuild_mineru_venv.rebuild_lock(paths.active):
                pass

    def test_post_activation_failure_preserves_failed_new_and_restores_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths, check_script = self._setup(root)
            older_backups = [paths.active.with_name(f"{paths.active.name}.bak-{stamp}") for stamp in ("001", "002", "003")]
            for backup in older_backups:
                backup.mkdir()
            calls: list[tuple[list[str], dict[str, object]]] = []
            prune = mock.Mock()

            with self.assertRaises(subprocess.CalledProcessError):
                rebuild_mineru_venv.rebuild_venv(
                    paths.active,
                    Path("/usr/bin/python3"),
                    "3.4.2",
                    check_script,
                    2,
                    timestamp="20260715T120000.000000Z-fixed",
                    base_env={},
                    runner=self._runner(paths, calls, fail_active_readiness=True),
                    disk_usage=lambda _path: SimpleNamespace(free=100 * 1024**3),
                    prune=prune,
                )

            self.assertEqual("old", (paths.active / "old-marker").read_text(encoding="utf-8"))
            self.assertEqual("new", (paths.staging / "new-marker").read_text(encoding="utf-8"))
            self.assertFalse(paths.backup.exists())
            self.assertTrue(all(path.is_dir() for path in older_backups))
            prune.assert_not_called()

    def test_post_activation_failure_without_old_active_leaves_no_broken_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths, check_script = self._setup(root, with_active=False)
            calls: list[tuple[list[str], dict[str, object]]] = []

            with self.assertRaises(subprocess.CalledProcessError):
                rebuild_mineru_venv.rebuild_venv(
                    paths.active,
                    Path("/usr/bin/python3"),
                    "3.4.2",
                    check_script,
                    2,
                    timestamp="20260715T120000.000000Z-fixed",
                    base_env={},
                    runner=self._runner(paths, calls, fail_active_readiness=True),
                    disk_usage=lambda _path: SimpleNamespace(free=100 * 1024**3),
                )

            self.assertFalse(paths.active.exists())
            self.assertEqual("new", (paths.staging / "new-marker").read_text(encoding="utf-8"))
            self.assertFalse(paths.backup.exists())

    def test_cli_defaults_match_server_contract(self) -> None:
        args = rebuild_mineru_venv.parse_args(
            [
                "--target",
                "/srv/vendor/mineru-venv",
                "--python",
                "/usr/bin/python3",
                "--check-script",
                "/srv/scripts/check_mineru.py",
            ]
        )

        self.assertEqual(Path("/srv/vendor/mineru-venv"), args.target)
        self.assertEqual(Path("/usr/bin/python3"), args.python)
        self.assertEqual("3.4.2", args.mineru_version)
        self.assertEqual(Path("/srv/scripts/check_mineru.py"), args.check_script)
        self.assertEqual(2, args.keep_backups)


class InstallMineruShellTest(unittest.TestCase):
    def test_server_target_delegates_with_exact_arguments_before_local_install(self) -> None:
        script = Path(__file__).with_name("install_mineru.sh")
        root = script.resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            fake_bin = temp_root / "bin"
            fake_bin.mkdir()
            argument_log = temp_root / "args.txt"
            fake_python = fake_bin / "python3"
            fake_python.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$@\" > \"$ARGUMENT_LOG\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            fake_uv = fake_bin / "uv"
            fake_uv.write_text("#!/usr/bin/env bash\nexit 97\n", encoding="utf-8")
            fake_uv.chmod(0o755)
            target = temp_root / "server" / "vendor" / "mineru-venv"
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{fake_bin}:{env['PATH']}",
                    "ARGUMENT_LOG": str(argument_log),
                    "MINERU_VENV_TARGET": str(target),
                    "MINERU_PYTHON": "/usr/bin/python3.10",
                    "MINERU_VERSION": "3.4.2",
                    "MINERU_KEEP_BACKUPS": "4",
                    "MINERU_WHEELHOUSE": "/must/not/be-used/on-server",
                }
            )

            completed = subprocess.run(
                ["bash", str(script)],
                env=env,
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual(
                [
                    str(root / "scripts" / "rebuild_mineru_venv.py"),
                    "--target",
                    str(target),
                    "--python",
                    "/usr/bin/python3.10",
                    "--mineru-version",
                    "3.4.2",
                    "--check-script",
                    str(root / "scripts" / "check_mineru.py"),
                    "--keep-backups",
                    "4",
                ],
                argument_log.read_text(encoding="utf-8").splitlines(),
            )
            self.assertNotIn("wheelhouse", completed.stdout.lower())
            self.assertNotIn("wheelhouse", completed.stderr.lower())

    def test_local_branch_retains_existing_wheelhouse_behavior(self) -> None:
        shell = Path(__file__).with_name("install_mineru.sh").read_text(encoding="utf-8")

        self.assertIn("backend/python-worker/.venv", shell)
        self.assertIn("MINERU_WHEELHOUSE", shell)
        self.assertIn("--no-index", shell)
        self.assertIn("--find-links", shell)


class ServerRunbookTest(unittest.TestCase):
    def test_rebuild_and_rollback_stop_before_switch_and_restart_after_readiness(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runbook = (root / "docs" / "server" / "RUNBOOK.md").read_text(encoding="utf-8")
        rebuild_heading = "## 原子重建 MinerU venv"
        rollback_heading = "## 回滚 MinerU venv"
        self.assertIn(rebuild_heading, runbook)
        self.assertIn(rollback_heading, runbook)
        rebuild_section = runbook.split(rebuild_heading, 1)[1].split(rollback_heading, 1)[0]
        rollback_section = runbook.split(rollback_heading, 1)[1]
        rebuild_command = """python3 scripts/rebuild_mineru_venv.py \\
  --target /home/user/AI_GENERATION_DOCKER/vendor/mineru-venv \\
  --python /usr/bin/python3 \\
  --mineru-version 3.4.2 \\
  --check-script /home/user/AI_GENERATION_DOCKER/scripts/check_mineru.py \\
  --keep-backups 2"""
        readiness_command = """MINERU_COMMAND=/home/user/AI_GENERATION_DOCKER/vendor/mineru-venv/bin/mineru \\
MINERU_API_ENABLED=false \\
CHECK_MINERU_IN_WORKER_VENV=1 \\
  /home/user/AI_GENERATION_DOCKER/vendor/mineru-venv/bin/python \\
  /home/user/AI_GENERATION_DOCKER/scripts/check_mineru.py --json --skip-api"""
        stop_command = "sudo docker compose -f docker-compose.server.yml stop question-engine"
        start_command = "sudo docker compose -f docker-compose.server.yml up -d question-engine"

        self.assertIn(rebuild_command, rebuild_section)
        self.assertIn(readiness_command, rebuild_section)
        self.assertLess(rebuild_section.index(stop_command), rebuild_section.index(rebuild_command))
        self.assertLess(rebuild_section.index(rebuild_command), rebuild_section.index(readiness_command))
        self.assertLess(rebuild_section.index(readiness_command), rebuild_section.index(start_command))
        self.assertIn("vendor/mineru-venv/bin/mineru --version", rebuild_section)

        self.assertIn('backup="/home/user/AI_GENERATION_DOCKER/vendor/mineru-venv.bak-', rollback_section)
        self.assertIn('mv vendor/mineru-venv "vendor/mineru-venv.failed-${stamp}"', rollback_section)
        self.assertIn('mv "$backup" vendor/mineru-venv', rollback_section)
        self.assertIn(readiness_command, rollback_section)
        self.assertLess(rollback_section.index(stop_command), rollback_section.index("mv vendor/mineru-venv"))
        self.assertLess(rollback_section.index(readiness_command), rollback_section.index(start_command))
        self.assertIn("vendor/mineru-venv/bin/mineru --version", rollback_section)


if __name__ == "__main__":
    unittest.main()
