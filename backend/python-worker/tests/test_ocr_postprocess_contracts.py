import json

import pytest

from app.ocr import (
    CanonicalOcrBundle as PublicCanonicalOcrBundle,
    OcrPostProcessingPipeline,
)
from app.ocr.contracts import (
    CanonicalOcrBundle,
    CanonicalOcrBundleError,
    OcrAsset,
    OcrLayoutBlock,
    OcrPage,
    SourceDocumentRef,
)


def test_ocr_package_exposes_stable_postprocess_entrypoints() -> None:
    assert PublicCanonicalOcrBundle is CanonicalOcrBundle
    assert callable(OcrPostProcessingPipeline.run_bundle)


def test_minimum_bundle_requires_artifact_root() -> None:
    with pytest.raises(CanonicalOcrBundleError, match="artifactRoot is required"):
        CanonicalOcrBundle(
            document_id="job-minimum",
            input_sha256="input-sha",
            canonical_markdown="1. 最小题目",
        )


def test_minimum_l0_bundle_accepts_exact_required_evidence(tmp_path) -> None:
    bundle = CanonicalOcrBundle.from_dict(
        {
            "schemaVersion": "canonical-ocr-bundle.v1",
            "documentId": "job-minimum",
            "inputSha256": "input-sha",
            "canonicalMarkdown": "1. 最小题目",
            "artifactRoot": str(tmp_path),
        }
    )

    assert bundle.capability_level == "L0"
    assert bundle.assets == ()
    assert bundle.pages == ()
    assert bundle.layout_blocks == ()


def test_l2_bundle_serializes_layout_assets_and_source_reference(tmp_path) -> None:
    artifact_root = tmp_path / "artifacts"
    (artifact_root / "images").mkdir(parents=True)
    (artifact_root / "images" / "figure.png").write_bytes(b"figure")
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"pdf")
    bundle = CanonicalOcrBundle(
        document_id="job-1",
        input_sha256="input-sha",
        canonical_markdown="1. 如图 ![](images/figure.png)",
        assets=(
            OcrAsset(
                asset_id="asset-figure",
                name="figure.png",
                path="images/figure.png",
                url="/api/ocr/jobs/job-1/files/images/figure.png",
                size_bytes=12,
                media_type="image/png",
            ),
        ),
        pages=(OcrPage(page_index=0, width=1000, height=1400),),
        layout_blocks=(
            OcrLayoutBlock(
                block_id="layout-1",
                block_type="image",
                page_index=0,
                bbox=(10, 20, 90, 120),
                page_width=1000,
                page_height=1400,
                order=1,
                image_ref="images/figure.png",
            ),
        ),
        source_document_ref=SourceDocumentRef(path=str(source_path)),
        artifact_root=str(artifact_root),
        producer={"name": "mineru", "version": "2"},
        capabilities=frozenset({"markdown", "embedded-images", "layout-bbox", "source-page"}),
    )

    payload = bundle.to_dict()
    restored = CanonicalOcrBundle.from_dict(payload)

    assert payload["schemaVersion"] == "canonical-ocr-bundle.v1"
    assert payload["assets"][0]["assetId"] == "asset-figure"
    assert payload["layoutBlocks"][0]["pageWidth"] == 1000
    assert payload["sourceDocumentRef"]["path"] == str(source_path)
    assert bundle.capability_level == "L2"
    assert restored == bundle


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"canonical_markdown": ""}, "canonicalMarkdown is required"),
        ({"canonical_markdown": "1. ![](images/missing.png)"}, "markdown image reference has no asset"),
    ],
)
def test_bundle_rejects_missing_required_markdown_evidence(
    tmp_path, kwargs: dict[str, str], message: str
) -> None:
    defaults = {
        "document_id": "job-1",
        "input_sha256": "input-sha",
        "canonical_markdown": "1. 正文",
        "assets": (),
        "pages": (),
        "layout_blocks": (),
        "artifact_root": str(tmp_path),
    }

    with pytest.raises(CanonicalOcrBundleError, match=message):
        CanonicalOcrBundle(**{**defaults, **kwargs})


def test_bundle_accepts_image_path_relative_to_markdown_artifact(tmp_path) -> None:
    (tmp_path / "auto" / "images").mkdir(parents=True)
    (tmp_path / "auto" / "paper.md").write_text("1. 如图 ![](images/figure.png)", encoding="utf-8")
    (tmp_path / "auto" / "images" / "figure.png").write_bytes(b"png")
    bundle = CanonicalOcrBundle(
        document_id="job-relative-image",
        input_sha256="input-sha",
        canonical_markdown="1. 如图 ![](images/figure.png)",
        artifact_root=str(tmp_path),
        markdown_artifact_path="auto/paper.md",
        assets=(
            OcrAsset(
                asset_id="image-1",
                name="figure.png",
                path="auto/images/figure.png",
                url="/files/figure.png",
                size_bytes=3,
                media_type="image/png",
            ),
        ),
    )

    assert bundle.assets[0].path == "auto/images/figure.png"


def test_bundle_rejects_invalid_layout_bbox() -> None:
    with pytest.raises(CanonicalOcrBundleError, match="bbox must be ordered"):
        OcrLayoutBlock(
            block_id="layout-1",
            block_type="text",
            page_index=0,
            bbox=(20, 10, 10, 30),
            page_width=100,
            page_height=100,
            order=0,
        )


def test_persisted_manifest_avoids_duplicate_markdown_and_json(tmp_path) -> None:
    (tmp_path / "paper.md").write_text("1. 外部题目", encoding="utf-8")
    (tmp_path / "paper.json").write_text(json.dumps({"pages": [1]}), encoding="utf-8")
    bundle = CanonicalOcrBundle(
        document_id="job-1",
        input_sha256="input-sha",
        canonical_markdown="1. 外部题目",
        artifact_root=str(tmp_path),
        markdown_artifact_path="paper.md",
        json_artifact_path="paper.json",
        json_content={"pages": [1]},
    )

    manifest = bundle.to_persisted_manifest()
    restored = CanonicalOcrBundle.from_persisted_manifest(manifest)

    assert "canonicalMarkdown" not in manifest
    assert "json" not in manifest
    assert restored == bundle
