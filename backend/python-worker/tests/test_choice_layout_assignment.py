import unittest

from app.choice_layout_assignment import assign_choice_images


class ChoiceLayoutAssignmentTest(unittest.TestCase):
    def test_assigns_two_by_two_grid_independent_of_image_serialization_order(self):
        items = self._grid_labels()
        items.extend(
            [
                self._image("images/d.png", 0, [520, 340, 700, 460]),
                self._image("images/a.png", 0, [120, 140, 300, 260]),
                self._image("images/c.png", 0, [120, 340, 300, 460]),
                self._image("images/b.png", 0, [520, 140, 700, 260]),
            ]
        )

        result = assign_choice_images(items, ["A", "B", "C", "D"])

        self.assertEqual(
            {
                "images/a.png": "A",
                "images/b.png": "B",
                "images/c.png": "C",
                "images/d.png": "D",
            },
            {image_id: value["optionLabel"] for image_id, value in result["assignments"].items()},
        )
        self.assertEqual([], result["blockingReasons"])

    def test_assigns_images_that_appear_before_each_vertical_option_label(self):
        items = [
            self._image("images/tire.png", 0, [220, 80, 520, 250]),
            self._label("A", 0, [100, 260, 140, 290]),
            self._image("images/camel.png", 0, [220, 310, 520, 450]),
            self._label("B", 0, [100, 460, 140, 490]),
            self._image("images/knife.png", 0, [220, 510, 520, 650]),
            self._label("C", 0, [100, 660, 140, 690]),
            self._image("images/tack.png", 0, [220, 710, 520, 850]),
            self._label("D", 0, [100, 860, 140, 890]),
        ]

        result = assign_choice_images(items, ["A", "B", "C", "D"])

        self.assertEqual(
            ["A", "B", "C", "D"],
            [result["assignments"][f"images/{name}.png"]["optionLabel"] for name in ("tire", "camel", "knife", "tack")],
        )

    def test_keeps_cross_page_choice_cells_in_one_assignment(self):
        items = [
            self._label("A", 0, [100, 100, 140, 130]),
            self._label("B", 0, [500, 100, 540, 130]),
            self._image("images/a.png", 0, [120, 150, 300, 280]),
            self._image("images/b.png", 0, [520, 150, 700, 280]),
            self._label("C", 1, [100, 100, 140, 130]),
            self._label("D", 1, [500, 100, 540, 130]),
            self._image("images/c.png", 1, [120, 150, 300, 280]),
            self._image("images/d.png", 1, [520, 150, 700, 280]),
        ]

        result = assign_choice_images(items, ["A", "B", "C", "D"])

        self.assertEqual(
            {"images/a.png": "A", "images/b.png": "B", "images/c.png": "C", "images/d.png": "D"},
            {image_id: value["optionLabel"] for image_id, value in result["assignments"].items()},
        )
        self.assertEqual([0, 1], result["pageIndexes"])

    def test_marks_small_global_margin_for_review(self):
        items = [
            self._label("A", 0, [100, 100, 140, 130]),
            self._label("B", 0, [300, 100, 340, 130]),
            self._image("images/center.png", 0, [190, 150, 250, 230]),
        ]

        result = assign_choice_images(items, ["A", "B"])

        assignment = result["assignments"]["images/center.png"]
        self.assertEqual("needs_review", assignment["reviewStatus"])
        self.assertLess(assignment["confidence"], 0.95)
        self.assertIn("layout_assignment_ambiguous", result["blockingReasons"])
        self.assertEqual(1, len(assignment["alternatives"]))

    @staticmethod
    def _label(label, page, bbox):
        return {
            "type": "text",
            "text": f"{label}.",
            "pageIndex": page,
            "bbox": bbox,
            "pageWidth": 1000,
            "pageHeight": 1000,
        }

    @staticmethod
    def _image(image_ref, page, bbox):
        return {
            "type": "image",
            "imageRef": image_ref,
            "pageIndex": page,
            "bbox": bbox,
            "pageWidth": 1000,
            "pageHeight": 1000,
        }

    @classmethod
    def _grid_labels(cls):
        return [
            cls._label("A", 0, [100, 100, 140, 130]),
            cls._label("B", 0, [500, 100, 540, 130]),
            cls._label("C", 0, [100, 300, 140, 330]),
            cls._label("D", 0, [500, 300, 540, 330]),
        ]


if __name__ == "__main__":
    unittest.main()
