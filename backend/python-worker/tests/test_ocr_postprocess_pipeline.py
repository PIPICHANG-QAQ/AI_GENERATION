import copy
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app import ocr_processing, question_markdown
from app.ocr.contracts import CanonicalOcrBundle, CanonicalOcrBundleError, OcrAsset, SourceDocumentRef
from app.ocr.mineru_adapter import MineruOcrBundleAdapter
from app.ocr.postprocess_pipeline import OcrPostProcessingPipeline


def test_collect_outputs_facade_delegates_to_single_pipeline_instance() -> None:
    expected = {"questions": []}

    with patch.object(ocr_processing.DEFAULT_OCR_POSTPROCESSING_PIPELINE, "run", return_value=expected) as run:
        result = ocr_processing.collect_outputs("job-1")

    assert result is expected
    run.assert_called_once_with("job-1")


def test_pipeline_run_adapts_legacy_job_before_running_bundle(tmp_path: Path) -> None:
    bundle = CanonicalOcrBundle(
        document_id="job-2",
        input_sha256="sha",
        canonical_markdown="1. 兼容题目",
        artifact_root=str(tmp_path),
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


def test_pipeline_runs_explicit_canonical_bundle_without_provider_name(tmp_path: Path) -> None:
    bundle = CanonicalOcrBundle(
        document_id="external-ocr-job",
        input_sha256="sha",
        canonical_markdown="1. 外部 OCR 题目",
        artifact_root=str(tmp_path),
    )
    expected = {"questions": [{"id": "q_1"}]}

    with patch("app.ocr_processing.collect_outputs_impl", return_value=expected) as implementation:
        result = OcrPostProcessingPipeline().run_bundle(bundle)

    assert result is expected
    implementation.assert_called_once_with("external-ocr-job", bundle=bundle)


def test_run_bundle_rejects_asset_path_traversal_before_collecting(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "outside.png").write_bytes(b"png")
    bundle = CanonicalOcrBundle(
        document_id="asset-traversal",
        input_sha256="sha",
        canonical_markdown="1. 题目",
        artifact_root=str(root),
        assets=(OcrAsset("asset-1", "outside.png", "../outside.png", "", 3, "image/png"),),
    )

    with patch("app.ocr_processing.collect_outputs_impl") as implementation:
        with pytest.raises(CanonicalOcrBundleError, match="relative path inside artifactRoot"):
            OcrPostProcessingPipeline().run_bundle(bundle)

    implementation.assert_not_called()


def test_run_bundle_rejects_native_artifact_path_traversal_before_collecting(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "outside.json").write_text("{}", encoding="utf-8")
    bundle = CanonicalOcrBundle(
        document_id="native-traversal",
        input_sha256="sha",
        canonical_markdown="1. 题目",
        artifact_root=str(root),
        native_artifacts=({"kind": "json", "path": "../outside.json"},),
    )

    with patch("app.ocr_processing.collect_outputs_impl") as implementation:
        with pytest.raises(CanonicalOcrBundleError, match="relative path inside artifactRoot"):
            OcrPostProcessingPipeline().run_bundle(bundle)

    implementation.assert_not_called()


def test_run_bundle_rejects_absolute_asset_path_even_inside_root(tmp_path: Path) -> None:
    asset_path = tmp_path / "figure.png"
    asset_path.write_bytes(b"png")
    bundle = CanonicalOcrBundle(
        document_id="absolute-asset",
        input_sha256="sha",
        canonical_markdown="1. 题目",
        artifact_root=str(tmp_path),
        assets=(OcrAsset("asset-1", "figure.png", str(asset_path), "", 3, "image/png"),),
    )

    with patch("app.ocr_processing.collect_outputs_impl") as implementation:
        with pytest.raises(CanonicalOcrBundleError, match="relative path inside artifactRoot"):
            OcrPostProcessingPipeline().run_bundle(bundle)

    implementation.assert_not_called()


def test_run_bundle_rejects_windows_absolute_asset_path(tmp_path: Path) -> None:
    bundle = CanonicalOcrBundle(
        document_id="windows-absolute-asset",
        input_sha256="sha",
        canonical_markdown="1. 题目",
        artifact_root=str(tmp_path),
        assets=(OcrAsset("asset-1", "figure.png", "C:\\outside\\figure.png", "", 3, "image/png"),),
    )

    with patch("app.ocr_processing.collect_outputs_impl") as implementation:
        with pytest.raises(CanonicalOcrBundleError, match="relative path inside artifactRoot"):
            OcrPostProcessingPipeline().run_bundle(bundle)

    implementation.assert_not_called()


def test_run_bundle_rejects_artifact_root_that_is_not_a_directory(tmp_path: Path) -> None:
    root_file = tmp_path / "artifact-root"
    root_file.write_text("not a directory", encoding="utf-8")
    bundle = CanonicalOcrBundle(
        document_id="invalid-root",
        input_sha256="sha",
        canonical_markdown="1. 题目",
        artifact_root=str(root_file),
    )

    with patch("app.ocr_processing.collect_outputs_impl") as implementation:
        with pytest.raises(CanonicalOcrBundleError, match="artifactRoot is not an existing directory"):
            OcrPostProcessingPipeline().run_bundle(bundle)

    implementation.assert_not_called()


@pytest.mark.parametrize("declared_kind", ["markdown", "json", "asset", "native"])
def test_run_bundle_rejects_missing_declared_files(tmp_path: Path, declared_kind: str) -> None:
    kwargs: dict[str, object] = {}
    if declared_kind == "markdown":
        kwargs["markdown_artifact_path"] = "missing.md"
    elif declared_kind == "json":
        kwargs["json_artifact_path"] = "missing.json"
    elif declared_kind == "asset":
        kwargs["assets"] = (OcrAsset("asset-1", "missing.png", "missing.png", "", 3, "image/png"),)
    else:
        kwargs["native_artifacts"] = ({"kind": "json", "path": "missing-native.json"},)
    bundle = CanonicalOcrBundle(
        document_id=f"missing-{declared_kind}",
        input_sha256="sha",
        canonical_markdown="1. 题目",
        artifact_root=str(tmp_path),
        **kwargs,
    )

    with patch("app.ocr_processing.collect_outputs_impl") as implementation:
        with pytest.raises(CanonicalOcrBundleError, match="declared artifact is unavailable"):
            OcrPostProcessingPipeline().run_bundle(bundle)

    implementation.assert_not_called()


def test_run_bundle_accepts_contained_files_and_exempts_source_document_path(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "paper.md").write_text("1. 如图 ![](figure.png)", encoding="utf-8")
    (root / "paper.json").write_text("{}", encoding="utf-8")
    (root / "figure.png").write_bytes(b"png")
    (root / "native.json").write_text("{}", encoding="utf-8")
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    bundle = CanonicalOcrBundle(
        document_id="contained-files",
        input_sha256="sha",
        canonical_markdown="1. 如图 ![](figure.png)",
        artifact_root=str(root),
        markdown_artifact_path="paper.md",
        json_artifact_path="paper.json",
        assets=(OcrAsset("asset-1", "figure.png", "figure.png", "", 3, "image/png"),),
        native_artifacts=({"kind": "json", "path": "native.json"},),
        source_document_ref=SourceDocumentRef(path=str(source)),
    )
    expected = {"questions": []}

    with patch("app.ocr_processing.collect_outputs_impl", return_value=expected) as implementation:
        result = OcrPostProcessingPipeline().run_bundle(bundle)

    assert result is expected
    implementation.assert_called_once_with("contained-files", bundle=bundle)


def test_legacy_run_and_explicit_bundle_have_real_artifact_level_parity(tmp_path: Path) -> None:
    job_id = "parity-job"
    output_root = tmp_path / "outputs"
    artifact_root = output_root / job_id
    artifact_root.mkdir(parents=True)
    markdown = "# 选择题\n\n1. 已知 $x+1=2$，求 $x$。\n\nA. 0\nB. 1\nC. 2\nD. 3\n"
    (artifact_root / "paper.md").write_text(markdown, encoding="utf-8")
    (artifact_root / "paper.json").write_text(json.dumps({"pages": []}), encoding="utf-8")
    job = {"id": job_id, "jobId": job_id, "status": "running", "uploadPath": ""}

    def read_job(_job_id: str) -> dict:
        return copy.deepcopy(job)

    visual_repair = {
        "enabled": False,
        "skippedReason": "deterministic parity fixture",
        "cropCount": 0,
        "underlineCount": 0,
        "maxConcurrency": 1,
        "preprocessed": {"preloadedPageCount": 0},
    }
    pipeline = OcrPostProcessingPipeline()
    with patch.dict(
        os.environ,
        {"ENABLE_LLM_SPLIT": "false", "OCR_AUTO_SEMANTIC_REPAIR_MODE": "skip"},
    ), patch.object(ocr_processing, "OUTPUT_ROOT", output_root), patch.object(
        question_markdown, "OUTPUT_ROOT", output_root
    ), patch(
        "app.worker_base.OUTPUT_ROOT", output_root
    ), patch.object(ocr_processing, "read_job", side_effect=read_job), patch(
        "app.worker_base.read_job", side_effect=read_job
    ), patch.object(ocr_processing, "write_job"), patch.object(
        ocr_processing, "prepare_visual_repair_context", return_value={}
    ), patch.object(
        ocr_processing, "apply_visual_repairs", return_value=visual_repair
    ), patch.object(
        ocr_processing, "refine_question_boundaries_in_chunks", return_value=(None, {"source": "test", "llmCalls": []})
    ), patch.object(
        ocr_processing, "collect_outputs_impl", wraps=ocr_processing.collect_outputs_impl
    ) as collect_outputs:
        legacy_outputs = pipeline.run(job_id)
        explicit_bundle = MineruOcrBundleAdapter().from_output(job, artifact_root)
        explicit_outputs = pipeline.run_bundle(explicit_bundle)

    normalized_legacy = json.loads(json.dumps(legacy_outputs, ensure_ascii=False, sort_keys=True))
    normalized_explicit = json.loads(json.dumps(explicit_outputs, ensure_ascii=False, sort_keys=True))
    assert normalized_explicit == normalized_legacy
    assert collect_outputs.call_count == 2
    assert all(call.kwargs.get("bundle") is not None for call in collect_outputs.call_args_list)
