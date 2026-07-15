import copy
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw

from app import ocr_processing, question_markdown
from app.ocr.contracts import (
    CanonicalOcrBundle,
    CanonicalOcrBundleError,
    OcrAsset,
    OcrLayoutBlock,
    OcrPage,
    SourceDocumentRef,
)
from app.ocr.mineru_adapter import MineruOcrBundleAdapter
from app.ocr.postprocess_pipeline import OcrPostProcessingPipeline


def _write_fill_blank_source(path: Path) -> None:
    image = Image.new("RGB", (320, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 20), "1. complete ____", fill="black")
    draw.line((80, 80, 250, 80), fill="black", width=2)
    image.save(path)


def _scratch_job_dir(postprocess_root: Path, document_id: str) -> Path:
    digest = hashlib.sha256(document_id.encode("utf-8")).hexdigest()
    return postprocess_root / f"job-{digest}"


def _canonical_visual_bundle(document_id: str, artifact_root: Path, source: Path) -> CanonicalOcrBundle:
    return CanonicalOcrBundle(
        document_id=document_id,
        input_sha256="sha",
        canonical_markdown="# 填空题\n\n1. complete ____",
        pages=(OcrPage(0, 320, 180),),
        layout_blocks=(
            OcrLayoutBlock("question-1", "text", 0, (0, 0, 300, 150), 320, 180, 0, text="1. complete ____"),
        ),
        source_document_ref=SourceDocumentRef(path=str(source)),
        artifact_root=str(artifact_root),
    )


def _run_bundle_deterministically(
    bundle: CanonicalOcrBundle,
    output_root: Path,
    postprocess_root: Path,
    *,
    visual_enabled: bool = True,
) -> dict:
    job = {"id": bundle.document_id, "jobId": bundle.document_id, "status": "running", "uploadPath": ""}

    def read_job(_job_id: str) -> dict:
        return copy.deepcopy(job)

    with patch.dict(
        os.environ,
        {
            "ENABLE_LLM_SPLIT": "false",
            "OCR_AUTO_SEMANTIC_REPAIR_MODE": "skip",
            "OCR_VISUAL_REPAIR_ENABLED": "true" if visual_enabled else "false",
        },
    ), patch.object(ocr_processing, "OUTPUT_ROOT", output_root), patch.object(
        ocr_processing, "POSTPROCESS_ROOT", postprocess_root, create=True
    ), patch.object(
        question_markdown, "OUTPUT_ROOT", output_root
    ), patch.object(
        ocr_processing, "read_job", side_effect=read_job
    ), patch.object(
        ocr_processing, "write_job"
    ), patch.object(
        ocr_processing,
        "refine_question_boundaries_in_chunks",
        return_value=(None, {"source": "test", "llmCalls": []}),
    ), patch(
        "app.visual_repair.run_secondary_ocr", return_value=(None, None)
    ):
        return OcrPostProcessingPipeline().run_bundle(bundle)


def test_normalize_office_html_tables_preserves_plain_and_unclosed_table_text_exactly() -> None:
    plain = "  plain markdown\n\n\n"
    unclosed = (
        "  before\n"
        "<table><tr><td>1. complete table</td></tr></table>\n"
        "<table><tr><td>2. unclosed table</td></tr>\n\n"
    )

    assert ocr_processing.normalize_office_html_tables(plain) == plain
    assert ocr_processing.normalize_office_html_tables(unclosed) == unclosed


def test_normalize_office_html_tables_preserves_commonmark_fences_and_inline_code() -> None:
    markdown = (
        "````html\n"
        "<table><tr><td>99. backtick code</td></tr></table>\n"
        "```\n"
        "<table><tr><td>98. still fenced after short closer</td></tr></table>\n"
        "`````\n"
        "   ~~~html\n"
        "<table><tr><td>97. tilde code</td></tr></table>\n"
        "   ~~~\n"
        "`<table><tr><td>96. inline code</td></tr></table>`\n"
        "<table><tr><td><p>1. external question</p></td></tr></table>"
    )
    expected = markdown.rsplit("<table", 1)[0] + "1. external question"

    assert ocr_processing.normalize_office_html_tables(markdown) == expected


