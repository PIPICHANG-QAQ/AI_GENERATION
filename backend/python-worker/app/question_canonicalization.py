"""Evidence-based canonicalization for paper and answer-section questions."""

from __future__ import annotations

from difflib import SequenceMatcher
import copy
import re
from typing import Any


ANSWER_HEADING_RE = re.compile(
    r"(?im)^\s*#{0,6}\s*(参考答案与试题解析|参考答案|答案与解析|试题答案|详解)\s*$"
)
TASKS_BLOCK_RE = re.compile(r"\\begin\{tasks\}[\s\S]*?\\end\{tasks\}", re.IGNORECASE)
QUESTION_PREFIX_RE = re.compile(r"^\s*\d+\s*[.．、]\s*")


def build_canonicalization_plan(markdown: str, questions: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a JSON-safe plan for merging answer-zone duplicates into paper questions."""
    answer_start = answer_zone_start(markdown)
    valid_questions = [item for item in questions if isinstance(item, dict) and question_id(item)]
    id_map = {question_id(item): question_id(item) for item in valid_questions}
    paper = [item for item in valid_questions if evidence_start(item) < answer_start]
    answers = [item for item in valid_questions if evidence_start(item) >= answer_start]
    automatic_merges: list[dict[str, Any]] = []
    review_items: list[dict[str, Any]] = []

    for duplicate in answers:
        ranked = sorted(
            ((match_score(candidate, duplicate), candidate) for candidate in paper),
            key=lambda item: item[0],
            reverse=True,
        )
        best_score, best = ranked[0] if ranked else (0.0, None)
        runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
        if best is not None and best_score >= 0.85 and best_score - runner_up >= 0.08:
            canonical_id = question_id(best)
            duplicate_id = question_id(duplicate)
            id_map[duplicate_id] = canonical_id
            automatic_merges.append(merge_evidence(best, duplicate, best_score))
        elif best is not None and best_score >= 0.65:
            review_items.append(review_evidence(best, duplicate, best_score, runner_up))

    return {
        "version": "question-canonicalization.v1",
        "answerZoneStart": answer_start if answer_start <= len(str(markdown or "")) else None,
        "idMap": id_map,
        "automaticMerges": automatic_merges,
        "reviewItems": review_items,
        "blockingIssues": ["ambiguous-duplicate-question"] if review_items else [],
    }


def answer_zone_start(markdown: str) -> int:
    source = str(markdown or "")
    match = ANSWER_HEADING_RE.search(source)
    return match.start() if match else len(source) + 1


def evidence_start(question: dict[str, Any]) -> int:
    evidence = question.get("sourceEvidence") if isinstance(question.get("sourceEvidence"), dict) else {}
    try:
        return max(0, int(evidence.get("start") or 0))
    except (TypeError, ValueError):
        return 0


def stem_core(question: dict[str, Any]) -> str:
    value = str(question.get("stemMarkdown") or question.get("manualMarkdown") or question.get("stem") or "")
    value = TASKS_BLOCK_RE.sub("", value)
    value = QUESTION_PREFIX_RE.sub("", value)
    value = re.sub(r"【\s*(?:分析|解答|答案|点评|详解)\s*】[\s\S]*$", "", value)
    return re.sub(r"[\s\u3000]+", "", value).strip("。．")


def match_score(paper: dict[str, Any], answer: dict[str, Any]) -> float:
    paper_number = parse_number(paper.get("number"))
    answer_number = parse_number(answer.get("number"))
    number_score = 0.45 if paper_number > 0 and paper_number == answer_number else 0.0
    left = stem_core(paper)
    right = stem_core(answer)
    stem_score = 0.35 * SequenceMatcher(None, left, right).ratio() if left and right else 0.0
    visual_score = 0.10 * option_image_similarity(paper, answer)
    section_score = 0.10 * type_section_similarity(paper, answer)
    return round(number_score + stem_score + visual_score + section_score, 6)


def option_image_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_options = option_labels(left)
    right_options = option_labels(right)
    if left_options and right_options:
        return len(left_options & right_options) / max(len(left_options | right_options), 1)
    left_images = image_labels(left)
    right_images = image_labels(right)
    if left_images and right_images:
        return len(left_images & right_images) / max(len(left_images | right_images), 1)
    return 0.0


def type_section_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_type = str(left.get("type") or "").strip().lower()
    right_type = str(right.get("type") or "").strip().lower()
    if left_type and right_type:
        return 1.0 if left_type == right_type else 0.0
    return 0.5


def merge_evidence(canonical: dict[str, Any], duplicate: dict[str, Any], score: float) -> dict[str, Any]:
    return {
        "canonicalId": question_id(canonical),
        "duplicateId": question_id(duplicate),
        "number": parse_number(canonical.get("number")),
        "score": score,
        "reasons": match_reasons(canonical, duplicate),
    }


def review_evidence(
    canonical: dict[str, Any],
    duplicate: dict[str, Any],
    score: float,
    runner_up_score: float,
) -> dict[str, Any]:
    return {
        "canonicalId": question_id(canonical),
        "duplicateId": question_id(duplicate),
        "number": parse_number(duplicate.get("number")),
        "score": score,
        "runnerUpScore": runner_up_score,
        "reasons": match_reasons(canonical, duplicate),
    }


def match_reasons(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if parse_number(left.get("number")) == parse_number(right.get("number")):
        reasons.append("same-question-number")
    if stem_core(left) == stem_core(right) and stem_core(left):
        reasons.append("same-stem-core")
    elif stem_core(left) and stem_core(right):
        reasons.append("similar-stem-core")
    if option_image_similarity(left, right) > 0:
        reasons.append("matching-option-or-image-evidence")
    if type_section_similarity(left, right) == 1.0:
        reasons.append("same-question-type")
    return reasons


def option_labels(question: dict[str, Any]) -> set[str]:
    return {
        str(item.get("label") or "").strip().upper()
        for item in question.get("options") or []
        if isinstance(item, dict) and str(item.get("label") or "").strip()
    }


def image_labels(question: dict[str, Any]) -> set[str]:
    return {
        str(item.get("label") or item.get("refLabel") or "").strip()
        for item in question.get("images") or []
        if isinstance(item, dict) and str(item.get("label") or item.get("refLabel") or "").strip()
    }


def question_id(question: dict[str, Any]) -> str:
    return str(question.get("id") or "").strip()


def parse_number(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

