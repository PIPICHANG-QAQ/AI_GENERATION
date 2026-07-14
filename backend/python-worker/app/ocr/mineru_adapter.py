"""Adapter from the current MinerU artifact tree to canonical OCR evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.ocr.contracts import CanonicalOcrBundle, OcrAsset, OcrLayoutBlock, OcrPage, SourceDocumentRef
from app.question_layout import load_question_layout_items


class MineruOcrBundleAdapter:
    """Build a provider-neutral bundle while preserving current MinerU selection rules."""

    def __init__(self, file_url: Callable[[str, Path], str] | None = None) -> None:
        self._file_url = file_url or self._default_file_url

    def from_job(self, job_id: str) -> CanonicalOcrBundle:
        """Read a legacy job and adapt the existing output directory."""
        from app.worker_base import OUTPUT_ROOT, read_job

        return self.from_output(read_job(job_id), OUTPUT_ROOT / job_id)

    def from_output(self, job: dict[str, Any], output_dir: Path) -> CanonicalOcrBundle:
        """Adapt one completed MinerU output directory without changing its files."""
        job_id = str(job.get("jobId") or job.get("id") or "").strip()
        if not job_id:
            raise ValueError("MinerU jobId is required")

        markdown_files = sorted(
            [path for path in output_dir.rglob("*") if path.suffix.lower() in {".md", ".markdown"}],
            key=lambda path: (-path.stat().st_size, path.as_posix()),
        )
        json_files = sorted(output_dir.rglob("*.json"), key=lambda path: (-path.stat().st_size, path.as_posix()))
        image_files = sorted(
            [path for path in output_dir.rglob("*") if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}],
            key=lambda path: path.as_posix(),
        )
        if not markdown_files:
            raise ValueError("MinerU output does not contain Markdown")

        markdown_path = markdown_files[0]
        markdown = markdown_path.read_text(encoding="utf-8", errors="replace")
        json_path = json_files[0] if json_files else None
        json_content = self._read_json(json_path) if json_path else None
        assets = tuple(self._asset(job_id, output_dir, path) for path in image_files)
        layout_blocks = tuple(self._layout_block(item) for item in load_question_layout_items(output_dir))
        pages = tuple(self._pages(layout_blocks))
        source_ref = self._source_ref(job)
        capabilities = {"markdown"}
        if assets:
            capabilities.add("embedded-images")
        if layout_blocks:
            capabilities.update({"layout-bbox", "reading-order"})
        if source_ref:
            capabilities.add("source-page")

        return CanonicalOcrBundle(
            document_id=job_id,
            input_sha256=self._input_sha256(source_ref, markdown),
            canonical_markdown=markdown,
            assets=assets,
            pages=pages,
            layout_blocks=layout_blocks,
            source_document_ref=source_ref,
            artifact_root=str(output_dir.resolve()),
            markdown_artifact_path=markdown_path.relative_to(output_dir).as_posix(),
            json_artifact_path=json_path.relative_to(output_dir).as_posix() if json_path else "",
            producer={
                "name": str(job.get("ocrProvider") or job.get("ocrFlowProvider") or "mineru"),
                "version": str(job.get("ocrProviderVersion") or job.get("mineruVersion") or ""),
            },
            native_artifacts=tuple(
                {"kind": "json", "path": path.relative_to(output_dir).as_posix()} for path in json_files
            ),
            capabilities=frozenset(capabilities),
            json_content=json_content,
        )

    def _asset(self, job_id: str, output_dir: Path, path: Path) -> OcrAsset:
        relative = path.relative_to(output_dir).as_posix()
        asset_id = f"asset-{hashlib.sha1(relative.encode('utf-8')).hexdigest()[:16]}"
        return OcrAsset(
            asset_id=asset_id,
            name=path.name,
            path=relative,
            url=self._file_url(job_id, path),
            size_bytes=path.stat().st_size,
            media_type=self._media_type(path),
        )

    @staticmethod
    def _layout_block(item: dict[str, Any]) -> OcrLayoutBlock:
        seed = json.dumps(
            {
                "pageIndex": item.get("pageIndex"),
                "sourceOrder": item.get("sourceOrder"),
                "type": item.get("type"),
                "text": item.get("text"),
                "imageRef": item.get("imageRef"),
                "bbox": item.get("bbox"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        bbox = tuple(float(value) for value in (item.get("bbox") or []))
        return OcrLayoutBlock(
            block_id=f"layout-{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:12]}",
            block_type=str(item.get("type") or "unknown"),
            page_index=int(item.get("pageIndex") or 0),
            bbox=bbox,  # type: ignore[arg-type]
            page_width=float(item["pageWidth"]) if item.get("pageWidth") is not None else None,
            page_height=float(item["pageHeight"]) if item.get("pageHeight") is not None else None,
            order=int(item.get("order") or 0),
            text=str(item.get("text") or ""),
            image_ref=str(item.get("imageRef") or ""),
            source_order=int(item.get("sourceOrder") or 0),
            coordinate_source=str(item.get("coordinateSource") or ""),
        )

    @staticmethod
    def _pages(blocks: tuple[OcrLayoutBlock, ...]) -> list[OcrPage]:
        pages: dict[int, OcrPage] = {}
        for block in blocks:
            if block.page_width is None or block.page_height is None:
                continue
            pages.setdefault(block.page_index, OcrPage(block.page_index, block.page_width, block.page_height))
        return [pages[index] for index in sorted(pages)]

    @staticmethod
    def _source_ref(job: dict[str, Any]) -> SourceDocumentRef | None:
        path = Path(str(job.get("uploadPath") or ""))
        if path.exists() and path.is_file():
            return SourceDocumentRef(path=str(path.resolve()))
        return None

    @staticmethod
    def _input_sha256(source_ref: SourceDocumentRef | None, markdown: str) -> str:
        if source_ref and source_ref.path:
            try:
                return hashlib.sha256(Path(source_ref.path).read_bytes()).hexdigest()
            except OSError:
                pass
        return hashlib.sha256(markdown.encode("utf-8")).hexdigest()

    @staticmethod
    def _read_json(path: Path) -> Any:
        raw = path.read_text(encoding="utf-8", errors="replace")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    @staticmethod
    def _media_type(path: Path) -> str:
        return {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }.get(path.suffix.lower(), "application/octet-stream")

    @staticmethod
    def _default_file_url(job_id: str, path: Path) -> str:
        from app.question_markdown import relative_file_url

        return relative_file_url(job_id, path)
