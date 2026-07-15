#!/usr/bin/env python3
"""Regression tests for the question-engine delivery boundary."""

from __future__ import annotations

import unittest

import package_question_engine_delivery as delivery


class DeliveryBoundaryTest(unittest.TestCase):
    def test_startup_dependencies_are_individually_required(self) -> None:
        startup_dependencies = (
            "scripts/docker-entrypoint.sh",
            "scripts/start_server_docker.sh",
            "scripts/test_docker_entrypoint.py",
        )
        for missing in startup_dependencies:
            with self.subTest(missing=missing):
                self.assertIn(missing, delivery.REQUIRED_IN_PACKAGE)
                files = [delivery.ROOT / relative for relative in delivery.REQUIRED_IN_PACKAGE if relative != missing]
                self.assertIn(
                    f"missing required delivery file: {missing}",
                    delivery.validate(files),
                )

    def test_mineru_rebuild_tool_and_tests_are_individually_required(self) -> None:
        rebuild_dependencies = (
            "scripts/rebuild_mineru_venv.py",
            "scripts/test_rebuild_mineru_venv.py",
            "scripts/rollback_mineru_venv.sh",
            "scripts/test_rollback_mineru_venv.py",
        )
        for missing in rebuild_dependencies:
            with self.subTest(missing=missing):
                self.assertIn(missing, delivery.REQUIRED_IN_PACKAGE)
                files = [delivery.ROOT / relative for relative in delivery.REQUIRED_IN_PACKAGE if relative != missing]
                self.assertIn(
                    f"missing required delivery file: {missing}",
                    delivery.validate(files),
                )


if __name__ == "__main__":
    unittest.main()
