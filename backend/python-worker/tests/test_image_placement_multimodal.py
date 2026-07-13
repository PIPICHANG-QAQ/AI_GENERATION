import unittest

from app.image_placement_multimodal import resolve_ambiguous_assignments


class ImagePlacementMultimodalTest(unittest.TestCase):
    def test_calls_resolver_only_for_mid_confidence_or_conflict(self):
        calls = []

        def resolver(payload):
            calls.append(payload)
            return {"assignments": {"images/a.png": "A", "images/b.png": "B"}}

        candidates = {
            "images/a.png": {"optionLabel": "A", "confidence": 0.84},
            "images/b.png": {"optionLabel": "B", "confidence": 0.84},
        }
        result = resolve_ambiguous_assignments([], candidates, ["A", "B"], resolver, enabled=True)
        high = resolve_ambiguous_assignments(
            [], {"images/a.png": {"optionLabel": "A", "confidence": 0.97}}, ["A"], resolver, enabled=True
        )
        low = resolve_ambiguous_assignments(
            [], {"images/a.png": {"optionLabel": "A", "confidence": 0.5}}, ["A"], resolver, enabled=True
        )

        self.assertTrue(result["applied"])
        self.assertEqual(1, len(calls))
        self.assertEqual("not-eligible", high["reason"])
        self.assertEqual("not-eligible", low["reason"])

    def test_rejects_unknown_images_invalid_labels_and_duplicate_options(self):
        candidates = {
            "images/a.png": {"optionLabel": "A", "confidence": 0.84},
            "images/b.png": {"optionLabel": "B", "confidence": 0.84},
        }
        responses = [
            {"assignments": {"images/missing.png": "A"}},
            {"assignments": {"images/a.png": "Z", "images/b.png": "B"}},
            {"assignments": {"images/a.png": "A", "images/b.png": "A"}},
        ]

        for response in responses:
            result = resolve_ambiguous_assignments(
                [], candidates, ["A", "B"], lambda _payload, value=response: value, enabled=True
            )
            self.assertFalse(result["applied"])
            self.assertEqual("invalid-response", result["reason"])

    def test_timeout_keeps_candidates_for_review(self):
        def resolver(_payload):
            raise TimeoutError("vision timeout")

        candidates = {"images/a.png": {"optionLabel": "A", "confidence": 0.84}}

        result = resolve_ambiguous_assignments([], candidates, ["A"], resolver, enabled=True, has_conflict=True)

        self.assertFalse(result["applied"])
        self.assertEqual("resolver-failed", result["reason"])
        self.assertEqual(candidates, result["candidates"])

    def test_disabled_fallback_never_calls_resolver(self):
        def resolver(_payload):
            raise AssertionError("must not be called")

        result = resolve_ambiguous_assignments(
            [], {"images/a.png": {"optionLabel": "A", "confidence": 0.84}}, ["A"], resolver, enabled=False
        )

        self.assertEqual("disabled", result["reason"])


if __name__ == "__main__":
    unittest.main()
