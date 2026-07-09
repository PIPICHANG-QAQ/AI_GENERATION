"""大模型拆题、标准化和解析 worker。

本模块只封装 DeepSeek / OpenAI 兼容模型调用、Prompt 组装和返回结果归一化。
业务状态、任务记录、答案写回和失败重试由 Java 主后端负责。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError, as_completed
import copy
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import httpx


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-pro"
VALID_QUESTION_TYPES = {"choice", "fill_blank", "solution", "unknown"}
LLM_KEY_HINT = "未配置本地模型或外部 DEEPSEEK_API_KEY / DASHSCOPE_API_KEY / ALIYUN_LLM_API_KEY"
LLM_ROUTER_CACHE_VERSION = "2026-07-07-hybrid-llm-router-v1"
LLM_ROUTER_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
LLM_ROUTER_CACHE_LOCK = threading.RLock()
LLM_ENDPOINT_SEMAPHORES: dict[str, threading.BoundedSemaphore] = {}
LLM_ENDPOINT_SEMAPHORES_LOCK = threading.RLock()
LLM_TASK_SEMAPHORES: dict[str, threading.BoundedSemaphore] = {}
LLM_TASK_SEMAPHORES_LOCK = threading.RLock()


def llm_api_key() -> str | None:
    """Return the configured external OpenAI-compatible LLM API key."""
    return os.getenv("DEEPSEEK_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or os.getenv("ALIYUN_LLM_API_KEY")


def infer_provider(base_url: str, model: str) -> str:
    configured = os.getenv("LLM_PROVIDER") or os.getenv("DASHSCOPE_PROVIDER")
    if configured:
        return configured
    base = str(base_url or "").lower()
    if "dashscope" in base or "aliyun" in base:
        return "dashscope"
    if "deepseek" in base:
        return "deepseek"
    model_name = str(model or "").lower()
    if "deepseek" in model_name:
        return "deepseek"
    return "openai-compatible"


def llm_status() -> dict[str, Any]:
    """返回大模型配置和可用性状态。"""
    enabled = os.getenv("ENABLE_LLM_SPLIT", "true").lower() not in {"0", "false", "no", "off"}
    external = external_llm_status()
    local = local_llm_status()
    preferred = local if router_mode() == "local" and local.get("configured") else external
    if not preferred.get("configured") and local.get("configured"):
        preferred = local
    if os.getenv("DEEPSEEK_API_KEY"):
        model = os.getenv("DEEPSEEK_MODEL") or os.getenv("LLM_MODEL") or os.getenv("DASHSCOPE_MODEL") or DEFAULT_MODEL
        base_url = os.getenv("DEEPSEEK_BASE_URL") or os.getenv("LLM_BASE_URL") or os.getenv("DASHSCOPE_BASE_URL") or DEFAULT_BASE_URL
    else:
        model = os.getenv("DASHSCOPE_MODEL") or os.getenv("LLM_MODEL") or os.getenv("DEEPSEEK_MODEL") or DEFAULT_MODEL
        base_url = os.getenv("DASHSCOPE_BASE_URL") or os.getenv("LLM_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL
    return {
        "enabled": enabled,
        "configured": bool(local.get("configured") or external.get("configured")),
        "provider": preferred.get("provider") or infer_provider(base_url, model),
        "model": preferred.get("model") or model,
        "baseUrl": preferred.get("baseUrl") or base_url,
        "routerMode": router_mode(),
        "local": public_endpoint_status(local),
        "external": public_endpoint_status(external),
    }


def router_mode() -> str:
    """Return hybrid routing mode."""
    mode = os.getenv("LLM_ROUTER_MODE", "external").strip().lower()
    if mode not in {"hybrid", "local", "external"}:
        mode = "hybrid"
    return mode


def public_endpoint_status(endpoint: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(endpoint.get("enabled")),
        "configured": bool(endpoint.get("configured")),
        "provider": endpoint.get("provider"),
        "model": endpoint.get("model"),
        "baseUrl": endpoint.get("baseUrl"),
        "role": endpoint.get("role"),
    }


def external_llm_status() -> dict[str, Any]:
    """Return external full-capability model endpoint configuration."""
    api_key = llm_api_key()
    if os.getenv("DEEPSEEK_API_KEY"):
        model = os.getenv("DEEPSEEK_MODEL") or os.getenv("LLM_MODEL") or os.getenv("DASHSCOPE_MODEL") or DEFAULT_MODEL
        base_url = os.getenv("DEEPSEEK_BASE_URL") or os.getenv("LLM_BASE_URL") or os.getenv("DASHSCOPE_BASE_URL") or DEFAULT_BASE_URL
    else:
        model = os.getenv("DASHSCOPE_MODEL") or os.getenv("LLM_MODEL") or os.getenv("DEEPSEEK_MODEL") or DEFAULT_MODEL
        base_url = os.getenv("DASHSCOPE_BASE_URL") or os.getenv("LLM_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL
    return {
        "role": "external",
        "enabled": bool_env("LLM_EXTERNAL_ENABLED", True),
        "configured": bool(api_key),
        "apiKey": api_key,
        "provider": infer_provider(base_url, model),
        "model": model,
        "baseUrl": base_url,
    }


def local_llm_status() -> dict[str, Any]:
    """Return server-local OpenAI-compatible model endpoint configuration."""
    enabled = bool_env("LOCAL_LLM_ENABLED", False)
    base_url = os.getenv("LOCAL_LLM_BASE_URL", "").strip()
    model = os.getenv("LOCAL_LLM_MODEL", "aux-qwen3-32b-fp8").strip()
    api_key = os.getenv("LOCAL_LLM_API_KEY", "EMPTY").strip() or "EMPTY"
    provider = os.getenv("LOCAL_LLM_PROVIDER", "").strip() or infer_provider(base_url, model)
    if provider == "openai-compatible":
        provider = "local-openai-compatible"
    return {
        "role": "local",
        "enabled": enabled,
        "configured": enabled and bool(base_url) and bool(model),
        "apiKey": api_key,
        "provider": provider,
        "model": model,
        "baseUrl": base_url,
    }


def llm_json_retry_payload(payload: dict[str, Any], reason: str, required_fields: list[str]) -> dict[str, Any]:
    """Build a stricter second-attempt payload after malformed JSON/schema output."""
    retry_payload = {**payload}
    retry_messages = list(payload.get("messages") or [])
    fields = "、".join(required_fields)
    retry_messages.append(
        {
            "role": "user",
            "content": (
                f"上一轮输出无法被系统接收：{reason}。"
                f"请只返回一个 JSON 对象，不要 Markdown 代码块、不要解释文字。"
                f"必须包含字段：{fields}。"
                "字段没有内容时返回空字符串或空数组，不要省略字段。"
            ),
        }
    )
    retry_payload["messages"] = retry_messages
    retry_payload["temperature"] = 0.0
    return retry_payload


def int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    """Read and clamp an integer environment option."""
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def bool_env(name: str, default: bool) -> bool:
    """Read a boolean environment option."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def llm_runtime_options() -> dict[str, Any]:
    """Return LLM execution controls used by OCR-Flow."""
    mode = os.getenv("OCR_AUTO_SEMANTIC_REPAIR_MODE", "skip").strip().lower()
    if mode not in {"skip", "inline", "inline-concurrent"}:
        mode = "skip"
    default_max_concurrency = (
        int_env("LOCAL_LLM_MAX_CONCURRENCY", int_env("LLM_MAX_CONCURRENCY", 1, 1, 8), 1, 16)
        if local_llm_status().get("configured") and router_mode() in {"hybrid", "local"}
        else int_env("LLM_MAX_CONCURRENCY", 1, 1, 8)
    )
    return {
        "maxConcurrency": default_max_concurrency,
        "boundaryMaxConcurrency": int_env("LLM_BOUNDARY_MAX_CONCURRENCY", default_max_concurrency, 1, 8),
        "standardizeMaxConcurrency": int_env("LLM_STANDARDIZE_MAX_CONCURRENCY", default_max_concurrency, 1, 16),
        "analysisMaxConcurrency": int_env("LLM_ANALYSIS_MAX_CONCURRENCY", default_max_concurrency, 1, 16),
        "standardizeMaxAttempts": int_env("LLM_STANDARDIZE_MAX_ATTEMPTS", 2, 1, 3),
        "analysisMaxAttempts": int_env("LLM_ANALYSIS_MAX_ATTEMPTS", 2, 1, 3),
        "boundaryChunkSize": int_env("LLM_BOUNDARY_CHUNK_SIZE", 5, 1, 20),
        "boundaryChunkMaxChars": int_env("LLM_BOUNDARY_CHUNK_MAX_CHARS", 6000, 1000, 30000),
        "autoSemanticRepairMode": mode,
        "metricsEnabled": bool_env("LLM_METRICS_ENABLED", True),
        "routerMode": router_mode(),
        "externalFallbackEnabled": bool_env("LLM_EXTERNAL_FALLBACK_ENABLED", True),
        "localMaxConcurrency": int_env("LOCAL_LLM_MAX_CONCURRENCY", 4, 1, 16),
        "externalMaxConcurrency": int_env("LLM_EXTERNAL_MAX_CONCURRENCY", 1, 1, 4),
        "cacheEnabled": bool_env("LLM_ROUTER_CACHE_ENABLED", True),
    }


def float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def llm_router_cache_ttl_seconds() -> float:
    return float_env("LLM_ROUTER_CACHE_TTL_SECONDS", 300.0, 0.0, 86400.0)


