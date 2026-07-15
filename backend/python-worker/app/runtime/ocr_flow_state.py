"""OCR-Flow state machine helpers.

This module owns only the serializable OCR-Flow definitions and pure-ish state
transitions.  ``worker_base`` re-exports these names for legacy worker modules,
so the wire shape and import identity remain unchanged during the split.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


OCR_FLOW_STEP_DEFINITIONS = [
    {"id": "upload", "label": "文件上传", "description": "保存原始上传文件"},
    {"id": "preprocess", "label": "预处理", "description": "识别文件类型并准备 OCR 输入"},
    {"id": "ocr-provider", "label": "OCR 引擎", "description": "调用 MinerU 或直接读取 Markdown"},
    {"id": "collect-outputs", "label": "收集产物", "description": "读取 Markdown、JSON 和图片资源"},
    {"id": "local-boundary-detect", "label": "本地边界候选", "description": "识别大题、题号、小问、选项和题图候选边界"},
    {"id": "llm-boundary-refine", "label": "AI 边界确认", "description": "让大模型只确认边界，不生成题干正文"},
    {"id": "question-structure-build", "label": "结构构建", "description": "按证据边界切片生成题目结构"},
    {"id": "sub-question-split", "label": "小问拆解", "description": "将大题内的小问写入 subQuestions"},
    {"id": "visual-repair", "label": "视觉修复", "description": "题目 crop、横线检测和可选 Pix2Text 二次 OCR"},
    {"id": "structure-validate", "label": "结构校验", "description": "校验选项、小问、题图、空位和证据回溯"},
    {"id": "math-normalize", "label": "公式校验", "description": "归一化公式并生成质量检查结果"},
    {"id": "ai-enrich", "label": "AI 增强", "description": "按配置执行语义修复和元数据补全"},
]
OCR_FLOW_TERMINAL_STATUSES = {"success", "failed", "skipped"}


def now_iso() -> str:
    """返回当前 UTC 时间的 ISO 字符串。"""
    return datetime.now(timezone.utc).isoformat()


def parse_ocr_flow_time(value: Any) -> datetime | None:
    """解析 OCR-Flow 时间戳。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def ocr_flow_duration_ms(started_at: Any, finished_at: Any, fallback_now: str) -> int | None:
    """计算 OCR-Flow 节点耗时。"""
    started = parse_ocr_flow_time(started_at)
    finished = parse_ocr_flow_time(finished_at) or parse_ocr_flow_time(fallback_now)
    if not started or not finished:
        return None
    return max(0, int((finished - started).total_seconds() * 1000))


def build_ocr_flow(created_at: str | None = None) -> dict[str, Any]:
    """初始化 OCR-Flow 节点状态。"""
    timestamp = created_at or now_iso()
    steps: list[dict[str, Any]] = []
    for definition in OCR_FLOW_STEP_DEFINITIONS:
        step = {
            **definition,
            "status": "pending",
            "startedAt": None,
            "finishedAt": None,
            "durationMs": None,
            "message": "",
        }
        if definition["id"] == "upload":
            step.update({
                "status": "success",
                "startedAt": timestamp,
                "finishedAt": timestamp,
                "durationMs": 0,
            })
        steps.append(step)
    return summarize_ocr_flow({
        "status": "pending",
        "currentStep": "preprocess",
        "startedAt": timestamp,
        "finishedAt": None,
        "steps": steps,
    })


def ensure_ocr_flow(job: dict[str, Any]) -> dict[str, Any]:
    """确保 job 中存在 OCR-Flow 状态。"""
    flow = job.get("ocrFlow")
    if isinstance(flow, dict) and isinstance(flow.get("steps"), list):
        known_steps = {str(step.get("id")): step for step in flow.get("steps", []) if isinstance(step, dict)}
        normalized_steps = []
        for definition in OCR_FLOW_STEP_DEFINITIONS:
            existing = known_steps.get(definition["id"], {})
            normalized_steps.append({
                **definition,
                "status": existing.get("status", "pending"),
                "startedAt": existing.get("startedAt"),
                "finishedAt": existing.get("finishedAt"),
                "durationMs": existing.get("durationMs"),
                "message": existing.get("message", ""),
            })
        flow["steps"] = normalized_steps
        job["ocrFlow"] = summarize_ocr_flow(flow)
        return job["ocrFlow"]

    created_at = str(job.get("createdAt") or now_iso())
    job["ocrFlow"] = build_ocr_flow(created_at)
    return job["ocrFlow"]


