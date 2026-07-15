#!/usr/bin/env python3
"""Regression tests for atomic MinerU virtualenv rebuilds."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
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
                    "--isolated",
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
                    "--isolated",
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


class CrashRecoveryJournalTest(unittest.TestCase):
    def _paths(self, root: Path, *, with_active: bool = True) -> rebuild_mineru_venv.BuildPaths:
        paths = rebuild_mineru_venv.build_paths(
            root / "vendor" / "mineru-venv",
            "20260715T120000.000000Z-fixed",
        )
        paths.active.parent.mkdir()
        if with_active:
            paths.active.mkdir()
            (paths.active / "old-marker").write_text("old", encoding="utf-8")
        paths.staging.mkdir()
        (paths.staging / "new-marker").write_text("new", encoding="utf-8")
        return paths

    def _journal(
        self,
        paths: rebuild_mineru_venv.BuildPaths,
        phase: str,
        *,
        had_active: bool,
    ) -> Path:
        return rebuild_mineru_venv.write_transaction_journal(
            paths,
            phase,
            had_active=had_active,
        )

    def _assert_old_active_and_new_staging(self, paths: rebuild_mineru_venv.BuildPaths) -> None:
        self.assertEqual("old", (paths.active / "old-marker").read_text(encoding="utf-8"))
        self.assertEqual("new", (paths.staging / "new-marker").read_text(encoding="utf-8"))
        self.assertFalse(paths.backup.exists())
        self.assertFalse(rebuild_mineru_venv.transaction_journal_path(paths.active).exists())

    def test_journal_write_is_atomic_and_fsyncs_file_and_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))

            with mock.patch.object(os, "fsync", wraps=os.fsync) as fsync:
                journal = self._journal(paths, "prepared", had_active=True)

            payload = json.loads(journal.read_text(encoding="utf-8"))
            self.assertEqual(str(paths.active), payload["active"])
            self.assertEqual(str(paths.staging), payload["staging"])
            self.assertEqual(str(paths.backup), payload["backup"])
            self.assertEqual("prepared", payload["phase"])
            self.assertTrue(payload["hadActive"])
            self.assertGreaterEqual(fsync.call_count, 2)
            self.assertEqual([], list(journal.parent.glob(f"{journal.name}.tmp-*")))
            self.assertNotIn("env", payload)
            self.assertNotIn("secret", journal.read_text(encoding="utf-8").lower())

    def test_rename_and_sync_fsyncs_parent_after_rename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            synced: list[Path] = []

            rebuild_mineru_venv.rename_and_sync(
                source,
                target,
                sync_directory=synced.append,
            )

            self.assertTrue(target.is_dir())
            self.assertEqual([root], synced)

    def test_recovery_before_first_rename_keeps_old_active_and_staging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            self._journal(paths, "prepared", had_active=True)

            rebuild_mineru_venv.recover_transaction(paths.active)

            self._assert_old_active_and_new_staging(paths)

    def test_recovery_after_active_to_backup_restores_old_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            self._journal(paths, "prepared", had_active=True)
            paths.active.rename(paths.backup)

            rebuild_mineru_venv.recover_transaction(paths.active)

            self._assert_old_active_and_new_staging(paths)

    def test_recovery_after_staging_to_active_rolls_back_unverified_new(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            self._journal(paths, "active_moved", had_active=True)
            paths.active.rename(paths.backup)
            paths.staging.rename(paths.active)

            rebuild_mineru_venv.recover_transaction(paths.active)

            self._assert_old_active_and_new_staging(paths)

    def test_recovery_without_old_active_never_leaves_unverified_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp), with_active=False)
            self._journal(paths, "active_moved", had_active=False)
            paths.staging.rename(paths.active)

            rebuild_mineru_venv.recover_transaction(paths.active)

            self.assertFalse(paths.active.exists())
            self.assertEqual("new", (paths.staging / "new-marker").read_text(encoding="utf-8"))
            self.assertFalse(rebuild_mineru_venv.transaction_journal_path(paths.active).exists())

    def test_recovery_resumes_either_interrupted_rollback_rename(self) -> None:
        for interruption in ("new_saved", "old_restored"):
            with self.subTest(interruption=interruption), tempfile.TemporaryDirectory() as tmp:
                paths = self._paths(Path(tmp))
                self._journal(paths, "rollback_started", had_active=True)
                paths.active.rename(paths.backup)
                paths.staging.rename(paths.active)
                paths.active.rename(paths.staging)
                if interruption == "old_restored":
                    paths.backup.rename(paths.active)

                rebuild_mineru_venv.recover_transaction(paths.active)

                self._assert_old_active_and_new_staging(paths)

    def test_recovery_after_active_verified_but_before_journal_clear_prefers_old_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            self._journal(paths, "active_verified", had_active=True)
            paths.active.rename(paths.backup)
            paths.staging.rename(paths.active)

            rebuild_mineru_venv.recover_transaction(paths.active)

            self._assert_old_active_and_new_staging(paths)

    def test_recovery_rejects_outside_or_symlink_journal_paths(self) -> None:
        for attack in ("outside", "symlink"):
            with self.subTest(attack=attack), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                paths = self._paths(root)
                staging = paths.staging
                if attack == "outside":
                    staging = root / "outside" / paths.staging.name
                else:
                    (paths.staging / "new-marker").unlink()
                    paths.staging.rmdir()
                    outside = root / "outside"
                    outside.mkdir()
                    paths.staging.symlink_to(outside, target_is_directory=True)
                payload = {
                    "schemaVersion": 1,
                    "active": str(paths.active),
                    "staging": str(staging),
                    "backup": str(paths.backup),
                    "phase": "prepared",
                    "hadActive": True,
                }
                journal = rebuild_mineru_venv.transaction_journal_path(paths.active)
                journal.write_text(json.dumps(payload), encoding="utf-8")

                with self.assertRaisesRegex(ValueError, "journal"):
                    rebuild_mineru_venv.recover_transaction(paths.active)

                self.assertEqual("old", (paths.active / "old-marker").read_text(encoding="utf-8"))
                self.assertTrue(journal.exists())


class RebuildSafetyTest(unittest.TestCase):
    def _request_paths(self, root: Path) -> tuple[rebuild_mineru_venv.BuildPaths, Path]:
        root = root.resolve()
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

    def test_request_rejects_any_target_parent_symlink_component(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            real = root / "real"
            (real / "vendor").mkdir(parents=True)
            linked = root / "linked"
            linked.symlink_to(real, target_is_directory=True)
            check_script = root / "scripts" / "check_mineru.py"
            check_script.parent.mkdir()
            check_script.write_text("# check\n", encoding="utf-8")
            paths = rebuild_mineru_venv.build_paths(linked / "vendor" / "mineru-venv", "fixed")

            with self.assertRaisesRegex(ValueError, "parent.*symlink"):
                rebuild_mineru_venv.validate_request(paths, check_script, 2)

    def test_request_accepts_normal_absolute_parent_chain_and_rejects_symlink_check_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            paths, check_script = self._request_paths(root)
            paths.active.parent.mkdir()

            rebuild_mineru_venv.validate_request(paths, check_script, 2)

            real_check = root / "scripts" / "real_check.py"
            real_check.write_text("# real\n", encoding="utf-8")
            check_script.unlink()
            check_script.symlink_to(real_check)
            with self.assertRaisesRegex(ValueError, "check-script.*symlink"):
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

    def test_prune_failed_staging_is_bounded_and_never_touches_unrelated_or_symlink_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp).resolve() / "vendor" / "mineru-venv"
            target.parent.mkdir()
            target.mkdir()
            failures = [
                target.with_name(f"{target.name}.new-2026071{day}T120000.000000Z-{token}")
                for day, token in ((3, "aaaaaaaa"), (4, "bbbbbbbb"), (5, "cccccccc"))
            ]
            for failure in failures:
                failure.mkdir()
            for failure, modified in zip(failures, (300, 100, 200), strict=True):
                os.utime(failure, ns=(modified, modified))
            unrelated_new = target.with_name(f"{target.name}.new-manual-do-not-delete")
            unrelated_new.mkdir()
            matching_file = target.with_name(f"{target.name}.new-20260711T120000.000000Z-ffffffff")
            matching_file.write_text("not a directory", encoding="utf-8")
            backup = target.with_name(f"{target.name}.bak-20260715T120000.000000Z-dddddddd")
            backup.mkdir()
            journal = rebuild_mineru_venv.transaction_journal_path(target)
            journal.write_text("{}", encoding="utf-8")
            symlink_failure = target.with_name(f"{target.name}.new-20260712T120000.000000Z-eeeeeeee")
            symlink_failure.symlink_to(target, target_is_directory=True)

            removed = rebuild_mineru_venv.prune_failed_staging(target, keep_failed_staging=2)

            self.assertEqual([failures[1]], removed)
            self.assertTrue(failures[0].is_dir())
            self.assertFalse(failures[1].exists())
            self.assertTrue(failures[2].is_dir())
            self.assertTrue(unrelated_new.is_dir())
            self.assertTrue(matching_file.is_file())
            self.assertTrue(backup.is_dir())
            self.assertTrue(journal.is_file())
            self.assertTrue(symlink_failure.is_symlink())
            self.assertTrue(target.is_dir())

    def test_prune_failed_staging_zero_removes_all_matching_old_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp).resolve() / "vendor" / "mineru-venv"
            target.parent.mkdir()
            failures = [
                target.with_name(f"{target.name}.new-2026071{day}T120000.000000Z-{token}")
                for day, token in ((3, "aaaaaaaa"), (4, "bbbbbbbb"))
            ]
            for failure in failures:
                failure.mkdir()

            removed = rebuild_mineru_venv.prune_failed_staging(target, keep_failed_staging=0)

            self.assertEqual(failures, removed)
            self.assertTrue(all(not failure.exists() for failure in failures))

            with self.assertRaisesRegex(ValueError, "keep-failed-staging"):
                rebuild_mineru_venv.prune_failed_staging(target, keep_failed_staging=-1)


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
            activation_text_files = [
                bin_dir / name
                for name in (
                    "activate",
                    "activate.csh",
                    "activate.fish",
                    "Activate.ps1",
                    "activate.bat",
                    "activate_this.py",
                )
            ]
            for activation_file in activation_text_files:
                activation_file.write_text(f"VIRTUAL_ENV={paths.staging}\n", encoding="utf-8")
            binary = bin_dir / "binary-tool"
            binary.write_bytes(b"\x00\xff" + os.fsencode(paths.staging))
            binary.chmod(0o755)
            binary_activation = bin_dir / "activate.xsh"
            binary_activation.write_bytes(b"\xff" + os.fsencode(paths.staging))
            symlink_target = root / "outside-entrypoint"
            self._write_entrypoint(symlink_target, staging_python)
            (bin_dir / "linked-tool").symlink_to(symlink_target)
            symlink_activation_target = root / "outside-activate"
            symlink_activation_target.write_text(f"VIRTUAL_ENV={paths.staging}\n", encoding="utf-8")
            (bin_dir / "activate.nu").symlink_to(symlink_activation_target)
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
                *activation_text_files,
            }
            self.assertEqual(expected_rewritten, set(rewritten))
            for name in ("mineru", "mineru-api", "other-tool"):
                self.assertEqual(f"#!{active_python}", (bin_dir / name).read_text(encoding="utf-8").splitlines()[0])
            self.assertIn(str(paths.active), pyvenv_cfg.read_text(encoding="utf-8"))
            self.assertIn(str(paths.active), pth.read_text(encoding="utf-8"))
            self.assertIn(str(paths.active), egg_link.read_text(encoding="utf-8"))
            for activation_file in activation_text_files:
                activation_text = activation_file.read_text(encoding="utf-8")
                self.assertIn(str(paths.active), activation_text)
                self.assertNotIn(str(paths.staging), activation_text)
            self.assertEqual(f"#!{staging_python}\n", non_executable.read_text(encoding="utf-8"))
            self.assertEqual(b"\x00\xff" + os.fsencode(paths.staging), binary.read_bytes())
            self.assertEqual(b"\xff" + os.fsencode(paths.staging), binary_activation.read_bytes())
            self.assertEqual(f"#!{staging_python}\nprint('ok')\n", symlink_target.read_text(encoding="utf-8"))
            self.assertEqual(
                f"VIRTUAL_ENV={paths.staging}\n",
                symlink_activation_target.read_text(encoding="utf-8"),
            )
            self.assertEqual(b"\xff" + os.fsencode(paths.staging), binary_pth.read_bytes())

    def test_relocation_assertion_rejects_known_activation_and_config_text_residuals(self) -> None:
        relative_candidates = (
            Path("bin/activate"),
            Path("bin/activate.csh"),
            Path("bin/activate.fish"),
            Path("bin/Activate.ps1"),
            Path("bin/activate.bat"),
            Path("bin/activate.nu"),
            Path("bin/activate.xsh"),
            Path("bin/activate_this.py"),
            Path("pyvenv.cfg"),
            Path("lib/python3.12/site-packages/editable.pth"),
            Path("lib/python3.12/site-packages/editable.egg-link"),
        )
        for relative in relative_candidates:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as tmp:
                paths = rebuild_mineru_venv.build_paths(Path(tmp) / "vendor" / "mineru-venv", "fixed")
                bin_dir = paths.staging / "bin"
                bin_dir.mkdir(parents=True)
                active_python = paths.active / "bin" / "python"
                self._write_entrypoint(bin_dir / "mineru", active_python)
                self._write_entrypoint(bin_dir / "mineru-api", active_python)
                candidate = paths.staging / relative
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_text(f"reference={paths.staging}\n", encoding="utf-8")

                with self.assertRaisesRegex(RuntimeError, "activation/config"):
                    rebuild_mineru_venv.assert_relocated(paths.staging, paths.active)

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
            activation_names = (
                "activate",
                "activate.csh",
                "activate.fish",
                "Activate.ps1",
                "activate.bat",
                "activate.nu",
                "activate.xsh",
                "activate_this.py",
            )
            for name in activation_names:
                activation_file = paths.staging / "bin" / name
                if activation_file.is_file() and not activation_file.is_symlink():
                    activation_text = activation_file.read_text(encoding="utf-8")
                    self.assertNotIn(str(paths.staging), activation_text)
            rebuild_mineru_venv.activate(paths)

            activation_probe = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1/bin/activate"\n'
                    'printf "%s\\n" "$VIRTUAL_ENV"\n'
                    "command -v python\n"
                    "python -c 'import sys; print(sys.prefix)'\n",
                    "bash",
                    str(paths.active),
                ],
                check=True,
                env=os.environ.copy(),
                capture_output=True,
                text=True,
            )
            virtual_env, resolved_python, activated_prefix = activation_probe.stdout.splitlines()
            self.assertEqual(str(paths.active), virtual_env)
            self.assertEqual(str(paths.active / "bin" / "python"), resolved_python)
            self.assertEqual(paths.active.resolve(), Path(activated_prefix).resolve())

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
        elif command[1:3] == ["-I", "-c"]:
            venv = Path(command[0]).parent.parent
            stdout = json.dumps(
                {
                    "mineruVersion": "3.4.2",
                    "markupSafeVersion": "3.0.3",
                    "pythonVersion": "3.12.0",
                    "pythonExecutable": str(venv / "bin" / "python"),
                    "pythonPrefix": str(venv),
                    "modulePaths": {
                        name: str(venv / "lib" / "python3.12" / "site-packages" / filename)
                        for name, filename in {
                            "markupsafe": "markupsafe/__init__.py",
                            "jinja2": "jinja2/__init__.py",
                            "transformers": "transformers/__init__.py",
                            "mineru": "mineru/__init__.py",
                            "mineru.cli.common": "mineru/cli/common.py",
                        }.items()
                    },
                },
                sort_keys=True,
            ) + "\n"
        elif command[-1:] == ["--version"]:
            stdout = "mineru, version 3.4.2\n"
        elif command[-3:] == ["pip", "freeze", "--all"]:
            stdout = "MarkupSafe==3.0.3\nmineru==3.4.2\n"
        else:
            stdout = ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    @staticmethod
    def _valid_manifest_payload(active: Path) -> dict[str, object]:
        packages = [
            {"name": "markupsafe", "version": "3.0.3"},
            {"name": "mineru", "version": "3.4.2"},
        ]
        canonical = json.dumps(packages, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n"
        return {
            "manifestVersion": 2,
            "targetMineruVersion": "3.4.2",
            "packages": packages,
            "packageListSha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "python": {
                "version": "3.12.0",
                "executable": str(active / "bin" / "python"),
            },
            "validation": {
                "validatedAt": "2026-07-16T00:00:00.000000Z",
                "readiness": True,
                "runtimeImports": True,
                "metadataVersions": True,
                "versionCommand": True,
                "mineruVersion": "3.4.2",
                "markupSafeVersion": "3.0.3",
            },
        }

    @classmethod
    def _write_valid_manifest(cls, active: Path) -> Path:
        cls._write_executables(active)
        manifest = active / "mineru-venv-manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps(cls._valid_manifest_payload(active), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return manifest

    @staticmethod
    def _write_executables(venv: Path) -> None:
        bin_dir = venv / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        for name in ("python", "mineru", "mineru-api"):
            path = bin_dir / name
            path.write_text("#!/bin/sh\n", encoding="utf-8")
            path.chmod(0o755)

    def test_install_and_validation_runners_have_distinct_bounded_io_contracts(self) -> None:
        install_runner = mock.Mock(return_value=subprocess.CompletedProcess(["pip"], 0))
        validation_runner = mock.Mock(
            return_value=subprocess.CompletedProcess(["check"], 0, stdout="ok", stderr="")
        )
        env = {"PATH": "/test/bin"}

        rebuild_mineru_venv._run_install(["python", "-m", "venv", "/tmp/staging"], env, 3600, install_runner)
        rebuild_mineru_venv._run_validation(["python", "-I", "check.py"], env, 300, validation_runner)

        install_runner.assert_called_once_with(
            ["python", "-m", "venv", "/tmp/staging"],
            check=True,
            env=env,
            timeout=3600,
        )
        validation_runner.assert_called_once_with(
            ["python", "-I", "check.py"],
            check=True,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )

    def test_environment_sanitization_removes_pip_and_python_injection(self) -> None:
        polluted = {
            "PATH": "/test/bin",
            "UNRELATED": "kept",
            "PIP_NO_INDEX": "1",
            "PIP_FIND_LINKS": "/mac-wheelhouse",
            "PIP_CONFIG_FILE": "/tmp/offline-pip.conf",
            "PIP_INDEX_URL": "file:///private/index",
            "PYTHONPATH": "/tmp/fake-modules",
            "PYTHONHOME": "/tmp/fake-home",
            "VIRTUAL_ENV": "/tmp/wrong-venv",
            "__PYVENV_LAUNCHER__": "/tmp/wrong-python",
        }

        clean = rebuild_mineru_venv.sanitized_environment(polluted)

        self.assertEqual("/test/bin", clean["PATH"])
        self.assertEqual("kept", clean["UNRELATED"])
        for key in polluted.keys() - {"PATH", "UNRELATED"}:
            self.assertNotIn(key, clean)

    def test_real_probe_requires_modules_from_target_venv_and_exact_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / "venv"
            subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, env=os.environ.copy())
            python = venv / "bin" / "python"
            purelib = Path(
                subprocess.run(
                    [str(python), "-I", "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                    check=True,
                    capture_output=True,
                    text=True,
                    env=os.environ.copy(),
                ).stdout.strip()
            )
            (purelib / "markupsafe.py").write_text("class Markup: pass\n", encoding="utf-8")
            (purelib / "jinja2.py").write_text("class Environment: pass\n", encoding="utf-8")
            (purelib / "transformers.py").write_text("VALUE = True\n", encoding="utf-8")
            common = purelib / "mineru" / "cli" / "common.py"
            common.parent.mkdir(parents=True)
            (purelib / "mineru" / "__init__.py").write_text("", encoding="utf-8")
            (purelib / "mineru" / "cli" / "__init__.py").write_text("", encoding="utf-8")
            common.write_text("def read_fn(): pass\n", encoding="utf-8")
            for distribution, version in (("mineru", "3.4.2"), ("MarkupSafe", "3.0.3")):
                metadata = purelib / f"{distribution}-{version}.dist-info" / "METADATA"
                metadata.parent.mkdir()
                metadata.write_text(
                    f"Metadata-Version: 2.1\nName: {distribution}\nVersion: {version}\n",
                    encoding="utf-8",
                )

            completed = subprocess.run(
                [
                    str(python),
                    "-I",
                    "-c",
                    rebuild_mineru_venv.build_runtime_import_probe(venv, "3.4.2"),
                ],
                check=True,
                capture_output=True,
                text=True,
                env=os.environ.copy(),
            )
            payload = json.loads(completed.stdout)

            self.assertEqual("3.4.2", payload["mineruVersion"])
            self.assertEqual("3.0.3", payload["markupSafeVersion"])
            for module_path in payload["modulePaths"].values():
                Path(module_path).resolve().relative_to(venv.resolve())

    def test_external_pythonpath_fake_modules_cannot_satisfy_staging_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            venv = root / "venv"
            subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, env=os.environ.copy())
            fake = root / "fake"
            fake.mkdir()
            (fake / "markupsafe.py").write_text("class Markup: pass\n", encoding="utf-8")
            (fake / "jinja2.py").write_text("class Environment: pass\n", encoding="utf-8")
            (fake / "transformers.py").write_text("VALUE = True\n", encoding="utf-8")
            common = fake / "mineru" / "cli" / "common.py"
            common.parent.mkdir(parents=True)
            (fake / "mineru" / "__init__.py").write_text("", encoding="utf-8")
            (fake / "mineru" / "cli" / "__init__.py").write_text("", encoding="utf-8")
            common.write_text("def read_fn(): pass\n", encoding="utf-8")
            check_script = root / "check.py"
            check_script.write_text(
                "print('{\"installed\":true,\"runtimeProbeOk\":true}')\n",
                encoding="utf-8",
            )
            for name in ("mineru", "mineru-api"):
                executable = venv / "bin" / name
                executable.write_text("#!/bin/sh\n", encoding="utf-8")
                executable.chmod(0o755)

            with self.assertRaises(subprocess.CalledProcessError) as raised:
                rebuild_mineru_venv.validate_staging(
                    venv,
                    check_script,
                    "3.4.2",
                    base_env={"PATH": os.environ["PATH"], "PYTHONPATH": str(fake)},
                    runner=subprocess.run,
                )

            self.assertEqual([str(venv / "bin" / "python"), "-I", "-c"], raised.exception.cmd[:3])

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

    def test_version_parser_accepts_one_exact_line_with_unrelated_warnings(self) -> None:
        completed = subprocess.CompletedProcess(
            ["mineru", "--version"],
            0,
            stdout="startup warning\n  MiNeRu  ,  VERSION   3.4.2  \ncache warning\n",
            stderr="optional dependency warning\n",
        )

        rebuild_mineru_venv._require_version(completed, "3.4.2")

    def test_version_parser_rejects_nonexact_missing_and_ambiguous_output(self) -> None:
        invalid_outputs = {
            "prerelease": ("mineru, version 3.4.2rc1\n", ""),
            "postrelease": ("mineru, version 3.4.2.post1\n", ""),
            "warning_mentions_expected": (
                "warning: expected 3.4.2\nmineru, version 3.4.1\n",
                "",
            ),
            "missing_line_mentions_expected": ("installed MinerU package 3.4.2\n", ""),
            "missing_line": ("MinerU version is unavailable\n", ""),
            "malformed_line": ("mineru, version 3.4.2 extra\n", ""),
            "duplicate_lines": (
                "mineru, version 3.4.2\nmineru, version 3.4.2\n",
                "",
            ),
            "conflicting_lines": (
                "mineru, version 3.4.2\n",
                "mineru, version 3.4.1\n",
            ),
        }
        for name, (stdout, stderr) in invalid_outputs.items():
            with self.subTest(name=name):
                completed = subprocess.CompletedProcess(
                    ["mineru", "--version"],
                    0,
                    stdout=stdout,
                    stderr=stderr,
                )

                with self.assertRaises(RuntimeError):
                    rebuild_mineru_venv._require_version(completed, "3.4.2")

    def test_staging_validation_uses_exact_commands_and_explicit_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / "mineru-venv.new-fixed"
            active = Path(tmp) / "mineru-venv"
            venv.mkdir()
            bin_dir = venv / "bin"
            bin_dir.mkdir()
            for name in ("python", "mineru", "mineru-api"):
                executable = bin_dir / name
                executable.write_text("#!/bin/sh\n", encoding="utf-8")
                executable.chmod(0o755)
            check_script = Path(tmp) / "scripts" / "check_mineru.py"
            check_script.parent.mkdir()
            check_script.write_text("# check\n", encoding="utf-8")

            manifest = rebuild_mineru_venv.validate_staging(
                venv,
                check_script,
                "3.4.2",
                base_env={"PATH": "/test/bin", "UNRELATED": "kept"},
                active_venv=active,
                runner=self._runner,
            )

            python = str(venv / "bin" / "python")
            mineru = str(venv / "bin" / "mineru")
            self.assertEqual(
                [
                    [python, "-I", str(check_script), "--json", "--skip-api"],
                    [python, "-I", "-c", rebuild_mineru_venv.build_runtime_import_probe(venv, "3.4.2")],
                    [mineru, "--version"],
                    [python, "-I", "-m", "pip", "freeze", "--all"],
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
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(str(active / "bin" / "python"), payload["python"]["executable"])
            self.assertNotIn(str(venv), manifest.read_text(encoding="utf-8"))

    def test_manifest_hashes_package_list_without_recording_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp)
            active = venv / "active"
            active.mkdir()
            package_list = "Zed_Pkg==2\nsafe==1\nprivate @ https://user:secret-token@example.invalid/pkg.whl\n"
            runtime = {
                "mineruVersion": "3.4.2",
                "markupSafeVersion": "3.0.3",
                "pythonVersion": "3.12.0",
            }

            manifest_path = rebuild_mineru_venv.write_manifest(
                venv,
                "3.4.2",
                package_list,
                active_venv=active,
                readiness={"installed": True, "runtimeProbeOk": True},
                runtime=runtime,
                validated_at="2026-07-16T00:00:00.000000Z",
            )
            manifest_text = manifest_path.read_text(encoding="utf-8")
            payload = json.loads(manifest_text)

            self.assertEqual("3.4.2", payload["targetMineruVersion"])
            self.assertEqual(
                [
                    {"name": "private", "version": "<direct-reference>"},
                    {"name": "safe", "version": "1"},
                    {"name": "zed-pkg", "version": "2"},
                ],
                payload["packages"],
            )
            canonical = json.dumps(
                payload["packages"], ensure_ascii=True, separators=(",", ":"), sort_keys=True
            ) + "\n"
            self.assertEqual(hashlib.sha256(canonical.encode("utf-8")).hexdigest(), payload["packageListSha256"])
            self.assertEqual("3.12.0", payload["python"]["version"])
            self.assertEqual(str(active / "bin" / "python"), payload["python"]["executable"])
            self.assertEqual("2026-07-16T00:00:00.000000Z", payload["validation"]["validatedAt"])
            self.assertTrue(payload["validation"]["readiness"])
            self.assertNotIn("secret-token", manifest_text)
            self.assertNotIn("https://", manifest_text)
            self.assertNotIn("environment", manifest_text.lower())

    def test_staging_validation_rejects_unexpected_mineru_version(self) -> None:
        def wrong_version(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            completed = self._runner(command, **kwargs)
            if command[-1:] == ["--version"]:
                return subprocess.CompletedProcess(command, 0, stdout="mineru, version 3.4.1\n", stderr="")
            return completed

        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / "staging"
            venv.mkdir()
            self._write_executables(venv)
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
            self._write_valid_manifest(active)

            rebuild_mineru_venv.validate_active(
                active,
                check_script,
                "3.4.2",
                base_env={"PATH": "/test/bin"},
                runner=self._runner,
            )

            self.assertEqual(
                [
                    [str(active / "bin" / "python"), "-I", str(check_script), "--json", "--skip-api"],
                    [
                        str(active / "bin" / "python"),
                        "-I",
                        "-c",
                        rebuild_mineru_venv.build_runtime_import_probe(active, "3.4.2"),
                    ],
                    [str(active / "bin" / "mineru"), "--version"],
                    [str(active / "bin" / "python"), "-I", "-m", "pip", "freeze", "--all"],
                ],
                [command for command, _kwargs in self.calls],
            )
            for _command, kwargs in self.calls:
                env = kwargs["env"]
                self.assertEqual(str(active / "bin" / "mineru"), env["MINERU_COMMAND"])
                self.assertEqual("false", env["MINERU_API_ENABLED"])
                self.assertEqual("1", env["CHECK_MINERU_IN_WORKER_VENV"])

    def test_active_validation_rejects_missing_or_tampered_manifest(self) -> None:
        mutations = {
            "missing": None,
            "target-version": ("targetMineruVersion", "3.4.1"),
            "package-hash": ("packageListSha256", "0" * 64),
            "staging-executable": ("python.executable", "/srv/mineru-venv.new-old/bin/python"),
            "validation-fact": ("validation.runtimeImports", False),
            "validation-time": ("validation.validatedAt", "garbageZ"),
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                active = Path(tmp) / "mineru-venv"
                active.mkdir()
                self._write_executables(active)
                check_script = Path(tmp) / "check.py"
                if mutation is not None:
                    payload = self._valid_manifest_payload(active)
                    dotted, value = mutation
                    container: dict[str, object] = payload
                    parts = dotted.split(".")
                    for part in parts[:-1]:
                        container = container[part]  # type: ignore[assignment]
                    container[parts[-1]] = value
                    (active / "mineru-venv-manifest.json").write_text(
                        json.dumps(payload),
                        encoding="utf-8",
                    )

                with self.assertRaisesRegex(RuntimeError, "manifest"):
                    rebuild_mineru_venv.validate_active(
                        active,
                        check_script,
                        "3.4.2",
                        base_env={"PATH": "/test/bin"},
                        runner=self._runner,
                    )

    def test_validation_requires_python_and_mineru_executables_to_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / "venv"
            venv.mkdir()
            check_script = Path(tmp) / "check.py"

            with self.assertRaisesRegex(RuntimeError, "bin/python"):
                rebuild_mineru_venv.validate_staging(
                    venv,
                    check_script,
                    "3.4.2",
                    base_env={},
                    runner=self._runner,
                )

            self.assertEqual([], self.calls)


class RebuildOrchestrationTest(unittest.TestCase):
    def _setup(self, root: Path, *, with_active: bool = True) -> tuple[rebuild_mineru_venv.BuildPaths, Path]:
        root = root.resolve()
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
                python = bin_dir / "python"
                python.write_text("#!/bin/sh\n", encoding="utf-8")
                python.chmod(0o755)
                for name in ("mineru", "mineru-api"):
                    self._entrypoint(bin_dir / name, bin_dir / "python")
                (paths.staging / "pyvenv.cfg").write_text(
                    f"command = python -m venv {paths.staging}\n",
                    encoding="utf-8",
                )
            elif fail_install and command[1:7] == ["-m", "pip", "--isolated", "install", "--upgrade", "pip"]:
                raise subprocess.CalledProcessError(1, command)
            elif command[0].startswith(str(paths.active.parent)) and not Path(command[0]).exists():
                raise FileNotFoundError(command[0])
            if fail_active_readiness and command == [
                str(paths.active / "bin" / "python"),
                "-I",
                str(paths.active.parent.parent / "scripts" / "check_mineru.py"),
                "--json",
                "--skip-api",
            ]:
                raise subprocess.CalledProcessError(1, command)
            if command[-1:] == ["--version"]:
                stdout = "mineru, version 3.4.2\n"
            elif command[-3:] == ["pip", "freeze", "--all"]:
                stdout = "MarkupSafe==3.0.3\nmineru==3.4.2\n"
            elif command[1:3] == ["-I", "-c"]:
                venv = Path(command[0]).parent.parent
                stdout = json.dumps(
                    {
                        "mineruVersion": "3.4.2",
                        "markupSafeVersion": "3.0.3",
                        "pythonVersion": "3.12.0",
                        "pythonExecutable": str(venv / "bin" / "python"),
                        "pythonPrefix": str(venv),
                        "modulePaths": {
                            name: str(venv / "lib" / "site-packages" / filename)
                            for name, filename in {
                                "markupsafe": "markupsafe/__init__.py",
                                "jinja2": "jinja2/__init__.py",
                                "transformers": "transformers/__init__.py",
                                "mineru": "mineru/__init__.py",
                                "mineru.cli.common": "mineru/cli/common.py",
                            }.items()
                        },
                    },
                    sort_keys=True,
                )
            elif command[-2:] == ["--json", "--skip-api"]:
                stdout = '{"installed":true,"runtimeProbeOk":true}\n'
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
            self.assertTrue((paths.active / "bin" / "python").exists())
            self.assertTrue((paths.active / "bin" / "mineru").exists())
            self.assertTrue((paths.active / "mineru-venv-manifest.json").is_file())
            self.assertFalse(rebuild_mineru_venv.transaction_journal_path(paths.active).exists())
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
            prune_failed = mock.Mock()

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
                    prune_failed=prune_failed,
                )

            self.assertEqual("old", (paths.active / "old-marker").read_text(encoding="utf-8"))
            self.assertEqual("new", (paths.staging / "new-marker").read_text(encoding="utf-8"))
            self.assertFalse(paths.backup.exists())
            prune_failed.assert_not_called()
            with rebuild_mineru_venv.rebuild_lock(paths.active):
                pass

    def test_install_or_validation_timeout_preserves_staging_and_old_active(self) -> None:
        for timeout_stage in ("install", "validation"):
            with self.subTest(timeout_stage=timeout_stage), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                paths, check_script = self._setup(root)
                calls: list[tuple[list[str], dict[str, object]]] = []
                normal_runner = self._runner(paths, calls)

                def timing_out(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                    if timeout_stage == "install" and command[1:4] == ["-m", "pip", "--isolated"]:
                        raise subprocess.TimeoutExpired(command, kwargs["timeout"])
                    if timeout_stage == "validation" and command[-2:] == ["--json", "--skip-api"]:
                        raise subprocess.TimeoutExpired(command, kwargs["timeout"], output="partial")
                    return normal_runner(command, **kwargs)

                with self.assertRaises(subprocess.TimeoutExpired):
                    rebuild_mineru_venv.rebuild_venv(
                        paths.active,
                        Path("/usr/bin/python3"),
                        "3.4.2",
                        check_script,
                        2,
                        timestamp="20260715T120000.000000Z-fixed",
                        base_env={"PATH": "/test/bin"},
                        runner=timing_out,
                        disk_usage=lambda _path: SimpleNamespace(free=100 * 1024**3),
                        install_timeout=11,
                        check_timeout=7,
                    )

                self.assertEqual("old", (paths.active / "old-marker").read_text(encoding="utf-8"))
                self.assertEqual("new", (paths.staging / "new-marker").read_text(encoding="utf-8"))
                self.assertFalse(paths.backup.exists())
                timeout_calls = [kwargs["timeout"] for _command, kwargs in calls if "timeout" in kwargs]
                self.assertTrue(timeout_calls)

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

    def test_prune_exception_warns_after_healthy_activation_without_failing_rebuild(self) -> None:
        for failure in (PermissionError("permission denied"), RuntimeError("cleanup failed")):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                paths, check_script = self._setup(root)
                calls: list[tuple[list[str], dict[str, object]]] = []
                stderr = io.StringIO()

                with mock.patch("sys.stderr", stderr):
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
                        prune=mock.Mock(side_effect=failure),
                    )

                self.assertEqual(paths, result)
                self.assertEqual("new", (paths.active / "new-marker").read_text(encoding="utf-8"))
                self.assertEqual("old", (paths.backup / "old-marker").read_text(encoding="utf-8"))
                self.assertIn("warning", stderr.getvalue().lower())
                self.assertIn(str(failure), stderr.getvalue())

    def test_prune_baseexception_is_not_swallowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths, check_script = self._setup(root)
            calls: list[tuple[list[str], dict[str, object]]] = []

            with self.assertRaises(KeyboardInterrupt):
                rebuild_mineru_venv.rebuild_venv(
                    paths.active,
                    Path("/usr/bin/python3"),
                    "3.4.2",
                    check_script,
                    2,
                    timestamp="20260715T120000.000000Z-fixed",
                    base_env={"PATH": "/test/bin"},
                    runner=self._runner(paths, calls),
                    disk_usage=lambda _path: SimpleNamespace(free=100 * 1024**3),
                    prune=mock.Mock(side_effect=KeyboardInterrupt()),
                )

            self.assertEqual("new", (paths.active / "new-marker").read_text(encoding="utf-8"))
            self.assertEqual("old", (paths.backup / "old-marker").read_text(encoding="utf-8"))

    def test_failed_staging_cleanup_exception_warns_without_failing_healthy_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths, check_script = self._setup(root)
            calls: list[tuple[list[str], dict[str, object]]] = []
            stderr = io.StringIO()

            with mock.patch("sys.stderr", stderr):
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
                    prune_failed=mock.Mock(side_effect=PermissionError("cannot prune failed staging")),
                )

            self.assertEqual(paths, result)
            self.assertEqual("new", (paths.active / "new-marker").read_text(encoding="utf-8"))
            self.assertEqual("old", (paths.backup / "old-marker").read_text(encoding="utf-8"))
            self.assertIn("warning", stderr.getvalue().lower())
            self.assertIn("cannot prune failed staging", stderr.getvalue())

    def test_failed_staging_cleanup_baseexception_is_not_swallowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths, check_script = self._setup(root)
            calls: list[tuple[list[str], dict[str, object]]] = []

            with self.assertRaises(KeyboardInterrupt):
                rebuild_mineru_venv.rebuild_venv(
                    paths.active,
                    Path("/usr/bin/python3"),
                    "3.4.2",
                    check_script,
                    2,
                    timestamp="20260715T120000.000000Z-fixed",
                    base_env={"PATH": "/test/bin"},
                    runner=self._runner(paths, calls),
                    disk_usage=lambda _path: SimpleNamespace(free=100 * 1024**3),
                    prune_failed=mock.Mock(side_effect=KeyboardInterrupt()),
                )

            self.assertEqual("new", (paths.active / "new-marker").read_text(encoding="utf-8"))
            self.assertEqual("old", (paths.backup / "old-marker").read_text(encoding="utf-8"))

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
        self.assertEqual(2, args.keep_failed_staging)
        self.assertEqual(3600, args.install_timeout)
        self.assertEqual(300, args.check_timeout)

    def test_cli_rejects_nonpositive_timeouts(self) -> None:
        base = [
            "--target",
            "/srv/vendor/mineru-venv",
            "--python",
            "/usr/bin/python3",
            "--check-script",
            "/srv/scripts/check_mineru.py",
        ]
        for option in ("--install-timeout", "--check-timeout"):
            for value in ("0", "-1"):
                with self.subTest(option=option, value=value), self.assertRaises(SystemExit):
                    rebuild_mineru_venv.parse_args([*base, option, value])

    def test_cli_failed_staging_retention_accepts_zero_and_rejects_negative(self) -> None:
        base = [
            "--target",
            "/srv/vendor/mineru-venv",
            "--python",
            "/usr/bin/python3",
            "--check-script",
            "/srv/scripts/check_mineru.py",
        ]

        args = rebuild_mineru_venv.parse_args([*base, "--keep-failed-staging", "0"])
        self.assertEqual(0, args.keep_failed_staging)
        with self.assertRaises(SystemExit):
            rebuild_mineru_venv.parse_args([*base, "--keep-failed-staging", "-1"])

    def test_main_returns_nonzero_and_reports_timeout(self) -> None:
        timeout = subprocess.TimeoutExpired(["pip", "install"], 10, output="partial install")
        argv = [
            "--target",
            "/srv/vendor/mineru-venv",
            "--python",
            "/usr/bin/python3",
            "--check-script",
            "/srv/scripts/check_mineru.py",
        ]

        with mock.patch.object(rebuild_mineru_venv, "rebuild_venv", side_effect=timeout), mock.patch(
            "sys.stderr"
        ) as stderr:
            result = rebuild_mineru_venv.main(argv)

        self.assertEqual(1, result)
        self.assertIn("timed out", "".join(call.args[0] for call in stderr.write.call_args_list).lower())


class VerifyOnlyTest(unittest.TestCase):
    @staticmethod
    def _runner(version_output: str, calls: list[list[str]]):
        def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            active = Path(command[0]).parent.parent
            if command[-1:] == ["--version"]:
                stdout = version_output
            elif command[-3:] == ["pip", "freeze", "--all"]:
                stdout = "MarkupSafe==3.0.3\nmineru==3.4.2\n"
            elif command[1:3] == ["-I", "-c"]:
                stdout = json.dumps(
                    {
                        "mineruVersion": "3.4.2",
                        "markupSafeVersion": "3.0.3",
                        "pythonVersion": "3.12.0",
                        "pythonExecutable": str(active / "bin" / "python"),
                        "pythonPrefix": str(active),
                        "modulePaths": {
                            name: str(active / "lib" / "site-packages" / filename)
                            for name, filename in {
                                "markupsafe": "markupsafe/__init__.py",
                                "jinja2": "jinja2/__init__.py",
                                "transformers": "transformers/__init__.py",
                                "mineru": "mineru/__init__.py",
                                "mineru.cli.common": "mineru/cli/common.py",
                            }.items()
                        },
                    }
                )
            else:
                stdout = '{"installed":true,"runtimeProbeOk":true}\n'
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

        return run

    def test_verify_only_cli_does_not_require_python_or_run_rebuild(self) -> None:
        argv = [
            "--verify-only",
            "--target",
            "/srv/vendor/mineru-venv",
            "--mineru-version",
            "3.4.2",
            "--check-script",
            "/srv/scripts/check_mineru.py",
        ]
        args = rebuild_mineru_venv.parse_args(argv)
        self.assertTrue(args.verify_only)
        self.assertIsNone(args.python)

        with mock.patch.object(rebuild_mineru_venv, "verify_active_venv") as verify, mock.patch.object(
            rebuild_mineru_venv, "rebuild_venv"
        ) as rebuild:
            result = rebuild_mineru_venv.main(argv)

        self.assertEqual(0, result)
        verify.assert_called_once()
        rebuild.assert_not_called()

    def test_normal_rebuild_still_requires_python(self) -> None:
        with self.assertRaises(SystemExit):
            rebuild_mineru_venv.parse_args(
                [
                    "--target",
                    "/srv/vendor/mineru-venv",
                    "--check-script",
                    "/srv/scripts/check_mineru.py",
                ]
            )

    def test_verify_only_accepts_exact_version_and_rejects_adversarial_outputs(self) -> None:
        invalid_outputs = (
            "mineru, version 3.4.1\n",
            "mineru, version 3.4.2rc1\n",
            "mineru, version 3.4.2.post1\n",
            "mineru, version 3.4.2\nmineru, version 3.4.2\n",
            "mineru, version 3.4.2\nmineru, version 3.4.1\n",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            active = root / "vendor" / "mineru-venv"
            active.mkdir(parents=True)
            VenvValidationTest._write_valid_manifest(active)
            check_script = root / "scripts" / "check_mineru.py"
            check_script.parent.mkdir()
            check_script.write_text("# check\n", encoding="utf-8")
            calls: list[list[str]] = []

            rebuild_mineru_venv.verify_active_venv(
                active,
                check_script,
                "3.4.2",
                base_env={"PATH": "/test/bin"},
                runner=self._runner("warning\nmineru, version 3.4.2\n", calls),
                check_timeout=9,
            )
            self.assertFalse(any("install" in command for command in calls))

            for output in invalid_outputs:
                with self.subTest(output=output), self.assertRaises(RuntimeError):
                    rebuild_mineru_venv.verify_active_venv(
                        active,
                        check_script,
                        "3.4.2",
                        base_env={"PATH": "/test/bin"},
                        runner=self._runner(output, []),
                        check_timeout=9,
                    )


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