def llm_cache_key(endpoint: dict[str, Any], task_type: str, payload: dict[str, Any]) -> str:
    cache_payload = {
        "version": LLM_ROUTER_CACHE_VERSION,
        "role": endpoint.get("role"),
        "baseUrl": endpoint.get("baseUrl"),
        "model": endpoint.get("model"),
        "taskType": task_type,
        "payload": payload,
    }
    encoded = json.dumps(cache_payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def cached_llm_response(cache_key: str) -> dict[str, Any] | None:
    if not bool_env("LLM_ROUTER_CACHE_ENABLED", True):
        return None
    ttl = llm_router_cache_ttl_seconds()
    if ttl <= 0:
        return None
    now = time.time()
    with LLM_ROUTER_CACHE_LOCK:
        entry = LLM_ROUTER_CACHE.get(cache_key)
        if not entry:
            return None
        expires_at, data = entry
        if expires_at <= now:
            LLM_ROUTER_CACHE.pop(cache_key, None)
            return None
        return copy.deepcopy(data)


def store_llm_response(cache_key: str, data: dict[str, Any]) -> None:
    if not bool_env("LLM_ROUTER_CACHE_ENABLED", True):
        return
    ttl = llm_router_cache_ttl_seconds()
    if ttl <= 0:
        return
    with LLM_ROUTER_CACHE_LOCK:
        LLM_ROUTER_CACHE[cache_key] = (time.time() + ttl, copy.deepcopy(data))


def endpoint_timeout_seconds(endpoint: dict[str, Any], task_type: str, default_timeout: float) -> float:
    role = str(endpoint.get("role") or "")
    if role == "local":
        task_key = task_type.upper().replace("-", "_")
        raw = os.getenv(f"LOCAL_LLM_{task_key}_TIMEOUT_SECONDS") or os.getenv("LOCAL_LLM_TIMEOUT_SECONDS")
        if raw:
            try:
                return max(1.0, float(raw))
            except (TypeError, ValueError):
                pass
        return min(float(default_timeout), float_env("LOCAL_LLM_DEFAULT_TIMEOUT_SECONDS", 45.0, 1.0, 300.0))
    return float(default_timeout)


def endpoint_semaphore(endpoint: dict[str, Any]) -> threading.BoundedSemaphore:
    role = str(endpoint.get("role") or "external")
    limit = int_env("LOCAL_LLM_MAX_CONCURRENCY", 4, 1, 16) if role == "local" else int_env("LLM_EXTERNAL_MAX_CONCURRENCY", 1, 1, 4)
    key = f"{role}:{limit}"
    with LLM_ENDPOINT_SEMAPHORES_LOCK:
        semaphore = LLM_ENDPOINT_SEMAPHORES.get(key)
        if semaphore is None:
            semaphore = threading.BoundedSemaphore(limit)
            LLM_ENDPOINT_SEMAPHORES[key] = semaphore
        return semaphore


def task_semaphore(task_type: str) -> threading.BoundedSemaphore:
    """Bound concurrent synchronous AI calls by task family."""
    if task_type == "standardize":
        limit = int_env("LLM_STANDARDIZE_MAX_CONCURRENCY", llm_runtime_options()["maxConcurrency"], 1, 16)
    elif task_type in {"analysis", "analysis-generate"}:
        limit = int_env("LLM_ANALYSIS_MAX_CONCURRENCY", llm_runtime_options()["maxConcurrency"], 1, 16)
    else:
        limit = llm_runtime_options()["maxConcurrency"]
    key = f"{task_type}:{limit}"
    with LLM_TASK_SEMAPHORES_LOCK:
        semaphore = LLM_TASK_SEMAPHORES.get(key)
        if semaphore is None:
            semaphore = threading.BoundedSemaphore(limit)
            LLM_TASK_SEMAPHORES[key] = semaphore
        return semaphore


def llm_risk_score(task_type: str, context: dict[str, Any] | None = None) -> float:
    """Score escalation risk from existing OCR evidence; 1.0 means use external directly."""
    context = context or {}
    reasons = normalize_string_list(context.get("reasons"))
    if context.get("forceExternal"):
        return 1.0
    try:
        markdown_chars = int(context.get("markdownChars") or 0)
    except (TypeError, ValueError):
        markdown_chars = 0
    local_safe_chars = int_env("LOCAL_LLM_SAFE_INPUT_CHARS", 6000, 1000, 50000)
    score = 0.25
    if task_type in {"boundary-refine", "sub-question-split"}:
        if markdown_chars > local_safe_chars:
            score = max(score, 0.97)
        if context.get("highConfidence"):
            score = 0.15
        if "no-question-boundaries" in reasons or "invalid-question-range" in reasons:
            score = max(score, 0.96)
        if "unstable-choice-options" in reasons:
            score = max(score, 0.72)
        if "question-number-gap" in reasons:
            score = max(score, 0.68)
        if "unknown-image-path" in reasons:
            score = max(score, 0.62)
        try:
            if int(context.get("questionCount") or 0) == 0:
                score = max(score, 0.96)
        except (TypeError, ValueError):
            pass
    if task_type == "standardize":
        markdown = str(context.get("markdown") or "")
        if len(markdown) > local_safe_chars:
            score = max(score, 0.97)
        hints = context.get("structuredHints") if isinstance(context.get("structuredHints"), dict) else {}
        question_type = str(hints.get("type") or "").strip()
        if len(markdown) > int_env("LLM_ROUTER_LONG_MARKDOWN_CHARS", 6000, 1000, 50000):
            score = max(score, 0.74)
        if re.search(r"[（(]\s*\d+\s*[）)]|[①②③④⑤⑥⑦⑧⑨⑩]", markdown):
            score = max(score, 0.58)
        if re.search(r"【?(?:答案|解析|解答|参考答案|故答案为)】?", markdown):
            score = max(score, 0.64)
        if question_type == "fill_blank" and not re.search(r"_{2,}|____|（\s*）|\(\s*\)|填空", markdown):
            score = max(score, 0.68)
        if hints.get("subQuestions"):
            score = max(score, 0.55)
    return min(1.0, max(0.0, score))


def route_llm_endpoints(
    task_type: str,
    risk_context: dict[str, Any] | None = None,
    force_external: bool = False,
) -> list[dict[str, Any]]:
    """Route OCR-flow LLM work to local-first or external fallback endpoints."""
    status = llm_status()
    if not status["enabled"]:
        return []
    mode = router_mode()
    local = local_llm_status()
    external = external_llm_status()
    local_first_tasks = {"sub-question-split", "standardize", "semantic-repair", "render-validation-repair"}
    external_first_risk = float_env("LLM_ROUTER_EXTERNAL_FIRST_RISK_THRESHOLD", 0.92, 0.0, 1.0)
    risk = llm_risk_score(task_type, risk_context)
    fallback_enabled = bool_env("LLM_EXTERNAL_FALLBACK_ENABLED", True)

    endpoints: list[dict[str, Any]] = []
    if force_external or mode == "external" or risk >= external_first_risk:
        if external.get("enabled") and external.get("configured"):
            endpoints.append({**external, "riskScore": risk, "routeReason": "external-forced-or-high-risk"})
        elif local.get("enabled") and local.get("configured"):
            endpoints.append({**local, "riskScore": risk, "routeReason": "external-unavailable-local-fallback"})
        return endpoints

    if mode in {"hybrid", "local"} and task_type in local_first_tasks and local.get("enabled") and local.get("configured"):
        endpoints.append({**local, "riskScore": risk, "routeReason": "local-first"})
        if mode == "hybrid" and fallback_enabled and external.get("enabled") and external.get("configured"):
            endpoints.append({**external, "riskScore": risk, "routeReason": "external-fallback"})
        return endpoints

    if external.get("enabled") and external.get("configured"):
        endpoints.append({**external, "riskScore": risk, "routeReason": "external-default"})
    elif local.get("enabled") and local.get("configured"):
        endpoints.append({**local, "riskScore": risk, "routeReason": "local-only"})
    return endpoints


def post_llm_json_for_endpoint(
    endpoint: dict[str, Any],
    payload: dict[str, Any],
    timeout_seconds: float,
    task_type: str,
) -> tuple[dict[str, Any], bool]:
    """Post one routed OpenAI-compatible call and return decoded response JSON."""
    api_key = str(endpoint.get("apiKey") or "EMPTY")
    routed_payload = {**payload, "model": endpoint.get("model") or payload.get("model")}
    if endpoint.get("role") == "local" and bool_env("LOCAL_LLM_DISABLE_THINKING", True):
        chat_template_kwargs = dict(routed_payload.get("chat_template_kwargs") or {})
        chat_template_kwargs.setdefault("enable_thinking", False)
        routed_payload["chat_template_kwargs"] = chat_template_kwargs
    cache_key = llm_cache_key(endpoint, task_type, routed_payload)
    cached = cached_llm_response(cache_key)
    if cached is not None:
        return cached, True

    url = f"{str(endpoint.get('baseUrl') or '').rstrip('/')}/chat/completions"
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"LLM endpoint baseUrl 无效：{endpoint.get('baseUrl')}")
    with endpoint_semaphore(endpoint):
        response = post_llm_json_with_deadline(
            url,
            api_key,
            routed_payload,
            endpoint_timeout_seconds(endpoint, task_type, timeout_seconds),
        )
    response.raise_for_status()
    data = response.json()
    store_llm_response(cache_key, data)
    return data, False


