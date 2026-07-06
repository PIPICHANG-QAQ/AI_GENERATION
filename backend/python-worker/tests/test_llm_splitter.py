import os
import unittest
from unittest.mock import patch

from app.llm_splitter import (
    llm_status,
    normalize_enriched_question,
    normalize_llm_result,
    preserve_local_boundaries_after_truncation,
    standardize_markdown_with_llm,
)


class LlmSplitterTest(unittest.TestCase):
    def test_llm_status_prefers_deepseek_settings_when_deepseek_key_exists(self):
        with patch.dict(
            os.environ,
            {
                "DEEPSEEK_API_KEY": "deepseek-key",
                "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
                "DEEPSEEK_MODEL": "deepseek-v4-pro",
                "DASHSCOPE_API_KEY": "legacy-key",
                "DASHSCOPE_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "DASHSCOPE_MODEL": "qwen-plus",
            },
            clear=True,
        ):
            status = llm_status()

        self.assertEqual("deepseek", status["provider"])
        self.assertEqual("deepseek-v4-pro", status["model"])
        self.assertEqual("https://api.deepseek.com", status["baseUrl"])

    def test_llm_status_uses_legacy_gateway_when_only_dashscope_key_exists(self):
        with patch.dict(
            os.environ,
            {
                "DASHSCOPE_API_KEY": "legacy-key",
                "DASHSCOPE_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "DASHSCOPE_MODEL": "deepseek-v4-pro",
            },
            clear=True,
        ):
            status = llm_status()

        self.assertEqual("dashscope", status["provider"])
        self.assertEqual("deepseek-v4-pro", status["model"])
        self.assertEqual("https://dashscope.aliyuncs.com/compatible-mode/v1", status["baseUrl"])

    def test_standardize_failure_returns_metadata_without_name_error(self):
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key", "ENABLE_LLM_SPLIT": "true"}):
            with patch("app.llm_splitter.httpx.Client", side_effect=RuntimeError("llm unavailable")):
                standardized, metadata = standardize_markdown_with_llm("题干 $x+1=2$")

        self.assertIsNone(standardized)
        self.assertEqual("llm unavailable", metadata["error"])
        self.assertEqual(0, metadata["imageCount"])

    def test_normalize_llm_result_keeps_sub_questions_inside_parent(self):
        raw = {
            "sections": [
                {
                    "id": "section_1",
                    "title": "解答题",
                    "type": "solution",
                    "questions": [
                        {
                            "id": "q1",
                            "number": 21,
                            "type": "solution",
                            "stemMarkdown": "已知函数 $f(x)$。",
                            "answer": "父题答案不应保留",
                            "analysis": "父题解析不应保留",
                            "subQuestions": [
                                {
                                    "id": "q1_sub1",
                                    "label": "(1)",
                                    "stemMarkdown": "求 $f(0)$。",
                                    "answer": "1",
                                    "analysis": "代入 $x=0$。",
                                },
                                {
                                    "id": "q1_sub2",
                                    "label": "(2)",
                                    "stemMarkdown": "求单调区间。",
                                    "answer": "递增",
                                    "analysis": "由导数判断。",
                                },
                            ],
                        }
                    ],
                }
            ]
        }

        result = normalize_llm_result(raw, [], {})
        parent = result["sections"][0]["questions"][0]

        self.assertEqual("", parent["answer"])
        self.assertEqual("", parent["analysis"])
        self.assertEqual(2, len(parent["subQuestions"]))
        self.assertEqual(parent["subQuestions"], parent["children"])
        self.assertEqual("(1)", parent["subQuestions"][0]["label"])
        self.assertEqual("代入 $x=0$。", parent["subQuestions"][0]["analysis"])

    def test_enriched_question_maps_solution_to_sub_questions(self):
        enriched = normalize_enriched_question(
            {
                "id": "q1",
                "type": "solution",
                "answer": "父题答案不应保留",
                "analysis": "父题解析不应保留",
                "subQuestions": [
                    {
                        "id": "q1_sub1",
                        "label": "(1)",
                        "type": "fill_blank",
                        "answer": "A",
                        "analysis": "第一问解析",
                        "knowledgePoints": ["函数"],
                        "contextMatched": True,
                        "answerEvidence": "(1) A",
                        "analysisEvidence": "(1) 第一问解析",
                    }
                ],
            }
        )

        self.assertEqual("", enriched["answer"])
        self.assertEqual("", enriched["analysis"])
        self.assertEqual("A", enriched["subQuestions"][0]["answer"])
        self.assertEqual("第一问解析", enriched["subQuestions"][0]["analysis"])

    def test_enriched_sub_question_without_evidence_is_cleared(self):
        enriched = normalize_enriched_question(
            {
                "id": "q1",
                "type": "solution",
                "subQuestions": [
                    {
                        "id": "q1_sub1",
                        "label": "(1)",
                        "answer": "A",
                        "analysis": "缺少证据的解析",
                        "contextMatched": False,
                    }
                ],
            }
        )

        sub_question = enriched["subQuestions"][0]
        self.assertEqual("", sub_question["answer"])
        self.assertEqual("", sub_question["analysis"])
        self.assertTrue(any("缺少 OCR 上下文证据" in warning for warning in sub_question["warnings"]))

    def test_preserves_local_boundaries_after_llm_truncation(self):
        parsed = {
            "sections": [{"id": "section_1", "title": "一、选择题", "type": "choice", "start": 0, "end": 100}],
            "questions": [{"id": "q_1", "number": 1, "start": 0, "end": 50, "sectionId": "section_1"}],
        }
        local = {
            "sections": [
                {"id": "section_1", "title": "一、选择题", "type": "choice", "start": 0, "end": 100},
                {"id": "section_2", "title": "三、解答题", "type": "solution", "start": 120, "end": 200},
            ],
            "questions": [
                {"id": "q_1", "number": 1, "start": 0, "end": 50, "sectionId": "section_1"},
                {"id": "q_21", "number": 21, "start": 150, "end": 190, "sectionId": "section_2"},
            ],
        }

        merged = preserve_local_boundaries_after_truncation(parsed, local, max_chars=100, source_length=200)

        self.assertEqual(["q_1", "q_21"], [question["id"] for question in merged["questions"]])
        self.assertEqual({"section_1", "section_2"}, {section["id"] for section in merged["sections"]})
        self.assertTrue(any("截断点后" in warning for warning in merged["warnings"]))


if __name__ == "__main__":
    unittest.main()
