"""Parity checks for the staged standardization module boundary."""

from __future__ import annotations

from app import import_services, question_canonicalization
from app.standardization import service
from app.canonicalization import service as canonicalization_service


def test_standardization_exports_existing_cache_and_response_functions() -> None:
    for name in (
        "standardize_cache_ttl_seconds",
        "standardize_cache_key",
        "clear_standardize_cache",
        "cached_standardize_response",
        "store_standardize_response",
        "standardize_markdown_ai_response",
        "finalize_standardize_response",
        "raw_ocr_context_for_import_question",
    ):
        assert getattr(service, name) is getattr(import_services, name)


def test_standardization_keeps_single_cache_state() -> None:
    assert service.AI_STANDARDIZE_CACHE is import_services.AI_STANDARDIZE_CACHE
    assert service.AI_STANDARDIZE_CACHE_LOCK is import_services.AI_STANDARDIZE_CACHE_LOCK


def test_canonicalization_exports_existing_pure_functions() -> None:
    for name in (
        "build_canonicalization_plan",
        "apply_canonicalization",
        "merge_answer_fields",
        "clean_subquestions",
        "match_score",
        "review_evidence",
    ):
        assert getattr(canonicalization_service, name) is getattr(question_canonicalization, name)
