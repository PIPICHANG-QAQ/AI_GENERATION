import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ocr_processing import apply_auto_semantic_repairs, build_llm_metrics, realign_question_images_from_layout


class OcrProcessingTest(unittest.TestCase):
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

    def test_realign_question_images_uses_mineru_geometry_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "paper_content_list.json").write_text(
                json.dumps(
                    [
                        {"type": "text", "text": "7. 第七题题干", "bbox": [100, 700, 500, 740], "page_idx": 0},
                        {"type": "image", "img_path": "images/q8.png", "bbox": [110, 760, 300, 830], "page_idx": 0},
                        {"type": "text", "text": "8. 第八题题干", "bbox": [100, 750, 520, 860], "page_idx": 0},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            assets = [
                {
                    "name": "q8.png",
                    "path": "paper/auto/images/q8.png",
                    "url": "/files/q8.png",
                }
            ]
            structured = {
                "questions": [
                    {
                        "id": "q7",
                        "number": 7,
                        "stemMarkdown": "第七题题干\n\n![](图1)",
                        "manualMarkdown": "第七题题干\n\n![](图1)",
                        "images": [{"name": "q8.png", "path": "paper/auto/images/q8.png", "url": "/files/q8.png", "label": "图1"}],
                    },
                    {
                        "id": "q8",
                        "number": 8,
                        "stemMarkdown": "第八题题干",
                        "manualMarkdown": "第八题题干",
                        "images": [],
                    },
                ]
            }

            result = realign_question_images_from_layout(structured, output_dir, assets)

        self.assertTrue(result["applied"])
        self.assertEqual(2, result["changed"])
        self.assertEqual([], structured["questions"][0]["images"])
        self.assertNotIn("![](图1)", structured["questions"][0]["stemMarkdown"])
        self.assertEqual("paper/auto/images/q8.png", structured["questions"][1]["images"][0]["path"])
        self.assertIn("![](图1)", structured["questions"][1]["stemMarkdown"])


if __name__ == "__main__":
    unittest.main()
