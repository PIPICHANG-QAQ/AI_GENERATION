from unittest.mock import patch

from app import ocr_processing
from app.ocr.postprocess_pipeline import OcrPostProcessingPipeline


def test_collect_outputs_facade_delegates_to_single_pipeline_instance() -> None:
    expected = {"questions": []}

    with patch.object(ocr_processing.DEFAULT_OCR_POSTPROCESSING_PIPELINE, "run", return_value=expected) as run:
        result = ocr_processing.collect_outputs("job-1")

    assert result is expected
    run.assert_called_once_with("job-1")


def test_pipeline_run_preserves_existing_collect_outputs_implementation() -> None:
    expected = {"questions": [{"id": "q1"}]}

    with patch("app.ocr_processing.collect_outputs_impl", return_value=expected) as implementation:
        result = OcrPostProcessingPipeline().run("job-2")

    assert result is expected
    implementation.assert_called_once_with("job-2")
