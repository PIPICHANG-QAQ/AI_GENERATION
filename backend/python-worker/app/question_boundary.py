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
from app.image_placement import build_image_placements, validate_image_placements


VALID_QUESTION_TYPES = {"choice", "fill_blank", "solution", "unknown"}
QUESTION_NUMBER_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(\d{1,3})[\.．、]\s*(.*)", re.S)
INLINE_QUESTION_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_])(?P<number>\d{1,3})[\.．、]\s*(?=[\u4e00-\u9fffA-Za-z$（(])")
IMAGE_FILE_EXTENSION_RE = re.compile(r"^\s*(?:jpe?g|png|webp|gif|bmp|tiff?)(?:\b|[)\]}>,._/-])", re.I)
PAPER_TOTAL_RE = re.compile(r"(?:本试卷|全卷|试卷)[^\n。；;]{0,40}?(?:共|共有)\s*(\d{1,3})\s*题")
SECTION_QUESTION_COUNT_RE = re.compile(r"(?:本大题|大题)?\s*(?:共有|共)\s*(\d{1,3})\s*(?:个\s*)?(?:小题|题)")
SECTION_QUESTION_RANGE_RE = re.compile(r"第\s*(\d{1,3})\s*(?:[~～\-]|\\~)\s*(\d{1,3})\s*题")
GENERIC_SECTION_HEADING_RE = re.compile(
    r"^(?:专题|考点|考向|题型|真题(?:感知|演练|汇编)?|模拟(?:预测|演练)?|基础(?:过关)?练|能力(?:提升)?练|综合(?:训练|检测)|易错(?:题)?|热点(?:题)?)"
    r"\s*(?:\d{1,3}|[一二三四五六七八九十]{1,3})?(?:[、.．:：-]\s*)?.{0,32}$"
)
QUESTION_SOURCE_TAG_RE = re.compile(r"^\s*(?:[（(]\s*)?(?:19|20)\d{2}[·.、\-—]")
QUESTION_STEM_CUE_RE = re.compile(
    r"已知|若|设|下列|则|求|证明|计算|化简|判断|满足|定义|命题|函数|集合|复数|"
    r"充要条件|充分|必要|取值范围|完成|补全|观察|选择|如图|"
    r"第[一二三四五六七八九十\d]{1,3}题|等于|为\s*[（(]|是\s*[“\"]|________|____|（\s*）|\(\s*\)"
)
QUESTION_LIST_EXPLANATION_RE = re.compile(
    r"形式|覆盖面|要求考生|不再直接|定义了|这要求|不仅是|而是在考|"
    r"试题主要|重点考查|侧重|转向|回归本质|创新考法"
)
PREFACE_LINE_RE = re.compile(
    r"本试卷|试题卷|答题纸|考生注意|考试时间|规定位置|计算器|注意事项|姓名|准考证|班级|学校"
)
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
    r")"
)
BRACKETED_SOLUTION_MARKER_RE = re.compile(
    r"【\s*(?P<label>参考答案|答案|解析|详解|分析|解答)\s*】"
)
LINE_SOLUTION_MARKER_RE = re.compile(
    r"(?im)(?P<prefix>^|[\r\n]+)[ \t]*(?P<label>参考答案|答案|解析|详解|分析|解答)\s*[:：]\s*"
)


