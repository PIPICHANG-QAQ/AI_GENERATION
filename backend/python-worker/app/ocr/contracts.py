"""Provider-neutral OCR evidence contracts for question post-processing.

The post-processing pipeline consumes these models instead of provider-specific
directory names or JSON fields.  The first version deliberately carries the
legacy artifact root so existing image and visual-repair I/O remains unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping


_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


class CanonicalOcrBundleError(ValueError):
    """Raised when OCR evidence cannot safely enter post-processing."""


@dataclass(frozen=True)
class OcrAsset:
    asset_id: str
    name: str
    path: str
    url: str
    size_bytes: int
    media_type: str

    def __post_init__(self) -> None:
        if not self.asset_id.strip():
            raise CanonicalOcrBundleError("assetId is required")
        if not self.path.strip():
            raise CanonicalOcrBundleError("asset path is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "assetId": self.asset_id,
            "name": self.name,
            "path": self.path,
            "url": self.url,
            "sizeBytes": self.size_bytes,
            "mediaType": self.media_type,
        }


@dataclass(frozen=True)
class OcrPage:
    page_index: int
    width: float
    height: float
    render_ref: str = ""

    def __post_init__(self) -> None:
        if self.page_index < 0:
            raise CanonicalOcrBundleError("pageIndex must not be negative")
        if self.width <= 0 or self.height <= 0:
            raise CanonicalOcrBundleError("page dimensions must be positive")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"pageIndex": self.page_index, "width": self.width, "height": self.height}
        if self.render_ref:
            payload["renderRef"] = self.render_ref
        return payload


@dataclass(frozen=True)
class OcrLayoutBlock:
    block_id: str
    block_type: str
    page_index: int
    bbox: tuple[float, float, float, float]
    page_width: float | None
    page_height: float | None
    order: int
    text: str = ""
    image_ref: str = ""
    source_order: int = 0
    coordinate_source: str = ""

    def __post_init__(self) -> None:
        if not self.block_id.strip():
            raise CanonicalOcrBundleError("blockId is required")
        if self.page_index < 0:
            raise CanonicalOcrBundleError("pageIndex must not be negative")
        if (self.page_width is None) != (self.page_height is None):
            raise CanonicalOcrBundleError("layout page dimensions must be supplied together")
        if self.page_width is not None and (self.page_width <= 0 or self.page_height is None or self.page_height <= 0):
            raise CanonicalOcrBundleError("layout page dimensions must be positive")
        if len(self.bbox) != 4:
            raise CanonicalOcrBundleError("bbox must contain four coordinates")
        x0, y0, x1, y1 = self.bbox
        if x1 < x0 or y1 < y0:
            raise CanonicalOcrBundleError("bbox must be ordered")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "blockId": self.block_id,
            "type": self.block_type,
            "text": self.text,
            "imageRef": self.image_ref,
            "pageIndex": self.page_index,
            "bbox": list(self.bbox),
            "order": self.order,
            "sourceOrder": self.source_order,
        }
        if self.page_width is not None and self.page_height is not None:
            payload["pageWidth"] = self.page_width
            payload["pageHeight"] = self.page_height
        if self.coordinate_source:
            payload["coordinateSource"] = self.coordinate_source
        return payload


@dataclass(frozen=True)
class SourceDocumentRef:
    path: str = ""
    uri: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "uri": self.uri}


@dataclass(frozen=True)
class CanonicalOcrBundle:
    document_id: str
    input_sha256: str
    canonical_markdown: str
    assets: tuple[OcrAsset, ...] = ()
    pages: tuple[OcrPage, ...] = ()
    layout_blocks: tuple[OcrLayoutBlock, ...] = ()
    source_document_ref: SourceDocumentRef | None = None
    artifact_root: str = ""
    markdown_artifact_path: str = ""
    json_artifact_path: str = ""
    producer: Mapping[str, Any] = field(default_factory=dict)
    native_artifacts: tuple[Mapping[str, Any], ...] = ()
    capabilities: frozenset[str] = field(default_factory=frozenset)
    json_content: Any = None
    schema_version: str = "canonical-ocr-bundle.v1"

    def __post_init__(self) -> None:
        if not self.document_id.strip():
            raise CanonicalOcrBundleError("documentId is required")
        if not self.input_sha256.strip():
            raise CanonicalOcrBundleError("inputSha256 is required")
        if not self.canonical_markdown.strip():
            raise CanonicalOcrBundleError("canonicalMarkdown is required")
        if self.schema_version != "canonical-ocr-bundle.v1":
            raise CanonicalOcrBundleError("unsupported schemaVersion")

        asset_refs = {asset.path for asset in self.assets}
        asset_refs.update(asset.name for asset in self.assets)
        asset_refs.update(asset.url for asset in self.assets if asset.url)
        missing = [ref for ref in self._markdown_image_refs() if ref not in asset_refs]
        if missing:
            raise CanonicalOcrBundleError(f"markdown image reference has no asset: {missing[0]}")

        page_indexes = [page.page_index for page in self.pages]
        if len(page_indexes) != len(set(page_indexes)):
            raise CanonicalOcrBundleError("pages must have unique pageIndex values")

    @property
    def capability_level(self) -> str:
        capabilities = self.capabilities
        if {"markdown", "embedded-images", "layout-bbox", "source-page"}.issubset(capabilities):
            return "L2"
        if {"markdown", "embedded-images"}.issubset(capabilities):
            return "L1"
        return "L0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "documentId": self.document_id,
            "inputSha256": self.input_sha256,
            "canonicalMarkdown": self.canonical_markdown,
            "assets": [asset.to_dict() for asset in self.assets],
            "pages": [page.to_dict() for page in self.pages],
            "layoutBlocks": [block.to_dict() for block in self.layout_blocks],
            "sourceDocumentRef": self.source_document_ref.to_dict() if self.source_document_ref else None,
            "artifactRoot": self.artifact_root,
            "markdownArtifactPath": self.markdown_artifact_path,
            "jsonArtifactPath": self.json_artifact_path,
            "producer": dict(self.producer),
            "nativeArtifacts": [dict(artifact) for artifact in self.native_artifacts],
            "capabilities": sorted(self.capabilities),
            "capabilityLevel": self.capability_level,
            "json": self.json_content,
        }

    def _markdown_image_refs(self) -> list[str]:
        return [match.strip().strip("<>") for match in _MARKDOWN_IMAGE_RE.findall(self.canonical_markdown)]
