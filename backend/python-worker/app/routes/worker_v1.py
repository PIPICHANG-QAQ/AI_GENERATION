"""Versioned worker v1 routes.

The handlers are deliberately thin delegates to the existing compatibility
functions.  This gives future Java callers a stable namespace without creating
a second OCR or AI implementation.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, UploadFile

from app.contracts.worker_v1 import AnalysisRequest, CanonicalizationRequest, StandardizationRequest
from app.question_markdown import normalize_math_markdown
# Kept as a named delegate target so integrations can replace the compatibility
# implementation in tests without importing the large legacy route module.
standardize_markdown_local = normalize_math_markdown


def _legacy(name: str, *args: Any, **kwargs: Any):
    """Resolve a legacy handler lazily, avoiding a route-module import cycle."""
    from app import worker_routes

    return getattr(worker_routes, name)(*args, **kwargs)


def create_ocr_job_record(*args: Any, **kwargs: Any):
    return _legacy("create_ocr_job_record", *args, **kwargs)


def worker_get_ocr_job(*args: Any, **kwargs: Any):
    return _legacy("worker_get_ocr_job", *args, **kwargs)


def worker_get_ocr_result(*args: Any, **kwargs: Any):
    return _legacy("worker_get_ocr_result", *args, **kwargs)


def worker_retry_ocr_job(*args: Any, **kwargs: Any):
    return _legacy("worker_retry_ocr_job", *args, **kwargs)


def preview_import_task_canonicalization(*args: Any, **kwargs: Any):
    return _legacy("preview_import_task_canonicalization", *args, **kwargs)


def worker_standardize_markdown_ai(*args: Any, **kwargs: Any):
    return _legacy("worker_standardize_markdown_ai", *args, **kwargs)


def generate_question_analysis(*args: Any, **kwargs: Any):
    return _legacy("generate_question_analysis", *args, **kwargs)


def worker_export_render(*args: Any, **kwargs: Any):
    return _legacy("worker_export_render", *args, **kwargs)

router = APIRouter(prefix="/worker/v1", tags=["worker-v1"])


@router.get("/capabilities")
def capabilities() -> dict[str, Any]:
    """Describe the stable v1 worker operations."""
    return {
        "schemaVersion": "worker-capabilities.v1",
        "workerVersion": "0.1.0",
        "operations": [
            "ocr.create",
            "ocr.status",
            "ocr.result",
            "ocr.retry",
            "canonicalization.preview",
            "standardize",
            "analysis",
            "export.render",
        ],
        "questionAssembly": {"published": False, "reason": "reserved for a later contract revision"},
    }


@router.post("/ocr")
async def create_ocr(background_tasks: BackgroundTasks, file: UploadFile = File(...)) -> dict[str, Any]:
    """Create an OCR job using the existing worker pipeline."""
    return create_ocr_job_record(background_tasks, file)


@router.get("/ocr/{job_id}")
def get_ocr(job_id: str) -> dict[str, Any]:
    return worker_get_ocr_job(job_id)


@router.get("/ocr/{job_id}/result")
def get_ocr_result(job_id: str) -> dict[str, Any]:
    return worker_get_ocr_result(job_id)


@router.post("/ocr/{job_id}/retry")
def retry_ocr(background_tasks: BackgroundTasks, job_id: str) -> dict[str, Any]:
    return worker_retry_ocr_job(background_tasks, job_id)


@router.post("/canonicalization/preview")
def canonicalization_preview(payload: CanonicalizationRequest) -> dict[str, Any]:
    return preview_import_task_canonicalization(payload.model_dump(mode="python", by_alias=True))


@router.post("/standardize")
def standardize(payload: StandardizationRequest) -> dict[str, Any]:
    return worker_standardize_markdown_ai(payload)


@router.post("/analysis")
def analysis(payload: AnalysisRequest) -> dict[str, Any]:
    return generate_question_analysis(payload)


@router.post("/export/render")
def export_render(payload: dict[str, Any]):
    return worker_export_render(payload)
