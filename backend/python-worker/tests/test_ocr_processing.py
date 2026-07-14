import inspect
import os
import unittest
from unittest.mock import patch

from app import ocr_processing, question_boundary
from app.ocr_processing import apply_auto_semantic_repairs, build_llm_metrics, select_structure_candidate


class OcrProcessingTest(unittest.TestCase):
    def test_invalid_fallback_does_not_replace_better_primary_candidate(self):
        primary = {
            "questions": [
                {"id": "q24", "number": 24, "options": [{"label": "A"}, {"label": "B"}], "images": [{"path": "q24.png"}]},
                {"id": "q25", "number": 25, "options": [{"label": "A"}, {"label": "B"}], "images": [{"path": "q25.png"}]},
            ]
        }
        fallback = {
            "questions": [
                {"id": "q24", "number": 24, "options": [], "images": []},
                {"id": "q25", "number": 25, "options": [], "images": [{"path": "q24.png"}, {"path": "q25.png"}]},
            ]
        }
        primary_validation = {"valid": False, "errors": ["答案区题号重复"]}
        fallback_validation = {"valid": False, "errors": ["答案区题号重复", "题图归属冲突"]}

        selected, validation = select_structure_candidate(
            primary,
            primary_validation,
            fallback,
            fallback_validation,
        )

        self.assertIs(primary, selected)
        self.assertFalse(validation["fallback"])
        self.assertTrue(validation["requiresReview"])
        self.assertEqual(fallback_validation, validation["fallbackValidation"])

    def test_valid_fallback_replaces_invalid_primary_candidate(self):
        primary = {"questions": [{"id": "q1", "number": 1}]}
        fallback = {"questions": [{"id": "q1", "number": 1}]}

        selected, validation = select_structure_candidate(
            primary,
            {"valid": False, "errors": ["bad boundary"]},
            fallback,
            {"valid": True, "errors": []},
        )

        self.assertIs(fallback, selected)
        self.assertTrue(validation["fallback"])
        self.assertFalse(validation["requiresReview"])

    def test_auto_semantic_repair_skip_mode_does_not_call_llm(self):
        structured = {"sections": [{"questions": [{"id": "q1", "stemMarkdown": '若 5"=4，则求值'}]}], "questions": []}
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "key", "OCR_AUTO_SEMANTIC_REPAIR_MODE": "skip", "ENABLE_LLM_SPLIT": "true"}):
            with patch("app.ocr_processing.standardize_markdown_with_llm") as standardize:
                result = apply_auto_semantic_repairs(structured)

        standardize.assert_not_called()
        self.assertEqual("skipped", result["mode"])
        self.assertEqual(1, result["candidateCount"])

    def test_auto_semantic_repair_inline_concurrent_applies_safe_result(self):
        structured = {"sections": [{"questions": [{"id": "q1", "stemMarkdown": '若 5"=4，则求值'}]}], "questions": []}
        with patch.dict(
            os.environ,
            {
                "DASHSCOPE_API_KEY": "key",
                "OCR_AUTO_SEMANTIC_REPAIR_MODE": "inline-concurrent",
                "LLM_MAX_CONCURRENCY": "2",
                "ENABLE_LLM_SPLIT": "true",
            },
        ):
            with patch(
                "app.ocr_processing.standardize_markdown_with_llm",
                return_value=(
                    "若 $5^n=4$，则求值",
                    {
                        "source": "ai",
                        "provider": "dashscope",
                        "model": "deepseek-v4-pro",
                        "confidence": "high",
                        "corrections": [],
                        "warnings": [],
                        "error": None,
                        "llmCall": {
                            "callType": "standardize",
                            "status": "success",
                            "provider": "dashscope",
                            "model": "deepseek-v4-pro",
                            "durationMs": 42,
                            "error": None,
                        },
                    },
                ),
            ):
                result = apply_auto_semantic_repairs(structured)

        self.assertEqual("inline-concurrent", result["mode"])
        self.assertEqual(1, result["appliedCount"])
        self.assertEqual(1, len(result["llmCalls"]))
        self.assertEqual("standardize", result["llmCalls"][0]["callType"])

    def test_build_llm_metrics_aggregates_call_counts_and_duration(self):
        with patch.dict(os.environ, {"LLM_METRICS_ENABLED": "true"}):
            metrics = build_llm_metrics(
                {"llmCalls": [{"callType": "boundary-refine", "durationMs": 100}]},
                {"llmCalls": [{"callType": "standardize", "durationMs": "25"}]},
            )

        self.assertTrue(metrics["enabled"])
        self.assertEqual(2, metrics["callCount"])
        self.assertEqual(125, metrics["totalDurationMs"])

    def test_collect_outputs_keeps_layout_read_only_for_question_extraction(self):
        collect_outputs_source = inspect.getsource(ocr_processing.collect_outputs_impl)
        detect_boundaries_source = inspect.getsource(question_boundary.detect_local_boundaries)

        self.assertFalse(hasattr(ocr_processing, "question_image_refs_by_layout"))
        self.assertFalse(hasattr(ocr_processing, "question_image_ref_groups_by_layout"))
        self.assertFalse(hasattr(ocr_processing, "realign_question_images_from_layout"))
        self.assertFalse(hasattr(question_boundary, "detect_local_boundaries_with_layout"))
        self.assertNotIn("load_question_layout_items", collect_outputs_source)
        self.assertNotIn("realign_question_images_from_layout", collect_outputs_source)
        self.assertNotIn("layout_items", detect_boundaries_source)
        self.assertNotIn("layoutItem", detect_boundaries_source)
        self.assertIn("layout-read-only", collect_outputs_source)
        self.assertIn("reconcile_structure_image_placements", collect_outputs_source)


if __name__ == "__main__":
    unittest.main()
