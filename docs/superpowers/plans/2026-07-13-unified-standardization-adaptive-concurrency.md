# Unified Standardization and Adaptive Concurrency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make single-question and global standardization use the same rule/OCR/cache/LLM pipeline, preserve question structure, expose truthful question-level progress, and adapt real LLM concurrency between 2 and 8 before deploying the branch to the server.

**Architecture:** Java owns canonical request construction, durable batch lifecycle, stale-input protection, and atomic writes. Python owns fast-path selection, result structure guards, and one shared adaptive LLM gate. The frontend renders canonical-question progress and execution-path counts; global and single-question flows differ only in candidate-versus-safe-write behavior.

**Tech Stack:** Java 17/Spring Boot/MyBatis Plus/H2 or MySQL, Python 3/FastAPI/httpx, React/TypeScript/Vitest, Docker Compose/Nginx.

---

## File map

- Create `backend/src/main/java/com/aigeneration/questionbank/domain/service/StandardizationRequestFactory.java`: canonical request, hints, editable choice Markdown, and input hash.
- Create `backend/src/test/java/com/aigeneration/questionbank/StandardizationRequestFactoryTest.java`: request parity and hash behavior.
- Modify `backend/src/main/java/com/aigeneration/questionbank/domain/service/AiFlowOrchestrationService.java`: use the factory for every import-question standardization request.
- Create `backend/python-worker/app/adaptive_concurrency.py`: shared priority-aware AIMD gate.
- Create `backend/python-worker/tests/test_adaptive_concurrency.py`: deterministic gate state tests.
- Modify `backend/python-worker/app/llm_splitter.py`: replace fixed standardization semaphore with the adaptive gate and record provider outcomes.
- Modify `backend/python-worker/app/import_services.py`: stable pipeline envelope and structure guard.
- Modify `backend/python-worker/app/worker_base.py`: accept pipeline/request metadata.
- Modify `backend/python-worker/tests/test_import_services.py`: fast-path and structure-guard regressions.
- Modify `backend/python-worker/tests/test_llm_splitter.py`: adaptive-gate integration metadata.
- Modify `backend/src/main/java/com/aigeneration/questionbank/domain/service/StandardizationBatchService.java`: one-question counts, request source, truthful item status, stale hash, and progress summaries.
- Modify `backend/src/main/java/com/aigeneration/questionbank/domain/entity/StandardizationBatchItemEntity.java`: persist execution metadata.
- Modify `backend/src/main/java/com/aigeneration/questionbank/migration/SchemaMigrator.java`: add compatible item metadata columns.
- Modify `backend/src/test/java/com/aigeneration/questionbank/StandardizationBatchServiceTest.java`: request source, canonical counts, and summary paths.
- Modify `local-platform/src/lib/standardization-job.ts`: question-level progress and execution-path labels.
- Modify `local-platform/src/lib/standardization-job.test.ts`: new progress contract.
- Modify `local-platform/src/components/question-bank/ImportWorkbenchTask.tsx`: render execution-path and adaptive-concurrency summary.
- Modify `.env.example` and `docker-compose.server.yml`: safe v2 feature flags and adaptive limits.
- Modify `question-engine/openapi/question-engine.v1.yaml` and `scripts/check_question_engine_contract.py`: document and validate added response fields.
- Modify `docs/delivery/ACCEPTANCE.md` and `docs/server/RUNBOOK.md`: acceptance and rollback commands.

### Task 1: Canonical Java standardization request

**Files:**
- Create: `backend/src/main/java/com/aigeneration/questionbank/domain/service/StandardizationRequestFactory.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/StandardizationRequestFactoryTest.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/AiFlowOrchestrationService.java:117-121,354-359,638-646`

- [ ] **Step 1: Write the failing request-factory tests**

