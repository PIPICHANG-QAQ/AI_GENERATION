"""视觉证据修复。

本模块只做低置信题目的题目级 crop、横线检测和可选二次 OCR。它不让
Pix2Text 或其它备用 OCR 覆盖高置信主链路结果。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from app.question_markdown import (
    is_fill_blank_markdown,
    normalize_fill_blank_markdown,
)


QUESTION_NUMBER_PREFIX_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(\d{1,3})[\.．、]\s*")
TRACEBACK_RE = re.compile(r"traceback|exception|error:", re.I)


class VisualRepairScratchError(ValueError):
    """Raised when visual-repair scratch storage is not a safe real directory."""


def build_postprocess_scratch_dir(postprocess_root: Path, document_id: str) -> Path:
    """Create a contained job scratch directory without using documentId as a path component."""
    if postprocess_root.is_symlink():
        raise VisualRepairScratchError("postprocess scratch root must not be a symlink")
    postprocess_root.mkdir(parents=True, exist_ok=True)
    if postprocess_root.is_symlink() or not postprocess_root.is_dir():
        raise VisualRepairScratchError("postprocess scratch root must be a real directory")
    resolved_root = postprocess_root.resolve(strict=True)
    digest = hashlib.sha256(document_id.encode("utf-8")).hexdigest()
    job_dir = postprocess_root / f"job-{digest}"
    if job_dir.is_symlink():
        raise VisualRepairScratchError("postprocess scratch job directory must not be a symlink")
    job_dir.mkdir(exist_ok=True)
    if job_dir.is_symlink() or not job_dir.is_dir():
        raise VisualRepairScratchError("postprocess scratch job path must be a real directory")
    resolved_job_dir = job_dir.resolve(strict=True)
    try:
        resolved_job_dir.relative_to(resolved_root)
    except ValueError as exc:
        raise VisualRepairScratchError("postprocess scratch job directory escapes its root") from exc
    return resolved_job_dir


def safe_scratch_child_directory(root: Path, name: str) -> Path:
    """Create one real child directory and validate that it stays inside root."""
    if root.is_symlink() or not root.is_dir():
        raise VisualRepairScratchError("visual repair scratch root must be a real directory")
    resolved_root = root.resolve(strict=True)
    child = root / name
    if child.is_symlink():
        raise VisualRepairScratchError(f"visual repair scratch component must not be a symlink: {name}")
    child.mkdir(exist_ok=True)
    if child.is_symlink() or not child.is_dir():
        raise VisualRepairScratchError(f"visual repair scratch component must be a real directory: {name}")
    resolved_child = child.resolve(strict=True)
    try:
        resolved_child.relative_to(resolved_root)
    except ValueError as exc:
        raise VisualRepairScratchError(f"visual repair scratch component escapes its root: {name}") from exc
    return resolved_child


def save_crop_without_following_symlinks(crop: Image.Image, crop_path: Path) -> None:
    """Atomically replace a real crop file without ever writing through a symlink target."""
    if crop_path.is_symlink():
        raise VisualRepairScratchError(f"visual repair crop target must not be a symlink: {crop_path.name}")
    temporary = crop_path.parent / f".{crop_path.name}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as file:
            descriptor = -1
            crop.save(file, format="PNG")
        if crop_path.is_symlink():
            raise VisualRepairScratchError(f"visual repair crop target must not be a symlink: {crop_path.name}")
        os.replace(temporary, crop_path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def apply_visual_repairs(
    structured: dict[str, Any],
    output_dir: Path,
    upload_path: str | Path | None,
    job_id: str,
    context: dict[str, Any] | None = None,
    scratch_dir: Path | Callable[[], Path] | None = None,
) -> dict[str, Any]:
    """对结构化题目应用题目级视觉修复。"""
    if os.getenv("OCR_VISUAL_REPAIR_ENABLED", "true").lower() == "false":
        return {"enabled": False, "skippedReason": "OCR_VISUAL_REPAIR_ENABLED=false"}

    if isinstance(context, dict) and ("visualItems" in context or "pageSizes" in context):
        repair_context = context
    else:
        repair_context = prepare_visual_repair_context(output_dir, upload_path)
        if isinstance(context, dict):
            repair_context["warnings"] = [*(context.get("warnings") or []), *(repair_context.get("warnings") or [])]
    visual_items = repair_context.get("visualItems") or []
    page_sizes = repair_context.get("pageSizes") or {}
    questions = list(iter_parent_questions(structured))
    candidates = [
        (index, question)
        for index, question in enumerate(questions)
        if question_needs_visual_repair(question)
    ]
    max_workers = min(
        clamped_int_env("OCR_VISUAL_REPAIR_MAX_CONCURRENCY", 2, 1, 8),
        max(1, len(candidates)),
    )
    summary: dict[str, Any] = {
        "enabled": True,
        "questionCount": len(questions),
        "candidateCount": len(candidates),
        "cropCount": 0,
        "underlineCount": 0,
        "placeholderRepairCount": 0,
        "maxConcurrency": max_workers,
        "preprocessed": {
            "used": bool(context),
            "visualItemCount": len(visual_items),
            "pageSizeCount": len(page_sizes),
            "preloadedPageCount": len(repair_context.get("pageImages") or {}),
        },
        "secondaryOcr": {
            "configured": pix2text_configured(),
            "attempted": 0,
            "applied": 0,
            "failed": 0,
        },
        "warnings": list(repair_context.get("warnings") or []),
    }

    if not candidates:
        return summary

    selected_scratch_dir = scratch_dir() if callable(scratch_dir) else scratch_dir
    crop_root = (selected_scratch_dir or output_dir).resolve(strict=True)
    crop_dir = crop_root / "visual_repair"
    crop_dir = safe_scratch_child_directory(crop_root, "visual_repair")
    for index, question in candidates:
        crop_path = crop_dir / f"{index:03d}_{safe_crop_name(question)}.png"
        if crop_path.is_symlink():
            raise VisualRepairScratchError(
                f"visual repair crop target must not be a symlink: {crop_path.name}"
            )

    if max_workers > 1 and len(candidates) > 1:
        results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(repair_visual_question, index, question, repair_context, upload_path, crop_root, crop_dir)
                for index, question in candidates
            ]
            for future in as_completed(futures):
                results.append(future.result())
    else:
        results = [
            repair_visual_question(index, question, repair_context, upload_path, crop_root, crop_dir)
            for index, question in candidates
        ]

    for result in sorted(results, key=lambda item: int(item.get("index") or 0)):
        question = result["question"]
        for key, value in (result.get("updates") or {}).items():
            question[key] = value
        attach_visual_repair(question, result.get("repairRecord") or {"status": "failed", "error": "missing repair result"})
        summary["cropCount"] += int(result.get("cropCount") or 0)
        summary["underlineCount"] += int(result.get("underlineCount") or 0)
        summary["placeholderRepairCount"] += int(result.get("placeholderRepairCount") or 0)
        summary["secondaryOcr"]["attempted"] += int((result.get("secondaryOcr") or {}).get("attempted") or 0)
        summary["secondaryOcr"]["applied"] += int((result.get("secondaryOcr") or {}).get("applied") or 0)
        summary["secondaryOcr"]["failed"] += int((result.get("secondaryOcr") or {}).get("failed") or 0)
        summary["warnings"].extend(result.get("warnings") or [])
    return summary


def prepare_visual_repair_context(output_dir: Path, upload_path: str | Path | None) -> dict[str, Any]:
    """只读准备视觉修复所需索引和有限页图像缓存。"""
    warnings: list[str] = []
    visual_items = load_visual_items(output_dir)
    page_sizes = load_page_sizes(output_dir)
    page_images = preload_visual_page_images(upload_path, visual_items, page_sizes, warnings)
    return {
        "visualItems": visual_items,
        "pageSizes": page_sizes,
        "itemNumberIndex": build_visual_item_number_index(visual_items),
        "pageImages": page_images,
        "warnings": warnings,
    }


def prepare_canonical_visual_repair_context(
    layout_items: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    upload_path: str | Path | None,
) -> dict[str, Any]:
    """Build visual-repair evidence only from declared canonical layout and pages."""
    warnings: list[str] = []
    visual_items: list[dict[str, Any]] = []
    page_sizes: dict[int, tuple[float, float]] = {}
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_index = parse_int(page.get("pageIndex"), 0)
        try:
            width = float(page.get("width") or 0)
            height = float(page.get("height") or 0)
        except (TypeError, ValueError):
            continue
        if width > 0 and height > 0:
            page_sizes[page_index] = (width, height)

    for item in layout_items:
        if not isinstance(item, dict):
            continue
        bbox = normalize_bbox(item.get("bbox"))
        text = str(item.get("text") or "").strip()
        if bbox and text:
            visual_items.append(
                {
                    "text": text,
                    "bbox": bbox,
                    "page_idx": parse_int(item.get("pageIndex"), 0),
                    "source": "canonical-layout",
                }
            )
        if item.get("pageWidth") is not None and item.get("pageHeight") is not None:
            try:
                width = float(item["pageWidth"])
                height = float(item["pageHeight"])
            except (TypeError, ValueError):
                continue
            if width > 0 and height > 0:
                page_sizes.setdefault(parse_int(item.get("pageIndex"), 0), (width, height))

    page_images = preload_visual_page_images(upload_path, visual_items, page_sizes, warnings) if visual_items else {}
    return {
        "visualItems": visual_items,
        "pageSizes": page_sizes,
        "itemNumberIndex": build_visual_item_number_index(visual_items),
        "pageImages": page_images,
        "warnings": warnings,
    }


def repair_visual_question(
    index: int,
    question: dict[str, Any],
    repair_context: dict[str, Any],
    upload_path: str | Path | None,
    crop_root: Path,
    crop_dir: Path,
) -> dict[str, Any]:
    """计算单题视觉修复结果，不直接写回原题。"""
    result: dict[str, Any] = {
        "index": index,
        "question": question,
        "updates": {},
        "cropCount": 0,
        "underlineCount": 0,
        "placeholderRepairCount": 0,
        "secondaryOcr": {"attempted": 0, "applied": 0, "failed": 0},
        "warnings": [],
    }
    try:
        visual_items = repair_context.get("visualItems") or []
        page_sizes = repair_context.get("pageSizes") or {}
        item = find_visual_item_for_question(question, visual_items, repair_context.get("itemNumberIndex") or {})
        if not item:
            result["warnings"].append(f"{question.get('id')} 未找到题目 bbox，跳过视觉修复")
            result["repairRecord"] = {"status": "skipped", "reason": "missing_bbox"}
            return result

        crop = crop_question_image(upload_path, item, page_sizes, repair_context.get("pageImages") or {})
        if crop is None:
            result["warnings"].append(f"{question.get('id')} 无法生成题目 crop")
            result["repairRecord"] = {"status": "skipped", "reason": "crop_unavailable"}
            return result

        crop_path = crop_dir / f"{index:03d}_{safe_crop_name(question)}.png"
        save_crop_without_following_symlinks(crop, crop_path)
        result["cropCount"] = 1

        underlines = detect_underline_segments(crop)
        result["underlineCount"] = len(underlines)
        repair_record: dict[str, Any] = {
            "status": "checked",
            "cropPath": crop_path.relative_to(crop_root).as_posix(),
            "pageIndex": item.get("page_idx"),
            "bbox": item.get("bbox"),
            "underlineCount": len(underlines),
            "underlines": underlines[:20],
        }

        secondary_text, secondary_error = run_secondary_ocr(crop_path)
        if secondary_text or secondary_error:
            result["secondaryOcr"]["attempted"] = 1
            repair_record["secondaryOcr"] = {
                "provider": "pix2text",
                "applied": False,
                "error": secondary_error,
                "markdown": secondary_text,
            }
            if secondary_error:
                result["secondaryOcr"]["failed"] = 1

        working_question = dict(question)
        applied_secondary = False
        if secondary_text and should_apply_secondary_ocr(working_question, secondary_text):
            apply_secondary_ocr(working_question, secondary_text)
            repair_record["secondaryOcr"]["applied"] = True
            result["secondaryOcr"]["applied"] = 1
            applied_secondary = True

        if not applied_secondary:
            added = apply_underline_placeholders(working_question, len(underlines))
            if added:
                repair_record["placeholderAdded"] = added
                result["placeholderRepairCount"] = added

        for key in ("type", "stemMarkdown", "manualMarkdown"):
            if working_question.get(key) != question.get(key):
                result["updates"][key] = working_question.get(key)
        result["repairRecord"] = repair_record
    except Exception as exc:  # pragma: no cover - 单题修复不能中断 OCR 任务
        result["warnings"].append(f"{question.get('id')} 视觉修复失败：{exc}")
        result["repairRecord"] = {"status": "failed", "error": str(exc)}
    return result


def load_visual_items(output_dir: Path) -> list[dict[str, Any]]:
    """读取 MinerU content_list 中的题目 bbox。"""
    items: list[dict[str, Any]] = []
    for path in sorted(output_dir.rglob("*_content_list.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for item in data:
            if not isinstance(item, dict) or not item.get("bbox"):
                continue
            text = item_text(item)
            if not text:
                continue
            items.append(
                {
                    "text": text,
                    "bbox": normalize_bbox(item.get("bbox")),
                    "page_idx": parse_int(item.get("page_idx"), 0),
                    "source": path.name,
                }
            )
    return [item for item in items if item["bbox"]]


def load_page_sizes(output_dir: Path) -> dict[int, tuple[float, float]]:
    """读取 MinerU middle.json 中的页面尺寸。"""
    sizes: dict[int, tuple[float, float]] = {}
    for path in sorted(output_dir.rglob("*_middle.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        pdf_info = data.get("pdf_info") if isinstance(data, dict) else None
        if not isinstance(pdf_info, list):
            continue
        for page in pdf_info:
            if not isinstance(page, dict) or not isinstance(page.get("page_size"), list):
                continue
            page_idx = parse_int(page.get("page_idx"), len(sizes))
            page_size = page.get("page_size") or []
            if len(page_size) >= 2:
                sizes[page_idx] = (float(page_size[0]), float(page_size[1]))
    return sizes


def build_visual_item_number_index(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """按题号建立 content_list bbox 索引。"""
    index: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        match = QUESTION_NUMBER_PREFIX_RE.match(item.get("text") or "")
        if match:
            index.setdefault(match.group(1), []).append(item)
    return index


def preload_visual_page_images(
    upload_path: str | Path | None,
    visual_items: list[dict[str, Any]],
    page_sizes: dict[int, tuple[float, float]],
    warnings: list[str],
) -> dict[int, tuple[Image.Image, tuple[float, float]]]:
    """提前加载有限页图像，避免视觉修复节点重复打开或渲染页面。"""
    if os.getenv("OCR_VISUAL_REPAIR_PRELOAD_ENABLED", "true").lower() == "false":
        return {}
    path = Path(str(upload_path or ""))
    if not path.exists():
        return {}
    max_pages = clamped_int_env("OCR_VISUAL_REPAIR_PRELOAD_MAX_PAGES", 4, 0, 32)
    if max_pages <= 0:
        return {}

    suffix = path.suffix.lower()
    page_images: dict[int, tuple[Image.Image, tuple[float, float]]] = {}
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}:
        try:
            with Image.open(path) as source:
                image = source.convert("RGB")
            page_images[0] = (image, page_sizes.get(0) or image.size)
        except Exception as exc:
            warnings.append(f"视觉修复预加载图片失败：{exc}")
        return page_images

    if suffix != ".pdf":
        return {}

    page_indices = sorted({parse_int(item.get("page_idx"), 0) for item in visual_items})[:max_pages]
    for page_idx in page_indices:
        page_image, page_size = render_pdf_page(path, page_idx, page_sizes.get(page_idx))
        if page_image is not None:
            page_images[page_idx] = (page_image, page_size)
        else:
            warnings.append(f"视觉修复预加载 PDF 第 {page_idx + 1} 页失败")
    return page_images


def item_text(item: dict[str, Any]) -> str:
    text = item.get("text")
    if isinstance(text, str):
        return text.strip()
    return ""


def normalize_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) < 4:
        return None
    try:
        x0, y0, x1, y1 = [float(v) for v in value[:4]]
    except (TypeError, ValueError):
        return None
    if x1 <= x0 or y1 <= y0:
        return None
    return [x0, y0, x1, y1]


def iter_parent_questions(structured: dict[str, Any]):
    seen: set[int] = set()
    for section in structured.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for question in section.get("questions") or []:
            if isinstance(question, dict) and id(question) not in seen:
                seen.add(id(question))
                yield question


def question_needs_visual_repair(question: dict[str, Any]) -> bool:
    if question.get("options"):
        return False
    if question.get("subQuestions") or question.get("children"):
        return False
    text = str(question.get("stemMarkdown") or question.get("manualMarkdown") or "")
    question_type = str(question.get("type") or "")
    return question_type == "fill_blank" or is_fill_blank_markdown(text)


def find_visual_item_for_question(
    question: dict[str, Any],
    items: list[dict[str, Any]],
    item_number_index: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any] | None:
    number = str(question.get("number") or "").strip()
    if number and item_number_index:
        indexed_items = item_number_index.get(number) or []
        if indexed_items:
            return indexed_items[0]
    if number:
        for item in items:
            match = QUESTION_NUMBER_PREFIX_RE.match(item.get("text") or "")
            if match and match.group(1) == number:
                return item
    stem_key = normalize_match_text(str(question.get("stemMarkdown") or ""))[:24]
    if stem_key:
        for item in items:
            if stem_key and stem_key in normalize_match_text(item.get("text") or ""):
                return item
    return None


def crop_question_image(
    upload_path: str | Path | None,
    item: dict[str, Any],
    page_sizes: dict[int, tuple[float, float]],
    page_images: dict[int, tuple[Image.Image, tuple[float, float]]] | None = None,
) -> Image.Image | None:
    path = Path(str(upload_path or ""))
    if not path.exists():
        return None
    bbox = item.get("bbox")
    if not isinstance(bbox, list) or len(bbox) < 4:
        return None
    page_idx = parse_int(item.get("page_idx"), 0)
    cached = (page_images or {}).get(page_idx)
    if cached:
        return crop_with_scaled_bbox(cached[0], bbox, cached[1])
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}:
        with Image.open(path) as source:
            image = source.convert("RGB")
        page_size = page_sizes.get(page_idx) or image.size
        return crop_with_scaled_bbox(image, bbox, page_size)
    if suffix == ".pdf":
        page_image, page_size = render_pdf_page(path, page_idx, page_sizes.get(page_idx))
        if page_image is None:
            return None
        return crop_with_scaled_bbox(page_image, bbox, page_size)
    return None


def render_pdf_page(
    path: Path,
    page_idx: int,
    page_size_hint: tuple[float, float] | None,
) -> tuple[Image.Image | None, tuple[float, float]]:
    try:
        import pypdfium2 as pdfium
    except Exception:
        return None, page_size_hint or (0.0, 0.0)
    try:
        pdf = pdfium.PdfDocument(str(path))
        page = pdf[page_idx]
        scale = float(os.getenv("OCR_VISUAL_REPAIR_PDF_RENDER_SCALE", "2.0"))
        bitmap = page.render(scale=scale)
        image = bitmap.to_pil().convert("RGB")
        page_size = page_size_hint or (image.width / scale, image.height / scale)
        return image, page_size
    except Exception:
        return None, page_size_hint or (0.0, 0.0)


def crop_with_scaled_bbox(
    image: Image.Image,
    bbox: list[float],
    page_size: tuple[float, float],
) -> Image.Image:
    page_width, page_height = page_size
    scale_x = image.width / page_width if page_width else 1.0
    scale_y = image.height / page_height if page_height else 1.0
    padding = int(os.getenv("OCR_VISUAL_REPAIR_CROP_PADDING", "12"))
    x0 = max(0, int(bbox[0] * scale_x) - padding)
    y0 = max(0, int(bbox[1] * scale_y) - padding)
    x1 = min(image.width, int(bbox[2] * scale_x) + padding)
    y1 = min(image.height, int(bbox[3] * scale_y) + padding)
    return image.crop((x0, y0, max(x1, x0 + 1), max(y1, y0 + 1))).copy()


def detect_underline_segments(image: Image.Image) -> list[dict[str, int]]:
    """用纯 PIL 扫描题目 crop 中的长横线。"""
    gray = image.convert("L")
    width, height = gray.size
    dark_threshold = int(os.getenv("OCR_VISUAL_REPAIR_DARK_THRESHOLD", "175"))
    min_run = max(
        int(os.getenv("OCR_VISUAL_REPAIR_MIN_UNDERLINE_PX", "36")),
        int(width * float(os.getenv("OCR_VISUAL_REPAIR_MIN_UNDERLINE_WIDTH_RATIO", "0.12"))),
    )
    rows: list[dict[str, int]] = []
    pixels = gray.tobytes()
    for y in range(height):
        row = pixels[y * width : (y + 1) * width]
        start: int | None = None
        for x, value in enumerate(row):
            if value < dark_threshold:
                if start is None:
                    start = x
                continue
            if start is not None and x - start >= min_run:
                rows.append({"x0": start, "x1": x, "y0": y, "y1": y + 1})
            start = None
        if start is not None and width - start >= min_run:
            rows.append({"x0": start, "x1": width, "y0": y, "y1": y + 1})

    merged = merge_underline_rows(rows)
    max_height = int(os.getenv("OCR_VISUAL_REPAIR_MAX_UNDERLINE_HEIGHT", "8"))
    return [
        item
        for item in merged
        if item["x1"] - item["x0"] >= min_run and item["y1"] - item["y0"] <= max_height
    ]


def merge_underline_rows(rows: list[dict[str, int]]) -> list[dict[str, int]]:
    merged: list[dict[str, int]] = []
    for row in rows:
        target = None
        for item in merged:
            close_y = row["y0"] <= item["y1"] + 2
            overlap_x = min(row["x1"], item["x1"]) - max(row["x0"], item["x0"]) > 0
            if close_y and overlap_x:
                target = item
                break
        if target:
            target["x0"] = min(target["x0"], row["x0"])
            target["x1"] = max(target["x1"], row["x1"])
            target["y0"] = min(target["y0"], row["y0"])
            target["y1"] = max(target["y1"], row["y1"])
        else:
            merged.append(dict(row))
    return merged


def apply_underline_placeholders(question: dict[str, Any], visual_blank_count: int) -> int:
    if visual_blank_count <= 0:
        return 0
    stem = str(question.get("stemMarkdown") or "")
    existing = count_blank_placeholders(stem)
    missing = max(0, min(visual_blank_count - existing, 8))
    if missing <= 0:
        return 0
    repaired = f"{stem.rstrip()}\n\n" + "\n".join("____" for _ in range(missing))
    repaired = normalize_fill_blank_markdown(repaired, "fill_blank")
    question["type"] = "fill_blank"
    question["stemMarkdown"] = repaired
    question["manualMarkdown"] = repaired
    return missing


def count_blank_placeholders(markdown: str) -> int:
    return len(re.findall(r"____|_{2,}|＿{2,}|\\_", str(markdown or "")))


def pix2text_configured() -> bool:
    return bool(os.getenv("PIX2TEXT_COMMAND") or shutil.which("pix2text") or shutil.which("p2t"))


def run_secondary_ocr(crop_path: Path) -> tuple[str | None, str | None]:
    command = resolve_pix2text_command(crop_path)
    if not command:
        return None, None
    timeout = int(os.getenv("PIX2TEXT_TIMEOUT_SECONDS", "45"))
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"Pix2Text timed out after {timeout} seconds."
    except Exception as exc:
        return None, str(exc)
    output = (result.stdout or "").strip()
    if result.returncode != 0:
        error = (result.stderr or output or f"Pix2Text exited with code {result.returncode}.").strip()
        return None, error[-1000:]
    return sanitize_secondary_ocr_text(output), None


def resolve_pix2text_command(crop_path: Path) -> list[str] | None:
    configured = os.getenv("PIX2TEXT_COMMAND")
    if configured:
        parts = shlex.split(configured)
        if any("{image}" in part for part in parts):
            return [part.replace("{image}", str(crop_path)) for part in parts]
        return [*parts, str(crop_path)]
    executable = shutil.which("pix2text") or shutil.which("p2t")
    if not executable:
        return None
    return [executable, str(crop_path)]


def sanitize_secondary_ocr_text(text: str | None) -> str | None:
    value = str(text or "").strip()
    if not value or TRACEBACK_RE.search(value):
        return None
    if len(value) > 6000:
        value = value[:6000]
    return value


def should_apply_secondary_ocr(question: dict[str, Any], candidate: str) -> bool:
    if os.getenv("OCR_VISUAL_REPAIR_APPLY_PIX2TEXT", "true").lower() == "false":
        return False
    candidate_text = sanitize_secondary_ocr_text(candidate)
    if not candidate_text:
        return False
    primary = str(question.get("stemMarkdown") or "")
    if len(candidate_text) < max(20, int(len(primary) * 0.8)):
        return False
    number = str(question.get("number") or "").strip()
    if number and QUESTION_NUMBER_PREFIX_RE.match(candidate_text):
        if QUESTION_NUMBER_PREFIX_RE.match(candidate_text).group(1) != number:
            return False
    return len(candidate_text) > len(primary) + 20 or count_blank_placeholders(candidate_text) > count_blank_placeholders(primary)


def apply_secondary_ocr(question: dict[str, Any], candidate: str) -> None:
    markdown = strip_question_number(candidate)
    markdown = normalize_fill_blank_markdown(markdown, "fill_blank")
    question["type"] = "fill_blank"
    question["stemMarkdown"] = markdown
    question["manualMarkdown"] = markdown


def strip_question_number(markdown: str) -> str:
    return QUESTION_NUMBER_PREFIX_RE.sub("", str(markdown or "").strip(), count=1).strip()


def attach_visual_repair(question: dict[str, Any], repair_record: dict[str, Any]) -> None:
    question["visualRepair"] = repair_record


def normalize_match_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def safe_crop_name(question: dict[str, Any]) -> str:
    value = str(question.get("id") or f"q_{question.get('number') or 'unknown'}")
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)[:80] or "question"


def parse_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def clamped_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    value = parse_int(os.getenv(name), default)
    return max(minimum, min(maximum, value))
