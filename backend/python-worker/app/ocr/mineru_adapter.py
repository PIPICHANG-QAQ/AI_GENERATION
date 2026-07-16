"""Adapter from the current MinerU artifact tree to canonical OCR evidence."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.ocr.contracts import CanonicalOcrBundle, OcrAsset, OcrLayoutBlock, OcrPage, SourceDocumentRef
from app.question_layout import index_layout_items, load_question_layout_items


class MineruOcrBundleAdapter:
    """Build a provider-neutral bundle while preserving current MinerU selection rules."""

    def __init__(self, file_url: Callable[[str, Path], str] | None = None) -> None:
        self._file_url = file_url or self._default_file_url

    def from_job(self, job_id: str) -> CanonicalOcrBundle:
        """Read a legacy job and adapt the existing output directory."""
        from app.worker_base import OUTPUT_ROOT, read_job

        return self.from_output(read_job(job_id), OUTPUT_ROOT / job_id)

    def from_output(self, job: dict[str, Any], output_dir: Path) -> CanonicalOcrBundle:
        """Adapt one completed MinerU output directory to canonical evidence."""
        job_id = str(job.get("jobId") or job.get("id") or "").strip()
        if not job_id:
            raise ValueError("MinerU jobId is required")
        output_root = output_dir.resolve(strict=True)

        markdown_candidates = [
            path for path in output_root.rglob("*") if path.suffix.lower() in {".md", ".markdown"}
        ]
        native_markdown_files = [path for path in markdown_candidates if not self._is_generated_canonical(path)]
        generated_markdown_files = [path for path in markdown_candidates if self._is_generated_canonical(path)]
        for path in native_markdown_files:
            if path.is_symlink():
                raise ValueError(f"MinerU Markdown must not be a symbolic link: {path}")
        native_markdown_files = sorted(
            native_markdown_files,
            key=lambda path: (-self._artifact_size(path, output_root, "MinerU Markdown"), path.as_posix()),
        )
        generated_markdown_files = sorted(generated_markdown_files, key=lambda path: path.as_posix())
        markdown_files = native_markdown_files + generated_markdown_files
        json_candidates = [
            path for path in output_root.rglob("*.json") if not self._is_generated_canonical_json(path)
        ]
        json_files = sorted(
            json_candidates,
            key=lambda path: (-self._artifact_size(path, output_root, "MinerU JSON"), path.as_posix()),
        )
        image_files = sorted(
            [path for path in output_root.rglob("*") if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}],
            key=lambda path: path.as_posix(),
        )
        if not markdown_files:
            raise ValueError("MinerU output does not contain Markdown")

        markdown_path = (native_markdown_files or generated_markdown_files)[0]
        markdown = ""
        for candidate in native_markdown_files:
            candidate, candidate_markdown = self._read_markdown(candidate, output_root)
            if candidate_markdown.strip():
                markdown_path = candidate
                markdown = candidate_markdown
                break
        if not markdown and native_markdown_files:
            markdown_path, markdown = self._materialize_content_list_markdown(native_markdown_files[0], output_root)
        if not markdown and native_markdown_files:
            for candidate in self._legacy_fallbacks_for(markdown_path, generated_markdown_files):
                candidate, candidate_markdown = self._read_markdown(candidate, output_root)
                if candidate_markdown.strip():
                    markdown_path = candidate
                    markdown = candidate_markdown
                    break
        json_path, json_content = self._materialize_json_snapshot(json_files[0], output_root) if json_files else (None, None)
        assets = tuple(self._asset(job_id, output_root, path) for path in image_files)
        layout_items = index_layout_items(load_question_layout_items(output_root), markdown)
        layout_blocks = tuple(self._layout_block(item) for item in layout_items)
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
            artifact_root=str(output_root),
            markdown_artifact_path=markdown_path.relative_to(output_root).as_posix(),
            json_artifact_path=json_path.relative_to(output_root).as_posix() if json_path else "",
            producer={
                "name": str(job.get("ocrProvider") or job.get("ocrFlowProvider") or "mineru"),
                "version": str(job.get("ocrProviderVersion") or job.get("mineruVersion") or ""),
            },
            native_artifacts=tuple(
                {"kind": "json", "path": path.relative_to(output_root).as_posix()} for path in json_files
            ),
            capabilities=frozenset(capabilities),
            json_content=json_content,
        )

    @classmethod
    def _materialize_content_list_markdown(cls, markdown_path: Path, output_dir: Path) -> tuple[Path, str]:
        content_list_path = markdown_path.with_name(f"{markdown_path.stem}_content_list.json")
        if not content_list_path.exists():
            return markdown_path, ""
        if content_list_path.is_symlink():
            raise ValueError(f"MinerU content list must not be a symbolic link: {content_list_path}")
        fragments: list[str] = []
        payload = cls._read_json(content_list_path, output_dir)
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                fragment = cls._content_item_markdown(item, image_prefix="../")
                if fragment:
                    fragments.append(fragment)

        canonical_markdown = "\n\n".join(fragments).strip()
        if not canonical_markdown:
            return markdown_path, ""
        digest = hashlib.sha256(canonical_markdown.encode("utf-8")).hexdigest()
        canonical_dir = markdown_path.parent / ".canonical"
        if canonical_dir.is_symlink():
            raise ValueError(f"Canonical Markdown directory must not be a symbolic link: {canonical_dir}")
        cls._ensure_directory(canonical_dir, output_dir, "Canonical Markdown directory")
        canonical_path = canonical_dir / f"{digest}.md"
        cls._atomic_write_text(canonical_path, canonical_markdown, output_dir)
        return canonical_path, canonical_markdown

    @classmethod
    def _is_generated_canonical(cls, path: Path) -> bool:
        if path.parent.name == ".canonical":
            digest = path.stem
            return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)

        stem = path.stem
        legacy_source_stem = cls._legacy_source_stem(path)
        if not legacy_source_stem:
            return False

        own_content_list = path.with_name(f"{stem}_content_list.json")
        legacy_sources = [path.with_name(f"{legacy_source_stem}{suffix}") for suffix in (".md", ".markdown")]
        return any(source.exists() for source in legacy_sources) and not own_content_list.exists()

    @staticmethod
    def _legacy_source_stem(path: Path) -> str:
        stem = path.stem
        if stem.endswith("_canonical"):
            return stem.removesuffix("_canonical")
        if "_canonical_" in stem:
            prefix, digest = stem.rsplit("_canonical_", 1)
            if len(digest) == 64 and all(character in "0123456789abcdef" for character in digest):
                return prefix
        return ""

    @staticmethod
    def _is_generated_canonical_json(path: Path) -> bool:
        digest = path.stem
        return (
            path.parent.name == ".canonical"
            and len(digest) == 64
            and all(character in "0123456789abcdef" for character in digest)
        )

    @classmethod
    def _legacy_fallbacks_for(cls, markdown_path: Path, generated_paths: list[Path]) -> list[Path]:
        matches: list[Path] = []
        for path in generated_paths:
            if path.parent != markdown_path.parent:
                continue
            if cls._legacy_source_stem(path) == markdown_path.stem:
                matches.append(path)
        return matches

    @classmethod
    def _materialize_json_snapshot(cls, json_path: Path, output_dir: Path) -> tuple[Path, Any]:
        if json_path.is_symlink():
            raise ValueError(f"MinerU JSON must not be a symbolic link: {json_path}")
        raw = cls._read_artifact_bytes(json_path, output_dir, "MinerU JSON")
        digest = hashlib.sha256(raw).hexdigest()
        canonical_dir = json_path.parent / ".canonical"
        if canonical_dir.is_symlink():
            raise ValueError(f"Canonical JSON directory must not be a symbolic link: {canonical_dir}")
        cls._ensure_directory(canonical_dir, output_dir, "Canonical JSON directory")
        canonical_path = canonical_dir / f"{digest}.json"
        cls._atomic_write_bytes(canonical_path, raw, output_dir)
        return canonical_path, cls._parse_json(raw)

    @classmethod
    def _content_item_markdown(cls, item: dict[str, Any], image_prefix: str = "") -> str:
        item_type = str(item.get("type") or "").strip().lower()
        fragments: list[str] = []

        if item_type == "list":
            list_items = cls._text_values(item.get("list_items"))
            fragments.extend(f"- {value}" for value in list_items)
        elif item_type == "table":
            fragments.extend(cls._text_values(item.get("table_caption")))
            fragments.extend(cls._text_values(item.get("table_body")))
            fragments.extend(cls._text_values(item.get("table_footnote")))
        elif item_type in {"code", "algorithm"}:
            prefix = "code" if item_type == "code" else "algorithm"
            fragments.extend(cls._text_values(item.get(f"{prefix}_caption")))
            code_body = "\n".join(cls._text_values(item.get(f"{prefix}_body")))
            if code_body:
                fragments.append(f"```\n{code_body}\n```")
            fragments.extend(cls._text_values(item.get(f"{prefix}_footnote")))
        elif item_type in {"image", "chart"}:
            image_ref = str(item.get("img_path") or item.get("image_path") or "").strip()
            if image_ref:
                if image_prefix and not image_ref.startswith("/") and "://" not in image_ref:
                    image_ref = f"{image_prefix}{image_ref}"
                fragments.append(f"![]({image_ref})")
            fragments.extend(cls._text_values(item.get(f"{item_type}_caption")))
            fragments.extend(cls._text_values(item.get(f"{item_type}_footnote")))
        else:
            fragments.extend(cls._text_values(item.get("text")))

        if not fragments:
            fragments.extend(cls._text_values(item.get("text")))
        return "\n".join(fragments).strip()

    @classmethod
    def _text_values(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            values: list[str] = []
            for item in value:
                values.extend(cls._text_values(item))
            return values
        if isinstance(value, dict):
            direct = value.get("text") or value.get("content")
            if isinstance(direct, str):
                return cls._text_values(direct)
            for key in ("children", "list_items"):
                nested = cls._text_values(value.get(key))
                if nested:
                    return nested
        return []

    @classmethod
    def _read_markdown(cls, path: Path, output_dir: Path) -> tuple[Path, str]:
        if path.is_symlink():
            raise ValueError(f"MinerU Markdown must not be a symbolic link: {path}")
        root, relative = cls._artifact_location(path, output_dir)
        raw = cls._read_artifact_bytes(path, output_dir, "MinerU Markdown")
        return root / relative, raw.decode("utf-8", errors="replace")

    @staticmethod
    def _artifact_location(path: Path, output_dir: Path) -> tuple[Path, Path]:
        root = output_dir.resolve(strict=True)
        candidate = path if path.is_absolute() else root / path
        try:
            relative = candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"MinerU artifact is outside output directory: {path}") from exc
        if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
            raise ValueError(f"MinerU artifact path is invalid: {path}")
        return root, relative

    @classmethod
    def _open_directory(cls, directory: Path, output_dir: Path, label: str) -> int:
        root, relative = cls._artifact_location(directory / ".artifact", output_dir)
        relative_directory = relative.parent
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(root, flags)
        try:
            for part in relative_directory.parts:
                child_descriptor = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child_descriptor
            return descriptor
        except OSError as exc:
            os.close(descriptor)
            raise ValueError(f"{label} must remain inside the output directory without symbolic links") from exc

    @classmethod
    def _read_artifact_bytes(cls, path: Path, output_dir: Path, label: str) -> bytes:
        _root, relative = cls._artifact_location(path, output_dir)
        parent_descriptor = cls._open_directory(path.parent, output_dir, f"{label} parent")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            try:
                descriptor = os.open(relative.name, flags, dir_fd=parent_descriptor)
            except OSError as exc:
                raise ValueError(f"{label} must be a regular file without symbolic links: {path}") from exc
            try:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise ValueError(f"{label} must be a regular file: {path}")
                with os.fdopen(descriptor, "rb") as handle:
                    descriptor = -1
                    return handle.read()
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
        finally:
            os.close(parent_descriptor)

    @classmethod
    def _artifact_size(cls, path: Path, output_dir: Path, label: str) -> int:
        _root, relative = cls._artifact_location(path, output_dir)
        parent_descriptor = cls._open_directory(path.parent, output_dir, f"{label} parent")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            try:
                descriptor = os.open(relative.name, flags, dir_fd=parent_descriptor)
            except OSError as exc:
                raise ValueError(f"{label} must be a regular file without symbolic links: {path}") from exc
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode):
                    raise ValueError(f"{label} must be a regular file: {path}")
                return metadata.st_size
            finally:
                os.close(descriptor)
        finally:
            os.close(parent_descriptor)

    @classmethod
    def _ensure_directory(cls, path: Path, output_dir: Path, label: str) -> None:
        _root, relative = cls._artifact_location(path / ".artifact", output_dir)
        parent_descriptor = cls._open_directory(path.parent, output_dir, f"{label} parent")
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            try:
                os.mkdir(relative.parent.name, mode=0o700, dir_fd=parent_descriptor)
            except FileExistsError:
                pass
            try:
                descriptor = os.open(relative.parent.name, flags, dir_fd=parent_descriptor)
            except OSError as exc:
                raise ValueError(f"{label} must be a real directory without symbolic links: {path}") from exc
            else:
                os.close(descriptor)
        finally:
            os.close(parent_descriptor)

    @classmethod
    def _atomic_write_text(cls, path: Path, content: str, output_dir: Path) -> None:
        cls._atomic_write_bytes(path, content.encode("utf-8"), output_dir)

    @classmethod
    def _atomic_write_bytes(cls, path: Path, content: bytes, output_dir: Path) -> None:
        _root, relative = cls._artifact_location(path, output_dir)
        parent_descriptor = cls._open_directory(path.parent, output_dir, "Canonical artifact parent")
        temporary_name = f".{relative.name}.{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = -1
        try:
            descriptor = os.open(temporary_name, flags, 0o600, dir_fd=parent_descriptor)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(
                temporary_name,
                relative.name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            os.fsync(parent_descriptor)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                os.unlink(temporary_name, dir_fd=parent_descriptor)
            except FileNotFoundError:
                pass
            os.close(parent_descriptor)

    def _asset(self, job_id: str, output_dir: Path, path: Path) -> OcrAsset:
        relative = path.relative_to(output_dir).as_posix()
        asset_id = f"asset-{hashlib.sha1(relative.encode('utf-8')).hexdigest()[:16]}"
        size_bytes = self._artifact_size(path, output_dir, "MinerU image")
        return OcrAsset(
            asset_id=asset_id,
            name=path.name,
            path=relative,
            url=self._file_url(job_id, path),
            size_bytes=size_bytes,
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
            markdown_start=int(item["start"]) if isinstance(item.get("start"), int) else None,
            markdown_end=int(item["end"]) if isinstance(item.get("end"), int) else None,
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
    def _parse_json(raw: bytes) -> Any:
        text = raw.decode("utf-8", errors="replace")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    @classmethod
    def _read_json(cls, path: Path, output_dir: Path) -> Any:
        return cls._parse_json(cls._read_artifact_bytes(path, output_dir, "MinerU JSON"))

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