```java
@Test
void choiceOptionsArePresentInMarkdownAndStructuredHints() {
    ImportQuestionEntity question = choiceQuestion();
    Map<String, Object> request = factory.build(question, "题干", "原始 OCR", "single");
    assertThat(request.get("markdown").toString()).contains("\\begin{tasks}(4)", "\\task 食品夹");
    Map<?, ?> hints = (Map<?, ?>) request.get("structuredHints");
    assertThat((List<?>) hints.get("options")).hasSize(4);
    assertThat(request).containsKeys("pipelineVersion", "inputHash", "requestSource");
}

@Test
void inputHashChangesWhenOptionPlacementOrSubQuestionChanges() {
    ImportQuestionEntity question = choiceQuestion();
    String before = factory.inputHash(question, "题干", "原始 OCR");
    question.setImagePlacementsJson("[{\"imageId\":\"img-1\",\"target\":{\"kind\":\"option\",\"optionLabel\":\"B\"}}]");
    assertThat(factory.inputHash(question, "题干", "原始 OCR")).isNotEqualTo(before);
}
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
cd backend && mvn -q -Dtest=StandardizationRequestFactoryTest test
```

Expected: compilation failure because `StandardizationRequestFactory` does not exist.

- [ ] **Step 3: Implement the minimal factory**

```java
@Component
public class StandardizationRequestFactory {
    static final String PIPELINE_VERSION = "standardization.v2";
    private final JsonSupport json;

    public Map<String, Object> build(ImportQuestionEntity question, String requestedMarkdown,
                                     String rawOcrContext, String requestSource) {
        List<Object> options = json.readList(question.getOptionsJson());
        List<Object> images = json.readList(question.getImagesJson());
        List<Object> placements = json.readList(question.getImagePlacementsJson());
        List<Object> subQuestions = json.readList(question.getChildrenJson());
        String markdown = withChoiceOptions(firstText(requestedMarkdown,
                question.getManualMarkdown(), question.getStemMarkdown()), question.getType(), options);
        Map<String, Object> hints = new LinkedHashMap<>();
        hints.put("questionId", question.getId());
        hints.put("number", question.getQuestionNumber());
        hints.put("type", text(question.getType()));
        hints.put("answer", text(question.getAnswer()));
        hints.put("analysis", text(question.getAnalysis()));
        hints.put("options", options);
        hints.put("images", images);
        hints.put("imagePlacements", placements);
        hints.put("subQuestions", subQuestions);
        hints.put("requestPriority", "single".equals(requestSource) ? "interactive" : "batch");
        Map<String, Object> request = new LinkedHashMap<>();
        request.put("pipelineVersion", PIPELINE_VERSION);
        request.put("markdown", markdown);
        request.put("rawOcrContext", text(rawOcrContext));
        request.put("structuredHints", hints);
        request.put("requestSource", requestSource);
        request.put("inputHash", inputHash(question, markdown, rawOcrContext));
        return request;
    }
}
```

Implement `withChoiceOptions` so it leaves an existing complete tasks block unchanged and otherwise serializes non-empty structured options as `\begin{tasks}(4)...\task...\end{tasks}`. Hash canonical JSON containing pipeline version, Markdown, raw OCR, options, images, placements, and children with SHA-256.

- [ ] **Step 4: Route both single and batch calls through the factory**

Inject `StandardizationRequestFactory` into `AiFlowOrchestrationService`. Replace `standardizeRequest(...)` for import questions with:

```java
String source = "global".equals(text(payload.get("requestSource"))) ? "global" : "single";
Map<String, Object> request = standardizationRequests.build(
        question,
        text(payload.get("markdown")),
        importRawContext(question),
        source
);
```

Keep ad-hoc Markdown standardization on its existing lightweight request path.

Before a requested automatic write, reload the question and build its current hash from persisted fields. If it differs from the request `inputHash`, set `writeDecision=review_required`, add `stale_input`, and skip `updateStandardizedResult`. Require worker `applyRecommendation=safe_to_apply` in `standardizeWriteAllowed`. Set Java's final decision explicitly: `candidate` for single preview, `applied` after successful global write, `unchanged` for a safe no-op, and `review_required` when a guard blocks writing.

- [ ] **Step 5: Run Java tests and verify GREEN**

