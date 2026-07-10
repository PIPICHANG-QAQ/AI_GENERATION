"""导入试卷版面解析框。

本模块把 MinerU OCR bbox 中与题目相关的区域叠加到原文件预览上，供
用户从原文件快速定位到右侧题目校验卡。坐标固定为原始 OCR 位置，不随
人工编辑变化。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from app.worker_base import OUTPUT_ROOT, IMPORT_UPLOAD_ROOT, HTTPException, FileResponse


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
PDF_RENDER_SCALE = float(os.getenv("OCR_LAYOUT_PDF_RENDER_SCALE", "2.0"))
LAYOUT_PADDING_RATIO = float(os.getenv("OCR_LAYOUT_PADDING_RATIO", "0.006"))
QUESTION_ANCHOR_RE = re.compile(
    r"^\s*(?:第\s*)?(?P<number>\d{1,3})\s*(?:[.．、]|[）)]|[（(]\s*\d+(?:\.\d+)?\s*分)"
)
OPTION_LABEL_TOKEN_RE = re.compile(r"^[A-Ha-h]\s*[.．、]?$")
PAGE_NOISE_RE = re.compile(r"^\s*(?:第\s*)?\d+\s*(?:页|/\s*\d+\s*$|$)")
SECTION_TITLE_KEYWORDS = ("选择题", "填空题", "解答题", "判断题", "计算题", "综合题", "试卷", "试题", "考试", "答案卡")
PREFACE_LAYOUT_KEYWORDS = ("本试卷", "试题卷", "答题纸", "考生注意", "考试时间", "规定位置", "计算器", "注意事项")
DISABLED_VALUES = {"0", "false", "no", "off", "disabled"}


@dataclass(frozen=True)
class PaperLayoutCapability:
    """导入工作台布局解析框能力边界。"""

    capability_id: str = "paper-layout-box"
    version: str = "paper-layout.v1"
    mode: str = "question-region-binding"

    def descriptor(self) -> dict[str, str]:
        """返回可序列化能力描述。"""
        return {
            "id": self.capability_id,
            "version": self.version,
            "mode": self.mode,
            "coordinatePriority": "mineru_middle,mineru_content_list",
        }

    def attach_to_task(self, task: dict[str, Any], job: dict[str, Any] | None = None) -> dict[str, Any]:
        """给导入任务附加 paperLayout。"""
        return _attach_paper_layout(task, job)

    def build_layout(self, task: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
        """从 OCR 产物构建父题级布局框。"""
        return _build_paper_layout(task, job)

    def render_page(self, task: dict[str, Any], job: dict[str, Any], page_index: int) -> FileResponse:
        """返回试卷原文件指定页预览图。"""
        return _render_source_page(task, job, page_index)

    def question_image_refs(self, output_dir: Path, limit: int) -> list[list[str]]:
        """按 OCR 几何关系返回每道题应关联的图片引用。"""
        return _question_image_refs_by_layout(output_dir, limit)


PAPER_LAYOUT_CAPABILITY = PaperLayoutCapability()


def attach_paper_layout(task: dict[str, Any], job: dict[str, Any] | None = None) -> dict[str, Any]:
    """兼容入口：给导入任务附加 paperLayout。"""
    return PAPER_LAYOUT_CAPABILITY.attach_to_task(task, job)


def build_paper_layout(task: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    """兼容入口：从 OCR 产物构建父题级布局框。"""
    return PAPER_LAYOUT_CAPABILITY.build_layout(task, job)


def render_source_page(task: dict[str, Any], job: dict[str, Any], page_index: int) -> FileResponse:
    """兼容入口：渲染试卷页面图片。"""
    return PAPER_LAYOUT_CAPABILITY.render_page(task, job, page_index)


def question_image_refs_by_layout(output_dir: Path, limit: int) -> list[list[str]]:
    """兼容入口：按几何 bbox 返回每道题应关联的图片引用。"""
    return PAPER_LAYOUT_CAPABILITY.question_image_refs(output_dir, limit)


def question_image_ref_groups_by_layout(output_dir: Path, limit: int) -> list[dict[str, Any]]:
    """按几何 bbox 返回题图引用分组，保留布局锚点题号。"""
    return _question_image_ref_groups_by_layout(output_dir, limit)


def paper_layout_enabled() -> bool:
    """返回布局解析框是否启用。"""
    return str(os.getenv("OCR_PAPER_LAYOUT_ENABLED", "true")).strip().lower() not in DISABLED_VALUES


def _attach_paper_layout(task: dict[str, Any], job: dict[str, Any] | None = None) -> dict[str, Any]:
    """给导入任务附加 paperLayout。"""
    if not isinstance(task, dict):
        return {}
    if not paper_layout_enabled():
        layout = empty_layout(["布局解析框已关闭"])
        task["paperLayout"] = layout
        return layout
    paper_job = job if isinstance(job, dict) else None
    if paper_job is None:
        layout = empty_layout(["试卷 OCR job 不存在，无法显示布局解析框"])
        task["paperLayout"] = layout
        return layout
    if paper_job.get("status") != "success":
        layout = empty_layout(["试卷 OCR 尚未完成，暂不显示布局解析框"])
        task["paperLayout"] = layout
        return layout
    layout = _build_paper_layout(task, paper_job)
    task["paperLayout"] = layout
    return layout


def empty_layout(warnings: list[str] | None = None) -> dict[str, Any]:
    """返回空布局结构。"""
    return {
        "version": "paper-layout.v1",
        "capability": PAPER_LAYOUT_CAPABILITY.descriptor(),
        "warnings": warnings or [],
        "pages": [],
        "regions": [],
    }


def _build_paper_layout(task: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    """从 OCR 产物构建父题级布局框。"""
    if not paper_layout_enabled():
        return empty_layout(["布局解析框已关闭"])
    job_id = str(job.get("jobId") or task.get("paperOcrJobId") or "").strip()
    upload_path = safe_source_path(job)
    if not job_id or upload_path is None:
        return empty_layout(["试卷原文件缺失，无法显示布局解析框"])

    output_dir = OUTPUT_ROOT / job_id
    pages_layout = paper_pages(task, job, upload_path)
    page_dimensions = {int(page["pageIndex"]): (float(page["width"]), float(page["height"])) for page in pages_layout["pages"]}
    warnings = list(pages_layout.get("warnings") or [])
    import_questions = [question for question in task.get("questions") or [] if isinstance(question, dict)]
    outputs = job.get("outputs") if isinstance(job.get("outputs"), dict) else {}
    source_questions = top_level_questions(outputs)
    source_lookup = source_question_lookup(source_questions)
    layout_items = load_question_layout_items(output_dir)
    indexed_layout_items = index_layout_items(layout_items, str(outputs.get("markdown") or "")) if outputs.get("markdown") else layout_items
    fallback_groups = sequential_question_item_groups(layout_items, len(layout_items))
    aligned_fallback_groups = align_layout_groups_to_source_questions(source_questions, fallback_groups)
    regions: list[dict[str, Any]] = []
    matched_count = 0
    for index, question in enumerate(import_questions, start=1):
        question_id = str(question.get("id") or "").strip()
        if not question_id:
            continue
        source_id = str(question.get("sourceQuestionId") or "").strip()
        source_question = source_lookup.get(source_id) if source_id else None
        display_index = parse_int(
            source_question.get("number") if isinstance(source_question, dict) else None,
            parse_int(question.get("number") or question.get("questionNumber"), index),
        )
        group_items = (
            items_for_question(indexed_layout_items, source_question.get("sourceEvidence"))
            if isinstance(source_question, dict)
            else []
        )
        if group_items:
            group_items = [item for item in group_items if should_include_in_question_region(item)]
        confidence = 0.96 if group_items else 0.88
        fallback_group = aligned_fallback_groups.get(source_id) if source_id else None
        if not fallback_group and not source_question and index - 1 < len(fallback_groups):
            fallback_group = fallback_groups[index - 1]
        if group_items and not question_region_items_are_reliable(group_items, question, source_question):
            group_items = []
            confidence = 0.88
        if not group_items and isinstance(fallback_group, dict):
            group_items = fallback_group.get("items") or []
            confidence = float(fallback_group.get("confidence") or confidence)
        if not group_items:
            continue
        matched_count += 1
        regions.extend(
            regions_for_items(
                group_items,
                page_dimensions,
                question_id=question_id,
                index=display_index,
                confidence=confidence,
            )
        )
    if not layout_items:
        warnings.append("OCR 未提供可用 bbox，未显示布局解析框")
    elif not fallback_groups and not regions:
        warnings.append("OCR bbox 未匹配到题目锚点，未显示布局解析框")
    elif not regions:
        warnings.append("OCR 题目 bbox 超出页面范围，未显示布局解析框")
    elif matched_count < len(import_questions):
        warnings.append(f"布局解析框仅匹配到 {matched_count}/{len(import_questions)} 道题，请人工复核未定位题目")

    return {
        **pages_layout,
        "warnings": warnings,
        "regions": regions,
    }


def paper_pages(task: dict[str, Any], job: dict[str, Any], upload_path: Path) -> dict[str, Any]:
    """返回试卷预览页元数据。"""
    job_id = str(job.get("jobId") or task.get("paperOcrJobId") or "").strip()
    version = layout_version(job)
    warnings: list[str] = []
    pages: list[dict[str, Any]] = []
    suffix = upload_path.suffix.lower()
    if suffix == ".pdf":
        page_sizes = pdf_preview_sizes(upload_path)
        if not page_sizes:
            warnings.append("无法渲染 PDF 页面，未显示布局解析框")
        for page_index, (width, height) in enumerate(page_sizes):
            pages.append(
                {
                    "pageIndex": page_index,
                    "width": width,
                    "height": height,
                    "previewUrl": f"/api/import-tasks/{task.get('id')}/source/paper/pages/{page_index}?v={version}",
                }
            )
    elif suffix in IMAGE_EXTENSIONS:
        try:
            with Image.open(upload_path) as image:
                width, height = image.size
            pages.append(
                {
                    "pageIndex": 0,
                    "width": width,
                    "height": height,
                    "previewUrl": f"/api/import-tasks/{task.get('id')}/source/paper/pages/0?v={version}",
                }
            )
        except Exception:
            warnings.append("无法读取试卷图片尺寸，未显示布局解析框")
    else:
        warnings.append("当前试卷文件类型暂不支持布局解析框预览")

    return {
        "version": "paper-layout.v1",
        "capability": PAPER_LAYOUT_CAPABILITY.descriptor(),
        "sourceVersion": version,
        "pages": pages,
        "warnings": warnings,
    }


def layout_version(job: dict[str, Any]) -> str:
    """返回布局内容版本指纹。"""
    payload = json.dumps(
        {
            "jobId": job.get("jobId"),
            "finishedAt": job.get("finishedAt"),
            "outputs": {
                "markdownFile": (job.get("outputs") or {}).get("markdownFile") if isinstance(job.get("outputs"), dict) else None,
                "jsonFile": (job.get("outputs") or {}).get("jsonFile") if isinstance(job.get("outputs"), dict) else None,
            },
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def safe_source_path(job: dict[str, Any]) -> Path | None:
    """返回安全的上传文件路径。"""
    target = Path(str(job.get("uploadPath") or "")).resolve()
    root = IMPORT_UPLOAD_ROOT.resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    if not target.exists() or not target.is_file():
        return None
    return target


def load_raw_layout_items(output_dir: Path) -> list[dict[str, Any]]:
    """读取 MinerU 原始 bbox 项，不拆行、不过滤、不关联题目。"""
    middle_items = load_middle_layout_items(output_dir)
    if middle_items:
        return middle_items

    items: list[dict[str, Any]] = []
    for path in sorted(output_dir.rglob("*_content_list.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for order, item in enumerate(data):
            if not isinstance(item, dict):
                continue
            bbox = normalize_bbox(item.get("bbox"))
            if not bbox:
                continue
            item_type = str(item.get("type") or "unknown").strip() or "unknown"
            items.append(
                {
                    "order": len(items),
                    "sourceOrder": order,
                    "type": item_type,
                    "text": item_text(item),
                    "imageRef": str(item.get("img_path") or item.get("image_path") or "").strip(),
                    "bbox": bbox,
                    "pageIndex": parse_int(item.get("page_idx"), 0),
                    "coordinateSource": "content_list",
                }
            )
    return items


def load_question_layout_items(output_dir: Path) -> list[dict[str, Any]]:
    """读取用于题目定位的布局项，优先使用与 PDF 页面同源的 middle 坐标。"""
    middle_items = load_middle_layout_items(output_dir)
    if middle_items:
        return sorted_layout_items(middle_items)
    return load_layout_items(output_dir)


def sorted_layout_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按页面几何阅读顺序排序并重写 order。"""
    sorted_items = sorted(items, key=layout_item_sort_key)
    for order, item in enumerate(sorted_items):
        item["order"] = order
    return sorted_items


