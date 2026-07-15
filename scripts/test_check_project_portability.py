import tempfile
import unittest
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import check_project_portability
from scripts.check_project_portability import is_allowed_absolute_local_path, iter_source_tree_paths


class CheckProjectPortabilityTest(unittest.TestCase):
    def check_text(self, relative_path: str, text: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            failures: list[str] = []
            with mock.patch.object(check_project_portability, "ROOT", root), mock.patch.object(
                check_project_portability,
                "validate",
                return_value=[],
            ):
                check_project_portability.check_packaged_files([path], failures)
        return failures

    def test_fixed_server_path_is_allowed_in_recovery_plan_and_runbook_contract_test(self):
        server_root = str(Path("/") / "home" / "user" / "AI_GENERATION_DOCKER")
        allowed_files = (
            "docs/superpowers/plans/2026-07-15-production-recovery-and-ocr-readiness.md",
            "scripts/test_rebuild_mineru_venv.py",
        )

        for relative_path in allowed_files:
            with self.subTest(relative_path=relative_path):
                self.assertTrue(is_allowed_absolute_local_path(relative_path, server_root))
                self.assertTrue(
                    is_allowed_absolute_local_path(relative_path, f"{server_root}/vendor/mineru-venv")
                )
                self.assertFalse(is_allowed_absolute_local_path(relative_path, f"{server_root}_EVIL"))
        self.assertFalse(is_allowed_absolute_local_path("scripts/unrelated.py", server_root))

    def test_fixed_server_path_allowance_uses_posix_lexical_normalization(self):
        server_root = str(Path("/") / "home" / "user" / "AI_GENERATION_DOCKER")
        relative_path = "scripts/test_rebuild_mineru_venv.py"

        self.assertFalse(
            is_allowed_absolute_local_path(relative_path, f"{server_root}/../private")
        )
        self.assertFalse(
            is_allowed_absolute_local_path(
                relative_path,
                f"{server_root}/vendor/../../.ssh/authorized_keys",
            )
        )
        self.assertTrue(
            is_allowed_absolute_local_path(
                relative_path,
                f"{server_root}/vendor/../vendor/mineru-venv",
            )
        )
        self.assertFalse(is_allowed_absolute_local_path(relative_path, server_root.lstrip("/")))
        self.assertFalse(is_allowed_absolute_local_path(relative_path, f"/{server_root}"))

    def test_allowed_server_path_does_not_hide_later_local_paths(self):
        server_path = str(
            Path("/") / "home" / "user" / "AI_GENERATION_DOCKER" / "vendor" / "mineru-venv"
        )
        user_path = str(Path("/") / "Users" / "example" / "private.txt")
        temporary_path = str(Path("/") / "var" / "folders" / "example" / "private.txt")

        failures = self.check_text(
            "scripts/test_rebuild_mineru_venv.py",
            " ".join((server_path, user_path, temporary_path)),
        )

        self.assertEqual(2, len(failures))
        self.assertTrue(any(user_path in failure for failure in failures))
        self.assertTrue(any(temporary_path in failure for failure in failures))

    def test_local_paths_before_allowed_server_path_are_all_reported(self):
        server_path = str(
            Path("/") / "home" / "user" / "AI_GENERATION_DOCKER" / "vendor" / "mineru-venv"
        )
        user_path = str(Path("/") / "Users" / "example" / "private.txt")
        temporary_path = str(Path("/") / "var" / "folders" / "example" / "private.txt")

        failures = self.check_text(
            "scripts/test_rebuild_mineru_venv.py",
            " ".join((user_path, temporary_path, server_path)),
        )

        self.assertEqual(2, len(failures))
        self.assertTrue(any(user_path in failure for failure in failures))
        self.assertTrue(any(temporary_path in failure for failure in failures))

    def test_source_tree_walk_prunes_excluded_dependency_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("print('ok')", encoding="utf-8")
            (root / "backend" / "python-worker" / ".venv" / "bin").mkdir(parents=True)
            (root / "backend" / "python-worker" / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            (root / "local-platform" / "node_modules" / "pkg").mkdir(parents=True)
            (root / "local-platform" / "node_modules" / "pkg" / "index.js").write_text("", encoding="utf-8")

            paths = [path.relative_to(root).as_posix() for path in iter_source_tree_paths(root)]

        self.assertIn("src/app.py", paths)
        self.assertFalse(any("/.venv/" in path or path.startswith(".venv/") for path in paths))
        self.assertFalse(any("/node_modules/" in path or path.startswith("node_modules/") for path in paths))


if __name__ == "__main__":
    unittest.main()