def detect_local_boundaries(markdown: str, assets: list[dict[str, Any]]) -> dict[str, Any]:
    """Detect candidate section, question, sub-question, option and image boundaries."""
    source = str(markdown or "")
    structure_contract = extract_paper_structure_contract(source)
    contract_sections_by_start = {
        int(section["start"]): section
        for section in structure_contract.get("sections", [])
        if isinstance(section, dict) and isinstance(section.get("start"), int)
    }
    sections: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    anchor_candidates: list[dict[str, Any]] = []
    current_section: dict[str, Any] | None = None

    def add_question_candidate(number: int, body: str, start: int, end: int, raw: str, source_kind: str) -> None:
        nonlocal current_section
        candidate = score_question_anchor_candidate(
            number=number,
            body=body,
            start=start,
            end=end,
            raw=raw,
            source_kind=source_kind,
            current_section=current_section,
            contract=structure_contract,
            source=source,
            previous_question=questions[-1] if questions else None,
        )
        anchor_candidates.append(candidate)
        if not candidate.get("accepted"):
            return
        if current_section is None:
            current_section = {
                "id": "section_0",
                "title": "未分组题目",
                "type": "unknown",
                "start": 0,
                "end": len(source),
                "numberingScope": "global",
            }
            sections.append(current_section)
        question = {
            "id": unique_question_id(number, questions),
            "number": number,
            "type": current_section.get("type") or "unknown",
            "sectionId": current_section["id"],
            "sectionTitle": current_section["title"],
            "start": start,
            "end": len(source),
            "anchorScore": candidate.get("score"),
            "anchorReasons": candidate.get("reasons", []),
            "numberingReset": candidate.get("numberingReset", False),
        }
        questions.append(question)

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
        is_section_heading = (
            is_section_heading_line(stripped, heading_text, section_type)
            or is_generic_section_heading_line(stripped, heading_text)
        )
        if is_section_heading and not question_match:
            expected_next = int(questions[-1].get("number") or 0) + 1 if questions else 1
            inline_question_match = find_glued_section_question(line, line_start, source, expected_next)
            clean_heading_text = (
                line[: inline_question_match.start("number")].strip().lstrip("#").strip()
                if inline_question_match is not None
                else heading_text
            )
            clean_section_type = infer_question_type(clean_heading_text)
            section_contract = contract_sections_by_start.get(line_start, {})
            current_section = {
                "id": f"section_{len(sections) + 1}",
                "title": clean_heading_text,
                "type": clean_section_type,
                "start": line_start,
                "end": len(source),
                "declaredCount": section_contract.get("declaredCount"),
                "rangeStart": section_contract.get("rangeStart"),
                "rangeEnd": section_contract.get("rangeEnd"),
                "numberingScope": "section" if clean_section_type == "unknown" else "global",
            }
            sections.append(current_section)
            if inline_question_match is not None:
                add_question_candidate(
                    int(inline_question_match.group("number")),
                    line[inline_question_match.end() :],
                    line_start + inline_question_match.start("number"),
                    line_end,
                    line[inline_question_match.start("number") :].strip(),
                    "inline-section",
                )
            continue

        if question_match:
            add_question_candidate(
                int(question_match.group(1)),
                question_match.group(2),
                line_start,
                line_end,
                heading_text,
                "line-start",
            )

        if current_section is not None and questions:
            expected_next = int(questions[-1].get("number") or 0) + 1
            for inline_match in INLINE_QUESTION_NUMBER_RE.finditer(line):
                number = int(inline_match.group("number"))
                if number != expected_next:
                    continue
                if not is_valid_inline_question_anchor(source, line, line_start, inline_match):
                    continue
                body = line[inline_match.end() :]
                add_question_candidate(
                    number,
                    body,
                    line_start + inline_match.start("number"),
                    line_end,
                    line[inline_match.start("number") :].strip(),
                    "inline",
                )
                break

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
        "anchorCandidates": anchor_candidates,
        "structureContract": structure_contract,
    }


def extract_paper_structure_contract(markdown: str) -> dict[str, Any]:
    """Extract declared paper/question-section counts used to validate boundaries."""
    source = str(markdown or "")
    total_match = PAPER_TOTAL_RE.search(source)
    total_question_count = int(total_match.group(1)) if total_match else None
    total_question_count_source = "paper" if total_match else None
    sections: list[dict[str, Any]] = []

    offset = 0
    for line in source.splitlines(keepends=True):
        line_start = offset
        offset += len(line)
        stripped = line.strip()
        heading_text = stripped.lstrip("#").strip()
        if not heading_text:
            continue
        section_type = infer_question_type(heading_text)
        if not is_section_heading_line(stripped, heading_text, section_type):
            continue
        inline_question_match = find_glued_section_question(line, line_start, source)
        clean_heading_text = (
            line[: inline_question_match.start("number")].strip().lstrip("#").strip()
            if inline_question_match is not None
            else heading_text
        )
        section_type = infer_question_type(clean_heading_text)
        count_match = SECTION_QUESTION_COUNT_RE.search(heading_text)
        declared_count = int(count_match.group(1)) if count_match else None
        explicit_ranges = [
            (int(match.group(1)), int(match.group(2)))
            for match in SECTION_QUESTION_RANGE_RE.finditer(heading_text)
        ]
        explicit_ranges = [(start, end) for start, end in explicit_ranges if end >= start]
        sections.append(
            {
                "title": clean_heading_text,
                "type": section_type,
                "start": line_start,
                "declaredCount": declared_count,
                "explicitRangeStart": min((item[0] for item in explicit_ranges), default=None),
                "explicitRangeEnd": max((item[1] for item in explicit_ranges), default=None),
            }
        )

    cursor = 1
    declared_total = 0
    declared_complete = bool(sections)
    for section in sections:
        declared_count = section.get("declaredCount")
        explicit_start = section.get("explicitRangeStart")
        explicit_end = section.get("explicitRangeEnd")
        if isinstance(explicit_start, int) and isinstance(explicit_end, int):
            section["rangeStart"] = explicit_start
            section["rangeEnd"] = explicit_end
            if not isinstance(declared_count, int) or declared_count <= 0:
                declared_count = explicit_end - explicit_start + 1
                section["declaredCount"] = declared_count
            cursor = explicit_end + 1
            declared_total += declared_count
        elif isinstance(declared_count, int) and declared_count > 0:
            section["rangeStart"] = cursor
            section["rangeEnd"] = cursor + declared_count - 1
            cursor += declared_count
            declared_total += declared_count
        else:
            declared_complete = False

    if total_question_count is None and declared_complete:
        total_question_count = declared_total
        total_question_count_source = "sections"

    first_section_start = sections[0]["start"] if sections else None
    pre_section_question_like_count = (
        count_question_like_anchors(source[:first_section_start])
        if isinstance(first_section_start, int) and first_section_start > 0
        else 0
    )
    first_section_is_authoritative = bool(
        sections
        and (
            total_question_count_source == "paper"
            or declared_complete
            or pre_section_question_like_count == 0
        )
    )

    return {
        "totalQuestionCount": total_question_count,
        "totalQuestionCountSource": total_question_count_source,
        "sections": sections,
        "firstSectionStart": first_section_start if first_section_is_authoritative else None,
        "firstSectionStartReliable": first_section_is_authoritative,
        "preSectionQuestionLikeCount": pre_section_question_like_count,
        "declaredSectionTotal": declared_total if declared_complete else None,
    }


