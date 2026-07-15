"""Compatibility entry point for the OCR post-processing pipeline.

The implementation remains in :mod:`app.ocr_processing` for this first
extraction step.  Keeping this class as the only pipeline entry point lets
callers move to the modular package without changing the existing algorithm,
configuration, or serialized output.
"""

from __future__ import annotations

from typing import Any

from app.ocr.contracts import CanonicalOcrBundle


class OcrPostProcessingPipeline:
    """Run the existing OCR post-processing implementation unchanged."""

    def run(self, job_id: str) -> dict[str, Any]:
        """Refresh from persisted canonical evidence, or adapt legacy MinerU jobs."""
        from app.worker_base import read_job
        from app.ocr.mineru_adapter import MineruOcrBundleAdapter

        persisted = read_job(job_id).get("canonicalOcrBundle")
        if isinstance(persisted, dict):
            bundle = CanonicalOcrBundle.from_persisted_manifest(persisted)
            if bundle.document_id != job_id:
                raise ValueError("persisted canonical bundle documentId does not match jobId")
            return self.run_bundle(bundle)
        return self.run_bundle(MineruOcrBundleAdapter().from_job(job_id))

    def run_bundle(self, bundle: CanonicalOcrBundle) -> dict[str, Any]:
        """Run question post-processing from explicit, provider-neutral evidence."""
        # Import lazily to avoid a cycle: ocr_processing owns the legacy
        # façade and imports this class at module import time.
        from app.ocr_processing import collect_outputs_impl

        return collect_outputs_impl(bundle.document_id, bundle=bundle)
