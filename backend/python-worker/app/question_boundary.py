"""Evidence-driven question boundary detection and structure building.

This module keeps LLM output constrained to source ranges. It builds question
objects by slicing OCR Markdown instead of trusting generated question text.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.question_markdown import (
    detect_choice_option_markers,
    ensure_question_images_in_markdown,
    image_from_path,
    infer_question_type,
    normalize_fill_blank_markdown,
    normalize_asset_path,
    refine_question_type_from_markdown,
    split_choice_options,
)


VALID_QUESTION_TYPES = {"choice", "fill_blank", "solution", "unknown"}
QUESTION_NUMBER_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(\d{1,3})[\.．、]\s*(.*)", re.S)
SUB_LABEL_RE = re.compile(
    r"(^|[\r\n]+|[ \t　]+|[。；;：:]\s*)"
    r"(?P<label>[（(]\s*(?:\d{1,2}|[一二三四五六七八九十]{1,3})\s*[）)]|[①②③④⑤⑥⑦⑧⑨⑩])"
)
IMAGE_REF_RE = re.compile(r"!\[[^\]]*]\s*\(\s*<?([^>)\s]+)>?(?:\s+['\"][^)]*['\"])?\s*\)")
NON_QUESTION_TAIL_RE = re.compile(
    r"(?im)^[ \t]*(?:#{1,6}[ \t]*)?(?:"
    r"\d{4}\s*年[^\n]{0,80}(?:试卷|考试|真题)"
    r"|参考答案(?:与|及)?(?:试题)?解析"
    r"|参考答案|答案解析|试题解析|答案与解析"
    r"|【\s*(?:解答|解析|答案)\s*】"
    r"|(?:解答|解析|答案)\s*[:：]"
    r")"
)


def detect_local_boundaries(markdown: str, assets: list[dict[str, Any]]) -> dict[str, Any]:
    """Detect candidate section, question, sub-question, option and image boundaries."""
    source = str(markdown or "")
    sections: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    current_section: dict[str, Any] | None = None

    offset = 0
    for line in source.splitlines(keepends=True):
        line_start = offset
        line_end = offset + len(line)
        stripped = line.strip()
        heading_text = stripped.lstrip("#").strip()
        offset = line_end
        if not heading_text:
            continue

        section_type = infer_question_type(heading_text)
        question_match = QUESTION_NUMBER_RE.match(heading_text)
        if is_section_heading_line(stripped, heading_text, section_type) and not question_match:
            current_section = {
                "id": f"section_{len(sections) + 1}",
                "title": heading_text,
                "type": section_type,
                "start": line_start,
                "end": len(source),
            }
            sections.append(current_section)
            continue

        if question_match:
            if current_section is None:
                current_section = {
                    "id": "section_0",
                    "title": "未分组题目",
                    "type": "unknown",
                    "start": 0,
                    "end": len(source),
                }
                sections.append(current_section)
            questions.append(
                {
                    "id": f"q_{question_match.group(1)}",
                    "number": int(question_match.group(1)),
                    "type": current_section.get("type") or "unknown",
                    "sectionId": current_section["id"],
                    "sectionTitle": current_section["title"],
                    "start": line_start,
                    "end": len(source),
                }
            )

    question_starts = [int(q["start"]) for q in questions]
    section_starts = [int(s["start"]) for s in sections]
    for index, question in enumerate(questions):
        next_starts = [start for start in [*question_starts[index + 1 :], *section_starts] if start > question["start"]]
        question["end"] = min(next_starts) if next_starts else len(source)
        q_text = source[question["start"] : question["end"]]
        question["subQuestions"] = (
            []
            if question.get("type") == "choice"
            else detect_sub_question_boundaries(q_text, int(question["start"]), int(question["end"]))
        )
        question["options"] = detect_option_boundaries(q_text, int(question["start"]))
        question["images"] = detect_image_refs(q_text, int(question["start"]), assets)

    for index, section in enumerate(sections):
        next_section_start = sections[index + 1]["start"] if index + 1 < len(sections) else len(source)
        section["end"] = next_section_start
        section["questions"] = [q["id"] for q in questions if q["sectionId"] == section["id"]]

    return {
        "source": "rule-boundary",
        "sections": sections,
        "questions": questions,
        "images": detect_image_refs(source, 0, assets),
        "questionCount": len(questions),
    }


def evaluate_boundary_confidence(markdown: str, boundaries: dict[str, Any], assets: list[dict[str, Any]]) -> dict[str, Any]:
    """Score whether local question boundaries are safe enough to skip LLM refinement."""
    source = str(markdown or "")
    questions = [question for question in boundaries.get("questions", []) if isinstance(question, dict)]
    reasons: list[str] = []
    low_ids: list[str] = []

    if not questions:
        reasons.append("no-question-boundaries")

    numbers = [int(question.get("number")) for question in questions if isinstance(question.get("number"), int)]
    if len(numbers) >= 2:
        for previous, current in zip(numbers, numbers[1:]):
            if current <= previous or current - previous > 1:
                reasons.append("question-number-gap")
                break

    for question in questions:
        qid = str(question.get("id") or "")
        start = question.get("start")
        end = question.get("end")
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start or end > len(source):
            reasons.append("invalid-question-range")
            if qid:
                low_ids.append(qid)
            continue
        if question.get("type") == "choice" and len(question.get("options") or []) not in {0, 4}:
            reasons.append("unstable-choice-options")
            if qid:
                low_ids.append(qid)

    asset_paths = {str(asset.get("path") or "") for asset in assets if isinstance(asset, dict)}
    for image in boundaries.get("images") or []:
        if not isinstance(image, dict):
            continue
        path = str(image.get("path") or "")
        if path and path not in asset_paths:
            reasons.append("unknown-image-path")
            break

    unique_reasons = list(dict.fromkeys(reasons))
    return {
        "highConfidence": not unique_reasons,
        "reasons": unique_reasons,
        "questionCount": len(questions),
        "lowConfidenceQuestionIds": list(dict.fromkeys(low_ids)),
    }


def plan_boundary_chunks(
    markdown: str,
    boundaries: dict[str, Any],
    chunk_size: int,
    max_chars: int | None = None,
) -> list[dict[str, Any]]:
    """Plan LLM boundary-refinement chunks while preserving absolute offsets."""
    source = str(markdown or "")
    questions = [question for question in boundaries.get("questions", []) if isinstance(question, dict)]
    if not questions:
        return []

    chunk_size = max(1, int(chunk_size or 1))
    char_budget = max(1000, int(max_chars or 0)) if max_chars else None
    sections = [section for section in boundaries.get("sections", []) if isinstance(section, dict)]
    chunks: list[dict[str, Any]] = []

    index = 0
    offset = 0
    while offset < len(questions):
        group: list[dict[str, Any]] = []
        group_start = int(questions[offset].get("start") or 0)
        group_end = group_start
        cursor = offset
        while cursor < len(questions) and len(group) < chunk_size:
            question = questions[cursor]
            question_start = int(question.get("start") or group_start)
            question_end = int(question.get("end") or question_start)
            next_start = min(group_start, question_start) if group else question_start
            next_end = max(group_end, question_end)
            if group and char_budget and next_end - next_start > char_budget:
                break
            group.append(question)
            group_start = next_start
            group_end = next_end
            cursor += 1
        if not group:
            group = [questions[offset]]
            cursor = offset + 1
        start = max(0, min(int(question.get("start") or 0) for question in group))
        end = min(len(source), max(int(question.get("end") or start) for question in group))
        section_ids = {str(question.get("sectionId") or "") for question in group}
        chunk_sections = [section for section in sections if str(section.get("id") or "") in section_ids]
        chunks.append(
            {
                "index": index,
                "start": start,
                "end": end,
                "markdown": source[start:end],
                "localBoundaries": {
                    "source": boundaries.get("source", "rule-boundary"),
                    "sections": chunk_sections,
                    "questions": group,
                    "images": [
                        image
                        for image in boundaries.get("images", [])
                        if isinstance(image, dict)
                        and isinstance(image.get("start"), int)
                        and start <= int(image.get("start")) < end
                    ],
                    "questionCount": len(group),
                },
            }
        )
        index += 1
        offset = cursor
    return chunks


def detect_sub_question_boundaries(text: str, base_offset: int, parent_end: int) -> list[dict[str, Any]]:
    """Detect sub-question labels inside a parent question slice."""
    matches: list[dict[str, Any]] = []
    for match in SUB_LABEL_RE.finditer(text):
        start = base_offset + match.start("label")
        if start == base_offset:
            # This can happen when an OCR line starts with "(1)" but there is no
            # parent question stem before it. It is still a valid sub-question.
            pass
        label = normalize_sub_label(match.group("label"))
        if label in {"(A)", "(B)", "(C)", "(D)", "(E)", "(F)", "(G)", "(H)"}:
            continue
        matches.append(
            {
                "label": label,
                "start": start,
                "contentStart": base_offset + match.end("label"),
                "end": parent_end,
            }
        )
    if len(matches) < 2:
        return []
    for index, item in enumerate(matches):
        item["end"] = matches[index + 1]["start"] if index + 1 < len(matches) else parent_end
    return matches


def detect_option_boundaries(text: str, base_offset: int) -> list[dict[str, Any]]:
    """Detect stable A/B/C/D option ranges."""
    matches = [
        {
            "label": marker["label"],
            "start": base_offset + int(marker["marker_start"]),
            "contentStart": base_offset + int(marker["content_start"]),
            "end": base_offset + len(text),
        }
        for marker in detect_choice_option_markers(text)
    ]
    selected: list[dict[str, Any]] = []
    for start_index, match in enumerate(matches):
        if match["label"] != "A":
            continue
        current = [match]
        expected = "B"
        for cursor in range(start_index + 1, len(matches)):
            if matches[cursor]["label"] == expected:
                current.append(matches[cursor])
                expected = chr(ord(expected) + 1)
                continue
            if current:
                break
        if len(current) >= 2:
            selected = current
            break
    if len(selected) < 2:
        return []
    for index, item in enumerate(selected):
        item["end"] = selected[index + 1]["start"] if index + 1 < len(selected) else base_offset + len(text)
    return selected


def detect_image_refs(text: str, base_offset: int, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect Markdown image references and map them to known OCR assets."""
    image_refs: list[dict[str, Any]] = []
    for match in IMAGE_REF_RE.finditer(text):
        raw_path = match.group(1).strip()
        image = image_from_path(raw_path, assets)
        image_refs.append(
            {
                **image,
                "start": base_offset + match.start(),
                "end": base_offset + match.end(),
                "raw": raw_path,
            }
        )
    return image_refs


