import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from app import worker_base
from app.import_services import (
    build_import_questions,
    detect_severe_latex_issues,
    normalize_sub_questions,
    standardize_markdown_ai_response,
    top_level_ocr_questions,
)


BROKEN_MARKDOWN = r"""（8分）（1）解下面一元一次不等式组，并写出它的所有非负整数解。

$$\left\{\begin{array}{l}
\displaystyle$\frac{5x - 1}{6} + 2$ $\geq$ \displaystyle$\frac{x + 5}{4}$, \\
\displaystyle 2x + 5$\leq 3$(5 - x)
\end{array}
\right.$$

（2）化简： $\left( \dfrac{a^{2}}{a - 2} - \dfrac{2a}{a + 2} \right)$\div$ \dfrac{a}{a^{2} - 4}$"""


class ImportServicesTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
