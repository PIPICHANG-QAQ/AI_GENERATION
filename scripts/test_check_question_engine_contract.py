#!/usr/bin/env python3
"""Unit tests for deterministic contract and architecture checks."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import check_question_engine_contract as contract_check


class MermaidStructureCheckTest(unittest.TestCase):
    def test_reports_declared_mmd_node_missing_from_svg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mmd = root / "flow.mmd"
            svg = root / "flow.svg"
            mmd.write_text(
                'flowchart LR\n  Present["Present"]\n  Missing["Missing"]\n  Present --> Missing\n',
                encoding="utf-8",
            )
            svg.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg"><g id="flowchart-Present-0"/></svg>',
                encoding="utf-8",
            )

            validator = getattr(contract_check, "validate_mermaid_svg_pair", None)
            self.assertIsNotNone(validator, "Mermaid structural consistency validator is missing")
            failures = validator(mmd, svg)

        self.assertEqual(["flow.svg: missing rendered node id for Missing"], failures)

    def test_worker_bundle_schema_requires_compatibility_artifact_root(self) -> None:
        worker_contract = (
            Path(__file__).resolve().parents[1] / "question-engine/openapi/worker.v1.yaml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "required: [schemaVersion, documentId, inputSha256, canonicalMarkdown, artifactRoot]",
            worker_contract,
        )


if __name__ == "__main__":
    unittest.main()
