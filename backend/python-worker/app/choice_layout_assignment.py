"""Deterministic two-dimensional assignment for choice-option images."""

from __future__ import annotations

import math
import re
from itertools import permutations
from typing import Any


OPTION_LABEL_RE = re.compile(r"^\s*([A-Ha-h])\s*[.．、:：]?\s*$")
AMBIGUOUS_MARGIN = 0.015


def assign_choice_images(
    layout_items: list[dict[str, Any]],
    option_labels: list[str] | None = None,
) -> dict[str, Any]:
    """Assign each image to one option with a global one-to-one constraint."""
    nodes = normalize_layout_nodes(layout_items)
    expected = normalized_option_labels(option_labels)
    label_nodes = select_label_nodes(nodes, expected)
    images = [node for node in nodes if node["kind"] == "image"]
    pages = sorted({int(node["pageIndex"]) for node in [*label_nodes.values(), *images]})
    blocking_reasons: list[str] = []

    if expected and len(label_nodes) != len(expected):
        blocking_reasons.append("choice_option_layout_labels_incomplete")
    if not images:
        return assignment_result({}, label_nodes, pages, blocking_reasons, 0.0, None, None)
    if len(images) > len(label_nodes):
        blocking_reasons.append("option_image_one_to_one_violation")
        return assignment_result({}, label_nodes, pages, blocking_reasons, 0.0, None, None)

    candidates: list[tuple[float, tuple[str, ...]]] = []
    labels = tuple(label_nodes)
    for assigned_labels in permutations(labels, len(images)):
        total = sum(
            image_label_cost(image, label_nodes[label])
            for image, label in zip(images, assigned_labels)
        )
        candidates.append((round(total, 9), assigned_labels))
    candidates.sort(key=lambda value: (value[0], value[1]))
    if not candidates:
        blocking_reasons.append("choice_option_layout_labels_missing")
        return assignment_result({}, label_nodes, pages, blocking_reasons, 0.0, None, None)

    best_cost, best_labels = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    second_cost = second[0] if second else None
    margin = ((second_cost - best_cost) / max(len(images), 1)) if second_cost is not None else 0.0
    ambiguous = second_cost is None or margin < AMBIGUOUS_MARGIN
    if ambiguous:
        blocking_reasons.append("layout_assignment_ambiguous")

    confidence = assignment_confidence(margin, has_second=second is not None)
    assignments: dict[str, dict[str, Any]] = {}
    for index, (image, label) in enumerate(zip(images, best_labels)):
        alternatives = []
        if second is not None and second[1][index] != label:
            alternatives.append(
                {
                    "optionLabel": second[1][index],
                    "method": "layout-global",
                    "totalCost": second_cost,
                }
            )
        assignments[image["imageRef"]] = {
            "optionLabel": label,
            "confidence": confidence,
            "reviewStatus": "needs_review" if ambiguous else "auto",
            "cost": round(image_label_cost(image, label_nodes[label]), 6),
            "alternatives": alternatives,
            "sourceEvidence": {
                "pageIndex": image["pageIndex"],
                "bbox": list(image["bbox"]),
                "pageWidth": image["pageWidth"],
                "pageHeight": image["pageHeight"],
            },
        }
    return assignment_result(
        assignments,
        label_nodes,
        pages,
        blocking_reasons,
        best_cost,
        second_cost,
        margin,
    )


def normalize_layout_nodes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for order, item in enumerate(items or []):
        if not isinstance(item, dict) or not valid_bbox(item.get("bbox")):
            continue
        try:
            page_index = int(item.get("pageIndex"))
        except (TypeError, ValueError):
            continue
        bbox = [float(value) for value in item["bbox"][:4]]
        page_width = positive_number(item.get("pageWidth"), max(1000.0, bbox[2]))
        page_height = positive_number(item.get("pageHeight"), max(1000.0, bbox[3]))
        image_ref = normalize_image_ref(item.get("imageRef"))
        text = str(item.get("text") or "").strip()
        label_match = OPTION_LABEL_RE.match(text)
        kind = "image" if image_ref else "option-label" if label_match else "text"
        nodes.append(
            {
                "kind": kind,
                "label": label_match.group(1).upper() if label_match else "",
                "text": text,
                "imageRef": image_ref,
                "pageIndex": page_index,
                "bbox": bbox,
                "pageWidth": page_width,
                "pageHeight": page_height,
                "order": int(item.get("order") or order),
            }
        )
    return nodes


def normalized_option_labels(labels: list[str] | None) -> list[str]:
    result: list[str] = []
    for value in labels or []:
        label = str(value or "").strip().upper()
        if re.fullmatch(r"[A-H]", label) and label not in result:
            result.append(label)
    return result


def select_label_nodes(
    nodes: list[dict[str, Any]],
    expected: list[str],
) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    allowed = set(expected)
    for node in nodes:
        label = node["label"] if node["kind"] == "option-label" else ""
        if not label or (allowed and label not in allowed) or label in selected:
            continue
        selected[label] = node
    return selected


def image_label_cost(image: dict[str, Any], label: dict[str, Any]) -> float:
    if image["pageIndex"] != label["pageIndex"]:
        return 5.0 + abs(int(image["pageIndex"]) - int(label["pageIndex"]))
    image_x, image_y = bbox_center(image["bbox"])
    label_x, label_y = bbox_center(label["bbox"])
    width = max(float(image["pageWidth"]), float(label["pageWidth"]), 1.0)
    height = max(float(image["pageHeight"]), float(label["pageHeight"]), 1.0)
    dx = abs(image_x - label_x) / width
    dy = abs(image_y - label_y) / height
    cost = 1.4 * dx + 2.0 * dy
    if intervals_overlap(image["bbox"][0], image["bbox"][2], label["bbox"][0], label["bbox"][2]):
        cost -= 0.08
    return max(0.0, cost)


def assignment_confidence(margin: float, *, has_second: bool) -> float:
    if not has_second or margin < AMBIGUOUS_MARGIN:
        return 0.84
    return round(min(0.98, 0.92 + margin * 2.0), 3)


def assignment_result(
    assignments: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    pages: list[int],
    blocking_reasons: list[str],
    total_cost: float,
    second_best_cost: float | None,
    margin: float | None,
) -> dict[str, Any]:
    return {
        "assignments": assignments,
        "cells": [
            {
                "optionLabel": label,
                "pageIndex": node["pageIndex"],
                "labelBbox": list(node["bbox"]),
            }
            for label, node in labels.items()
        ],
        "pageIndexes": pages,
        "totalCost": round(total_cost, 6),
        "secondBestCost": round(second_best_cost, 6) if second_best_cost is not None else None,
        "margin": round(margin, 6) if margin is not None else None,
        "blockingReasons": list(dict.fromkeys(blocking_reasons)),
    }


def valid_bbox(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= 4
        and all(isinstance(item, (int, float)) for item in value[:4])
        and value[2] > value[0]
        and value[3] > value[1]
    )


def bbox_center(bbox: list[float]) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def intervals_overlap(a1: float, a2: float, b1: float, b2: float) -> bool:
    return min(a2, b2) > max(a1, b1)


def positive_number(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) and parsed > 0 else default


def normalize_image_ref(value: Any) -> str:
    return str(value or "").split("?", 1)[0].split("#", 1)[0].replace("\\", "/").lstrip("./")