```bash
cd backend && mvn -q -Dtest=StandardizationRequestFactoryTest,DomainControllerTest test
```

Expected: both test classes pass.

- [ ] **Step 6: Commit**

```bash
git add backend/src/main/java/com/aigeneration/questionbank/domain/service/StandardizationRequestFactory.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/service/AiFlowOrchestrationService.java \
  backend/src/test/java/com/aigeneration/questionbank/StandardizationRequestFactoryTest.java
git commit -m "feat: unify standardization requests"
```

### Task 2: Stable worker pipeline envelope and structure guard

**Files:**
- Modify: `backend/python-worker/app/worker_base.py:123-128`
- Modify: `backend/python-worker/app/import_services.py:34-82,692-755,912-1094`
- Modify: `backend/python-worker/tests/test_import_services.py`

- [ ] **Step 1: Write failing fast-path and structure tests**

```python
def test_cached_standardize_response_reports_cache_without_model_call():
    hints = {"type": "choice", "options": [{"label": "A", "content": "甲"}, {"label": "B", "content": "乙"}]}
    with patch("app.import_services.standardize_markdown_with_llm") as call:
        call.return_value = ("题干", {"source": "ai", "confidence": "medium", "warnings": [], "corrections": []})
        first = standardize_markdown_ai_response("题干", structured_hints=hints)
        second = standardize_markdown_ai_response("题干", structured_hints=hints)
    assert first["executionPath"] == "llm"
    assert second["executionPath"] == "cache"
    assert second["cachedExecutionPath"] == "llm"
    assert second["modelInvoked"] is False
    assert call.call_count == 1

def test_same_count_image_options_with_removed_refs_require_review():
    hints = {
        "type": "choice",
        "options": [
            {"label": "A", "content": "![](图1)"},
            {"label": "B", "content": "![](图2)"},
        ],
        "images": [{"imageId": "i1", "label": "图1"}, {"imageId": "i2", "label": "图2"}],
    }
    with patch("app.import_services.standardize_markdown_with_llm", return_value=(
        r"题干\n\n\begin{tasks}(2)\n\task 文字甲\n\task 文字乙\n\end{tasks}",
        {"source": "ai", "confidence": "medium", "warnings": [], "corrections": []},
    )):
        result = standardize_markdown_ai_response("题干", structured_hints=hints)
    assert result["applyRecommendation"] == "review_required"
    assert "option_image_reference_removed" in result["reviewReasons"]
```

- [ ] **Step 2: Run the tests and verify RED**

```bash
PYTHONPATH=backend/python-worker /Users/chang/Documents/AI_GENERATION/backend/python-worker/.venv/bin/pytest -q \
  backend/python-worker/tests/test_import_services.py -k 'cached_standardize_response_reports_cache_without_model_call or same_count_image_options_with_removed_refs_require_review'
```

Expected: failures for missing envelope fields.

- [ ] **Step 3: Add request metadata fields**

Extend `MarkdownPayload` with defaults:

```python
pipelineVersion: str = "standardization.v1"
inputHash: str = ""
requestSource: str = "single"
```

Pass these fields from `/api/markdown/standardize/ai` and `/worker/ai/standardize` into `standardize_markdown_ai_response` without changing legacy callers.

- [ ] **Step 4: Add one envelope finalizer**

```python
def finalize_standardize_response(response, structured_hints, execution_path, *, model_invoked=False,
                                  cache_hit=False, cached_execution_path=None):
    result = copy.deepcopy(response)
    reasons = structure_review_reasons(result, structured_hints)
    result["executionPath"] = execution_path
    result["modelInvoked"] = model_invoked
    result["cacheHit"] = cache_hit
    result["cachedExecutionPath"] = cached_execution_path
    result["reviewReasons"] = reasons
    result["applyRecommendation"] = "review_required" if reasons or result.get("standardizer", {}).get("applyBlocked") else "safe_to_apply"
    result["originalStructure"] = structure_summary(structured_hints)
    result["resultStructure"] = structure_summary(result)
    result["providerCallAttempts"] = len(result.get("standardizer", {}).get("llmCalls") or [])
    return result
```

