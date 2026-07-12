"""Python worker 基础配置与共享模型。

本模块只保存 FastAPI 应用对象、路径配置、请求模型、JSON 存储和 OCR-Flow 运行时摘要。
Java 主后端是业务入口；这里的状态文件只作为 worker 兼容桥和本地开发回退。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import uuid
from html import escape
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.llm_splitter import (
    enrich_questions_metadata_with_llm,
    generate_question_analysis_with_llm,
    llm_status,
    refine_question_boundaries_with_llm,
    refine_questions_with_llm,
    rule_splitter_metadata,
    standardize_markdown_with_llm,
)
from app.math_normalizer import normalize_math_markdown, normalize_structured_math
from app.ocr_flow import OcrFlowRuntime, parse_extensions, providers, selected_provider_name


# APP_ROOT 指向 backend/python-worker，BACKEND_ROOT 指向统一后的 Java 主后端目录 backend。
APP_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = APP_ROOT.parent
PROJECT_ROOT = BACKEND_ROOT.parent
STORAGE_ROOT = Path(os.getenv("PYTHON_WORKER_STORAGE_ROOT", str(BACKEND_ROOT / "storage"))).resolve()
UPLOAD_ROOT = STORAGE_ROOT / "uploads"
OUTPUT_ROOT = STORAGE_ROOT / "outputs"
JOB_ROOT = STORAGE_ROOT / "jobs"
IMPORT_UPLOAD_ROOT = STORAGE_ROOT / "import_uploads"
EXPORT_ROOT = STORAGE_ROOT / "exports"
BANK_IMAGE_ROOT = STORAGE_ROOT / "bank_question_images"
LIBRARY_STORE_FILE = STORAGE_ROOT / "library_store.json"
JSON_FILE_LOCK = threading.RLock()

DEFAULT_OCR_PROVIDER_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".docx", ".pptx", ".xlsx"}
OCR_PROVIDER_EXTENSIONS = parse_extensions(os.getenv("OCR_FLOW_EXTENSIONS"), DEFAULT_OCR_PROVIDER_EXTENSIONS)
MINERU_EXTENSIONS = OCR_PROVIDER_EXTENSIONS
MARKDOWN_EXTENSIONS = {".md", ".markdown"}
DOC_CONVERT_EXTENSIONS = {".doc"}
ALLOWED_EXTENSIONS = OCR_PROVIDER_EXTENSIONS | MARKDOWN_EXTENSIONS | DOC_CONVERT_EXTENSIONS
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MINERU_TIMEOUT_SECONDS = int(os.getenv("MINERU_TIMEOUT_SECONDS", "1800"))
MINERU_VERSION_TIMEOUT_SECONDS = int(os.getenv("MINERU_VERSION_TIMEOUT_SECONDS", "3"))
QUESTION_RE = re.compile(r"^\s*(\d{1,3})[\.．、]\s*(.*)", re.S)
TASK_STATUSES = {"处理中", "待校验", "部分完成", "已完成"}
QUESTION_STATUSES = {"待校验", "已校验", "已入库"}
DIFFICULTIES = {"easy", "medium", "hard"}
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


def load_local_env() -> None:
    """加载本地 .env 配置，填充尚未存在的环境变量。"""
    # 兼容根目录、统一 backend 和 Python worker 子目录三种本地配置位置。
    for env_path in (PROJECT_ROOT / ".env", BACKEND_ROOT / ".env", APP_ROOT / ".env"):
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


load_local_env()

OCR_PROVIDER_EXTENSIONS = parse_extensions(os.getenv("OCR_FLOW_EXTENSIONS"), DEFAULT_OCR_PROVIDER_EXTENSIONS)
MINERU_EXTENSIONS = OCR_PROVIDER_EXTENSIONS
ALLOWED_EXTENSIONS = OCR_PROVIDER_EXTENSIONS | MARKDOWN_EXTENSIONS | DOC_CONVERT_EXTENSIONS
MINERU_TIMEOUT_SECONDS = int(os.getenv("MINERU_TIMEOUT_SECONDS", str(MINERU_TIMEOUT_SECONDS)))
MINERU_VERSION_TIMEOUT_SECONDS = int(os.getenv("MINERU_VERSION_TIMEOUT_SECONDS", str(MINERU_VERSION_TIMEOUT_SECONDS)))


for directory in (UPLOAD_ROOT, OUTPUT_ROOT, JOB_ROOT, IMPORT_UPLOAD_ROOT, EXPORT_ROOT, BANK_IMAGE_ROOT):
    directory.mkdir(parents=True, exist_ok=True)


app = FastAPI(title="AI Question Bank OCR API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class MarkdownPayload(BaseModel):
    """Markdown 标准化请求模型。"""
    markdown: str = Field(default="", max_length=100000)
    rawOcrContext: str = Field(default="", max_length=100000)
    structuredHints: dict[str, Any] | None = None


class QuestionManualMarkdownPayload(BaseModel):
    """人工编辑 Markdown 更新请求模型。"""
    markdown: str = Field(default="", max_length=100000)


class KnowledgePointPayload(BaseModel):
    """知识点创建和更新请求模型。"""
    name: str = Field(min_length=1, max_length=120)
    parentId: str | None = None
    subject: str = ""
    grade: str = ""
    description: str = ""


class ImportQuestionPayload(BaseModel):
    """导入题更新请求模型。"""
    manualMarkdown: str | None = Field(default=None, max_length=100000)
    type: str | None = None
    answer: str | None = Field(default=None, max_length=50000)
    analysis: str | None = Field(default=None, max_length=100000)
    knowledgePointIds: list[str] | None = None
    knowledgePoints: list[str] | None = None
    difficulty: str | None = None
    score: float | None = None
    status: str | None = None
    options: list[dict[str, Any]] | None = None
    images: list[dict[str, Any]] | None = None
    imagePlacements: list[dict[str, Any]] | None = None
    subQuestions: list[dict[str, Any]] | None = None


class QuestionAnalysisPayload(BaseModel):
    """题目 AI 解析请求模型。"""
    manualMarkdown: str = Field(default="", max_length=100000)
    type: str = "unknown"
    answer: str = Field(default="", max_length=50000)
    knowledgePoints: list[str] = []
    images: list[dict[str, Any]] | None = None
    subQuestions: list[dict[str, Any]] | None = None


class ImportTaskUpdatePayload(BaseModel):
    """导入任务更新请求模型。"""
    title: str = Field(min_length=1, max_length=160)


class ImportTaskBatchDeletePayload(BaseModel):
    """导入任务批量删除请求模型。"""
    taskIds: list[str] = Field(default_factory=list, max_length=200)


class BankQuestionPayload(BaseModel):
    """题库题创建和更新请求模型。"""
    stemMarkdown: str = Field(default="", max_length=100000)
    manualMarkdown: str | None = Field(default=None, max_length=100000)
    type: str = "unknown"
    answer: str = ""
    analysis: str = ""
    knowledgePointIds: list[str] = []
    knowledgePoints: list[str] = []
    difficulty: str = "medium"
    score: float = 0
    subject: str = ""
    grade: str = ""
    region: str = ""
    year: str = ""
    source: str = ""
    options: list[dict[str, str]] = []
    images: list[dict[str, Any]] = []
    imagePlacements: list[dict[str, Any]] = []
    subQuestions: list[dict[str, Any]] = []


class PaperPayload(BaseModel):
    """试卷创建和更新请求模型。"""
    title: str = Field(min_length=1, max_length=160)
    subject: str = Field(default="", max_length=80)
    grade: str = Field(default="", max_length=80)
    questionIds: list[str] = []
    rules: dict[str, Any] = {}
    answerDisplay: str = "teacher"
    scores: dict[str, float] = {}
    subSelections: dict[str, list[str]] = {}
    header: dict[str, Any] = {}
    status: str = "已发布"


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


def safe_filename(filename: str) -> str:
    """清理上传文件名，避免路径分隔符影响本地存储路径。"""
    name = Path(filename or "upload").name
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    return name or "upload"


def job_file(job_id: str) -> Path:
    """根据 OCR job ID 计算 job 元数据文件路径。"""
    return JOB_ROOT / f"{job_id}.json"


def mineru_command() -> str | None:
    """读取当前配置的 MinerU 命令。"""
    provider = providers(APP_ROOT, MINERU_VERSION_TIMEOUT_SECONDS)["mineru"]
    return provider.command() if hasattr(provider, "command") else None


def backup_json_file(path: Path) -> Path:
    """返回 JSON 状态文件的备份路径。"""
    return path.with_name(path.name + ".bak")


def corrupt_json_file(path: Path) -> Path:
    """返回 JSON 损坏文件隔离路径。"""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return path.with_name(f"{path.name}.corrupt-{timestamp}")


def read_json_with_backup(path: Path, default: Any = None) -> Any:
    """读取 JSON 文件，主文件损坏时回退 .bak 并隔离损坏文件。"""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        backup = backup_json_file(path)
        if backup.exists():
            try:
                return json.loads(backup.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        try:
            isolated = corrupt_json_file(path)
            path.replace(isolated)
        except OSError:
            pass
        return default


def atomic_write_json(path: Path, payload: Any) -> None:
    """原子写入 JSON 文件，并把成功写入内容复制为 .bak 备份。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, path)
        shutil.copy2(path, backup_json_file(path))
    finally:
        tmp_path.unlink(missing_ok=True)


