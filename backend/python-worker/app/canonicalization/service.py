"""Explicit aliases for the existing pure canonicalization functions."""

from app.question_canonicalization import (
    apply_canonicalization,
    build_canonicalization_plan,
    clean_subquestions,
    match_score,
    merge_answer_fields,
    review_evidence,
)

__all__ = [
    "apply_canonicalization",
    "build_canonicalization_plan",
    "clean_subquestions",
    "match_score",
    "merge_answer_fields",
    "review_evidence",
]