Call it on every return path. A cached result must set the current `executionPath` to `cache`, preserve the original path as `cachedExecutionPath`, and set current `modelInvoked=false`.

Echo `pipelineVersion` and `inputHash` into the envelope so Java can audit which immutable input produced the candidate.

- [ ] **Step 5: Implement strict structure reasons**

Compare original structured options against result Markdown/options. Emit stable reasons for option count changes, label changes, and removal of image labels/refs. Preserve existing automatic recovery when the model drops the whole option block; block same-count candidates that silently replace image refs with text.

- [ ] **Step 6: Run focused and full Python tests**

```bash
PYTHONPATH=backend/python-worker /Users/chang/Documents/AI_GENERATION/backend/python-worker/.venv/bin/pytest -q \
  backend/python-worker/tests/test_import_services.py
PYTHONPATH=backend/python-worker /Users/chang/Documents/AI_GENERATION/backend/python-worker/.venv/bin/pytest -q \
  backend/python-worker/tests
```

Expected: focused and full suites pass.

- [ ] **Step 7: Commit**

```bash
git add backend/python-worker/app/worker_base.py backend/python-worker/app/import_services.py \
  backend/python-worker/tests/test_import_services.py
git commit -m "feat: guard standardization structure"
```

### Task 3: Shared adaptive LLM gate

**Files:**
- Create: `backend/python-worker/app/adaptive_concurrency.py`
- Create: `backend/python-worker/tests/test_adaptive_concurrency.py`
- Modify: `backend/python-worker/app/llm_splitter.py:27-33,275-302,900-950`
- Modify: `backend/python-worker/tests/test_llm_splitter.py`

- [ ] **Step 1: Write deterministic AIMD tests**

```python
def test_gate_increases_after_success_window():
    gate = AdaptiveConcurrencyGate(initial=4, minimum=2, maximum=8, success_window=3, cooldown_seconds=30)
    for _ in range(3):
        gate.record_success(100)
    assert gate.snapshot()["limit"] == 5

def test_gate_halves_on_rate_limit_and_respects_floor():
    gate = AdaptiveConcurrencyGate(initial=8, minimum=2, maximum=8, success_window=20, cooldown_seconds=30)
    gate.record_failure("rate_limit")
    assert gate.snapshot()["limit"] == 4
    gate.record_failure("service_unavailable")
    assert gate.snapshot()["limit"] == 2

def test_interactive_waiter_precedes_batch_waiter():
    gate = AdaptiveConcurrencyGate(initial=2, minimum=2, maximum=8, success_window=20, cooldown_seconds=30)
    assert gate.priority_value("interactive") < gate.priority_value("batch")
```

- [ ] **Step 2: Run tests and verify RED**

```bash
PYTHONPATH=backend/python-worker /Users/chang/Documents/AI_GENERATION/backend/python-worker/.venv/bin/pytest -q \
  backend/python-worker/tests/test_adaptive_concurrency.py
```

Expected: import failure because `app.adaptive_concurrency` does not exist.

- [ ] **Step 3: Implement the gate**

Create a condition-based gate with `slot(priority)`, `record_success(duration_ms)`, `record_failure(kind)`, and `snapshot()`. Use an incrementing ticket and priority heap so interactive waiters run before batch waiters while FIFO is preserved inside a priority. Do not resize a `BoundedSemaphore`; compare `active < limit` under one condition so limit changes are safe.

The failure classifier must map 429 to `rate_limit`, 503 to `service_unavailable`, and timeout exceptions to `timeout`. On each failure set `limit=max(minimum, limit//2)` and `cooldownUntil=clock()+cooldownSeconds`.

- [ ] **Step 4: Replace only the standardization task semaphore**

```python
priority = str((structured_hints or {}).get("requestPriority") or "batch")
gate = standardization_concurrency_gate()
with gate.slot(priority):
    try:
        data, cache_hit = post_llm_json_for_endpoint(...)
        gate.record_success(duration_ms)
    except Exception as exc:
        gate.record_failure(classify_provider_failure(exc))
        raise
```