def score_question_anchor_candidate(
    *,
    number: int,
    body: str,
    start: int,
    end: int,
    raw: str,
    source_kind: str,
    current_section: dict[str, Any] | None,
    contract: dict[str, Any],
    source: str,
    previous_question: dict[str, Any] | None,
) -> dict[str, Any]:
    """Score a numeric anchor before deciding whether it is a real question."""
    reasons: list[str] = []
    score = 0
    contract_sections = [section for section in contract.get("sections", []) if isinstance(section, dict)]
    first_section_start = contract.get("firstSectionStart")
    strong_question_anchor = looks_like_question_anchor(raw, body)
    typed_section_context = bool(
        current_section
        and (
            normalize_type(current_section.get("type")) != "unknown"
            or isinstance(current_section.get("rangeStart"), int)
            or isinstance(current_section.get("declaredCount"), int)
        )
    )
    numbering_reset = False
    authoritative_contract = bool(
        isinstance(first_section_start, int)
        or contract_expected_numbers(contract)
        or isinstance(contract.get("totalQuestionCount"), int)
    )

    if isinstance(first_section_start, int) and start < first_section_start:
        reasons.append("before-first-section")
    elif authoritative_contract and contract_sections and current_section is None:
        reasons.append("outside-declared-section")
    else:
        score += 30

    if looks_like_exam_preface(raw) or looks_like_exam_preface(body):
        reasons.append("preface-numbered-line")
    else:
        score += 20

    if strong_question_anchor:
        score += 15
    elif (previous_question is None or number == 1) and not typed_section_context:
        reasons.append("weak-question-anchor")

    if current_section is not None:
        score += 25
        range_start = current_section.get("rangeStart")
        range_end = current_section.get("rangeEnd")
        if isinstance(range_start, int) and isinstance(range_end, int):
            if not (range_start <= number <= range_end):
                reasons.append("outside-section-number-range")
            else:
                score += 20

    if previous_question is not None:
        previous_number = previous_question.get("number")
        if isinstance(previous_number, int):
            if number == previous_number + 1:
                score += 15
            elif is_allowed_question_number_reset(number, previous_question, current_section, strong_question_anchor):
                score += 10
                numbering_reset = True
            elif number <= previous_number:
                reasons.append("non-increasing-question-number")
            else:
                reasons.append("question-number-gap")

    if body.strip():
        score += 10

    accepted = score >= 45 and not any(
        reason
        in {
            "before-first-section",
            "outside-declared-section",
            "preface-numbered-line",
            "outside-section-number-range",
            "non-increasing-question-number",
            "weak-question-anchor",
        }
        for reason in reasons
    )
    return {
        "number": number,
        "start": start,
        "end": end,
        "source": source_kind,
        "score": score,
        "accepted": accepted,
        "numberingReset": numbering_reset,
        "reasons": list(dict.fromkeys(reasons)),
        "preview": source[start : min(len(source), start + 80)],
    }


def looks_like_exam_preface(text: str) -> bool:
    return bool(PREFACE_LINE_RE.search(str(text or "")))


def count_question_like_anchors(text: str) -> int:
    count = 0
    for line in str(text or "").splitlines():
        heading_text = line.strip().lstrip("#").strip()
        match = QUESTION_NUMBER_RE.match(heading_text)
        if not match:
            continue
        if looks_like_exam_preface(heading_text):
            continue
        if looks_like_question_anchor(heading_text, match.group(2)):
            count += 1
    return count


