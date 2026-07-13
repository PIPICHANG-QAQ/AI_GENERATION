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
SUB_QUESTION_LABEL_RE = re.compile(r"\(?\s*([0-9]+|[a-zA-Z])\s*\)?")
INLINE_OPTION_MARKER_RE = re.compile(r"(?<![A-Za-z0-9_])([A-H])[.．、:：]\s*")


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
        if best is not None and best_score >= 0.75 and best_score - runner_up >= 0.12:
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


def apply_canonicalization(
    questions: list[dict[str, Any]], plan: dict[str, Any]
) -> dict[str, Any]:
    """Apply an approved merge plan without replacing paper-side visual content."""
    originals = [item for item in questions if isinstance(item, dict)]
    by_id = {question_id(item): copy.deepcopy(item) for item in originals if question_id(item)}

    for evidence in plan.get("automaticMerges") or []:
        if not isinstance(evidence, dict):
            continue
        canonical_id = str(evidence.get("canonicalId") or "").strip()
        duplicate_id = str(evidence.get("duplicateId") or "").strip()
        canonical = by_id.get(canonical_id)
        duplicate = by_id.get(duplicate_id)
        if canonical is None or duplicate is None or canonical_id == duplicate_id:
            continue
        merge_answer_fields(canonical, duplicate)
        merged_ids = canonical.setdefault("mergedFromQuestionIds", [])
        if duplicate_id not in merged_ids:
            merged_ids.append(duplicate_id)
        for nested_id in duplicate.get("mergedFromQuestionIds") or []:
            if nested_id and nested_id not in merged_ids:
                merged_ids.append(nested_id)
        by_id.pop(duplicate_id, None)

    output: list[dict[str, Any]] = []
    emitted: set[str] = set()
    for original in originals:
        original_id = question_id(original)
        canonical_id = str((plan.get("idMap") or {}).get(original_id) or original_id)
        if canonical_id in emitted or canonical_id not in by_id:
            continue
        question = by_id.pop(canonical_id)
        raw_children = question.get("subQuestions")
        if not isinstance(raw_children, list):
            raw_children = question.get("children") if isinstance(question.get("children"), list) else []
        cleaned, issues = clean_subquestions(raw_children)
        question["subQuestions"] = cleaned
        question["children"] = cleaned
        if issues:
            question.setdefault("canonicalizationIssues", []).extend(issues)
        output.append(question)
        emitted.add(canonical_id)

    for remaining_id, question in by_id.items():
        if remaining_id in emitted:
            continue
        cleaned, issues = clean_subquestions(
            question.get("subQuestions")
            if isinstance(question.get("subQuestions"), list)
            else question.get("children") or []
        )
        question["subQuestions"] = cleaned
        question["children"] = cleaned
        if issues:
            question.setdefault("canonicalizationIssues", []).extend(issues)
        output.append(question)

    return {"questions": output, "plan": copy.deepcopy(plan)}


