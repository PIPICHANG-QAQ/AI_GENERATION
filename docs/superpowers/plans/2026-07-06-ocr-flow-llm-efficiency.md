# OCR Flow LLM Efficiency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce OCR task wall-clock time by keeping the OCR main path focused on deterministic structure work, skipping unnecessary LLM calls, using bounded concurrency only for low-confidence work, and recording timing data for future capacity decisions.

**Architecture:** Keep Java as the platform-facing API and keep Python worker as the OCR/AI execution boundary. The first iteration stays inside `backend/python-worker/app` and does not add a new platform status model; it adds LLM call metrics, a local-boundary confidence gate, chunked boundary refinement, and bounded semantic-repair concurrency. Deferred/background AI enrichment is treated as a second iteration because it should be coordinated through Java `ai-flow` rather than mutating Python OCR outputs after Java has already synchronized them.

**Tech Stack:** Python 3.10+, FastAPI worker, `httpx`, `unittest`, existing OCR job JSON store, Spring Boot Java backend for runtime exposure, existing docs and smoke scripts.

---

## Context Read

Relevant docs and code checked before writing this plan:

- `docs/architecture/TECHNICAL_DESIGN.md`: OCR pipeline, LLM fallback behavior, LLM config keys, OCR step semantics.
- `docs/product/OCR_PHASE_1_SPEC.md`: OCR-Flow output contract, boundary rules, answer evidence rules, provider replacement boundary.
- `docs/delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md`: OCR-Flow runtime and internal worker endpoint boundaries.
- `docs/delivery/OPERATIONS_GUIDE.md`: AI concurrency recommendation, performance baseline table, timeout and troubleshooting guidance.
- `docs/delivery/ACCEPTANCE.md`: OCR success must survive LLM failure; AI standardization failure must not block manual review.
- `docs/development/CONTRIBUTING.md`: Python worker changes require tests and docs updates; performance/concurrency config changes must update docs.
- `backend/python-worker/app/ocr_processing.py`: current OCR flow, current unconditional `llm-boundary-refine`, current serial `autoSemanticRepair`.
- `backend/python-worker/app/llm_splitter.py`: LLM status, boundary prompt, standardize prompt, metadata enrichment.
- `backend/python-worker/app/worker_base.py`: existing `ocrFlow.steps[].durationMs` and `elapsedMs`.
- `backend/python-worker/tests`: existing `unittest` layout.

## Target Behavior

The optimized OCR path should behave as follows:

1. OCR main path always produces Markdown/JSON/assets, local boundaries, structure, visual repair metadata, structure validation, and math validation.
2. If local boundaries are high-confidence, skip `llm-boundary-refine` and record why it was skipped.
3. If local boundaries are low-confidence, split by local question ranges and call boundary LLM concurrently with a fixed maximum concurrency.
4. If chunked boundary refinement fails or returns invalid ranges, fall back to the corresponding local boundaries without failing the OCR job.
5. `autoSemanticRepair` should not dominate the OCR main path. First iteration should support a default non-blocking mode by skipping automatic semantic repair in OCR, plus an opt-in bounded inline-concurrent mode for deployments that still want automatic repair before review.
6. Every LLM call should return timing metadata: call type, provider, model, duration, status, chunk index if applicable, fallback reason, and error class without exposing API keys or full prompts.

### Follow-up: AI Standardize / Analysis Robustness on 2026-07-08

- AI 标准化和 AI 解析继续保持单题人工按钮的同步请求语义，但新增任务级有界并发：`LLM_STANDARDIZE_MAX_CONCURRENCY` / `LLM_ANALYSIS_MAX_CONCURRENCY`，并保留 endpoint 级 `LOCAL_LLM_MAX_CONCURRENCY` / `LLM_EXTERNAL_MAX_CONCURRENCY` 限流。
- AI 标准化 LLM 超时、限流或 schema 失败时返回 `source=rules-fallback`、`fallbackUsed=true`、`retryable=true` 的本地候选，不再直接抛 `409 标准化失败`；兜底候选不进入成功缓存。
- AI 解析 LLM 失败时返回 `metadata.fallbackUsed=true`、`metadata.retryable=true` 的可重试响应；前端只提示用户稍后重试或人工填写，不清空当前答案/解析。
- 大量用户上线或批量 AI 加工成为常态时，下一步应把同步按钮升级为 Java `ai-flow` 后台 job + MQ/Redis 队列，增加租户/用户/模型 endpoint 三级限流、幂等、重试、死信和可观测指标。

## File Structure

Modify:

- `backend/python-worker/app/llm_splitter.py`
  - Add LLM runtime option parsing.
  - Add LLM call timing metadata.
  - Add chunk-level boundary payload support.
  - Add a new public boundary refinement entry point that can skip, single-call, or chunked-call.

- `backend/python-worker/app/question_boundary.py`
  - Add local-boundary confidence scoring helpers.
  - Add chunk planning helpers that preserve absolute source offsets.
  - Keep structure building unchanged except for accepting merged chunk boundaries.