Leave boundary and analysis semaphores unchanged. Add `adaptiveConcurrency` snapshot to standardizer metadata. Raise the external endpoint configurable maximum from 4 to 8 without changing its environment-controlled value.

- [ ] **Step 5: Run focused and full worker tests**

```bash
PYTHONPATH=backend/python-worker /Users/chang/Documents/AI_GENERATION/backend/python-worker/.venv/bin/pytest -q \
  backend/python-worker/tests/test_adaptive_concurrency.py backend/python-worker/tests/test_llm_splitter.py
PYTHONPATH=backend/python-worker /Users/chang/Documents/AI_GENERATION/backend/python-worker/.venv/bin/pytest -q backend/python-worker/tests
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/python-worker/app/adaptive_concurrency.py backend/python-worker/app/llm_splitter.py \
  backend/python-worker/tests/test_adaptive_concurrency.py backend/python-worker/tests/test_llm_splitter.py
git commit -m "feat: adapt standardization concurrency"
```

### Task 4: Durable question-level batch progress

**Files:**
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/StandardizationBatchService.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/entity/StandardizationBatchItemEntity.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/migration/SchemaMigrator.java`
- Modify: `backend/src/test/java/com/aigeneration/questionbank/StandardizationBatchServiceTest.java`

- [ ] **Step 1: Write failing batch tests**

```java
@Test
void batchUsesOneQuestionItemAndMarksGlobalRequestSource() throws Exception {
    // arrange one choice question and a successful worker response with executionPath=rules
    service.start("job-1");
    verify(ai).standardizeImportQuestion(eq("task-1"), eq("q1"), argThat(payload ->
            Boolean.TRUE.equals(payload.get("writeResult")) && "global".equals(payload.get("requestSource"))));
    assertEquals(1, job.getTotalItems());
    assertEquals("rules", item.getExecutionPath());
}

@Test
void reviewRequiredIsNotCountedAsTechnicalFailure() throws Exception {
    when(ai.standardizeImportQuestion(any(), any(), any())).thenReturn(Map.of(
            "writeResult", false,
            "writeDecision", "review_required",
            "executionPath", "llm",
            "reviewReasons", List.of("option_image_reference_removed")
    ));
    service.start("job-1");
    assertEquals("review_required", item.getStatus());
    assertEquals("partial_review", job.getStatus());
}
```

- [ ] **Step 2: Run tests and verify RED**

```bash
cd backend && mvn -q -Dtest=StandardizationBatchServiceTest test
```

Expected: failures because request source, metadata fields, and `partial_review` do not exist.

- [ ] **Step 3: Add backward-compatible item columns**

Add idempotent migration columns:

```java
addColumnIfMissing("java_standardization_batch_items", "execution_path", "VARCHAR(40)");
addColumnIfMissing("java_standardization_batch_items", "write_decision", "VARCHAR(40)");
addColumnIfMissing("java_standardization_batch_items", "model_invoked", "BOOLEAN");
addColumnIfMissing("java_standardization_batch_items", "cache_hit", "BOOLEAN");
addColumnIfMissing("java_standardization_batch_items", "provider_call_attempts", "INT");
addColumnIfMissing("java_standardization_batch_items", "review_reasons_json", "TEXT");
```

Mirror fields and accessors on `StandardizationBatchItemEntity`.

- [ ] **Step 4: Make question count authoritative**

Set each item `totalItems=1`; set the job `totalItems=questions.size()` for compatibility. Add `requestSource=global` to the call. Interpret `writeDecision=review_required` as a successful technical execution that requires review, not an exception.

Persist execution metadata from the response. Aggregate `rulesCount`, `ocrFallbackCount`, `cacheHitCount`, `llmQuestionCount`, `reviewRequiredCount`, `providerCallAttempts`, and adaptive concurrency in `toMap` from item metadata.

- [ ] **Step 5: Make batch terminal states truthful**

Finish with `partial_review` when review items exist and no technical failures; preserve `partial_failed` for technical failure. Include review items in completed question counts.

- [ ] **Step 6: Run Java tests**

```bash
cd backend && mvn -q -Dtest=StandardizationBatchServiceTest,DomainControllerTest test
cd backend && mvn -q test
```

Expected: focused and full Java suites pass.

- [ ] **Step 7: Commit**

```bash
git add backend/src/main/java/com/aigeneration/questionbank/domain/service/StandardizationBatchService.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/entity/StandardizationBatchItemEntity.java \
  backend/src/main/java/com/aigeneration/questionbank/migration/SchemaMigrator.java \
  backend/src/test/java/com/aigeneration/questionbank/StandardizationBatchServiceTest.java