def looks_like_question_anchor(raw: str, body: str) -> bool:
    """Return true when a numbered line looks like a question, not an overview list item."""
    text = re.sub(r"\s+", " ", str(body or raw or "")).strip()
    if not text:
        return False
    if QUESTION_LIST_EXPLANATION_RE.search(text) and not QUESTION_SOURCE_TAG_RE.search(text):
        return False
    return bool(QUESTION_SOURCE_TAG_RE.search(text) or QUESTION_STEM_CUE_RE.search(text))


def is_allowed_question_number_reset(
    number: int,
    previous_question: dict[str, Any],
    current_section: dict[str, Any] | None,
    strong_question_anchor: bool,
) -> bool:
    """Allow topic compilations to restart numbering while preserving exam strictness."""
    previous_number = previous_question.get("number")
    if number != 1 or not isinstance(previous_number, int) or previous_number < 2 or not strong_question_anchor:
        return False
    previous_section_id = str(previous_question.get("sectionId") or "")
    current_section_id = str((current_section or {}).get("id") or "")
    if current_section_id and current_section_id != previous_section_id:
        return True
    return previous_number >= 3


def unique_question_id(number: int, questions: list[dict[str, Any]]) -> str:
    """Return a stable unique id while keeping q_N for the first occurrence."""
    base = f"q_{number}"
    existing = {str(question.get("id") or "") for question in questions}
    if base not in existing:
        return base
    suffix = 2
    while f"{base}_{suffix}" in existing:
        suffix += 1
    return f"{base}_{suffix}"


def is_valid_inline_question_anchor(source: str, line: str, line_start: int, match: re.Match[str]) -> bool:
    """Return whether an inline numeric token can be a glued question number."""
    absolute_start = line_start + match.start("number")
    if is_offset_inside_markdown_image_ref(line, match.start("number")):
        return False
    if is_offset_inside_markdown_image_ref(source, absolute_start):
        return False
    body = line[match.end() :]
    if IMAGE_FILE_EXTENSION_RE.match(body):
        return False
    return True


def find_glued_section_question(
    line: str,
    line_start: int,
    source: str,
    expected_number: int | None = None,
) -> re.Match[str] | None:
    """Find a real question number OCR glued after a section heading."""
    for match in INLINE_QUESTION_NUMBER_RE.finditer(line):
        number = int(match.group("number"))
        if expected_number is not None and number != expected_number:
            continue
        if not is_valid_inline_question_anchor(source, line, line_start, match):
            continue
        body = line[match.end() :]
        if looks_like_question_anchor(line[match.start("number") :], body):
            return match
    return None


def is_offset_inside_markdown_image_ref(text: str, offset: int) -> bool:
    if offset < 0:
        return False
    for image_match in IMAGE_REF_RE.finditer(str(text or "")):
        if image_match.start() <= offset < image_match.end():
            return True
    return False


def evaluate_boundary_confidence(markdown: str, boundaries: dict[str, Any], assets: list[dict[str, Any]]) -> dict[str, Any]:
    """Score whether local question boundaries are safe enough to skip LLM refinement."""
    source = str(markdown or "")
    questions = [question for question in boundaries.get("questions", []) if isinstance(question, dict)]
    contract = boundaries.get("structureContract") if isinstance(boundaries.get("structureContract"), dict) else {}
    reasons: list[str] = []
    low_ids: list[str] = []

    if not questions:
        reasons.append("no-question-boundaries")

    numbers = [int(question.get("number")) for question in questions if isinstance(question.get("number"), int)]
    expected_total = contract.get("totalQuestionCount")
    allows_partial_prefix = contract_allows_partial_section_prefix(contract, numbers)
    if isinstance(expected_total, int) and expected_total > 0 and len(questions) != expected_total and not allows_partial_prefix:
        reasons.append("question-count-mismatch")
    expected_numbers = contract_expected_numbers(contract)
    if expected_numbers and numbers != expected_numbers and not allows_partial_prefix:
        reasons.append("question-number-contract-mismatch")
    reset_flags = [bool(question.get("numberingReset")) for question in questions if isinstance(question.get("number"), int)]
    allows_numbering_resets = sequence_allows_numbering_resets(numbers, reset_flags)
    if len(set(numbers)) != len(numbers) and not allows_numbering_resets:
        reasons.append("duplicate-question-number")
    if len(numbers) >= 2:
        for index, (previous, current) in enumerate(zip(numbers, numbers[1:]), start=1):
            if index < len(reset_flags) and reset_flags[index]:
                continue
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
                    "structureContract": boundaries.get("structureContract"),
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


def contract_expected_numbers(contract: dict[str, Any]) -> list[int]:
    expected_numbers: list[int] = []
    if not isinstance(contract, dict):
        return expected_numbers
    for section in contract.get("sections") or []:
        if not isinstance(section, dict):
            continue
        range_start = section.get("rangeStart")
        range_end = section.get("rangeEnd")
        if isinstance(range_start, int) and isinstance(range_end, int) and range_end >= range_start:
            expected_numbers.extend(range(range_start, range_end + 1))
    return expected_numbers


