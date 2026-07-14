import json

import pytest

from app.ocr.contracts import (
    CanonicalOcrBundle,
    CanonicalOcrBundleError,
    OcrAsset,
    OcrLayoutBlock,
    OcrPage,
    SourceDocumentRef,
)


def test_l2_bundle_serializes_layout_assets_and_source_reference() -> None:
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
        source_document_ref=SourceDocumentRef(path="/tmp/source.pdf"),
        artifact_root="/tmp/outputs/job-1",
        producer={"name": "mineru", "version": "2"},
        capabilities=frozenset({"markdown", "embedded-images", "layout-bbox", "source-page"}),
    )

    payload = bundle.to_dict()
    restored = CanonicalOcrBundle.from_dict(payload)

    assert payload["schemaVersion"] == "canonical-ocr-bundle.v1"
    assert payload["assets"][0]["assetId"] == "asset-figure"
    assert payload["layoutBlocks"][0]["pageWidth"] == 1000
    assert payload["sourceDocumentRef"]["path"] == "/tmp/source.pdf"
    assert bundle.capability_level == "L2"
    assert restored == bundle


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"canonical_markdown": ""}, "canonicalMarkdown is required"),
        ({"canonical_markdown": "1. ![](images/missing.png)"}, "markdown image reference has no asset"),
    ],
)
def test_bundle_rejects_missing_required_markdown_evidence(kwargs: dict[str, str], message: str) -> None:
    defaults = {
        "document_id": "job-1",
        "input_sha256": "input-sha",
        "canonical_markdown": "1. 正文",
        "assets": (),
        "pages": (),
        "layout_blocks": (),
    }

    with pytest.raises(CanonicalOcrBundleError, match=message):
        CanonicalOcrBundle(**{**defaults, **kwargs})


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
