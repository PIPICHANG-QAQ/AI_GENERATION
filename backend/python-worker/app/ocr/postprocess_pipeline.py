"""Compatibility entry point for the OCR post-processing pipeline.

The implementation remains in :mod:`app.ocr_processing` for this first
extraction step.  Keeping this class as the only pipeline entry point lets
callers move to the modular package without changing the existing algorithm,
configuration, or serialized output.
"""

from __future__ import annotations

from typing import Any


class OcrPostProcessingPipeline:
    """Run the existing OCR post-processing implementation unchanged."""

    def run(self, job_id: str) -> dict[str, Any]:
        """Delegate to the legacy implementation without changing its contract."""
        # Import lazily to avoid a cycle: ocr_processing owns the legacy
        # façade and imports this class at module import time.
        from app.ocr_processing import collect_outputs_impl

        return collect_outputs_impl(job_id)