- `backend/python-worker/app/ocr_processing.py`
  - Replace unconditional `refine_question_boundaries_with_llm` with confidence-gated boundary refinement.
  - Replace serial `apply_auto_semantic_repairs` with mode-aware behavior and bounded concurrency.
  - Attach `llmMetrics` to OCR outputs and OCR job flow metadata.

- `backend/python-worker/app/worker_base.py`
  - Preserve existing OCR step duration behavior.
  - Optionally add `details` or `metrics` preservation in step summaries if needed by the worker output contract.

- `backend/python-worker/tests/test_llm_splitter.py`
  - Add tests for LLM option parsing, timing metadata, single-call fallback, chunked merge metadata, and error fallback.

- `backend/python-worker/tests/test_question_boundary.py`
  - Add tests for high-confidence local boundary detection, low-confidence detection, and chunk range planning.

- `backend/python-worker/tests/test_import_services.py`
  - Add tests only if import question serialization needs to preserve new `autoSemanticRepair` or `llmMetrics` fields.

- `.env.example`
  - Add concurrency, gating, semantic-repair mode, and metrics config keys.

- `docs/architecture/TECHNICAL_DESIGN.md`
  - Update OCR flow description to include local confidence gate, chunked LLM refinement, and LLM metrics.

- `docs/product/OCR_PHASE_1_SPEC.md`
  - Update OCR-Flow rules for high-confidence local boundary skip and low-confidence chunk refinement.

- `docs/delivery/OPERATIONS_GUIDE.md`
  - Update AI concurrency config, performance baseline guidance, and troubleshooting.

- `docs/delivery/ACCEPTANCE.md`
  - Add acceptance checks for LLM skip/fallback metadata and OCR success when chunk calls fail.

- `docs/CHANGELOG.md`
  - Add a dated entry for OCR/LLM efficiency changes.

Do not modify in the first iteration:

- `question-engine/openapi/question-engine.v1.yaml`
- Generated SDKs
- Java platform-facing API models

Reason: the first iteration stores optimization metadata inside existing OCR job outputs and existing runtime diagnostics. It should not change the stable platform API surface.

---

### Task 1: Add LLM Runtime Options and Timing Metadata

**Files:**
- Modify: `backend/python-worker/app/llm_splitter.py`
- Test: `backend/python-worker/tests/test_llm_splitter.py`

- [x] **Step 1: Write tests for option parsing**

Add tests to `backend/python-worker/tests/test_llm_splitter.py`:

```python
from app.llm_splitter import llm_runtime_options


def test_llm_runtime_options_reads_safe_defaults(self):
    with patch.dict(os.environ, {}, clear=True):
        options = llm_runtime_options()

    self.assertEqual(1, options["maxConcurrency"])
    self.assertEqual(5, options["boundaryChunkSize"])
    self.assertEqual("skip", options["autoSemanticRepairMode"])
    self.assertTrue(options["metricsEnabled"])


def test_llm_runtime_options_clamps_concurrency(self):
    with patch.dict(
        os.environ,
        {
            "LLM_MAX_CONCURRENCY": "99",
            "LLM_BOUNDARY_CHUNK_SIZE": "0",
            "OCR_AUTO_SEMANTIC_REPAIR_MODE": "inline-concurrent",
            "LLM_METRICS_ENABLED": "false",
        },
        clear=True,
    ):
        options = llm_runtime_options()

    self.assertEqual(8, options["maxConcurrency"])
    self.assertEqual(1, options["boundaryChunkSize"])
    self.assertEqual("inline-concurrent", options["autoSemanticRepairMode"])
    self.assertFalse(options["metricsEnabled"])
```

- [x] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=backend/python-worker backend/python-worker/.venv/bin/python -m unittest discover -s backend/python-worker/tests -p test_llm_splitter.py
```

Expected: fail because `llm_runtime_options` does not exist.

- [x] **Step 3: Add option helpers**

Add to `backend/python-worker/app/llm_splitter.py` near `llm_status()`:

```python
def int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def llm_runtime_options() -> dict[str, Any]:
    mode = os.getenv("OCR_AUTO_SEMANTIC_REPAIR_MODE", "skip").strip().lower()
    if mode not in {"skip", "inline", "inline-concurrent"}:
        mode = "skip"
    return {
        "maxConcurrency": int_env("LLM_MAX_CONCURRENCY", 1, 1, 8),
        "boundaryChunkSize": int_env("LLM_BOUNDARY_CHUNK_SIZE", 5, 1, 20),
        "autoSemanticRepairMode": mode,
        "metricsEnabled": bool_env("LLM_METRICS_ENABLED", True),
    }