def contract_allows_partial_section_prefix(contract: dict[str, Any], question_numbers: list[int]) -> bool:
    """Allow cropped single-section scans to contain only the leading questions."""
    if not isinstance(contract, dict) or contract.get("totalQuestionCountSource") == "paper":
        return False
    sections = [section for section in contract.get("sections") or [] if isinstance(section, dict)]
    if len(sections) != 1 or not question_numbers:
        return False
    expected_numbers = contract_expected_numbers(contract)
    if not expected_numbers or len(question_numbers) >= len(expected_numbers):
        return False
    return question_numbers == expected_numbers[: len(question_numbers)]


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
        return {"sections": [], "questions": [], "structureContract": normalized.get("structureContract")}

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
    return {
        "sections": sections,
        "questions": flat_questions,
        "structureContract": normalized.get("structureContract"),
    }


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
                "numberingScope": str(section.get("numberingScope") or section.get("numbering_scope") or "global"),
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
            "pageIndex": question.get("pageIndex"),
            "numberingReset": bool(question.get("numberingReset") or question.get("numbering_reset")),
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
    structure_contract = boundaries.get("structureContract") if isinstance(boundaries.get("structureContract"), dict) else {}
    return {"sections": safe_sections, "questions": safe_questions, "structureContract": structure_contract}


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
    solution = extract_embedded_solution_blocks(raw_text, start)
    stem_raw_text = solution["stemText"]
    body = strip_question_number(stem_raw_text)
    question_type = refine_question_type_from_markdown(normalize_type(raw_question.get("type")), body)
    if question_type == "unknown" and raw_question.get("options"):
        question_type = "choice"
    child_boundaries = raw_question.get("subQuestions") or []
    stem_end = start + len(stem_raw_text)
    parent_images = images_for_range(raw_question.get("images") or [], assets, start, stem_end)
    question = {
        "id": question_id,
        "number": number,
        "type": question_type,
        "sectionId": str(raw_question.get("sectionId") or ""),
        "sectionTitle": str(raw_question.get("sectionTitle") or ""),
        "pageIndex": raw_question.get("pageIndex"),
        "stemMarkdown": "",
        "manualMarkdown": "",
        "answer": solution["answer"],
        "analysis": solution["analysis"],
        "answerEvidence": solution["answerEvidence"],
        "analysisEvidence": solution["analysisEvidence"],
        "images": parent_images,
        "options": [],
        "children": [],
        "subQuestions": [],
        "sourceEvidence": {"start": start, "end": stem_end},
        "numberingReset": bool(raw_question.get("numberingReset")),
    }
    question["imagePlacements"] = build_image_placements(raw_question, raw_question.get("images") or [])

    if child_boundaries:
        question["answer"] = ""
        question["analysis"] = ""
        question["answerEvidence"] = ""
        question["analysisEvidence"] = ""
        first_child_start = int(child_boundaries[0]["start"])
        parent_stem_raw = source[start:min(first_child_start, stem_end)]
        question["stemMarkdown"] = normalize_fill_blank_markdown(strip_question_number(parent_stem_raw).strip(), question["type"])
        question["manualMarkdown"] = question["stemMarkdown"]
        question["images"] = images_for_range(raw_question.get("images") or [], assets, start, min(first_child_start, stem_end))
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
    solution = extract_embedded_solution_blocks(raw_text, start)
    stem_raw_text = solution["stemText"]
    body = strip_sub_label(stem_raw_text, label)
    stem, options = split_choice_options(body, "choice")
    base_type = normalize_type(raw_child.get("type") or "unknown")
    question_type = "choice" if options else refine_question_type_from_markdown(base_type, body)
    normalized_stem = stem if options else normalize_fill_blank_markdown(body.strip(), question_type)
    stem_end = start + len(stem_raw_text)
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
        "answer": solution["answer"],
        "analysis": solution["analysis"],
        "answerEvidence": solution["answerEvidence"],
        "analysisEvidence": solution["analysisEvidence"],
        "knowledgePointIds": [],
        "knowledgePoints": [],
        "difficulty": "",
        "score": 0.0,
        "images": images_for_range(raw_child.get("images") or [], assets, start, stem_end),
        "options": options,
        "children": [],
        "subQuestions": [],
        "sourceEvidence": {"start": start, "end": stem_end},
    }
    child["imagePlacements"] = build_image_placements(raw_child, raw_child.get("images") or [])
    return child


