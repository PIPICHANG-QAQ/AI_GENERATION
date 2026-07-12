import unittest

from app.image_placement import (
    build_image_placements,
    reconcile_image_placements,
    reconcile_structure_image_placements,
    validate_image_placements,
)


class ImagePlacementTest(unittest.TestCase):
    def test_structure_reconciliation_uses_only_question_layout_interval(self):
        placement = self._placement("p1", "images/a.png", "unassigned", 0.0)
        question = {
            "id": "q1",
            "sourceEvidence": {"start": 10, "end": 80},
            "imagePlacements": [placement],
            "children": [],
        }
        structured = {"sections": [{"questions": [question]}], "questions": [question]}
        layout_items = [
            {"order": 0, "type": "text", "text": "A.", "pageIndex": 0, "bbox": [100, 100, 140, 130]},
            {
                "order": 1,
                "type": "image",
                "imageRef": "images/a.png",
                "pageIndex": 0,
                "bbox": [120, 140, 300, 260],
                "markdownStart": 30,
                "markdownEnd": 50,
            },
            {"order": 2, "type": "text", "text": "B.", "pageIndex": 0, "bbox": [500, 500, 540, 530], "markdownStart": 100},
        ]

        summary = reconcile_structure_image_placements(structured, layout_items)

        self.assertEqual("A", question["imagePlacements"][0]["target"]["optionLabel"])
        self.assertEqual(1, summary["methodCounts"]["geometry"])

    def test_geometry_maps_two_column_grid_independent_of_serialized_image_order(self):
        image_positions = {
            "images/d.png": [520, 340, 700, 460],
            "images/a.png": [120, 140, 300, 260],
            "images/c.png": [120, 340, 300, 460],
            "images/b.png": [520, 140, 700, 260],
        }
        placements = [
            self._placement(f"p{index}", image_id, "unassigned", 0.0)
            for index, image_id in enumerate(image_positions)
        ]
        layout_items = [
            {"blockId": "label-a", "type": "text", "text": "A.", "pageIndex": 0, "bbox": [100, 100, 140, 130]},
            {"blockId": "label-b", "type": "text", "text": "B.", "pageIndex": 0, "bbox": [500, 100, 540, 130]},
            {"blockId": "label-c", "type": "text", "text": "C.", "pageIndex": 0, "bbox": [100, 300, 140, 330]},
            {"blockId": "label-d", "type": "text", "text": "D.", "pageIndex": 0, "bbox": [500, 300, 540, 330]},
            *[
                {"blockId": f"image-{index}", "type": "image", "imageRef": image_id, "pageIndex": 0, "bbox": bbox}
                for index, (image_id, bbox) in enumerate(image_positions.items())
            ],
        ]

        reconciled, summary = reconcile_image_placements(placements, layout_items)

        by_image = {item["imageId"]: item["target"]["optionLabel"] for item in reconciled}
        self.assertEqual(
            {"images/a.png": "A", "images/b.png": "B", "images/c.png": "C", "images/d.png": "D"},
            by_image,
        )
        self.assertEqual(4, summary["methodCounts"]["geometry"])
        self.assertEqual(0, summary["unassignedCount"])

    def test_geometry_conflict_does_not_override_explicit_offset(self):
        placements = [self._placement("p1", "paper/auto/images/a.png", "option", 0.99, option_label="A")]
        layout_items = [
            {"type": "text", "text": "A.", "pageIndex": 0, "bbox": [100, 100, 140, 130]},
            {"type": "text", "text": "B.", "pageIndex": 0, "bbox": [500, 100, 540, 130]},
            {"type": "image", "imageRef": "images/a.png", "pageIndex": 0, "bbox": [520, 140, 700, 260]},
        ]

        reconciled, summary = reconcile_image_placements(placements, layout_items)

        self.assertEqual("A", reconciled[0]["target"]["optionLabel"])
        self.assertIn("geometry-conflict", reconciled[0]["inference"]["reasons"])
        self.assertEqual(1, summary["conflictCount"])

    def test_explicit_offsets_assign_stem_option_subquestion_and_unassigned(self):
        boundary = {
            "id": "q1",
            "start": 0,
            "end": 300,
            "options": [
                {"label": "A", "start": 100, "end": 150},
                {"label": "B", "start": 150, "end": 200},
            ],
            "subQuestions": [
                {"id": "q1-sub-1", "label": "(1)", "start": 220, "end": 280},
            ],
        }
        images = [
            {"path": "images/stem.png", "start": 50, "end": 60, "pageIndex": 0, "bbox": [10, 20, 30, 40]},
            {"path": "images/a.png", "start": 120, "end": 130},
            {"path": "images/sub.png", "start": 240, "end": 250},
            {"path": "images/outside.png", "start": 330, "end": 340},
        ]

        placements = build_image_placements(boundary, images)

        self.assertEqual(
            ["stem", "option", "subquestion", "unassigned"],
            [placement["target"]["kind"] for placement in placements],
        )
        self.assertEqual("A", placements[1]["target"]["optionLabel"])
        self.assertEqual("q1-sub-1", placements[2]["target"]["subQuestionId"])
        self.assertEqual("explicit-offset", placements[0]["inference"]["method"])
        self.assertEqual([10, 20, 30, 40], placements[0]["sourceEvidence"]["bbox"])
        self.assertEqual("needs_review", placements[3]["reviewStatus"])

    def test_validation_reports_dangling_duplicate_owner_and_unassigned(self):
        images = [{"path": "images/a.png"}, {"path": "images/b.png"}]
        placements = [
            self._placement("p1", "images/a.png", "stem", 0.99),
            self._placement("p2", "images/a.png", "option", 0.99, option_label="A"),
            self._placement("p3", "images/missing.png", "stem", 0.99),
            self._placement("p4", "images/b.png", "unassigned", 0.0),
        ]

        result = validate_image_placements(images, placements, question_type="choice", option_count=0)

        self.assertFalse(result["valid"])
        self.assertTrue(any("不存在" in error for error in result["errors"]))
        self.assertTrue(any("多个高置信归属" in error for error in result["errors"]))
        self.assertTrue(any("未归属" in warning for warning in result["warnings"]))
        self.assertTrue(any("没有有效选项" in warning for warning in result["warnings"]))

    @staticmethod
    def _placement(placement_id, image_id, kind, confidence, option_label=None):
        target = {"kind": kind}
        if option_label:
            target["optionLabel"] = option_label
        return {
            "placementId": placement_id,
            "imageId": image_id,
            "target": target,
            "inference": {"method": "explicit-offset", "confidence": confidence, "reasons": []},
        }


if __name__ == "__main__":
    unittest.main()