```

- [x] **Step 4: Add timing metadata helper**

Add to `backend/python-worker/app/llm_splitter.py`:

```python
def llm_call_metadata(
    call_type: str,
    started_at: float,
    status: str,
    error: str | None = None,
    chunk_index: int | None = None,
    item_count: int | None = None,
) -> dict[str, Any]:
    llm = llm_status()
    duration_ms = max(0, int((time.perf_counter() - started_at) * 1000))
    metadata = {
        "callType": call_type,
        "status": status,
        "provider": llm["provider"],
        "model": llm["model"],
        "durationMs": duration_ms,
        "error": error,
    }
    if chunk_index is not None:
        metadata["chunkIndex"] = chunk_index
    if item_count is not None:
        metadata["itemCount"] = item_count
    return metadata
```

Also add `import time` at the top of `backend/python-worker/app/llm_splitter.py`.

- [x] **Step 5: Run tests**

Run:

```bash
./scripts/test_python_worker.sh
```

Expected: all Python worker tests pass.

---

### Task 2: Add Local Boundary Confidence Scoring and Chunk Planning

**Files:**
- Modify: `backend/python-worker/app/question_boundary.py`
- Test: `backend/python-worker/tests/test_question_boundary.py`

- [x] **Step 1: Write confidence tests**

Add tests:

```python
from app.question_boundary import evaluate_boundary_confidence, plan_boundary_chunks


def test_high_confidence_choice_boundaries_can_skip_llm(self):
    markdown = """一、选择题
1. 下列说法正确的是（ ）
A. 甲
B. 乙
C. 丙
D. 丁
2. 下列说法错误的是（ ）
A. 甲
B. 乙
C. 丙
D. 丁
"""
    boundaries = detect_local_boundaries(markdown, [])
    confidence = evaluate_boundary_confidence(markdown, boundaries, [])

    self.assertTrue(confidence["highConfidence"])
    self.assertEqual([], confidence["lowConfidenceQuestionIds"])


def test_low_confidence_when_question_numbers_are_not_monotonic(self):
    markdown = """一、选择题
1. 第一题
3. 第三题
"""
    boundaries = detect_local_boundaries(markdown, [])
    confidence = evaluate_boundary_confidence(markdown, boundaries, [])

    self.assertFalse(confidence["highConfidence"])
    self.assertIn("question-number-gap", confidence["reasons"])


def test_boundary_chunks_preserve_absolute_offsets(self):
    markdown = """一、选择题
1. 第一题
2. 第二题
3. 第三题
4. 第四题
"""
    boundaries = detect_local_boundaries(markdown, [])
    chunks = plan_boundary_chunks(markdown, boundaries, chunk_size=2)

    self.assertEqual(2, len(chunks))
    self.assertEqual(0, chunks[0]["index"])
    self.assertLess(chunks[0]["start"], chunks[0]["end"])
    self.assertGreaterEqual(chunks[1]["start"], chunks[0]["start"])
    self.assertTrue(all(question["start"] >= chunks[0]["start"] for question in chunks[0]["localBoundaries"]["questions"]))
```

- [x] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=backend/python-worker backend/python-worker/.venv/bin/python -m unittest discover -s backend/python-worker/tests -p test_question_boundary.py
```

Expected: fail because helpers do not exist.

- [x] **Step 3: Implement `evaluate_boundary_confidence`**

Add to `backend/python-worker/app/question_boundary.py`:

```python
def evaluate_boundary_confidence(markdown: str, boundaries: dict[str, Any], assets: list[dict[str, Any]]) -> dict[str, Any]:
    questions = [q for q in boundaries.get("questions", []) if isinstance(q, dict)]
    reasons: list[str] = []
    low_ids: list[str] = []
    if not questions:
        reasons.append("no-question-boundaries")
    numbers = [int(q.get("number")) for q in questions if isinstance(q.get("number"), int)]
    if len(numbers) >= 2:
        for previous, current in zip(numbers, numbers[1:]):
            if current <= previous or current - previous > 1:
                reasons.append("question-number-gap")
                break
    for question in questions:
        qid = str(question.get("id") or "")
        start = question.get("start")
        end = question.get("end")
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start or end > len(markdown):
            reasons.append("invalid-question-range")
            if qid:
                low_ids.append(qid)
            continue
        if question.get("type") == "choice" and len(question.get("options") or []) not in {0, 4}:
            reasons.append("unstable-choice-options")
            if qid:
                low_ids.append(qid)
    asset_paths = {str(asset.get("path") or "") for asset in assets if isinstance(asset, dict)}
    for image in boundaries.get("images") or []:
        path = str(image.get("path") or "")
        if path and path not in asset_paths:
            reasons.append("unknown-image-path")
            break
    unique_reasons = list(dict.fromkeys(reasons))
    return {
        "highConfidence": not unique_reasons,
        "reasons": unique_reasons,
        "questionCount": len(questions),
        "lowConfidenceQuestionIds": list(dict.fromkeys(low_ids)),
    }
```

- [x] **Step 4: Implement `plan_boundary_chunks`**

Add to `backend/python-worker/app/question_boundary.py`:

