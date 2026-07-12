from app.question_canonicalization import apply_canonicalization, build_canonicalization_plan


def test_answer_zone_duplicate_merges_into_paper_question():
    markdown = (
        "1. 杠杆题\nA.食品夹 B.船桨\n"
        "参考答案与试题解析\n"
        "1. 杠杆题\n【解答】修枝剪刀省力"
    )
    answer_start = markdown.index("1. 杠杆题", markdown.index("参考答案"))
    questions = [
        {
            "id": "q_1",
            "number": 1,
            "type": "choice",
            "stemMarkdown": "1. 杠杆题",
            "options": [{"label": "A", "content": "食品夹"}],
            "sourceEvidence": {"start": 0, "end": markdown.index("参考答案")},
        },
        {
            "id": "q_1_2",
            "number": 1,
            "type": "choice",
            "stemMarkdown": "1. 杠杆题",
            "analysis": "修枝剪刀省力",
            "sourceEvidence": {"start": answer_start, "end": len(markdown)},
        },
    ]

    plan = build_canonicalization_plan(markdown, questions)

    assert plan["idMap"] == {"q_1": "q_1", "q_1_2": "q_1"}
    assert plan["automaticMerges"][0]["duplicateId"] == "q_1_2"
    assert plan["automaticMerges"][0]["canonicalId"] == "q_1"
    assert plan["blockingIssues"] == []


def test_same_number_without_answer_heading_is_not_merged():
    markdown = "一、选择题\n1. 第一题\n二、附加题\n1. 另一道题"
    second_start = markdown.rindex("1. 另一道题")
    questions = [
        {
            "id": "q_1",
            "number": 1,
            "stemMarkdown": "第一题",
            "sourceEvidence": {"start": markdown.index("1. 第一题"), "end": second_start},
        },
        {
            "id": "q_1_2",
            "number": 1,
            "stemMarkdown": "另一道题",
            "sourceEvidence": {"start": second_start, "end": len(markdown)},
        },
    ]

    plan = build_canonicalization_plan(markdown, questions)

    assert plan["automaticMerges"] == []
    assert plan["idMap"]["q_1_2"] == "q_1_2"


def test_ambiguous_answer_match_is_left_for_review():
    markdown = "1. 同题\n1. 同题\n参考答案\n1. 同题"
    answer_start = markdown.rindex("1. 同题")
    questions = [
        {"id": "paper-a", "number": 1, "stemMarkdown": "同题", "sourceEvidence": {"start": 0, "end": 5}},
        {"id": "paper-b", "number": 1, "stemMarkdown": "同题", "sourceEvidence": {"start": 6, "end": 11}},
        {
            "id": "answer-a",
            "number": 1,
            "stemMarkdown": "同题",
            "sourceEvidence": {"start": answer_start, "end": len(markdown)},
        },
    ]

    plan = build_canonicalization_plan(markdown, questions)

    assert plan["automaticMerges"] == []
    assert plan["reviewItems"][0]["duplicateId"] == "answer-a"
    assert plan["blockingIssues"] == ["ambiguous-duplicate-question"]


def test_unique_exact_stem_without_type_or_options_is_merged():
    markdown = "26. 证明题\n参考答案\n26. 证明题"
    answer_start = markdown.rindex("26. 证明题")
    questions = [
        {"id": "q_26", "number": 26, "stemMarkdown": "证明题", "sourceEvidence": {"start": 0, "end": 8}},
        {
            "id": "q_26_2",
            "number": 26,
            "stemMarkdown": "证明题",
            "sourceEvidence": {"start": answer_start, "end": len(markdown)},
        },
    ]

    plan = build_canonicalization_plan(markdown, questions)

    assert plan["idMap"]["q_26_2"] == "q_26"
    assert plan["reviewItems"] == []


def test_apply_keeps_paper_visuals_and_adds_answer_analysis():
    questions = [
        {
            "id": "q_2",
            "number": 2,
            "stemMarkdown": "杠杆题",
            "options": [{"label": "A", "content": "食品夹"}],
            "images": [{"imageId": "paper-a"}],
            "imagePlacements": [{"imageId": "paper-a", "target": "option", "optionLabel": "A"}],
            "analysis": "",
        },
        {
            "id": "q_2_2",
            "number": 2,
            "stemMarkdown": "杠杆题",
            "options": [{"label": "A", "content": "答案区食品夹"}],
            "images": [{"imageId": "answer-a"}],
            "imagePlacements": [{"imageId": "answer-a", "target": "stem"}],
            "analysis": "修枝剪刀是省力杠杆",
        },
    ]
    plan = {
        "idMap": {"q_2": "q_2", "q_2_2": "q_2"},
        "automaticMerges": [{"canonicalId": "q_2", "duplicateId": "q_2_2", "score": 1.0}],
    }

    result = apply_canonicalization(questions, plan)

    assert len(result["questions"]) == 1
    canonical = result["questions"][0]
    assert canonical["options"] == [{"label": "A", "content": "食品夹"}]
    assert canonical["images"] == [{"imageId": "paper-a"}]
    assert canonical["imagePlacements"] == [{"imageId": "paper-a", "target": "option", "optionLabel": "A"}]
    assert canonical["analysis"] == "修枝剪刀是省力杠杆"
    assert canonical["mergedFromQuestionIds"] == ["q_2_2"]


def test_repeated_solution_labels_do_not_create_extra_subquestions():
    question = {
        "id": "q_30",
        "subQuestions": [
            {"label": "(1)", "stemMarkdown": "题干一"},
            {"label": "(2)", "stemMarkdown": "题干二"},
            {"label": "(1)", "stemMarkdown": "分析重复一"},
            {"label": "(2)", "stemMarkdown": "答案重复二"},
        ],
    }

    result = apply_canonicalization(
        [question], {"idMap": {"q_30": "q_30"}, "automaticMerges": []}
    )

    canonical = result["questions"][0]
    assert [sub["label"] for sub in canonical["subQuestions"]] == ["(1)", "(2)"]
    assert canonical["children"] == canonical["subQuestions"]
    assert len(canonical["canonicalizationIssues"]) == 2


def test_conflicting_answers_are_reported_without_overwriting_paper_answer():
    questions = [
        {"id": "q_1", "number": 1, "answer": "A"},
        {"id": "q_1_2", "number": 1, "answer": "B"},
    ]
    plan = {
        "idMap": {"q_1": "q_1", "q_1_2": "q_1"},
        "automaticMerges": [{"canonicalId": "q_1", "duplicateId": "q_1_2", "score": 1.0}],
    }

    result = apply_canonicalization(questions, plan)

    canonical = result["questions"][0]
    assert canonical["answer"] == "A"
    assert canonical["canonicalizationIssues"][0]["type"] == "answer-conflict"
