"""Shared AI runtime compatibility surface.

This module deliberately re-exports the existing LLM runtime objects instead
of copying or wrapping them.  There must be exactly one set of environment
option readers, router functions, caches, locks, and semaphores in a worker
process.  The implementation still lives in :mod:`app.llm_splitter` for this
small migration slice; later slices can move the implementation here while
keeping these names stable.

Do not add business logic, prompts, retry policy, or concurrency limits here.
"""

from app.llm_splitter import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    LLM_ENDPOINT_SEMAPHORES,
    LLM_ENDPOINT_SEMAPHORES_LOCK,
    LLM_KEY_HINT,
    LLM_ROUTER_CACHE,
    LLM_ROUTER_CACHE_LOCK,
    LLM_ROUTER_CACHE_VERSION,
    LLM_TASK_SEMAPHORES,
    LLM_TASK_SEMAPHORES_LOCK,
    VALID_QUESTION_TYPES,
    bool_env,
    cached_llm_response,
    endpoint_semaphore,
    endpoint_timeout_seconds,
    external_llm_status,
    float_env,
    infer_provider,
    int_env,
    llm_api_key,
    llm_cache_key,
    llm_json_retry_payload,
    llm_router_cache_ttl_seconds,
    llm_runtime_options,
    llm_status,
    local_llm_status,
    public_endpoint_status,
    route_llm_endpoints,
    router_mode,
    store_llm_response,
    task_semaphore,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "LLM_ENDPOINT_SEMAPHORES",
    "LLM_ENDPOINT_SEMAPHORES_LOCK",
    "LLM_KEY_HINT",
    "LLM_ROUTER_CACHE",
    "LLM_ROUTER_CACHE_LOCK",
    "LLM_ROUTER_CACHE_VERSION",
    "LLM_TASK_SEMAPHORES",
    "LLM_TASK_SEMAPHORES_LOCK",
    "VALID_QUESTION_TYPES",
    "bool_env",
    "cached_llm_response",
    "endpoint_semaphore",
    "endpoint_timeout_seconds",
    "external_llm_status",
    "float_env",
    "infer_provider",
    "int_env",
    "llm_api_key",
    "llm_cache_key",
    "llm_json_retry_payload",
    "llm_router_cache_ttl_seconds",
    "llm_runtime_options",
    "llm_status",
    "local_llm_status",
    "public_endpoint_status",
    "route_llm_endpoints",
    "router_mode",
    "store_llm_response",
    "task_semaphore",
]
