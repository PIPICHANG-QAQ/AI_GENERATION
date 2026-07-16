import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.ocr.contracts import CanonicalOcrBundleError
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

    expected_markdown = "1. x + 1 = 2, find x.\n\nA. 0\n\nB. 1"
    expected_digest = hashlib.sha256(expected_markdown.encode("utf-8")).hexdigest()
    expected_path = output_dir / f"paper_canonical_{expected_digest}.md"
    assert bundle.canonical_markdown == expected_markdown
    assert bundle.markdown_artifact_path == f"paper/auto/{expected_path.name}"
    assert expected_path.read_text(encoding="utf-8") == bundle.canonical_markdown
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


def test_adapter_recovers_structured_content_list_items(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs" / "job-structured" / "paper" / "auto"
    output_dir.mkdir(parents=True)
    (output_dir / "paper.md").write_text("", encoding="utf-8")
    (output_dir / "paper_content_list.json").write_text(
        json.dumps(
            [
                {"type": "list", "list_items": ["1. choose an answer", "A. zero", "B. one"]},
                {
                    "type": "table",
                    "table_caption": ["Values"],
                    "table_body": "<table><tr><td>1</td></tr></table>",
                    "table_footnote": ["Source note"],
                },
                {"type": "code", "code_caption": ["Algorithm"], "code_body": "answer = 1"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    bundle = MineruOcrBundleAdapter().from_output(
        {"jobId": "job-structured", "ocrProvider": "mineru"},
        tmp_path / "outputs" / "job-structured",
    )

    assert "- 1. choose an answer" in bundle.canonical_markdown
    assert "<table><tr><td>1</td></tr></table>" in bundle.canonical_markdown
    assert "Source note" in bundle.canonical_markdown
    assert "```\nanswer = 1\n```" in bundle.canonical_markdown


def test_adapter_does_not_read_content_list_from_another_output_directory(tmp_path: Path) -> None:
    output_root = tmp_path / "outputs" / "job-isolation"
    selected_dir = output_root / "selected" / "auto"
    selected_dir.mkdir(parents=True)
    (selected_dir / "paper.md").write_text("", encoding="utf-8")
    (selected_dir / "other_content_list.json").write_text(
        json.dumps([{"type": "text", "text": "1. same directory, different document"}]),
        encoding="utf-8",
    )
    other_dir = output_root / "other" / "auto"
    other_dir.mkdir(parents=True)
    (other_dir / "other_content_list.json").write_text(
        json.dumps([{"type": "text", "text": "1. belongs to another document"}]),
        encoding="utf-8",
    )

    with pytest.raises(CanonicalOcrBundleError, match="canonicalMarkdown is required"):
        MineruOcrBundleAdapter().from_output(
            {"jobId": "job-isolation", "ocrProvider": "mineru"},
            output_root,
        )

    assert not (selected_dir / "paper_canonical.md").exists()


def test_adapter_replaces_canonical_symlink_without_writing_outside_root(tmp_path: Path) -> None:
    output_root = tmp_path / "outputs" / "job-symlink"
    output_dir = output_root / "paper" / "auto"
    output_dir.mkdir(parents=True)
    (output_dir / "paper.md").write_text("", encoding="utf-8")
    (output_dir / "paper_content_list.json").write_text(
        json.dumps([{"type": "text", "text": "1. safe recovered text"}]),
        encoding="utf-8",
    )
    recovered_markdown = "1. safe recovered text"
    digest = hashlib.sha256(recovered_markdown.encode("utf-8")).hexdigest()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside sentinel", encoding="utf-8")
    canonical_path = output_dir / f"paper_canonical_{digest}.md"
    canonical_path.symlink_to(outside)

    bundle = MineruOcrBundleAdapter().from_output(
        {"jobId": "job-symlink", "ocrProvider": "mineru"},
        output_root,
    )

    assert outside.read_text(encoding="utf-8") == "outside sentinel"
    assert not canonical_path.is_symlink()
    assert canonical_path.read_text(encoding="utf-8") == recovered_markdown
    assert bundle.canonical_markdown == recovered_markdown


def test_adapter_materializes_fallback_atomically_for_concurrent_calls(tmp_path: Path) -> None:
    output_root = tmp_path / "outputs" / "job-concurrent"
    output_dir = output_root / "paper" / "auto"
    output_dir.mkdir(parents=True)
    (output_dir / "paper.md").write_text("", encoding="utf-8")
    (output_dir / "paper_content_list.json").write_text(
        json.dumps([{"type": "text", "text": "1. concurrent recovered text"}]),
        encoding="utf-8",
    )

    def adapt() -> str:
        bundle = MineruOcrBundleAdapter().from_output(
            {"jobId": "job-concurrent", "ocrProvider": "mineru"},
            output_root,
        )
        return bundle.canonical_markdown

    with ThreadPoolExecutor(max_workers=8) as executor:
        markdown_results = list(executor.map(lambda _index: adapt(), range(16)))

    recovered_markdown = "1. concurrent recovered text"
    digest = hashlib.sha256(recovered_markdown.encode("utf-8")).hexdigest()
    canonical_path = output_dir / f"paper_canonical_{digest}.md"
    assert markdown_results == [recovered_markdown] * 16
    assert canonical_path.read_text(encoding="utf-8") == recovered_markdown
    assert list(output_dir.glob(f".{canonical_path.name}.*.tmp")) == []


def test_adapter_rejects_content_list_symlink_to_another_document(tmp_path: Path) -> None:
    output_root = tmp_path / "outputs" / "job-source-symlink"
    selected_dir = output_root / "selected" / "auto"
    selected_dir.mkdir(parents=True)
    (selected_dir / "paper.md").write_text("", encoding="utf-8")
    other_dir = output_root / "other" / "auto"
    other_dir.mkdir(parents=True)
    foreign_content_list = other_dir / "paper_content_list.json"
    foreign_content_list.write_text(
        json.dumps([{"type": "text", "text": "1. foreign document"}]),
        encoding="utf-8",
    )
    (selected_dir / "paper_content_list.json").symlink_to(foreign_content_list)

    with pytest.raises(ValueError, match="symbolic link"):
        MineruOcrBundleAdapter().from_output(
            {"jobId": "job-source-symlink", "ocrProvider": "mineru"},
            output_root,
        )


def test_adapter_persists_each_fallback_version_at_an_immutable_path(tmp_path: Path) -> None:
    output_root = tmp_path / "outputs" / "job-versioned"
    output_dir = output_root / "paper" / "auto"
    output_dir.mkdir(parents=True)
    (output_dir / "paper.md").write_text("", encoding="utf-8")
    content_list_path = output_dir / "paper_content_list.json"

    content_list_path.write_text(
        json.dumps([{"type": "text", "text": "VERSION A"}]),
        encoding="utf-8",
    )
    bundle_a = MineruOcrBundleAdapter().from_output(
        {"jobId": "job-versioned", "ocrProvider": "mineru"},
        output_root,
    )
    manifest_a = bundle_a.to_persisted_manifest()

    content_list_path.write_text(
        json.dumps([{"type": "text", "text": "VERSION B"}]),
        encoding="utf-8",
    )
    bundle_b = MineruOcrBundleAdapter().from_output(
        {"jobId": "job-versioned", "ocrProvider": "mineru"},
        output_root,
    )
    manifest_b = bundle_b.to_persisted_manifest()

    restored_a = type(bundle_a).from_persisted_manifest(manifest_a)
    restored_b = type(bundle_b).from_persisted_manifest(manifest_b)

    assert restored_a.canonical_markdown == "VERSION A"
    assert restored_b.canonical_markdown == "VERSION B"
    assert bundle_a.markdown_artifact_path != bundle_b.markdown_artifact_path


def test_adapter_skips_larger_whitespace_only_native_markdown(tmp_path: Path) -> None:
    output_root = tmp_path / "outputs" / "job-whitespace"
    output_root.mkdir(parents=True)
    (output_root / "paper.md").write_text("1. valid question", encoding="utf-8")
    (output_root / "noise.md").write_text(" " * 100, encoding="utf-8")

    bundle = MineruOcrBundleAdapter().from_output(
        {"jobId": "job-whitespace", "ocrProvider": "mineru"},
        output_root,
    )

    assert bundle.canonical_markdown == "1. valid question"
    assert bundle.markdown_artifact_path == "paper.md"