def load_middle_layout_items(output_dir: Path) -> list[dict[str, Any]]:
    """读取 MinerU middle.json 中与 PDF 页面坐标同源的原始块。"""
    items: list[dict[str, Any]] = []
    for path in sorted(output_dir.rglob("*_middle.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        pdf_info = data.get("pdf_info")
        if not isinstance(pdf_info, list):
            continue
        for page_order, page in enumerate(pdf_info):
            if not isinstance(page, dict):
                continue
            page_size = middle_page_size(page.get("page_size"))
            page_index = parse_int(page.get("page_idx"), page_order)
            block_keys = ["para_blocks", "discarded_blocks"]
            if not any(isinstance(page.get(key), list) and page.get(key) for key in block_keys):
                block_keys = ["preproc_blocks"]
            for block_key in block_keys:
                blocks = page.get(block_key)
                if not isinstance(blocks, list):
                    continue
                for block_order, block in enumerate(blocks):
                    if not isinstance(block, dict):
                        continue
                    bbox = normalize_bbox(block.get("bbox"))
                    if not bbox:
                        continue
                    item_type = str(block.get("type") or "unknown").strip() or "unknown"
                    item = {
                        "order": len(items),
                        "sourceOrder": parse_int(block.get("index"), block_order),
                        "type": item_type,
                        "text": middle_block_text(block),
                        "imageRef": middle_block_image_ref(block),
                        "bbox": bbox,
                        "pageIndex": page_index,
                        "coordinateSource": "middle",
                        "blockSource": block_key,
                    }
                    if page_size:
                        item["pageWidth"], item["pageHeight"] = page_size
                    items.append(item)
    return items


def middle_page_size(value: Any) -> tuple[float, float] | None:
    """返回 middle.json 页面坐标尺寸。"""
    if not isinstance(value, list) or len(value) < 2:
        return None
    try:
        width, height = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def middle_block_text(block: dict[str, Any]) -> str:
    """提取 middle.json block 文本。"""
    direct = block.get("text") or block.get("content")
    if isinstance(direct, str):
        return direct.strip()
    lines = block.get("lines")
    if not isinstance(lines, list):
        return ""
    line_texts: list[str] = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        spans = line.get("spans")
        if not isinstance(spans, list):
            continue
        chunks: list[str] = []
        for span in spans:
            if not isinstance(span, dict):
                continue
            content = span.get("content") or span.get("text") or span.get("latex")
            if isinstance(content, str) and content.strip():
                chunks.append(content.strip())
        if chunks:
            line_texts.append("".join(chunks))
    return "\n".join(line_texts).strip()


def middle_block_image_ref(block: dict[str, Any]) -> str:
    """提取 middle.json block 的图片引用。"""
    nested = first_image_ref(block)
    if nested:
        return nested
    return ""


def first_image_ref(value: Any) -> str:
    """从 middle.json 的嵌套 image block/span 中提取图片路径。"""
    if isinstance(value, dict):
        for key in ("img_path", "image_path", "path"):
            ref = value.get(key)
            if isinstance(ref, str) and ref.strip():
                return ref.strip()
        content = value.get("content")
        if value.get("type") == "image" and isinstance(content, str) and content.strip():
            return content.strip()
        for key in ("blocks", "lines", "spans"):
            ref = first_image_ref(value.get(key))
            if ref:
                return ref
    if isinstance(value, list):
        for item in value:
            ref = first_image_ref(item)
            if ref:
                return ref
    return ""


def load_layout_items(output_dir: Path) -> list[dict[str, Any]]:
    """读取 OCR content_list 中的 bbox 项。"""
    items: list[dict[str, Any]] = []
    for path in sorted(output_dir.rglob("*_content_list.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for order, item in enumerate(data):
            if not isinstance(item, dict):
                continue
            bbox = normalize_bbox(item.get("bbox"))
            if not bbox:
                continue
            text = item_text(item)
            image_ref = str(item.get("img_path") or item.get("image_path") or "").strip()
            if not text and not image_ref:
                continue
            base_item = {
                "sourceOrder": order,
                "type": item.get("type"),
                "text": text,
                "imageRef": image_ref,
                "bbox": bbox,
                "pageIndex": parse_int(item.get("page_idx"), 0),
            }
            for expanded_item in expand_layout_item(base_item):
                expanded_item["order"] = len(items)
                items.append(expanded_item)
    sorted_items = sorted(items, key=layout_item_sort_key)
    for order, item in enumerate(sorted_items):
        item["order"] = order
    return sorted_items


def layout_item_sort_key(item: dict[str, Any]) -> tuple[int, float, float, int]:
    """返回页面几何阅读顺序。"""
    bbox = item.get("bbox")
    x0 = float(bbox[0]) if isinstance(bbox, list) and len(bbox) >= 4 else 0.0
    y0 = float(bbox[1]) if isinstance(bbox, list) and len(bbox) >= 4 else 0.0
    return (
        parse_int(item.get("pageIndex"), 0),
        y0,
        x0,
        parse_int(item.get("order"), 0),
    )


def expand_layout_item(item: dict[str, Any]) -> list[dict[str, Any]]:
    """把 MinerU 多行 text block 近似拆成行级 bbox。"""
    text = str(item.get("text") or "")
    bbox = item.get("bbox")
    if not text or "\n" not in text or not isinstance(bbox, list) or len(bbox) < 4:
        return [dict(item)]

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) <= 1:
        return [dict(item)]

    x0, y0, x1, y1 = [float(value) for value in bbox[:4]]
    line_height = (y1 - y0) / len(lines)
    expanded: list[dict[str, Any]] = []
    for line_index, line in enumerate(lines):
        line_item = dict(item)
        line_item["text"] = line
        line_item["lineIndex"] = line_index
        line_item["lineCount"] = len(lines)
        line_item["bbox"] = [
            x0,
            y0 + line_height * line_index,
            x1,
            y0 + line_height * (line_index + 1),
        ]
        expanded.append(line_item)
    return expanded


def normalize_bbox(value: Any) -> list[float] | None:
    """归一化 bbox。"""
    if not isinstance(value, list) or len(value) < 4:
        return None
    try:
        x0, y0, x1, y1 = [float(item) for item in value[:4]]
    except (TypeError, ValueError):
        return None
    if x1 <= x0 or y1 <= y0:
        return None
    return [x0, y0, x1, y1]


def item_text(item: dict[str, Any]) -> str:
    """提取 content_list 文本。"""
    text = item.get("text")
    if isinstance(text, str):
        return text.strip()
    return ""


def parse_int(value: Any, fallback: int) -> int:
    """安全 int。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def top_level_questions(outputs: dict[str, Any]) -> list[dict[str, Any]]:
    """返回 OCR 输出父题列表。"""
    questions: list[dict[str, Any]] = []
    for section in outputs.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for question in section.get("questions") or []:
            if isinstance(question, dict):
                questions.append(question)
    if questions:
        return questions
    return [question for question in outputs.get("questions") or [] if isinstance(question, dict)]


def source_question_lookup(source_questions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """按导入 sourceQuestionId 规则建立 OCR 父题映射。"""
    lookup: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    for index, question in enumerate(source_questions, start=1):
        base_id = str(question.get("id") or f"q_{index}").strip() or f"q_{index}"
        occurrence = counts.get(base_id, 0) + 1
        counts[base_id] = occurrence
        source_id = base_id if occurrence == 1 else f"{base_id}__occurrence_{occurrence}"
        lookup[source_id] = question
    return lookup


def align_layout_groups_to_source_questions(
    source_questions: list[dict[str, Any]],
    groups: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Align raw layout anchor groups to accepted OCR questions by question-number sequence."""
    source_numbers = [parse_int(question.get("number"), -1) for question in source_questions if isinstance(question, dict)]
    if not source_numbers or not groups:
        return {}

    best_start = -1
    best_length = 0
    best_non_preface = -1
    for start in range(len(groups)):
        length = 0
        while (
            length < len(source_numbers)
            and start + length < len(groups)
            and parse_int(groups[start + length].get("anchorNumber"), -1) == source_numbers[length]
        ):
            length += 1
        if length <= 0:
            continue
        non_preface = 0 if layout_group_looks_like_preface(groups[start]) else 1
        if length > best_length or (length == best_length and non_preface > best_non_preface):
            best_start = start
            best_length = length
            best_non_preface = non_preface

    if best_start < 0:
        return {}

    lookup: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    group_cursor = best_start
    for index, question in enumerate(source_questions, start=0):
        if not isinstance(question, dict):
            continue
        source_number = parse_int(question.get("number"), -1)
        matched_group_index = -1
        while group_cursor < len(groups):
            group_number = parse_int(groups[group_cursor].get("anchorNumber"), -1)
            if group_number == source_number:
                matched_group_index = group_cursor
                group_cursor += 1
                break
            if group_number > source_number:
                break
            group_cursor += 1
        if matched_group_index < 0:
            continue
        base_id = str(question.get("id") or f"q_{index + 1}").strip() or f"q_{index + 1}"
        occurrence = counts.get(base_id, 0) + 1
        counts[base_id] = occurrence
        source_id = base_id if occurrence == 1 else f"{base_id}__occurrence_{occurrence}"
        lookup[source_id] = groups[matched_group_index]
    return lookup


def layout_group_looks_like_preface(group: dict[str, Any]) -> bool:
    for item in group.get("items") or []:
        text = str(item.get("text") or "")
        if any(keyword in text for keyword in PREFACE_LAYOUT_KEYWORDS):
            return True
    return False


def index_layout_items(items: list[dict[str, Any]], markdown: str) -> list[dict[str, Any]]:
    """为 content_list item 建立 Markdown offset。"""
    cursor = 0
    indexed: list[dict[str, Any]] = []
    for item in items:
        indexed_item = dict(item)
        text = str(item.get("text") or "")
        image_ref = str(item.get("imageRef") or "")
        start = -1
        token_len = 0
        if text and should_index_layout_text(text):
            start = markdown.find(text, cursor)
            token_len = len(text)
            if start < 0 and len(text) > 24:
                start = markdown.find(text[:24], cursor)
                token_len = 24
        if start < 0 and image_ref:
            start = markdown.find(image_ref, cursor)
            token_len = len(image_ref)
        if start >= 0:
            indexed_item["start"] = start
            indexed_item["end"] = start + max(token_len, 1)
            cursor = max(cursor, indexed_item["end"])
        indexed.append(indexed_item)
    return indexed


def should_index_layout_text(text: str) -> bool:
    """判断 layout 文本是否适合作为 Markdown offset 锚点。"""
    stripped = text.strip()
    if not stripped:
        return False
    if OPTION_LABEL_TOKEN_RE.match(stripped):
        return False
    return True


def question_region_items_are_reliable(
    items: list[dict[str, Any]],
    import_question: dict[str, Any],
    source_question: dict[str, Any] | None,
) -> bool:
    """过滤只命中选项小标签等明显不完整的布局匹配。"""
    if not items:
        return False
    image_ref_count = sum(1 for item in items if str(item.get("imageRef") or "").strip())
    expected_images = expected_question_image_count(import_question, source_question)
    if expected_images and image_ref_count == 0:
        return False
    expected_text_length = expected_question_text_length(import_question, source_question)
    if len(items) == 1:
        item = items[0]
        if str(item.get("imageRef") or "").strip():
            return expected_text_length <= 12
        if question_anchor_number(item) is not None:
            return True
        compact = re.sub(r"\s+", "", str(item.get("text") or ""))
        if len(compact) <= 6:
            return False
    return True


def expected_question_image_count(import_question: dict[str, Any], source_question: dict[str, Any] | None) -> int:
    """优先使用导入题目的最终图片数判断布局覆盖率。"""
    import_images = import_question.get("images") if isinstance(import_question, dict) else None
    if isinstance(import_images, list):
        return len(import_images)
    source_images = source_question.get("images") if isinstance(source_question, dict) else None
    if isinstance(source_images, list):
        return len(source_images)
    return 0


def expected_question_text_length(import_question: dict[str, Any], source_question: dict[str, Any] | None) -> int:
    """返回题干文本长度，用于判断 image-only 布局是否过窄。"""
    for question in (import_question, source_question):
        if not isinstance(question, dict):
            continue
        for key in ("stemMarkdown", "manualMarkdown", "stem", "title"):
            value = question.get(key)
            if isinstance(value, str) and value.strip():
                return len(re.sub(r"\s+", "", value))
    return 0


def items_for_question(items: list[dict[str, Any]], evidence: Any) -> list[dict[str, Any]]:
    """根据 sourceEvidence 选出题目 blocks。"""
    if not isinstance(evidence, dict):
        return []
    try:
        start = int(evidence.get("start"))
        end = int(evidence.get("end"))
    except (TypeError, ValueError):
        return []
    if end <= start:
        return []
    direct = [
        item
        for item in items
        if isinstance(item.get("start"), int)
        and isinstance(item.get("end"), int)
        and item["end"] > start
        and item["start"] < end
    ]
    if not direct:
        return []
    min_order = min(int(item["order"]) for item in direct)
    max_order = max(int(item["order"]) for item in direct)
    return [item for item in items if min_order <= int(item["order"]) <= max_order]


def anchor_items_for_question(items: list[dict[str, Any]], evidence: Any) -> list[dict[str, Any]]:
    """根据 sourceEvidence 兜底定位单个题干锚点 block。"""
    direct = items_for_question(items, evidence)
    for item in direct:
        if question_anchor_number(item) is not None:
            return [item]
    for item in direct:
        text = str(item.get("text") or "").strip()
        if text and not str(item.get("imageRef") or "").strip() and should_include_in_question_region(item):
            return [item]
    return []


def items_for_number(items: list[dict[str, Any]], number: Any) -> list[dict[str, Any]]:
    """按题号前缀兜底定位单个题目 block。"""
    number_text = str(number or "").strip()
    if not number_text:
        return []
    prefix_options = (f"{number_text}.", f"{number_text}．", f"{number_text}、")
    for item in items:
        text = str(item.get("text") or "").lstrip()
        if any(text.startswith(prefix) for prefix in prefix_options):
            return [item]
    return []


def sequential_question_item_groups(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """按 MinerU 页面顺序和题号锚点切出每道题的布局 items。"""
    if limit <= 0:
        return []
    anchors: list[int] = []
    for item_index, item in enumerate(items):
        if question_anchor_number(item) is not None:
            anchors.append(item_index)
    if not anchors:
        return []

    groups: list[dict[str, Any]] = []
    for anchor_offset, start_index in enumerate(anchors):
        end_index = anchors[anchor_offset + 1] if anchor_offset + 1 < len(anchors) else len(items)
        span_items = [
            item
            for item in items[start_index:end_index]
            if should_include_in_question_region(item)
        ]
        if not span_items:
            continue
        if layout_group_looks_like_preface({"items": span_items}):
            continue
        groups.append(
            {
                "items": span_items,
                "anchorNumber": question_anchor_number(items[start_index]),
                "confidence": 0.94,
            }
        )
        if len(groups) >= limit:
            break
    return groups


def sequential_question_anchor_groups(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """按 MinerU 页面顺序返回每道题的题干锚点 item。"""
    if limit <= 0:
        return []
    groups: list[dict[str, Any]] = []
    for item in items:
        anchor_number = question_anchor_number(item)
        if anchor_number is None:
            continue
        if not should_include_in_question_region(item):
            continue
        groups.append(
            {
                "items": [item],
                "anchorNumber": anchor_number,
                "confidence": 0.96,
            }
        )
        if len(groups) >= limit:
            break
    return groups


def _question_image_refs_by_layout(output_dir: Path, limit: int) -> list[list[str]]:
    """按 MinerU 几何 bbox 返回每道题应关联的图片引用。"""
    return [group["imageRefs"] for group in _question_image_ref_groups_by_layout(output_dir, limit)]


def _question_image_ref_groups_by_layout(output_dir: Path, limit: int) -> list[dict[str, Any]]:
    """按 MinerU 几何 bbox 返回每道题应关联的图片引用和题号锚点。"""
    items = load_layout_items(output_dir)
    groups = sequential_question_item_groups(items, limit)
    result: list[dict[str, Any]] = []
    for group in groups:
        refs: list[str] = []
        seen: set[str] = set()
        for item in group.get("items") or []:
            image_ref = str(item.get("imageRef") or "").strip()
            if not image_ref or image_ref in seen:
                continue
            seen.add(image_ref)
            refs.append(image_ref)
        result.append(
            {
                "anchorNumber": group.get("anchorNumber"),
                "imageRefs": refs,
            }
        )
    return result


def question_anchor_number(item: dict[str, Any]) -> int | None:
    """返回题号锚点；布局框只用锚点顺序，不用该数字覆盖平台编号。"""
    text = str(item.get("text") or "").strip()
    if not text:
        return None
    match = QUESTION_ANCHOR_RE.match(text)
    if not match:
        return None
    try:
        return int(match.group("number"))
    except (TypeError, ValueError):
        return None


def should_include_in_question_region(item: dict[str, Any]) -> bool:
    """过滤页码、卷面标题等不属于题目范围的块。"""
    text = str(item.get("text") or "").strip()
    image_ref = str(item.get("imageRef") or "").strip()
    if image_ref:
        return True
    if not text:
        return False
    if is_page_noise(text):
        return False
    if is_non_question_title(item, text):
        return False
    return True


def raw_regions_for_items(
    items: list[dict[str, Any]],
    page_dimensions: dict[int, tuple[float, float]],
) -> list[dict[str, Any]]:
    """把 MinerU 原始 bbox 逐条转换成前端 region。"""
    regions: list[dict[str, Any]] = []
    for item in items:
        page_index = parse_int(item.get("pageIndex"), 0)
        dims = page_dimensions.get(page_index)
        bbox = item.get("bbox")
        if not dims or not isinstance(bbox, list) or len(bbox) < 4:
            continue
        width = float(item.get("pageWidth") or dims[0])
        height = float(item.get("pageHeight") or dims[1])
        if width <= 0 or height <= 0:
            continue
        left = clamp(float(bbox[0]) / width)
        top = clamp(float(bbox[1]) / height)
        right = clamp(float(bbox[2]) / width)
        bottom = clamp(float(bbox[3]) / height)
        if right <= left or bottom <= top:
            continue
        text = str(item.get("text") or "").strip()
        regions.append(
            {
                "questionId": "",
                "index": parse_int(item.get("order"), len(regions)) + 1,
                "pageIndex": page_index,
                "x": round(left, 6),
                "y": round(top, 6),
                "w": round(right - left, 6),
                "h": round(bottom - top, 6),
                "confidence": 1.0,
                "source": "mineru_raw",
                "type": str(item.get("type") or "unknown"),
                "text": text[:120],
                "coordinateSource": str(item.get("coordinateSource") or "unknown"),
            }
        )
    return regions


def is_page_noise(text: str) -> bool:
    """判断页码类噪声。"""
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return True
    if compact in {"试卷", "答案", "答题卡"}:
        return True
    return bool(PAGE_NOISE_RE.match(compact))


def is_non_question_title(item: dict[str, Any], text: str) -> bool:
    """过滤不以题号开头的章节/试卷标题。"""
    if question_anchor_number(item) is not None:
        return False
    item_type = str(item.get("type") or "").lower()
    if item_type == "title":
        return True
    return any(keyword in text for keyword in SECTION_TITLE_KEYWORDS)


def regions_for_items(
    items: list[dict[str, Any]],
    page_dimensions: dict[int, tuple[float, float]],
    *,
    question_id: str,
    index: int,
    confidence: float = 0.9,
) -> list[dict[str, Any]]:
    """把同一道题的 bbox 合并为每页一个 region。"""
    regions: list[dict[str, Any]] = []
    by_page: dict[int, list[tuple[list[float], float, float, str]]] = {}
    for item in items:
        page_index = parse_int(item.get("pageIndex"), 0)
        bbox = item.get("bbox")
        if isinstance(bbox, list) and len(bbox) >= 4:
            dims = coordinate_dimensions_for_item(item, page_dimensions)
            if not dims:
                continue
            width, height = dims
            by_page.setdefault(page_index, []).append((bbox, width, height, str(item.get("coordinateSource") or "unknown")))
    for page_index in sorted(by_page):
        entries = by_page[page_index]
        if not entries:
            continue
        width, height = entries[0][1], entries[0][2]
        if width <= 0 or height <= 0:
            continue
        boxes = [entry[0] for entry in entries]
        x0 = min(box[0] for box in boxes)
        y0 = min(box[1] for box in boxes)
        x1 = max(box[2] for box in boxes)
        y1 = max(box[3] for box in boxes)
        pad_x = width * LAYOUT_PADDING_RATIO
        pad_y = height * LAYOUT_PADDING_RATIO
        left = clamp((x0 - pad_x) / width)
        top = clamp((y0 - pad_y) / height)
        right = clamp((x1 + pad_x) / width)
        bottom = clamp((y1 + pad_y) / height)
        if right <= left or bottom <= top:
            continue
        regions.append(
            {
                "questionId": question_id,
                "index": index,
                "pageIndex": page_index,
                "x": round(left, 6),
                "y": round(top, 6),
                "w": round(right - left, 6),
                "h": round(bottom - top, 6),
                "confidence": round(confidence, 2),
                "source": "mineru_question",
                "coordinateSource": entries[0][3],
            }
        )
    return regions


def coordinate_dimensions_for_item(
    item: dict[str, Any],
    page_dimensions: dict[int, tuple[float, float]],
) -> tuple[float, float] | None:
    """返回 bbox 所属坐标系尺寸。"""
    page_index = parse_int(item.get("pageIndex"), 0)
    dims = page_dimensions.get(page_index)
    if not dims:
        return None
    try:
        width = float(item.get("pageWidth") or dims[0])
        height = float(item.get("pageHeight") or dims[1])
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def clamp(value: float) -> float:
    """约束到 0-1。"""
    return max(0.0, min(1.0, value))


def pdf_preview_sizes(path: Path) -> list[tuple[int, int]]:
    """返回 PDF 按布局预览 scale 渲染后的页面尺寸。"""
    try:
        import pypdfium2 as pdfium
    except Exception:
        return []
    try:
        pdf = pdfium.PdfDocument(str(path))
        sizes: list[tuple[int, int]] = []
        for index in range(len(pdf)):
            page = pdf[index]
            sizes.append((int(math.ceil(page.get_width() * PDF_RENDER_SCALE)), int(math.ceil(page.get_height() * PDF_RENDER_SCALE))))
        return sizes
    except Exception:
        return []


def _render_source_page(task: dict[str, Any], job: dict[str, Any], page_index: int) -> FileResponse:
    """渲染并返回试卷页面图片。"""
    upload_path = safe_source_path(job)
    if upload_path is None:
        raise HTTPException(status_code=404, detail="Source file not found")
    if page_index < 0:
        raise HTTPException(status_code=404, detail="Page not found")

    suffix = upload_path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        if page_index != 0:
            raise HTTPException(status_code=404, detail="Page not found")
        return FileResponse(upload_path, media_type=None, filename=upload_path.name, content_disposition_type="inline")
    if suffix != ".pdf":
        raise HTTPException(status_code=415, detail="Only paper images and PDFs support layout page preview")

    page_path = preview_page_path(str(job.get("jobId") or task.get("paperOcrJobId")), page_index)
    if not page_path.exists():
        render_pdf_page(upload_path, page_index, page_path)
    return FileResponse(page_path, media_type="image/png", filename=page_path.name, content_disposition_type="inline")


def preview_page_path(job_id: str, page_index: int) -> Path:
    """返回缓存页图路径。"""
    target = OUTPUT_ROOT / str(job_id) / "paper_preview_pages" / f"page_{page_index + 1}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def render_pdf_page(source: Path, page_index: int, target: Path) -> None:
    """将 PDF 指定页渲染为 PNG。"""
    try:
        import pypdfium2 as pdfium
    except Exception as exc:
        raise HTTPException(status_code=500, detail="pypdfium2 不可用，无法渲染 PDF 页面") from exc
    try:
        pdf = pdfium.PdfDocument(str(source))
        if page_index >= len(pdf):
            raise HTTPException(status_code=404, detail="Page not found")
        page = pdf[page_index]
        bitmap = page.render(scale=PDF_RENDER_SCALE)
        image = bitmap.to_pil().convert("RGB")
        image.save(target)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF 页面渲染失败：{exc}") from exc