def summarize_ocr_flow(flow: dict[str, Any]) -> dict[str, Any]:
    """刷新 OCR-Flow 汇总字段。"""
    timestamp = now_iso()
    steps = [step for step in flow.get("steps", []) if isinstance(step, dict)]
    repair_stale_running_ocr_flow_steps(steps, timestamp)
    for step in steps:
        if step.get("startedAt") and (step.get("finishedAt") or step.get("status") == "running"):
            step["durationMs"] = ocr_flow_duration_ms(step.get("startedAt"), step.get("finishedAt"), timestamp)
        elif not step.get("startedAt"):
            step["durationMs"] = None

    running_step = next((step for step in steps if step.get("status") == "running"), None)
    pending_step = next((step for step in steps if step.get("status") == "pending"), None)
    failed_step = next((step for step in steps if step.get("status") == "failed"), None)
    completed_count = sum(1 for step in steps if step.get("status") in {"success", "skipped"})

    if failed_step:
        flow["status"] = "failed"
        flow["currentStep"] = failed_step.get("id")
        flow["finishedAt"] = failed_step.get("finishedAt") or flow.get("finishedAt")
    elif running_step:
        flow["status"] = "running"
        flow["currentStep"] = running_step.get("id")
        flow["finishedAt"] = None
    elif pending_step:
        flow["status"] = "pending"
        flow["currentStep"] = pending_step.get("id")
        flow["finishedAt"] = None
    else:
        flow["status"] = "success"
        flow["currentStep"] = None
        flow["finishedAt"] = flow.get("finishedAt") or timestamp

    flow["completedCount"] = completed_count
    flow["totalCount"] = len(steps)
    flow["elapsedMs"] = ocr_flow_duration_ms(flow.get("startedAt"), flow.get("finishedAt"), timestamp)
    return flow


def repair_stale_running_ocr_flow_steps(steps: list[dict[str, Any]], timestamp: str) -> None:
    """Close impossible running steps when later OCR-Flow steps already finished.

    A duplicated OCR job can write an older snapshot after a newer run has advanced
    the flow. In that state the job may be successful while an earlier step, most
    often llm-boundary-refine, remains running forever. The later terminal step is
    stronger evidence, so close the stale running step as skipped.
    """
    for index, step in enumerate(steps):
        if step.get("status") != "running":
            continue
        later_terminal = next(
            (
                later
                for later in steps[index + 1:]
                if later.get("status") in OCR_FLOW_TERMINAL_STATUSES
            ),
            None,
        )
        if not later_terminal:
            continue
        finished_at = (
            later_terminal.get("startedAt")
            or later_terminal.get("finishedAt")
            or timestamp
        )
        step["status"] = "skipped"
        step["finishedAt"] = step.get("finishedAt") or finished_at
        message = str(step.get("message") or "").strip()
        repair_message = "检测到后续节点已完成，自动结束该节点"
        step["message"] = f"{message}；{repair_message}" if message and repair_message not in message else repair_message


def finalize_ocr_flow_for_terminal_job(job: dict[str, Any]) -> None:
    """Keep OCR-Flow consistent when the job itself has reached a terminal state."""
    if job.get("status") != "success":
        return
    flow = job.get("ocrFlow")
    if not isinstance(flow, dict) or not isinstance(flow.get("steps"), list):
        return
    timestamp = str(job.get("finishedAt") or now_iso())
    for step in flow["steps"]:
        if not isinstance(step, dict):
            continue
        if step.get("status") == "running":
            step["status"] = "skipped"
            step["startedAt"] = step.get("startedAt") or timestamp
            step["finishedAt"] = step.get("finishedAt") or timestamp
            message = str(step.get("message") or "").strip()
            repair_message = "任务已完成，自动结束未关闭节点"
            step["message"] = f"{message}；{repair_message}" if message and repair_message not in message else repair_message
        elif step.get("status") == "pending":
            step["status"] = "skipped"
            step["startedAt"] = step.get("startedAt") or timestamp
            step["finishedAt"] = step.get("finishedAt") or timestamp
            step["message"] = step.get("message") or "任务已完成，历史节点未单独记录"
    job["ocrFlow"] = summarize_ocr_flow(flow)


def mark_ocr_flow_step(
    job: dict[str, Any],
    step_id: str,
    status: str,
    message: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """更新 OCR-Flow 单个节点状态。"""
    flow = ensure_ocr_flow(job)
    current_time = timestamp or now_iso()
    step = next((item for item in flow["steps"] if item.get("id") == step_id), None)
    if not step:
        return flow

    if status == "running":
        step["startedAt"] = step.get("startedAt") or current_time
        step["finishedAt"] = None
    elif status in OCR_FLOW_TERMINAL_STATUSES:
        step["startedAt"] = step.get("startedAt") or current_time
        step["finishedAt"] = current_time
    else:
        step["startedAt"] = None
        step["finishedAt"] = None

    step["status"] = status
    if message is not None:
        step["message"] = message
    job["ocrFlow"] = summarize_ocr_flow(flow)
    return job["ocrFlow"]


__all__ = [
    "OCR_FLOW_STEP_DEFINITIONS",
    "OCR_FLOW_TERMINAL_STATUSES",
    "now_iso",
    "parse_ocr_flow_time",
    "ocr_flow_duration_ms",
    "build_ocr_flow",
    "ensure_ocr_flow",
    "summarize_ocr_flow",
    "repair_stale_running_ocr_flow_steps",
    "finalize_ocr_flow_for_terminal_job",
    "mark_ocr_flow_step",
]
