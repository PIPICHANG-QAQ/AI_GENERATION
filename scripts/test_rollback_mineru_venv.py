#!/usr/bin/env python3
"""Behavior tests for safe MinerU virtualenv rollback."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ROLLBACK_SCRIPT = ROOT / "scripts" / "rollback_mineru_venv.sh"


class RollbackMineruVenvShellTest(unittest.TestCase):
    def test_shell_syntax_is_valid(self) -> None:
        subprocess.run(["bash", "-n", str(ROLLBACK_SCRIPT)], check=True, env=os.environ.copy())

    def _layout(self, root: Path, operation_id: str = "testcase") -> dict[str, object]:
        root = root.resolve()
        target = root / "vendor" / "mineru-venv"
        backup = target.with_name(f"{target.name}.bak-20260715T120000.000000Z-aaaaaaaa")
        target.mkdir(parents=True)
        backup.mkdir()
        (target / "identity").write_text("prior", encoding="utf-8")
        (backup / "identity").write_text("candidate", encoding="utf-8")
        (backup / "ready").write_text("yes", encoding="utf-8")
        (backup / "version-output").write_text("mineru, version 3.4.2\n", encoding="utf-8")
        check_script = root / "scripts" / "check_mineru.py"
        check_script.parent.mkdir()
        check_script.write_text("# fake readiness path\n", encoding="utf-8")
        verifier = root / "fake_verify.py"
        verifier.write_text(
            "#!/usr/bin/env python3\n"
            "import argparse\n"
            "from pathlib import Path\n"
            "import subprocess\n"
            "import sys\n"
            f"sys.path.insert(0, {str(ROOT / 'scripts')!r})\n"
            "import rebuild_mineru_venv\n"
            "parser = argparse.ArgumentParser()\n"
            "parser.add_argument('--verify-only', action='store_true', required=True)\n"
            "parser.add_argument('--target', type=Path, required=True)\n"
            "parser.add_argument('--mineru-version', required=True)\n"
            "parser.add_argument('--check-script', type=Path, required=True)\n"
            "args = parser.parse_args()\n"
            "if not (args.target / 'ready').is_file():\n"
            "    raise SystemExit(1)\n"
            "output = (args.target / 'version-output').read_text(encoding='utf-8')\n"
            "completed = subprocess.CompletedProcess(['mineru', '--version'], 0, stdout=output, stderr='')\n"
            "try:\n"
            "    rebuild_mineru_venv._require_version(completed, args.mineru_version)\n"
            "except RuntimeError as exc:\n"
            "    print(exc, file=sys.stderr)\n"
            "    raise SystemExit(1)\n",
            encoding="utf-8",
        )
        verifier.chmod(0o755)
        start_log = root / "start.log"
        env = os.environ.copy()
        env.update(
            {
                "MINERU_ROLLBACK_OPERATION_ID": operation_id,
                "START_LOG": str(start_log),
            }
        )
        args = [
            "--target",
            str(target),
            "--backup",
            str(backup),
            "--check-script",
            str(check_script),
            "--rebuild-script",
            str(verifier),
            "--mineru-version",
            "3.4.2",
        ]
        return {
            "target": target,
            "backup": backup,
            "check_script": check_script,
            "verifier": verifier,
            "start_log": start_log,
            "env": env,
            "args": args,
            "prior": Path(f"{target}.failed-{operation_id}"),
            "rejected": Path(f"{target}.rejected-{operation_id}"),
        }

    def _run(self, layout: dict[str, object]) -> subprocess.CompletedProcess[str]:
        wrapper = (
            'if "$@"; then printf "start\\n" >> "$START_LOG"; '
            'else status=$?; exit "$status"; fi'
        )
        return subprocess.run(
            ["bash", "-c", wrapper, "rollback-test", "bash", str(ROLLBACK_SCRIPT), *layout["args"]],
            env=layout["env"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )

    def test_good_candidate_succeeds_and_only_then_allows_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            layout = self._layout(Path(tmp), "good")

            completed = self._run(layout)

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual("candidate", (layout["target"] / "identity").read_text(encoding="utf-8"))
            self.assertEqual("prior", (layout["prior"] / "identity").read_text(encoding="utf-8"))
            self.assertFalse(layout["backup"].exists())
            self.assertEqual("start\n", layout["start_log"].read_text(encoding="utf-8"))
            self.assertIn(str(layout["prior"]), completed.stdout)

    def test_bad_readiness_is_rejected_prior_is_restored_and_start_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            layout = self._layout(Path(tmp), "bad-ready")
            (layout["backup"] / "ready").unlink()

            completed = self._run(layout)

            self.assertNotEqual(0, completed.returncode)
            self.assertEqual("prior", (layout["target"] / "identity").read_text(encoding="utf-8"))
            self.assertEqual("candidate", (layout["rejected"] / "identity").read_text(encoding="utf-8"))
            self.assertFalse(layout["prior"].exists())
            self.assertFalse(layout["start_log"].exists())
            self.assertIn(str(layout["rejected"]), completed.stderr)

    def test_nonexact_versions_are_rejected_and_never_allow_start(self) -> None:
        invalid_outputs = {
            "wrong": "mineru, version 3.4.1\n",
            "rc": "mineru, version 3.4.2rc1\n",
            "post": "mineru, version 3.4.2.post1\n",
            "duplicate": "mineru, version 3.4.2\nmineru, version 3.4.2\n",
            "conflict": "mineru, version 3.4.2\nmineru, version 3.4.1\n",
        }
        for name, output in invalid_outputs.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                layout = self._layout(Path(tmp), f"version-{name}")
                (layout["backup"] / "version-output").write_text(output, encoding="utf-8")

                completed = self._run(layout)

                self.assertNotEqual(0, completed.returncode)
                self.assertEqual("prior", (layout["target"] / "identity").read_text(encoding="utf-8"))
                self.assertEqual("candidate", (layout["rejected"] / "identity").read_text(encoding="utf-8"))
                self.assertFalse(layout["start_log"].exists())

    def test_candidate_move_failure_restores_prior_and_blocks_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            layout = self._layout(Path(tmp), "move-fail")
            fake_bin = Path(tmp) / "bin"
            fake_bin.mkdir()
            fake_mv = fake_bin / "mv"
            fake_mv.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"${2:-}\" == \"$FAIL_MV_SOURCE\" ]]; then exit 71; fi\n"
                "exec /bin/mv \"$@\"\n",
                encoding="utf-8",
            )
            fake_mv.chmod(0o755)
            layout["env"]["PATH"] = f"{fake_bin}:{layout['env']['PATH']}"
            layout["env"]["FAIL_MV_SOURCE"] = str(layout["backup"])

            completed = self._run(layout)

            self.assertNotEqual(0, completed.returncode)
            self.assertEqual("prior", (layout["target"] / "identity").read_text(encoding="utf-8"))
            self.assertEqual("candidate", (layout["backup"] / "identity").read_text(encoding="utf-8"))
            self.assertFalse(layout["prior"].exists())
            self.assertFalse(layout["start_log"].exists())
            self.assertIn("restored", completed.stderr.lower())

    def test_restore_move_failure_reports_exact_manual_recovery_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            layout = self._layout(Path(tmp), "restore-fail")
            fake_bin = Path(tmp) / "bin"
            fake_bin.mkdir()
            fake_mv = fake_bin / "mv"
            fake_mv.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"${2:-}\" == \"$FAIL_MV_SOURCE\" || \"${2:-}\" == \"$FAIL_RESTORE_SOURCE\" ]]; then exit 72; fi\n"
                "exec /bin/mv \"$@\"\n",
                encoding="utf-8",
            )
            fake_mv.chmod(0o755)
            layout["env"]["PATH"] = f"{fake_bin}:{layout['env']['PATH']}"
            layout["env"]["FAIL_MV_SOURCE"] = str(layout["backup"])
            layout["env"]["FAIL_RESTORE_SOURCE"] = str(layout["prior"])

            completed = self._run(layout)

            self.assertNotEqual(0, completed.returncode)
            self.assertFalse(layout["target"].exists())
            self.assertEqual("prior", (layout["prior"] / "identity").read_text(encoding="utf-8"))
            self.assertIn(str(layout["prior"]), completed.stderr)
            self.assertIn(str(layout["target"]), completed.stderr)

    def test_rejects_unsafe_paths_names_symlinks_and_reserved_path_collision(self) -> None:
        cases = ("relative", "wrong-name", "wrong-parent", "target-symlink", "backup-symlink", "collision")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                layout = self._layout(Path(tmp), f"unsafe-{case}")
                args = list(layout["args"])
                if case == "relative":
                    args[1] = "relative/mineru-venv"
                elif case == "wrong-name":
                    wrong = Path(tmp).resolve() / "vendor" / "other-backup"
                    wrong.mkdir()
                    args[3] = str(wrong)
                elif case == "wrong-parent":
                    wrong = Path(tmp).resolve() / "other" / f"{layout['target'].name}.bak-safe"
                    wrong.mkdir(parents=True)
                    args[3] = str(wrong)
                elif case == "target-symlink":
                    real = Path(f"{layout['target']}.real")
                    layout["target"].rename(real)
                    layout["target"].symlink_to(real, target_is_directory=True)
                elif case == "backup-symlink":
                    real = Path(f"{layout['backup']}.real")
                    layout["backup"].rename(real)
                    layout["backup"].symlink_to(real, target_is_directory=True)
                else:
                    layout["prior"].mkdir()
                layout["args"] = args

                completed = self._run(layout)

                self.assertNotEqual(0, completed.returncode)
                self.assertFalse(layout["start_log"].exists())


if __name__ == "__main__":
    unittest.main()