def build_structure_from_boundaries(
    markdown: str,
    boundaries: dict[str, Any] | None,
    assets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build OCR question structure by slicing Markdown according to boundaries."""
    source = str(markdown or "")
    normalized = normalize_boundaries(boundaries or {}, source)
    raw_sections = normalized.get("sections") or []
    raw_questions = normalized.get("questions") or []
    if not raw_questions:
        return {"sections": [], "questions": []}

    sections_by_id: dict[str, dict[str, Any]] = {}
    sections: list[dict[str, Any]] = []
    for index, raw_section in enumerate(raw_sections, start=1):
        section_id = str(raw_section.get("id") or f"section_{index}")
        section = {
            "id": section_id,
            "title": str(raw_section.get("title") or f"第 {index} 大题"),
            "type": normalize_type(raw_section.get("type")),
            "questions": [],
        }
        sections_by_id[section_id] = section
        sections.append(section)

    if not sections:
        section = {"id": "section_0", "title": "未分组题目", "type": "unknown", "questions": []}
        sections_by_id[section["id"]] = section
        sections.append(section)

    flat_questions: list[dict[str, Any]] = []
    for fallback_index, raw_question in enumerate(raw_questions, start=1):
        question = build_question(source, raw_question, assets, fallback_index)
        if not question:
            continue
        section_id = str(raw_question.get("sectionId") or raw_question.get("section_id") or "")
        section = sections_by_id.get(section_id) or section_for_question(sections, raw_question)
        question["sectionId"] = section["id"]
        question["sectionTitle"] = section["title"]
        if question["type"] == "unknown":
            question["type"] = section["type"]
        section["questions"].append(question)
        flat_questions.append(question)

    sections = [section for section in sections if section["questions"]]
    for question in flat_questions:
        ensure_question_images_in_markdown(question)
    return {"sections": sections, "questions": flat_questions}


def normalize_boundaries(boundaries: dict[str, Any], source: str) -> dict[str, Any]:
    """Normalize model/local boundary output and discard unsafe spans."""
    sections = boundaries.get("sections") if isinstance(boundaries.get("sections"), list) else []
    questions = boundaries.get("questions") if isinstance(boundaries.get("questions"), list) else []
    safe_sections = []
    for index, section in enumerate(sections, start=1):
        if not isinstance(section, dict):
            continue
        safe_sections.append(
            {
                "id": str(section.get("id") or f"section_{index}"),
                "title": str(section.get("title") or f"第 {index} 大题"),
                "type": normalize_type(section.get("type")),
                "start": clamp_int(section.get("start"), 0, len(source)),
                "end": clamp_int(section.get("end"), 0, len(source)),
            }
        )

    safe_questions: list[dict[str, Any]] = []
    for index, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            continue
        start = clamp_int(question.get("start"), 0, len(source))
        end = clamp_int(question.get("end"), 0, len(source))
        if end <= start:
            continue
        safe_question = {
            "id": str(question.get("id") or f"q_{index}"),
            "number": parse_number(question.get("number"), index),
            "type": normalize_type(question.get("type")),
            "sectionId": str(question.get("sectionId") or question.get("section_id") or ""),
            "sectionTitle": str(question.get("sectionTitle") or question.get("section_title") or ""),
            "start": start,
            "end": end,
            "_rawSubQuestions": question.get("subQuestions") or question.get("children"),
            "_rawOptions": question.get("options"),
            "_rawImages": question.get("images"),
        }
        safe_questions.append(safe_question)
    safe_questions.sort(key=lambda item: (item["start"], item["end"]))
    for index, question in enumerate(safe_questions):
        next_start = safe_questions[index + 1]["start"] if index + 1 < len(safe_questions) else len(source)
        if question["end"] > next_start:
            question["end"] = next_start
        question["subQuestions"] = normalize_child_boundaries(question.pop("_rawSubQuestions", None), question["start"], question["end"])
        question["options"] = normalize_child_boundaries(question.pop("_rawOptions", None), question["start"], question["end"])
        question["images"] = normalize_image_boundaries(question.pop("_rawImages", None), question["start"], question["end"])
    return {"sections": safe_sections, "questions": safe_questions}


def normalize_child_boundaries(value: Any, parent_start: int, parent_end: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        start = clamp_int(item.get("start"), parent_start, parent_end)
        end = clamp_int(item.get("end"), parent_start, parent_end)
        if end <= start:
            continue
        result.append(
            {
                **item,
                "id": str(item.get("id") or f"sub_{index}"),
                "label": str(item.get("label") or item.get("number") or f"({index})"),
                "start": start,
                "contentStart": clamp_int(item.get("contentStart") or item.get("content_start") or start, start, end),
                "end": end,
            }
        )
    result.sort(key=lambda item: (item["start"], item["end"]))
    safe_result: list[dict[str, Any]] = []
    for index, item in enumerate(result):
        start = int(item["start"])
        next_start = int(result[index + 1]["start"]) if index + 1 < len(result) else parent_end
        end = min(int(item["end"]), next_start)
        if end <= start:
            continue
        safe_result.append(
            {
                **item,
                "start": start,
                "contentStart": clamp_int(item.get("contentStart"), start, end),
                "end": end,
            }
        )
    return safe_result


def normalize_image_boundaries(value: Any, parent_start: int, parent_end: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        start = clamp_int(item.get("start"), parent_start, parent_end)
        end = clamp_int(item.get("end"), parent_start, parent_end)
        result.append({**item, "start": start, "end": max(start, end)})
    return result


def build_question(source: str, raw_question: dict[str, Any], assets: list[dict[str, Any]], fallback_index: int) -> dict[str, Any] | None:
    start = int(raw_question["start"])
    end = int(raw_question["end"])
    end = trim_non_question_tail_end(source, start, end)
    raw_text = source[start:end]
    if not raw_text.strip():
        return None

    number = parse_number(raw_question.get("number"), fallback_index)
    question_id = str(raw_question.get("id") or f"q_{number}")
    body = strip_question_number(raw_text)
    question_type = refine_question_type_from_markdown(normalize_type(raw_question.get("type")), body)
    child_boundaries = raw_question.get("subQuestions") or []
    parent_images = images_for_range(raw_question.get("images") or [], assets, start, end)
    question = {
        "id": question_id,
        "number": number,
        "type": question_type,
        "sectionId": str(raw_question.get("sectionId") or ""),
        "sectionTitle": str(raw_question.get("sectionTitle") or ""),
        "pageIndex": None,
        "stemMarkdown": "",
        "manualMarkdown": "",
        "answer": "",
        "analysis": "",
        "images": parent_images,
        "options": [],
        "children": [],
        "subQuestions": [],
        "sourceEvidence": {"start": start, "end": end},
    }

    if child_boundaries:
        first_child_start = int(child_boundaries[0]["start"])
        parent_stem_raw = source[start:first_child_start]
        question["stemMarkdown"] = normalize_fill_blank_markdown(strip_question_number(parent_stem_raw).strip(), question["type"])
        question["manualMarkdown"] = question["stemMarkdown"]
        question["images"] = images_for_range(raw_question.get("images") or [], assets, start, first_child_start)
        question_images = raw_question.get("images") or []
        for child_index, child_boundary in enumerate(child_boundaries, start=1):
            child_start = int(child_boundary.get("start") or start)
            if child_start >= end:
                continue
            child = build_sub_question(
                source,
                {
                    **child_boundary,
                    "end": min(int(child_boundary.get("end") or end), end),
                    "images": [*question_images, *(child_boundary.get("images") or [])],
                },
                assets,
                question,
                child_index,
            )
            if child:
                question["children"].append(child)
        question["subQuestions"] = question["children"]
        return question

    stem, options = split_choice_options(body, "choice" if question_type == "choice" else question_type)
    if options:
        question["type"] = "choice"
        question["stemMarkdown"] = stem
        question["options"] = options
    else:
        question["stemMarkdown"] = normalize_fill_blank_markdown(body.strip(), question["type"])
    question["manualMarkdown"] = question["stemMarkdown"]
    return question


def build_sub_question(
    source: str,
    raw_child: dict[str, Any],
    assets: list[dict[str, Any]],
    parent: dict[str, Any],
    fallback_index: int,
) -> dict[str, Any] | None:
    start = int(raw_child["start"])
    end = int(raw_child["end"])
    end = trim_non_question_tail_end(source, start, end)
    raw_text = source[start:end]
    if not raw_text.strip():
        return None
    label = normalize_sub_label(str(raw_child.get("label") or f"({fallback_index})"))
    body = strip_sub_label(raw_text, label)
    stem, options = split_choice_options(body, "choice")
    base_type = normalize_type(raw_child.get("type") or "unknown")
    question_type = "choice" if options else refine_question_type_from_markdown(base_type, body)
    normalized_stem = stem if options else normalize_fill_blank_markdown(body.strip(), question_type)
    child = {
        "id": str(raw_child.get("id") or f"{parent['id']}_sub_{fallback_index}"),
        "label": label,
        "number": fallback_index,
        "type": question_type,
        "sectionId": parent["sectionId"],
        "sectionTitle": parent["sectionTitle"],
        "pageIndex": None,
        "stem": normalized_stem,
        "stemMarkdown": normalized_stem,
        "manualMarkdown": normalized_stem,
        "answer": "",
        "analysis": "",
        "knowledgePointIds": [],
        "knowledgePoints": [],
        "difficulty": "",
        "score": 0.0,
        "images": images_for_range(raw_child.get("images") or [], assets, start, end),
        "options": options,
        "children": [],
        "subQuestions": [],
        "sourceEvidence": {"start": start, "end": end},
    }
    return child


def trim_non_question_tail_end(source: str, start: int, end: int) -> int:
    """Trim answer/title blocks that OCR appended to the end of a question span."""
    text = source[start:end]
    for match in NON_QUESTION_TAIL_RE.finditer(text):
        prefix = text[: match.start()]
        if prefix.strip():
            return start + len(prefix.rstrip())
    return end


def validate_structure(structured: dict[str, Any], markdown: str, assets: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate structure constraints before accepting AI-refined boundaries."""
    asset_paths = {normalize_asset_path(str(asset.get("path") or asset.get("name") or "")) for asset in assets}
    asset_paths = {path for path in asset_paths if path}
    errors: list[str] = []
    warnings: list[str] = []
    question_count = 0
    sub_question_count = 0

    for section in structured.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for question in section.get("questions") or []:
            if not isinstance(question, dict):
                continue
            question_count += 1
            children = question.get("subQuestions") or question.get("children") or []
            if children:
                sub_question_count += len(children)
                if question.get("answer") or question.get("analysis"):
                    errors.append(f"{question.get('id')} 含小问但父题 answer/analysis 非空")
            if question.get("type") == "choice" and len(question.get("options") or []) < 2:
                warnings.append(f"{question.get('id')} 被判为选择题但选项少于 2 个")
            validate_images(question, asset_paths, errors)
            for child in children:
                if not isinstance(child, dict):
                    continue
                label = str(child.get("label") or "")
                evidence = child.get("sourceEvidence") or {}
                start = evidence.get("start")
                end = evidence.get("end")
                evidence_text = markdown[start:end] if isinstance(start, int) and isinstance(end, int) else ""
                if label and label not in evidence_text:
                    warnings.append(f"{question.get('id')} 小问 {label} 未在证据片段中找到标签")
                if child.get("type") == "choice" and len(child.get("options") or []) < 2:
                    warnings.append(f"{question.get('id')} 小问 {label} 被判为选择题但选项少于 2 个")
                validate_images(child, asset_paths, errors)

    if question_count == 0:
        errors.append("未生成题目结构")
    return {
        "valid": not errors,
        "questionCount": question_count,
        "subQuestionCount": sub_question_count,
        "errors": errors,
        "warnings": warnings,
    }


def validate_images(question: dict[str, Any], asset_paths: set[str], errors: list[str]) -> None:
    for image in question.get("images") or []:
        if not isinstance(image, dict):
            continue
        path = normalize_asset_path(str(image.get("path") or image.get("name") or ""))
        if asset_paths and path and path not in asset_paths and Path(path).name not in {Path(p).name for p in asset_paths}:
            errors.append(f"{question.get('id')} 引用了未知题图 {path}")


def merge_legacy_images(structured: dict[str, Any], legacy: dict[str, Any]) -> None:
    """Preserve image assignments from the legacy content_list parser when present."""
    legacy_by_number: dict[int, dict[str, Any]] = {}
    for section in legacy.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for question in section.get("questions") or []:
            if isinstance(question, dict) and isinstance(question.get("number"), int):
                legacy_by_number[question["number"]] = question
    for section in structured.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for question in section.get("questions") or []:
            if not isinstance(question, dict) or question.get("images"):
                continue
            legacy_question = legacy_by_number.get(question.get("number"))
            if legacy_question and legacy_question.get("images"):
                question["images"] = legacy_question["images"]


def section_for_question(sections: list[dict[str, Any]], question: dict[str, Any]) -> dict[str, Any]:
    start = int(question.get("start") or 0)
    candidates = [section for section in sections if int(section.get("start") or 0) <= start]
    return candidates[-1] if candidates else sections[0]


def images_for_range(raw_images: list[dict[str, Any]], assets: list[dict[str, Any]], start: int, end: int) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_image in raw_images:
        if not isinstance(raw_image, dict):
            continue
        image_start = raw_image.get("start")
        if isinstance(image_start, int) and not (start <= image_start < end):
            continue
        path = str(raw_image.get("path") or raw_image.get("raw") or raw_image.get("name") or "").strip()
        if not path:
            continue
        image = image_from_path(path, assets)
        key = str(image.get("path") or image.get("name") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        images.append(image)
    return images


def strip_question_number(text: str) -> str:
    match = QUESTION_NUMBER_RE.match(str(text or "").strip())
    return (match.group(2) if match else text).strip()


def strip_sub_label(text: str, label: str) -> str:
    stripped = str(text or "").strip()
    escaped = re.escape(label)
    stripped = re.sub(rf"^\s*{escaped}\s*", "", stripped)
    stripped = re.sub(r"^\s*[（(]\s*(?:\d{1,2}|[一二三四五六七八九十]{1,3})\s*[）)]\s*", "", stripped)
    stripped = re.sub(r"^\s*[①②③④⑤⑥⑦⑧⑨⑩]\s*", "", stripped)
    return stripped.strip()


def normalize_sub_label(label: str) -> str:
    value = re.sub(r"\s+", "", str(label or ""))
    circled = "①②③④⑤⑥⑦⑧⑨⑩"
    if value in circled:
        return f"({circled.index(value) + 1})"
    match = re.search(r"[（(](.*?)[）)]", value)
    if match:
        return f"({match.group(1)})"
    return value


def is_section_heading_line(stripped: str, heading_text: str, section_type: str) -> bool:
    """Return true for Markdown or plain OCR section headings like 一、选择题."""
    if section_type == "unknown":
        return False
    if stripped.startswith("#"):
        return True
    if len(heading_text) > 40:
        return False
    if re.match(r"^[一二三四五六七八九十]+[、.．]\s*", heading_text):
        return True
    if re.match(r"^第[一二三四五六七八九十\d]+[部分章节题]\b", heading_text):
        return True
    return False


def normalize_type(value: Any) -> str:
    normalized = str(value or "unknown").strip()
    return normalized if normalized in VALID_QUESTION_TYPES else "unknown"


def parse_number(value: Any, fallback: int) -> int:
    if isinstance(value, int):
        return value
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else fallback


def clamp_int(value: Any, lower: int, upper: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = lower
    return max(lower, min(parsed, upper))
