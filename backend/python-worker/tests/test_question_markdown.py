import unittest

from app.question_markdown import detect_choice_option_markers, split_choice_options


class QuestionMarkdownTest(unittest.TestCase):
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
