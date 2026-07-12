from app.question_canonicalization import build_canonicalization_plan


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
