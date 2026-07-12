import json
import os
import unittest
from contextlib import nullcontext
from unittest.mock import patch

from app.llm_splitter import (
    boundary_refinement_skipped_metadata,
    llm_runtime_options,
    llm_status,
    generate_question_analysis_with_llm,
    merge_boundary_chunk_results,
    normalize_enriched_question,
    normalize_llm_result,
    preserve_local_boundaries_after_truncation,
    refine_question_boundaries_with_llm,
    route_llm_endpoints,
    standardize_markdown_with_llm,
)


class LlmSplitterTest(unittest.TestCase):
    def test_boundary_skip_metadata_marks_local_confidence(self):
        metadata = boundary_refinement_skipped_metadata({"highConfidence": True, "reasons": []})

        self.assertEqual("local-boundary", metadata["source"])
        self.assertFalse(metadata["fallback"])
        self.assertEqual("local-high-confidence", metadata["reason"])
        self.assertEqual([], metadata["llmCalls"])

    def test_boundary_refine_failure_returns_sanitized_llm_call_metric(self):
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key", "ENABLE_LLM_SPLIT": "true"}):
            with patch("app.llm_splitter.httpx.Client", side_effect=RuntimeError("llm unavailable")):
                result, metadata = refine_question_boundaries_with_llm(
                    "1. 题干\nA. 1\nB. 2",
                    [],
                    {"questions": [{"id": "q_1"}]},
                )

        self.assertIsNone(result)
        self.assertIn("llmCalls", metadata)
        self.assertEqual("boundary-refine", metadata["llmCalls"][0]["callType"])
        self.assertEqual("failed", metadata["llmCalls"][0]["status"])
        self.assertIn("durationMs", metadata["llmCalls"][0])
        self.assertNotIn("test-key", json.dumps(metadata, ensure_ascii=False))

    def test_merge_boundary_chunk_results_keeps_chunk_order_and_warnings(self):
        local = {
            "sections": [{"id": "section_1", "title": "一、选择题", "type": "choice"}],
            "questions": [{"id": "q_1", "start": 0}, {"id": "q_2", "start": 20}],
        }
        chunks = [
            {"index": 0, "result": {"sections": [], "questions": [{"id": "q_1", "start": 0}], "warnings": ["w1"]}},
            {"index": 1, "result": None, "localBoundaries": {"sections": [], "questions": [{"id": "q_2", "start": 20}]}, "error": "timeout"},
        ]

        merged = merge_boundary_chunk_results(local, chunks)

        self.assertEqual(["q_1", "q_2"], [item["id"] for item in merged["questions"]])
        self.assertTrue(any("timeout" in warning for warning in merged["warnings"]))

    def test_llm_runtime_options_reads_safe_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            options = llm_runtime_options()

        self.assertEqual(1, options["maxConcurrency"])
        self.assertEqual(1, options["boundaryMaxConcurrency"])
        self.assertEqual(1, options["standardizeMaxConcurrency"])
        self.assertEqual(1, options["analysisMaxConcurrency"])
        self.assertEqual(2, options["standardizeMaxAttempts"])
        self.assertEqual(2, options["analysisMaxAttempts"])
        self.assertEqual(5, options["boundaryChunkSize"])
        self.assertEqual("skip", options["autoSemanticRepairMode"])
        self.assertTrue(options["metricsEnabled"])

    def test_llm_runtime_options_clamps_concurrency(self):
        with patch.dict(
            os.environ,
            {
                "LLM_MAX_CONCURRENCY": "99",
                "LLM_BOUNDARY_MAX_CONCURRENCY": "99",
                "LLM_STANDARDIZE_MAX_CONCURRENCY": "99",
                "LLM_ANALYSIS_MAX_CONCURRENCY": "99",
                "LLM_STANDARDIZE_MAX_ATTEMPTS": "99",
                "LLM_ANALYSIS_MAX_ATTEMPTS": "99",
                "LLM_BOUNDARY_CHUNK_SIZE": "0",
                "OCR_AUTO_SEMANTIC_REPAIR_MODE": "inline-concurrent",
                "LLM_METRICS_ENABLED": "false",
            },
            clear=True,
        ):
            options = llm_runtime_options()

        self.assertEqual(8, options["maxConcurrency"])
        self.assertEqual(8, options["boundaryMaxConcurrency"])
        self.assertEqual(16, options["standardizeMaxConcurrency"])
        self.assertEqual(16, options["analysisMaxConcurrency"])
        self.assertEqual(3, options["standardizeMaxAttempts"])
        self.assertEqual(3, options["analysisMaxAttempts"])
        self.assertEqual(1, options["boundaryChunkSize"])
        self.assertEqual("inline-concurrent", options["autoSemanticRepairMode"])
        self.assertFalse(options["metricsEnabled"])

    def test_boundary_concurrency_can_override_general_llm_concurrency(self):
        with patch.dict(
            os.environ,
            {
                "LLM_MAX_CONCURRENCY": "1",
                "LLM_BOUNDARY_MAX_CONCURRENCY": "4",
            },
            clear=True,
        ):
            options = llm_runtime_options()

        self.assertEqual(1, options["maxConcurrency"])
        self.assertEqual(4, options["boundaryMaxConcurrency"])

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

    def test_boundary_refine_uses_external_model_first_in_hybrid_mode(self):
        with patch.dict(
            os.environ,
            {
                "ENABLE_LLM_SPLIT": "true",
                "LLM_ROUTER_MODE": "hybrid",
                "LOCAL_LLM_ENABLED": "true",
                "LOCAL_LLM_BASE_URL": "http://local-llm/v1",
                "LOCAL_LLM_MODEL": "aux-qwen3-32b-fp8",
                "DEEPSEEK_API_KEY": "deepseek-key",
                "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
                "DEEPSEEK_MODEL": "deepseek-v4-pro",
            },
            clear=True,
        ):
            endpoints = route_llm_endpoints("boundary-refine", {"markdownChars": 1200, "questionCount": 3})

        self.assertEqual(["external"], [endpoint["role"] for endpoint in endpoints])
        self.assertEqual("external-default", endpoints[0]["routeReason"])

    def test_standardize_failure_returns_metadata_without_name_error(self):
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key", "ENABLE_LLM_SPLIT": "true"}):
            with patch("app.llm_splitter.httpx.Client", side_effect=RuntimeError("llm unavailable")):
                standardized, metadata = standardize_markdown_with_llm("题干 $x+1=2$")

        self.assertIsNone(standardized)
        self.assertEqual("llm unavailable", metadata["error"])
        self.assertEqual(0, metadata["imageCount"])
        self.assertEqual("standardize", metadata["llmCall"]["callType"])
        self.assertEqual("failed", metadata["llmCall"]["status"])
        self.assertIn("durationMs", metadata["llmCall"])

    def test_standardize_uses_interactive_adaptive_gate(self):
        class Gate:
            def __init__(self):
                self.priorities = []
                self.successes = []

            def slot(self, priority):
                self.priorities.append(priority)
                return nullcontext()

            def record_success(self, duration_ms):
                self.successes.append(duration_ms)

            def record_failure(self, _kind):
                raise AssertionError("successful call must not record failure")

            def snapshot(self):
                return {"active": 0, "limit": 4, "minimum": 2, "maximum": 8, "cooldown": False}

        gate = Gate()
        response = {
            "choices": [{"message": {"content": json.dumps({
                "markdown": "题干 $x+1=2$",
                "answer": "",
                "analysis": "",
                "subQuestions": [],
                "corrections": [],
                "warnings": [],
                "confidence": "high",
            }, ensure_ascii=False)}}]
        }
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key", "ENABLE_LLM_SPLIT": "true"}):
            with patch("app.llm_splitter.standardization_concurrency_gate", return_value=gate):
                with patch("app.llm_splitter.post_llm_json_for_endpoint", return_value=(response, False)):
                    standardized, metadata = standardize_markdown_with_llm(
                        "题干 $x+1=2$",
                        structured_hints={"requestPriority": "interactive"},
                    )

        self.assertEqual("题干 $x+1=2$", standardized)
        self.assertEqual(["interactive"], gate.priorities)
        self.assertEqual(1, len(gate.successes))
        self.assertEqual(4, metadata["adaptiveConcurrency"]["limit"])

    def test_analysis_failure_returns_retryable_fallback_metadata(self):
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test-key", "ENABLE_LLM_SPLIT": "true"}):
            with patch("app.llm_splitter.post_llm_json_for_endpoint", side_effect=RuntimeError("read operation timed out")):
                analysis, metadata = generate_question_analysis_with_llm("计算：$x+1=2$。")

        self.assertEqual("", analysis)
        self.assertEqual("read operation timed out", metadata["error"])
        self.assertTrue(metadata["fallbackUsed"])
        self.assertTrue(metadata["retryable"])
        self.assertIn("AI 解析暂时不可用", metadata["warnings"][0])
        self.assertEqual("analysis-generate", metadata["llmCall"]["callType"])
        self.assertEqual("failed", metadata["llmCall"]["status"])
        self.assertIn("llmCalls", metadata)

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