def write_job(job: dict[str, Any]) -> None:
    """将 OCR job 元数据写入本地 JSON 文件。"""
    with JSON_FILE_LOCK:
        finalize_ocr_flow_for_terminal_job(job)
        atomic_write_json(job_file(job["jobId"]), job)


def read_job(job_id: str) -> dict[str, Any]:
    """读取指定 OCR job 的本地 JSON 元数据。"""
    path = job_file(job_id)
    existed = path.exists()
    job = read_json_with_backup(path)
    if isinstance(job, dict):
        return job
    if not existed:
        raise HTTPException(status_code=404, detail="OCR job not found")
    raise HTTPException(status_code=500, detail="OCR job metadata is corrupted")


def default_store() -> dict[str, Any]:
    """构造本地业务数据存储的默认结构。"""
    return {
        "importTasks": [],
        "bankQuestions": [],
        "knowledgePoints": [],
        "papers": [],
    }


def read_store() -> dict[str, Any]:
    """读取本地业务数据存储，缺失时返回默认结构。"""
    with JSON_FILE_LOCK:
        store = read_json_with_backup(LIBRARY_STORE_FILE, default_store())
    if not isinstance(store, dict):
        store = default_store()
    defaults = default_store()
    for key, value in defaults.items():
        if key not in store or not isinstance(store[key], list):
            store[key] = value
    return store


