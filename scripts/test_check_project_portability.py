import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.check_project_portability import (
    check_text_paths,
    find_absolute_local_paths,
    is_allowed_absolute_local_path,
    iter_source_tree_paths,
)


class CheckProjectPortabilityTest(unittest.TestCase):
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
        private_path = f"{server_root}/../private"
        ssh_path = f"{server_root}/vendor/../../.ssh/authorized_keys"
        inside_path = f"{server_root}/vendor/../vendor/mineru-venv"

        failures = check_text_paths(
            relative_path,
            " ".join((private_path, ssh_path, inside_path)),
        )

        self.assertEqual(2, len(failures))
        self.assertTrue(any(private_path in failure for failure in failures))
        self.assertTrue(any(ssh_path in failure for failure in failures))
        self.assertFalse(any(inside_path in failure for failure in failures))
        self.assertFalse(is_allowed_absolute_local_path(relative_path, server_root.lstrip("/")))
        self.assertFalse(is_allowed_absolute_local_path(relative_path, f"/{server_root}"))

    def test_punctuation_separates_allowed_and_local_path_candidates(self):
        server_root = str(Path("/") / "home" / "user" / "AI_GENERATION_DOCKER")
        user_path = str(Path("/") / "Users" / "example" / "private.txt")
        relative_path = "scripts/test_rebuild_mineru_venv.py"

        for separator in (":", ";", ",", ".", ")"):
            with self.subTest(separator=separator):
                text = f"{server_root}{separator}{user_path}"
                self.assertEqual(
                    [server_root, user_path],
                    find_absolute_local_paths(text),
                )
                failures = check_text_paths(relative_path, text)
                self.assertEqual(1, len(failures))
                self.assertIn(user_path, failures[0])

    def test_allowed_root_and_subpath_are_clean_before_trailing_punctuation(self):
        server_root = str(Path("/") / "home" / "user" / "AI_GENERATION_DOCKER")
        server_child = f"{server_root}/vendor/mineru-venv"
        relative_path = "scripts/test_rebuild_mineru_venv.py"

        for candidate in (server_root, server_child):
            for punctuation in (":", ";", ",", ".", ")"):
                with self.subTest(candidate=candidate, punctuation=punctuation):
                    text = f"documented path: {candidate}{punctuation} next"
                    self.assertEqual([candidate], find_absolute_local_paths(text))
                    self.assertEqual([], check_text_paths(relative_path, text))

    def test_json_escaped_slashes_are_normalized_before_scanning(self):
        user_path = str(Path("/") / "Users" / "example" / "private.txt")
        escaped_path = user_path.replace("/", "\\/")

        self.assertEqual([user_path], find_absolute_local_paths(escaped_path))
        failures = check_text_paths("docs/example.json", escaped_path)
        self.assertEqual(1, len(failures))
        self.assertIn(user_path, failures[0])

    def test_double_leading_slash_is_one_rejected_candidate(self):
        server_root = str(Path("/") / "home" / "user" / "AI_GENERATION_DOCKER")
        double_slash_path = f"/{server_root}"
        relative_path = "scripts/test_rebuild_mineru_venv.py"

        self.assertEqual([double_slash_path], find_absolute_local_paths(double_slash_path))
        failures = check_text_paths(relative_path, double_slash_path)
        self.assertEqual(1, len(failures))
        self.assertIn(double_slash_path, failures[0])

    def test_https_urls_are_not_treated_as_local_paths(self):
        user_suffix = "/".join(("Users", "example", "private.txt"))
        server_suffix = "/".join(("home", "user", "AI_GENERATION_DOCKER", "guide"))
        text = f"https://example.com/{user_suffix} https://example.com/{server_suffix}"
        escaped_text = text.replace("/", "\\/")

        self.assertEqual([], find_absolute_local_paths(text))
        self.assertEqual([], find_absolute_local_paths(escaped_text))
        self.assertEqual([], check_text_paths("docs/example.md", text))

    def test_allowed_server_path_does_not_hide_later_local_paths(self):
        server_path = str(
            Path("/") / "home" / "user" / "AI_GENERATION_DOCKER" / "vendor" / "mineru-venv"
        )
        user_path = str(Path("/") / "Users" / "example" / "private.txt")
        temporary_path = str(Path("/") / "var" / "folders" / "example" / "private.txt")

        failures = check_text_paths(
            "scripts/test_rebuild_mineru_venv.py",
            " ".join((server_path, user_path, temporary_path)),
        )

        self.assertEqual(
            [server_path, user_path, temporary_path],
            find_absolute_local_paths(" ".join((server_path, user_path, temporary_path))),
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

        failures = check_text_paths(
            "scripts/test_rebuild_mineru_venv.py",
            " ".join((user_path, temporary_path, server_path)),
        )

        self.assertEqual(
            [user_path, temporary_path, server_path],
            find_absolute_local_paths(" ".join((user_path, temporary_path, server_path))),
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