def test_normalize_office_html_tables_replaces_multiple_tables_without_touching_surroundings() -> None:
    markdown = (
        " \n\nlead\n"
        "<table><tr><td><p>1. first</p></td></tr></table>\n\n\n"
        "middle `code`\n"
        "<TABLE class=\"sheet\"><TR><TH>2. second</TH></TR></TABLE>\n"
        "tail\n\n "
    )
    expected = " \n\nlead\n1. first\n\n\nmiddle `code`\n2. second\ntail\n\n "

    assert ocr_processing.normalize_office_html_tables(markdown) == expected


def test_normalize_office_html_tables_preserves_single_indented_code_line_and_surroundings() -> None:
    markdown = (
        "before\n"
        "    <table><tr><td>99. four-space code</td></tr></table>\n"
        "after\n"
    )

    assert ocr_processing.normalize_office_html_tables(markdown) == markdown


def test_normalize_office_html_tables_preserves_multiline_indented_code_with_blank_line() -> None:
    markdown = (
        "prefix\n"
        "    <table><tr><td>99. first code line</td></tr></table>\n"
        "\n"
        "    <table><tr><td>98. second code line</td></tr></table>\n"
        "suffix\n"
    )

    assert ocr_processing.normalize_office_html_tables(markdown) == markdown


def test_normalize_office_html_tables_preserves_tab_indented_code() -> None:
    markdown = "\t<table><tr><td>99. tab code</td></tr></table>\n"

    assert ocr_processing.normalize_office_html_tables(markdown) == markdown


def test_normalize_office_html_tables_converts_table_after_three_spaces() -> None:
    markdown = "before\n   <table><tr><td><p>1. real question</p></td></tr></table>\nafter"

    assert ocr_processing.normalize_office_html_tables(markdown) == "before\n   1. real question\nafter"


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


@pytest.mark.parametrize("undeclared_kind", ["regular", "symlink"])
def test_explicit_bundle_ignores_undeclared_content_v2_artifact(
    tmp_path: Path,
    undeclared_kind: str,
) -> None:
    job_id = f"side-channel-{undeclared_kind}"
    output_root = tmp_path / "outputs"
    artifact_root = output_root / job_id
    artifact_root.mkdir(parents=True)
    (artifact_root / "figure.png").write_bytes(b"png")
    bundle = CanonicalOcrBundle(
        document_id=job_id,
        input_sha256="sha",
        canonical_markdown="# 选择题\n\n1. 计算 $1+1$。\n\nA. 1\nB. 2",
        artifact_root=str(artifact_root),
        assets=(OcrAsset("asset-1", "figure.png", "figure.png", "", 3, "image/png"),),
    )
    baseline = _run_bundle_deterministically(bundle, output_root, tmp_path / "postprocess", visual_enabled=False)
    provider_native = json.dumps(
        [[
            {"type": "title", "content": {"title_content": [{"type": "text", "content": "选择题"}]}},
            {"type": "title", "content": {"title_content": [{"type": "text", "content": "1. 如图计算 $1+1$。"}]}},
            {"type": "image", "content": {"image_source": {"path": "figure.png"}}},
        ]],
        ensure_ascii=False,
    )
    undeclared = artifact_root / "hostile_content_list_v2.json"
    if undeclared_kind == "regular":
        undeclared.write_text(provider_native, encoding="utf-8")
    else:
        outside = tmp_path / "outside_content_list_v2.json"
        outside.write_text(provider_native, encoding="utf-8")
        undeclared.symlink_to(outside)

    with_undeclared = _run_bundle_deterministically(bundle, output_root, tmp_path / "postprocess", visual_enabled=False)

    assert json.loads(json.dumps(with_undeclared, ensure_ascii=False, sort_keys=True)) == json.loads(
        json.dumps(baseline, ensure_ascii=False, sort_keys=True)
    )


def test_explicit_bundle_visual_context_ignores_undeclared_provider_layout_files(tmp_path: Path) -> None:
    job_id = "visual-side-channel"
    output_root = tmp_path / "outputs"
    artifact_root = output_root / job_id
    artifact_root.mkdir(parents=True)
    source = tmp_path / "paper.png"
    _write_fill_blank_source(source)
    (artifact_root / "hostile_content_list.json").write_text(
        json.dumps([{"type": "text", "text": "1. complete ____", "bbox": [0, 0, 300, 150], "page_idx": 0}]),
        encoding="utf-8",
    )
    (artifact_root / "hostile_middle.json").write_text(
        json.dumps({"pdf_info": [{"page_idx": 0, "page_size": [320, 180]}]}),
        encoding="utf-8",
    )
    bundle = CanonicalOcrBundle(
        document_id=job_id,
        input_sha256="sha",
        canonical_markdown="# 填空题\n\n1. complete ____",
        source_document_ref=SourceDocumentRef(path=str(source)),
        artifact_root=str(artifact_root),
    )

    outputs = _run_bundle_deterministically(bundle, output_root, tmp_path / "postprocess")

    assert outputs["visualRepair"]["cropCount"] == 0
    assert outputs["visualRepair"]["preprocessed"]["visualItemCount"] == 0
    assert outputs["visualRepair"]["preprocessed"]["preloadedPageCount"] == 0
    assert not (artifact_root / "visual_repair").exists()