def write_store(store: dict[str, Any]) -> None:
    """将本地业务数据存储写回 JSON 文件。"""
    with JSON_FILE_LOCK:
        atomic_write_json(LIBRARY_STORE_FILE, store)


def make_id(prefix: str) -> str:
    """生成带业务前缀的唯一 ID。"""
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def find_by_id(items: list[dict[str, Any]], item_id: str) -> dict[str, Any] | None:
    """在字典列表中按 id 查找对象。"""
    return next((item for item in items if item.get("id") == item_id), None)


def normalize_question_type(value: Any) -> str:
    """归一化题型字段，缺失时返回 unknown。"""
    question_type = str(value or "unknown").strip()
    return question_type if question_type in {"choice", "fill_blank", "solution", "unknown"} else "unknown"


def normalize_difficulty(value: Any) -> str:
    """归一化难度字段，缺失时返回 medium。"""
    difficulty = str(value or "medium").strip().lower()
    return difficulty if difficulty in DIFFICULTIES else "medium"


def normalize_string_values(values: Any) -> list[str]:
    """将任意输入归一化为去空白字符串列表。"""
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def create_ocr_job_record(background_tasks: BackgroundTasks, file: UploadFile, upload_root: Path = UPLOAD_ROOT) -> dict[str, Any]:
    """保存上传文件并创建待执行 OCR job 记录。"""
    filename = safe_filename(file.filename or "upload")
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix or 'unknown'}")
    ensure_ocr_provider_ready_for_file(filename)

    job_id = f"ocr_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    upload_dir = upload_root / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_path = upload_dir / filename
    with upload_path.open("wb") as destination:
        shutil.copyfileobj(file.file, destination)

    created_at = now_iso()
    job = {
        "jobId": job_id,
        "filename": filename,
        "contentType": file.content_type,
        "status": "pending",
        "createdAt": created_at,
        "startedAt": None,
        "finishedAt": None,
        "error": None,
        "uploadPath": str(upload_path),
        "ocrFlowProvider": selected_provider_name(),
        "ocrProvider": selected_provider_name(),
        "outputs": None,
        "ocrFlow": build_ocr_flow(created_at),
    }
    write_job(job)
    # 延迟导入避免基础配置模块和 OCR 执行模块形成循环依赖。
    from app.ocr_execution import run_ocr_job

    background_tasks.add_task(run_ocr_job, job_id, str(upload_path))
    return job


