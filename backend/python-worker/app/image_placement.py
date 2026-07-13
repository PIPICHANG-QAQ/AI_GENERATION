"""Deterministic image-to-question-target placement and consistency checks."""

from __future__ import annotations

import hashlib
import math
import re
from copy import deepcopy
from typing import Any

from app.choice_layout_assignment import assign_choice_images
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
            has_geometry = isinstance(image.get("pageIndex"), int) and valid_bbox(image.get("bbox"))
            option = next((item for item in options if interval_contains(item, offset)), None)
            child = next((item for item in children if interval_contains(item, offset)), None)
            if option is not None:
                target = {"kind": "option", "optionLabel": str(option.get("label") or "").upper()}
                method = "explicit-offset"
                confidence = 0.96 if has_geometry else 0.9
                reasons = ["inside-option-span"] + (["source-geometry-present"] if has_geometry else ["missing-source-geometry"])
            elif child is not None:
                target = {
                    "kind": "subquestion",
                    "subQuestionId": str(child.get("id") or child.get("label") or ""),
                }
                method = "explicit-offset"
                confidence = 0.96 if has_geometry else 0.9
                reasons = ["inside-subquestion-span"] + (["source-geometry-present"] if has_geometry else ["missing-source-geometry"])
            elif interval_contains(question_boundary, offset):
                target = {"kind": "stem"}
                method = "explicit-offset"
                confidence = 0.96 if has_geometry else 0.9
                reasons = ["inside-question-stem-span"] + (["source-geometry-present"] if has_geometry else ["missing-source-geometry"])
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
                "reviewStatus": "auto" if target["kind"] in ASSIGNED_TARGET_KINDS and confidence >= 0.95 else "needs_review",
            }
        )
    return placements


