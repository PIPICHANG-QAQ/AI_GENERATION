import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.check_project_portability import iter_source_tree_paths


class CheckProjectPortabilityTest(unittest.TestCase):
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
