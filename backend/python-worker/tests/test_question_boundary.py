import unittest

from app.question_boundary import (
    build_structure_from_boundaries,
    detect_local_boundaries,
    evaluate_boundary_confidence,
    extract_paper_structure_contract,
    merge_legacy_images,
    plan_boundary_chunks,
    validate_structure,
)
from app.question_markdown import question_to_edit_markdown


class QuestionBoundaryTest(unittest.TestCase):
    def test_embedded_final_option_label_restores_stable_four_choice_boundary(self):
        markdown = """一、选择题
1. 如图所示，选择正确的一项（ ）
A. 第一项
![](images/a.png)
B. 第二项
![](images/b.png)
C. 第三项 D

![](images/d.png)
第四项
"""

        boundaries = detect_local_boundaries(markdown, [])
        confidence = evaluate_boundary_confidence(markdown, boundaries, [])

        self.assertEqual(
            ["A", "B", "C", "D"],
            [option["label"] for option in boundaries["questions"][0]["options"]],
        )
        self.assertNotIn("unstable-choice-options", confidence["reasons"])

    def test_build_structure_preserves_explicit_option_image_placements(self):
        markdown = """一、选择题
1. 请选择正确图形
A.
![](images/a.png)
B.
![](images/b.png)
"""
        assets = [
            {"name": "a.png", "path": "images/a.png", "url": "/a.png"},
            {"name": "b.png", "path": "images/b.png", "url": "/b.png"},
        ]

        boundaries = detect_local_boundaries(markdown, assets)
        structured = build_structure_from_boundaries(markdown, boundaries, assets)
        question = structured["questions"][0]

        self.assertEqual(["A", "B"], [item["target"]["optionLabel"] for item in question["imagePlacements"]])
        self.assertTrue(all(item["inference"]["method"] == "explicit-offset" for item in question["imagePlacements"]))

    def test_structure_validation_rejects_duplicate_high_confidence_placements(self):
        markdown = "1. 如图，求角度。\n\n![](images/a.png)"
        assets = [{"name": "a.png", "path": "images/a.png", "url": "/a.png"}]
        boundaries = detect_local_boundaries(markdown, assets)
        structured = build_structure_from_boundaries(markdown, boundaries, assets)
        question = structured["questions"][0]
        duplicate = {**question["imagePlacements"][0], "placementId": "duplicate", "target": {"kind": "option", "optionLabel": "A"}}
        question["imagePlacements"].append(duplicate)

        validation = validate_structure(structured, markdown, assets)

        self.assertFalse(validation["valid"])
        self.assertTrue(any("多个高置信归属" in error for error in validation["errors"]))

    def test_legacy_images_do_not_cross_question_owners(self):
        images = [
            {"name": f"option-{index}.png", "path": f"images/option-{index}.png"}
            for index in range(1, 5)
        ]
        primary_questions = [
            {"id": "q1", "number": 1, "images": images.copy()},
            {"id": "q2", "number": 2, "images": []},
        ]
        structured = {
            "sections": [{"questions": primary_questions}],
            "questions": primary_questions,
        }
        legacy_questions = [
            {"id": "legacy-q1", "number": 1, "images": []},
            {"id": "legacy-q2", "number": 2, "images": images.copy()},
        ]
        legacy = {
            "sections": [{"questions": legacy_questions}],
            "questions": legacy_questions,
        }

        merge_legacy_images(structured, legacy)

        self.assertEqual([], primary_questions[1]["images"])
        self.assertEqual(4, len(primary_questions[1]["imageWarnings"]))
        self.assertTrue(all("另一道题" in warning for warning in primary_questions[1]["imageWarnings"]))

    def test_high_confidence_choice_boundaries_can_skip_llm(self):
        markdown = """一、选择题
1. 下列说法正确的是（ ）
A. 甲
B. 乙
C. 丙
D. 丁
2. 下列说法错误的是（ ）
A. 甲
B. 乙
C. 丙
D. 丁
"""
        boundaries = detect_local_boundaries(markdown, [])
        confidence = evaluate_boundary_confidence(markdown, boundaries, [])

        self.assertTrue(confidence["highConfidence"])
        self.assertEqual([], confidence["lowConfidenceQuestionIds"])

    def test_topic_compilation_allows_numbering_resets(self):
        markdown = """专题 01 集合、常用逻辑用语与复数

考点 01 集合

1．（2026·新课标全国Ⅰ卷·高考真题）已知集合 A，则 A∩B=（ ）
A. 甲 B. 乙 C. 丙 D. 丁
【答案】A

2．（2026·北京卷·高考真题）已知集合 M，则 M∪N=（ ）
A. 甲 B. 乙 C. 丙 D. 丁
【答案】B

考点 02 常用逻辑用语

1．（2026·天津卷·高考真题）设 x∈R，则“x>0”是“x^2+3x>0”的（ ）
A. 充分而不必要条件 B. 必要而不充分条件 C. 充分必要条件 D. 既不充分也不必要条件
【答案】A

2．（2026·北京卷·高考真题）若 p 是真命题，则下列说法正确的是（ ）
A. 甲 B. 乙 C. 丙 D. 丁
【答案】C

三、填空题

3．（2026·上海·三模）已知全集 U=R，则 A∩B=________．
【答案】{1}
"""
        boundaries = detect_local_boundaries(markdown, [])
        confidence = evaluate_boundary_confidence(markdown, boundaries, [])
        structured = build_structure_from_boundaries(markdown, boundaries, [])
        validation = validate_structure(structured, markdown, [], boundaries.get("structureContract"))

        self.assertTrue(confidence["highConfidence"])
        self.assertEqual([1, 2, 1, 2, 3], [question["number"] for question in structured["questions"]])
        self.assertTrue(structured["questions"][2]["numberingReset"])
        self.assertEqual(["q_1", "q_2", "q_1_2", "q_2_2", "q_3"], [question["id"] for question in structured["questions"]])
        self.assertTrue(validation["valid"])
        self.assertIn("题号按专题/练习分组重置", validation["warnings"])
        self.assertEqual(["A", "B", "C", "D"], [option["label"] for option in structured["questions"][0]["options"]])
        self.assertEqual("A", structured["questions"][0]["answer"])
        self.assertNotIn("【答案】", structured["questions"][0]["stemMarkdown"])

    def test_extracts_inline_answer_and_analysis_from_question_slice(self):
        markdown = """## 一、选择题
1. 已知集合 A，则 A∩B=（ ）A. 甲 B. 乙 C. 丙 D. 丁【答案】C【详解】因为 A 和 B 的公共元素为丙，所以选 C。
2. 已知集合 M，则 M∪N=（ ）
A. 甲 B. 乙 C. 丙 D. 丁
【答案】B
【分析】根据并集定义处理。
【详解】合并两个集合中的元素，得到乙。
"""
        boundaries = detect_local_boundaries(markdown, [])
        structured = build_structure_from_boundaries(markdown, boundaries, [])
        first, second = structured["questions"]

        self.assertEqual("C", first["answer"])
        self.assertIn("公共元素", first["analysis"])
        self.assertNotIn("【答案】", first["stemMarkdown"])
        self.assertEqual(["A", "B", "C", "D"], [option["label"] for option in first["options"]])
        self.assertEqual("B", second["answer"])
        self.assertIn("根据并集定义处理", second["analysis"])
        self.assertIn("得到乙", second["analysis"])
        self.assertNotIn("【详解】", second["stemMarkdown"])

    def test_short_answer_followed_by_unlabeled_solution_goes_to_analysis(self):
        markdown = """## 一、选择题
1. 已知全集 U，则结果为（ ）A. 甲 B. 乙 C. 丙 D. 丁
【答案】D

$$
A \\cup B = U
$$

所以选 D。
"""
        boundaries = detect_local_boundaries(markdown, [])
        structured = build_structure_from_boundaries(markdown, boundaries, [])
        question = structured["questions"][0]

        self.assertEqual("D", question["answer"])
        self.assertIn("A \\cup B", question["analysis"])
        self.assertIn("所以选 D", question["analysis"])

    def test_topic_overview_numbered_list_is_not_question(self):
        markdown = """专题 01 集合、常用逻辑用语与复数

创新考法
1. 多选题形式（全国Ⅰ卷）：增加了试题的覆盖面，要求考生全面判断。

考点 01 集合

1．（2026·新课标全国Ⅰ卷·高考真题）已知集合 A，则 A∩B=（ ）
A. 甲 B. 乙 C. 丙 D. 丁
"""
        boundaries = detect_local_boundaries(markdown, [])

        self.assertEqual([1], [question["number"] for question in boundaries["questions"]])
        self.assertFalse(boundaries["anchorCandidates"][0]["accepted"])
        self.assertIn("weak-question-anchor", boundaries["anchorCandidates"][0]["reasons"])

    def test_low_confidence_when_question_numbers_are_not_monotonic(self):
        markdown = """一、选择题
1. 第一题
3. 第三题
"""
        boundaries = detect_local_boundaries(markdown, [])
        confidence = evaluate_boundary_confidence(markdown, boundaries, [])

        self.assertFalse(confidence["highConfidence"])
        self.assertIn("question-number-gap", confidence["reasons"])

    def test_boundary_chunks_preserve_absolute_offsets(self):
        markdown = """一、选择题
1. 第一题
2. 第二题
3. 第三题
4. 第四题
"""
        boundaries = detect_local_boundaries(markdown, [])
        chunks = plan_boundary_chunks(markdown, boundaries, chunk_size=2)

        self.assertEqual(2, len(chunks))
        self.assertEqual(0, chunks[0]["index"])
        self.assertLess(chunks[0]["start"], chunks[0]["end"])
        self.assertGreaterEqual(chunks[1]["start"], chunks[0]["start"])
        self.assertTrue(all(question["start"] >= chunks[0]["start"] for question in chunks[0]["localBoundaries"]["questions"]))

    def test_detects_sub_questions_inside_parent_question(self):
        markdown = """## 三、解答题
21. 已知函数 $f(x)=x^3-3x+1$。
(1) 求 $f(x)$ 的单调区间；
(2) 求 $f(x)$ 在 $[-2,2]$ 上的最大值与最小值。
"""

        boundaries = detect_local_boundaries(markdown, [])
        structured = build_structure_from_boundaries(markdown, boundaries, [])
        validation = validate_structure(structured, markdown, [])
        parent = structured["sections"][0]["questions"][0]

        self.assertTrue(validation["valid"])
        self.assertEqual(1, len(structured["questions"]))
        self.assertIn("已知函数", parent["stemMarkdown"])
        self.assertEqual("", parent["answer"])
        self.assertEqual("", parent["analysis"])
        self.assertEqual(2, len(parent["subQuestions"]))
        self.assertEqual("(1)", parent["subQuestions"][0]["label"])
        self.assertIn("单调区间", parent["subQuestions"][0]["stemMarkdown"])
        self.assertIn("最大值", parent["subQuestions"][1]["stemMarkdown"])

    def test_does_not_treat_function_argument_as_sub_question(self):
        markdown = """三、解答题
21. 已知函数 $f(x)=x^2$。
(1) 求 $f(2)$；
(2) 求函数的单调区间。
"""

        boundaries = detect_local_boundaries(markdown, [])
        structured = build_structure_from_boundaries(markdown, boundaries, [])
        parent = structured["sections"][0]["questions"][0]

        self.assertEqual(2, len(parent["subQuestions"]))
        self.assertEqual(["(1)", "(2)"], [item["label"] for item in parent["subQuestions"]])
        self.assertIn("f(2)", parent["subQuestions"][0]["stemMarkdown"])

    def test_splits_choice_options_without_putting_options_in_stem(self):
        markdown = """## 一、选择题
1. 已知二次函数 $f(x)=x^2-2x-3$，则它的零点是（ ）
A. $x=1$ 或 $x=3$
B. $x=-1$ 或 $x=3$
C. $x=-1$ 或 $x=-3$
D. $x=1$ 或 $x=-3$
"""

        boundaries = detect_local_boundaries(markdown, [])
        structured = build_structure_from_boundaries(markdown, boundaries, [])
        question = structured["sections"][0]["questions"][0]

        self.assertEqual("choice", question["type"])
        self.assertEqual(["A", "B", "C", "D"], [option["label"] for option in question["options"]])
        self.assertNotIn("A.", question["stemMarkdown"])
        self.assertIn("零点", question["stemMarkdown"])

    def test_splits_inline_choice_options_after_closing_parenthesis(self):
        markdown = """一、选择题
1. 下列6个数中：-3，$\\frac{5}{19}$，-$\\pi$，$\\sqrt[3]{2}$，0.1237，-0.5050050005...，其中是无理数的有()A. 2个 B. 3个 C. 4个 D. 5个
"""

        boundaries = detect_local_boundaries(markdown, [])
        structured = build_structure_from_boundaries(markdown, boundaries, [])
        question = structured["sections"][0]["questions"][0]

        self.assertEqual("choice", question["type"])
        self.assertEqual(["A", "B", "C", "D"], [option["label"] for option in question["options"]])
        self.assertEqual(["2个", "3个", "4个", "5个"], [option["content"] for option in question["options"]])
        self.assertIn("有()", question["stemMarkdown"])
        self.assertNotIn("A.", question["stemMarkdown"])

    def test_splits_full_width_and_colon_choice_markers(self):
        markdown = """一、选择题
1. 下列说法正确的是（ ）Ａ．甲 Ｂ．乙 Ｃ．丙 Ｄ．丁
2. 下列说法错误的是（ ）A: 甲 B: 乙 C: 丙 D: 丁
"""

        boundaries = detect_local_boundaries(markdown, [])
        structured = build_structure_from_boundaries(markdown, boundaries, [])
        first, second = structured["sections"][0]["questions"]

        self.assertEqual(["A", "B", "C", "D"], [option["label"] for option in first["options"]])
        self.assertEqual(["甲", "乙", "丙", "丁"], [option["content"] for option in first["options"]])
        self.assertEqual(["A", "B", "C", "D"], [option["label"] for option in second["options"]])
        self.assertEqual(["甲", "乙", "丙", "丁"], [option["content"] for option in second["options"]])

    def test_splits_glued_later_choice_markers(self):
        markdown = """一、选择题
1. 设 x∈R，则下列条件判断正确的是（ ）
A. 充分而不必要条件
B. 必要而不充分条件C. 充分必要条件 D. 既不充分也不必要条件
"""

        boundaries = detect_local_boundaries(markdown, [])
        structured = build_structure_from_boundaries(markdown, boundaries, [])
        question = structured["sections"][0]["questions"][0]

        self.assertEqual(["A", "B", "C", "D"], [option["label"] for option in question["options"]])
        self.assertEqual(
            ["充分而不必要条件", "必要而不充分条件", "充分必要条件", "既不充分也不必要条件"],
            [option["content"] for option in question["options"]],
        )

    def test_splits_bare_choice_markers_only_at_line_start(self):
        markdown = """一、选择题
1. 下列说法正确的是（ ）
A 甲
B 乙
C 丙
D 丁
2. 如图，设 A 为点，B 为点，C 为点，D 为点，则结论正确的是（ ）
"""

        boundaries = detect_local_boundaries(markdown, [])
        structured = build_structure_from_boundaries(markdown, boundaries, [])
        first, second = structured["sections"][0]["questions"]

        self.assertEqual(["A", "B", "C", "D"], [option["label"] for option in first["options"]])
        self.assertEqual([], second["options"])
        self.assertIn("设 A 为点", second["stemMarkdown"])

    def test_keeps_trailing_question_image_out_of_last_choice_option(self):
        markdown = """一、选择题
1. 如图，$OE$ 平分 $\\angle AOC$，$OD$ 平分 $\\angle BOC$，下列结论不一定正确的是（ ）
A. $\\angle AOD = \\angle BOC$ B. $\\angle AOC = \\angle AOE$
C. $\\angle AOE + \\angle BOD = 90^{\\circ}$ D.
$\\angle AOD + \\angle BOD = 180^{\\circ}$
![](图1)
"""

        boundaries = detect_local_boundaries(markdown, [{"name": "图1", "path": "图1", "url": "/图1.png"}])
        structured = build_structure_from_boundaries(markdown, boundaries, [{"name": "图1", "path": "图1", "url": "/图1.png"}])
        question = structured["sections"][0]["questions"][0]

        self.assertEqual(["A", "B", "C", "D"], [option["label"] for option in question["options"]])
        self.assertIn("![](图1)", question["stemMarkdown"])
        self.assertIn("180", question["options"][-1]["content"])
        self.assertNotIn("![]", question["options"][-1]["content"])

    def test_choice_option_images_are_labelized_without_moving_to_stem(self):
        markdown = """一、选择题
1. 观察图形，选择正确选项。

![](images/stem.png)

\\begin{tasks}(4)
\\task ![]
(images/a.png)
\\task ![]
(images/b.png)
\\task ![]
(images/c.png)
\\task ![]
(images/d.png)
\\end{tasks}
"""
        assets = [
            {"name": "stem.png", "path": "images/stem.png", "url": "/stem.png"},
            {"name": "a.png", "path": "images/a.png", "url": "/a.png"},
            {"name": "b.png", "path": "images/b.png", "url": "/b.png"},
            {"name": "c.png", "path": "images/c.png", "url": "/c.png"},
            {"name": "d.png", "path": "images/d.png", "url": "/d.png"},
        ]

        boundaries = detect_local_boundaries(markdown, assets)
        structured = build_structure_from_boundaries(markdown, boundaries, assets)
        question = structured["sections"][0]["questions"][0]
        edit_markdown = question_to_edit_markdown(question)

        self.assertEqual("choice", question["type"])
        self.assertIn("![](图1)", question["stemMarkdown"])
        self.assertNotIn("![](图2)", question["stemMarkdown"])
        self.assertNotIn("images/a.png", question["stemMarkdown"])
        self.assertEqual(["![](图2)", "![](图3)", "![](图4)", "![](图5)"], [option["content"] for option in question["options"]])
        self.assertIn("\\task ![](图2)", edit_markdown)
        self.assertNotIn("images/a.png", edit_markdown)
        self.assertEqual(1, edit_markdown.count("![](图2)"))

    def test_completion_fill_blank_keeps_placeholders_and_image(self):
        markdown = """三、解答题
22. （8分）完成推理填空

如图，已知 $\\angle B = \\angle D , \\angle B A E = \\angle E$ .将证明 $\\angle A F C + \\angle D A E = 1 8 0 ^ { \\circ }$ 的过程填写完整.

证明： $\\because \\angle B A E = \\angle E$

11 C ).

$\\therefore \\angle B = \\angle$ ( \\_).

又： $\\angle B = \\angle D$

$\\therefore \\angle D = \\angle$ (等量代换).

$\\therefore A D / / B C ($ ).

![](images/proof.png)
"""
        assets = [{"name": "proof.png", "path": "images/proof.png", "url": "/proof.png"}]

        boundaries = detect_local_boundaries(markdown, assets)
        structured = build_structure_from_boundaries(markdown, boundaries, assets)
        question = structured["sections"][0]["questions"][0]

        self.assertEqual("fill_blank", question["type"])
        self.assertEqual([], question["subQuestions"])
        self.assertIn("____", question["stemMarkdown"])
        self.assertNotIn("11 C", question["stemMarkdown"])
        self.assertIn("![](图1)", question["stemMarkdown"])
        self.assertNotIn("images/proof.png", question["stemMarkdown"])
        self.assertEqual(["images/proof.png"], [image["path"] for image in question["images"]])

    def test_blank_slot_task_normalization_is_cue_based(self):
        markdown = """三、解答题
22. （8分）补全下列证明过程

证明：由已知可得

I B ).

$\\therefore \\angle A = \\angle$ ( $ ).
"""

        boundaries = detect_local_boundaries(markdown, [])
        structured = build_structure_from_boundaries(markdown, boundaries, [])
        question = structured["sections"][0]["questions"][0]

        self.assertEqual("fill_blank", question["type"])
        self.assertIn("____", question["stemMarkdown"])
        self.assertNotIn("I B", question["stemMarkdown"])
        self.assertIn("$\\therefore \\angle A = \\angle$ (____)", question["stemMarkdown"])

    def test_factorization_fill_blank_restores_missing_equal_placeholders(self):
        markdown = """三、解答题
24.（8分）（1）分解下列因式，将结果直接写在横线上：

$x ^ { 2 } + 4 x + 4 =$ $1 6 x ^ { 2 } + 2 4 x + 9 =$ $9 x ^ { 2 } - 1 2 x + 4 =$

(2) 观察以上三个多项式的系数，有 $4 ^ { 2 } = 4 \\times 1 \\times 4$。
①请你用数学式子表示a、b、c之间的关系；
②解决问题：若多项式 $x ^ { 2 } - 2 ( m - 3 ) x + ( 1 0 - 6 m )$ 是一个完全平方式，求m的值。
"""

        boundaries = detect_local_boundaries(markdown, [])
        structured = build_structure_from_boundaries(markdown, boundaries, [])
        parent = structured["sections"][0]["questions"][0]

        self.assertEqual("fill_blank", parent["type"])
        self.assertGreaterEqual(parent["stemMarkdown"].count("____"), 3)
        self.assertIn("$x ^ { 2 } + 4 x + 4 =$ ____", parent["stemMarkdown"])

    def test_assigns_image_refs_inside_sub_question_to_child(self):
        markdown = """## 三、解答题
21. 阅读材料。
(1) 如图回答问题。
![](images/sub1.png)
(2) 说明理由。
"""
        assets = [{"name": "sub1.png", "path": "images/sub1.png", "url": "/sub1.png"}]

        boundaries = detect_local_boundaries(markdown, assets)
        structured = build_structure_from_boundaries(markdown, boundaries, assets)
        parent = structured["sections"][0]["questions"][0]

        self.assertEqual([], parent["images"])
        self.assertEqual(["images/sub1.png"], [image["path"] for image in parent["subQuestions"][0]["images"]])
        self.assertEqual([], parent["subQuestions"][1]["images"])

    def test_trims_answer_section_title_from_last_sub_question(self):
        markdown = """## 三、解答题
28. （12分）如图，抛物线经过 A、B、C 三点。
(1) 求抛物线的函数表达式；
(2) 求点 C' 和点 D 的坐标；
(3) 设 P 是抛物线上位于对称轴右侧的一点，点 Q 在抛物线的对称轴上，求直线BP的函数表达式

![](images/q28-3.png)

# 2019年四川省成都市中考数学试卷

参考答案与试题解析
1. 答案 A
"""
        assets = [{"name": "q28-3.png", "path": "images/q28-3.png", "url": "/q28-3.png"}]

        boundaries = detect_local_boundaries(markdown, assets)
        structured = build_structure_from_boundaries(markdown, boundaries, assets)
        child = structured["sections"][0]["questions"][0]["subQuestions"][2]

        self.assertIn("设 P 是抛物线", child["stemMarkdown"])
        self.assertIn("![](图1)", child["stemMarkdown"])
        self.assertNotIn("images/q28-3.png", child["stemMarkdown"])
        self.assertNotIn("2019年四川省成都市中考数学试卷", child["stemMarkdown"])
        self.assertNotIn("参考答案与试题解析", child["stemMarkdown"])
        self.assertEqual(["images/q28-3.png"], [image["path"] for image in child["images"]])

    def test_trims_overlapping_llm_child_boundaries(self):
        markdown = """## 三、解答题
21. 已知条件。
(1) 第一问。
(2) 第二问。
"""
        boundaries = detect_local_boundaries(markdown, [])
        first_child = boundaries["questions"][0]["subQuestions"][0]
        first_child["end"] = boundaries["questions"][0]["end"]

        structured = build_structure_from_boundaries(markdown, boundaries, [])
        parent = structured["sections"][0]["questions"][0]

        self.assertNotIn("(2) 第二问", parent["subQuestions"][0]["stemMarkdown"])
        self.assertIn("第二问", parent["subQuestions"][1]["stemMarkdown"])

    def test_plain_ocr_section_heading_sets_question_type(self):
        markdown = """一、选择题
1. 下列说法正确的是（ ）
A. 甲
B. 乙
"""

        boundaries = detect_local_boundaries(markdown, [])
        structured = build_structure_from_boundaries(markdown, boundaries, [])
        question = structured["sections"][0]["questions"][0]

        self.assertEqual("choice", structured["sections"][0]["type"])
        self.assertEqual("choice", question["type"])
        self.assertIn("下列说法", question["stemMarkdown"])
        self.assertNotIn("一、选择题", question["stemMarkdown"])

    def test_paper_contract_filters_numbered_exam_preface(self):
        markdown = """# 高二数学试卷
考生注意：
1.本试卷共3题，满分150分，考试时间120分钟；
2.本试卷包括试题卷和答题纸两部分。

一、填空题（本大题共有2题，满分8分）
1. 第一题题干
2. 第二题题干

二、解答题（本大题共有1题，满分10分）
3. 第三题题干
"""

        boundaries = detect_local_boundaries(markdown, [])
        structured = build_structure_from_boundaries(markdown, boundaries, [])
        validation = validate_structure(structured, markdown, [])

        self.assertEqual(3, boundaries["structureContract"]["totalQuestionCount"])
        self.assertEqual([1, 2, 3], [question["number"] for question in boundaries["questions"]])
        self.assertTrue(any(not item["accepted"] and "before-first-section" in item["reasons"] for item in boundaries["anchorCandidates"]))
        self.assertTrue(validation["valid"], validation)

    def test_contract_infers_explicit_section_question_ranges(self):
        markdown = """二、选择题（本大题共有4题，满分18分，第13\\~14题每题4分，第15\\~16题每题5分）
13. 第一题
14. 第二题
15. 第三题
16. 第四题
"""

        contract = extract_paper_structure_contract(markdown)
        section = contract["sections"][0]

        self.assertEqual(13, section["rangeStart"])
        self.assertEqual(16, section["rangeEnd"])
        self.assertEqual(4, section["declaredCount"])

    def test_single_section_declared_count_allows_partial_page_prefix(self):
        markdown = """一、选择题（本大题共10个小题，每小题3分）
1. 第一题
2. 第二题
3. 第三题
4. 第四题
"""

        boundaries = detect_local_boundaries(markdown, [])
        structured = build_structure_from_boundaries(markdown, boundaries, [])
        validation = validate_structure(structured, markdown, [], boundaries["structureContract"])

        self.assertEqual(10, boundaries["structureContract"]["totalQuestionCount"])
        self.assertTrue(validation["valid"], validation)
        self.assertTrue(any("局部页面" in warning for warning in validation["warnings"]))

    def test_detects_glued_next_question_number_inside_line(self):
        markdown = """一、填空题（本大题共有2题，第11\\~12题每题5分）
11. 已知数列，求最大值.12. 已知双曲线，求距离
"""

        boundaries = detect_local_boundaries(markdown, [])
        structured = build_structure_from_boundaries(markdown, boundaries, [])

        self.assertEqual([11, 12], [question["number"] for question in boundaries["questions"]])
        self.assertEqual([11, 12], [question["number"] for question in structured["questions"]])
        self.assertTrue(structured["questions"][1]["sourceEvidence"]["start"] > structured["questions"][0]["sourceEvidence"]["start"])
        self.assertIn("已知双曲线", structured["questions"][1]["stemMarkdown"])

    def test_inline_question_number_does_not_split_image_filename(self):
        markdown = """一、选择题（本大题共10个小题，每小题3分）
1. 第一题（）
![](images/a4.jpg)
2. 第二题（）
3. 第三题（）
A
![](images/option4.jpg)
B.
![](images/option5.jpg)
4. 第四题（）
![](images/q4.png)
"""
        assets = [
            {"name": "a4.jpg", "path": "images/a4.jpg", "url": "/a4.jpg"},
            {"name": "option4.jpg", "path": "images/option4.jpg", "url": "/option4.jpg"},
            {"name": "option5.jpg", "path": "images/option5.jpg", "url": "/option5.jpg"},
            {"name": "q4.png", "path": "images/q4.png", "url": "/q4.png"},
        ]

        boundaries = detect_local_boundaries(markdown, assets)
        structured = build_structure_from_boundaries(markdown, boundaries, assets)

        self.assertEqual([1, 2, 3, 4], [question["number"] for question in boundaries["questions"]])
        self.assertEqual([1, 2, 3, 4], [question["number"] for question in structured["questions"]])
        self.assertNotIn("jpg)", structured["questions"][2]["stemMarkdown"])
        self.assertEqual(["images/option4.jpg", "images/option5.jpg"], [image["path"] for image in structured["questions"][2]["images"]])
        self.assertIn("第四题", structured["questions"][3]["stemMarkdown"])

    def test_structure_validation_rejects_question_evidence_starting_mid_formula(self):
        markdown = """一、填空题（本大题共有2题，第11\\~12题每题5分）
11. 已知数列，求最大值.12. 已知双曲线 $x^2/144-y^2/25=1$，求距离
"""
        contract = extract_paper_structure_contract(markdown)
        bad_boundaries = {
            "structureContract": contract,
            "sections": [
                {"id": "section_1", "title": contract["sections"][0]["title"], "type": "fill_blank", "start": 0, "end": len(markdown)}
            ],
            "questions": [
                {"id": "q_11", "number": 11, "type": "fill_blank", "sectionId": "section_1", "start": markdown.index("11."), "end": markdown.index("144")},
                {"id": "q_12", "number": 12, "type": "fill_blank", "sectionId": "section_1", "start": markdown.index("144"), "end": len(markdown)},
            ],
        }

        structured = build_structure_from_boundaries(markdown, bad_boundaries, [])
        validation = validate_structure(structured, markdown, [], contract)

        self.assertFalse(validation["valid"])
        self.assertTrue(any("题号 12" in error for error in validation["errors"]))

    def test_structure_validation_rejects_question_evidence_starting_at_image_extension(self):
        markdown = """一、选择题
3. 第三题
![](images/abc4.jpg)
4. 第四题
"""
        bad_start = markdown.index("4.jpg")
        bad_boundaries = {
            "sections": [{"id": "section_1", "title": "一、选择题", "type": "choice", "start": 0, "end": len(markdown)}],
            "questions": [
                {"id": "q_3", "number": 3, "type": "choice", "sectionId": "section_1", "start": markdown.index("3."), "end": bad_start},
                {"id": "q_4", "number": 4, "type": "choice", "sectionId": "section_1", "start": bad_start, "end": len(markdown)},
            ],
        }

        structured = build_structure_from_boundaries(markdown, bad_boundaries, [])
        validation = validate_structure(structured, markdown, [])

        self.assertFalse(validation["valid"])
        self.assertTrue(any("题号 4" in error for error in validation["errors"]))

    def test_choice_question_circled_statement_numbers_are_not_sub_questions(self):
        markdown = """一、选择题
1. 已知下列命题：① 甲正确；② 乙正确；③ 丙正确。正确的是（ ）
A. ①②
B. ②③
C. ①③
D. ①②③
"""

        boundaries = detect_local_boundaries(markdown, [])
        structured = build_structure_from_boundaries(markdown, boundaries, [])
        question = structured["sections"][0]["questions"][0]

        self.assertEqual("choice", question["type"])
        self.assertEqual([], question["subQuestions"])
        self.assertEqual(["A", "B", "C", "D"], [option["label"] for option in question["options"]])
        self.assertIn("① 甲正确", question["stemMarkdown"])

    def test_rejects_unknown_image_paths(self):
        markdown = "1. 如图，求角度。\n\n![](images/a.png)"
        boundaries = detect_local_boundaries(markdown, [{"name": "a.png", "path": "images/a.png", "url": "/a.png"}])
        boundaries["questions"][0]["images"] = [{"path": "images/not-exist.png", "start": 8, "end": 20}]
        structured = build_structure_from_boundaries(markdown, boundaries, [{"name": "a.png", "path": "images/a.png", "url": "/a.png"}])
        validation = validate_structure(structured, markdown, [{"name": "a.png", "path": "images/a.png", "url": "/a.png"}])

        self.assertFalse(validation["valid"])
        self.assertTrue(any("未知题图" in error for error in validation["errors"]))


if __name__ == "__main__":
    unittest.main()
