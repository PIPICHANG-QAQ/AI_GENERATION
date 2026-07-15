#!/usr/bin/env python3
"""Unit tests for deterministic contract and architecture checks."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import check_question_engine_contract as contract_check


class MermaidStructureCheckTest(unittest.TestCase):
    def write_pair(self, root: Path, mmd_text: str, svg_text: str) -> tuple[Path, Path]:
        mmd = root / "flow.mmd"
        svg = root / "flow.svg"
        mmd.write_text(mmd_text, encoding="utf-8")
        svg.write_text(svg_text, encoding="utf-8")
        return mmd, svg

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
                '<svg xmlns="http://www.w3.org/2000/svg"><g id="flowchart-Present-0"><text>Present</text></g></svg>',
                encoding="utf-8",
            )

            validator = getattr(contract_check, "validate_mermaid_svg_pair", None)
            self.assertIsNotNone(validator, "Mermaid structural consistency validator is missing")
            failures = validator(mmd, svg)

        self.assertEqual(["flow.svg: missing rendered node id for Missing"], failures)

    def test_reports_stale_rendered_node_label_with_same_node_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mmd, svg = self.write_pair(
                Path(tmp),
                'flowchart LR\n  A["Current<br/>Label"]\n',
                '<svg xmlns="http://www.w3.org/2000/svg"><g id="flowchart-A-0"><text>Stale Label</text></g></svg>',
            )

            failures = contract_check.validate_mermaid_svg_pair(mmd, svg)

        self.assertEqual(["flow.svg: stale rendered label for A: expected 'Current Label'"], failures)

    def test_reports_missing_rendered_directed_edge_with_same_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mmd, svg = self.write_pair(
                Path(tmp),
                'flowchart LR\n  A["A"]\n  B["B"]\n  A --> B\n',
                '<svg xmlns="http://www.w3.org/2000/svg"><g id="flowchart-A-0"><text>A</text></g><g id="flowchart-B-1"><text>B</text></g></svg>',
            )

            failures = contract_check.validate_mermaid_svg_pair(mmd, svg)

        self.assertEqual(["flow.svg: missing rendered directed edge A -> B"], failures)

    def test_reports_extra_reverse_rendered_edge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mmd, svg = self.write_pair(
                Path(tmp),
                'flowchart LR\n  A["A"]\n  B["B"]\n  A --> B\n',
                '<svg xmlns="http://www.w3.org/2000/svg">'
                '<path data-id="L_A_B_0"/><path data-id="L_B_A_0"/>'
                '<g id="flowchart-A-0"><text>A</text></g>'
                '<g id="flowchart-B-1"><text>B</text></g>'
                '</svg>',
            )

            failures = contract_check.validate_mermaid_svg_pair(mmd, svg)

        self.assertEqual(["flow.svg: unexpected rendered directed edge B -> A"], failures)

    def test_resolves_ambiguous_encoded_edge_to_unique_declared_edge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mmd, svg = self.write_pair(
                Path(tmp),
                'flowchart LR\n'
                '  A["A"]\n'
                '  B_C["B_C"]\n'
                '  A_B["A_B"]\n'
                '  C["C"]\n'
                '  A --> B_C\n',
                '<svg xmlns="http://www.w3.org/2000/svg">'
                '<path data-id="L_A_B_C_0"/><path data-id="L_A_B_C_1"/>'
                '<g id="flowchart-A-0"><text>A</text></g>'
                '<g id="flowchart-B_C-1"><text>B_C</text></g>'
                '<g id="flowchart-A_B-2"><text>A_B</text></g>'
                '<g id="flowchart-C-3"><text>C</text></g>'
                '</svg>',
            )

            failures = contract_check.validate_mermaid_svg_pair(mmd, svg)

        self.assertEqual([], failures)

    def test_reports_ambiguous_encoded_edge_with_sorted_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mmd, svg = self.write_pair(
                Path(tmp),
                'flowchart LR\n'
                '  A["A"]\n'
                '  B_C["B_C"]\n'
                '  A_B["A_B"]\n'
                '  C["C"]\n',
                '<svg xmlns="http://www.w3.org/2000/svg">'
                '<path data-id="L_A_B_C_0"/>'
                '<g id="flowchart-A-0"><text>A</text></g>'
                '<g id="flowchart-B_C-1"><text>B_C</text></g>'
                '<g id="flowchart-A_B-2"><text>A_B</text></g>'
                '<g id="flowchart-C-3"><text>C</text></g>'
                '</svg>',
            )

            failures = contract_check.validate_mermaid_svg_pair(mmd, svg)

        self.assertEqual(
            ["flow.svg: ambiguous rendered edge A_B_C: candidates A -> B_C, A_B -> C"],
            failures,
        )

    def test_reports_missing_rendered_class_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mmd, svg = self.write_pair(
                Path(tmp),
                'flowchart LR\n  A["A"]\n  class A important;\n',
                '<svg xmlns="http://www.w3.org/2000/svg"><g id="flowchart-A-0" class="node default"><text>A</text></g></svg>',
            )

            failures = contract_check.validate_mermaid_svg_pair(mmd, svg)

        self.assertEqual(["flow.svg: missing rendered class important for A"], failures)

    def test_reports_obsolete_source_defined_custom_class_but_ignores_renderer_utility_class(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mmd, svg = self.write_pair(
                Path(tmp),
                'flowchart LR\n  A["A"]\n  class A current;\n  classDef current fill:#fff;\n  classDef obsolete fill:#000;\n',
                '<svg xmlns="http://www.w3.org/2000/svg">'
                '<g id="flowchart-A-0" class="node default current obsolete renderer-utility"><text>A</text></g>'
                '</svg>',
            )

            failures = contract_check.validate_mermaid_svg_pair(mmd, svg)

        self.assertEqual(["flow.svg: unexpected rendered class obsolete for A"], failures)

    def test_reports_source_defined_custom_class_assigned_to_wrong_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mmd, svg = self.write_pair(
                Path(tmp),
                'flowchart LR\n  A["A"]\n  B["B"]\n  class A important;\n  classDef important fill:#fff;\n',
                '<svg xmlns="http://www.w3.org/2000/svg">'
                '<g id="flowchart-A-0" class="node default"><text>A</text></g>'
                '<g id="flowchart-B-1" class="node default important"><text>B</text></g>'
                '</svg>',
            )

            failures = contract_check.validate_mermaid_svg_pair(mmd, svg)

        self.assertEqual(
            [
                "flow.svg: missing rendered class important for A",
                "flow.svg: unexpected rendered class important for B",
            ],
            failures,
        )

    def test_reports_removed_rendered_endpoint_with_stale_edge_and_custom_class(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mmd, svg = self.write_pair(
                Path(tmp),
                'flowchart LR\n  B["B"]\n  classDef retired fill:#000;\n',
                '<svg xmlns="http://www.w3.org/2000/svg">'
                '<path data-id="L_B_Removed_Node-v2_0"/>'
                '<g id="prefix-flowchart-B-0" class="node default"><text>B</text></g>'
                '<g id="prefix-flowchart-Removed_Node-v2-7" class="node default retired renderer-utility">'
                '<text>Removed</text></g>'
                '</svg>',
            )

            failures = contract_check.validate_mermaid_svg_pair(mmd, svg)

        self.assertEqual(
            [
                "flow.svg: unexpected rendered node id for Removed_Node-v2",
                "flow.svg: unexpected rendered class retired for Removed_Node-v2",
                "flow.svg: unexpected rendered directed edge B -> Removed_Node-v2",
            ],
            failures,
        )

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
