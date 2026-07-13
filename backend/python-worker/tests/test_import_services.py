import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from app import worker_base
from app.import_services import (
    apply_auto_standardize_result,
    auto_standardize_import_questions,
    bank_question_duplicate_reason,
    bank_question_from_import,
    build_import_questions,
    canonicalize_import_outputs,
    clear_standardize_cache,
    detect_severe_latex_issues,
    find_bank_question_index_for_import,
    import_task_image_library,
    normalize_display_math_blocks,
    normalize_sub_questions,
    recover_stale_glued_section_questions,
    render_validate_markdown_candidate,
    standardize_markdown_ai_response,
    top_level_ocr_questions,
    update_import_question_from_payload,
)
from app.question_markdown import ensure_question_images_in_markdown
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
    def test_task_image_library_indexes_nested_subquestion_images(self):
        task = {
            "questions": [
                {
                    "id": "q37",
                    "number": 37,
                    "images": [],
                    "subQuestions": [
                        {
                            "id": "q37_sub_3",
                            "label": "(3)",
                            "images": [
                                {"name": "q37-a.png", "path": "images/q37-a.png", "url": "/q37-a.png"},
                                {"name": "q37-b.png", "path": "images/q37-b.png", "url": "/q37-b.png"},
                            ],
                        }
                    ],
                }
            ]
        }

        library = import_task_image_library(task)

        self.assertEqual(2, len(library))
        self.assertEqual(["subQuestion", "subQuestion"], [item["ownerKind"] for item in library])
        self.assertEqual(["q37_sub_3", "q37_sub_3"], [item["ownerId"] for item in library])
        self.assertEqual(["(3)", "(3)"], [item["ownerLabel"] for item in library])

    def test_auto_standardize_preserves_nested_subquestion_image_ownership(self):
        child = {
            "id": "q37_sub_3",
            "label": "(3)",
            "type": "solution",
            "stemMarkdown": "A 和 B 的重力。\n\n![](图1)\n\n![](图2)",
            "manualMarkdown": "A 和 B 的重力。\n\n![](图1)\n\n![](图2)",
            "images": [
                {"name": "q37-a.png", "path": "images/q37-a.png", "url": "/q37-a.png", "label": "图1"},
                {"name": "q37-b.png", "path": "images/q37-b.png", "url": "/q37-b.png", "label": "图2"},
            ],
            "imagePlacements": [
                {"imageKey": "images/q37-a.png", "target": "stem"},
                {"imageKey": "images/q37-b.png", "target": "stem"},
            ],
        }
        question = {
            "id": "q37",
            "number": 37,
            "type": "solution",
            "stemMarkdown": "某物理兴趣小组设计了装置。求：",
            "manualMarkdown": "某物理兴趣小组设计了装置。求：",
            "images": [],
            "subQuestions": [child],
            "children": [child],
        }
        response = {
            "markdown": "某物理兴趣小组设计了装置，求：",
            "subQuestions": [
                {
                    "id": "q37_sub_3",
                    "label": "(3)",
                    "stemMarkdown": "A 和 B 的重力。\n\n![](图1)\n\n![](图2)",
                    "manualMarkdown": "A 和 B 的重力。\n\n![](图1)\n\n![](图2)",
                }
            ],
            "standardizer": {
                "source": "ai",
                "provider": "mock",
                "model": "mock-model",
                "confidence": "high",
                "warnings": [],
                "fixes": [],
            },
        }

        metadata = apply_auto_standardize_result(
            question,
            response,
            "某物理兴趣小组设计了装置。求：",
            "risky",
            ["render-risk"],
        )

        self.assertEqual("applied", metadata["status"])
        updated_child = question["subQuestions"][0]
        self.assertEqual(
            ["images/q37-a.png", "images/q37-b.png"],
            [image["path"] for image in updated_child["images"]],
        )
        self.assertEqual(2, len(updated_child["imagePlacements"]))
        self.assertIn("![](图1)", updated_child["manualMarkdown"])
        self.assertIn("![](图2)", updated_child["manualMarkdown"])

    def test_auto_standardize_blocks_nested_subquestion_candidate_that_drops_refs(self):
        child = {
            "id": "q37_sub_3",
            "label": "(3)",
            "type": "solution",
            "stemMarkdown": "A 和 B 的重力。\n\n![](图1)\n\n![](图2)",
            "manualMarkdown": "A 和 B 的重力。\n\n![](图1)\n\n![](图2)",
            "images": [
                {"name": "q37-a.png", "path": "images/q37-a.png", "url": "/q37-a.png", "label": "图1"},
                {"name": "q37-b.png", "path": "images/q37-b.png", "url": "/q37-b.png", "label": "图2"},
            ],
        }
        question = {
            "id": "q37",
            "type": "solution",
            "stemMarkdown": "某物理兴趣小组设计了装置。求：",
            "manualMarkdown": "某物理兴趣小组设计了装置。求：",
            "images": [],
            "subQuestions": [child],
            "children": [child],
        }
        response = {
            "markdown": "某物理兴趣小组设计了装置，求：",
            "subQuestions": [
                {
                    "id": "q37_sub_3",
                    "label": "(3)",
                    "stemMarkdown": "A 和 B 的重力。",
                    "manualMarkdown": "A 和 B 的重力。",
                }
            ],
            "standardizer": {"source": "ai", "confidence": "high", "warnings": [], "fixes": []},
        }

        metadata = apply_auto_standardize_result(
            question,
            response,
            "某物理兴趣小组设计了装置。求：",
            "risky",
            ["render-risk"],
        )

        self.assertEqual("blocked", metadata["status"])
        self.assertIn("candidate-dropped-subquestion-images", " ".join(metadata["validation"]["errors"]))
        self.assertIn("![](图1)", question["subQuestions"][0]["manualMarkdown"])
        self.assertIn("![](图2)", question["subQuestions"][0]["manualMarkdown"])

    def test_auto_standardize_blocks_nested_subquestion_candidate_that_changes_assets(self):
        child = {
            "id": "q37_sub_3",
            "label": "(3)",
            "type": "solution",
            "stemMarkdown": "A 和 B 的重力。\n\n![](图1)\n\n![](图2)",
            "manualMarkdown": "A 和 B 的重力。\n\n![](图1)\n\n![](图2)",
            "images": [
                {"name": "q37-a.png", "path": "images/q37-a.png", "url": "/q37-a.png", "label": "图1"},
                {"name": "q37-b.png", "path": "images/q37-b.png", "url": "/q37-b.png", "label": "图2"},
            ],
        }
        question = {
            "id": "q37",
            "type": "solution",
            "stemMarkdown": "某物理兴趣小组设计了装置。求：",
            "manualMarkdown": "某物理兴趣小组设计了装置。求：",
            "images": [],
            "subQuestions": [child],
            "children": [child],
        }
        response = {
            "markdown": "某物理兴趣小组设计了装置，求：",
            "subQuestions": [
                {
                    "id": "q37_sub_3",
                    "label": "(3)",
                    "manualMarkdown": "A 和 B 的重力。\n\n![](图1)\n\n![](图2)",
                    "images": [{"name": "wrong.png", "path": "images/wrong.png", "url": "/wrong.png"}],
                }
            ],
            "standardizer": {"source": "ai", "confidence": "high", "warnings": [], "fixes": []},
        }

        metadata = apply_auto_standardize_result(
            question,
            response,
            "某物理兴趣小组设计了装置。求：",
            "risky",
            ["render-risk"],
        )

        self.assertEqual("blocked", metadata["status"])
        self.assertIn("candidate-changed-subquestion-images", " ".join(metadata["validation"]["errors"]))

    def setUp(self):
        clear_standardize_cache()

    def test_canonicalize_import_outputs_merges_answer_zone_duplicate(self):
        markdown = "1. 第一题\n参考答案与试题解析\n1. 第一题\n【解答】解析"
        answer_start = markdown.rindex("1. 第一题")
        task = {"id": "task-1", "paperOcrJobId": "ocr-1"}
        outputs = {
            "markdown": markdown,
            "questions": [
                {
                    "id": "q_1",
                    "number": 1,
                    "stemMarkdown": "第一题",
                    "sourceEvidence": {"start": 0, "end": markdown.index("参考答案")},
                },
                {
                    "id": "q_1_2",
                    "number": 1,
                    "stemMarkdown": "第一题",
                    "analysis": "解析",
                    "sourceEvidence": {"start": answer_start, "end": len(markdown)},
                },
            ],
        }

        result = canonicalize_import_outputs(task, outputs)
        repeated = canonicalize_import_outputs(task, outputs)

        self.assertEqual(2, result["summary"]["beforeQuestionCount"])
        self.assertEqual(1, result["summary"]["afterQuestionCount"])
        self.assertEqual(1, result["summary"]["mergedQuestionCount"])
        self.assertEqual("解析", result["questions"][0]["analysis"])
        self.assertEqual([], result["blockingIssues"])
        self.assertTrue(result["applyToken"])
        self.assertEqual(result["applyToken"], repeated["applyToken"])
        self.assertEqual(result["questions"][0]["id"], repeated["questions"][0]["id"])

    def test_canonicalization_preview_preserves_saved_paper_question_edits(self):
        markdown = "1. 第一题\n参考答案\n1. 第一题"
        task = {
            "id": "task-1",
            "paperOcrJobId": "ocr-1",
            "questions": [
                {
                    "id": "saved-paper-id",
                    "sourceQuestionId": "q_1",
                    "number": 1,
                    "manualMarkdown": "人工修订后的第一题",
                    "analysis": "",
                    "images": [{"imageId": "saved-image"}],
                    "options": [],
                },
                {
                    "id": "saved-answer-id",
                    "sourceQuestionId": "q_1_2",
                    "number": 2,
                },
            ],
        }
        outputs = {
            "markdown": markdown,
            "questions": [
                {
                    "id": "q_1",
                    "number": 1,
                    "stemMarkdown": "第一题",
                    "sourceEvidence": {"start": 0, "end": markdown.index("参考答案")},
                },
                {
                    "id": "q_1_2",
                    "number": 1,
                    "stemMarkdown": "第一题",
                    "analysis": "答案区解析",
                    "sourceEvidence": {"start": markdown.rindex("1. 第一题"), "end": len(markdown)},
                },
            ],
        }

        result = canonicalize_import_outputs(task, outputs)

        canonical = result["questions"][0]
        self.assertEqual("saved-paper-id", canonical["id"])
        self.assertEqual("人工修订后的第一题", canonical["manualMarkdown"])
        self.assertEqual([{"imageId": "saved-image"}], canonical["images"])
        self.assertEqual("答案区解析", canonical["analysis"])
        self.assertEqual(
            {"saved-paper-id": "saved-paper-id", "saved-answer-id": "saved-paper-id"},
            result["canonicalization"]["idMap"],
        )

    def test_canonicalization_preview_replaces_auto_saved_glued_choice_stem(self):
        glued_stem = (
            "下列说法正确的是（A．做功越少的机械做功越慢"
            "B．流体在流速大的地方压强大"
            "C．力的作用效果只与力的大小有关"
            "D．风力发电机是将风能转化为电能的设备"
        )
        markdown = f"11．{glued_stem}\n参考答案\n11．下列说法正确的是（ ）"
        answer_start = markdown.rindex("11．")
        outputs = {
            "markdown": markdown,
            "questions": [
                {
                    "id": "q_11",
                    "number": 11,
                    "type": "choice",
                    "stemMarkdown": glued_stem,
                    "manualMarkdown": glued_stem,
                    "options": [],
                    "sourceEvidence": {"start": 0, "end": markdown.index("参考答案")},
                },
                {
                    "id": "q_11_2",
                    "number": 11,
                    "type": "choice",
                    "stemMarkdown": "下列说法正确的是（ ）",
                    "options": [
                        {"label": "A", "content": "甲"},
                        {"label": "B", "content": "乙"},
                        {"label": "C", "content": "丙"},
                        {"label": "D", "content": "丁"},
                    ],
                    "sourceEvidence": {"start": answer_start, "end": len(markdown)},
                },
            ],
        }
        task = {
            "id": "task-1",
            "questions": [
                {
                    "id": "saved-q11",
                    "sourceQuestionId": "q_11",
                    "number": 11,
                    "type": "choice",
                    "stemMarkdown": glued_stem,
                    "manualMarkdown": glued_stem,
                    "options": [],
                }
            ],
        }

        result = canonicalize_import_outputs(task, outputs)

        question = result["questions"][0]
        self.assertEqual("下列说法正确的是（ ）", question["stemMarkdown"])
        self.assertEqual("下列说法正确的是（ ）", question["manualMarkdown"])
        self.assertEqual(["A", "B", "C", "D"], [option["label"] for option in question["options"]])

    def test_canonicalization_preview_keeps_manually_edited_options(self):
        outputs = {
            "markdown": "1．选择正确答案（ ）\nA．自动甲 B．自动乙 C．自动丙 D．自动丁",
            "questions": [
                {
                    "id": "q_1",
                    "number": 1,
                    "type": "choice",
                    "stemMarkdown": "选择正确答案（ ）",
                    "options": [
                        {"label": "A", "content": "自动甲"},
                        {"label": "B", "content": "自动乙"},
                        {"label": "C", "content": "自动丙"},
                        {"label": "D", "content": "自动丁"},
                    ],
                    "sourceEvidence": {"start": 0, "end": 40},
                }
            ],
        }
        task = {
            "id": "task-1",
            "questions": [
                {
                    "id": "saved-q1",
                    "sourceQuestionId": "q_1",
                    "number": 1,
                    "stemMarkdown": "选择正确答案（ ）",
                    "manualMarkdown": "选择正确答案（ ）",
                    "manualEditedAt": "2026-07-13T10:00:00",
                    "options": [{"label": "A", "content": "人工保留选项"}],
                }
            ],
        }

        question = canonicalize_import_outputs(task, outputs)["questions"][0]

        self.assertEqual([{"label": "A", "content": "人工保留选项"}], question["options"])

    def test_canonicalization_preview_does_not_treat_blank_manual_as_auto_saved(self):
        glued_stem = "选择正确答案（A．甲B．乙C．丙D．丁"
        markdown = f"1．{glued_stem}\n参考答案\n1．选择正确答案（ ）"
        outputs = {
            "markdown": markdown,
            "questions": [
                {
                    "id": "q_1",
                    "number": 1,
                    "type": "choice",
                    "stemMarkdown": glued_stem,
                    "options": [],
                    "sourceEvidence": {"start": 0, "end": markdown.index("参考答案")},
                },
                {
                    "id": "q_1_2",
                    "number": 1,
                    "type": "choice",
                    "stemMarkdown": "选择正确答案（ ）",
                    "options": [
                        {"label": "A", "content": "甲"},
                        {"label": "B", "content": "乙"},
                        {"label": "C", "content": "丙"},
                        {"label": "D", "content": "丁"},
                    ],
                    "sourceEvidence": {"start": markdown.rindex("1．"), "end": len(markdown)},
                },
            ],
        }
        task = {
            "id": "task-1",
            "questions": [
                {
                    "id": "saved-q1",
                    "sourceQuestionId": "q_1",
                    "number": 1,
                    "stemMarkdown": glued_stem,
                    "manualMarkdown": "",
                    "options": [],
                }
            ],
        }

        question = canonicalize_import_outputs(task, outputs)["questions"][0]

        self.assertEqual(glued_stem, question["stemMarkdown"])
        self.assertEqual("", question["manualMarkdown"])
        self.assertEqual([], question["options"])

    def test_canonicalization_preview_does_not_convert_saved_solution_to_choice(self):
        glued_stem = "请分析（A．条件甲 B．条件乙 C．条件丙 D．条件丁"
        outputs = {
            "markdown": "1．请选择（ ）\nA．甲 B．乙 C．丙 D．丁",
            "questions": [
                {
                    "id": "q_1",
                    "number": 1,
                    "type": "choice",
                    "stemMarkdown": "请选择（ ）",
                    "options": [
                        {"label": "A", "content": "甲"},
                        {"label": "B", "content": "乙"},
                        {"label": "C", "content": "丙"},
                        {"label": "D", "content": "丁"},
                    ],
                    "sourceEvidence": {"start": 0, "end": 30},
                }
            ],
        }
        task = {
            "id": "task-1",
            "questions": [
                {
                    "id": "saved-q1",
                    "sourceQuestionId": "q_1",
                    "number": 1,
                    "type": "solution",
                    "stemMarkdown": glued_stem,
                    "manualMarkdown": glued_stem,
                    "options": [],
                }
            ],
        }

        question = canonicalize_import_outputs(task, outputs)["questions"][0]

        self.assertEqual(glued_stem, question["stemMarkdown"])
        self.assertEqual(glued_stem, question["manualMarkdown"])
        self.assertEqual([], question["options"])

    def test_canonicalization_preview_recovers_option_and_layout_placement_diffs(self):
        markdown = "1. 选择正确图片"
        images = [{"path": f"images/{label.lower()}.png"} for label in "ABCD"]
        outputs = {
            "markdown": markdown,
            "sections": [
                {
                    "questions": [
                        {
                            "id": "q_1",
                            "number": 1,
                            "type": "choice",
                            "stemMarkdown": "选择正确图片",
                            "sourceEvidence": {"start": 0, "end": len(markdown)},
                            "options": [
                                {"label": "A", "content": "甲\n![](images/a.png)"},
                                {"label": "B", "content": "乙\n![](images/b.png)"},
                                {"label": "C", "content": "![](images/c.png)\n丙 D\n\n![](images/d.png)\n丁"},
                            ],
                            "images": images,
                            "imagePlacements": [
                                {"placementId": "p-a", "imageId": "images/a.png", "target": {"kind": "option", "optionLabel": "A"}, "inference": {"method": "explicit-offset", "confidence": 0.99, "reasons": []}},
                                {"placementId": "p-b", "imageId": "images/b.png", "target": {"kind": "option", "optionLabel": "B"}, "inference": {"method": "explicit-offset", "confidence": 0.99, "reasons": []}},
                                {"placementId": "p-c", "imageId": "images/c.png", "target": {"kind": "option", "optionLabel": "C"}, "inference": {"method": "explicit-offset", "confidence": 0.99, "reasons": []}},
                                {"placementId": "p-d", "imageId": "images/d.png", "target": {"kind": "option", "optionLabel": "C"}, "inference": {"method": "explicit-offset", "confidence": 0.99, "reasons": []}},
                            ],
                        }
                    ]
                }
            ],
        }
        layout_items = []
        for index, label in enumerate("ABCD"):
            x = 100 if index % 2 == 0 else 500
            y = 100 if index < 2 else 300
            layout_items.extend(
                [
                    {"type": "text", "text": f"{label}.", "pageIndex": 0, "bbox": [x, y, x + 40, y + 30]},
                    {"type": "image", "imageRef": f"images/{label.lower()}.png", "pageIndex": 0, "bbox": [x + 20, y + 40, x + 200, y + 160]},
                ]
            )

        result = canonicalize_import_outputs({"id": "task-1"}, outputs, layout_items=layout_items)

        question = result["questions"][0]
        self.assertEqual(["A", "B", "C", "D"], [option["label"] for option in question["options"]])
        self.assertEqual(
            {"images/a.png": "A", "images/b.png": "B", "images/c.png": "C", "images/d.png": "D"},
            {
                placement["imageId"]: placement["target"]["optionLabel"]
                for placement in question["imagePlacements"]
            },
        )
        diff = result["structureDiffs"][0]
        self.assertEqual(1, diff["number"])
        self.assertEqual(3, diff["optionCountBefore"])
        self.assertEqual(4, diff["optionCountAfter"])
        self.assertTrue(any(item["imageId"] == "images/d.png" and item["newTarget"]["optionLabel"] == "D" for item in diff["placements"]))

    def test_canonicalization_preview_rewrites_trusted_option_image_placements_atomically(self):
        images = [
            {"path": f"images/{label.lower()}.png", "label": f"图{index}"}
            for index, label in enumerate("ABCD", start=1)
        ]
        placements = [
            {
                "placementId": f"p-{label.lower()}",
                "imageId": f"images/{label.lower()}.png",
                "target": {"kind": "option", "optionLabel": label},
                "order": index,
                "inference": {"method": "layout-global", "confidence": 0.98, "reasons": []},
                "reviewStatus": "auto",
            }
            for index, label in enumerate("ABCD")
        ]
        outputs = {
            "markdown": "1. 如图所示，属于省力杠杆的是（ ）",
            "questions": [
                {
                    "id": "q_1",
                    "number": 1,
                    "type": "choice",
                    "stemMarkdown": "如图所示，属于省力杠杆的是（ ）",
                    "options": [
                        {"label": "A", "content": "![](图1)\n\n食品夹"},
                        {"label": "B", "content": "![](图2)  \n船桨\n\n![](图3)"},
                        {"label": "C", "content": "修枝剪刀\n\n![](图4)"},
                        {"label": "D", "content": "托盘天平"},
                    ],
                    "images": images,
                    "imagePlacements": placements,
                }
            ],
        }

        question = canonicalize_import_outputs({"id": "task-1"}, outputs)["questions"][0]

        self.assertEqual(
            [
                "![](图1) 食品夹",
                "![](图2) 船桨",
                "![](图3) 修枝剪刀",
                "![](图4) 托盘天平",
            ],
            [option["content"] for option in question["options"]],
        )

    def test_canonicalization_preview_preserves_image_when_trusted_target_option_is_missing(self):
        outputs = {
            "markdown": "1. 选择正确图片",
            "questions": [
                {
                    "id": "q_1",
                    "number": 1,
                    "type": "choice",
                    "stemMarkdown": "选择正确图片",
                    "options": [
                        {"label": "A", "content": "甲"},
                        {"label": "B", "content": "乙"},
                        {"label": "C", "content": "![](图1) 丙"},
                    ],
                    "images": [{"path": "images/a.png", "label": "图1"}],
                    "imagePlacements": [
                        {
                            "placementId": "p-invalid",
                            "imageId": "images/a.png",
                            "target": {"kind": "option", "optionLabel": "D"},
                            "inference": {"method": "layout-global", "confidence": 0.99, "reasons": []},
                            "reviewStatus": "auto",
                        }
                    ],
                }
            ],
        }

        question = canonicalize_import_outputs({"id": "task-1"}, outputs)["questions"][0]

        self.assertIn("![](图1)", question["options"][2]["content"])
        self.assertEqual(1, len(question["images"]))

    def test_canonicalization_preview_preserves_image_when_trusted_owners_conflict(self):
        placements = [
            {
                "placementId": f"p-{label.lower()}",
                "imageId": "images/a.png",
                "target": {"kind": "option", "optionLabel": label},
                "inference": {"method": "layout-global", "confidence": 0.99, "reasons": []},
                "reviewStatus": "auto",
            }
            for label in ("A", "B")
        ]
        outputs = {
            "markdown": "1. 选择正确图片",
            "questions": [
                {
                    "id": "q_1",
                    "number": 1,
                    "type": "choice",
                    "stemMarkdown": "选择正确图片",
                    "options": [
                        {"label": "A", "content": "甲"},
                        {"label": "B", "content": "乙"},
                        {"label": "C", "content": "![](图1) 丙"},
                    ],
                    "images": [{"path": "images/a.png", "label": "图1"}],
                    "imagePlacements": placements,
                }
            ],
        }

        question = canonicalize_import_outputs({"id": "task-1"}, outputs)["questions"][0]

        contents = [option["content"] for option in question["options"]]
        self.assertEqual(1, sum(content.count("![](图1)") for content in contents))
        self.assertIn("![](图1)", contents[2])

    def test_canonicalization_preview_keeps_placement_review_out_of_apply_blocking_issues(self):
        outputs = {
            "markdown": "1. 选择正确答案",
            "questions": [
                {
                    "id": "q_1",
                    "number": 1,
                    "type": "choice",
                    "stemMarkdown": "选择正确答案",
                    "options": [
                        {"label": "A", "content": "甲"},
                        {"label": "B", "content": "乙"},
                    ],
                    "images": [{"path": "images/actual.png", "label": "图1"}],
                    "imagePlacements": [
                        {
                            "placementId": "p-missing",
                            "imageId": "images/missing.png",
                            "target": {"kind": "option", "optionLabel": "A"},
                            "inference": {"method": "rule", "confidence": 0.99, "reasons": []},
                            "reviewStatus": "auto",
                        }
                    ],
                }
            ],
        }

        result = canonicalize_import_outputs({"id": "task-1"}, outputs)

        self.assertEqual([], result["applyBlockingIssues"])
        self.assertEqual("image-placement-validation", result["blockingIssues"][0]["type"])

    def test_canonicalization_preview_keeps_ambiguous_duplicates_apply_blocking(self):
        markdown = "1. 同题\n1. 同题\n参考答案\n1. 同题"
        answer_start = markdown.rindex("1. 同题")
        outputs = {
            "markdown": markdown,
            "questions": [
                {"id": "paper-a", "number": 1, "stemMarkdown": "同题", "sourceEvidence": {"start": 0, "end": 5}},
                {"id": "paper-b", "number": 1, "stemMarkdown": "同题", "sourceEvidence": {"start": 6, "end": 11}},
                {
                    "id": "answer-a",
                    "number": 1,
                    "stemMarkdown": "同题",
                    "sourceEvidence": {"start": answer_start, "end": len(markdown)},
                },
            ],
        }

        result = canonicalize_import_outputs({"id": "task-1"}, outputs)

        self.assertEqual(["ambiguous-duplicate-question"], result["applyBlockingIssues"])
        self.assertIn("ambiguous-duplicate-question", result["blockingIssues"])

    def test_canonicalization_preview_recovers_question_glued_to_section_heading(self):
        markdown = """一、解答题
1．（6分）完成实验。

2．（6分）继续实验。

五、选择题（每小题2分，共10分）3．（2分）如图所示，下列说法正确的是（ ）
A．甲 B．乙 C．丙 D．丁

4．（2分）下一道选择题是（ ）
A．甲 B．乙 C．丙 D．丁
"""
        q2_start = markdown.index("2．")
        q2_end = markdown.index("五、选择题")
        q4_start = markdown.index("4．")
        outputs = {
            "markdown": markdown,
            "assets": [],
            "sections": [
                {
                    "questions": [
                        {
                            "id": "q_1",
                            "number": 1,
                            "type": "solution",
                            "stemMarkdown": "（6分）完成实验。",
                            "analysis": "保留旧结构分析字段",
                            "sourceEvidence": {"start": markdown.index("1．"), "end": q2_start},
                        },
                        {
                            "id": "q_2",
                            "number": 2,
                            "type": "solution",
                            "stemMarkdown": "（6分）继续实验。",
                            "sourceEvidence": {"start": q2_start, "end": q2_end},
                        },
                        {
                            "id": "q_4",
                            "number": 4,
                            "type": "choice",
                            "stemMarkdown": "下一道选择题是（ ）",
                            "sourceEvidence": {"start": q4_start, "end": len(markdown)},
                            "options": [
                                {"label": "A", "content": "甲"},
                                {"label": "B", "content": "乙"},
                                {"label": "C", "content": "丙"},
                                {"label": "D", "content": "丁"},
                            ],
                        },
                    ]
                }
            ],
        }
        task = {
            "id": "task-1",
            "questions": [
                {
                    "id": "saved-q4",
                    "sourceQuestionId": "q_4",
                    "number": 3,
                    "manualMarkdown": "人工修订后的第4题",
                    "options": [],
                }
            ],
        }

        result = canonicalize_import_outputs(task, outputs)

        self.assertEqual(["q_1", "q_2", "q_3", "q_4"], [question["sourceQuestionId"] for question in result["questions"]])
        self.assertEqual("保留旧结构分析字段", result["questions"][0]["analysis"])
        self.assertEqual(3, result["summary"]["beforeQuestionCount"])
        self.assertEqual(4, result["summary"]["afterQuestionCount"])
        self.assertEqual(1, result["summary"]["recoveredQuestionCount"])
        self.assertEqual(0, result["summary"]["mergedQuestionCount"])
        recovered = result["questions"][2]
        self.assertEqual(3, recovered["number"])
        self.assertEqual(["A", "B", "C", "D"], [option["label"] for option in recovered["options"]])
        saved = result["questions"][3]
        self.assertEqual("saved-q4", saved["id"])
        self.assertEqual(4, saved["number"])
        self.assertEqual("人工修订后的第4题", saved["manualMarkdown"])
        recovered_diff = next(item for item in result["structureDiffs"] if item["sourceQuestionId"] == "q_3")
        self.assertTrue(recovered_diff["added"])
        self.assertTrue(recovered_diff["changed"])
        renumbered_diff = next(item for item in result["structureDiffs"] if item["sourceQuestionId"] == "q_4")
        self.assertEqual(3, renumbered_diff["numberBefore"])
        self.assertEqual(4, renumbered_diff["numberAfter"])
        self.assertTrue(renumbered_diff["changed"])

    def test_glued_section_recovery_ignores_existing_question_with_shifted_start(self):
        markdown = """一、解答题
1．完成实验。

五、选择题（每小题2分）2．选择正确答案（ ）
A．甲 B．乙 C．丙 D．丁
"""
        inline_start = markdown.index("2．")
        stored_questions = [
            {
                "id": "q_1",
                "number": 1,
                "type": "solution",
                "stemMarkdown": "完成实验。",
                "analysis": "必须保留的旧结构字段",
                "sourceEvidence": {"start": markdown.index("1．"), "end": markdown.index("五、选择题")},
            },
            {
                "id": "q_2",
                "number": 2,
                "type": "choice",
                "stemMarkdown": "选择正确答案（ ）",
                "options": [{"label": "A", "content": "甲"}],
                "sourceEvidence": {"start": inline_start + 1, "end": len(markdown)},
            },
        ]

        recovered = recover_stale_glued_section_questions(
            {"markdown": markdown, "assets": [], "questions": stored_questions},
            stored_questions,
        )

        self.assertEqual(stored_questions, recovered)

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

    def test_clean_structured_choice_uses_same_rules_fast_path_for_single_and_global(self):
        markdown = r"""已知 $2+3=$（ ）

\begin{tasks}(4)
\task 4
\task 5
\task 6
\task 7
\end{tasks}"""
        hints = {
            "type": "choice",
            "answer": "B",
            "analysis": "直接计算。",
            "options": [
                {"label": "A", "content": "4"},
                {"label": "B", "content": "5"},
                {"label": "C", "content": "6"},
                {"label": "D", "content": "7"},
            ],
        }

        with patch("app.import_services.standardize_markdown_with_llm") as standardize:
            single = standardize_markdown_ai_response(
                markdown,
                structured_hints=hints,
                request_source="single",
            )
            global_result = standardize_markdown_ai_response(
                markdown,
                structured_hints=hints,
                request_source="global",
            )

        standardize.assert_not_called()
        for result in (single, global_result):
            self.assertEqual("rules", result["executionPath"])
            self.assertFalse(result["modelInvoked"])
            self.assertEqual(0, result["providerCallAttempts"])
            self.assertEqual("safe_to_apply", result["applyRecommendation"])
            self.assertEqual(4, result["resultStructure"]["optionCount"])
            self.assertEqual("B", result["answer"])
            self.assertEqual("直接计算。", result["analysis"])

    def test_placement_blocker_prevents_safe_rules_write_for_single_and_global(self):
        markdown = r"""题干

\begin{tasks}(4)
\task 甲
\task 乙
\task 丙
\task 丁
\end{tasks}"""
        hints = {
            "type": "choice",
            "options": [
                {"label": "A", "content": "甲"},
                {"label": "B", "content": "乙"},
                {"label": "C", "content": "丙"},
                {"label": "D", "content": "丁"},
            ],
            "imagePlacementValidation": {
                "blocking": True,
                "blockingReasons": ["stem_option_geometry_conflict"],
            },
        }

        with patch("app.import_services.standardize_markdown_with_llm") as standardize:
            results = [
                standardize_markdown_ai_response(markdown, structured_hints=hints, request_source=source)
                for source in ("single", "global")
            ]

        standardize.assert_not_called()
        for result in results:
            self.assertEqual("review_required", result["applyRecommendation"])
            self.assertIn("stem_option_geometry_conflict", result["reviewReasons"])

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
        self.assertEqual("llm", first["executionPath"])
        self.assertTrue(first["modelInvoked"])
        self.assertEqual("cache", second["executionPath"])
        self.assertEqual("llm", second["cachedExecutionPath"])
        self.assertFalse(second["modelInvoked"])
        self.assertEqual("safe_to_apply", second["applyRecommendation"])

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

    def test_standardize_router_cache_is_not_counted_as_provider_invocation(self):
        with patch("app.import_services.standardize_markdown_with_llm") as standardize:
            standardize.return_value = (
                "题干 $x+1=2$",
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
                    "llmCall": {"status": "success", "cacheHit": True},
                    "llmCalls": [{"status": "success", "cacheHit": True}],
                },
            )

            result = standardize_markdown_ai_response("题干 $x+1=2$")

        self.assertEqual("cache", result["executionPath"])
        self.assertEqual("llm", result["cachedExecutionPath"])
        self.assertFalse(result["modelInvoked"])
        self.assertTrue(result["cacheHit"])
        self.assertEqual(0, result["providerCallAttempts"])

    def test_standardize_preserves_original_choice_image_options_when_llm_drops_them(self):
        markdown = r"""如图所示的几何体是由 6 个小正方体搭成，它的左视图是（ ）$
\begin{array}{l}x

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

    def test_standardize_blocks_same_count_options_when_image_refs_are_removed(self):
        markdown = r"""题干 $
