from unittest.mock import patch

from app import ocr_processing
from app.ocr.contracts import CanonicalOcrBundle
from app.ocr.postprocess_pipeline import OcrPostProcessingPipeline


def test_collect_outputs_facade_delegates_to_single_pipeline_instance() -> None:
    expected = {"questions": []}

    with patch.object(ocr_processing.DEFAULT_OCR_POSTPROCESSING_PIPELINE, "run", return_value=expected) as run:
        result = ocr_processing.collect_outputs("job-1")

    assert result is expected
    run.assert_called_once_with("job-1")


def test_pipeline_run_adapts_legacy_job_before_running_bundle() -> None:
    bundle = CanonicalOcrBundle(
        document_id="job-2",
        input_sha256="sha",
        canonical_markdown="1. 兼容题目",
    )
    expected = {"questions": [{"id": "q1"}]}

    with patch("app.worker_base.read_job", return_value={}), patch("app.ocr.mineru_adapter.MineruOcrBundleAdapter.from_job", return_value=bundle) as adapter, patch.object(
        OcrPostProcessingPipeline,
        "run_bundle",
        return_value=expected,
    ) as run_bundle:
        result = OcrPostProcessingPipeline().run("job-2")

    assert result is expected
    adapter.assert_called_once_with("job-2")
    run_bundle.assert_called_once_with(bundle)


def test_pipeline_run_reuses_persisted_canonical_bundle_before_legacy_adapter(tmp_path) -> None:
    (tmp_path / "paper.md").write_text("1. 外部题目", encoding="utf-8")
    bundle = CanonicalOcrBundle(
        document_id="external-job",
        input_sha256="sha",
        canonical_markdown="1. 外部题目",
        artifact_root=str(tmp_path),
        markdown_artifact_path="paper.md",
    )
    expected = {"questions": [{"id": "q1"}]}

    with patch("app.worker_base.read_job", return_value={"canonicalOcrBundle": bundle.to_persisted_manifest()}), patch(
        "app.ocr.mineru_adapter.MineruOcrBundleAdapter.from_job"
    ) as adapter, patch.object(OcrPostProcessingPipeline, "run_bundle", return_value=expected) as run_bundle:
        result = OcrPostProcessingPipeline().run("external-job")

    assert result is expected
    adapter.assert_not_called()
    run_bundle.assert_called_once_with(bundle)


def test_pipeline_runs_explicit_canonical_bundle_without_provider_name() -> None:
    bundle = CanonicalOcrBundle(
        document_id="external-ocr-job",
        input_sha256="sha",
        canonical_markdown="1. 外部 OCR 题目",
        artifact_root="/tmp/external-ocr-job",
    )
    expected = {"questions": [{"id": "q_1"}]}

    with patch("app.ocr_processing.collect_outputs_impl", return_value=expected) as implementation:
        result = OcrPostProcessingPipeline().run_bundle(bundle)

    assert result is expected
    implementation.assert_called_once_with("external-ocr-job", bundle=bundle)
