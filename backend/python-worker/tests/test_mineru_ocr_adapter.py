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
    assert bundle.pages[0].height == 1400
    assert bundle.source_document_ref is not None
    assert bundle.source_document_ref.path == str(source)
