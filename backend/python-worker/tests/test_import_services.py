import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from app import worker_base
from app.import_services import (
    build_import_questions,
    clear_standardize_cache,
    detect_severe_latex_issues,
    normalize_display_math_blocks,
    normalize_sub_questions,
    render_validate_markdown_candidate,
    standardize_markdown_ai_response,
    top_level_ocr_questions,
    update_import_question_from_payload,
)
from app.worker_base import ImportQuestionPayload


BROKEN_MARKDOWN = r"""（8分）（1）解下面一元一次不等式组，并写出它的所有非负整数解。

$$\left\{\begin{array}{l}
\displaystyle$\frac{5x - 1}{6} + 2$ $\geq$ \displaystyle$\frac{x + 5}{4}$, \\
\displaystyle 2x + 5$\leq 3$(5 - x)
\end{array}
\right.$$

（2）化简： $\left( \dfrac{a^{2}}{a - 2} - \dfrac{2a}{a + 2} \right)$\div$ \dfrac{a}{a^{2} - 4}$"""

CLEAN_OCR_MARKDOWN = r"""（8分）（1）解下面一元一次不等式组，并写出它的所有非负整数解。

$$
\left\{ \begin{array} { l }
\displaystyle { \frac { 5x - 1 } { 6 } } + 2 \geq \displaystyle { \frac { x + 5 } { 4 } } \\
\displaystyle 2x + 5 \leq 3 ( 5 - x )
\end{array} \right.
$$

（2）化简： $\left( \dfrac{a^{2}}{a - 2} - \dfrac{2a}{a + 2} \right) \div \dfrac{a}{a^{2} - 4}$"""

NUMBERED_DUPLICATED_CLEAN_OCR_MARKDOWN = f"20.{CLEAN_OCR_MARKDOWN}\n\n{CLEAN_OCR_MARKDOWN}"

SEVERELY_DAMAGED_MANUAL_MARKDOWN = r"""（8分）（1）解下面一元一次不等式组，并写出它的所有非负整数解。

$$\left\{\begin{array}{l l}{\displaystyle${\frac{5 x - 1}{6}$} + 2$\geq$ \displaystyle${\frac{x + 5}{4}$} .} \\ {\displaystyle{2 x + 5$\leq 3$ ( 5 - x )}} \end{array} \right.$$(2) 化简： $\left($ ${\frac$ ${a ^{2}}{a - 2}}$ $- {\frac{2 a}{a + 2}$ $} \right)$ $\div$$$$\frac{a}$ ${a ^{2} - 4}$"""


