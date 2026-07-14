"""Runtime foundation parity tests.

These tests deliberately pin identity as well as serialized behaviour.  The
worker_base module remains the compatibility façade used by legacy modules,
while runtime modules own the extracted definitions.
"""

from __future__ import annotations

from app import main, worker_base
from app.runtime import ocr_flow_state


def test_worker_base_reexports_shared_runtime_instances() -> None:
    """The façade must not create duplicate config or OCR-flow state objects."""
    assert main.app is worker_base.app
    assert worker_base.OCR_FLOW_STEP_DEFINITIONS is ocr_flow_state.OCR_FLOW_STEP_DEFINITIONS
    assert worker_base.OCR_FLOW_TERMINAL_STATUSES is ocr_flow_state.OCR_FLOW_TERMINAL_STATUSES


def test_worker_base_reexports_ocr_flow_state_functions() -> None:
    """Legacy imports must resolve to the extracted OCR-flow implementation."""
    for name in (
        "build_ocr_flow",
        "ensure_ocr_flow",
        "summarize_ocr_flow",
        "repair_stale_running_ocr_flow_steps",
        "finalize_ocr_flow_for_terminal_job",
        "mark_ocr_flow_step",
        "now_iso",
        "parse_ocr_flow_time",
        "ocr_flow_duration_ms",
    ):
        assert getattr(worker_base, name) is getattr(ocr_flow_state, name)


def test_extracted_ocr_flow_preserves_fixed_snapshot() -> None:
    """A fixed timestamp must produce the same wire payload as before extraction."""
    flow = ocr_flow_state.build_ocr_flow("2026-07-14T00:00:00+00:00")

    assert flow["status"] == "pending"
    assert flow["currentStep"] == "preprocess"
    assert flow["startedAt"] == "2026-07-14T00:00:00+00:00"
    assert flow["completedCount"] == 1
    assert flow["totalCount"] == len(ocr_flow_state.OCR_FLOW_STEP_DEFINITIONS)
    assert flow["steps"][0] == {
        "id": "upload",
        "label": "文件上传",
        "description": "保存原始上传文件",
        "status": "success",
        "startedAt": "2026-07-14T00:00:00+00:00",
        "finishedAt": "2026-07-14T00:00:00+00:00",
        "durationMs": 0,
        "message": "",
    }
