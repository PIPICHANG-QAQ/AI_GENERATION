import json
import shutil
import unittest

from PIL import Image

from app.question_layout import (
    build_paper_layout,
    load_layout_items,
    regions_for_items,
)
from app.worker_base import IMPORT_UPLOAD_ROOT, OUTPUT_ROOT


class QuestionLayoutTest(unittest.TestCase):
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
        self.assertEqual([1, 2], [region["index"] for region in layout["regions"]])


if __name__ == "__main__":
    unittest.main()