class ImportServicesTest(unittest.TestCase):
    def setUp(self):
        clear_standardize_cache()

    def test_standardize_repairs_fragmented_latex_delimiters_without_llm(self):
        self.assertIn("展示公式内部嵌套了单个 $ 分隔符", detect_severe_latex_issues(BROKEN_MARKDOWN))
        self.assertIn("行内公式被数学运算符切断", detect_severe_latex_issues(BROKEN_MARKDOWN))

        result = standardize_markdown_ai_response(BROKEN_MARKDOWN)
        standardizer = result["standardizer"]

        self.assertEqual([], standardizer["candidateSevereIssues"])
        self.assertTrue(standardizer["latexDelimiterRepaired"])
        self.assertEqual("rules", standardizer["source"])
        self.assertIn(r"\displaystyle\frac{5x - 1}{6} + 2 \geq", result["markdown"])
        self.assertIn(r"\right)\div \dfrac{a}{a^{2} - 4}$", result["markdown"])
        self.assertNotIn(r"\displaystyle$", result["markdown"])
        self.assertEqual([], detect_severe_latex_issues(result["markdown"]))

    def test_standardize_uses_clean_raw_ocr_candidate_before_llm(self):
        self.assertEqual([], detect_severe_latex_issues(CLEAN_OCR_MARKDOWN))
        self.assertIn("存在连续 4 个及以上 $", "\n".join(detect_severe_latex_issues(SEVERELY_DAMAGED_MANUAL_MARKDOWN)))

        with patch("app.import_services.standardize_markdown_with_llm") as standardize:
            result = standardize_markdown_ai_response(SEVERELY_DAMAGED_MANUAL_MARKDOWN, raw_ocr_context=CLEAN_OCR_MARKDOWN)

        standardize.assert_not_called()
        standardizer = result["standardizer"]
        self.assertIn(r"\frac { 5x - 1 } { 6 }", result["markdown"])
        self.assertEqual("ocr-fallback", standardizer["source"])
        self.assertTrue(standardizer["rawOcrFallbackUsed"])
        self.assertEqual([], standardizer["candidateSevereIssues"])
        self.assertEqual([], detect_severe_latex_issues(result["markdown"]))

    def test_standardize_collapses_numbered_raw_ocr_duplicate_suffix(self):
        with patch("app.import_services.standardize_markdown_with_llm") as standardize:
            result = standardize_markdown_ai_response(
                SEVERELY_DAMAGED_MANUAL_MARKDOWN,
                raw_ocr_context=NUMBERED_DUPLICATED_CLEAN_OCR_MARKDOWN,
            )

        standardize.assert_not_called()
        self.assertEqual("ocr-fallback", result["standardizer"]["source"])
        self.assertEqual(1, result["markdown"].count("解下面一元一次不等式组"))
        self.assertEqual(1, result["markdown"].count("（2）化简"))
        correction_reasons = [item["reason"] for item in result["standardizer"]["corrections"]]
        self.assertIn("折叠 AI 标准化候选中的整题重复输出", correction_reasons)

    def test_display_math_blocks_are_split_from_following_text(self):
        markdown = r"题干 $$\left\{\begin{array}{l}x>1\end{array}\right.$$(2) 化简： $a+b$"

        fixed, corrections = normalize_display_math_blocks(markdown)
        validation = render_validate_markdown_candidate(fixed)

        self.assertIn("\n$$\n", fixed)
        self.assertIn("\n$$\n\n(2)", fixed)
        self.assertTrue(corrections)
        self.assertTrue(validation["valid"])

    def test_standardize_reuses_cached_llm_result_for_identical_input(self):
        markdown = r"计算：$x + 1$。"
        raw_context = r"20. 计算：$x + 1$。"
        hints = {"number": 20, "type": "solution"}

        with patch("app.import_services.standardize_markdown_with_llm") as standardize:
            standardize.return_value = (
                r"计算：$x+1$。",
                {
                    "source": "ai",
                    "provider": "mock",
                    "model": "mock-model",
                    "error": None,
                    "corrections": [],
                    "warnings": [],
                    "confidence": "high",
                    "answer": "",
                    "analysis": "",
                },
            )

            first = standardize_markdown_ai_response(markdown, raw_ocr_context=raw_context, structured_hints=hints)
            second = standardize_markdown_ai_response(markdown, raw_ocr_context=raw_context, structured_hints=hints)

        self.assertEqual(1, standardize.call_count)
        self.assertFalse(first["standardizer"].get("cacheHit", False))
        self.assertTrue(second["standardizer"]["cacheHit"])
        self.assertEqual(first["markdown"], second["markdown"])

    def test_standardize_llm_timeout_returns_local_fallback_candidate(self):
        markdown = r"计算：$x + 1$。"

        with patch("app.import_services.standardize_markdown_with_llm") as standardize:
            standardize.return_value = (
                None,
                {
                    "source": "ai",
                    "provider": "mock",
                    "model": "mock-model",
                    "error": "The read operation timed out",
                    "retryable": True,
                    "retryAfterSeconds": 10,
                    "llmCalls": [{"status": "failed", "error": "The read operation timed out"}],
                },
            )
            result = standardize_markdown_ai_response(markdown)

        standardizer = result["standardizer"]
        self.assertEqual("rules-fallback", standardizer["source"])
        self.assertTrue(standardizer["fallbackUsed"])
        self.assertTrue(standardizer["retryable"])
        self.assertEqual("The read operation timed out", standardizer["error"])
        self.assertIn("AI 标准化暂时不可用", standardizer["warnings"][0])
        self.assertEqual(markdown, result["markdown"])

    def test_standardize_preserves_original_choice_image_options_when_llm_drops_them(self):
        markdown = r"""如图所示的几何体是由 6 个小正方体搭成，它的左视图是（ ）

\begin{tasks}(4)
\task ![](图2)
\task ![](图3)
\task ![](图4)
\task ![](图5)
\end{tasks}"""
        hints = {
            "type": "choice",
            "options": [
                {"label": "A", "content": "![](图2)"},
                {"label": "B", "content": "![](图3)"},
                {"label": "C", "content": "![](图4)"},
                {"label": "D", "content": "![](图5)"},
            ],
        }

        with patch("app.import_services.standardize_markdown_with_llm") as standardize:
            standardize.return_value = (
                "如图所示的几何体是由 6 个小正方体搭成，它的左视图是（ ）",
                {
                    "source": "ai",
                    "provider": "mock",
                    "model": "mock-model",
                    "error": None,
                    "corrections": [],
                    "warnings": [],
                    "confidence": "medium",
                    "answer": "",
                    "analysis": "",
                },
            )
            result = standardize_markdown_ai_response(markdown, structured_hints=hints)

        self.assertIn(r"\begin{tasks}(4)", result["markdown"])
        self.assertIn(r"\task ![](图2)", result["markdown"])
        self.assertIn(r"\task ![](图5)", result["markdown"])
        self.assertEqual(["A", "B", "C", "D"], [option["label"] for option in result["options"]])
        self.assertIn("AI 标准化选择题结构保护", result["standardizer"]["fixes"])
        self.assertIn("已保留原 OCR 选项结构", " ".join(result["standardizer"]["warnings"]))

    def test_standardize_collapses_adjacent_duplicate_llm_markdown(self):
        markdown = (
            "已知函数 $f(x)=x^2-2x+1$，点 $A(1,0)$ 在图象上。"
            "请根据题意写出函数的顶点坐标，并说明图象与坐标轴的交点情况。"
            "要求保留必要的计算过程，并用规范的数学符号表示最终结论。"
        )
        duplicated = f"{markdown}\n\n{markdown}"

        with patch("app.import_services.standardize_markdown_with_llm") as standardize:
            standardize.return_value = (
                duplicated,
                {
                    "source": "ai",
                    "provider": "mock",
                    "model": "mock-model",
                    "error": None,
                    "corrections": [],
                    "warnings": [],
                    "confidence": "high",
                    "answer": "",
                    "analysis": "",
                },
            )
            result = standardize_markdown_ai_response(markdown, structured_hints={"type": "solution"})

        self.assertEqual(markdown, result["markdown"])
        correction_reasons = [item["reason"] for item in result["standardizer"]["corrections"]]
        self.assertIn("折叠 AI 标准化候选中的整题重复输出", correction_reasons)

    def test_standardize_second_pass_extracts_missing_sub_questions(self):
        markdown = "已知函数 $f(x)$ 满足条件。\n\n(1) 求 $f(0)$。\n\n(2) 证明 $f(x)$ 单调递增。"

        with patch("app.import_services.standardize_markdown_with_llm") as standardize:
            standardize.return_value = (
                markdown,
                {
                    "source": "ai",
                    "provider": "mock",
                    "model": "mock-model",
                    "error": None,
                    "corrections": [],
                    "warnings": [],
                    "confidence": "high",
                    "answer": "",
                    "analysis": "",
                    "subQuestions": [],
                },
            )
            result = standardize_markdown_ai_response(markdown, structured_hints={"type": "solution"})

        self.assertEqual("已知函数 $f(x)$ 满足条件。", result["markdown"])
        self.assertEqual(["(1)", "(2)"], [item["label"] for item in result["subQuestions"]])
        self.assertIn("求 $f(0)$。", result["subQuestions"][0]["stemMarkdown"])
        self.assertEqual("", result["answer"])
        self.assertEqual("", result["analysis"])

    def test_worker_store_recovers_from_backup_when_main_json_is_corrupted(self):
        original_store_file = worker_base.LIBRARY_STORE_FILE
        with tempfile.TemporaryDirectory() as temp_dir:
            store_file = Path(temp_dir) / "library_store.json"
            worker_base.LIBRARY_STORE_FILE = store_file
            try:
                expected = {
                    "importTasks": [{"id": "import_task_safe_store", "title": "安全备份任务"}],
                    "bankQuestions": [],
                    "knowledgePoints": [],
                    "papers": [],
                }
                worker_base.write_store(expected)
                store_file.write_text("{broken-json", encoding="utf-8")

                recovered = worker_base.read_store()

                self.assertEqual("import_task_safe_store", recovered["importTasks"][0]["id"])
                self.assertTrue(store_file.with_name("library_store.json.bak").exists())
            finally:
                worker_base.LIBRARY_STORE_FILE = original_store_file

    def test_top_level_ocr_questions_ignores_flattened_sub_questions(self):
        parent = {
            "id": "q1",
            "number": 21,
            "stemMarkdown": "已知函数 $f(x)$。",
            "subQuestions": [
                {"id": "q1_sub1", "label": "(1)", "stemMarkdown": "求 $f(0)$。"},
            ],
        }
        outputs = {
            "sections": [{"id": "section_1", "questions": [parent]}],
            "questions": [parent, parent["subQuestions"][0]],
        }

        questions = top_level_ocr_questions(outputs)

        self.assertEqual(1, len(questions))
        self.assertEqual("q1", questions[0]["id"])

    def test_top_level_ocr_questions_keeps_repeated_ocr_ids_from_answer_sections(self):
        first = {"id": "q_1", "number": 1, "stemMarkdown": "正文第 1 题"}
        second = {"id": "q_1", "number": 1, "stemMarkdown": "答案解析第 1 题"}
        outputs = {
            "sections": [
                {"id": "paper", "questions": [first]},
                {"id": "answer", "questions": [second]},
            ],
            "questions": [first, second],
        }

        questions = top_level_ocr_questions(outputs)

        self.assertEqual(2, len(questions))
        self.assertEqual(["正文第 1 题", "答案解析第 1 题"], [item["stemMarkdown"] for item in questions])

    def test_build_import_questions_uses_platform_sequence_numbers_for_repeated_ocr_ids(self):
        task = {"stage": "初中", "subject": "数学", "grade": "九年级", "title": "测试卷"}
        outputs = {
            "sections": [
                {
                    "id": "paper",
                    "questions": [
                        {"id": "q_1", "number": 1, "type": "choice", "stemMarkdown": "正文第 1 题"},
                    ],
                },
                {
                    "id": "answer",
                    "questions": [
                        {"id": "q_1", "number": 1, "type": "solution", "stemMarkdown": "答案解析第 1 题"},
                    ],
                },
            ],
            "questions": [],
        }

        with patch.dict("os.environ", {"ENABLE_IMPORT_SYNC_AI_ENRICH": "false"}):
            questions = build_import_questions(task, outputs, "")

        self.assertEqual(2, len(questions))
        self.assertEqual([1, 2], [item["number"] for item in questions])
        self.assertEqual(["q_1", "q_1__occurrence_2"], [item["sourceQuestionId"] for item in questions])

    def test_build_import_questions_persists_sub_question_solutions(self):
        task = {"stage": "初中", "subject": "数学", "grade": "九年级", "title": "测试卷"}
        outputs = {
            "markdown": "21. 已知函数\n(1) 求值\n(2) 证明",
            "sections": [
                {
                    "id": "section_1",
                    "questions": [
                        {
                            "id": "q1",
                            "number": 21,
                            "type": "solution",
                            "stemMarkdown": "已知函数。",
                            "subQuestions": [
                                {
                                    "id": "q1_sub1",
                                    "label": "(1)",
                                    "stemMarkdown": "求值。",
                                    "answer": "1",
                                    "analysis": "代入计算。",
                                },
                                {
                                    "id": "q1_sub2",
                                    "label": "(2)",
                                    "stemMarkdown": "证明。",
                                    "answer": "成立",
                                    "analysis": "按定义证明。",
                                },
                            ],
                        }
                    ],
                }
            ],
            "questions": [],
        }

        with patch.dict("os.environ", {"ENABLE_IMPORT_SYNC_AI_ENRICH": "false"}):
            questions = build_import_questions(task, outputs, "")

        self.assertEqual(1, len(questions))
        self.assertEqual("", questions[0]["answer"])
        self.assertEqual("", questions[0]["analysis"])
        self.assertEqual(2, len(questions[0]["subQuestions"]))
        self.assertEqual("代入计算。", questions[0]["subQuestions"][0]["analysis"])

    def test_normalize_sub_questions_merges_enriched_solution_by_label(self):
        sub_questions = normalize_sub_questions(
            [{"id": "local_sub_1", "label": "(1)", "stemMarkdown": "求值。"}],
            [{"label": "(1)", "answer": "1", "analysis": "代入计算。", "knowledgePoints": ["函数"]}],
        )

        self.assertEqual("1", sub_questions[0]["answer"])
        self.assertEqual("代入计算。", sub_questions[0]["analysis"])
        self.assertEqual(["函数"], sub_questions[0]["knowledgePoints"])

    def test_update_import_question_accepts_object_raw_options(self):
        question = {
            "id": "q1",
            "images": [],
            "options": [],
        }
        payload = ImportQuestionPayload(
            options=[
                {"label": "A", "content": "2个", "contentMarkdown": "2个", "raw": {"label": "A", "content": "2个"}},
                {"label": "B", "content": "3个", "contentMarkdown": "3个", "raw": {"label": "B", "content": "3个"}},
            ],
            subQuestions=[
                {
                    "id": "sub1",
                    "label": "(1)",
                    "type": "choice",
                    "stemMarkdown": "选择正确答案。",
                    "options": [
                        {"label": "A", "content": "正确", "raw": {"label": "A", "content": "正确"}},
                        {"label": "B", "content": "错误", "raw": {"label": "B", "content": "错误"}},
                    ],
                }
            ],
        )

        update_import_question_from_payload(question, payload)

        self.assertEqual(
            [
                {"label": "A", "content": "2个", "contentMarkdown": "2个"},
                {"label": "B", "content": "3个", "contentMarkdown": "3个"},
            ],
            question["options"],
        )
        self.assertEqual(
            [
                {"label": "A", "content": "正确", "contentMarkdown": "正确"},
                {"label": "B", "content": "错误", "contentMarkdown": "错误"},
            ],
            question["subQuestions"][0]["options"],
        )


if __name__ == "__main__":
    unittest.main()