```python
def plan_boundary_chunks(markdown: str, boundaries: dict[str, Any], chunk_size: int) -> list[dict[str, Any]]:
    source = str(markdown or "")
    questions = [q for q in boundaries.get("questions", []) if isinstance(q, dict)]
    if not questions:
        return []
    chunk_size = max(1, int(chunk_size or 1))
    chunks: list[dict[str, Any]] = []
    sections = [s for s in boundaries.get("sections", []) if isinstance(s, dict)]
    for index, offset in enumerate(range(0, len(questions), chunk_size)):
        group = questions[offset : offset + chunk_size]
        start = max(0, min(int(q.get("start") or 0) for q in group))
        end = min(len(source), max(int(q.get("end") or start) for q in group))
        section_ids = {str(q.get("sectionId") or "") for q in group}
        chunk_sections = [section for section in sections if str(section.get("id") or "") in section_ids]
        chunks.append(
            {
                "index": index,
                "start": start,
                "end": end,
                "markdown": source[start:end],
                "localBoundaries": {
                    "source": boundaries.get("source", "rule-boundary"),
                    "sections": chunk_sections,
                    "questions": group,
                    "images": [
                        image
                        for image in boundaries.get("images", [])
                        if isinstance(image, dict)
                        and isinstance(image.get("start"), int)
                        and start <= int(image.get("start")) < end
                    ],
                    "questionCount": len(group),
                },
            }
        )
    return chunks
```

- [x] **Step 5: Run tests**

Run:

```bash
./scripts/test_python_worker.sh
```

Expected: all Python worker tests pass.

---

### Task 3: Implement Confidence-Gated Boundary Refinement

**Files:**
- Modify: `backend/python-worker/app/llm_splitter.py`
- Modify: `backend/python-worker/app/ocr_processing.py`
- Modify: `backend/python-worker/app/worker_base.py` only if step details are needed
- Test: `backend/python-worker/tests/test_llm_splitter.py`

- [x] **Step 1: Add tests for skip metadata**

Add test:

```python
from app.llm_splitter import boundary_refinement_skipped_metadata


def test_boundary_skip_metadata_marks_local_confidence(self):
    metadata = boundary_refinement_skipped_metadata({"highConfidence": True, "reasons": []})

    self.assertEqual("local-boundary", metadata["source"])
    self.assertFalse(metadata["fallback"])
    self.assertEqual("local-high-confidence", metadata["reason"])
```

- [x] **Step 2: Implement skip metadata helper**

Add to `backend/python-worker/app/llm_splitter.py`:

```python
def boundary_refinement_skipped_metadata(confidence: dict[str, Any]) -> dict[str, Any]:
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
```

- [x] **Step 3: Change `collect_outputs` to skip high-confidence local boundaries**

In `backend/python-worker/app/ocr_processing.py`, import:

```python
from app.question_boundary import evaluate_boundary_confidence, plan_boundary_chunks
```

After `local_boundaries = detect_local_boundaries(markdown, assets)`, add:

```python
boundary_confidence = evaluate_boundary_confidence(markdown, local_boundaries, assets)
```

Replace the unconditional call:

```python
llm_boundaries, boundary_splitter = refine_question_boundaries_with_llm(markdown, assets, local_boundaries)
```

with:

```python
if boundary_confidence.get("highConfidence"):
    llm_boundaries = None
    boundary_splitter = boundary_refinement_skipped_metadata(boundary_confidence)
else:
    llm_boundaries, boundary_splitter = refine_question_boundaries_with_llm(markdown, assets, local_boundaries)
```

Update the step message:

```python
boundary_step_status = "skipped" if boundary_confidence.get("highConfidence") else ("success" if llm_boundaries else "skipped")
boundary_step_message = (
    "本地边界高置信，跳过 AI 边界确认"
    if boundary_confidence.get("highConfidence")
    else ("AI 边界确认完成" if llm_boundaries else str(boundary_splitter.get("error") or "使用本地边界候选"))
)
```

- [x] **Step 4: Preserve confidence in outputs**

Add `boundaryConfidence` to the returned outputs:

```python
"boundaryConfidence": boundary_confidence,
```

- [x] **Step 5: Run tests**

Run:

```bash
./scripts/test_python_worker.sh
```

Expected: all Python worker tests pass.

---

### Task 4: Add Chunked Concurrent Boundary Refinement

**Files:**
- Modify: `backend/python-worker/app/llm_splitter.py`
- Modify: `backend/python-worker/app/ocr_processing.py`
- Test: `backend/python-worker/tests/test_llm_splitter.py`
- Test: `backend/python-worker/tests/test_question_boundary.py`

- [x] **Step 1: Add merge behavior tests**

Add a test around a pure merge helper:

```python
from app.llm_splitter import merge_boundary_chunk_results


def test_merge_boundary_chunk_results_keeps_chunk_order_and_warnings(self):
    local = {
        "sections": [{"id": "section_1", "title": "一、选择题", "type": "choice"}],
        "questions": [{"id": "q_1", "start": 0}, {"id": "q_2", "start": 20}],
    }
    chunks = [
        {"index": 0, "result": {"sections": [], "questions": [{"id": "q_1", "start": 0}], "warnings": ["w1"]}},
        {"index": 1, "result": None, "localBoundaries": {"sections": [], "questions": [{"id": "q_2", "start": 20}]}, "error": "timeout"},
    ]

    merged = merge_boundary_chunk_results(local, chunks)

    self.assertEqual(["q_1", "q_2"], [item["id"] for item in merged["questions"]])
    self.assertTrue(any("timeout" in warning for warning in merged["warnings"]))
```

