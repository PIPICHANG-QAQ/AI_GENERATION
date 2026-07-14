from __future__ import annotations

import os
from pathlib import Path
import tempfile
from unittest import TestCase, mock

from app.import_services import ocr_auto_standardize_max_workers, ocr_auto_standardize_mode
from app.llm_splitter import llm_runtime_options
from app.visual_repair import apply_visual_repairs
from app.adaptive_concurrency import reset_standardization_concurrency_gate, standardization_concurrency_gate
from app.ocr_flow import MineruOcrProvider
from app.worker_base import (
    DEFAULT_OCR_PROVIDER_EXTENSIONS,
    MINERU_EXTENSIONS,
    OCR_FLOW_STEP_DEFINITIONS,
    OCR_PROVIDER_EXTENSIONS,
    MINERU_TIMEOUT_SECONDS,
    MINERU_VERSION_TIMEOUT_SECONDS,
)


class WorkerConfigurationContractTest(TestCase):
    def test_python_defaults_and_step_order_are_frozen(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            options = llm_runtime_options()
            self.assertEqual(1, options["maxConcurrency"])
            self.assertEqual(1, options["boundaryMaxConcurrency"])
            self.assertEqual(1, options["standardizeMaxConcurrency"])
            self.assertEqual(1, options["analysisMaxConcurrency"])
            self.assertEqual(2, options["standardizeMaxAttempts"])
            self.assertEqual(2, options["analysisMaxAttempts"])
            self.assertEqual(4, options["localMaxConcurrency"])
            self.assertEqual(1, options["externalMaxConcurrency"])
            self.assertEqual("skip", options["autoSemanticRepairMode"])
            self.assertEqual("risky", ocr_auto_standardize_mode())
            self.assertEqual(2, ocr_auto_standardize_max_workers())

        self.assertEqual(
            [
                "upload", "preprocess", "ocr-provider", "collect-outputs",
                "local-boundary-detect", "llm-boundary-refine", "question-structure-build",
                "sub-question-split", "visual-repair", "structure-validate", "math-normalize", "ai-enrich",
            ],
            [step["id"] for step in OCR_FLOW_STEP_DEFINITIONS],
        )
        self.assertEqual(1800, MINERU_TIMEOUT_SECONDS)
        self.assertEqual(3, MINERU_VERSION_TIMEOUT_SECONDS)
        expected_extensions = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".docx", ".pptx", ".xlsx"}
        self.assertEqual(expected_extensions, DEFAULT_OCR_PROVIDER_EXTENSIONS)
        self.assertEqual(expected_extensions, OCR_PROVIDER_EXTENSIONS)
        self.assertEqual(OCR_PROVIDER_EXTENSIONS, MINERU_EXTENSIONS)
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(MineruOcrProvider(Path("/tmp/ocrflow-config-contract"), 3)._api_url())
        reset_standardization_concurrency_gate()
        with mock.patch.dict(os.environ, {}, clear=True):
            gate = standardization_concurrency_gate().snapshot()
        self.assertEqual({"limit": 4, "minimum": 2, "maximum": 8}, {
            key: gate[key] for key in ("limit", "minimum", "maximum")
        })
        reset_standardization_concurrency_gate()

    def test_visual_repair_default_and_disable_contract(self):
        structured = {
            "sections": [{"questions": [
                {"type": "fill_blank", "stemMarkdown": "第一题 ____"},
                {"type": "fill_blank", "stemMarkdown": "第二题 ____"},
            ]}],
        }
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {}, clear=True):
                summary = apply_visual_repairs(
                    structured, Path(directory), None, "config-contract",
                    {"visualItems": [], "pageSizes": {}, "pageImages": {}},
                )
            self.assertTrue(summary["enabled"])
            self.assertEqual(2, summary["maxConcurrency"])
            with mock.patch.dict(os.environ, {"OCR_VISUAL_REPAIR_ENABLED": "false"}, clear=True):
                disabled = apply_visual_repairs(structured, Path(directory), None, "config-contract")
            self.assertFalse(disabled["enabled"])

        visual_source = Path(__file__).resolve().parents[1].joinpath("app", "visual_repair.py").read_text(encoding="utf-8")
        for expected in (
            'os.getenv("OCR_VISUAL_REPAIR_PRELOAD_ENABLED", "true")',
            'clamped_int_env("OCR_VISUAL_REPAIR_PRELOAD_MAX_PAGES", 4, 0, 32)',
            'os.getenv("OCR_VISUAL_REPAIR_PDF_RENDER_SCALE", "2.0")',
            'os.getenv("OCR_VISUAL_REPAIR_CROP_PADDING", "12")',
            'os.getenv("OCR_VISUAL_REPAIR_DARK_THRESHOLD", "175")',
            'os.getenv("OCR_VISUAL_REPAIR_MIN_UNDERLINE_PX", "36")',
            'OCR_VISUAL_REPAIR_MIN_UNDERLINE_WIDTH_RATIO',
            '"0.12"',
            'os.getenv("OCR_VISUAL_REPAIR_MAX_UNDERLINE_HEIGHT", "8")',
            'os.getenv("OCR_VISUAL_REPAIR_APPLY_PIX2TEXT", "true")',
        ):
            self.assertIn(expected, visual_source)

    def test_invalid_concurrency_is_clamped_without_changing_contract(self):
        with mock.patch.dict(os.environ, {
            "LLM_MAX_CONCURRENCY": "999",
            "LLM_STANDARDIZE_MAX_ATTEMPTS": "invalid",
            "OCR_AUTO_STANDARDIZE_MAX_CONCURRENCY": "999",
        }, clear=True):
            options = llm_runtime_options()
            self.assertEqual(8, options["maxConcurrency"])
            self.assertEqual(2, options["standardizeMaxAttempts"])
            self.assertEqual(8, ocr_auto_standardize_max_workers())
