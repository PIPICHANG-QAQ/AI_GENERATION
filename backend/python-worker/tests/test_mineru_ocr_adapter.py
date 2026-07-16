import json
from pathlib import Path

from app.ocr.mineru_adapter import MineruOcrBundleAdapter


def test_adapter_builds_l2_bundle_from_mineru_artifacts(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs" / "job-1"
    image_path = output_dir / "images" / "figure.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"png")
    (output_dir / "paper.md").write_text("1. 如图 ![](images/figure.png)", encoding="utf-8")
    (output_dir / "paper_content_list.json").write_text(
        json.dumps(
            [{"type": "image", "img_path": "images/figure.png", "bbox": [10, 20, 90, 120], "page_idx": 0}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (output_dir / "paper_middle.json").write_text(
        json.dumps(
            {
                "pdf_info": [
                    {
                        "page_idx": 0,
                        "page_size": [1000, 1400],
                        "para_blocks": [
                            {
                                "type": "image",
                                "bbox": [10, 20, 90, 120],
                                "index": 7,
                                "lines": [{"spans": [{"type": "image", "img_path": "images/figure.png"}]}],
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"source paper")

    bundle = MineruOcrBundleAdapter(file_url=lambda job_id, path: f"/files/{job_id}/{path.name}").from_output(
        {"jobId": "job-1", "uploadPath": str(source), "ocrProvider": "mineru"},
        output_dir,
    )

    assert bundle.canonical_markdown == "1. 如图 ![](images/figure.png)"
    assert bundle.capability_level == "L2"
    assert bundle.assets[0].path == "images/figure.png"
    assert bundle.layout_blocks[0].page_width == 1000
    assert bundle.layout_blocks[0].coordinate_source == "middle"
    assert bundle.layout_blocks[0].markdown_start == bundle.canonical_markdown.index("images/figure.png")
    assert bundle.pages[0].height == 1400
    assert bundle.source_document_ref is not None
    assert bundle.source_document_ref.path == str(source)


def test_adapter_recovers_blank_markdown_from_content_list(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs" / "job-blank" / "paper" / "auto"
    output_dir.mkdir(parents=True)
    native_markdown = output_dir / "paper.md"
    native_markdown.write_text("", encoding="utf-8")
    (output_dir / "paper_content_list.json").write_text(
        json.dumps(
            [
                {"type": "header", "text": "1. x + 1 = 2, find x.", "page_idx": 0},
                {"type": "aside_text", "text": "A. 0", "page_idx": 0},
                {"type": "aside_text", "text": "B. 1", "page_idx": 0},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    bundle = MineruOcrBundleAdapter().from_output(
        {"jobId": "job-blank", "ocrProvider": "mineru"},
        tmp_path / "outputs" / "job-blank",
    )
    restored = type(bundle).from_persisted_manifest(bundle.to_persisted_manifest())

    assert bundle.canonical_markdown == "1. x + 1 = 2, find x.\n\nA. 0\n\nB. 1"
    assert bundle.markdown_artifact_path == "paper/auto/paper_canonical.md"
    assert (output_dir / "paper_canonical.md").read_text(encoding="utf-8") == bundle.canonical_markdown
    assert native_markdown.read_text(encoding="utf-8") == ""
    assert restored.canonical_markdown == bundle.canonical_markdown


def test_adapter_prefers_nonblank_native_markdown_over_stale_fallback(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs" / "job-retry" / "paper" / "auto"
    output_dir.mkdir(parents=True)
    (output_dir / "paper.md").write_text("1. fresh native result", encoding="utf-8")
    stale_fallback = output_dir / "paper_canonical.md"
    stale_fallback.write_text("1. stale fallback result that is deliberately longer", encoding="utf-8")

    bundle = MineruOcrBundleAdapter().from_output(
        {"jobId": "job-retry", "ocrProvider": "mineru"},
        tmp_path / "outputs" / "job-retry",
    )

    assert bundle.canonical_markdown == "1. fresh native result"
    assert bundle.markdown_artifact_path == "paper/auto/paper.md"
    assert stale_fallback.read_text(encoding="utf-8") == "1. stale fallback result that is deliberately longer"
