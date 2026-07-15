"""Stable provider-neutral OCR post-processing entrypoints.

Provider adapters may import the public contracts from this package without
depending on MinerU-specific implementation modules.  Internal algorithms stay
behind :class:`OcrPostProcessingPipeline`.
"""

from app.ocr.contracts import (
    CanonicalOcrBundle,
    CanonicalOcrBundleError,
    OcrAsset,
    OcrLayoutBlock,
    OcrPage,
    SourceDocumentRef,
)
from app.ocr.postprocess_pipeline import OcrPostProcessingPipeline

__all__ = [
    "CanonicalOcrBundle",
    "CanonicalOcrBundleError",
    "OcrAsset",
    "OcrLayoutBlock",
    "OcrPage",
    "OcrPostProcessingPipeline",
    "SourceDocumentRef",
]
