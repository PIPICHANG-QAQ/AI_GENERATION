import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from app.visual_repair import apply_visual_repairs, detect_underline_segments, prepare_visual_repair_context


class VisualRepairTest(unittest.TestCase):
    def _write_question_image(self, path: Path) -> None:
        image = Image.new("RGB", (640, 360), "white")
        draw = ImageDraw.Draw(image)
        draw.text((40, 40), "22. complete proof fill blank", fill="black")
        draw.line((120, 130, 420, 130), fill="black", width=2)
        draw.line((180, 190, 500, 190), fill="black", width=2)
        image.save(path)

    def _write_content_list(self, output_dir: Path) -> None:
        (output_dir / "sample_content_list.json").write_text(
            """[
  {
    "type": "text",
    "text": "22. （8分）完成推理填空\\n证明：",
    "bbox": [20, 20, 620, 330],
    "page_idx": 0
  }
]""",
            encoding="utf-8",
        )

    def _write_two_question_image(self, path: Path) -> None:
        image = Image.new("RGB", (640, 380), "white")
        draw = ImageDraw.Draw(image)
        draw.text((40, 40), "22. complete proof fill blank", fill="black")
        draw.line((120, 130, 420, 130), fill="black", width=2)
        draw.text((40, 220), "23. complete another fill blank", fill="black")
        draw.line((140, 300, 430, 300), fill="black", width=2)
        image.save(path)

    def _write_two_question_content_list(self, output_dir: Path) -> None:
        (output_dir / "sample_content_list.json").write_text(
            """[
  {
    "type": "text",
    "text": "22. （8分）完成推理填空",
    "bbox": [20, 20, 620, 170],
    "page_idx": 0
  },
  {
    "type": "text",
    "text": "23. （8分）继续完成推理填空",
    "bbox": [20, 190, 620, 350],
    "page_idx": 0
  }
]""",
            encoding="utf-8",
        )

    def test_detect_underline_segments_finds_long_horizontal_lines(self):
        image = Image.new("RGB", (500, 200), "white")
        draw = ImageDraw.Draw(image)
        draw.line((50, 80, 360, 80), fill="black", width=2)

        segments = detect_underline_segments(image)

        self.assertEqual(1, len(segments))
        self.assertGreaterEqual(segments[0]["x1"] - segments[0]["x0"], 250)

    def test_apply_visual_repairs_adds_placeholders_from_question_crop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "outputs"
            output_dir.mkdir()
            upload = root / "paper.png"
            self._write_question_image(upload)
            self._write_content_list(output_dir)
            structured = {
                "sections": [
                    {
                        "id": "section_1",
                        "questions": [
                            {
                                "id": "q_22",
                                "number": 22,
                                "type": "fill_blank",
                                "stemMarkdown": "（8分）完成推理填空\n证明：",
                                "manualMarkdown": "（8分）完成推理填空\n证明：",
                                "options": [],
                            }
                        ],
                    }
                ]
            }

            with patch.dict(os.environ, {"OCR_VISUAL_REPAIR_ENABLED": "true"}, clear=False):
                summary = apply_visual_repairs(structured, output_dir, upload, "job_1")

            question = structured["sections"][0]["questions"][0]
            self.assertEqual(1, summary["cropCount"])
            self.assertGreaterEqual(summary["underlineCount"], 2)
            self.assertIn("____", question["stemMarkdown"])
            self.assertEqual("checked", question["visualRepair"]["status"])
            self.assertTrue((output_dir / question["visualRepair"]["cropPath"]).exists())

    def test_apply_visual_repairs_can_apply_pix2text_secondary_ocr(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "outputs"
            output_dir.mkdir()
            upload = root / "paper.png"
            self._write_question_image(upload)
            self._write_content_list(output_dir)
            command = root / "pix2text_mock.py"
            command.write_text(
                "import sys\n"
                "print('22. （8分）完成推理填空\\n证明：因为 A=B（已知）\\n因此 ____')\n",
                encoding="utf-8",
            )
            structured = {
                "sections": [
                    {
                        "id": "section_1",
                        "questions": [
                            {
                                "id": "q_22",
                                "number": 22,
                                "type": "fill_blank",
                                "stemMarkdown": "（8分）完成推理填空",
                                "manualMarkdown": "（8分）完成推理填空",
                                "options": [],
                            }
                        ],
                    }
                ]
            }

            env = {
                "OCR_VISUAL_REPAIR_ENABLED": "true",
                "PIX2TEXT_COMMAND": f"{os.sys.executable} {command} {{image}}",
                "OCR_VISUAL_REPAIR_APPLY_PIX2TEXT": "true",
            }
            with patch.dict(os.environ, env, clear=False):
                summary = apply_visual_repairs(structured, output_dir, upload, "job_1")

        question = structured["sections"][0]["questions"][0]
        self.assertEqual(1, summary["secondaryOcr"]["attempted"])
        self.assertEqual(1, summary["secondaryOcr"]["applied"])
        self.assertIn("因为 A=B", question["stemMarkdown"])
        self.assertTrue(question["visualRepair"]["secondaryOcr"]["applied"])

    def test_apply_visual_repairs_merges_concurrent_results_in_question_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "outputs"
            output_dir.mkdir()
            upload = root / "paper.png"
            self._write_two_question_image(upload)
            self._write_two_question_content_list(output_dir)
            structured = {
                "sections": [
                    {
                        "id": "section_1",
                        "questions": [
                            {
                                "id": "q_22",
                                "number": 22,
                                "type": "fill_blank",
                                "stemMarkdown": "完成推理填空",
                                "manualMarkdown": "完成推理填空",
                                "options": [],
                            },
                            {
                                "id": "q_23",
                                "number": 23,
                                "type": "fill_blank",
                                "stemMarkdown": "继续完成推理填空",
                                "manualMarkdown": "继续完成推理填空",
                                "options": [],
                            },
                        ],
                    }
                ]
            }

            context = prepare_visual_repair_context(output_dir, upload)
            with patch.dict(os.environ, {"OCR_VISUAL_REPAIR_MAX_CONCURRENCY": "2"}, clear=False):
                with patch("app.visual_repair.run_secondary_ocr", return_value=(None, None)):
                    summary = apply_visual_repairs(structured, output_dir, upload, "job_1", context)

            questions = structured["sections"][0]["questions"]
            self.assertEqual(2, summary["candidateCount"])
            self.assertEqual(2, summary["maxConcurrency"])
            self.assertEqual(1, summary["preprocessed"]["preloadedPageCount"])
            self.assertEqual("checked", questions[0]["visualRepair"]["status"])
            self.assertEqual("checked", questions[1]["visualRepair"]["status"])
            self.assertTrue(questions[0]["visualRepair"]["cropPath"].endswith("000_q_22.png"))
            self.assertTrue(questions[1]["visualRepair"]["cropPath"].endswith("001_q_23.png"))


if __name__ == "__main__":
    unittest.main()
