import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_ocrflow_boundaries import check_boundaries, main as boundary_main
import check_project_portability as portability


class CheckOcrflowBoundariesTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temporary_directory.name)
        self.config_path = self.repo_root / "config" / "ocrflow-boundaries.json"
        self.baseline_config_path = self.repo_root / "protected" / "ocrflow-boundaries-baseline.json"
        self.write_config([], [])
        self.write_baseline([])

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

    def write_baseline(self, allowlist: list[dict]) -> None:
        self.baseline_config_path.parent.mkdir(parents=True, exist_ok=True)
        self.baseline_config_path.write_text(
            json.dumps({"version": 1, "allowlist": allowlist}),
            encoding="utf-8",
        )

    def check_boundaries(self) -> list[str]:
        return check_boundaries(
            self.repo_root,
            self.config_path,
            baseline_config_path=self.baseline_config_path,
        )

    def test_rejects_python_worker_question_bank_route(self):
        self.write_source(
            "backend/python-worker/app/worker_routes.py",
            '@app.post("/api/question-bank/questions")\ndef create_question():\n    pass\n',
        )

        failures = self.check_boundaries()

        self.assertTrue(any("python-worker-business-api" in failure for failure in failures), failures)
        self.assertTrue(any("/api/question-bank/questions" in failure for failure in failures), failures)

    def test_rejects_statically_constructed_python_worker_business_uris(self):
        self.write_source(
            "backend/python-worker/app/generated_routes.py",
            '\n'.join(
                [
                    'CONCAT = "/api/" + "question-bank/concat"',
                    'FORMATTED = "/api/{}/formatted".format("question-bank")',
                    'FSTRING = f"http://{host}/api/question-bank/fstring/{job_id}"',
                    "",
                ]
            ),
        )

        failures = self.check_boundaries()

        self.assertTrue(any("/api/question-bank/concat" in failure for failure in failures), failures)
        self.assertTrue(any("/api/question-bank/formatted" in failure for failure in failures), failures)
        self.assertTrue(any("/api/question-bank/fstring/{job_id}" in failure for failure in failures), failures)

    def test_rejects_python_worker_uri_built_from_named_constants(self):
        self.write_source(
            "backend/python-worker/app/named_routes.py",
            '\n'.join(
                [
                    'API_PREFIX = "/api/"',
                    'ROUTE = API_PREFIX + "question-bank/questions"',
                    "",
                ]
            ),
        )

        failures = self.check_boundaries()

        self.assertTrue(any("/api/question-bank/questions" in failure for failure in failures), failures)

    def test_rejects_java_ocrflow_call_to_python_api(self):
        self.write_source(
            "backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/WorkerClient.java",
            'class WorkerClient { String path = "/api/ocr/jobs"; }\n',
        )

        failures = self.check_boundaries()

        self.assertTrue(any("java-ocrflow-python-api" in failure for failure in failures), failures)
        self.assertTrue(any("/api/ocr/jobs" in failure for failure in failures), failures)

    def test_normalizes_common_java_worker_transport_uri_construction(self):
        transport_path = (
            "backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/worker/PythonWorkerTransport.java"
        )
        self.write_source(
            transport_path,
            '\n'.join(
                [
                    "class PythonWorkerTransport {",
                    '  Object a = URI.create("http://worker:8000/api/ocr/jobs");',
                    '  Object b = base.resolve("/api/import-tasks");',
                    '  Object c = builder.path("/api/" + "question-bank/questions");',
                    "}",
                    "",
                ]
            ),
        )
        domain_path = "backend/src/main/java/com/aigeneration/questionbank/ocrflow/domain/Notes.java"
        self.write_source(domain_path, 'class Notes { String example = "/api/documentation-only"; }\n')

        failures = self.check_boundaries()

        self.assertTrue(any(transport_path in failure and "/api/ocr/jobs" in failure for failure in failures), failures)
        self.assertTrue(any(transport_path in failure and "/api/import-tasks" in failure for failure in failures), failures)
        self.assertTrue(
            any(transport_path in failure and "/api/question-bank/questions" in failure for failure in failures),
            failures,
        )
        self.assertFalse(any(domain_path in failure for failure in failures), failures)

    def test_normalizes_segmented_java_worker_transport_builder_chains(self):
        transport_path = (
            "backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/worker/SegmentedTransport.java"
        )
        self.write_source(
            transport_path,
            '\n'.join(
                [
                    "class SegmentedTransport {",
                    '  Object a = base.resolve("api").resolve("ocr/jobs");',
                    '  Object b = builder.pathSegment("api", "question-bank", "questions");',
                    "}",
                    "",
                ]
            ),
        )

        failures = self.check_boundaries()

        self.assertTrue(any(transport_path in failure and "/api/ocr/jobs" in failure for failure in failures), failures)
        self.assertTrue(
            any(transport_path in failure and "/api/question-bank/questions" in failure for failure in failures),
            failures,
        )

    def test_rejects_review_core_react_and_dom_dependencies(self):
        self.write_source(
            "question-engine/review-core/src/review.ts",
            'import React from "react";\nexport const title = document.title;\n',
        )

        failures = self.check_boundaries()

        self.assertTrue(any("review-core-ui-dependency" in failure and "react" in failure for failure in failures), failures)
        self.assertTrue(any("review-core-ui-dependency" in failure and "document" in failure for failure in failures), failures)

    def test_rejects_review_core_dom_types_computed_globals_jsx_and_template_access(self):
        self.write_source(
            "question-engine/review-core/src/dom-types.ts",
            "export function focus(input: HTMLInputElement, owner: Document) { return input; }\n",
        )
        self.write_source(
            "question-engine/review-core/src/computed.ts",
            'export const doc = globalThis["document"];\n',
        )
        self.write_source(
            "question-engine/review-core/src/view.tsx",
            "export const view = <section data-kind=\"review\" />;\n",
        )
        self.write_source(
            "question-engine/review-core/src/template.ts",
            "export const title = `${document.title}`;\n",
        )

        failures = self.check_boundaries()

        self.assertTrue(any("DOM type: HTMLInputElement" in failure for failure in failures), failures)
        self.assertTrue(any('globalThis["document"]' in failure for failure in failures), failures)
        self.assertTrue(any("JSX syntax" in failure for failure in failures), failures)
        self.assertTrue(
            any("template.ts" in failure and "DOM global: document" in failure for failure in failures),
            failures,
        )

    def test_review_core_lexer_preserves_dom_after_url_string_and_template_expression(self):
        source_path = "question-engine/review-core/src/url-and-template.ts"
        self.write_source(
            source_path,
            'const endpoint = "http://worker"; document.title; const href = `${window.location}`;\n',
        )

        failures = self.check_boundaries()

        self.assertTrue(any(source_path in failure and "DOM global: document" in failure for failure in failures), failures)
        self.assertTrue(any(source_path in failure and "DOM global: window" in failure for failure in failures), failures)

    def test_rejects_worker_algorithm_import_from_legacy(self):
        self.write_source(
            "backend/python-worker/app/ocr/pipeline.py",
            "from app.legacy import import_tasks\n",
        )

        failures = self.check_boundaries()

        self.assertTrue(any("worker-algorithm-legacy-import" in failure for failure in failures), failures)
        self.assertTrue(any("app.legacy.import_tasks" in failure for failure in failures), failures)

    def test_new_root_worker_algorithm_is_scanned_while_non_algorithm_layers_are_excluded(self):
        algorithm_path = "backend/python-worker/app/new_algorithm.py"
        self.write_source(algorithm_path, "from app.legacy import import_tasks\n")
        for excluded_path in (
            "backend/python-worker/app/routes/compatibility.py",
            "backend/python-worker/app/runtime/store.py",
            "backend/python-worker/app/contracts/models.py",
            "backend/python-worker/app/legacy/question_bank.py",
        ):
            self.write_source(excluded_path, "from app.legacy import shared\n")

        failures = self.check_boundaries()

        legacy_failures = [failure for failure in failures if "worker-algorithm-legacy-import" in failure]
        self.assertTrue(any(algorithm_path in failure for failure in legacy_failures), failures)
        self.assertFalse(any("/routes/" in failure for failure in legacy_failures), failures)
        self.assertFalse(any("/runtime/" in failure for failure in legacy_failures), failures)
        self.assertFalse(any("/contracts/" in failure for failure in legacy_failures), failures)
        self.assertFalse(any("/legacy/" in failure for failure in legacy_failures), failures)

    def test_rejects_dynamic_worker_algorithm_legacy_imports(self):
        algorithm_path = "backend/python-worker/app/dynamic_algorithm.py"
        self.write_source(
            algorithm_path,
            '\n'.join(
                [
                    "import importlib",
                    'question_bank = importlib.import_module("app." + "legacy.question_bank")',
                    'papers = __import__("app.legacy.papers")',
                    "",
                ]
            ),
        )

        failures = self.check_boundaries()

        self.assertTrue(any(algorithm_path in failure and "app.legacy.question_bank" in failure for failure in failures), failures)
        self.assertTrue(any(algorithm_path in failure and "app.legacy.papers" in failure for failure in failures), failures)

    def test_rejects_aliased_importlib_legacy_import(self):
        algorithm_path = "backend/python-worker/app/aliased_dynamic_algorithm.py"
        self.write_source(
            algorithm_path,
            'from importlib import import_module as load\nmodule = load("app.legacy.foo")\n',
        )

        failures = self.check_boundaries()

        self.assertTrue(any(algorithm_path in failure and "app.legacy.foo" in failure for failure in failures), failures)

    def test_exact_allowlist_entry_does_not_allow_new_pattern_in_same_file(self):
        allowed = {
            "rule": "python-worker-business-api",
            "path": "backend/python-worker/app/worker_routes.py",
            "pattern": "/api/question-bank/questions",
            "count": 1,
        }
        self.write_config([allowed], [allowed])
        self.write_baseline([allowed])
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

        failures = self.check_boundaries()

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
        self.write_baseline([allowed])
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

        failures = self.check_boundaries()

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
        self.write_baseline([frozen])

        failures = self.check_boundaries()

        self.assertTrue(any("not present in protected baseline" in failure for failure in failures), failures)

    def test_removed_violation_and_allowlist_entry_are_accepted(self):
        frozen = {
            "rule": "python-worker-business-api",
            "path": "backend/python-worker/app/worker_routes.py",
            "pattern": "/api/question-bank/questions",
            "count": 1,
        }
        self.write_config([frozen], [])
        self.write_baseline([frozen])

        failures = self.check_boundaries()

        self.assertEqual([], failures)

    def test_allowlist_rejects_glob_paths(self):
        broad_entry = {
            "rule": "python-worker-business-api",
            "path": "backend/python-worker/app/**",
            "pattern": "/api/question-bank/questions",
            "count": 1,
        }
        self.write_config([broad_entry], [broad_entry])
        self.write_baseline([broad_entry])

        failures = self.check_boundaries()

        self.assertTrue(any("must name one exact file" in failure for failure in failures), failures)

    def test_allowlist_rejects_directory_paths(self):
        broad_entry = {
            "rule": "python-worker-business-api",
            "path": "backend/python-worker/app",
            "pattern": "/api/question-bank/questions",
            "count": 1,
        }
        self.write_config([broad_entry], [broad_entry])
        self.write_baseline([broad_entry])

        failures = self.check_boundaries()

        self.assertTrue(any("must name one exact file" in failure for failure in failures), failures)

    def test_external_baseline_rejects_synchronized_current_config_expansion(self):
        added = {
            "rule": "python-worker-business-api",
            "path": "backend/python-worker/app/worker_routes.py",
            "pattern": "/api/question-bank/admin",
            "count": 1,
        }
        self.write_config([added], [added])
        self.write_source(added["path"], '@app.get("/api/question-bank/admin")\ndef admin():\n    pass\n')

        failures = self.check_boundaries()

        self.assertTrue(any("not present in protected baseline" in failure for failure in failures), failures)

    def test_missing_protected_baseline_fails_closed_with_bootstrap_guidance(self):
        failures = check_boundaries(self.repo_root, self.config_path, environment={})

        self.assertTrue(any("protected baseline unavailable" in failure for failure in failures), failures)
        self.assertTrue(any("--baseline-config" in failure for failure in failures), failures)

    def test_environment_can_inject_protected_baseline(self):
        added = {
            "rule": "python-worker-business-api",
            "path": "backend/python-worker/app/worker_routes.py",
            "pattern": "/api/question-bank/admin",
            "count": 1,
        }
        self.write_config([added], [added])

        failures = check_boundaries(
            self.repo_root,
            self.config_path,
            environment={"OCRFLOW_BOUNDARY_BASELINE_CONFIG": str(self.baseline_config_path)},
        )

        self.assertTrue(any("not present in protected baseline" in failure for failure in failures), failures)

    def test_cli_accepts_protected_baseline_config(self):
        added = {
            "rule": "python-worker-business-api",
            "path": "backend/python-worker/app/worker_routes.py",
            "pattern": "/api/question-bank/admin",
            "count": 1,
        }
        self.write_config([added], [added])
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            return_code = boundary_main(
                [
                    "--root",
                    str(self.repo_root),
                    "--config",
                    str(self.config_path),
                    "--baseline-config",
                    str(self.baseline_config_path),
                ]
            )

        self.assertEqual(1, return_code)
        self.assertIn("not present in protected baseline", output.getvalue())

    def test_default_baseline_comes_from_config_introduction_commit(self):
        subprocess.run(["git", "init", "-q"], cwd=self.repo_root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.repo_root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo_root, check=True)
        subprocess.run(["git", "add", "config/ocrflow-boundaries.json"], cwd=self.repo_root, check=True)
        subprocess.run(["git", "commit", "-qm", "add protected boundary baseline"], cwd=self.repo_root, check=True)
        added = {
            "rule": "python-worker-business-api",
            "path": "backend/python-worker/app/worker_routes.py",
            "pattern": "/api/question-bank/admin",
            "count": 1,
        }
        self.write_config([added], [added])
        self.write_source(added["path"], '@app.get("/api/question-bank/admin")\ndef admin():\n    pass\n')

        failures = check_boundaries(self.repo_root, self.config_path)

        self.assertTrue(any("not present in protected baseline" in failure for failure in failures), failures)

    def test_depth_one_clone_rejects_git_history_as_unprotected_baseline(self):
        source_repo = self.repo_root / "source-repo"
        source_repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=source_repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=source_repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=source_repo, check=True)
        source_config = source_repo / "config" / "ocrflow-boundaries.json"
        source_config.parent.mkdir(parents=True)
        source_config.write_text(json.dumps({"version": 1, "allowlist": []}), encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=source_repo, check=True)
        subprocess.run(["git", "commit", "-qm", "add boundary baseline"], cwd=source_repo, check=True)

        added = {
            "rule": "python-worker-business-api",
            "path": "backend/python-worker/app/worker_routes.py",
            "pattern": "/api/question-bank/admin",
            "count": 1,
        }
        source_config.write_text(json.dumps({"version": 1, "allowlist": [added]}), encoding="utf-8")
        source_path = source_repo / added["path"]
        source_path.parent.mkdir(parents=True)
        source_path.write_text('@app.get("/api/question-bank/admin")\ndef admin():\n    pass\n', encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=source_repo, check=True)
        subprocess.run(["git", "commit", "-qm", "expand boundary allowlist"], cwd=source_repo, check=True)

        clone = self.repo_root / "depth-one-clone"
        subprocess.run(["git", "clone", "-q", "--depth", "1", source_repo.as_uri(), str(clone)], check=True)

        failures = check_boundaries(clone, clone / "config" / "ocrflow-boundaries.json", environment={})

        self.assertTrue(any("shallow repository" in failure for failure in failures), failures)
        self.assertTrue(any("--baseline-config" in failure for failure in failures), failures)

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

    def test_portability_uses_injected_protected_baseline(self):
        added = {
            "rule": "python-worker-business-api",
            "path": "backend/python-worker/app/worker_routes.py",
            "pattern": "/api/question-bank/admin",
            "count": 1,
        }
        self.write_config([added], [added])
        failures: list[str] = []

        with (
            mock.patch.object(portability, "ROOT", self.repo_root),
            mock.patch.dict(os.environ, {"OCRFLOW_BOUNDARY_BASELINE_CONFIG": str(self.baseline_config_path)}, clear=True),
        ):
            portability.check_architecture_boundaries(failures)

        self.assertTrue(any("not present in protected baseline" in failure for failure in failures), failures)


if __name__ == "__main__":
    unittest.main()