def post_llm_json_with_deadline(
    url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> httpx.Response:
    """POST to an OpenAI-compatible endpoint with a hard total deadline.

    httpx read timeouts are not a total request deadline: a slow model can keep
    sending tokens and hold OCR-Flow forever. The outer future deadline forces
    boundary confirmation to fail fast and lets the caller fall back to local
    boundaries.
    """
    deadline = max(1.0, float(timeout_seconds))
    io_timeout = httpx.Timeout(
        timeout=deadline,
        connect=min(10.0, deadline),
        read=min(30.0, deadline),
        write=min(10.0, deadline),
        pool=min(10.0, deadline),
    )

    def send() -> httpx.Response:
        with httpx.Client(timeout=io_timeout) as client:
            return client.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(send)
    try:
        return future.result(timeout=deadline)
    except FutureTimeoutError as exc:
        future.cancel()
        raise TimeoutError(f"LLM request exceeded total deadline {int(deadline)}s") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def llm_call_metadata(
    call_type: str,
    started_at: float,
    status: str,
    error: str | None = None,
    chunk_index: int | None = None,
    item_count: int | None = None,
    retry_count: int | None = None,
    endpoint: dict[str, Any] | None = None,
    cache_hit: bool | None = None,
) -> dict[str, Any]:
    """Build sanitized timing metadata for one LLM call."""
    llm = endpoint or llm_status()
    duration_ms = max(0, int((time.perf_counter() - started_at) * 1000))
    sanitized_error = None
    if error is not None:
        sanitized_error = re.sub(r"\s+", " ", str(error)).strip()
        if len(sanitized_error) > 300:
            sanitized_error = f"{sanitized_error[:297]}..."
    metadata = {
        "callType": call_type,
        "status": status,
        "provider": llm["provider"],
        "model": llm["model"],
        "route": llm.get("role"),
        "routeReason": llm.get("routeReason"),
        "riskScore": llm.get("riskScore"),
        "durationMs": duration_ms,
        "error": sanitized_error,
    }
    if chunk_index is not None:
        metadata["chunkIndex"] = chunk_index
    if item_count is not None:
        metadata["itemCount"] = item_count
    if retry_count is not None:
        metadata["retryCount"] = retry_count
    if cache_hit is not None:
        metadata["cacheHit"] = cache_hit
    return metadata


def rule_splitter_metadata(reason: str | None = None) -> dict[str, Any]:
    """构造规则拆题元数据。"""
    return {
        "source": "rule",
        "provider": None,
        "model": None,
        "fallback": reason is not None,
        "error": reason,
        "llmCalls": [],
    }


def llm_splitter_metadata() -> dict[str, Any]:
    """构造 LLM 拆题元数据。"""
    status = llm_status()
    return {
        "source": "llm",
        "provider": status["provider"],
        "model": status["model"],
        "fallback": False,
        "error": None,
    }


def boundary_refinement_skipped_metadata(confidence: dict[str, Any]) -> dict[str, Any]:
    """Build metadata for local-boundary high-confidence skips."""
    return {
        "source": "local-boundary",
        "provider": None,
        "model": None,
        "fallback": False,
        "error": None,
        "reason": "local-high-confidence" if confidence.get("highConfidence") else "llm-boundary-not-required",
        "confidence": confidence,
        "llmCalls": [],
    }


def refine_questions_with_llm(
    markdown: str,
    assets: list[dict[str, Any]],
    local_structured: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """调用大模型优化本地拆题结果。"""
    status = llm_status()
    if not status["enabled"]:
        return None, rule_splitter_metadata("LLM 拆题已通过 ENABLE_LLM_SPLIT 关闭")
    if not status["configured"]:
        return None, rule_splitter_metadata(f"{LLM_KEY_HINT}，已使用本地规则拆题")
    if not markdown.strip():
        return None, rule_splitter_metadata("OCR Markdown 为空，已使用本地规则拆题")

    api_key = llm_api_key()
    assert api_key is not None

    max_chars = int(os.getenv("LLM_SPLIT_MAX_CHARS", "30000"))
    timeout_seconds = float(os.getenv("LLM_SPLIT_TIMEOUT_SECONDS", "90"))
    payload = build_payload(markdown[:max_chars], assets, local_structured, status["model"])
    url = f"{str(status['baseUrl']).rstrip('/')}/chat/completions"

    try:
        response = post_llm_json_with_deadline(url, api_key, payload, timeout_seconds)
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        parsed = extract_json_object(content)
        structured = normalize_llm_result(parsed, assets, local_structured)
        return structured, llm_splitter_metadata()
    except Exception as exc:
        return None, rule_splitter_metadata(f"LLM 拆题失败，已回退本地规则：{exc}")


def refine_question_boundaries_with_llm(
    markdown: str,
    assets: list[dict[str, Any]],
    local_boundaries: dict[str, Any],
    risk_context: dict[str, Any] | None = None,
    force_external: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Ask the LLM to confirm boundaries only, never to generate question text."""
    status = llm_status()
    if not status["enabled"]:
        return None, rule_splitter_metadata("LLM 边界确认已通过 ENABLE_LLM_SPLIT 关闭")
    if not status["configured"]:
        return None, rule_splitter_metadata(f"{LLM_KEY_HINT}，已使用本地边界候选")
    if not markdown.strip():
        return None, rule_splitter_metadata("OCR Markdown 为空，已使用本地边界候选")

    max_chars = int(os.getenv("LLM_BOUNDARY_MAX_CHARS", "30000"))
    timeout_seconds = float(os.getenv("LLM_BOUNDARY_TIMEOUT_SECONDS", "90"))
    boundary_markdown = markdown[:max_chars]
    payload = build_boundary_payload(boundary_markdown, assets, local_boundaries, status["model"])
    item_count = len(local_boundaries.get("questions") or [])
    routed_context = {
        **(risk_context or {}),
        "markdownChars": len(boundary_markdown),
        "itemCount": item_count,
    }
    endpoints = route_llm_endpoints("boundary-refine", routed_context, force_external=force_external)
    if not endpoints:
        return None, rule_splitter_metadata(f"{LLM_KEY_HINT}，已使用本地边界候选")

    calls: list[dict[str, Any]] = []
    errors: list[str] = []
    for endpoint in endpoints:
        started = time.perf_counter()
        try:
            data, cache_hit = post_llm_json_for_endpoint(endpoint, payload, timeout_seconds, "boundary-refine")
            content = data["choices"][0]["message"]["content"]
            parsed = extract_json_object(content)
            parsed = preserve_local_boundaries_after_truncation(parsed, local_boundaries, max_chars, len(markdown))
            calls.append(llm_call_metadata("boundary-refine", started, "success", item_count=item_count, endpoint=endpoint, cache_hit=cache_hit))
            return parsed, {
                "source": "llm-boundary",
                "provider": endpoint["provider"],
                "model": endpoint["model"],
                "route": endpoint.get("role"),
                "riskScore": endpoint.get("riskScore"),
                "fallback": False,
                "error": None,
                "warnings": normalize_string_list(parsed.get("warnings")),
                "llmCalls": calls,
            }
        except Exception as exc:
            errors.append(f"{endpoint.get('role') or endpoint.get('provider')}: {exc}")
            calls.append(llm_call_metadata("boundary-refine", started, "failed", error=str(exc), item_count=item_count, endpoint=endpoint))
            continue

    metadata = rule_splitter_metadata(f"LLM 边界确认失败，已回退本地边界候选：{'; '.join(errors)}")
    metadata["llmCalls"] = calls
    return None, metadata


def offset_boundary_ranges(value: Any, delta: int) -> Any:
    """Return a copy with boundary offsets shifted by delta."""
    if isinstance(value, list):
        return [offset_boundary_ranges(item, delta) for item in value]
    if not isinstance(value, dict):
        return value
    shifted: dict[str, Any] = {}
    for key, item in value.items():
        if key in {"start", "end", "contentStart"} and isinstance(item, int):
            shifted[key] = item + delta
        else:
            shifted[key] = offset_boundary_ranges(item, delta)
    return shifted


def merge_boundary_chunk_results(local_boundaries: dict[str, Any], chunk_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge chunked LLM boundary results, falling back per chunk."""
    sections_by_id: dict[str, dict[str, Any]] = {}
    questions: list[dict[str, Any]] = []
    warnings: list[str] = []

    for section in local_boundaries.get("sections") or []:
        if isinstance(section, dict):
            sections_by_id[str(section.get("id") or len(sections_by_id))] = section

    for chunk in sorted(chunk_results, key=lambda item: int(item.get("index") or 0)):
        result = chunk.get("result") if isinstance(chunk.get("result"), dict) else chunk.get("localBoundaries")
        if not isinstance(result, dict):
            continue
        for section in result.get("sections") or []:
            if isinstance(section, dict):
                sections_by_id[str(section.get("id") or len(sections_by_id))] = section
        for question in result.get("questions") or []:
            if isinstance(question, dict):
                questions.append(question)
        if chunk.get("error"):
            warnings.append(f"chunk {chunk.get('index')} fallback: {chunk.get('error')}")
        warnings.extend(normalize_string_list(result.get("warnings")))

    deduped_questions: list[dict[str, Any]] = []
    seen_starts: set[int] = set()
    for question in sorted(questions, key=lambda item: int(item.get("start") or 0)):
        start = question.get("start")
        if isinstance(start, int) and start in seen_starts:
            continue
        if isinstance(start, int):
            seen_starts.add(start)
        deduped_questions.append(question)

    return {
        "source": "llm-boundary-chunked",
        "sections": list(sections_by_id.values()),
        "questions": deduped_questions,
        "warnings": list(dict.fromkeys(warnings)),
    }


def refine_boundary_chunk_with_llm(
    chunk: dict[str, Any],
    assets: list[dict[str, Any]],
    risk_context: dict[str, Any] | None = None,
    force_external: bool = False,
) -> dict[str, Any]:
    """Refine one chunk and map model offsets back to full-document offsets."""
    chunk_start = int(chunk.get("start") or 0)
    local_boundaries = chunk.get("localBoundaries") if isinstance(chunk.get("localBoundaries"), dict) else {}
    prompt_boundaries = offset_boundary_ranges(local_boundaries, -chunk_start)
    result, metadata = refine_question_boundaries_with_llm(
        str(chunk.get("markdown") or ""),
        assets,
        prompt_boundaries,
        risk_context=risk_context,
        force_external=force_external,
    )
    restored = offset_boundary_ranges(result, chunk_start) if result else None
    return {
        **chunk,
        "result": restored,
        "error": metadata.get("error") if isinstance(metadata, dict) else None,
        "metadata": metadata,
    }


def refine_question_boundaries_in_chunks(
    chunks: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    local_boundaries: dict[str, Any],
    risk_context: dict[str, Any] | None = None,
    force_external: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Run boundary refinement on planned chunks with bounded concurrency."""
    options = llm_runtime_options()
    if not chunks:
        return None, rule_splitter_metadata("没有可用于 AI 边界确认的题目分片")

    calls: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    def chunk_call_metadata(metadata: dict[str, Any], chunk: dict[str, Any]) -> list[dict[str, Any]]:
        question_count = len((chunk.get("localBoundaries") or {}).get("questions") or [])
        result: list[dict[str, Any]] = []
        for call in metadata.get("llmCalls") or []:
            if isinstance(call, dict):
                result.append({**call, "chunkIndex": chunk.get("index"), "itemCount": call.get("itemCount", question_count)})
        return result

    boundary_max_concurrency = int(options.get("boundaryMaxConcurrency") or options["maxConcurrency"])
    if len(chunks) <= 1 or boundary_max_concurrency <= 1:
        for chunk in chunks:
            result = refine_boundary_chunk_with_llm(chunk, assets, risk_context=risk_context, force_external=force_external)
            metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
            calls.extend(chunk_call_metadata(metadata, chunk))
            results.append(result)
    else:
        with ThreadPoolExecutor(max_workers=boundary_max_concurrency) as executor:
            futures = {
                executor.submit(refine_boundary_chunk_with_llm, chunk, assets, risk_context, force_external): chunk
                for chunk in chunks
            }
            for future in as_completed(futures):
                chunk = futures[future]
                try:
                    result = future.result()
                    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
                    calls.extend(chunk_call_metadata(metadata, chunk))
                    results.append(result)
                except Exception as exc:
                    calls.append(
                        {
                            "callType": "boundary-refine",
                            "status": "failed",
                            "provider": llm_status()["provider"],
                            "model": llm_status()["model"],
                            "durationMs": 0,
                            "error": re.sub(r"\s+", " ", str(exc)).strip()[:300],
                            "chunkIndex": chunk.get("index"),
                            "itemCount": len((chunk.get("localBoundaries") or {}).get("questions") or []),
                        }
                    )
                    results.append({**chunk, "result": None, "error": str(exc)})

    merged = merge_boundary_chunk_results(local_boundaries, results)
    status = llm_status()
    routed_calls = [call for call in calls if isinstance(call, dict)]
    last_success = next((call for call in reversed(routed_calls) if call.get("status") == "success"), None)
    return merged, {
        "source": "llm-boundary-chunked",
        "provider": (last_success or status).get("provider"),
        "model": (last_success or status).get("model"),
        "route": (last_success or {}).get("route"),
        "fallback": False,
        "error": None,
        "llmCalls": calls,
        "chunkCount": len(chunks),
        "maxConcurrency": boundary_max_concurrency,
        "warnings": normalize_string_list(merged.get("warnings")),
    }


def standardize_markdown_with_llm(
    markdown: str,
    raw_ocr_context: str = "",
    structured_hints: dict[str, Any] | None = None,
) -> tuple[str | None, dict[str, Any]]:
    """调用大模型标准化题目 Markdown。"""
    status = llm_status()
    if not status["enabled"]:
        return None, {"source": "ai", "provider": status["provider"], "model": status["model"], "error": "LLM 已通过 ENABLE_LLM_SPLIT 关闭"}
    if not status["configured"]:
        return None, {"source": "ai", "provider": status["provider"], "model": status["model"], "error": LLM_KEY_HINT}
    if not markdown.strip():
        return "", {"source": "ai", "provider": status["provider"], "model": status["model"], "error": None}

    timeout_seconds = float(os.getenv("LLM_STANDARDIZE_TIMEOUT_SECONDS", "60"))
    payload = {
        "model": status["model"],
        "temperature": 0.0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是题库 Markdown + LaTeX 公式修复器。"
                    "只返回 JSON 对象，不要解释。"
                    "只做最小必要修改：修正 Markdown 公式分隔符、LaTeX 命令空格、括号配对和高置信 OCR 公式错误。"
                    "禁止求解题目、补不存在的答案、改写题意、重排题号、分值、选项和自然语言文本。"
                    "如果 currentMarkdown 或 rawOcrContext 明显把本题答案、解析、参考答案、解答过程扫进题干，"
                    "需要把这些内容从 markdown 中移除，并分别返回 answer、analysis；"
                    "如果题目包含（1）（2）等小问，或 structuredHints.subQuestions 非空，必须把答案和解析按小问归属到 subQuestions；"
                    "即使没有答案和解析，只要 currentMarkdown 明显包含小问结构，也必须返回 subQuestions[].label 和 subQuestions[].stemMarkdown，"
                    "并让 markdown 只保留大题共用材料/父题题干，不要把小问题干继续混在父题 markdown 中。"
                    "此时父题 answer、analysis 返回空字符串，小问对象返回 id、label、answer、analysis，可选返回 stemMarkdown。"
                    "返回的 markdown 必须只包含题干、选项和必要题图引用，不能再包含【答案】、【解析】、【解答】、故答案为、解答过程等内容；"
                    "答案和解析一旦抽取，只能放在 answer、analysis 字段中，不得重复留在 markdown 字段里。"
                    "只有能从输入文本中直接摘录或高置信归纳时才返回 answer、analysis，否则返回空字符串。"
                    "不要把其它题号的答案或解析串到当前题。"
                    "不要把普通不等式、方程或短公式改写成 array/cases/aligned 等复杂环境，除非原文已经明确使用了该结构。"
                    "不要把题目整体包进 \\left、\\right、\\begin{array} 或其它大结构。"
                    "保留原有换行、题号、选项和 LaTeX tasks 环境；已有 tasks 环境只修正拼写和公式，不改变选项含义。"
                    "选择题的选项结构优先级高于题干格式修复：不得删除、合并、重排 A/B/C/D 选项；"
                    "图片选项必须保留为原有 `![](图N)` 引用，禁止把图片选项并入题干或替换成文字描述。"
                    "没有 tasks 时不要主动新增 tasks；只有 structuredHints.type 明确为 choice，且原文已有 A/B/C/D 等清晰选项边界时，"
                    "才可最小化整理为标准 LaTeX tasks 环境：\\begin{tasks}(4) ... \\task 选项 ... \\end{tasks}。"
                    "禁止输出 \\begin{ttasks}、\\end{ttasks} 或其它拼写错误。"
                    "如果无法高置信识别选项边界，保留原文并在 warnings 中说明。"
                    "遇到填空题、补全题、空缺题、横线题或 structuredHints.type=fill_blank 时，必须保留空位。"
                    "如果 OCR 把横线漏掉，只能在对应位置补 `____`、`(____)` 这类占位符；禁止直接补答案。"
                    "如果 OCR 把空线误识别成短字母/数字/标点噪声行，可替换为空位占位符并写入 warnings。"
                    "如果提供 rawOcrContext，它只是同一题附近的原始 OCR 参考；currentMarkdown 才是要修复的主文本。"
                    "只能用 rawOcrContext 修复明显损坏的公式片段，禁止复制参考上下文里的其它题目、页眉页脚或无关内容。"
                    "遇到形如 5\"、5“、5” 且同题上下文出现 5^m、5^{3m-2n} 等指数结构时，"
                    "可高置信修复为 5^n 或对应上下文变量，并记录 corrections。"
                    "如果无法高置信判断，保留原文并记录 warnings。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "schema": {
                            "markdown": "标准化后的 Markdown + LaTeX",
                            "answer": "从题干或 OCR 上下文抽取出的本题答案；没有则为空字符串",
                            "analysis": "从题干或 OCR 上下文抽取出的本题解析；没有则为空字符串",
                            "subQuestions": [
                                {
                                    "id": "小问 id，优先沿用 structuredHints.subQuestions 中的 id",
                                    "label": "小问标签，如 (1)",
                                    "stemMarkdown": "可选：标准化后的小问题干",
                                    "answer": "该小问答案；没有则为空字符串",
                                    "analysis": "该小问解析；没有则为空字符串",
                                    "contextMatched": "答案/解析是否能在输入 OCR 上下文中找到证据",
                                    "answerEvidence": "支持该小问答案的最短 OCR 原文证据；没有则为空字符串",
                                    "analysisEvidence": "支持该小问解析的最短 OCR 原文证据；没有则为空字符串",
                                }
                            ],
                            "corrections": [{"before": "原片段", "after": "修正片段", "reason": "修正理由"}],
                            "warnings": ["无法高置信判断的问题"],
                            "confidence": "high | medium | low",
                        },
                        "semanticExamples": [
                            {
                                "before": "若 $5^{m}=3$，5\"=4，则 $5^{3m-2n}$ 的值是()",
                                "after": "若 $5^{m}=3$，$5^n=4$，则 $5^{3m-2n}$ 的值是()",
                                "reason": "后文出现 3m-2n，前文应给出 5^m 与 5^n 两个条件；引号是上标 n 的 OCR 误识别。",
                            }
                        ],
                        "currentMarkdown": markdown,
                        "rawOcrContext": raw_ocr_context[:6000],
                        "structuredHints": structured_hints or {},
                        "markdown": markdown,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }

    last_error: Exception | None = None
    calls: list[dict[str, Any]] = []
    attempt_payload = payload
    max_attempts = int_env("LLM_STANDARDIZE_MAX_ATTEMPTS", 2, 1, 3)
    with task_semaphore("standardize"):
        for attempt in range(max_attempts):
            endpoints = route_llm_endpoints(
                "standardize",
                {
                    "markdown": markdown,
                    "rawOcrContext": raw_ocr_context,
                    "structuredHints": structured_hints or {},
                },
            )
            for endpoint in endpoints:
                started = time.perf_counter()
                try:
                    data, cache_hit = post_llm_json_for_endpoint(endpoint, attempt_payload, timeout_seconds, "standardize")
                    content = data["choices"][0]["message"]["content"]
                    parsed = extract_json_object(content)
                    standardized = str(parsed.get("markdown") or "").strip()
                    if not standardized:
                        raise ValueError("模型未返回 markdown 字段")
                    success_call = llm_call_metadata("standardize", started, "success", retry_count=attempt, endpoint=endpoint, cache_hit=cache_hit)
                    calls.append(success_call)
                    return standardized, {
                        "source": "ai",
                        "provider": endpoint["provider"],
                        "model": endpoint["model"],
                        "route": endpoint.get("role"),
                        "riskScore": endpoint.get("riskScore"),
                        "error": None,
                        "answer": str(parsed.get("answer") or parsed.get("suggestedAnswer") or "").strip(),
                        "analysis": str(parsed.get("analysis") or parsed.get("explanation") or "").strip(),
                        "subQuestions": normalize_solution_sub_questions(parsed.get("subQuestions") or parsed.get("children")),
                        "corrections": normalize_corrections(parsed.get("corrections")),
                        "warnings": normalize_string_list(parsed.get("warnings")),
                        "confidence": str(parsed.get("confidence") or "unknown"),
                        "llmCall": success_call,
                        "llmCalls": calls,
                    }
                except Exception as exc:
                    last_error = exc
                    calls.append(llm_call_metadata("standardize", started, "failed", error=str(exc), retry_count=attempt, endpoint=endpoint))
                    continue
            if attempt < max_attempts - 1:
                attempt_payload = llm_json_retry_payload(
                    payload,
                    str(last_error or "模型返回不符合 schema"),
                    ["markdown", "answer", "analysis", "subQuestions", "corrections", "warnings", "confidence"],
                )
                continue
            break

    error = str(last_error or "AI 标准化失败")
    return None, {
        "source": "ai",
        "provider": status["provider"],
        "model": status["model"],
        "error": error,
        "fallbackUsed": True,
        "retryable": True,
        "retryAfterSeconds": int_env("LLM_STANDARDIZE_RETRY_AFTER_SECONDS", 10, 1, 300),
        "imageCount": 0,
        "llmCall": calls[-1] if calls else llm_call_metadata("standardize", time.perf_counter(), "failed", error=error, retry_count=max_attempts - 1),
        "llmCalls": calls,
    }


def analysis_image_urls(images: list[dict[str, Any]]) -> list[str]:
    """提取 AI 解析请求中的图片 URL。"""
    urls: list[str] = []
    seen: set[str] = set()
    for image in images:
        if not isinstance(image, dict):
            continue
        value = str(
            image.get("imageDataUrl")
            or image.get("dataUrl")
            or image.get("data_url")
            or ""
        ).strip()
        if not value:
            url = str(image.get("url") or "").strip()
            if url.startswith("data:image/") or url.startswith("http://") or url.startswith("https://"):
                value = url
        if not value or value in seen:
            continue
        seen.add(value)
        urls.append(value)
    return urls


def analysis_image_metadata(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """提取 AI 解析请求中的图片元数据。"""
    metadata: list[dict[str, Any]] = []
    for image in images:
        if not isinstance(image, dict):
            continue
        item: dict[str, Any] = {}
        for key in ("name", "path", "url", "source", "size", "type", "contentType", "aiImageIncluded", "aiImageSkipReason"):
            if key in image:
                item[key] = image[key]
        metadata.append(item)
    return metadata


def generate_question_analysis_with_llm(
    stem_markdown: str,
    answer: str = "",
    question_type: str = "unknown",
    knowledge_points: list[str] | None = None,
    images: list[dict[str, Any]] | None = None,
    sub_questions: list[dict[str, Any]] | None = None,
) -> tuple[str | None, dict[str, Any]]:
    """调用大模型生成题目解析和答案建议。"""
    status = llm_status()
    if not status["enabled"]:
        return None, {"source": "ai", "provider": status["provider"], "model": status["model"], "error": "LLM 已通过 ENABLE_LLM_SPLIT 关闭"}
    if not status["configured"]:
        return None, {"source": "ai", "provider": status["provider"], "model": status["model"], "error": LLM_KEY_HINT}
    if not stem_markdown.strip():
        return None, {"source": "ai", "provider": status["provider"], "model": status["model"], "error": "题干为空，无法生成解析"}

    timeout_seconds = float(os.getenv("LLM_ANALYSIS_TIMEOUT_SECONDS", "75"))
    image_urls = analysis_image_urls(images or [])
    sub_question_hints = compact_sub_questions(sub_questions or [])
    user_text = json.dumps(
        {
            "schema": {
                "analysis": "Markdown + LaTeX 解析",
                "answer": "如能确定，可返回建议答案；否则为空字符串",
                "subQuestions": [
                    {
                        "id": "小问 id，必须沿用输入 subQuestions 的 id",
                        "label": "小问标签，如 (1)",
                        "answer": "该小问答案；无法确定时为空字符串",
                        "analysis": "该小问 Markdown + LaTeX 解析；无法判断时为空字符串",
                        "warnings": ["该小问需要人工复核的问题"],
                    }
                ],
                "warnings": ["需要人工复核的问题"],
                "confidence": "high | medium | low",
            },
            "question": {
                "type": question_type,
                "stemMarkdown": stem_markdown,
                "answer": answer,
                "knowledgePoints": knowledge_points or [],
                "images": analysis_image_metadata(images or []),
                "subQuestions": sub_question_hints,
            },
        },
        ensure_ascii=False,
    )
    user_content: str | list[dict[str, Any]]
    if image_urls:
        user_content = [{"type": "text", "text": user_text}]
        user_content.extend({"type": "image_url", "image_url": {"url": image_url}} for image_url in image_urls)
    else:
        user_content = user_text

    payload = {
        "model": status["model"],
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是中学题库解析生成助手。只返回 JSON 对象，不要返回 Markdown 代码块或额外解释。"
                    "根据题干、题型、答案和知识点生成准确、简洁、适合教师入库复核的解析。"
                    "解析必须使用 Markdown + LaTeX，保留公式的 $...$ 或 $$...$$ 形式。"
                    "没有 subQuestions 时必须返回非空 analysis；如果答案为空，先求解并在解析中给出结论。"
                    "如果输入包含 subQuestions，必须按每个小问分别返回 subQuestions[].answer 和 subQuestions[].analysis，"
                    "父题 answer 与 analysis 返回空字符串；不要把多个小问解析混在父题 analysis 里。"
                    "只有题干信息严重缺失、完全无法判断时，才允许返回空 analysis 并写入 warnings。"
                    "如果题目包含题图，必须结合题图推理；不要改写题干，不要编造看不清或不存在的图片内容。"
                ),
            },
            {
                "role": "user",
                "content": user_content,
            },
        ],
    }
    started = time.perf_counter()

    last_error: Exception | None = None
    last_warnings: list[str] = []
    last_sub_questions: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    attempt_payload = payload
    max_attempts = int_env("LLM_ANALYSIS_MAX_ATTEMPTS", 2, 1, 3)
    with task_semaphore("analysis-generate"):
        for attempt in range(max_attempts):
            endpoints = route_llm_endpoints(
                "analysis-generate",
                {
                    "markdown": stem_markdown,
                    "markdownChars": len(stem_markdown),
                    "questionType": question_type,
                    "imageCount": len(image_urls),
                    "subQuestionCount": len(sub_question_hints),
                },
            )
            for endpoint in endpoints:
                call_started = time.perf_counter()
                try:
                    data, cache_hit = post_llm_json_for_endpoint(endpoint, attempt_payload, timeout_seconds, "analysis-generate")
                    content = data["choices"][0]["message"]["content"]
                    parsed = extract_json_object(content)
                    raw_analysis = (
                        parsed.get("analysis")
                        or parsed.get("解析")
                        or parsed.get("solution")
                        or parsed.get("explanation")
                    )
                    if not raw_analysis and isinstance(parsed.get("steps"), list):
                        raw_analysis = "\n\n".join(str(step) for step in parsed["steps"] if str(step).strip())
                    analysis = str(raw_analysis or "").strip()
                    solution_sub_questions = normalize_solution_sub_questions(parsed.get("subQuestions") or parsed.get("children"))
                    warnings = normalize_string_list(parsed.get("warnings"))
                    last_warnings = warnings
                    last_sub_questions = solution_sub_questions
                    if sub_question_hints and not solution_sub_questions:
                        raise ValueError(warnings[0] if warnings else "模型未返回 subQuestions 小问解析字段")
                    has_sub_question_analysis = any(str(item.get("analysis") or "").strip() for item in solution_sub_questions)
                    if not analysis and not has_sub_question_analysis:
                        raise ValueError(warnings[0] if warnings else "模型未返回 analysis 字段")
                    answer_text = str(parsed.get("answer") or "").strip()
                    if solution_sub_questions:
                        analysis = ""
                        answer_text = ""
                    success_call = llm_call_metadata(
                        "analysis-generate",
                        call_started,
                        "success",
                        item_count=1,
                        retry_count=attempt,
                        endpoint=endpoint,
                        cache_hit=cache_hit,
                    )
                    calls.append(success_call)
                    return analysis, {
                        "source": "ai",
                        "provider": endpoint["provider"],
                        "model": endpoint["model"],
                        "route": endpoint.get("role"),
                        "riskScore": endpoint.get("riskScore"),
                        "error": None,
                        "answer": answer_text,
                        "subQuestions": solution_sub_questions,
                        "warnings": warnings,
                        "confidence": str(parsed.get("confidence") or "unknown"),
                        "imageCount": len(image_urls),
                        "llmCall": success_call,
                        "llmCalls": calls,
                    }
                except Exception as exc:
                    last_error = exc
                    calls.append(
                        llm_call_metadata(
                            "analysis-generate",
                            call_started,
                            "failed",
                            error=str(exc),
                            item_count=1,
                            retry_count=attempt,
                            endpoint=endpoint,
                        )
                    )
                    continue
            if attempt < max_attempts - 1:
                required_fields = ["analysis", "answer", "subQuestions", "warnings", "confidence"]
                attempt_payload = llm_json_retry_payload(payload, str(last_error or "模型返回不符合 schema"), required_fields)
                continue
            break

    error = str(last_error or "AI 解析失败")
    fallback_warning = f"AI 解析暂时不可用：{error}。已保留当前题目内容，可稍后重试或人工填写解析。"
    return "", {
        "source": "ai",
        "provider": status["provider"],
        "model": status["model"],
        "error": error,
        "fallbackUsed": True,
        "retryable": True,
        "retryAfterSeconds": int_env("LLM_ANALYSIS_RETRY_AFTER_SECONDS", 10, 1, 300),
        "warnings": [fallback_warning, *last_warnings],
        "confidence": "unknown",
        "imageCount": len(image_urls),
        "subQuestions": last_sub_questions,
        "answer": "",
        "llmCall": calls[-1] if calls else llm_call_metadata("analysis-generate", started, "failed", error=error, item_count=1, retry_count=max_attempts - 1),
        "llmCalls": calls,
    }


def enrich_questions_metadata_with_llm(
    questions: list[dict[str, Any]],
    answer_context: str = "",
    paper_ocr_context: str = "",
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """调用大模型补充题型、答案、解析和知识点元数据。"""
    status = llm_status()
    if not status["enabled"]:
        return {}, {"source": "rule", "provider": status["provider"], "model": status["model"], "error": "LLM 已通过 ENABLE_LLM_SPLIT 关闭"}
    if not status["configured"]:
        return {}, {"source": "rule", "provider": status["provider"], "model": status["model"], "error": f"{LLM_KEY_HINT}，已使用本地默认题目元数据"}
    if not questions:
        return {}, {"source": "rule", "provider": status["provider"], "model": status["model"], "error": "题目为空，跳过 AI 元数据补全"}

    api_key = llm_api_key()
    assert api_key is not None

    compact_questions = []
    for question in questions[: int(os.getenv("LLM_ENRICH_MAX_QUESTIONS", "80"))]:
        compact_questions.append(
            {
                "id": question.get("id"),
                "type": question.get("type"),
                "stemMarkdown": question.get("stemMarkdown") or question.get("manualMarkdown") or "",
                "options": question.get("options", []),
                "images": [{"path": image.get("path")} for image in question.get("images", []) if isinstance(image, dict)],
                "subQuestions": compact_sub_questions(question.get("subQuestions") or question.get("children")),
            }
        )

    timeout_seconds = float(os.getenv("LLM_ENRICH_TIMEOUT_SECONDS", "90"))
    url = f"{str(status['baseUrl']).rstrip('/')}/chat/completions"
    payload = {
        "model": status["model"],
        "temperature": 0.0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是题库入库前的题目元数据补全助手。只返回 JSON 对象，不要解释。"
                    "基于题干、选项、题图引用、同卷 OCR 全文和可选答案 OCR 文本，为每道题补全题型、答案、解析、知识点、难度和分值。"
                    "不得编造题图路径；题图只能保留输入中的 images。"
                    "答案和解析必须优先从 answerContext 或 paperOcrContext 中抽取并与题号、题干语义匹配。"
                    "如果题目包含 subQuestions，必须把答案、解析、知识点、难度和分值归属到对应小问；父题 answer、analysis 返回空字符串。"
                    "匹配小问时优先使用小问 id，其次使用 label，例如 (1)、(2)。"
                    "如果同一份试卷 OCR 文本末尾或题后包含“答案”“解析”“参考答案”“解答过程”等区域，需要识别该区域并匹配到对应题目。"
                    "不是每道题都有答案或解析；某题无法从 OCR 上下文高置信匹配时，对该题 answer 和 analysis 返回空字符串，并在 warnings 中说明。"
                    "不要为了补齐空缺而自行求解题目；不要把其它题的答案、解析串到当前题。"
                    "每题必须返回 contextMatched、answerEvidence 和 analysisEvidence。"
                    "只有答案或解析能在 answerContext 或 paperOcrContext 中找到对应题号/题干附近证据时，contextMatched 才能为 true。"
                    "answerEvidence 和 analysisEvidence 应摘录最短 OCR 原文证据；没有证据时为空字符串。"
                    "difficulty 只能是 easy、medium、hard。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "schema": {
                            "questions": [
                                {
                                    "id": "输入题目 id",
                                    "type": "choice | fill_blank | solution | unknown",
                                    "answer": "答案，无法确定为空字符串",
                                    "analysis": "解析，无法确定为空字符串",
                                    "knowledgePoints": ["知识点名称"],
                                    "difficulty": "easy | medium | hard",
                                    "score": 0,
                                    "contextMatched": False,
                                    "answerEvidence": "OCR 中支持答案匹配的最短原文证据",
                                    "analysisEvidence": "OCR 中支持解析匹配的最短原文证据",
                                    "subQuestions": [
                                        {
                                            "id": "输入小问 id",
                                            "label": "(1)",
                                            "type": "choice | fill_blank | solution | unknown",
                                            "answer": "该小问答案，无法确定为空字符串",
                                            "analysis": "该小问解析，无法确定为空字符串",
                                            "knowledgePoints": ["知识点名称"],
                                            "difficulty": "easy | medium | hard",
                                            "score": 0,
                                            "contextMatched": False,
                                            "answerEvidence": "OCR 中支持该小问答案的最短原文证据",
                                            "analysisEvidence": "OCR 中支持该小问解析的最短原文证据",
                                            "warnings": ["需要人工复核的问题"],
                                        }
                                    ],
                                    "warnings": ["需要人工复核的问题"],
                                }
                            ]
                        },
                        "answerContext": answer_context[: int(os.getenv("LLM_ENRICH_ANSWER_MAX_CHARS", "20000"))],
                        "paperOcrContext": paper_ocr_context[: int(os.getenv("LLM_ENRICH_PAPER_MAX_CHARS", "30000"))],
                        "questions": compact_questions,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }
    started = time.perf_counter()

    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        parsed = extract_json_object(content)
        result: dict[str, dict[str, Any]] = {}
        for item in parsed.get("questions", []):
            if not isinstance(item, dict):
                continue
            question_id = str(item.get("id") or "")
            if not question_id:
                continue
            result[question_id] = normalize_enriched_question(item)
        return result, {
            "source": "ai",
            "provider": status["provider"],
            "model": status["model"],
            "error": None,
            "llmCall": llm_call_metadata("metadata-enrich", started, "success", item_count=len(compact_questions)),
        }
    except Exception as exc:
        return {}, {
            "source": "rule",
            "provider": status["provider"],
            "model": status["model"],
            "error": f"AI 题目元数据补全失败，已使用本地默认值：{exc}",
            "llmCall": llm_call_metadata("metadata-enrich", started, "failed", error=str(exc), item_count=len(compact_questions)),
        }


def normalize_enriched_question(item: dict[str, Any], require_evidence: bool = True) -> dict[str, Any]:
    """归一化 LLM 增强后的题目字段。"""
    question_type = normalize_type(item.get("type"))
    difficulty = str(item.get("difficulty") or "medium").strip().lower()
    if difficulty not in {"easy", "medium", "hard"}:
        difficulty = "medium"
    score = item.get("score", 0)
    try:
        normalized_score = float(score)
    except (TypeError, ValueError):
        normalized_score = 0
    warnings = normalize_string_list(item.get("warnings"))
    context_matched = item.get("contextMatched")
    has_evidence = bool(str(item.get("answerEvidence") or item.get("analysisEvidence") or "").strip())
    should_keep_solution = True
    if require_evidence:
        should_keep_solution = context_matched is True or has_evidence
    warning_text = "\n".join(warnings)
    if require_evidence and re.search(r"未在|没有.*证据|无法.*匹配|无法.*确定|需人工复核", warning_text):
        should_keep_solution = False
    answer = str(item.get("answer") or "").strip()
    analysis = str(item.get("analysis") or "").strip()
    sub_questions = normalize_enriched_sub_questions(item.get("subQuestions") or item.get("children"))
    if sub_questions:
        answer = ""
        analysis = ""
    if not should_keep_solution:
        if answer or analysis:
            warnings.append("模型返回的答案或解析缺少 OCR 上下文证据，已清空并保留人工复核提示")
        answer = ""
        analysis = ""
    return {
        "type": question_type,
        "answer": answer,
        "analysis": analysis,
        "knowledgePoints": normalize_string_list(item.get("knowledgePoints")),
        "difficulty": difficulty,
        "score": normalized_score,
        "subQuestions": sub_questions,
        "contextMatched": bool(should_keep_solution),
        "answerEvidence": str(item.get("answerEvidence") or "").strip(),
        "analysisEvidence": str(item.get("analysisEvidence") or "").strip(),
        "warnings": warnings,
    }


def normalize_corrections(value: Any) -> list[dict[str, str]]:
    """归一化 LLM 返回的修正项列表。"""
    if not isinstance(value, list):
        return []
    corrections: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        corrections.append(
            {
                "before": str(item.get("before") or ""),
                "after": str(item.get("after") or ""),
                "reason": str(item.get("reason") or ""),
            }
        )
    return corrections


def compact_sub_questions(value: Any) -> list[dict[str, Any]]:
    """构造发送给 LLM 的小问紧凑上下文。"""
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "id": item.get("id") or f"sub_{index}",
                "label": item.get("label") or f"({index})",
                "type": item.get("type") or "unknown",
                "stemMarkdown": item.get("stemMarkdown") or item.get("manualMarkdown") or item.get("stem") or "",
                "answer": item.get("answer") or item.get("suggestedAnswer") or "",
                "analysis": item.get("analysis") or item.get("explanation") or "",
                "knowledgePoints": item.get("knowledgePoints", []),
                "difficulty": item.get("difficulty") or "",
                "score": item.get("score"),
                "options": item.get("options", []),
                "images": [{"path": image.get("path")} for image in item.get("images", []) if isinstance(image, dict)],
            }
        )
    return result


def normalize_solution_sub_questions(value: Any) -> list[dict[str, Any]]:
    """归一化 AI 标准化返回的小问答案/解析。"""
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "id": str(item.get("id") or f"sub_{index}"),
                "label": str(item.get("label") or f"({index})"),
                "stemMarkdown": str(item.get("stemMarkdown") or item.get("manualMarkdown") or item.get("stem") or "").strip(),
                "answer": str(item.get("answer") or item.get("suggestedAnswer") or "").strip(),
                "analysis": str(item.get("analysis") or item.get("explanation") or "").strip(),
                "contextMatched": bool(item.get("contextMatched")),
                "answerEvidence": str(item.get("answerEvidence") or "").strip(),
                "analysisEvidence": str(item.get("analysisEvidence") or "").strip(),
                "warnings": normalize_string_list(item.get("warnings")),
            }
        )
    return result


def normalize_enriched_sub_questions(value: Any) -> list[dict[str, Any]]:
    """归一化 AI 元数据补全返回的小问字段。"""
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        normalized = normalize_enriched_question({**item, "id": item.get("id") or f"sub_{index}"}, require_evidence=True)
        normalized["id"] = str(item.get("id") or f"sub_{index}")
        normalized["label"] = str(item.get("label") or f"({index})")
        result.append(normalized)
    return result


def preserve_local_boundaries_after_truncation(
    parsed: dict[str, Any],
    local_boundaries: dict[str, Any],
    max_chars: int,
    source_length: int,
) -> dict[str, Any]:
    """Preserve local question boundaries that the LLM could not see."""
    if source_length <= max_chars:
        return parsed
    if not isinstance(parsed.get("questions"), list):
        return parsed

    questions = [q for q in parsed.get("questions", []) if isinstance(q, dict)]
    sections = [s for s in parsed.get("sections", []) if isinstance(s, dict)]
    existing_starts: set[int] = set()
    for question in questions:
        try:
            existing_starts.add(int(question.get("start")))
        except (TypeError, ValueError):
            continue
    existing_section_ids = {str(s.get("id") or "") for s in sections}

    appended_count = 0
    for local_question in local_boundaries.get("questions") or []:
        if not isinstance(local_question, dict):
            continue
        start = local_question.get("start")
        if not isinstance(start, int) or start < max_chars or start in existing_starts:
            continue
        questions.append(local_question)
        existing_starts.add(start)
        appended_count += 1
        section_id = str(local_question.get("sectionId") or "")
        if section_id and section_id not in existing_section_ids:
            local_section = next(
                (
                    section
                    for section in local_boundaries.get("sections") or []
                    if isinstance(section, dict) and str(section.get("id") or "") == section_id
                ),
                None,
            )
            if local_section:
                sections.append(local_section)
                existing_section_ids.add(section_id)

    if appended_count:
        warnings = normalize_string_list(parsed.get("warnings"))
        warnings.append(f"OCR 文本超过 LLM 边界确认窗口，已保留截断点后的 {appended_count} 个本地题目边界")
        parsed = {**parsed, "sections": sections, "questions": questions, "warnings": warnings}
    return parsed


def normalize_string_list(value: Any) -> list[str]:
    """归一化字符串列表。"""
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def build_payload(markdown: str, assets: list[dict[str, Any]], local_structured: dict[str, Any], model: str) -> dict[str, Any]:
    """构造 LLM 拆题请求 payload。"""
    asset_refs = [{"name": asset.get("name"), "path": asset.get("path")} for asset in assets]
    local_reference = {
        "sections": local_structured.get("sections", []),
        "questionCount": len(local_structured.get("questions", [])),
    }

    system_prompt = (
        "你是试卷 OCR 结构化拆题引擎。"
        "只返回一个合法 JSON 对象，不要返回 Markdown 代码块、解释或额外文字。"
        "必须保留题干中的 Markdown、LaTeX 数学公式和必要换行。"
        "不得编造图片路径；题图只能从用户给出的 assets.path 中选择。"
    )
    user_prompt = {
        "task": "将整卷 OCR Markdown 拆成大题、小题和小问。选择题需要拆出选项；同一道大题的（1）（2）等小问必须打包在同一个 questions.subQuestions 结构内，同时兼容输出 children。",
        "schema": {
            "sections": [
                {
                    "id": "section_1",
                    "title": "一、选择题",
                    "type": "choice | fill_blank | solution | unknown",
                    "questions": [
                        {
                            "id": "q_1",
                            "number": 1,
                            "type": "choice | fill_blank | solution | unknown",
                            "sectionId": "section_1",
                            "sectionTitle": "一、选择题",
                            "pageIndex": None,
                            "stemMarkdown": "题干，不要包含 A/B/C/D 选项",
                            "images": [{"path": "images/example.jpg"}],
                            "options": [{"label": "A", "content": "选项内容"}],
                            "answer": "无小问时的整题答案；没有则为空字符串",
                            "analysis": "无小问时的整题解析；没有则为空字符串",
                            "subQuestions": [
                                {
                                    "id": "q_1_sub_1",
                                    "label": "(1)",
                                    "type": "choice | fill_blank | solution | unknown",
                                    "stemMarkdown": "小问题干，不要包含答案解析",
                                    "images": [],
                                    "options": [],
                                    "answer": "该小问答案；没有则为空字符串",
                                    "analysis": "该小问解析；没有则为空字符串",
                                    "knowledgePoints": [],
                                    "difficulty": "easy | medium | hard",
                                    "score": 0,
                                }
                            ],
                            "children": "与 subQuestions 相同的兼容数组",
                        }
                    ],
                }
            ]
        },
        "rules": [
            "大题标题放入 sections.title，大题下的小题放入 sections.questions。",
            "必须主动识别（1）（2）（3）、①②③、一二三等小问边界；不要依赖本地规则。",
            "如果一道大题包含小问，将共用材料/大题题干作为父题 stemMarkdown，小问放入 subQuestions，并同步到 children。",
            "有小问时父题 answer、analysis 必须为空字符串；答案/解析要尽量对应到具体小问。",
            "小问题干不得混入答案、解析、参考答案或解答过程；这些内容应放到小问 answer、analysis。",
            "选择题 stemMarkdown 不要包含选项，选项放入 options。",
            "非选择题 options 返回空数组。",
            "没有题图时 images 返回空数组。",
            "图片只能引用 assets 中的 path。",
            "无法判断题型时 type 使用 unknown。",
            "尽量以 localReference 的拆分结果作为参考，但要修正本地规则造成的错拆、漏拆和题图归属错误。",
        ],
        "assets": asset_refs,
        "localReference": local_reference,
        "ocrMarkdown": markdown,
    }
    return {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
        ],
    }


def build_boundary_payload(
    markdown: str,
    assets: list[dict[str, Any]],
    local_boundaries: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    """Build prompt for boundary-only question splitting."""
    asset_refs = [{"name": asset.get("name"), "path": asset.get("path")} for asset in assets]
    compact_local = {
        "sections": local_boundaries.get("sections", []),
        "questions": [
            {
                "id": q.get("id"),
                "number": q.get("number"),
                "type": q.get("type"),
                "sectionId": q.get("sectionId"),
                "sectionTitle": q.get("sectionTitle"),
                "start": q.get("start"),
                "end": q.get("end"),
                "subQuestions": q.get("subQuestions", []),
                "options": q.get("options", []),
                "images": q.get("images", []),
            }
            for q in local_boundaries.get("questions", [])
            if isinstance(q, dict)
        ],
    }
    system_prompt = (
        "你是 OCR 题目边界确认器。只返回合法 JSON 对象。"
        "你的任务只允许确认或修正 start/end 边界、题型、题号、小问 label、选项 label 和题图 path。"
        "禁止输出、改写或补充任何题干、答案、解析、知识点、公式正文。"
        "所有 start/end 都必须是 ocrMarkdown 字符偏移，且必须落在输入文本范围内。"
        "题图 path 只能来自 assets.path。"
        "不确定时保留 localBoundaries，并在 warnings 中说明。"
    )
    user_prompt = {
        "task": "确认 OCR Markdown 的大题、题号、小问、选择题选项和题图归属边界。不要生成题干正文。",
        "schema": {
            "sections": [
                {"id": "section_1", "title": "一、选择题", "type": "choice | fill_blank | solution | unknown", "start": 0, "end": 100}
            ],
            "questions": [
                {
                    "id": "q_1",
                    "number": 1,
                    "type": "choice | fill_blank | solution | unknown",
                    "sectionId": "section_1",
                    "sectionTitle": "一、选择题",
                    "start": 0,
                    "end": 100,
                    "subQuestions": [
                        {"id": "q_1_sub_1", "label": "(1)", "start": 20, "contentStart": 23, "end": 60}
                    ],
                    "options": [
                        {"label": "A", "start": 60, "contentStart": 63, "end": 70}
                    ],
                    "images": [{"path": "images/example.png", "start": 10, "end": 30}],
                }
            ],
            "warnings": ["无法高置信确认的问题"],
        },
        "rules": [
            "大题下出现 (1)(2)(3)、①②③、（一）（二）等，通常可作为 subQuestions 候选。",
            "如果题型是 fill_blank，或题干包含“填空”“横线”“空缺”“补全”“填写”等空位题提示，这些符号也可能只是空位编号、证明步骤编号或提示语；只有后面有完整独立问句时才确认为 subQuestions。",
            "选择题选项必须是稳定连续的 A/B/C/D 边界；不要把公式变量 A、B 当作选项。",
            "父题共用材料应位于 question.start 到第一个 subQuestion.start 之间。",
            "如果 localBoundaries 已合理，直接沿用。",
            "不要返回 stemMarkdown、answer、analysis、knowledgePoints 或任何正文内容。",
        ],
        "assets": asset_refs,
        "localBoundaries": compact_local,
        "ocrMarkdown": markdown,
    }
    return {
        "model": model,
        "temperature": 0.0,
        "max_tokens": int_env("LLM_BOUNDARY_MAX_TOKENS", 4096, 512, 16000),
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
        ],
    }


def extract_json_object(content: str) -> dict[str, Any]:
    """从模型文本响应中提取 JSON 对象。"""
    cleaned = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.S)
    if fenced:
        cleaned = fenced.group(1)
    cleaned = re.sub(r"(?is)<think>.*?</think>", "", cleaned).strip()
    decoder = json.JSONDecoder()
    parsed: Any | None = None
    if cleaned.startswith("{"):
        try:
            parsed = decoder.raw_decode(cleaned)[0]
        except json.JSONDecodeError:
            parsed = None
    if parsed is None:
        for match in re.finditer(r"\{", cleaned):
            try:
                candidate = decoder.raw_decode(cleaned[match.start() :])[0]
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                parsed = candidate
                break
    if parsed is None:
        raise ValueError("模型未返回 JSON 对象")
    if not isinstance(parsed, dict):
        raise ValueError("模型返回值不是 JSON 对象")
    return parsed


def normalize_llm_result(raw: dict[str, Any], assets: list[dict[str, Any]], local_structured: dict[str, Any]) -> dict[str, Any]:
    """归一化 LLM 拆题结果。"""
    raw_sections = raw.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        raise ValueError("模型结果缺少 sections")

    sections: list[dict[str, Any]] = []
    flat_questions: list[dict[str, Any]] = []

    for section_index, raw_section in enumerate(raw_sections, start=1):
        if not isinstance(raw_section, dict):
            continue
        section_id = str(raw_section.get("id") or f"section_{section_index}")
        section_title = str(raw_section.get("title") or f"第 {section_index} 大题")
        section_type = normalize_type(raw_section.get("type"))
        section = {
            "id": section_id,
            "title": section_title,
            "type": section_type,
            "questions": [],
        }
        raw_questions = raw_section.get("questions", [])
        if isinstance(raw_questions, list):
            for question_index, raw_question in enumerate(raw_questions, start=1):
                question = normalize_question(raw_question, assets, section, question_index)
                if question:
                    section["questions"].append(question)
                    flatten_question(question, flat_questions)
        sections.append(section)

    if not flat_questions:
        raise ValueError("模型结果未生成题目")

    return {"sections": sections, "questions": flat_questions}


def normalize_question(
    raw_question: Any,
    assets: list[dict[str, Any]],
    section: dict[str, Any],
    fallback_index: int,
) -> dict[str, Any] | None:
    """归一化单道 LLM 题目对象。"""
    if not isinstance(raw_question, dict):
        return None

    number = parse_number(raw_question.get("number"), fallback_index)
    question_type = normalize_type(raw_question.get("type") or section["type"])
    question_id = str(raw_question.get("id") or f"q_{number}")
    stem = str(raw_question.get("stemMarkdown") or raw_question.get("stem") or "").strip()
    options = normalize_options(raw_question.get("options"), question_type)
    images = normalize_images(raw_question.get("images"), assets)
    raw_sub_questions = raw_question.get("subQuestions")
    if not isinstance(raw_sub_questions, list):
        raw_sub_questions = raw_question.get("children", [])

    question = {
        "id": question_id,
        "number": number,
        "type": question_type,
        "sectionId": str(raw_question.get("sectionId") or section["id"]),
        "sectionTitle": str(raw_question.get("sectionTitle") or section["title"]),
        "pageIndex": parse_page_index(raw_question.get("pageIndex")),
        "stemMarkdown": stem,
        "answer": str(raw_question.get("answer") or "").strip(),
        "analysis": str(raw_question.get("analysis") or "").strip(),
        "images": images,
        "options": options,
        "children": [],
        "subQuestions": [],
    }

    if isinstance(raw_sub_questions, list):
        for child_index, raw_child in enumerate(raw_sub_questions, start=1):
            child = normalize_sub_question(raw_child, assets, question, child_index)
            if child:
                question["children"].append(child)
        question["subQuestions"] = question["children"]
    if question["subQuestions"]:
        question["answer"] = ""
        question["analysis"] = ""
    return question


def normalize_sub_question(
    raw_child: Any,
    assets: list[dict[str, Any]],
    parent: dict[str, Any],
    fallback_index: int,
) -> dict[str, Any] | None:
    """归一化单个小问对象。"""
    if not isinstance(raw_child, dict):
        return None
    child_id = str(raw_child.get("id") or f"{parent['id']}_sub_{fallback_index}")
    label = str(raw_child.get("label") or raw_child.get("number") or f"({fallback_index})").strip()
    question_type = normalize_type(raw_child.get("type") or parent.get("type"))
    stem = str(raw_child.get("stemMarkdown") or raw_child.get("manualMarkdown") or raw_child.get("stem") or "").strip()
    difficulty = str(raw_child.get("difficulty") or "").strip().lower()
    if difficulty not in {"easy", "medium", "hard"}:
        difficulty = ""
    try:
        score = float(raw_child.get("score", 0) or 0)
    except (TypeError, ValueError):
        score = 0.0
    child = {
        "id": child_id,
        "label": label or f"({fallback_index})",
        "number": parse_number(raw_child.get("number"), fallback_index),
        "type": question_type,
        "sectionId": parent["sectionId"],
        "sectionTitle": parent["sectionTitle"],
        "pageIndex": parse_page_index(raw_child.get("pageIndex")),
        "stem": str(raw_child.get("stem") or stem),
        "stemMarkdown": stem,
        "manualMarkdown": str(raw_child.get("manualMarkdown") or stem),
        "answer": str(raw_child.get("answer") or "").strip(),
        "analysis": str(raw_child.get("analysis") or "").strip(),
        "knowledgePointIds": raw_child.get("knowledgePointIds", []) if isinstance(raw_child.get("knowledgePointIds"), list) else [],
        "knowledgePoints": normalize_string_list(raw_child.get("knowledgePoints")),
        "difficulty": difficulty,
        "score": score,
        "images": normalize_images(raw_child.get("images"), assets),
        "options": normalize_options(raw_child.get("options"), question_type),
        "children": [],
        "subQuestions": [],
    }
    return child


def normalize_type(value: Any) -> str:
    """归一化题型值。"""
    normalized = str(value or "unknown").strip()
    return normalized if normalized in VALID_QUESTION_TYPES else "unknown"


def parse_number(value: Any, fallback: int) -> int:
    """解析题号，失败时使用兜底值。"""
    if isinstance(value, int):
        return value
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else fallback


def parse_page_index(value: Any) -> int | None:
    """解析页码索引。"""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else None


def normalize_options(raw_options: Any, question_type: str) -> list[dict[str, str]]:
    """归一化选择题选项。"""
    if question_type != "choice" or not isinstance(raw_options, list):
        return []
    options: list[dict[str, str]] = []
    seen_labels: set[str] = set()
    for option in raw_options:
        if not isinstance(option, dict):
            continue
        label = str(option.get("label") or "").strip().upper()
        content = str(option.get("content") or "").strip()
        if not label or label in seen_labels:
            continue
        seen_labels.add(label)
        options.append({"label": label, "content": content})
    return options


def normalize_images(raw_images: Any, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """归一化 LLM 返回的题图引用。"""
    if not isinstance(raw_images, list):
        return []
    images: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for raw_image in raw_images:
        image_path = raw_image.get("path") if isinstance(raw_image, dict) else raw_image
        if not image_path:
            continue
        image = image_from_assets(str(image_path), assets)
        if image["path"] in seen_paths:
            continue
        seen_paths.add(image["path"])
        images.append(image)
    return images


def normalize_asset_path(path: str) -> str:
    """归一化 OCR 资源路径。"""
    return path.split("?", 1)[0].split("#", 1)[0].lstrip("./")


def image_from_assets(image_path: str, assets: list[dict[str, Any]]) -> dict[str, Any]:
    """从资源列表中匹配并构造题图对象。"""
    normalized_image_path = normalize_asset_path(image_path)
    image_name = Path(normalized_image_path).name
    matched_asset = next(
        (
            asset
            for asset in assets
            if normalize_asset_path(str(asset.get("path", ""))) == normalized_image_path
            or normalize_asset_path(str(asset.get("path", ""))).endswith(f"/{normalized_image_path}")
            or asset.get("name") == image_name
        ),
        None,
    )
    if matched_asset:
        return {
            "name": matched_asset["name"],
            "path": matched_asset["path"],
            "url": matched_asset["url"],
        }
    return {"name": image_name, "path": normalized_image_path, "url": None}


def flatten_question(question: dict[str, Any], output: list[dict[str, Any]]) -> None:
    """将题目和子题扁平化追加到输出列表。"""
    output.append(question)
    children = question.get("subQuestions") if isinstance(question.get("subQuestions"), list) else question.get("children", [])
    for child in children:
        if isinstance(child, dict):
            flatten_question(child, output)
