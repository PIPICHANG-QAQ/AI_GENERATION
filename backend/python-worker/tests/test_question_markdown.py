import unittest

from app.question_markdown import detect_choice_option_markers, split_choice_options


class QuestionMarkdownTest(unittest.TestCase):
    def test_recovers_external_text_tasks_chain_after_math_decoy(self):
        markdown = r"""\begin{tasks}(2)
\task A项
\task B项 \[ C.\ x=1 \] C. 外部文本 D．另一文本
\end{tasks}"""

        stem, options = split_choice_options(markdown, "choice")

        self.assertEqual("", stem)
        self.assertEqual(
            [
                {"label": "A", "content": "A项"},
                {"label": "B", "content": r"B项 \[ C.\ x=1 \]"},
                {"label": "C", "content": "外部文本"},
                {"label": "D", "content": "另一文本"},
            ],
            options,
        )

    def test_recovers_explicit_text_tasks_label_chain(self):
        markdown = r"""\begin{tasks}(2)
\task A项
\task B项 C. 这是文本选项 D．另一文本选项
\end{tasks}"""

        stem, options = split_choice_options(markdown, "choice")

        self.assertEqual("", stem)
        self.assertEqual(
            [
                {"label": "A", "content": "A项"},
                {"label": "B", "content": "B项"},
                {"label": "C", "content": "这是文本选项"},
                {"label": "D", "content": "另一文本选项"},
            ],
            options,
        )

    def test_does_not_recover_tasks_with_unclosed_dollar(self):
        for name, content in {
            "inline": "B项 $5 C. x D. y",
            "display": "B项 $$5 C. x D. y",
            "inline_parens": r"B项 \(5 C. x D. y",
            "display_brackets": r"B项 \[5 C. x D. y",
        }.items():
            with self.subTest(name=name):
                markdown = "\n".join((r"\begin{tasks}(2)", r"\task A项", rf"\task {content}", r"\end{tasks}"))

                stem, options = split_choice_options(markdown, "choice")

                self.assertEqual("", stem)
                self.assertEqual(
                    [
                        {"label": "A", "content": "A项"},
                        {"label": "B", "content": content},
                    ],
                    options,
                )

    def test_does_not_recover_tasks_with_empty_task(self):
        markdown = r"""\begin{tasks}(2)
\task A项
\task
\task 前缀 D $4$ E．$5$
\end{tasks}"""

        stem, options = split_choice_options(markdown, "choice")

        self.assertEqual("", stem)
        self.assertEqual(
            [
                {"label": "A", "content": "A项"},
                {"label": "B", "content": "前缀 D $4$ E．$5$"},
            ],
            options,
        )

    def test_does_not_recover_nonconsecutive_tasks_labels(self):
        markdown = r"""\begin{tasks}(2)
\task A项
\task B项 C $3$ E．$4$
\end{tasks}"""

        stem, options = split_choice_options(markdown, "choice")

        self.assertEqual("", stem)
        self.assertEqual(
            [
                {"label": "A", "content": "A项"},
                {"label": "B", "content": "B项 C $3$ E．$4$"},
            ],
            options,
        )

    def test_does_not_recover_punctuated_point_name_in_tasks(self):
        markdown = r"""\begin{tasks}(2)
\task A项
\task B项 C $3$ 点 D．$4$
\end{tasks}"""

        stem, options = split_choice_options(markdown, "choice")

        self.assertEqual("", stem)
        self.assertEqual(
            [
                {"label": "A", "content": "A项"},
                {"label": "B", "content": "B项 C $3$ 点 D．$4$"},
            ],
            options,
        )

    def test_recovers_glued_tasks_options_before_later_task(self):
        markdown = r"""题干
\begin{tasks}(2)
\task A项
\task B项 C $3$ D．$4$
\task E项
\end{tasks}"""

        stem, options = split_choice_options(markdown, "choice")

        self.assertEqual("题干", stem)
        self.assertEqual(
            [
                {"label": "A", "content": "A项"},
                {"label": "B", "content": "B项"},
                {"label": "C", "content": "$3$"},
                {"label": "D", "content": "$4$"},
                {"label": "E", "content": "E项"},
            ],
            options,
        )

    def test_does_not_recover_tasks_labels_inside_math_delimiters(self):
        formulas = {
            "inline_dollar": r"$ C. \ x=1 \qquad D. \ x=2 $",
            "display_dollar": r"$$ C. \ x=1 \qquad D. \ x=2 $$",
            "inline_parens": r"\( C. \ x=1 \qquad D. \ x=2 \)",
            "display_brackets": r"\[ C. \ x=1 \qquad D. \ x=2 \]",
        }

        for name, formula in formulas.items():
            with self.subTest(name=name):
                markdown = "\n".join((r"\begin{tasks}(2)", r"\task A项", rf"\task {formula}", r"\end{tasks}"))

                stem, options = split_choice_options(markdown, "choice")

                self.assertEqual("", stem)
                self.assertEqual(
                    [
                        {"label": "A", "content": "A项"},
                        {"label": "B", "content": formula},
                    ],
                    options,
                )

    def test_recovers_glued_trailing_tasks_options(self):
        markdown = r"""\begin{tasks}(2)
\task $5500 \times 10^{4}$
\task $55 \times 10^{6}$ C $5.5 \times 10^{7}$ D．$5.5 \times 10^{8}$
\end{tasks}"""

        stem, options = split_choice_options(markdown, "choice")

        self.assertEqual("", stem)
        self.assertEqual(
            [
                {"label": "A", "content": "$5500 \\times 10^{4}$"},
                {"label": "B", "content": "$55 \\times 10^{6}$"},
                {"label": "C", "content": "$5.5 \\times 10^{7}$"},
                {"label": "D", "content": "$5.5 \\times 10^{8}$"},
            ],
            options,
        )

    def test_does_not_recover_ambiguous_trailing_tasks_labels(self):
        cases = {
            "inline_variable": r"""\begin{tasks}(2)
\task $5500 \times 10^{4}$
\task $55 \times 10^{6}$ $C$ $5.5 \times 10^{7}$ D．$5.5 \times 10^{8}$
\end{tasks}""",
            "point_named_d": r"""\begin{tasks}(2)
\task $5500 \times 10^{4}$
\task $55 \times 10^{6}$ C $5.5 \times 10^{7}$ 点 D 在数轴上表示 $5.5 \times 10^{8}$
\end{tasks}""",
            "incomplete_chain": r"""\begin{tasks}(2)
\task $5500 \times 10^{4}$
\task $55 \times 10^{6}$ C $5.5 \times 10^{7}$
\end{tasks}""",
        }

        for name, markdown in cases.items():
            with self.subTest(name=name):
                stem, options = split_choice_options(markdown, "choice")

                self.assertEqual("", stem)
                self.assertEqual(
                    [
                        {"label": "A", "content": "$5500 \\times 10^{4}$"},
                        {"label": "B", "content": markdown.split(r"\task ", 2)[2].split(r"\end{tasks}")[0].strip()},
                    ],
                    options,
                )

    def test_recovers_embedded_expected_label_before_option_image(self):
        markdown = """（2分）如图所示，为了增大摩擦的是（ ）
A. 乘车系好安全带
![](images/a.png)
B. 轴承中装有滚珠
![](images/b.png)
C. 运动鞋底的鞋钉 D

![](images/d.png)
气垫船
"""

        stem, options = split_choice_options(markdown, "choice")

        self.assertNotIn("A. 乘车", stem)
        self.assertEqual(["A", "B", "C", "D"], [option["label"] for option in options])
        self.assertNotIn(" D", options[2]["content"])
        self.assertIn("images/d.png", options[3]["content"])

    def test_does_not_promote_isolated_or_inline_variable_d(self):
        without_prefix = "题干中的点 D\n\n![](images/diagram.png)"
        with_formula = """A. 甲
B. 乙
C. 点 D 与圆相交，选择正确结论
![](images/diagram.png)
"""

        isolated = detect_choice_option_markers(without_prefix)
        _stem, options = split_choice_options(with_formula, "choice")

        self.assertEqual([], isolated)
        self.assertEqual(["A", "B", "C"], [option["label"] for option in options])

    def test_recovers_continuous_choice_chain_across_serialized_pages(self):
        markdown = """A. 第一页左图
![](images/a.png)
B. 第一页右图
![](images/b.png)

<!-- page-break -->

C. 第二页左图 D

![](images/d.png)
第二页右图
"""

        _stem, options = split_choice_options(markdown, "choice")

        self.assertEqual(["A", "B", "C", "D"], [option["label"] for option in options])


if __name__ == "__main__":
    unittest.main()