- [x] **Step 2: Implement chunk result merge helper**

Add to `backend/python-worker/app/llm_splitter.py`:

```python
def merge_boundary_chunk_results(local_boundaries: dict[str, Any], chunk_results: list[dict[str, Any]]) -> dict[str, Any]:
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
    deduped_questions = []
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
```

- [x] **Step 3: Implement chunked boundary entry point**

Add to `backend/python-worker/app/llm_splitter.py`:

```python
def refine_question_boundaries_in_chunks(
    chunks: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    local_boundaries: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    options = llm_runtime_options()
    if len(chunks) <= 1 or options["maxConcurrency"] <= 1:
        return refine_question_boundaries_with_llm(
            chunks[0]["markdown"] if chunks else "",
            assets,
            chunks[0]["localBoundaries"] if chunks else local_boundaries,
        )
    calls: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=options["maxConcurrency"]) as executor:
        futures = {
            executor.submit(refine_question_boundaries_with_llm, chunk["markdown"], assets, chunk["localBoundaries"]): chunk
            for chunk in chunks
        }
        for future in as_completed(futures):
            chunk = futures[future]
            try:
                result, metadata = future.result()
                calls.append({**metadata, "chunkIndex": chunk["index"], "questionCount": len(chunk["localBoundaries"].get("questions") or [])})
                results.append({**chunk, "result": result, "error": metadata.get("error")})
            except Exception as exc:
                calls.append({"chunkIndex": chunk["index"], "status": "failed", "error": str(exc)})
                results.append({**chunk, "result": None, "error": str(exc)})
    merged = merge_boundary_chunk_results(local_boundaries, results)
    return merged, {
        "source": "llm-boundary-chunked",
        "provider": llm_status()["provider"],
        "model": llm_status()["model"],
        "fallback": False,
        "error": None,
        "llmCalls": calls,
        "chunkCount": len(chunks),
        "maxConcurrency": options["maxConcurrency"],
        "warnings": normalize_string_list(merged.get("warnings")),
    }
```

Also add imports:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
```

- [x] **Step 4: Use chunked refinement in `collect_outputs`**

In `backend/python-worker/app/ocr_processing.py`, replace the low-confidence branch:

```python
chunks = plan_boundary_chunks(markdown, local_boundaries, llm_runtime_options()["boundaryChunkSize"])
llm_boundaries, boundary_splitter = refine_question_boundaries_in_chunks(chunks, assets, local_boundaries)
```

Import the new functions from `app.llm_splitter`.

- [x] **Step 5: Validate merged chunks before use**

After chunked refinement and before assigning `boundary_source`, add:

```python
candidate_structured = build_structure_from_boundaries(markdown, llm_boundaries, assets) if llm_boundaries else {}
candidate_validation = validate_structure(candidate_structured, markdown, assets) if candidate_structured.get("questions") else {"valid": False}
if llm_boundaries and not candidate_validation.get("valid"):
    boundary_splitter = rule_splitter_metadata("分片 AI 边界确认结构校验失败，已回退本地边界候选")
    llm_boundaries = None
```

- [x] **Step 6: Run tests**

Run:

```bash
./scripts/test_python_worker.sh
python -m compileall backend/python-worker/app
```

Expected: all tests pass and compileall reports no syntax errors.

---

### Task 5: Make Auto Semantic Repair Mode-Aware and Bounded Concurrent

**Files:**
- Modify: `backend/python-worker/app/ocr_processing.py`
- Modify: `backend/python-worker/app/llm_splitter.py` if shared concurrency helpers are reused
- Test: `backend/python-worker/tests/test_llm_splitter.py`
- Test: add `backend/python-worker/tests/test_ocr_processing.py` if no suitable test file exists

- [x] **Step 1: Add tests for skip mode**

Create `backend/python-worker/tests/test_ocr_processing.py`:

```python
import os
import unittest
from unittest.mock import patch

from app.ocr_processing import apply_auto_semantic_repairs


class OcrProcessingTest(unittest.TestCase):
    def test_auto_semantic_repair_skip_mode_does_not_call_llm(self):
        structured = {"sections": [{"questions": [{"id": "q1", "stemMarkdown": '若 5"=4，则求值'}]}], "questions": []}
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "key", "OCR_AUTO_SEMANTIC_REPAIR_MODE": "skip", "ENABLE_LLM_SPLIT": "true"}):
            with patch("app.ocr_processing.standardize_markdown_with_llm") as standardize:
                result = apply_auto_semantic_repairs(structured)

        standardize.assert_not_called()
        self.assertEqual("skipped", result["mode"])
        self.assertEqual(1, result["candidateCount"])


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Add tests for bounded concurrent mode**