git commit -m "feat: report question-level standardization progress"
```

### Task 5: Frontend progress and execution sources

**Files:**
- Modify: `local-platform/src/lib/standardization-job.ts`
- Modify: `local-platform/src/lib/standardization-job.test.ts`
- Modify: `local-platform/src/components/question-bank/ImportWorkbenchTask.tsx:520-550,1038-1054`

- [ ] **Step 1: Write failing formatter tests**

```typescript
it("formats canonical-question progress and execution paths", () => {
  expect(formatStandardizationProgress({
    completedQuestions: 38,
    totalQuestions: 51,
    rulesCount: 12,
    ocrFallbackCount: 3,
    cacheHitCount: 8,
    llmQuestionCount: 15,
    reviewRequiredCount: 2,
    failedCount: 0,
    currentLlmConcurrency: 5,
    maximumLlmConcurrency: 8,
  })).toBe("已完成 38/51 道题 · 规则 12 · OCR 3 · 缓存 8 · AI 15 · 待复核 2 · 失败 0 · 模型并发 5/8");
});
```

- [ ] **Step 2: Run and verify RED**

```bash
cd local-platform && npm test -- --run src/lib/standardization-job.test.ts
```

Expected: assertion failure with the old “内容项” text.

- [ ] **Step 3: Implement the new progress type and formatter**

Add the fields from the API summary and remove content-item wording. Keep defaults at zero and model maximum at eight.

- [ ] **Step 4: Update the task panel**

Use question counts as the primary progress. Render source counts and `partial_review` distinctly from failure. Show retry only for failed items and a review notice for review items. Continue polling while queued/running/cancelling.

- [ ] **Step 5: Run frontend tests and build**

```bash
cd local-platform && npm test -- --run
cd local-platform && npm run build
```

Expected: all tests and the production build pass.

- [ ] **Step 6: Commit**

```bash
git add local-platform/src/lib/standardization-job.ts local-platform/src/lib/standardization-job.test.ts \
  local-platform/src/components/question-bank/ImportWorkbenchTask.tsx
git commit -m "feat: show standardization execution paths"
```

### Task 6: Configuration, contracts, and operations

**Files:**
- Modify: `.env.example`
- Modify: `docker-compose.server.yml`
- Modify: `question-engine/openapi/question-engine.v1.yaml`
- Modify: `scripts/check_question_engine_contract.py`
- Modify: `docs/delivery/ACCEPTANCE.md`
- Modify: `docs/server/RUNBOOK.md`

- [ ] **Step 1: Write the failing contract assertions**

Extend `scripts/check_question_engine_contract.py` to require global standardization responses to define `rulesCount`, `ocrFallbackCount`, `cacheHitCount`, `llmQuestionCount`, `reviewRequiredCount`, `providerCallAttempts`, `currentLlmConcurrency`, and `maximumLlmConcurrency`.

- [ ] **Step 2: Run and verify RED**

```bash
python3 scripts/check_question_engine_contract.py
```

Expected: failure because OpenAPI lacks the new fields.

- [ ] **Step 3: Update configuration defaults**

```text
STANDARDIZATION_PIPELINE_V2_ENABLED=true
STANDARDIZATION_PIPELINE_V2_SHADOW_MODE=false
STANDARDIZATION_AI_AUTO_APPLY_ENABLED=true
STANDARDIZATION_ADAPTIVE_CONCURRENCY_ENABLED=true
AI_STANDARDIZATION_MAX_CONCURRENCY=12
LLM_STANDARDIZE_INITIAL_CONCURRENCY=4
LLM_STANDARDIZE_MIN_CONCURRENCY=2
LLM_STANDARDIZE_MAX_CONCURRENCY=8
LLM_EXTERNAL_MAX_CONCURRENCY=8
```

Use the same defaults in `.env.example` and Compose. Do not expose secrets.

- [ ] **Step 4: Update OpenAPI and operator docs**

Document stable summary fields, `partial_review`, feature flags, health checks, shadow mode, auto-apply disable, fixed-concurrency fallback, and rollback order.

- [ ] **Step 5: Run contract checks**

```bash
python3 scripts/check_question_engine_contract.py
python3 scripts/check_openapi_sdk_sync.py
```

Expected: both exit zero.

- [ ] **Step 6: Commit**

```bash
git add .env.example docker-compose.server.yml question-engine/openapi/question-engine.v1.yaml \
  scripts/check_question_engine_contract.py docs/delivery/ACCEPTANCE.md docs/server/RUNBOOK.md