def extract_embedded_solution_blocks(text: str, base_offset: int = 0) -> dict[str, Any]:
    """Split embedded OCR answer/analysis markers out of a question slice."""
    source = str(text or "")
    markers = detect_solution_markers(source)
    if not markers:
        return {
            "stemText": source,
            "answer": "",
            "analysis": "",
            "answerEvidence": "",
            "analysisEvidence": "",
        }

    first_start = markers[0]["start"]
    answer_parts: list[str] = []
    analysis_parts: list[str] = []
    answer_evidence: list[str] = []
    analysis_evidence: list[str] = []
    for index, marker in enumerate(markers):
        content_start = int(marker["end"])
        content_end = int(markers[index + 1]["start"]) if index + 1 < len(markers) else len(source)
        content = source[content_start:content_end].strip()
        if not content:
            continue
        kind = solution_marker_kind(str(marker["label"]))
        evidence = source[int(marker["start"]) : content_end].strip()
        if kind == "answer":
            answer_text, trailing_analysis = split_answer_content(content)
            if answer_text:
                answer_parts.append(answer_text)
                answer_evidence.append(evidence if not trailing_analysis else source[int(marker["start"]) : content_start + len(answer_text)].strip())
            if trailing_analysis:
                analysis_parts.append(trailing_analysis)
                analysis_evidence.append(trailing_analysis)
        else:
            analysis_parts.append(content)
            analysis_evidence.append(evidence)

    return {
        "stemText": source[:first_start].rstrip(),
        "answer": "\n\n".join(answer_parts).strip(),
        "analysis": "\n\n".join(analysis_parts).strip(),
        "answerEvidence": "\n\n".join(answer_evidence).strip(),
        "analysisEvidence": "\n\n".join(analysis_evidence).strip(),
        "solutionEvidence": {
            "start": base_offset + first_start,
            "end": base_offset + len(source),
        },
    }


def detect_solution_markers(text: str) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    for match in BRACKETED_SOLUTION_MARKER_RE.finditer(text):
        markers.append(
            {
                "label": match.group("label"),
                "start": match.start(),
                "end": match.end(),
            }
        )
    for match in LINE_SOLUTION_MARKER_RE.finditer(text):
        start = match.start("label")
        markers.append(
            {
                "label": match.group("label"),
                "start": start,
                "end": match.end(),
            }
        )
    markers.sort(key=lambda item: (int(item["start"]), int(item["end"])))
    deduped: list[dict[str, Any]] = []
    occupied: set[tuple[int, int]] = set()
    for marker in markers:
        key = (int(marker["start"]), int(marker["end"]))
        if key in occupied:
            continue
        occupied.add(key)
        deduped.append(marker)
    return deduped


def solution_marker_kind(label: str) -> str:
    return "answer" if "答案" in label else "analysis"


def split_answer_content(content: str) -> tuple[str, str]:
    """Keep concise answer text separate from unlabeled following explanation."""
    text = str(content or "").strip()
    if not text:
        return "", ""
    paragraphs = re.split(r"\n\s*\n", text, maxsplit=1)
    if len(paragraphs) == 2 and looks_like_short_answer(paragraphs[0]):
        return paragraphs[0].strip(), paragraphs[1].strip()
    lines = text.splitlines()
    if len(lines) > 1 and looks_like_short_answer(lines[0]):
        return lines[0].strip(), "\n".join(lines[1:]).strip()
    return text, ""