\begin{array}{l}x

\begin{tasks}(2)
\task ![](图1)
\task ![](图2)
\end{tasks}"""
        hints = {
            "type": "choice",
            "options": [
                {"label": "A", "content": "![](图1)"},
                {"label": "B", "content": "![](图2)"},
            ],
            "images": [
                {"imageId": "i1", "label": "图1"},
                {"imageId": "i2", "label": "图2"},
            ],
        }
        candidate = r"""题干

\begin{tasks}(2)
\task 文字甲
\task 文字乙
\end{tasks}"""

        with patch("app.import_services.standardize_markdown_with_llm") as standardize:
            standardize.return_value = (
                candidate,
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

        self.assertEqual("review_required", result["applyRecommendation"])
        self.assertIn("option_image_reference_removed", result["reviewReasons"])

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

    def test_rebank_import_question_reuses_existing_bank_question(self):
        task = {"id": "task_1", "title": "测试卷", "stage": "初中", "subject": "数学", "grade": "九年级"}
        question = {
            "id": "question_1",
            "number": 1,
            "status": "已入库",
            "bankQuestionId": "bank_question_1",
            "manualMarkdown": "修改后的题干",
            "stemMarkdown": "原题干",
            "answer": "B",
            "analysis": "解析",
            "type": "choice",
            "difficulty": "medium",
        }
        existing = {
            "id": "bank_question_1",
            "sourceImportTaskId": "task_1",
            "sourceImportQuestionId": "question_1",
            "manualMarkdown": "旧题干",
            "answer": "A",
            "createdAt": "2026-01-01T00:00:00",
        }
        store = {"bankQuestions": [existing]}

        index = find_bank_question_index_for_import(store, task, question)
        bank_question = bank_question_from_import(task, question, store["bankQuestions"][index])

        self.assertEqual(0, index)
        self.assertEqual("bank_question_1", bank_question["id"])
        self.assertEqual("2026-01-01T00:00:00", bank_question["createdAt"])
        self.assertEqual("修改后的题干", bank_question["manualMarkdown"])
        self.assertIsNone(bank_question_duplicate_reason(store, bank_question, bank_question["id"]))

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

    def test_image_placements_round_trip_from_ocr_to_import_and_bank_payload(self):
        task = {"id": "task-1", "stage": "初中", "subject": "数学", "grade": "七年级", "title": "测试卷"}
        placements = [
            {
                "placementId": "placement-a",
                "imageId": "images/a.png",
                "target": {"kind": "option", "optionLabel": "A"},
                "order": 0,
                "sourceEvidence": {"markdownStart": 42, "markdownEnd": 58},
                "inference": {"method": "explicit-offset", "confidence": 0.99, "reasons": ["inside-option-span"]},
                "reviewStatus": "auto",
            }
        ]
        outputs = {
            "questions": [
                {
                    "id": "q1",
                    "number": 1,
                    "type": "choice",
                    "stemMarkdown": "选择正确图片",
                    "images": [{"name": "a.png", "path": "images/a.png", "url": "/a.png"}],
                    "options": [{"label": "A", "content": "![](images/a.png)"}, {"label": "B", "content": "文字"}],
                    "imagePlacements": placements,
                }
            ]
        }

        with patch.dict("os.environ", {"ENABLE_IMPORT_SYNC_AI_ENRICH": "false"}):
            imported = build_import_questions(task, outputs, "")[0]
        banked = bank_question_from_import(task, imported)

        self.assertEqual(placements, imported["imagePlacements"])
        self.assertEqual(placements, banked["imagePlacements"])

    def test_build_import_questions_keeps_choice_option_images_out_of_stem(self):
        task = {"stage": "初中", "subject": "数学", "grade": "七年级", "title": "测试卷"}
        images = [
            {"name": "a.jpg", "path": "images/a.jpg", "url": "/files/a.jpg"},
            {"name": "b.jpg", "path": "images/b.jpg", "url": "/files/b.jpg"},
            {"name": "c.jpg", "path": "images/c.jpg", "url": "/files/c.jpg"},
            {"name": "d.jpg", "path": "images/d.jpg", "url": "/files/d.jpg"},
        ]
        outputs = {
            "sections": [
                {
                    "id": "section_1",
                    "questions": [
                        {
                            "id": "q_3",
                            "number": 3,
                            "type": "choice",
                            "stemMarkdown": "下面四个图中，线段 BE 是高的是（ ）",
                            "images": images,
                            "options": [
                                {"label": "A", "content": "![](images/a.jpg)"},
                                {"label": "B", "content": "![](images/b.jpg)"},
                                {"label": "C", "content": "![](images/c.jpg)"},
                                {"label": "D", "content": "![](images/d.jpg)"},
                            ],
                        }
                    ],
                }
            ],
        }

        with patch.dict("os.environ", {"ENABLE_IMPORT_SYNC_AI_ENRICH": "false"}):
            questions = build_import_questions(task, outputs, "")

        question = questions[0]
        self.assertEqual(4, len(question["images"]))
        self.assertNotIn("![]", question["stemMarkdown"])
        self.assertEqual(["![](图1)", "![](图2)", "![](图3)", "![](图4)"], [option["content"] for option in question["options"]])

    def test_build_import_questions_preserves_image_placement_validation(self):
        validation = {
            "blocking": True,
            "blockingReasons": ["choice_option_sequence_incomplete"],
        }
        outputs = {
            "sections": [
                {
                    "questions": [
                        {
                            "id": "q1",
                            "number": 1,
                            "type": "choice",
                            "stemMarkdown": "选择正确项",
                            "options": [{"label": "A", "content": "甲"}, {"label": "B", "content": "乙"}],
                            "images": [],
                            "imagePlacementValidation": validation,
                        }
                    ]
                }
            ]
        }

        with patch.dict("os.environ", {"ENABLE_IMPORT_SYNC_AI_ENRICH": "false", "OCR_AUTO_STANDARDIZE_MODE": "off"}):
            imported = build_import_questions({}, outputs, "")[0]

        self.assertEqual(validation, imported["imagePlacementValidation"])

    def test_build_import_questions_attaches_trailing_choice_images_to_text_options(self):
        task = {"stage": "初中", "subject": "物理", "grade": "八年级", "title": "测试卷"}
        images = [
            {"name": "a.jpg", "path": "images/a.jpg", "url": "/files/a.jpg"},
            {"name": "b.jpg", "path": "images/b.jpg", "url": "/files/b.jpg"},
            {"name": "c.jpg", "path": "images/c.jpg", "url": "/files/c.jpg"},
            {"name": "d.jpg", "path": "images/d.jpg", "url": "/files/d.jpg"},
        ]
        outputs = {
            "sections": [
                {
                    "id": "section_1",
                    "questions": [
                        {
                            "id": "q_2",
                            "number": 2,
                            "type": "choice",
                            "stemMarkdown": (
                                "如图所示，属于省力杠杆的是（ ）\n\n"
                                "![](images/a.jpg)\n\n![](images/b.jpg)\n\n"
                                "![](images/c.jpg)\n\n![](images/d.jpg)"
                            ),
                            "images": images,
                            "options": [
                                {"label": "A", "content": "食品夹"},
                                {"label": "B", "content": "船桨"},
                                {"label": "C", "content": "修枝剪刀"},
                                {"label": "D", "content": "托盘天平"},
                            ],
                        }
                    ],
                }
            ],
        }

        with patch.dict("os.environ", {"ENABLE_IMPORT_SYNC_AI_ENRICH": "false"}):
            questions = build_import_questions(task, outputs, "")

        question = questions[0]
        self.assertEqual(4, len(question["images"]))
        self.assertNotIn("![]", question["stemMarkdown"])
        self.assertEqual(
            ["![](图1)\n\n食品夹", "![](图2)\n\n船桨", "![](图3)\n\n修枝剪刀", "![](图4)\n\n托盘天平"],
            [option["content"] for option in question["options"]],
        )

    def test_build_import_questions_drops_unreferenced_choice_images_without_image_cue(self):
        task = {"stage": "初中", "subject": "数学", "grade": "七年级", "title": "测试卷"}
        outputs = {
            "sections": [
                {
                    "id": "section_1",
                    "questions": [
                        {
                            "id": "q_2",
                            "number": 2,
                            "type": "choice",
                            "stemMarkdown": "0.0000025 用科学记数法表示为（ ）",
                            "images": [
                                {"name": "a.jpg", "path": "images/a.jpg", "url": "/files/a.jpg"},
                                {"name": "b.jpg", "path": "images/b.jpg", "url": "/files/b.jpg"},
                            ],
                            "options": [
                                {"label": "A", "content": "$2.5\\times10^{-6}$"},
                                {"label": "B", "content": "$2.5\\times10^{6}$"},
                            ],
                        }
                    ],
                }
            ],
        }

        with patch.dict("os.environ", {"ENABLE_IMPORT_SYNC_AI_ENRICH": "false"}):
            questions = build_import_questions(task, outputs, "")

        self.assertEqual([], questions[0]["images"])
        self.assertNotIn("![]", questions[0]["stemMarkdown"])

    def test_ensure_question_images_removes_previously_appended_unreferenced_choice_images(self):
        question = {
            "id": "q2",
            "type": "choice",
            "stemMarkdown": "0.0000025 用科学记数法表示为（ ）\n\n![](图1)\n\n![](图2)",
            "manualMarkdown": "0.0000025 用科学记数法表示为（ ）\n\n![](图1)\n\n![](图2)",
            "images": [
                {"label": "图1", "name": "a.jpg", "path": "images/a.jpg", "url": "/files/a.jpg"},
                {"label": "图2", "name": "b.jpg", "path": "images/b.jpg", "url": "/files/b.jpg"},
            ],
            "options": [
                {"label": "A", "content": "$2.5\\times10^{-6}$"},
                {"label": "B", "content": "$2.5\\times10^{6}$"},
            ],
        }

        changed = ensure_question_images_in_markdown(question)

        self.assertTrue(changed)
        self.assertEqual([], question["images"])
        self.assertNotIn("![]", question["stemMarkdown"])

    def test_ensure_question_images_attaches_trailing_choice_images_to_options(self):
        question = {
            "id": "q2",
            "type": "choice",
            "stemMarkdown": "如图所示，属于省力杠杆的是（ ）\n\n![](图1)\n\n![](图2)\n\n![](图3)\n\n![](图4)",
            "manualMarkdown": "如图所示，属于省力杠杆的是（ ）\n\n![](图1)\n\n![](图2)\n\n![](图3)\n\n![](图4)",
            "images": [
                {"label": "图1", "name": "a.jpg", "path": "images/a.jpg", "url": "/files/a.jpg"},
                {"label": "图2", "name": "b.jpg", "path": "images/b.jpg", "url": "/files/b.jpg"},
                {"label": "图3", "name": "c.jpg", "path": "images/c.jpg", "url": "/files/c.jpg"},
                {"label": "图4", "name": "d.jpg", "path": "images/d.jpg", "url": "/files/d.jpg"},
            ],
            "options": [
                {"label": "A", "content": "食品夹"},
                {"label": "B", "content": "船桨"},
                {"label": "C", "content": "修枝剪刀"},
                {"label": "D", "content": "托盘天平"},
            ],
        }

        changed = ensure_question_images_in_markdown(question)

        self.assertTrue(changed)
        self.assertNotIn("![]", question["stemMarkdown"])
        self.assertEqual("![](图1)\n\n食品夹", question["options"][0]["content"])
        self.assertEqual("![](图4)\n\n托盘天平", question["options"][3]["content"])
        self.assertNotIn("![]", question["manualMarkdown"])

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

    def test_build_import_questions_uses_ocr_embedded_solution_without_ai_enrich(self):
        task = {"stage": "高中", "subject": "数学", "grade": "高三", "title": "专题汇编"}
        outputs = {
            "markdown": "1. 已知集合 A，则 A∩B=（ ）\n【答案】C\n【详解】公共元素为 C。",
            "sections": [
                {
                    "id": "section_1",
                    "questions": [
                        {
                            "id": "q_1",
                            "number": 1,
                            "type": "choice",
                            "stemMarkdown": "已知集合 A，则 A∩B=（ ）",
                            "answer": "C",
                            "analysis": "公共元素为 C。",
                            "answerEvidence": "【答案】C",
                            "analysisEvidence": "【详解】公共元素为 C。",
                            "options": [
                                {"label": "A", "content": "甲"},
                                {"label": "B", "content": "乙"},
                                {"label": "C", "content": "丙"},
                                {"label": "D", "content": "丁"},
                            ],
                        }
                    ],
                }
            ],
        }

        with patch.dict("os.environ", {"ENABLE_IMPORT_SYNC_AI_ENRICH": "false"}):
            questions = build_import_questions(task, outputs, "")

        self.assertEqual("C", questions[0]["answer"])
        self.assertEqual("公共元素为 C。", questions[0]["analysis"])
        self.assertTrue(questions[0]["aiMetadata"]["contextMatched"])
        self.assertEqual("【答案】C", questions[0]["aiMetadata"]["answerEvidence"])

    def test_build_import_questions_auto_standardizes_risky_questions_with_concurrency(self):
        task = {"stage": "初中", "subject": "数学", "grade": "七年级", "title": "测试卷"}
        outputs = {
            "markdown": "1. 第一题\n2. 第二题",
            "sections": [
                {
                    "id": "section_1",
                    "questions": [
                        {
                            "id": "q_1",
                            "number": 1,
                            "type": "choice",
                            "stemMarkdown": "第一题（ ）",
                            "options": [{"label": "A", "content": "甲"}],
                        },
                        {
                            "id": "q_2",
                            "number": 2,
                            "type": "choice",
                            "stemMarkdown": "第二题（ ）",
                            "options": [{"label": "A", "content": "丙"}],
                        },
                    ],
                }
            ],
        }

        request_priorities = []

        def standardize(markdown, **kwargs):
            request_priorities.append((kwargs.get("structured_hints") or {}).get("requestPriority"))
            if "第一题" in markdown:
                return (
                    "第一题（ ）\n\n\\begin{tasks}(2)\n\\task 甲\n\\task 乙\n\\end{tasks}",
                    {"source": "ai", "provider": "mock", "model": "mock", "error": None, "warnings": [], "confidence": "high"},
                )
            return (
                "第二题（ ）\n\n\\begin{tasks}(2)\n\\task 丙\n\\task 丁\n\\end{tasks}",
                {"source": "ai", "provider": "mock", "model": "mock", "error": None, "warnings": [], "confidence": "high"},
            )

        with patch.dict(
            "os.environ",
            {
                "ENABLE_IMPORT_SYNC_AI_ENRICH": "false",
                "OCR_AUTO_STANDARDIZE_MODE": "risky",
                "OCR_AUTO_STANDARDIZE_MAX_CONCURRENCY": "2",
                "DASHSCOPE_API_KEY": "key",
            },
        ):
            with patch("app.import_services.standardize_markdown_with_llm", side_effect=standardize) as standardize_llm:
                questions = build_import_questions(task, outputs, "")

        self.assertEqual(2, standardize_llm.call_count)
        self.assertEqual(["automatic", "automatic"], request_priorities)
        self.assertEqual(2, task["autoStandardize"]["appliedCount"])
        self.assertEqual(["A", "B"], [option["label"] for option in questions[0]["options"]])
        self.assertEqual(["甲", "乙"], [option["content"] for option in questions[0]["options"]])
        self.assertEqual("applied", questions[0]["autoStandardize"]["status"])
        self.assertIn("choice-option-count-low", questions[0]["autoStandardize"]["reasons"])

    def test_auto_standardize_blocks_candidate_that_drops_required_images(self):
        question = {
            "id": "q1",
            "number": 1,
            "type": "choice",
            "stemMarkdown": "选择正确图片。",
            "manualMarkdown": "选择正确图片。",
            "images": [{"label": "图1", "name": "a.jpg", "path": "images/a.jpg", "url": "/files/a.jpg"}],
            "options": [{"label": "A", "content": "![](图1)"}],
        }
        before_options = list(question["options"])

        with patch.dict("os.environ", {"OCR_AUTO_STANDARDIZE_MODE": "all", "DASHSCOPE_API_KEY": "key"}):
            with patch(
                "app.import_services.standardize_markdown_ai_response",
                return_value={
                    "markdown": "选择正确图片。\n\nA. 文字选项",
                    "standardizer": {"source": "ai", "error": None, "applyBlocked": False, "warnings": [], "confidence": "medium"},
                },
            ):
                summary = auto_standardize_import_questions([question], {}, {"markdown": "1. 选择正确图片"})

        self.assertEqual(0, summary["appliedCount"])
        self.assertEqual(before_options, question["options"])
        self.assertEqual("blocked", question["autoStandardize"]["status"])
        self.assertIn("candidate-dropped-images:图1", question["autoStandardize"]["validation"]["errors"])

    def test_auto_standardize_off_mode_does_not_call_llm(self):
        question = {
            "id": "q1",
            "number": 1,
            "type": "choice",
            "stemMarkdown": "第一题（ ）",
            "options": [{"label": "A", "content": "甲"}],
        }

        with patch.dict("os.environ", {"OCR_AUTO_STANDARDIZE_MODE": "off"}):
            with patch("app.import_services.standardize_markdown_ai_response") as standardize:
                summary = auto_standardize_import_questions([question], {}, {"markdown": "1. 第一题"})

        standardize.assert_not_called()
        self.assertFalse(summary["enabled"])

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
        self.assertTrue(question["manualOptionsEditedAt"])
        self.assertEqual(
            [
                {"label": "A", "content": "正确", "contentMarkdown": "正确"},
                {"label": "B", "content": "错误", "contentMarkdown": "错误"},
            ],
            question["subQuestions"][0]["options"],
        )


if __name__ == "__main__":
    unittest.main()
