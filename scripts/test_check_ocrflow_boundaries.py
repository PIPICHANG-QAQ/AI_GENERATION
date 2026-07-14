import json
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_ocrflow_boundaries import check_boundaries
import check_project_portability as portability


class CheckOcrflowBoundariesTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temporary_directory.name)
        self.config_path = self.repo_root / "config" / "ocrflow-boundaries.json"
        self.write_config([], [])

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write_source(self, relative_path: str, content: str) -> None:
        path = self.repo_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def write_config(self, frozen_allowlist: list[dict], allowlist: list[dict]) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "frozenAllowlist": frozen_allowlist,
                    "allowlist": allowlist,
                }
            ),
            encoding="utf-8",
        )

    def test_rejects_python_worker_question_bank_route(self):
        self.write_source(
            "backend/python-worker/app/worker_routes.py",
            '@app.post("/api/question-bank/questions")\ndef create_question():\n    pass\n',
        )

        failures = check_boundaries(self.repo_root, self.config_path)

        self.assertTrue(any("python-worker-business-api" in failure for failure in failures), failures)
        self.assertTrue(any("/api/question-bank/questions" in failure for failure in failures), failures)

    def test_rejects_java_ocrflow_call_to_python_api(self):
        self.write_source(
            "backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/WorkerClient.java",
            'class WorkerClient { String path = "/api/ocr/jobs"; }\n',
        )

        failures = check_boundaries(self.repo_root, self.config_path)

        self.assertTrue(any("java-ocrflow-python-api" in failure for failure in failures), failures)
        self.assertTrue(any("/api/ocr/jobs" in failure for failure in failures), failures)

    def test_rejects_review_core_react_and_dom_dependencies(self):
        self.write_source(
            "question-engine/review-core/src/review.ts",
            'import React from "react";\nexport const title = document.title;\n',
        )

        failures = check_boundaries(self.repo_root, self.config_path)

        self.assertTrue(any("review-core-ui-dependency" in failure and "react" in failure for failure in failures), failures)
        self.assertTrue(any("review-core-ui-dependency" in failure and "document" in failure for failure in failures), failures)

    def test_rejects_worker_algorithm_import_from_legacy(self):
        self.write_source(
            "backend/python-worker/app/ocr/pipeline.py",
            "from app.legacy import import_tasks\n",
        )

        failures = check_boundaries(self.repo_root, self.config_path)

        self.assertTrue(any("worker-algorithm-legacy-import" in failure for failure in failures), failures)
        self.assertTrue(any("app.legacy.import_tasks" in failure for failure in failures), failures)

    def test_exact_allowlist_entry_does_not_allow_new_pattern_in_same_file(self):
        allowed = {
            "rule": "python-worker-business-api",
            "path": "backend/python-worker/app/worker_routes.py",
            "pattern": "/api/question-bank/questions",
            "count": 1,
        }
        self.write_config([allowed], [allowed])
        self.write_source(
            allowed["path"],
            '\n'.join(
                [
                    '@app.get("/api/question-bank/questions")',
                    "def list_questions():",
                    "    pass",
                    '@app.get("/api/question-bank/admin")',
                    "def list_admin_questions():",
                    "    pass",
                    "",
                ]
            ),
        )

        failures = check_boundaries(self.repo_root, self.config_path)

        self.assertFalse(any("unallowlisted" in failure and allowed["pattern"] in failure for failure in failures), failures)
        self.assertTrue(any("unallowlisted" in failure and "/api/question-bank/admin" in failure for failure in failures), failures)

    def test_exact_allowlist_count_does_not_allow_duplicate_new_occurrence(self):
        allowed = {
            "rule": "python-worker-business-api",
            "path": "backend/python-worker/app/worker_routes.py",
            "pattern": "/api/question-bank/questions",
            "count": 1,
        }
        self.write_config([allowed], [allowed])
        self.write_source(
            allowed["path"],
            '\n'.join(
                [
                    '@app.get("/api/question-bank/questions")',
                    "def list_questions():",
                    "    pass",
                    '@app.post("/api/question-bank/questions")',
                    "def create_question():",
                    "    pass",
                    "",
                ]
            ),
        )

        failures = check_boundaries(self.repo_root, self.config_path)

        self.assertTrue(any("expected 1 occurrence(s), found 2" in failure for failure in failures), failures)

    def test_allowlist_may_only_shrink_from_frozen_baseline(self):
        frozen = {
            "rule": "python-worker-business-api",
            "path": "backend/python-worker/app/worker_routes.py",
            "pattern": "/api/question-bank/questions",
            "count": 1,
        }
        added = {
            "rule": "python-worker-business-api",
            "path": "backend/python-worker/app/worker_routes.py",
            "pattern": "/api/question-bank/admin",
            "count": 1,
        }
        self.write_config([frozen], [frozen, added])

        failures = check_boundaries(self.repo_root, self.config_path)

        self.assertTrue(any("not present in frozen allowlist" in failure for failure in failures), failures)

    def test_removed_violation_and_allowlist_entry_are_accepted(self):
        frozen = {
            "rule": "python-worker-business-api",
            "path": "backend/python-worker/app/worker_routes.py",
            "pattern": "/api/question-bank/questions",
            "count": 1,
        }
        self.write_config([frozen], [])

        failures = check_boundaries(self.repo_root, self.config_path)

        self.assertEqual([], failures)

    def test_allowlist_rejects_glob_paths(self):
        broad_entry = {
            "rule": "python-worker-business-api",
            "path": "backend/python-worker/app/**",
            "pattern": "/api/question-bank/questions",
            "count": 1,
        }
        self.write_config([broad_entry], [broad_entry])

        failures = check_boundaries(self.repo_root, self.config_path)

        self.assertTrue(any("must name one exact file" in failure for failure in failures), failures)

    def test_allowlist_rejects_directory_paths(self):
        broad_entry = {
            "rule": "python-worker-business-api",
            "path": "backend/python-worker/app",
            "pattern": "/api/question-bank/questions",
            "count": 1,
        }
        self.write_config([broad_entry], [broad_entry])

        failures = check_boundaries(self.repo_root, self.config_path)

        self.assertTrue(any("must name one exact file" in failure for failure in failures), failures)

    def test_portability_main_returns_failure_for_boundary_violation(self):
        with (
            mock.patch.object(portability, "iter_files", return_value=[]),
            mock.patch.object(portability, "check_packaged_files"),
            mock.patch.object(portability, "check_source_tree_symlinks"),
            mock.patch.object(portability, "check_local_install_state"),
            mock.patch.object(portability, "check_architecture_boundaries") as boundary_check,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            boundary_check.side_effect = lambda failures: failures.append("boundary failed")

            return_code = portability.main()

        self.assertEqual(1, return_code)
        boundary_check.assert_called_once()


if __name__ == "__main__":
    unittest.main()