Add:

```python
    def test_auto_semantic_repair_inline_concurrent_applies_safe_result(self):
        structured = {"sections": [{"questions": [{"id": "q1", "stemMarkdown": '若 5"=4，则求值'}]}], "questions": []}
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "key", "OCR_AUTO_SEMANTIC_REPAIR_MODE": "inline-concurrent", "LLM_MAX_CONCURRENCY": "2", "ENABLE_LLM_SPLIT": "true"}):
            with patch("app.ocr_processing.standardize_markdown_with_llm", return_value=("若 $5^n=4$，则求值", {"source": "ai", "provider": "dashscope", "model": "deepseek-v4-pro", "confidence": "high", "corrections": [], "warnings": [], "error": None})):
                result = apply_auto_semantic_repairs(structured)

        self.assertEqual("inline-concurrent", result["mode"])
        self.assertEqual(1, result["appliedCount"])
```

- [x] **Step 3: Update `apply_auto_semantic_repairs` mode behavior**

In `backend/python-worker/app/ocr_processing.py`, import `llm_runtime_options`.

At the start of `apply_auto_semantic_repairs`, add mode to summary:

```python
options = llm_runtime_options()
summary["mode"] = options["autoSemanticRepairMode"]
```

Build candidates before calling LLM:

```python
candidates = []
for question in iter_structured_questions(structured):
    question_id = str(question.get("id") or id(question))
    if question_id in seen_question_ids:
        continue
    seen_question_ids.add(question_id)
    if needs_auto_semantic_repair(question):
        candidates.append(question)
summary["candidateCount"] = len(candidates)
```

If mode is `skip`, return without LLM:

```python
if options["autoSemanticRepairMode"] == "skip":
    summary["skippedCount"] = len(candidates)
    summary["error"] = "OCR 主链路跳过自动 AI 语义修复，保留人工校验和 AI 标准化入口"
    return summary
```

- [x] **Step 4: Add bounded concurrent execution**

For `inline-concurrent`, use `ThreadPoolExecutor(max_workers=options["maxConcurrency"])` to call `standardize_markdown_with_llm(question_to_edit_markdown(question))`.

Keep the existing safety gate unchanged:

```python
can_apply = confidence != "low" and not has_semantic_ocr_issue(remaining_issues)
```

Only mutate question objects after each future returns and passes the same safety checks.

- [x] **Step 5: Keep serial inline mode for diagnostics**

If `OCR_AUTO_SEMANTIC_REPAIR_MODE=inline`, run the existing serial logic. This preserves a simple mode for debugging provider rate-limit issues.

- [x] **Step 6: Run tests**

Run:

```bash
./scripts/test_python_worker.sh
python -m compileall backend/python-worker/app
```

Expected: all tests pass.

---

### Task 6: Attach LLM Metrics to OCR Outputs and Step Messages

**Files:**
- Modify: `backend/python-worker/app/llm_splitter.py`
- Modify: `backend/python-worker/app/ocr_processing.py`
- Test: `backend/python-worker/tests/test_llm_splitter.py`
- Test: `backend/python-worker/tests/test_ocr_processing.py`

- [x] **Step 1: Add metrics expectations**

Add tests that assert:

```python
self.assertIn("llmCalls", boundary_splitter)
self.assertIn("durationMs", boundary_splitter["llmCalls"][0])
```

For skipped local confidence:

```python
self.assertEqual([], boundary_splitter["llmCalls"])
```

- [x] **Step 2: Add metadata to existing LLM calls**

In each LLM function that calls `httpx.Client.post`, wrap call sections with:

```python
started = time.perf_counter()
```

On success, include:

```python
"llmCall": llm_call_metadata("boundary-refine", started, "success")
```

On exception, include:

```python
"llmCall": llm_call_metadata("boundary-refine", started, "failed", error=str(exc))
```

Do this for:

- `refine_question_boundaries_with_llm`
- `standardize_markdown_with_llm`
- `generate_question_analysis_with_llm`
- `enrich_questions_metadata_with_llm`

- [x] **Step 3: Aggregate OCR-level metrics**

In `collect_outputs`, build:

```python
llm_metrics = []
for item in boundary_splitter.get("llmCalls") or []:
    llm_metrics.append(item)
for item in auto_semantic_repair.get("llmCalls") or []:
    llm_metrics.append(item)
```

Return:

```python
"llmMetrics": {
    "enabled": llm_runtime_options()["metricsEnabled"],
    "callCount": len(llm_metrics),
    "totalDurationMs": sum(int(item.get("durationMs") or 0) for item in llm_metrics),
    "calls": llm_metrics,
},
```

- [x] **Step 4: Keep metrics sanitized**

Do not store:

- API keys
- Authorization headers
- full prompts
- full OCR Markdown
- image base64

Metrics should only include call type, provider, model, status, duration, chunk index, item count, and short error string.

- [x] **Step 5: Run tests**

Run:

```bash
./scripts/test_python_worker.sh
python -m compileall backend/python-worker/app
```

Expected: tests and compileall pass.

---

### Task 7: Update Configuration and Documentation

**Files:**
- Modify: `.env.example`
- Modify: `docs/architecture/TECHNICAL_DESIGN.md`
- Modify: `docs/product/OCR_PHASE_1_SPEC.md`
- Modify: `docs/delivery/OPERATIONS_GUIDE.md`
- Modify: `docs/delivery/ACCEPTANCE.md`
- Modify: `docs/CHANGELOG.md`

- [x] **Step 1: Add env keys**

Add under the LLM config block in `.env.example`:

```text
# LLM efficiency controls. Keep concurrency within model gateway rate limits.
LLM_MAX_CONCURRENCY=1
LLM_BOUNDARY_CHUNK_SIZE=5
LLM_METRICS_ENABLED=true

# OCR automatic semantic repair mode:
# skip: do not run automatic AI semantic repair in OCR main path
# inline: run repairs serially for diagnostics
# inline-concurrent: run eligible repairs with bounded concurrency
OCR_AUTO_SEMANTIC_REPAIR_MODE=skip
```

- [x] **Step 2: Update technical design**

In `docs/architecture/TECHNICAL_DESIGN.md`, update the LLM integration section to say:

- Local boundary confidence is evaluated before LLM.
- High-confidence local boundaries skip AI boundary confirmation.
- Low-confidence ranges are chunked by local question ranges.
- Chunk failures fall back to local boundaries and do not fail OCR.
- `autoSemanticRepair` defaults to skip in OCR main path and can be enabled inline by configuration.
- `llmMetrics` records call count and duration.

- [x] **Step 3: Update OCR phase spec**

In `docs/product/OCR_PHASE_1_SPEC.md`, update OCR-Flow rules:

- OCR output contract remains `markdown/json/assets/sections/questions/mathValidation`.
- Boundary LLM is a low-confidence refinement mechanism, not a mandatory step.
- Automatic semantic repair must not overwrite low-confidence repairs.
- Manual AI standardization remains the authoritative human-approved repair path.

- [x] **Step 4: Update operations guide**

In `docs/delivery/OPERATIONS_GUIDE.md`, add the new config keys to the Python worker config table and performance section. Update the benchmark table guidance to record:

- `llmMetrics.callCount`
- `llmMetrics.totalDurationMs`
- `ocrFlow.steps[].durationMs`
- count of skipped local-confidence boundary refinements
- count of chunk fallbacks

- [x] **Step 5: Update acceptance**

In `docs/delivery/ACCEPTANCE.md`, add checks:

- LLM unavailable still returns OCR outputs.
- High-confidence local sample reports `llm-boundary-refine` skipped.
- Low-confidence sample with mocked chunk failure still succeeds with fallback metadata.
- `llmMetrics` does not expose prompts, API keys, or base64 images.

- [x] **Step 6: Update changelog**

Add an entry:

```markdown
## 2026-07-06

- 优化 OCR-Flow LLM 调用策略：高置信本地边界跳过 AI 边界确认，低置信边界支持按题段分片并发确认。
- 新增 LLM 调用耗时指标，用于后续性能基准和容量规划。
- 新增 OCR 自动语义修复模式配置，默认不阻塞 OCR 主链路。
```

- [x] **Step 7: Run documentation checks**

Run:

```bash
python scripts/check_question_engine_contract.py
python scripts/check_project_portability.py
python scripts/package_question_engine_delivery.py --check-only --include-local-platform
```

Expected: all checks pass. If a check fails because local generated artifacts or dependencies are missing, record the exact reason in the implementation summary.

---

### Task 8: Run End-to-End Verification

**Files:**
- No code files modified in this task.

- [x] **Step 1: Run Python worker tests**

Run:

```bash
./scripts/test_python_worker.sh
python -m compileall backend/python-worker/app
```

Expected: all tests pass.

- [x] **Step 2: Run Java tests if Java-facing runtime output changed**

Run:

```bash
(cd backend && JAVA_HOME=$(/usr/libexec/java_home -v 17) mvn test)
```

Expected: Maven test suite passes.

- [x] **Step 3: Run basic deploy smoke**

Run:

```bash
./scripts/deploy_local.sh --skip-smoke
./scripts/smoke_deploy_basic.py
```

Expected: Python worker, Java backend, and local platform health checks pass.

- [x] **Step 4: Run OCR smoke**

Run:

```bash
./scripts/deploy_local.sh --with-mineru
./scripts/smoke_ocr.py
```

Expected:

- OCR job succeeds.
- OCR result includes `sections`, `questions`, `mathValidation`.
- OCR result includes `boundaryConfidence`.
- OCR result includes `llmMetrics`.
- LLM failure or skip does not fail the OCR job.