def reconcile_image_placements(
    placements: list[dict[str, Any]],
    layout_items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Reconcile automatic placements with a global bbox assignment."""
    reconciled = deepcopy(placements)
    labels = option_label_nodes(layout_items)
    label_values = list(dict.fromkeys(label for label, _node in labels))
    global_assignment = assign_choice_images(layout_items, label_values)
    image_nodes = [
        item
        for item in layout_items
        if isinstance(item, dict) and str(item.get("imageRef") or "").strip()
    ]
    conflict_count = 0
    protected_manual_count = 0
    for placement in reconciled:
        image_id = normalize_asset_path(str(placement.get("imageId") or ""))
        image_node = unique_layout_image_node(image_id, image_nodes)
        image_ref = str(image_node.get("imageRef") or "") if isinstance(image_node, dict) else ""
        assigned = global_assignment["assignments"].get(normalize_asset_path(image_ref))
        if not isinstance(assigned, dict):
            continue
        option_label = str(assigned.get("optionLabel") or "")
        geometry_confidence = float(assigned.get("confidence") or 0.0)
        if not option_label:
            continue
        target = placement.get("target") if isinstance(placement.get("target"), dict) else {"kind": "unassigned"}
        inference = placement.setdefault("inference", {})
        reasons = inference.setdefault("reasons", [])
        alternatives = inference.setdefault("alternatives", [])
        current_kind = str(target.get("kind") or "unassigned")
        current_label = str(target.get("optionLabel") or "")
        source_evidence = placement.setdefault("sourceEvidence", {})
        source_evidence.update(
            {
                "pageIndex": image_node.get("pageIndex"),
                "bbox": list(image_node.get("bbox") or []),
                "pageWidth": image_node.get("pageWidth"),
                "pageHeight": image_node.get("pageHeight"),
            }
        )
        if placement.get("reviewStatus") in {"confirmed", "overridden"}:
            protected_manual_count += 1
            if current_kind != "option" or current_label != option_label:
                conflict_count += 1
                if "manual-placement-protected" not in reasons:
                    reasons.append("manual-placement-protected")
                alternatives.append(
                    {
                        "target": {"kind": "option", "optionLabel": option_label},
                        "method": "layout-global",
                        "confidence": geometry_confidence,
                    }
                )
            continue
        if current_kind == "unassigned":
            placement["target"] = {"kind": "option", "optionLabel": option_label}
            inference.update(
                {
                    "method": "layout-global",
                    "confidence": geometry_confidence,
                    "reasons": ["global-option-cell-assignment"],
                    "alternatives": assigned.get("alternatives") or [],
                }
            )
            placement["reviewStatus"] = str(assigned.get("reviewStatus") or "needs_review")
        elif current_kind == "option" and current_label == option_label:
            if "geometry-agreement" not in reasons:
                reasons.append("geometry-agreement")
            inference["confidence"] = max(float(inference.get("confidence") or 0.0), geometry_confidence)
            if geometry_confidence >= 0.95:
                placement["reviewStatus"] = "auto"
        else:
            conflict_count += 1
            previous_target = deepcopy(target)
            placement["target"] = {"kind": "option", "optionLabel": option_label}
            inference.update(
                {
                    "method": "layout-global",
                    "confidence": geometry_confidence,
                    "reasons": [*reasons, "geometry-conflict", "global-option-cell-assignment"],
                    "alternatives": [
                        {
                            "target": previous_target,
                            "method": str(inference.get("method") or "explicit-offset"),
                            "confidence": float(inference.get("confidence") or 0.0),
                        },
                        *(assigned.get("alternatives") or []),
                    ],
                }
            )
            placement["reviewStatus"] = str(assigned.get("reviewStatus") or "needs_review")

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
        "protectedManualCount": protected_manual_count,
        "totalCost": global_assignment.get("totalCost"),
        "secondBestCost": global_assignment.get("secondBestCost"),
        "margin": global_assignment.get("margin"),
        "blockingReasons": global_assignment.get("blockingReasons") or [],
    }


def unique_layout_image_node(image_id: str, image_nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Match full vs provider-relative paths only when the suffix result is unique."""
    normalized_id = normalize_asset_path(image_id)
    exact = [
        item
        for item in image_nodes
        if normalize_asset_path(str(item.get("imageRef") or "")) == normalized_id
    ]
    if len(exact) == 1:
        return exact[0]
    suffix = []
    for item in image_nodes:
        ref = normalize_asset_path(str(item.get("imageRef") or ""))
        if ref and (normalized_id.endswith(f"/{ref}") or ref.endswith(f"/{normalized_id}")):
            suffix.append(item)
    return suffix[0] if len(suffix) == 1 else None


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
        "protectedManualCount": 0,
        "blockingReasons": [],
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
            totals["protectedManualCount"] += summary["protectedManualCount"]
            totals["blockingReasons"].extend(summary["blockingReasons"])
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
    totals["blockingReasons"] = list(dict.fromkeys(totals["blockingReasons"]))
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


def valid_bbox(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= 4
        and all(isinstance(item, (int, float)) for item in value[:4])
        and value[2] > value[0]
        and value[3] > value[1]
    )
def validate_image_placements(
    images: list[dict[str, Any]],
    placements: list[dict[str, Any]],
    *,
    question_type: str = "unknown",
    option_count: int = 0,
) -> dict[str, Any]:
    """Validate asset conservation, geometry evidence, and choice invariants."""
    asset_ids = {image_key(image) for image in images if isinstance(image, dict)}
    asset_ids.discard("")
    errors: list[str] = []
    warnings: list[str] = []
    exclusive_owners: dict[str, list[str]] = {}
    blocking_reasons: list[str] = []
    option_image_counts: dict[str, int] = {}
    stem_image_count = 0
    missing_geometry_count = 0

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
            blocking_reasons.append("image_asset_conservation_failed")
        if kind == "unassigned":
            warnings.append(f"题图尚未归属：{image_id}")
        elif placement.get("reviewStatus") == "needs_review":
            warnings.append(f"题图归属需要人工复核：{image_id}")
        if kind not in NON_EXCLUSIVE_TARGET_KINDS and confidence >= 0.9:
            exclusive_owners.setdefault(image_id, []).append(str(placement.get("placementId") or kind))
        if kind == "option":
            option_label = str(target.get("optionLabel") or "").strip().upper()
            if option_label:
                option_image_counts[option_label] = option_image_counts.get(option_label, 0) + 1
        elif kind == "stem":
            stem_image_count += 1
        source_evidence = placement.get("sourceEvidence") if isinstance(placement.get("sourceEvidence"), dict) else {}
        if kind not in NON_EXCLUSIVE_TARGET_KINDS and confidence >= 0.95 and (
            not isinstance(source_evidence.get("pageIndex"), int) or not valid_bbox(source_evidence.get("bbox"))
        ):
            missing_geometry_count += 1
            blocking_reasons.append("missing_image_geometry")
        if "manual-placement-protected" in (inference.get("reasons") or []):
            blocking_reasons.append("manual_placement_conflict")

    for image_id, owners in exclusive_owners.items():
        if image_id and len(owners) > 1:
            errors.append(f"题图存在多个高置信归属：{image_id}")
            blocking_reasons.append("option_image_one_to_one_violation")
    if question_type == "choice" and option_count < 2:
        warnings.append("选择题没有有效选项，无法可靠校验选项题图")

    expected_option_count = 0
    if question_type == "choice":
        expected_option_count = 4 if option_count in {3, 4} or len(asset_ids) >= 4 else option_count
    if expected_option_count == 4 and option_count != 4:
        blocking_reasons.append("choice_option_sequence_incomplete")
    missing_option_labels = [
        chr(ord("A") + index)
        for index in range(expected_option_count)
        if option_image_counts.get(chr(ord("A") + index), 0) == 0
    ]
    if stem_image_count and len(asset_ids) >= expected_option_count >= 2 and missing_option_labels:
        blocking_reasons.append("stem_option_geometry_conflict")
    if any(count > 1 for count in option_image_counts.values()) and missing_option_labels:
        blocking_reasons.append("option_image_one_to_one_violation")

    blocking_reasons = list(dict.fromkeys(blocking_reasons))
    blocker_messages = {
        "choice_option_sequence_incomplete": "选择题选项序列不完整",
        "stem_option_geometry_conflict": "题干题图与选项题图布局冲突",
        "option_image_one_to_one_violation": "选项题图不满足一对一归属",
        "missing_image_geometry": "高置信题图归属缺少页码或坐标证据",
        "image_asset_conservation_failed": "题图资源与归属记录不守恒",
        "manual_placement_conflict": "自动归属与人工确认结果冲突",
    }
    errors.extend(blocker_messages[code] for code in blocking_reasons if blocker_messages[code] not in errors)

    return {
        "valid": not errors,
        "blocking": bool(blocking_reasons),
        "blockingReasons": blocking_reasons,
        "errors": errors,
        "warnings": warnings,
        "expectedOptionCount": expected_option_count,
        "optionImageCounts": option_image_counts,
        "missingOptionLabels": missing_option_labels,
        "missingGeometryCount": missing_geometry_count,
        "placementCount": len(placements),
        "unassignedCount": sum(
            1
            for placement in placements
            if isinstance(placement, dict)
            and isinstance(placement.get("target"), dict)
            and placement["target"].get("kind") == "unassigned"
        ),
    }