def looks_like_short_answer(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    if not compact:
        return False
    if len(compact) > 80:
        return False
    return not re.search(r"因为|所以|由题|可得|解得|证明|计算|根据|对于|若|则", compact)


def trim_non_question_tail_end(source: str, start: int, end: int) -> int:
    """Trim answer/title blocks that OCR appended to the end of a question span."""
    text = source[start:end]
    for match in NON_QUESTION_TAIL_RE.finditer(text):
        prefix = text[: match.start()]
        if prefix.strip():
            return start + len(prefix.rstrip())
    return end


def validate_structure(
    structured: dict[str, Any],
    markdown: str,
    assets: list[dict[str, Any]],
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate structure constraints before accepting AI-refined boundaries."""
    asset_paths = {normalize_asset_path(str(asset.get("path") or asset.get("name") or "")) for asset in assets}
    asset_paths = {path for path in asset_paths if path}
    if contract is None and isinstance(structured.get("structureContract"), dict):
        contract = structured.get("structureContract")
    errors: list[str] = []
    warnings: list[str] = []
    question_count = 0
    sub_question_count = 0
    question_numbers: list[int] = []
    question_numbering_resets: list[bool] = []

    for section in structured.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for question in section.get("questions") or []:
            if not isinstance(question, dict):
                continue
            question_count += 1
            if isinstance(question.get("number"), int):
                number = int(question["number"])
                question_numbers.append(number)
                question_numbering_resets.append(bool(question.get("numberingReset")))
                if not question_evidence_starts_with_number(markdown, question.get("sourceEvidence"), number):
                    errors.append(f"{question.get('id')} 证据片段未从题号 {number} 开始")
            children = question.get("subQuestions") or question.get("children") or []
            if children:
                sub_question_count += len(children)
                if question.get("answer") or question.get("analysis"):
                    errors.append(f"{question.get('id')} 含小问但父题 answer/analysis 非空")
            if question.get("type") == "choice" and len(question.get("options") or []) < 2:
                warnings.append(f"{question.get('id')} 被判为选择题但选项少于 2 个")
            validate_images(question, asset_paths, errors)
            placement_assets = list(question.get("images") or [])
            for child in children:
                if isinstance(child, dict):
                    placement_assets.extend(child.get("images") or [])
            validate_question_placements(question, placement_assets, errors, warnings)
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
                validate_question_placements(child, child.get("images") or [], errors, warnings)

    if question_count == 0:
        errors.append("未生成题目结构")
    validate_structure_contract(contract or {}, question_numbers, question_count, errors, warnings, question_numbering_resets)
    return {
        "valid": not errors,
        "questionCount": question_count,
        "subQuestionCount": sub_question_count,
        "errors": errors,
        "warnings": warnings,
    }


def question_evidence_starts_with_number(markdown: str, evidence: Any, number: int) -> bool:
    if not isinstance(evidence, dict):
        return True
    start = evidence.get("start")
    end = evidence.get("end")
    if not isinstance(start, int) or not isinstance(end, int) or end <= start:
        return True
    prefix = str(markdown or "")[start : min(end, start + 40)]
    match = re.match(rf"^\s*(?:#{{1,6}}\s*)?{number}\s*[\.．、]", prefix)
    if not match:
        return False
    return not IMAGE_FILE_EXTENSION_RE.match(prefix[match.end() :])


def validate_structure_contract(
    contract: dict[str, Any],
    question_numbers: list[int],
    question_count: int,
    errors: list[str],
    warnings: list[str],
    numbering_resets: list[bool] | None = None,
) -> None:
    if not isinstance(contract, dict) or not contract:
        return
    expected_total = contract.get("totalQuestionCount")
    allows_partial_prefix = contract_allows_partial_section_prefix(contract, question_numbers)
    if isinstance(expected_total, int) and expected_total > 0 and question_count != expected_total:
        if allows_partial_prefix:
            warnings.append(f"题目数量 {question_count} 少于单大题声明 {expected_total}，按局部页面处理")
        else:
            errors.append(f"题目数量 {question_count} 与卷面声明 {expected_total} 不一致")

    expected_numbers: list[int] = []
    for section in contract.get("sections") or []:
        if not isinstance(section, dict):
            continue
        range_start = section.get("rangeStart")
        range_end = section.get("rangeEnd")
        if isinstance(range_start, int) and isinstance(range_end, int) and range_end >= range_start:
            expected_numbers.extend(range(range_start, range_end + 1))
    if expected_numbers and question_numbers != expected_numbers:
        if allows_partial_prefix:
            warnings.append(f"题号序列 {question_numbers} 是单大题声明 {expected_numbers} 的前缀")
        else:
            errors.append(f"题号序列 {question_numbers} 与卷面声明 {expected_numbers} 不一致")
    elif len(set(question_numbers)) != len(question_numbers):
        if sequence_allows_numbering_resets(question_numbers, numbering_resets or []):
            warnings.append("题号按专题/练习分组重置")
        else:
            errors.append("题号序列存在重复")
    elif question_numbers:
        for index, (previous, current) in enumerate(zip(question_numbers, question_numbers[1:]), start=1):
            if numbering_resets and index < len(numbering_resets) and numbering_resets[index]:
                continue
            if current != previous + 1:
                warnings.append("题号序列不连续")
                break


def sequence_allows_numbering_resets(numbers: list[int], reset_flags: list[bool]) -> bool:
    if len(numbers) < 2 or not reset_flags or len(reset_flags) != len(numbers):
        return False
    saw_reset = False
    previous = numbers[0]
    for index, current in enumerate(numbers[1:], start=1):
        if reset_flags[index]:
            if current != 1 or previous < 2:
                return False
            saw_reset = True
        elif current != previous + 1:
            return False
        previous = current
    return saw_reset


def validate_images(question: dict[str, Any], asset_paths: set[str], errors: list[str]) -> None:
    for image in question.get("images") or []:
        if not isinstance(image, dict):
            continue
        path = normalize_asset_path(str(image.get("path") or image.get("name") or ""))
        if asset_paths and path and path not in asset_paths and Path(path).name not in {Path(p).name for p in asset_paths}:
            errors.append(f"{question.get('id')} 引用了未知题图 {path}")


def validate_question_placements(
    question: dict[str, Any],
    images: list[dict[str, Any]],
    errors: list[str],
    warnings: list[str],
) -> None:
    placements = question.get("imagePlacements")
    if not isinstance(placements, list):
        return
    result = validate_image_placements(
        images,
        placements,
        question_type=str(question.get("type") or "unknown"),
        option_count=len(question.get("options") or []),
    )
    question["imagePlacementValidation"] = result
    question_id = str(question.get("id") or "question")
    errors.extend(f"{question_id} {message}" for message in result["errors"])
    warnings.extend(f"{question_id} {message}" for message in result["warnings"])


def merge_legacy_images(structured: dict[str, Any], legacy: dict[str, Any]) -> None:
    """Preserve image assignments from the legacy content_list parser when present."""
    def image_key(image: dict[str, Any]) -> str:
        return normalize_asset_path(str(image.get("path") or image.get("name") or image.get("url") or ""))

    def walk_questions(root: dict[str, Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen_objects: set[int] = set()

        def append_question(question: dict[str, Any]) -> None:
            object_id = id(question)
            if object_id in seen_objects:
                return
            seen_objects.add(object_id)
            result.append(question)
            for field in ("subQuestions", "children"):
                for child in question.get(field) or []:
                    if isinstance(child, dict):
                        append_question(child)

        for section in root.get("sections") or []:
            if not isinstance(section, dict):
                continue
            for question in section.get("questions") or []:
                if isinstance(question, dict):
                    append_question(question)
        for question in root.get("questions") or []:
            if isinstance(question, dict):
                append_question(question)
        return result

    primary_owners: dict[str, set[str]] = {}
    for question in walk_questions(structured):
        owner_id = str(question.get("id") or f"question-object-{id(question)}")
        for image in question.get("images") or []:
            if not isinstance(image, dict):
                continue
            key = image_key(image)
            if key:
                primary_owners.setdefault(key, set()).add(owner_id)

    legacy_by_number: dict[int, list[dict[str, Any]]] = {}
    for section in legacy.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for question in section.get("questions") or []:
            if isinstance(question, dict) and isinstance(question.get("number"), int):
                legacy_by_number.setdefault(question["number"], []).append(question)
    occurrence_by_number: dict[int, int] = {}
    for section in structured.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for question in section.get("questions") or []:
            if not isinstance(question, dict):
                continue
            number = question.get("number")
            if not isinstance(number, int):
                continue
            occurrence = occurrence_by_number.get(number, 0)
            occurrence_by_number[number] = occurrence + 1
            if question.get("images"):
                continue
            legacy_candidates = legacy_by_number.get(number) or []
            legacy_question = legacy_candidates[occurrence] if occurrence < len(legacy_candidates) else None
            if legacy_question and legacy_question.get("images"):
                owner_id = str(question.get("id") or f"question-object-{id(question)}")
                accepted_images: list[dict[str, Any]] = []
                warnings = question.setdefault("imageWarnings", [])
                for image in legacy_question.get("images") or []:
                    if not isinstance(image, dict):
                        continue
                    key = image_key(image)
                    conflicting_owners = primary_owners.get(key, set()) - {owner_id}
                    if conflicting_owners:
                        warnings.append(f"旧版候选题图 {key} 已由另一道题持有，未自动合并")
                        continue
                    accepted_images.append(image)
                    if key:
                        primary_owners.setdefault(key, set()).add(owner_id)
                if accepted_images:
                    question["images"] = accepted_images


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
        image["imageId"] = normalize_asset_path(str(image.get("path") or image.get("name") or ""))
        source_evidence = {
            "markdownStart": raw_image.get("start") if isinstance(raw_image.get("start"), int) else None,
            "markdownEnd": raw_image.get("end") if isinstance(raw_image.get("end"), int) else None,
            "pageIndex": raw_image.get("pageIndex"),
            "bbox": raw_image.get("bbox") if isinstance(raw_image.get("bbox"), list) else None,
        }
        if any(value is not None for value in source_evidence.values()):
            image["sourceEvidence"] = source_evidence
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
    if re.match(r"^[一二三四五六七八九十]+[、.．]\s*", heading_text):
        return True
    if re.match(r"^第[一二三四五六七八九十\d]+[部分章节题]\b", heading_text):
        return True
    if len(heading_text) > 80:
        return False
    return False


def is_generic_section_heading_line(stripped: str, heading_text: str) -> bool:
    """Return true for topic-compilation headings that do not imply a question type."""
    text = str(heading_text or "").strip()
    if not text:
        return False
    if len(text) > 48:
        return False
    if QUESTION_NUMBER_RE.match(text):
        return False
    if stripped.startswith("#") and GENERIC_SECTION_HEADING_RE.match(text):
        return True
    return bool(GENERIC_SECTION_HEADING_RE.match(text))


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