git commit -m "docs: configure adaptive standardization"
```

### Task 7: Full verification, server deployment, and live acceptance

**Files:**
- Verify all changed files
- Deploy to `/home/user/AI_GENERATION_DOCKER`

- [ ] **Step 1: Run full local verification in parallel**

```bash
PYTHONPATH=backend/python-worker /Users/chang/Documents/AI_GENERATION/backend/python-worker/.venv/bin/pytest -q backend/python-worker/tests
cd backend && mvn -q test
cd local-platform && npm test -- --run && npm run build
python3 scripts/check_question_engine_contract.py
python3 scripts/check_openapi_sdk_sync.py
git diff --check
```

Expected: Python, Java, frontend, build, contract checks, and diff check all succeed.

- [ ] **Step 2: Review the branch diff against the design**

Confirm each acceptance item in `docs/superpowers/specs/2026-07-13-unified-standardization-adaptive-concurrency-design.md` has implementation or an explicit compatibility path. Confirm no unrelated files changed and no secrets are tracked.

- [ ] **Step 3: Create a server backup**

Over SSH, create:

```bash
cd /home/user
sudo tar -czf AI_GENERATION_DOCKER_backup_$(date +%Y%m%d_%H%M%S).tar.gz AI_GENERATION_DOCKER
```

Record the exact backup path before replacing files.

- [ ] **Step 4: Synchronize the current branch without `.git` or secrets**

Transfer the committed worktree contents while excluding `.git`, local virtual environments, `node_modules`, build output, storage data, and local secret files. Preserve the server `.env` and storage directories.

- [ ] **Step 5: Rebuild and start the service**

```bash
cd /home/user/AI_GENERATION_DOCKER
sudo docker compose -f docker-compose.server.yml up -d --build question-engine
sudo docker compose -f docker-compose.server.yml ps
```

Expected: `question-engine` becomes `healthy`.

- [ ] **Step 6: Run public and business smoke tests**

```bash
curl -fsS http://120.211.112.121:5173/api/java/health
curl -fsSI http://120.211.112.121:5173/
curl -fsS http://120.211.112.121:5173/api/system/llm
```

Use an existing completed task if present. Run canonicalization preview only, then create a global standardization job only when the task is safe and the user data is a designated test task. Verify question-level counts, execution paths, option/image preservation, and model concurrency. Do not apply canonicalization to unrelated live data.

- [ ] **Step 7: Commit any test-discovered fixes after TDD verification**

For each discovered bug, first add a failing regression test, verify RED, implement the minimal fix, rerun focused and full tests, then commit with a scoped `fix:` message. Rebuild the server after the final fix.

- [ ] **Step 8: Final server verification**

Confirm remote source hashes match the local committed files, container state is `running healthy`, public health is HTTP 200, and the deployed branch remains unmerged from `main`.
