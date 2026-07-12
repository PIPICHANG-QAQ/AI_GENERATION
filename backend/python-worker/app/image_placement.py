"""Deterministic image-to-question-target placement and consistency checks."""

from __future__ import annotations

import hashlib
import math
import re
from copy import deepcopy
from typing import Any

from app.question_markdown import normalize_asset_path


ASSIGNED_TARGET_KINDS = {"stem", "option", "subquestion", "shared", "answer", "analysis"}
NON_EXCLUSIVE_TARGET_KINDS = {"shared", "unassigned", "decoration"}
OPTION_LABEL_RE = re.compile(r"^\s*([A-Ha-h])\s*[.．、]?\s*$")


def image_key(image: dict[str, Any]) -> str:
    return normalize_asset_path(str(image.get("imageId") or image.get("path") or image.get("name") or image.get("url") or ""))


def interval_contains(span: dict[str, Any], offset: int) -> bool:
    start = span.get("start")
    end = span.get("end")
    return isinstance(start, int) and isinstance(end, int) and start <= offset < end


def stable_placement_id(question_id: str, image_id: str, order: int) -> str:
    digest = hashlib.sha1(f"{question_id}|{image_id}|{order}".encode("utf-8")).hexdigest()[:12]
    return f"placement-{digest}"


def build_image_placements(
    question_boundary: dict[str, Any],
    images: list[dict[str, Any]],
    layout_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Assign images by explicit Markdown intervals; geometry is reconciled separately."""
    del layout_items  # Reserved for the non-destructive geometry reconciliation stage.
    question_id = str(question_boundary.get("id") or "question")
    options = [item for item in question_boundary.get("options") or [] if isinstance(item, dict)]
    children = [
        item
        for item in (question_boundary.get("subQuestions") or question_boundary.get("children") or [])
        if isinstance(item, dict)
    ]
    placements: list[dict[str, Any]] = []
    for order, image in enumerate(images):
        if not isinstance(image, dict):
            continue
        image_id = image_key(image)
        if not image_id:
            continue
        offset = image.get("start")
        target: dict[str, Any] = {"kind": "unassigned"}
        method = "rule"
        confidence = 0.0
        reasons = ["missing-markdown-offset"]

        if isinstance(offset, int):
            option = next((item for item in options if interval_contains(item, offset)), None)
            child = next((item for item in children if interval_contains(item, offset)), None)
            if option is not None:
                target = {"kind": "option", "optionLabel": str(option.get("label") or "").upper()}
                method = "explicit-offset"
                confidence = 0.99
                reasons = ["inside-option-span"]
            elif child is not None:
                target = {
                    "kind": "subquestion",
                    "subQuestionId": str(child.get("id") or child.get("label") or ""),
                }
                method = "explicit-offset"
                confidence = 0.99
                reasons = ["inside-subquestion-span"]
            elif interval_contains(question_boundary, offset):
                target = {"kind": "stem"}
                method = "explicit-offset"
                confidence = 0.98
                reasons = ["inside-question-stem-span"]
            else:
                reasons = ["outside-question-span"]

        source_evidence = {
            "markdownStart": image.get("start") if isinstance(image.get("start"), int) else None,
            "markdownEnd": image.get("end") if isinstance(image.get("end"), int) else None,
            "pageIndex": image.get("pageIndex"),
            "bbox": image.get("bbox") if isinstance(image.get("bbox"), list) else None,
        }
        placements.append(
            {
                "placementId": stable_placement_id(question_id, image_id, order),
                "imageId": image_id,
                "target": target,
                "order": order,
                "sourceEvidence": source_evidence,
                "inference": {
                    "method": method,
                    "confidence": confidence,
                    "reasons": reasons,
                    "alternatives": [],
                },
                "reviewStatus": "auto" if target["kind"] in ASSIGNED_TARGET_KINDS else "needs_review",
            }
        )
    return placements


def reconcile_image_placements(
    placements: list[dict[str, Any]],
    layout_items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Corroborate placements with bbox geometry without overriding explicit offsets."""
    reconciled = deepcopy(placements)
    labels = option_label_nodes(layout_items)
    images_by_ref = {
        normalize_asset_path(str(item.get("imageRef") or "")): item
        for item in layout_items
        if isinstance(item, dict) and str(item.get("imageRef") or "").strip()
    }
    conflict_count = 0
    for placement in reconciled:
        image_id = normalize_asset_path(str(placement.get("imageId") or ""))
        image_node = images_by_ref.get(image_id)
        candidate = geometry_option_candidate(image_node, labels)
        if candidate is None:
            continue
        option_label, geometry_confidence = candidate
        target = placement.get("target") if isinstance(placement.get("target"), dict) else {"kind": "unassigned"}
        inference = placement.setdefault("inference", {})
        reasons = inference.setdefault("reasons", [])
        alternatives = inference.setdefault("alternatives", [])
        current_kind = str(target.get("kind") or "unassigned")
        current_label = str(target.get("optionLabel") or "")
        if current_kind == "unassigned":
            placement["target"] = {"kind": "option", "optionLabel": option_label}
            inference.update(
                {
                    "method": "geometry",
                    "confidence": geometry_confidence,
                    "reasons": ["nearest-option-cell", "geometry-margin-sufficient"],
                    "alternatives": [],
                }
            )
            placement["reviewStatus"] = "auto" if geometry_confidence >= 0.9 else "needs_review"
        elif current_kind == "option" and current_label == option_label:
            if "geometry-agreement" not in reasons:
                reasons.append("geometry-agreement")
        else:
            conflict_count += 1
            if "geometry-conflict" not in reasons:
                reasons.append("geometry-conflict")
            alternatives.append(
                {
                    "target": {"kind": "option", "optionLabel": option_label},
                    "method": "geometry",
                    "confidence": geometry_confidence,
                }
            )
            inference["confidence"] = min(float(inference.get("confidence") or 0.0), 0.85)
            placement["reviewStatus"] = "needs_review"

    method_counts: dict[str, int] = {}
    assigned_counts: dict[str, int] = {}
    unassigned_count = 0
    for placement in reconciled:
        inference = placement.get("inference") if isinstance(placement.get("inference"), dict) else {}
        method = str(inference.get("method") or "unknown")
        method_counts[method] = method_counts.get(method, 0) + 1
        target = placement.get("target") if isinstance(placement.get("target"), dict) else {}
        kind = str(target.get("kind") or "unassigned")
        assigned_counts[kind] = assigned_counts.get(kind, 0) + 1
        if kind == "unassigned":
            unassigned_count += 1
    return reconciled, {
        "placementCount": len(reconciled),
        "assignedCounts": assigned_counts,
        "methodCounts": method_counts,
        "conflictCount": conflict_count,
        "unassignedCount": unassigned_count,
    }


def reconcile_structure_image_placements(
    structured: dict[str, Any],
    layout_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply read-only layout evidence to each question's placements and return a safe summary."""
    totals = {
        "applied": bool(layout_items),
        "placementCount": 0,
        "assignedCounts": {},
        "methodCounts": {},
        "conflictCount": 0,
        "unassignedCount": 0,
    }
    seen_questions: set[int] = set()

    def reconcile_question(question: dict[str, Any]) -> None:
        object_id = id(question)
        if object_id in seen_questions:
            return
        seen_questions.add(object_id)
        placements = question.get("imagePlacements")
        if isinstance(placements, list):
            question_items = layout_items_for_evidence(layout_items, question.get("sourceEvidence"))
            reconciled, summary = reconcile_image_placements(placements, question_items)
            question["imagePlacements"] = reconciled
            totals["placementCount"] += summary["placementCount"]
            totals["conflictCount"] += summary["conflictCount"]
            totals["unassignedCount"] += summary["unassignedCount"]
            for field in ("assignedCounts", "methodCounts"):
                for key, value in summary[field].items():
                    totals[field][key] = totals[field].get(key, 0) + value
        for field in ("subQuestions", "children"):
            for child in question.get(field) or []:
                if isinstance(child, dict):
                    reconcile_question(child)

    for section in structured.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for question in section.get("questions") or []:
            if isinstance(question, dict):
                reconcile_question(question)
    for question in structured.get("questions") or []:
        if isinstance(question, dict):
            reconcile_question(question)
    return totals


def layout_items_for_evidence(layout_items: list[dict[str, Any]], evidence: Any) -> list[dict[str, Any]]:
    if not isinstance(evidence, dict):
        return []
    start = evidence.get("start")
    end = evidence.get("end")
    if not isinstance(start, int) or not isinstance(end, int) or end <= start:
        return []
    ordered = sorted(layout_items, key=lambda item: int(item.get("order") or 0))
    lower_order = -1
    upper_order = math.inf
    for item in ordered:
        markdown_start = item.get("markdownStart")
        markdown_end = item.get("markdownEnd")
        order = int(item.get("order") or 0)
        if not isinstance(markdown_start, int):
            continue
        if isinstance(markdown_end, int) and markdown_end <= start:
            lower_order = max(lower_order, order)
        elif markdown_start >= end:
            upper_order = min(upper_order, order)
    return [
        item
        for item in ordered
        if lower_order < int(item.get("order") or 0) < upper_order
        and (
            not isinstance(item.get("markdownStart"), int)
            or (
                int(item.get("markdownEnd") or item["markdownStart"] + 1) > start
                and item["markdownStart"] < end
            )
        )
    ]


def option_label_nodes(layout_items: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    nodes: list[tuple[str, dict[str, Any]]] = []
    for item in layout_items:
        if not isinstance(item, dict) or not valid_bbox(item.get("bbox")):
            continue
        match = OPTION_LABEL_RE.match(str(item.get("text") or ""))
        if match:
            nodes.append((match.group(1).upper(), item))
    return nodes


def geometry_option_candidate(
    image_node: dict[str, Any] | None,
    labels: list[tuple[str, dict[str, Any]]],
) -> tuple[str, float] | None:
    if not isinstance(image_node, dict) or not valid_bbox(image_node.get("bbox")):
        return None
    page_index = image_node.get("pageIndex")
    image_center = bbox_center(image_node["bbox"])
    scored: list[tuple[float, str]] = []
    for label, node in labels:
        if node.get("pageIndex") != page_index:
            continue
        label_center = bbox_center(node["bbox"])
        distance = math.dist(image_center, label_center)
        if image_center[1] < label_center[1]:
            distance *= 1.5
        scored.append((distance, label))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0])
    best_distance, best_label = scored[0]
    if len(scored) == 1:
        return (best_label, 0.9) if best_distance <= 600 else None
    second_distance = scored[1][0]
    margin = second_distance - best_distance
    if margin < 30 or best_distance > second_distance * 0.8:
        return None
    confidence = min(0.97, 0.9 + 0.07 * (margin / max(second_distance, 1.0)))
    return best_label, round(confidence, 3)


def valid_bbox(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= 4
        and all(isinstance(item, (int, float)) for item in value[:4])
        and value[2] > value[0]
        and value[3] > value[1]
    )


def bbox_center(bbox: list[float]) -> tuple[float, float]:
    return ((float(bbox[0]) + float(bbox[2])) / 2.0, (float(bbox[1]) + float(bbox[3])) / 2.0)


def validate_image_placements(
    images: list[dict[str, Any]],
    placements: list[dict[str, Any]],
    *,
    question_type: str = "unknown",
    option_count: int = 0,
) -> dict[str, Any]:
    """Validate asset conservation and exclusive high-confidence ownership."""
    asset_ids = {image_key(image) for image in images if isinstance(image, dict)}
    asset_ids.discard("")
    errors: list[str] = []
    warnings: list[str] = []
    exclusive_owners: dict[str, list[str]] = {}

    for placement in placements:
        if not isinstance(placement, dict):
            continue
        image_id = normalize_asset_path(str(placement.get("imageId") or ""))
        target = placement.get("target") if isinstance(placement.get("target"), dict) else {}
        kind = str(target.get("kind") or "unassigned")
        inference = placement.get("inference") if isinstance(placement.get("inference"), dict) else {}
        confidence = float(inference.get("confidence") or 0.0)
        if image_id not in asset_ids:
            errors.append(f"题图放置引用的资源不存在：{image_id or '<empty>'}")
        if kind == "unassigned":
            warnings.append(f"题图尚未归属：{image_id}")
        if kind not in NON_EXCLUSIVE_TARGET_KINDS and confidence >= 0.9:
            exclusive_owners.setdefault(image_id, []).append(str(placement.get("placementId") or kind))

    for image_id, owners in exclusive_owners.items():
        if image_id and len(owners) > 1:
            errors.append(f"题图存在多个高置信归属：{image_id}")
    if question_type == "choice" and option_count < 2:
        warnings.append("选择题没有有效选项，无法可靠校验选项题图")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "placementCount": len(placements),
        "unassignedCount": sum(
            1
            for placement in placements
            if isinstance(placement, dict)
            and isinstance(placement.get("target"), dict)
            and placement["target"].get("kind") == "unassigned"
        ),
    }
