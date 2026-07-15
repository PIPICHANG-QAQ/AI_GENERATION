#!/usr/bin/env python3
"""Behavior tests for the MinerU rollback shell delegate."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ROLLBACK_SCRIPT = ROOT / "scripts" / "rollback_mineru_venv.sh"
REBUILD_SCRIPT = ROOT / "scripts" / "rebuild_mineru_venv.py"


class RollbackMineruVenvShellTest(unittest.TestCase):
    def _layout(self, root: Path) -> dict[str, object]:
        root = root.resolve()
        target = root / "vendor" / "mineru-venv"
        backup = target.with_name(f"{target.name}.bak-20260715T120000.000000Z-aaaaaaaa")
        target.mkdir(parents=True)
        backup.mkdir()
        (target / "identity").write_text("prior", encoding="utf-8")
        (backup / "identity").write_text("candidate", encoding="utf-8")
        check_script = root / "scripts" / "check_mineru.py"
        check_script.parent.mkdir()
        check_script.write_text("# readiness\n", encoding="utf-8")
        args_log = root / "args.log"
        start_log = root / "start.log"
        fake_rebuilder = root / "fake_rebuilder.py"
        fake_rebuilder.write_text(
            "#!/usr/bin/env python3\n"
            "import os\n"
            "from pathlib import Path\n"
            "import sys\n"
            "Path(os.environ['ARGS_LOG']).write_text('\\n'.join(sys.argv[1:]) + '\\n', encoding='utf-8')\n"
            "raise SystemExit(int(os.environ.get('REBUILDER_STATUS', '0')))\n",
            encoding="utf-8",
        )
        fake_rebuilder.chmod(0o755)
        env = os.environ.copy()
        env.update({"ARGS_LOG": str(args_log), "START_LOG": str(start_log)})
        args = [
            "--target",
            str(target),
            "--backup",
            str(backup),
            "--check-script",
            str(check_script),
            "--rebuild-script",
            str(fake_rebuilder),
            "--mineru-version",
            "3.4.2",
        ]
        return {
            "target": target,
            "backup": backup,
            "check_script": check_script,
            "fake_rebuilder": fake_rebuilder,
            "args_log": args_log,
            "start_log": start_log,
            "env": env,
            "args": args,
        }

    def _run(self, layout: dict[str, object]) -> subprocess.CompletedProcess[str]:
        wrapper = 'if "$@"; then printf "start\\n" >> "$START_LOG"; else exit "$?"; fi'
        return subprocess.run(
            ["bash", "-c", wrapper, "rollback-test", "bash", str(ROLLBACK_SCRIPT), *layout["args"]],
            env=layout["env"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )

    def test_shell_syntax_is_valid(self) -> None:
        subprocess.run(["bash", "-n", str(ROLLBACK_SCRIPT)], check=True, env=os.environ.copy())

    def test_execs_python_rebuilder_with_exact_rollback_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            layout = self._layout(Path(tmp))

            completed = self._run(layout)

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual("start\n", layout["start_log"].read_text(encoding="utf-8"))
            self.assertEqual(
                [
                    "--rollback-backup",
                    str(layout["backup"]),
                    "--target",
                    str(layout["target"]),
                    "--mineru-version",
                    "3.4.2",
                    "--check-script",
                    str(layout["check_script"]),
                ],
                layout["args_log"].read_text(encoding="utf-8").splitlines(),
            )
            self.assertEqual("prior", (layout["target"] / "identity").read_text(encoding="utf-8"))
            self.assertEqual("candidate", (layout["backup"] / "identity").read_text(encoding="utf-8"))

    def test_rebuilder_failure_is_propagated_and_blocks_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            layout = self._layout(Path(tmp))
            layout["env"]["REBUILDER_STATUS"] = "23"

            completed = self._run(layout)

            self.assertEqual(23, completed.returncode)
            self.assertFalse(layout["start_log"].exists())

    def test_helper_contains_no_move_logic_and_execs_the_rebuilder(self) -> None:
        shell = ROLLBACK_SCRIPT.read_text(encoding="utf-8")

        self.assertIsNone(re.search(r"\bmv\b", shell))
        self.assertIn("exec", shell)
        self.assertIn("--rollback-backup", shell)

    def test_relative_required_path_is_rejected_before_exec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            layout = self._layout(Path(tmp))
            args = list(layout["args"])
            args[1] = "relative/mineru-venv"
            layout["args"] = args

            completed = self._run(layout)

            self.assertNotEqual(0, completed.returncode)
            self.assertFalse(layout["args_log"].exists())
            self.assertFalse(layout["start_log"].exists())

    def test_duplicate_and_unknown_arguments_are_rejected(self) -> None:
        for extra in (("--target", "/tmp/duplicate"), ("--unknown", "value")):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as tmp:
                layout = self._layout(Path(tmp))
                layout["args"] = [*layout["args"], *extra]

                completed = self._run(layout)

                self.assertNotEqual(0, completed.returncode)
                self.assertFalse(layout["args_log"].exists())
                self.assertFalse(layout["start_log"].exists())

    def test_python_rejects_ancestor_symlink_without_moving_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            real = root / "real"
            layout = self._layout(real)
            alias = root / "alias"
            alias.symlink_to(real, target_is_directory=True)
            args = list(layout["args"])
            args[1] = str(alias / "vendor" / layout["target"].name)
            args[3] = str(alias / "vendor" / layout["backup"].name)
            args[7] = str(REBUILD_SCRIPT)
            layout["args"] = args

            completed = self._run(layout)

            self.assertNotEqual(0, completed.returncode)
            self.assertIn("symlink", completed.stderr.lower())
            self.assertEqual("prior", (layout["target"] / "identity").read_text(encoding="utf-8"))
            self.assertEqual("candidate", (layout["backup"] / "identity").read_text(encoding="utf-8"))
            self.assertFalse(layout["start_log"].exists())


if __name__ == "__main__":
    unittest.main()