def test_run_bundle_uses_canonical_visual_context_without_provider_scans(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    bundle = CanonicalOcrBundle(
        document_id="no-provider-scan",
        input_sha256="sha",
        canonical_markdown="1. canonical question",
        artifact_root=str(artifact_root),
    )

    with patch.object(Path, "rglob", side_effect=AssertionError("explicit bundle must not rglob artifactRoot")), patch(
        "app.visual_repair.load_visual_items", side_effect=AssertionError("provider visual items must not load")
    ), patch(
        "app.visual_repair.load_page_sizes", side_effect=AssertionError("provider page sizes must not load")
    ):
        outputs = _run_bundle_deterministically(
            bundle,
            tmp_path / "outputs",
            tmp_path / "postprocess",
            visual_enabled=False,
        )

    assert outputs["markdown"] == "1. canonical question"


def test_run_bundle_normalizes_office_html_table_before_question_boundaries(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    bundle = CanonicalOcrBundle(
        document_id="office-table-question",
        input_sha256="sha",
        canonical_markdown=(
            "<table>\n"
            "  <tr><th><p>1. x + 1 = 2, find x.</p></th></tr>\n"
            "  <tr><td><p>A. 0   B. 1   C. 2   D. 3</p></td></tr>\n"
            "</table>"
        ),
        artifact_root=str(artifact_root),
    )

    outputs = _run_bundle_deterministically(
        bundle,
        tmp_path / "outputs",
        tmp_path / "postprocess",
        visual_enabled=False,
    )

    assert outputs["markdown"] == "1. x + 1 = 2, find x.\nA. 0 B. 1 C. 2 D. 3"
    assert len(outputs["questions"]) == 1
    assert outputs["questions"][0]["number"] == 1


def test_run_bundle_preserves_code_examples_while_normalizing_external_table(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    canonical_markdown = (
        "```html\n"
        "<table><tr><td>99. fenced example</td></tr></table>\n"
        "```\n\n"
        "`<table><tr><td>98. inline example</td></tr></table>`\n\n"
        "<table>\n"
        "  <tr><th><p>1. x + 1 = 2, find x.</p></th></tr>\n"
        "  <tr><td><p>A. 0   B. 1   C. 2   D. 3</p></td></tr>\n"
        "</table>"
    )
    bundle = CanonicalOcrBundle(
        document_id="mixed-code-and-office-table",
        input_sha256="sha",
        canonical_markdown=canonical_markdown,
        artifact_root=str(artifact_root),
    )

    outputs = _run_bundle_deterministically(
        bundle,
        tmp_path / "outputs",
        tmp_path / "postprocess",
        visual_enabled=False,
    )

    assert outputs["markdown"] == (
        "```html\n"
        "<table><tr><td>99. fenced example</td></tr></table>\n"
        "```\n\n"
        "`<table><tr><td>98. inline example</td></tr></table>`\n\n"
        "1. x + 1 = 2, find x.\nA. 0 B. 1 C. 2 D. 3"
    )
    assert len(outputs["questions"]) == 1
    assert outputs["questions"][0]["number"] == 1


def test_run_bundle_preserves_indented_code_while_normalizing_xlsx_table(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    canonical_markdown = (
        "    <table><tr><td>99. four-space code</td></tr></table>\n"
        "\n"
        "\t<table><tr><td>98. tab code</td></tr></table>\n\n"
        "<table>\n"
        "  <tr><th><p>1. x + 1 = 2, find x.</p></th></tr>\n"
        "  <tr><td><p>A. 0   B. 1   C. 2   D. 3</p></td></tr>\n"
        "</table>"
    )
    bundle = CanonicalOcrBundle(
        document_id="indented-code-and-xlsx-table",
        input_sha256="sha",
        canonical_markdown=canonical_markdown,
        artifact_root=str(artifact_root),
    )

    outputs = _run_bundle_deterministically(
        bundle,
        tmp_path / "outputs",
        tmp_path / "postprocess",
        visual_enabled=False,
    )

    assert outputs["markdown"] == (
        "    <table><tr><td>99. four-space code</td></tr></table>\n"
        "\n"
        "\t<table><tr><td>98. tab code</td></tr></table>\n\n"
        "1. x + 1 = 2, find x.\nA. 0 B. 1 C. 2 D. 3"
    )
    assert len(outputs["questions"]) == 1
    assert outputs["questions"][0]["number"] == 1


def test_run_bundle_does_not_create_scratch_when_visual_repair_is_disabled(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    source = tmp_path / "paper.png"
    _write_fill_blank_source(source)
    bundle = _canonical_visual_bundle("disabled-visual-repair", artifact_root, source)
    postprocess_root = tmp_path / "postprocess"

    outputs = _run_bundle_deterministically(
        bundle,
        tmp_path / "outputs",
        postprocess_root,
        visual_enabled=False,
    )

    assert outputs["visualRepair"]["enabled"] is False
    assert not postprocess_root.exists()


def test_run_bundle_does_not_create_scratch_without_visual_candidates(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    bundle = CanonicalOcrBundle(
        document_id="no-visual-candidates",
        input_sha256="sha",
        canonical_markdown="1. canonical question",
        artifact_root=str(artifact_root),
    )
    postprocess_root = tmp_path / "postprocess"

    outputs = _run_bundle_deterministically(bundle, tmp_path / "outputs", postprocess_root)

    assert outputs["visualRepair"]["candidateCount"] == 0
    assert not postprocess_root.exists()


def test_run_bundle_writes_derived_crop_only_to_worker_scratch_with_read_only_artifacts(tmp_path: Path) -> None:
    job_id = "read-only-artifacts"
    output_root = tmp_path / "outputs"
    artifact_root = output_root / job_id
    artifact_root.mkdir(parents=True)
    source = tmp_path / "paper.png"
    _write_fill_blank_source(source)
    bundle = _canonical_visual_bundle(job_id, artifact_root, source)
    postprocess_root = tmp_path / "postprocess"
    artifact_root.chmod(0o555)
    try:
        outputs = _run_bundle_deterministically(bundle, output_root, postprocess_root)
    finally:
        artifact_root.chmod(0o755)

    assert outputs["visualRepair"]["cropCount"] == 1
    crops = list(_scratch_job_dir(postprocess_root, job_id).rglob("*.png"))
    assert len(crops) == 1
    assert not (artifact_root / "visual_repair").exists()


@pytest.mark.parametrize(
    "document_id_kind",
    [
        "posix-traversal",
        "posix-absolute",
        "windows-drive-backslash",
        "windows-drive-forward-slash",
        "windows-parent-backslash",
        "windows-unc",
    ],
)
def test_run_bundle_hashes_untrusted_document_id_before_selecting_scratch_directory(
    tmp_path: Path,
    document_id_kind: str,
) -> None:
    postprocess_root = tmp_path / "postprocess"
    outside = tmp_path / "outside"
    document_ids = {
        "posix-traversal": "../outside-traversal",
        "posix-absolute": str(outside / "absolute-job"),
        "windows-drive-backslash": r"C:\outside\job",
        "windows-drive-forward-slash": "C:/outside/job",
        "windows-parent-backslash": r"..\outside\job",
        "windows-unc": r"\\server\share\job",
    }
    document_id = document_ids[document_id_kind]
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    source = tmp_path / "paper.png"
    _write_fill_blank_source(source)
    bundle = _canonical_visual_bundle(document_id, artifact_root, source)

    outputs = _run_bundle_deterministically(bundle, tmp_path / "outputs", postprocess_root)

    expected_job_dir = _scratch_job_dir(postprocess_root, document_id)
    assert outputs["visualRepair"]["cropCount"] == 1
    assert len(list(expected_job_dir.rglob("*.png"))) == 1
    assert sorted(path.name for path in postprocess_root.iterdir()) == [expected_job_dir.name]
    assert not outside.exists()
    assert not (tmp_path / "outside-traversal").exists()


def test_run_bundle_rejects_preexisting_scratch_job_directory_symlink(tmp_path: Path) -> None:
    document_id = "job-dir-symlink"
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    source = tmp_path / "paper.png"
    _write_fill_blank_source(source)
    bundle = _canonical_visual_bundle(document_id, artifact_root, source)
    postprocess_root = tmp_path / "postprocess"
    postprocess_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    _scratch_job_dir(postprocess_root, document_id).symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        _run_bundle_deterministically(bundle, tmp_path / "outputs", postprocess_root)

    assert list(outside.iterdir()) == []


def test_run_bundle_rejects_preexisting_crop_file_symlink(tmp_path: Path) -> None:
    document_id = "crop-file-symlink"
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    source = tmp_path / "paper.png"
    _write_fill_blank_source(source)
    bundle = _canonical_visual_bundle(document_id, artifact_root, source)
    postprocess_root = tmp_path / "postprocess"
    crop_dir = _scratch_job_dir(postprocess_root, document_id) / "visual_repair"
    crop_dir.mkdir(parents=True)
    outside_file = tmp_path / "outside.png"
    outside_file.write_bytes(b"sentinel")
    (crop_dir / "000_q_1.png").symlink_to(outside_file)

    with pytest.raises(ValueError, match="symlink"):
        _run_bundle_deterministically(bundle, tmp_path / "outputs", postprocess_root)

    assert outside_file.read_bytes() == b"sentinel"


def test_legacy_collect_and_adapter_bundle_have_real_artifact_level_parity(tmp_path: Path) -> None:
    job_id = "parity-job"
    output_root = tmp_path / "outputs"
    artifact_root = output_root / job_id
    artifact_root.mkdir(parents=True)
    markdown = "# 填空题\n\n1. 已知 $x+1=2$，则 $x=____$。\n"
    (artifact_root / "paper.md").write_text(markdown, encoding="utf-8")
    (artifact_root / "paper_content_list.json").write_text(
        json.dumps([{"type": "text", "text": "1. 已知 x+1=2，则 x=____。", "bbox": [0, 0, 300, 150], "page_idx": 0}]),
        encoding="utf-8",
    )
    (artifact_root / "paper_middle.json").write_text(
        json.dumps(
            {
                "pdf_info": [
                    {
                        "page_idx": 0,
                        "page_size": [320, 180],
                        "para_blocks": [
                            {
                                "type": "text",
                                "bbox": [0, 0, 300, 150],
                                "lines": [{"spans": [{"type": "text", "content": "1. 已知 x+1=2，则 x=____。"}]}],
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    source = tmp_path / "paper.png"
    _write_fill_blank_source(source)
    job = {"id": job_id, "jobId": job_id, "status": "running", "uploadPath": str(source)}

    def read_job(_job_id: str) -> dict:
        return copy.deepcopy(job)

    pipeline = OcrPostProcessingPipeline()
    with patch.dict(
        os.environ,
        {"ENABLE_LLM_SPLIT": "false", "OCR_AUTO_SEMANTIC_REPAIR_MODE": "skip"},
    ), patch.object(ocr_processing, "OUTPUT_ROOT", output_root), patch.object(
        ocr_processing, "POSTPROCESS_ROOT", tmp_path / "postprocess", create=True
    ), patch.object(
        question_markdown, "OUTPUT_ROOT", output_root
    ), patch(
        "app.worker_base.OUTPUT_ROOT", output_root
    ), patch.object(ocr_processing, "read_job", side_effect=read_job), patch(
        "app.worker_base.read_job", side_effect=read_job
    ), patch.object(ocr_processing, "write_job"), patch.object(
        ocr_processing, "refine_question_boundaries_in_chunks", return_value=(None, {"source": "test", "llmCalls": []})
    ), patch(
        "app.visual_repair.run_secondary_ocr", return_value=(None, None)
    ), patch.object(
        ocr_processing, "collect_outputs_impl", wraps=ocr_processing.collect_outputs_impl
    ) as collect_outputs:
        legacy_outputs = ocr_processing.collect_outputs_impl(job_id, bundle=None)
        explicit_bundle = MineruOcrBundleAdapter().from_output(job, artifact_root)
        explicit_outputs = pipeline.run_bundle(explicit_bundle)

    normalized_legacy = json.loads(json.dumps(legacy_outputs, ensure_ascii=False, sort_keys=True))
    normalized_explicit = json.loads(json.dumps(explicit_outputs, ensure_ascii=False, sort_keys=True))
    assert normalized_explicit == normalized_legacy
    assert collect_outputs.call_count == 2
    assert collect_outputs.call_args_list[0].kwargs.get("bundle") is None
    assert collect_outputs.call_args_list[1].kwargs.get("bundle") is not None
