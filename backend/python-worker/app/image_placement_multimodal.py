"""Constrained protocol for optional low-confidence placement review."""

from __future__ import annotations

import copy
from typing import Any, Callable


PlacementResolver = Callable[[dict[str, Any]], dict[str, Any]]


def resolve_ambiguous_assignments(
    crop_evidence: list[dict[str, Any]],
    candidates: dict[str, dict[str, Any]],
    option_labels: list[str],
    resolver: PlacementResolver,
    *,
    enabled: bool,
    has_conflict: bool = False,
) -> dict[str, Any]:
    """Call an injected vision resolver and accept only a constrained mapping."""
    original = copy.deepcopy(candidates)
    if not enabled:
        return outcome(False, "disabled", original)
    if not has_conflict and not any(
        0.8 <= float(value.get("confidence") or 0.0) < 0.95
        for value in candidates.values()
        if isinstance(value, dict)
    ):
        return outcome(False, "not-eligible", original)

    payload = {
        "instruction": "只返回题图归属映射，不得修改题干、选项、答案或图片资产",
        "crops": copy.deepcopy(crop_evidence),
        "optionLabels": normalized_labels(option_labels),
        "images": [
            {
                "imageId": image_id,
                "candidate": value.get("optionLabel"),
                "confidence": float(value.get("confidence") or 0.0),
            }
            for image_id, value in candidates.items()
            if isinstance(value, dict)
        ],
    }
    try:
        response = resolver(payload)
    except Exception as exc:
        return {**outcome(False, "resolver-failed", original), "error": str(exc)}

    assignments = response.get("assignments") if isinstance(response, dict) else None
    validated = validate_assignment_mapping(assignments, set(candidates), set(payload["optionLabels"]))
    if validated is None:
        return outcome(False, "invalid-response", original)
    return {
        "applied": True,
        "reason": "resolved",
        "assignments": validated,
        "candidates": original,
    }


def validate_assignment_mapping(
    value: Any,
    image_ids: set[str],
    option_labels: set[str],
) -> dict[str, str] | None:
    if not isinstance(value, dict) or set(map(str, value)) != image_ids:
        return None
    allowed = {*option_labels, "stem", "unassigned"}
    result: dict[str, str] = {}
    used_options: set[str] = set()
    for raw_image_id, raw_target in value.items():
        image_id = str(raw_image_id)
        target = str(raw_target or "").strip()
        if image_id not in image_ids or target not in allowed:
            return None
        if target in option_labels:
            if target in used_options:
                return None
            used_options.add(target)
        result[image_id] = target
    return result


def normalized_labels(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values or []:
        label = str(value or "").strip().upper()
        if len(label) == 1 and "A" <= label <= "H" and label not in result:
            result.append(label)
    return result


def outcome(applied: bool, reason: str, candidates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "applied": applied,
        "reason": reason,
        "assignments": {},
        "candidates": candidates,
    }