def ensure_ocr_provider_ready_for_file(filename: str) -> None:
    """在创建 OCR job 前确认非 Markdown 文件所需 provider 可用。"""
    suffix = Path(filename).suffix.lower()
    if suffix in MARKDOWN_EXTENSIONS:
        return
    if suffix not in OCR_PROVIDER_EXTENSIONS and suffix not in DOC_CONVERT_EXTENSIONS:
        return

    provider = selected_ocr_provider()
    if provider is None:
        raise HTTPException(
            status_code=503,
            detail=f"Unsupported OCR provider: {selected_provider_name()}",
        )
    status = provider.status()
    if status.get("installed") is True:
        return

    error = str(status.get("error") or "OCR provider is not installed.")
    raise HTTPException(
        status_code=503,
        detail=(
            f"OCR provider is unavailable for {suffix or 'this'} files. "
            "Run ./scripts/deploy_local.sh --with-mineru or configure MINERU_COMMAND. "
            f"{error}"
        ),
    )


def mineru_status() -> dict[str, Any]:
    """返回 MinerU provider 的运行时状态。"""
    return providers(APP_ROOT, MINERU_VERSION_TIMEOUT_SECONDS)["mineru"].status()


def ocr_flow_providers() -> dict[str, Any]:
    """返回当前注册的 OCR provider 字典。"""
    return providers(APP_ROOT, MINERU_VERSION_TIMEOUT_SECONDS)


def selected_ocr_provider() -> Any | None:
    """返回当前配置选中的 OCR provider。"""
    return ocr_flow_providers().get(selected_provider_name())


def ocr_flow_runtime() -> OcrFlowRuntime:
    """返回 OCR-Flow 的 runtime 诊断信息。"""
    # collect_outputs 位于 OCR 处理模块，运行时再导入以保持模块边界清晰。
    from app.ocr_processing import collect_outputs

    return OcrFlowRuntime(
        output_root=OUTPUT_ROOT,
        timeout_seconds=MINERU_TIMEOUT_SECONDS,
        now_iso=now_iso,
        read_job=read_job,
        write_job=write_job,
        collect_outputs=collect_outputs,
        mark_step=mark_ocr_flow_step,
    )


def ocr_flow_status() -> dict[str, Any]:
    """返回 OCR-Flow 状态 Map。"""
    available_providers = ocr_flow_providers()
    selected = selected_provider_name()
    provider = available_providers.get(selected)
    return {
        "capability": "ocr-flow",
        "selectedProvider": selected,
        "availableProviders": sorted(available_providers.keys()),
        "providerConfigured": provider is not None,
        "providerStatus": provider.status() if provider else {"provider": selected, "installed": False, "error": "Unsupported OCR provider"},
        "directMarkdownExtensions": sorted(MARKDOWN_EXTENSIONS),
        "docConvertExtensions": sorted(DOC_CONVERT_EXTENSIONS),
        "ocrProviderExtensions": sorted(OCR_PROVIDER_EXTENSIONS),
        "allowedExtensions": sorted(ALLOWED_EXTENSIONS),
        "timeoutSeconds": MINERU_TIMEOUT_SECONDS,
        "configKeys": {
            "provider": "OCR_FLOW_PROVIDER",
            "extensions": "OCR_FLOW_EXTENSIONS",
            "mineruCommand": "MINERU_COMMAND",
            "timeout": "MINERU_TIMEOUT_SECONDS",
        },
        "flowSteps": OCR_FLOW_STEP_DEFINITIONS,
    }