def merge_answer_fields(canonical: dict[str, Any], duplicate: dict[str, Any]) -> None:
    """Fill answer-side fields and record conflicts, leaving paper visuals untouched."""
    for field in ("answer", "analysis"):
        current = str(canonical.get(field) or "").strip()
        incoming = str(duplicate.get(field) or "").strip()
        if not incoming:
            continue
        if not current:
            canonical[field] = duplicate.get(field)
        elif current != incoming:
            canonical.setdefault("canonicalizationIssues", []).append(
                {
                    "type": f"{field}-conflict",
                    "field": field,
                    "kept": canonical.get(field),
                    "candidate": duplicate.get(field),
                    "sourceQuestionId": question_id(duplicate),
                }
            )

    canonical_options = [item for item in canonical.get("options") or [] if isinstance(item, dict)]
    duplicate_options = [item for item in duplicate.get("options") or [] if isinstance(item, dict)]
    raw_stem = str(canonical.get("stemMarkdown") or "")
    cleaned_stem, had_glued_options = strip_glued_choice_options(raw_stem)
    same_choice_type = (
        str(canonical.get("type") or "").strip().lower() == "choice"
        and str(duplicate.get("type") or "").strip().lower() == "choice"
    )
    if same_choice_type and not canonical_options and duplicate_options and had_glued_options:
        canonical["stemMarkdown"] = cleaned_stem
        if not canonical.get("manualMarkdown") or str(canonical.get("manualMarkdown")) == raw_stem:
            canonical["manualMarkdown"] = cleaned_stem
        canonical["options"] = copy.deepcopy(duplicate_options)

    canonical_children = canonical.get("subQuestions")
    if not isinstance(canonical_children, list):
        canonical_children = canonical.get("children") if isinstance(canonical.get("children"), list) else []
    duplicate_children = duplicate.get("subQuestions")
    if not isinstance(duplicate_children, list):
        duplicate_children = duplicate.get("children") if isinstance(duplicate.get("children"), list) else []

    merged_children = copy.deepcopy(canonical_children)
    child_by_label = {
        normalize_subquestion_label(child.get("label")): child
        for child in merged_children
        if isinstance(child, dict) and normalize_subquestion_label(child.get("label"))
    }
    for incoming in duplicate_children:
        if not isinstance(incoming, dict):
            continue
        label = normalize_subquestion_label(incoming.get("label"))
        target = child_by_label.get(label) if label else None
        if target is None:
            copied = copy.deepcopy(incoming)
            merged_children.append(copied)
            if label:
                child_by_label[label] = copied
            continue
        merge_answer_fields(target, incoming)
    if canonical_children or duplicate_children:
        canonical["subQuestions"] = merged_children
        canonical["children"] = merged_children


def clean_subquestions(
    subquestions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep the first increasing label run and report repeats/regressions."""
    cleaned: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    last_rank: tuple[int, int] | None = None
    for index, child in enumerate(subquestions or []):
        if not isinstance(child, dict):
            continue
        label = normalize_subquestion_label(child.get("label"))
        rank = subquestion_rank(label)
        issue_type = ""
        if label and label in seen:
            issue_type = "repeated-subquestion-label"
        elif rank is not None and last_rank is not None and rank <= last_rank:
            issue_type = "regressing-subquestion-label"
        if issue_type:
            issues.append(
                {
                    "type": issue_type,
                    "label": str(child.get("label") or ""),
                    "sourceIndex": index,
                }
            )
            continue
        copied = copy.deepcopy(child)
        cleaned.append(copied)
        if label:
            seen.add(label)
        if rank is not None:
            last_rank = rank
    return cleaned, issues


def normalize_subquestion_label(value: Any) -> str:
    source = str(value or "").strip()
    match = SUB_QUESTION_LABEL_RE.search(source)
    return match.group(1).lower() if match else source.lower()


def subquestion_rank(label: str) -> tuple[int, int] | None:
    if label.isdigit():
        return (0, int(label))
    if len(label) == 1 and label.isalpha():
        return (1, ord(label.lower()) - ord("a") + 1)
    return None


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
    if str(question.get("type") or "").strip().lower() == "choice" and not option_labels(question):
        value, _ = strip_glued_choice_options(value)
    return re.sub(r"[\s\u3000]+", "", value).strip("。．")


def strip_glued_choice_options(value: str) -> tuple[str, bool]:
    source = str(value or "")
    option_markers = list(INLINE_OPTION_MARKER_RE.finditer(source))
    option_labels = [match.group(1).upper() for match in option_markers]
    if len(option_labels) < 4 or option_labels[:4] != ["A", "B", "C", "D"]:
        return source, False
    stem = source[: option_markers[0].start()].rstrip()
    if not stem.endswith(("（", "(")):
        return source, False
    if stem.endswith("（"):
        stem += " ）"
    elif stem.endswith("("):
        stem += " )"
    return stem, True


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
