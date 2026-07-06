"""视觉证据修复。

本模块只做低置信题目的题目级 crop、横线检测和可选二次 OCR。它不让
Pix2Text 或其它备用 OCR 覆盖高置信主链路结果。
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image

from app.question_markdown import (
    is_fill_blank_markdown,
    normalize_fill_blank_markdown,
)


QUESTION_NUMBER_PREFIX_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(\d{1,3})[\.．、]\s*")
TRACEBACK_RE = re.compile(r"traceback|exception|error:", re.I)


def apply_visual_repairs(
    structured: dict[str, Any],
    output_dir: Path,
    upload_path: str | Path | None,
    job_id: str,
) -> dict[str, Any]:
    """对结构化题目应用题目级视觉修复。"""
    if os.getenv("OCR_VISUAL_REPAIR_ENABLED", "true").lower() == "false":
        return {"enabled": False, "skippedReason": "OCR_VISUAL_REPAIR_ENABLED=false"}

    visual_items = load_visual_items(output_dir)
    page_sizes = load_page_sizes(output_dir)
    questions = list(iter_parent_questions(structured))
    summary: dict[str, Any] = {
        "enabled": True,
        "questionCount": len(questions),
        "candidateCount": 0,
        "cropCount": 0,
        "underlineCount": 0,
        "placeholderRepairCount": 0,
        "secondaryOcr": {
            "configured": pix2text_configured(),
            "attempted": 0,
            "applied": 0,
            "failed": 0,
        },
        "warnings": [],
    }

    crop_dir = output_dir / "visual_repair"
    for question in questions:
        if not question_needs_visual_repair(question):
            continue
        summary["candidateCount"] += 1
        try:
            item = find_visual_item_for_question(question, visual_items)
            if not item:
                summary["warnings"].append(f"{question.get('id')} 未找到题目 bbox，跳过视觉修复")
                attach_visual_repair(question, {"status": "skipped", "reason": "missing_bbox"})
                continue

            crop = crop_question_image(upload_path, item, page_sizes)
            if crop is None:
                summary["warnings"].append(f"{question.get('id')} 无法生成题目 crop")
                attach_visual_repair(question, {"status": "skipped", "reason": "crop_unavailable"})
                continue

            crop_dir.mkdir(parents=True, exist_ok=True)
            crop_path = crop_dir / f"{safe_crop_name(question)}.png"
            crop.save(crop_path)
            summary["cropCount"] += 1

            underlines = detect_underline_segments(crop)
            summary["underlineCount"] += len(underlines)
            repair_record: dict[str, Any] = {
                "status": "checked",
                "cropPath": crop_path.relative_to(output_dir).as_posix(),
                "pageIndex": item.get("page_idx"),
                "bbox": item.get("bbox"),
                "underlineCount": len(underlines),
                "underlines": underlines[:20],
            }

            secondary_text, secondary_error = run_secondary_ocr(crop_path)
            if secondary_text or secondary_error:
                summary["secondaryOcr"]["attempted"] += 1
                repair_record["secondaryOcr"] = {
                    "provider": "pix2text",
                    "applied": False,
                    "error": secondary_error,
                    "markdown": secondary_text,
                }
                if secondary_error:
                    summary["secondaryOcr"]["failed"] += 1

            applied_secondary = False
            if secondary_text and should_apply_secondary_ocr(question, secondary_text):
                apply_secondary_ocr(question, secondary_text)
                repair_record["secondaryOcr"]["applied"] = True
                summary["secondaryOcr"]["applied"] += 1
                applied_secondary = True

            if not applied_secondary:
                added = apply_underline_placeholders(question, len(underlines))
                if added:
                    repair_record["placeholderAdded"] = added
                    summary["placeholderRepairCount"] += added

            attach_visual_repair(question, repair_record)
        except Exception as exc:  # pragma: no cover - 单题修复不能中断 OCR 任务
            summary["warnings"].append(f"{question.get('id')} 视觉修复失败：{exc}")
            attach_visual_repair(question, {"status": "failed", "error": str(exc)})
    return summary


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


def find_visual_item_for_question(question: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any] | None:
    number = str(question.get("number") or "").strip()
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
) -> Image.Image | None:
    path = Path(str(upload_path or ""))
    if not path.exists():
        return None
    bbox = item.get("bbox")
    if not isinstance(bbox, list) or len(bbox) < 4:
        return None
    page_idx = parse_int(item.get("page_idx"), 0)
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}:
        image = Image.open(path).convert("RGB")
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
    return image.crop((x0, y0, max(x1, x0 + 1), max(y1, y0 + 1)))


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
