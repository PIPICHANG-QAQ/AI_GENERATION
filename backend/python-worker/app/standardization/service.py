"""Compatibility surface for standardization algorithms.

Only explicit aliases are exposed here.  This module deliberately does not
copy cache state or standardization logic; both continue to have one owner in
``app.import_services`` during the migration.
"""

from app.import_services import (
    AI_STANDARDIZE_CACHE,
    AI_STANDARDIZE_CACHE_LOCK,
    cached_standardize_response,
    clear_standardize_cache,
    finalize_standardize_response,
    raw_ocr_context_for_import_question,
    standardize_cache_key,
    standardize_cache_ttl_seconds,
    standardize_markdown_ai_response,
    store_standardize_response,
)

__all__ = [
    "AI_STANDARDIZE_CACHE",
    "AI_STANDARDIZE_CACHE_LOCK",
    "cached_standardize_response",
    "clear_standardize_cache",
    "finalize_standardize_response",
    "raw_ocr_context_for_import_question",
    "standardize_cache_key",
    "standardize_cache_ttl_seconds",
    "standardize_markdown_ai_response",
    "store_standardize_response",
]
