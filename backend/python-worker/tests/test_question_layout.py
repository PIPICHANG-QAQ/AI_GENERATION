import json
import shutil
import unittest
from unittest.mock import patch

from PIL import Image

from app.question_layout import (
    attach_paper_layout,
    build_paper_layout,
    load_image_placement_evidence,
    load_layout_items,
    merge_canonical_regions,
    regions_for_items,
)
from app.worker_base import IMPORT_UPLOAD_ROOT, OUTPUT_ROOT


class QuestionLayoutTest(unittest.TestCase):
    def test_overlapping_regions_for_same_canonical_question_are_unioned(self):
        regions = [
            {
                "questionId": "q_2",
                "index": 2,
                "pageIndex": 0,
                "x": 0.14,
                "y": 0.27,
                "w": 0.59,
                "h": 0.13,
                "confidence": 0.96,
            },
            {
                "questionId": "q_2_2",
                "index": 2,
                "pageIndex": 0,
                "x": 0.16,
                "y": 0.38,
                "w": 0.69,
                "h": 0.15,
                "confidence": 0.96,
            },
        ]

        merged = merge_canonical_regions(regions, {"q_2": "q_2", "q_2_2": "q_2"})

        self.assertEqual(1, len(merged))
        self.assertEqual("q_2", merged[0]["questionId"])
        self.assertEqual(0.14, merged[0]["x"])
        self.assertEqual(0.27, merged[0]["y"])
        self.assertEqual(0.71, round(merged[0]["w"], 2))
        self.assertEqual(0.26, round(merged[0]["h"], 2))
        self.assertEqual(2, len(merged[0]["mergedFromRegions"]))

    def test_cross_page_regions_remain_separate(self):
        regions = [
            {"questionId": "q_7", "index": 7, "pageIndex": 0, "x": 0.1, "y": 0.8, "w": 0.8, "h": 0.15},
            {"questionId": "q_7", "index": 7, "pageIndex": 1, "x": 0.1, "y": 0.0, "w": 0.8, "h": 0.2},
        ]

        merged = merge_canonical_regions(regions, {"q_7": "q_7"})

        self.assertEqual(2, len(merged))
        self.assertEqual([0, 1], [region["pageIndex"] for region in merged])

    def test_separate_regions_for_same_question_are_not_unioned(self):
        regions = [
            {"questionId": "q_9", "index": 9, "pageIndex": 0, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.1},
            {"questionId": "q_9", "index": 9, "pageIndex": 0, "x": 0.7, "y": 0.5, "w": 0.2, "h": 0.1},
        ]

        self.assertEqual(2, len(merge_canonical_regions(regions, {"q_9": "q_9"})))

    def test_image_placement_evidence_exposes_sanitized_read_only_nodes(self):
        content_list = [
            {"type": "text", "text": "A.", "bbox": [100, 100, 140, 130], "page_idx": 0},
            {"type": "image", "img_path": "images/a.png", "bbox": [120, 140, 300, 260], "page_idx": 0},
        ]
        (self.output_dir / "paper_content_list.json").write_text(
            json.dumps(content_list, ensure_ascii=False),
            encoding="utf-8",
        )

        nodes = load_image_placement_evidence(self.output_dir)

        self.assertEqual(2, len(nodes))
        self.assertEqual(
            {"blockId", "type", "text", "imageRef", "pageIndex", "bbox"},
            set(nodes[0]),
        )
        self.assertTrue(all(node["blockId"] for node in nodes))

    def setUp(self):
        self.job_id = "layout_test_job"
        self.task_id = "import_task_layout_test"
        self.upload_dir = IMPORT_UPLOAD_ROOT / self.job_id
        self.output_dir = OUTPUT_ROOT / self.job_id
        shutil.rmtree(self.upload_dir, ignore_errors=True)
        shutil.rmtree(self.output_dir, ignore_errors=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.paper_path = self.upload_dir / "paper.png"
        Image.new("RGB", (1000, 1200), "white").save(self.paper_path)

    def tearDown(self):
        shutil.rmtree(self.upload_dir, ignore_errors=True)
        shutil.rmtree(self.output_dir, ignore_errors=True)

    def test_attach_paper_layout_returns_empty_layout_when_disabled(self):
        task = {"id": self.task_id, "paperOcrJobId": self.job_id, "questions": [{"id": "question_a"}]}
        job = {"jobId": self.job_id, "status": "success", "uploadPath": str(self.paper_path), "outputs": {}}

        with patch.dict("os.environ", {"OCR_PAPER_LAYOUT_ENABLED": "false"}):
            layout = attach_paper_layout(task, job)

        self.assertEqual([], layout["pages"])
        self.assertEqual([], layout["regions"])
        self.assertEqual(["布局解析框已关闭"], layout["warnings"])
        self.assertEqual(layout, task["paperLayout"])

    def test_builds_question_layout_and_binds_question_ids(self):
        markdown = "一、选择题\n1. 第一题题干\n题图\n2. 第二题题干\n"
        content_list = [
            {"type": "text", "text": "一、选择题", "bbox": [80, 40, 240, 70], "page_idx": 0},
            {"type": "text", "text": "1. 第一题题干", "bbox": [100, 100, 320, 140], "page_idx": 0},
            {"type": "image", "img_path": "images/q1.png", "bbox": [110, 150, 260, 260], "page_idx": 0},
            {"type": "text", "text": "题图", "bbox": [100, 270, 180, 300], "page_idx": 0},
            {"type": "text", "text": "2. 第二题题干", "bbox": [100, 340, 320, 380], "page_idx": 0},
        ]
        (self.output_dir / "paper_content_list.json").write_text(
            json.dumps(content_list, ensure_ascii=False),
            encoding="utf-8",
        )
        task = {
            "id": self.task_id,
            "paperOcrJobId": self.job_id,
            "questions": [
                {"id": "question_a", "sourceQuestionId": "ocr_q1"},
                {"id": "question_b", "sourceQuestionId": "ocr_q2"},
            ],
        }
        job = {
            "jobId": self.job_id,
            "status": "success",
            "uploadPath": str(self.paper_path),
            "outputs": {
                "markdown": markdown,
                "sections": [
                    {
                        "questions": [
                            {
                                "id": "ocr_q1",
                                "number": "1",
                                "sourceEvidence": {
                                    "start": markdown.index("1."),
                                    "end": markdown.index("2."),
                                },
                            },
                            {
                                "id": "ocr_q2",
                                "number": "2",
                                "sourceEvidence": {
                                    "start": markdown.index("2."),
                                    "end": len(markdown),
                                },
                            },
                        ],
                    }
                ],
            },
        }

        layout = build_paper_layout(task, job)

        self.assertEqual(1, len(layout["pages"]))
        self.assertEqual(2, len(layout["regions"]))
        self.assertEqual([1, 2], [region["index"] for region in layout["regions"]])
        self.assertEqual(["mineru_question", "mineru_question"], [region["source"] for region in layout["regions"]])
        self.assertEqual(["question_a", "question_b"], [region["questionId"] for region in layout["regions"]])
        self.assertLess(layout["regions"][0]["y"], layout["regions"][1]["y"])
        self.assertEqual([], layout["warnings"])

    def test_regions_are_grouped_per_page_for_cross_page_parent(self):
        items = [
            {"bbox": [100, 100, 300, 200], "pageIndex": 0},
            {"bbox": [120, 40, 360, 180], "pageIndex": 1},
        ]

        regions = regions_for_items(
            items,
            {0: (1000, 1200), 1: (1000, 1200)},
            question_id="question_a",
            index=7,
        )

        self.assertEqual(2, len(regions))
        self.assertEqual([0, 1], [region["pageIndex"] for region in regions])
        self.assertEqual([7, 7], [region["index"] for region in regions])

    def test_question_layout_filters_titles_and_section_text(self):
        markdown = "2019 年试卷\n选择题说明\n1. 第一题题干\nA. 1\n2. 第二题题干\n"
        content_list = [
            {"type": "title", "text": "2019 年试卷", "bbox": [120, 70, 500, 100], "page_idx": 0},
            {"type": "text", "text": "选择题说明", "bbox": [120, 110, 500, 140], "page_idx": 0},
            {"type": "text", "text": "1. 第一题题干", "bbox": [120, 180, 500, 220], "page_idx": 0},
            {"type": "text", "text": "A. 1", "bbox": [140, 230, 220, 260], "page_idx": 0},
            {"type": "text", "text": "2. 第二题题干", "bbox": [120, 310, 500, 350], "page_idx": 0},
        ]
        (self.output_dir / "paper_content_list.json").write_text(
            json.dumps(content_list, ensure_ascii=False),
            encoding="utf-8",
        )
        task = {
            "id": self.task_id,
            "paperOcrJobId": self.job_id,
            "questions": [
                {"id": "question_a", "sourceQuestionId": "ocr_q1"},
                {"id": "question_b", "sourceQuestionId": "ocr_q2"},
            ],
        }
        job = {
            "jobId": self.job_id,
            "status": "success",
            "uploadPath": str(self.paper_path),
            "outputs": {
                "markdown": markdown,
                "sections": [
                    {
                        "questions": [
                            {
                                "id": "ocr_q1",
                                "number": "1",
                                "sourceEvidence": {"start": 0, "end": markdown.index("2.")},
                            },
                            {
                                "id": "ocr_q2",
                                "number": "2",
                                "sourceEvidence": {"start": markdown.index("2."), "end": len(markdown)},
                            },
                        ],
                    }
                ],
            },
        }

        layout = build_paper_layout(task, job)

        self.assertEqual(2, len(layout["regions"]))
        self.assertEqual(["question_a", "question_b"], [region["questionId"] for region in layout["regions"]])
        self.assertEqual([1, 2], [region["index"] for region in layout["regions"]])
        self.assertGreater(layout["regions"][0]["y"], 0.1)

    def test_question_layout_uses_source_evidence_after_preface_anchors_are_filtered(self):
        markdown = "考生注意：\n1.本试卷共2题，满分100分；\n2.答题纸另页。\n一、填空题（本大题共有2题）\n1. 第一题题干\n2. 第二题题干\n"
        q1_start = markdown.index("1. 第一题题干")
        q2_start = markdown.index("2. 第二题题干")
        content_list = [
            {"type": "text", "text": "考生注意：", "bbox": [100, 80, 220, 110], "page_idx": 0},
            {"type": "text", "text": "1.本试卷共2题，满分100分；", "bbox": [100, 120, 520, 155], "page_idx": 0},
            {"type": "text", "text": "2.答题纸另页。", "bbox": [100, 165, 360, 195], "page_idx": 0},
            {"type": "text", "text": "一、填空题（本大题共有2题）", "bbox": [100, 230, 580, 265], "page_idx": 0},
            {"type": "text", "text": "1. 第一题题干 OCR", "bbox": [120, 320, 520, 360], "page_idx": 0},
            {"type": "text", "text": "2. 第二题题干 OCR", "bbox": [120, 410, 520, 450], "page_idx": 0},
        ]
        (self.output_dir / "paper_content_list.json").write_text(
            json.dumps(content_list, ensure_ascii=False),
            encoding="utf-8",
        )
        task = {
            "id": self.task_id,
            "paperOcrJobId": self.job_id,
            "questions": [
                {"id": "question_1", "sourceQuestionId": "ocr_q1", "number": 1},
                {"id": "question_2", "sourceQuestionId": "ocr_q2", "number": 2},
            ],
        }
        job = {
            "jobId": self.job_id,
            "status": "success",
            "uploadPath": str(self.paper_path),
            "outputs": {
                "markdown": markdown,
                "sections": [
                    {
                        "questions": [
                            {"id": "ocr_q1", "number": 1, "sourceEvidence": {"start": q1_start, "end": q2_start}},
                            {"id": "ocr_q2", "number": 2, "sourceEvidence": {"start": q2_start, "end": len(markdown)}},
                        ]
                    }
                ],
            },
        }

        layout = build_paper_layout(task, job)

        self.assertEqual(2, len(layout["regions"]))
        self.assertEqual(["question_1", "question_2"], [region["questionId"] for region in layout["regions"]])
        self.assertEqual([1, 2], [region["index"] for region in layout["regions"]])
        self.assertGreater(layout["regions"][0]["y"], 0.25)

    def test_question_layout_uses_middle_page_size_for_coordinates(self):
        middle = {
            "pdf_info": [
                {
                    "page_idx": 0,
                    "page_size": [500, 600],
                    "para_blocks": [
                        {
                            "type": "title",
                            "bbox": [50, 30, 450, 60],
                            "index": 1,
                            "lines": [
                                {
                                    "spans": [
                                        {
                                            "type": "text",
                                            "content": "试卷标题",
                                        }
                                    ]
                                }
                            ],
                        },
                        {
                            "type": "text",
                            "bbox": [50, 120, 450, 180],
                            "index": 2,
                            "lines": [
                                {
                                    "spans": [
                                        {
                                            "type": "text",
                                            "content": "1. 第一题题干",
                                        }
                                    ]
                                }
                            ],
                        },
                    ],
                    "discarded_blocks": [
                        {
                            "type": "page_number",
                            "bbox": [200, 540, 300, 590],
                            "index": 2,
                            "lines": [
                                {
                                    "spans": [
                                        {
                                            "type": "text",
                                            "content": "第1页",
                                        }
                                    ]
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        (self.output_dir / "paper_middle.json").write_text(
            json.dumps(middle, ensure_ascii=False),
            encoding="utf-8",
        )
        task = {
            "id": self.task_id,
            "paperOcrJobId": self.job_id,
            "questions": [
                {"id": "question_a", "sourceQuestionId": "ocr_q1"},
            ],
        }
        job = {
            "jobId": self.job_id,
            "status": "success",
            "uploadPath": str(self.paper_path),
            "outputs": {},
        }

        layout = build_paper_layout(task, job)

        self.assertEqual(1, len(layout["regions"]))
        self.assertEqual("question_a", layout["regions"][0]["questionId"])
        self.assertEqual("middle", layout["regions"][0]["coordinateSource"])
        self.assertAlmostEqual(0.19, layout["regions"][0]["y"], places=2)
        self.assertAlmostEqual(0.11, layout["regions"][0]["h"], places=2)

    def test_multiline_mineru_item_is_split_before_anchor_grouping(self):
        markdown = "2019 年试卷\n1. 第一题题干\nA. 1\n2. 第二题题干"
        content_list = [
            {
                "type": "text",
                "text": markdown,
                "bbox": [100, 100, 500, 260],
                "page_idx": 0,
            }
        ]
        (self.output_dir / "paper_content_list.json").write_text(
            json.dumps(content_list, ensure_ascii=False),
            encoding="utf-8",
        )

        items = load_layout_items(self.output_dir)

        self.assertEqual(["2019 年试卷", "1. 第一题题干", "A. 1", "2. 第二题题干"], [item["text"] for item in items])
        self.assertEqual(140.0, items[1]["bbox"][1])
        self.assertEqual(180.0, items[1]["bbox"][3])

        task = {
            "id": self.task_id,
            "paperOcrJobId": self.job_id,
            "questions": [
                {"id": "question_a", "sourceQuestionId": "ocr_q1"},
                {"id": "question_b", "sourceQuestionId": "ocr_q2"},
            ],
        }
        job = {
            "jobId": self.job_id,
            "status": "success",
            "uploadPath": str(self.paper_path),
            "outputs": {
                "markdown": markdown,
                "sections": [
                    {
                        "questions": [
                            {"id": "ocr_q1", "number": "1", "sourceEvidence": {"start": 0, "end": markdown.index("2.")}},
                            {"id": "ocr_q2", "number": "2", "sourceEvidence": {"start": markdown.index("2."), "end": len(markdown)}},
                        ]
                    }
                ],
            },
        }

        layout = build_paper_layout(task, job)

        self.assertEqual(2, len(layout["regions"]))
        self.assertEqual(["question_a", "question_b"], [region["questionId"] for region in layout["regions"]])

    def test_geometry_order_keeps_image_with_following_question(self):
        markdown = "7. 第七题题干\n8. 第八题题干\n"
        content_list = [
            {"type": "text", "text": "7. 第七题题干", "bbox": [100, 700, 500, 740], "page_idx": 0},
            {"type": "image", "img_path": "images/q8.png", "bbox": [110, 760, 300, 830], "page_idx": 0},
            {"type": "text", "text": "8. 第八题题干", "bbox": [100, 750, 520, 860], "page_idx": 0},
        ]
        (self.output_dir / "paper_content_list.json").write_text(
            json.dumps(content_list, ensure_ascii=False),
            encoding="utf-8",
        )
        task = {
            "id": self.task_id,
            "paperOcrJobId": self.job_id,
            "questions": [
                {"id": "question_7", "sourceQuestionId": "ocr_q7"},
                {"id": "question_8", "sourceQuestionId": "ocr_q8"},
            ],
        }
        job = {
            "jobId": self.job_id,
            "status": "success",
            "uploadPath": str(self.paper_path),
            "outputs": {
                "markdown": markdown,
                "sections": [
                    {
                        "questions": [
                            {"id": "ocr_q7", "number": "7", "sourceEvidence": {"start": 0, "end": markdown.index("8.")}},
                            {"id": "ocr_q8", "number": "8", "sourceEvidence": {"start": markdown.index("8."), "end": len(markdown)}},
                        ]
                    }
                ],
            },
        }

        layout = build_paper_layout(task, job)

        self.assertEqual(2, len(layout["regions"]))
        self.assertEqual(["question_7", "question_8"], [region["questionId"] for region in layout["regions"]])
        self.assertEqual([7, 8], [region["index"] for region in layout["regions"]])

    def test_nested_middle_images_and_option_labels_do_not_shift_next_question_region(self):
        def image_block(index, bbox, image_path):
            return {
                "type": "image",
                "bbox": bbox,
                "index": index,
                "blocks": [
                    {
                        "type": "image_body",
                        "bbox": bbox,
                        "index": index,
                        "lines": [{"spans": [{"type": "image", "image_path": image_path}]}],
                    }
                ],
            }

        markdown = (
            "1. 下面四个图中，线段BE是VABC的高的是（）\n\n"
            "A\n\n![](images/tri_a.jpg)\n\n"
            "B.\n\n![](images/tri_b.jpg)\n\n"
            "C.\n\n![](images/tri_c.jpg)\n\n"
            "D.\n\n![](images/tri_d.jpg)\n\n"
            "2. 马扎侧面示意图. 若 $\\angle A O B = 8 0 ^ { \\circ }$ ，则 $\\angle A$ 的度数为(）\n\n"
            "![](images/stool.jpg)"
        )
        q2_start = markdown.index("2.")
        middle = {
            "pdf_info": [
                {
                    "page_idx": 0,
                    "page_size": [200, 200],
                    "para_blocks": [
                        {"type": "text", "bbox": [15, 61, 94, 66], "index": 1, "lines": [{"spans": [{"type": "text", "content": "1. 下面四个图中，线段BE是VABC的高的是（）"}]}]},
                        {"type": "text", "bbox": [15, 78, 20, 82], "index": 2, "lines": [{"spans": [{"type": "text", "content": "A"}]}]},
                        image_block(3, [21, 69, 49, 91], "tri_a.jpg"),
                        {"type": "text", "bbox": [91, 77, 95, 82], "index": 4, "lines": [{"spans": [{"type": "text", "content": "B."}]}]},
                        image_block(5, [96, 70, 127, 89], "tri_b.jpg"),
                        {"type": "text", "bbox": [15, 99, 20, 104], "index": 6, "lines": [{"spans": [{"type": "text", "content": "C."}]}]},
                        image_block(7, [20, 92, 59, 111], "tri_c.jpg"),
                        {"type": "text", "bbox": [91, 99, 96, 104], "index": 8, "lines": [{"spans": [{"type": "text", "content": "D."}]}]},
                        image_block(9, [96, 93, 132, 109], "tri_d.jpg"),
                        {"type": "text", "bbox": [15, 112, 168, 125], "index": 10, "lines": [{"spans": [{"type": "text", "content": "2. 马扎侧面示意图. 若\\angle A O B = 8 0 ^ { \\circ }，则\\angle A的度数为(）"}]}]},
                        image_block(11, [50, 128, 78, 138], "stool.jpg"),
                    ],
                }
            ],
        }
        (self.output_dir / "paper_middle.json").write_text(
            json.dumps(middle, ensure_ascii=False),
            encoding="utf-8",
        )
        task = {
            "id": self.task_id,
            "paperOcrJobId": self.job_id,
            "questions": [
                {"id": "question_choice", "sourceQuestionId": "ocr_q1", "images": [{}, {}, {}, {}]},
                {"id": "question_geometry", "sourceQuestionId": "ocr_q2", "images": [{}]},
            ],
        }
        job = {
            "jobId": self.job_id,
            "status": "success",
            "uploadPath": str(self.paper_path),
            "outputs": {
                "markdown": markdown,
                "sections": [
                    {
                        "questions": [
                            {
                                "id": "ocr_q1",
                                "number": "1",
                                "stemMarkdown": "下面四个图中，线段BE是VABC的高的是（）",
                                "sourceEvidence": {"start": 0, "end": q2_start},
                            },
                            {
                                "id": "ocr_q2",
                                "number": "2",
                                "stemMarkdown": "马扎侧面示意图. 若 $\\angle A O B = 8 0 ^ { \\circ }$ ，则 $\\angle A$ 的度数为(）",
                                "sourceEvidence": {"start": q2_start, "end": len(markdown)},
                            },
                        ]
                    }
                ],
            },
        }

        layout = build_paper_layout(task, job)

        self.assertEqual(2, len(layout["regions"]))
        self.assertEqual(["question_choice", "question_geometry"], [region["questionId"] for region in layout["regions"]])
        self.assertGreater(layout["regions"][0]["w"], 0.55)
        self.assertGreater(layout["regions"][0]["h"], 0.2)
        self.assertGreater(layout["regions"][1]["y"], 0.5)
        self.assertGreater(layout["regions"][1]["w"], 0.7)
        self.assertGreater(layout["regions"][1]["h"], 0.1)

    def test_question_layout_prefers_original_question_number_for_region_label(self):
        markdown = "11. 第十一题题干\n12. 第十二题题干\n"
        content_list = [
            {"type": "text", "text": "11. 第十一题题干", "bbox": [100, 100, 500, 140], "page_idx": 0},
            {"type": "text", "text": "12. 第十二题题干", "bbox": [100, 220, 520, 260], "page_idx": 0},
        ]
        (self.output_dir / "paper_content_list.json").write_text(
            json.dumps(content_list, ensure_ascii=False),
            encoding="utf-8",
        )
        task = {
            "id": self.task_id,
            "paperOcrJobId": self.job_id,
            "questions": [
                {"id": "question_11", "sourceQuestionId": "ocr_q11", "number": 1},
                {"id": "question_12", "sourceQuestionId": "ocr_q12", "number": 2},
            ],
        }
        job = {
            "jobId": self.job_id,
            "status": "success",
            "uploadPath": str(self.paper_path),
            "outputs": {
                "markdown": markdown,
                "sections": [
                    {
                        "questions": [
                            {"id": "ocr_q11", "number": "11", "sourceEvidence": {"start": 0, "end": markdown.index("12.")}},
                            {"id": "ocr_q12", "number": "12", "sourceEvidence": {"start": markdown.index("12."), "end": len(markdown)}},
                        ]
                    }
                ],
            },
        }

        layout = build_paper_layout(task, job)

        self.assertEqual([11, 12], [region["index"] for region in layout["regions"]])


if __name__ == "__main__":
    unittest.main()
