import unittest

from app.question_markdown import detect_choice_option_markers, split_choice_options


class QuestionMarkdownTest(unittest.TestCase):
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