Verification note: latest local high-confidence Markdown smoke ran in isolated `PYTHON_WORKER_STORAGE_ROOT=/tmp/ai_generation_ocr_efficiency_smoke` and finished with `status=success`, `ocrFlow.status=success`, `outputs.boundaryConfidence.highConfidence=true`, `outputs.splitter.source=local-boundary`, `outputs.splitter.reason=local-high-confidence`, `outputs.llmMetrics.callCount=0`, and `outputs.autoSemanticRepair.mode=skipped`.

- [x] **Step 5: Run AI smoke only when key is configured**

Run:

```bash
./scripts/deploy_local.sh --with-ai
./scripts/smoke_ai.py
```

Expected: AI standardization and analysis still work through Java-created AI jobs.

Verification note: skipped in this local run because `DEEPSEEK_API_KEY` / `DASHSCOPE_API_KEY` / `ALIYUN_LLM_API_KEY` were not configured.

Additional verification on 2026-07-06:

```bash
backend/python-worker/.venv/bin/python -m pytest \
  backend/python-worker/tests/test_llm_splitter.py \
  backend/python-worker/tests/test_question_boundary.py \
  backend/python-worker/tests/test_ocr_processing.py
./scripts/test_python_worker.sh
python3 -m unittest scripts/test_check_project_portability.py
python3 scripts/check_project_portability.py
```

Result: targeted OCR/LLM efficiency tests passed (`33 passed`), full Python worker tests passed (`48 tests`), portability script unit test passed, and `check_project_portability.py` completed with `project portability check passed`.

Additional server rollout verification on 2026-07-08:

- Server project directory fixed to `/home/user/AI_GENERATION_DOCKER`; the public customer preview address is `http://120.211.112.121:5173/`.
- AI boundary confirmation runs against the external full model by default on the server. Effective settings: `LLM_BOUNDARY_CHUNK_SIZE=5`, `LLM_BOUNDARY_MAX_CONCURRENCY=4`, `LLM_EXTERNAL_MAX_CONCURRENCY=4`.
- MinerU was moved to resident `mineru-api` mode through `MINERU_API_URL=http://127.0.0.1:8002`; ModelScope cache is host-mounted at `server-data/modelscope-cache`.
- Server MinerU venv has `onnxruntime-gpu==1.23.2`; available providers include `TensorrtExecutionProvider`, `CUDAExecutionProvider`, and `CPUExecutionProvider`.
- GPU split verified: AI_GENERATION / MinerU uses physical GPU0 and vLLM / `aux-qwen3-32b-fp8` uses physical GPU1.
- Import task `import_task_20260708_052629_3d1b2b05` (`title=4123`) was rebuilt with the new platform sequence numbering rule: old `28` questions became `56` questions, with repeated OCR ids preserved as `q_1__occurrence_2` through `q_28__occurrence_2`.
- Related server records were written to `docs/server/README.md`, `docs/server/CHANGELOG.md`, and `docs/server/RUNBOOK.md`.

---

## Rollout Plan

1. Ship Task 1 and Task 2 first. These are mostly additive and give confidence scoring plus metrics foundations.
2. Ship Task 3 next with `LLM_MAX_CONCURRENCY=1`. This validates high-confidence skip without introducing chunk concurrency yet.
3. Ship Task 4 with `LLM_MAX_CONCURRENCY=2` in development, then raise to `4` only after model gateway limits are known.
4. Ship Task 5 with default `OCR_AUTO_SEMANTIC_REPAIR_MODE=skip`. Enable `inline-concurrent` only for controlled testing.
5. Use Task 6 metrics to fill the operations performance table before deciding whether a second iteration should create Java-managed background AI enrichment jobs.

## Acceptance Criteria

- OCR task succeeds when LLM is disabled, unavailable, timeout, or returns invalid JSON.
- High-confidence local boundary samples skip LLM and still pass `validate_structure`.
- Low-confidence samples call chunked boundary refinement and fall back per chunk on failure.
- OCR outputs include sanitized LLM timing metadata.
- `autoSemanticRepair` no longer serially blocks OCR by default.
- Existing local platform import, manual review, AI standardization, and question package output remain compatible.

## Known Non-Goals for This Iteration

- Do not add a Java-visible processing status for background AI enrichment.
- Do not change OpenAPI or generated SDK in the first iteration.
- Do not directly expose Python worker APIs to the platform.
- Do not add a full queue/MQ implementation.
- Do not use LLM to generate question text, answers, or analysis during boundary confirmation.

## Follow-Up Iteration: Java-Managed Background AI Enrichment

If metrics show `autoSemanticRepair` or metadata enrichment remains valuable but too slow for OCR completion, plan a second iteration through Java `ai-flow`:

1. Java marks OCR job `待校验` after deterministic OCR outputs are ready.
2. Java creates `java_ai_jobs` for optional semantic repair or metadata enrichment.
3. Frontend displays AI enhancement progress separately from OCR completion.
4. Successful AI jobs write candidates, not silent overwrites, unless existing confidence gates pass.
5. Callback-flow can notify platform when optional AI enrichment finishes.

This second iteration should update OpenAPI, SDK, interface guide, status/error docs, acceptance scripts, and Java tests because it changes platform-visible behavior.
