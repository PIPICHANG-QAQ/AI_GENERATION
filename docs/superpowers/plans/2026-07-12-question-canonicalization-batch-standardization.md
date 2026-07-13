# Question Canonicalization and Batch Standardization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge paper/answer duplicate questions and same-question layout boxes, render option images reliably, and replace browser-serial standardization with a persistent server-side batch job capped at concurrency 2.

**Architecture:** Python owns pure OCR evidence analysis, canonicalization, sub-question cleanup, and region geometry. Java owns durable task snapshots, canonicalization application, quality gates, batch-job persistence, concurrency, retries, cancellation, and recovery. React consumes Java APIs, renders a unified question visual model, and polls durable jobs instead of issuing one request per field.

**Tech Stack:** Python 3/FastAPI/pytest, Java 17/Spring Boot/MyBatis-Plus/H2/JUnit 5/Mockito, React 18/TypeScript/Vitest/React Testing Library, Docker Compose.

---

## File map

**Python worker**

- Create `backend/python-worker/app/question_canonicalization.py`: document-zone classification, duplicate scoring, merge planning, sub-question cleanup, and application.
- Modify `backend/python-worker/app/question_layout.py`: canonical region mapping and safe same-page union.
- Modify `backend/python-worker/app/import_services.py`: canonicalize before creating import questions and expose preview data.
- Modify `backend/python-worker/app/worker_routes.py`: internal canonicalization preview endpoint.
- Create `backend/python-worker/tests/test_question_canonicalization.py`: pure canonicalization regression tests.
- Modify `backend/python-worker/tests/test_question_layout.py`: same-question region union tests.
- Modify `backend/python-worker/tests/test_import_services.py`: import integration and option-image preservation tests.

**Java backend**

- Create `backend/src/main/java/com/aigeneration/questionbank/domain/entity/ImportTaskSnapshotEntity.java`: pre-apply rollback snapshot.
- Create `backend/src/main/java/com/aigeneration/questionbank/domain/entity/StandardizationBatchJobEntity.java`: durable batch summary.
- Create `backend/src/main/java/com/aigeneration/questionbank/domain/entity/StandardizationBatchItemEntity.java`: durable per-question work item.
- Create matching mapper interfaces under `backend/src/main/java/com/aigeneration/questionbank/domain/mapper/`.
- Create `backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportTaskCanonicalizationService.java`: preview, apply, rollback, and quality gate.
- Create `backend/src/main/java/com/aigeneration/questionbank/domain/service/StandardizationBatchService.java`: bounded scheduling, retry, cancellation, resumption, and recovery.
- Create `backend/src/main/java/com/aigeneration/questionbank/domain/controller/ImportTaskCanonicalizationController.java`: canonicalization API.
- Create `backend/src/main/java/com/aigeneration/questionbank/domain/controller/StandardizationBatchController.java`: batch-job API.
- Modify `backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportQuestionSyncService.java`: atomically synchronize Markdown, structured options, images, placements, and AI sub-questions.
- Modify `backend/src/main/resources/schema.sql` and `backend/src/main/java/com/aigeneration/questionbank/migration/SchemaMigrator.java`: add snapshot and batch tables.
- Create `backend/src/test/java/com/aigeneration/questionbank/ImportTaskCanonicalizationServiceTest.java`.
- Create `backend/src/test/java/com/aigeneration/questionbank/StandardizationBatchServiceTest.java`.
- Modify `backend/src/test/java/com/aigeneration/questionbank/DomainControllerTest.java`: endpoint integration coverage.

**Frontend**

- Create `local-platform/src/lib/question-visual-model.ts`: deterministic stem/option/image/placement view model.
- Create `local-platform/src/lib/question-visual-model.test.ts`.
- Modify `local-platform/src/components/ui/MarkdownRenderer.tsx`: use the visual model and visible image failure fallback.
- Modify `local-platform/src/components/question-bank/QuestionPreview.tsx`: render canonical option images and conflicts.
- Modify `local-platform/src/components/question-bank/ImportWorkbenchTask.tsx`: canonicalization preview/apply UI, gate, and batch-job polling/cancel/resume.
- Modify `local-platform/src/lib/api.ts`: canonicalization and standardization job APIs.
- Modify `local-platform/src/lib/question.test.ts`: save/preview round-trip coverage.

**Contracts and delivery**

- Modify `contracts/openapi/question-engine.openapi.yaml` and generated SDK artifacts required by the repository contract check.
- Modify `docs/delivery/OPERATIONS_GUIDE.md`: concurrency settings, rollout, smoke checks, and rollback.
- Modify `.env.example` or the repository's deployment environment template with `LLM_STANDARDIZE_MAX_CONCURRENCY=2` and `LLM_EXTERNAL_MAX_CONCURRENCY=2`.

---

### Task 1: Pure document-zone and duplicate-question canonicalization

**Files:**
- Create: `backend/python-worker/app/question_canonicalization.py`
- Create: `backend/python-worker/tests/test_question_canonicalization.py`

- [ ] **Step 1: Write failing zone and duplicate matching tests**

```python
from app.question_canonicalization import build_canonicalization_plan


def test_answer_zone_duplicate_merges_into_paper_question():
    markdown = "1. 杠杆题\nA.食品夹 B.船桨\n参考答案与试题解析\n1. 杠杆题\n【解答】修枝剪刀省力"
    questions = [
        {"id": "q_1", "number": 1, "stemMarkdown": "1. 杠杆题", "options": [{"label": "A", "content": "食品夹"}]},
        {"id": "q_1_2", "number": 1, "stemMarkdown": "1. 杠杆题", "analysis": "修枝剪刀省力"},
    ]

    plan = build_canonicalization_plan(markdown, questions)

    assert plan["idMap"] == {"q_1": "q_1", "q_1_2": "q_1"}
    assert plan["automaticMerges"][0]["duplicateId"] == "q_1_2"
    assert plan["blockingIssues"] == []


def test_same_number_without_answer_heading_is_not_merged():
    markdown = "一、选择题\n1. 第一题\n二、附加题\n1. 另一道题"
    questions = [
        {"id": "q_1", "number": 1, "stemMarkdown": "第一题"},
        {"id": "q_1_2", "number": 1, "stemMarkdown": "另一道题"},
    ]

    plan = build_canonicalization_plan(markdown, questions)

    assert plan["automaticMerges"] == []
    assert plan["idMap"]["q_1_2"] == "q_1_2"
```

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run: `python3 -m pytest backend/python-worker/tests/test_question_canonicalization.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'app.question_canonicalization'`.

- [ ] **Step 3: Implement zone classification and scored planning**

Create these public functions and keep the output JSON-serializable:

```python
ANSWER_HEADING_RE = re.compile(r"(?im)^\s*#{0,6}\s*(参考答案与试题解析|参考答案|答案与解析|试题答案|详解)\s*$")


def build_canonicalization_plan(markdown: str, questions: list[dict[str, Any]]) -> dict[str, Any]:
    answer_start = answer_zone_start(markdown)
    id_map = {str(q.get("id") or ""): str(q.get("id") or "") for q in questions}
    paper = [q for q in questions if evidence_start(q) < answer_start]
    answers = [q for q in questions if evidence_start(q) >= answer_start]
    merges: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    for duplicate in answers:
        ranked = sorted(
            ((match_score(candidate, duplicate), candidate) for candidate in paper),
            key=lambda item: item[0],
            reverse=True,
        )
        best_score, best = ranked[0] if ranked else (0.0, None)
        runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
        if best and best_score >= 0.85 and best_score - runner_up >= 0.08:
            canonical_id = str(best["id"])
            id_map[str(duplicate["id"])] = canonical_id
            merges.append(merge_evidence(best, duplicate, best_score))
        elif best_score >= 0.65:
            reviews.append(review_evidence(best, duplicate, best_score, runner_up))
    return {
        "version": "question-canonicalization.v1",
        "idMap": id_map,
        "automaticMerges": merges,
        "reviewItems": reviews,
        "blockingIssues": ["ambiguous-duplicate-question"] if reviews else [],
    }
```

Use these helper contracts; `option_image_similarity` and `type_section_similarity` return a normalized value from 0.0 to 1.0:

```python
def answer_zone_start(markdown: str) -> int:
    match = ANSWER_HEADING_RE.search(str(markdown or ""))
    return match.start() if match else len(str(markdown or "")) + 1


def evidence_start(question: dict[str, Any]) -> int:
    evidence = question.get("sourceEvidence") if isinstance(question.get("sourceEvidence"), dict) else {}
    return int(evidence.get("start") or 0)


def stem_core(question: dict[str, Any]) -> str:
    value = str(question.get("stemMarkdown") or question.get("manualMarkdown") or "")
    value = re.sub(r"\\begin\{tasks\}[\s\S]*?\\end\{tasks\}", "", value)
    value = re.sub(r"^\s*\d+\s*[.．、]\s*", "", value)
    return re.sub(r"\s+", "", value).strip("。．")


def match_score(paper: dict[str, Any], answer: dict[str, Any]) -> float:
    number_score = 0.45 if int(paper.get("number") or 0) == int(answer.get("number") or 0) else 0.0
    stem_score = 0.35 * SequenceMatcher(None, stem_core(paper), stem_core(answer)).ratio()
    visual_score = 0.10 * option_image_similarity(paper, answer)
    section_score = 0.10 * type_section_similarity(paper, answer)
    return round(number_score + stem_score + visual_score + section_score, 6)
```

- [ ] **Step 4: Run focused tests**

Run: `python3 -m pytest backend/python-worker/tests/test_question_canonicalization.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/python-worker/app/question_canonicalization.py backend/python-worker/tests/test_question_canonicalization.py
git commit -m "feat: plan canonical question merges"
```

### Task 2: Apply field merges and clean repeated answer-section sub-questions

**Files:**
- Modify: `backend/python-worker/app/question_canonicalization.py`
- Modify: `backend/python-worker/tests/test_question_canonicalization.py`

- [ ] **Step 1: Add failing merge and sub-question tests**

```python
from app.question_canonicalization import apply_canonicalization


def test_apply_keeps_paper_visuals_and_adds_answer_analysis():
    questions = [
        {"id": "q_2", "number": 2, "stemMarkdown": "杠杆题", "images": [{"imageId": "paper-a"}], "analysis": ""},
        {"id": "q_2_2", "number": 2, "stemMarkdown": "杠杆题", "images": [{"imageId": "answer-a"}], "analysis": "修枝剪刀是省力杠杆"},
    ]
    plan = {"idMap": {"q_2": "q_2", "q_2_2": "q_2"}, "automaticMerges": [{"canonicalId": "q_2", "duplicateId": "q_2_2", "score": 1.0}]}

    result = apply_canonicalization(questions, plan)

    assert len(result["questions"]) == 1
    assert result["questions"][0]["images"] == [{"imageId": "paper-a"}]
    assert result["questions"][0]["analysis"] == "修枝剪刀是省力杠杆"
    assert result["questions"][0]["mergedFromQuestionIds"] == ["q_2_2"]


def test_repeated_solution_labels_do_not_create_extra_subquestions():
    question = {
        "id": "q_30",
        "subQuestions": [
            {"label": "(1)", "stemMarkdown": "题干一"},
            {"label": "(2)", "stemMarkdown": "题干二"},
            {"label": "(1)", "stemMarkdown": "分析重复一"},
            {"label": "(2)", "stemMarkdown": "答案重复二"},
        ],
    }

    result = apply_canonicalization([question], {"idMap": {"q_30": "q_30"}, "automaticMerges": []})

    assert [sub["label"] for sub in result["questions"][0]["subQuestions"]] == ["(1)", "(2)"]
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `python3 -m pytest backend/python-worker/tests/test_question_canonicalization.py -q`

Expected: failures because `apply_canonicalization` is missing.

- [ ] **Step 3: Implement deterministic application**

Add:

```python
def apply_canonicalization(questions: list[dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any]:
    by_id = {str(q.get("id") or ""): copy.deepcopy(q) for q in questions}
    merge_by_duplicate = {str(item["duplicateId"]): item for item in plan.get("automaticMerges") or []}
    for duplicate_id, evidence in merge_by_duplicate.items():
        canonical_id = str(evidence["canonicalId"])
        canonical = by_id[canonical_id]
        duplicate = by_id[duplicate_id]
        merge_answer_fields(canonical, duplicate)
        canonical.setdefault("mergedFromQuestionIds", []).append(duplicate_id)
        by_id.pop(duplicate_id, None)
    output = []
    for original in questions:
        qid = str(original.get("id") or "")
        if qid not in by_id:
            continue
        question = by_id.pop(qid)
        cleaned, issues = clean_subquestions(question.get("subQuestions") or question.get("children") or [])
        question["subQuestions"] = cleaned
        question["children"] = cleaned
        if issues:
            question.setdefault("canonicalizationIssues", []).extend(issues)
        output.append(question)
    return {"questions": output, "plan": plan}
```

`merge_answer_fields` must preserve paper stem/options/images/placements, fill empty answer/analysis from the duplicate, merge sub-questions by normalized label, and append conflict records instead of overwriting unequal non-empty answers. `clean_subquestions` must keep the first monotonic label sequence and report repeated/regressing labels.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest backend/python-worker/tests/test_question_canonicalization.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/python-worker/app/question_canonicalization.py backend/python-worker/tests/test_question_canonicalization.py
git commit -m "feat: apply canonical question merges"
```

### Task 3: Merge canonical layout regions safely

**Files:**
- Modify: `backend/python-worker/app/question_layout.py`
- Modify: `backend/python-worker/tests/test_question_layout.py`

- [ ] **Step 1: Add failing geometry tests**

```python
from app.question_layout import merge_canonical_regions


def test_overlapping_regions_for_same_canonical_question_are_unioned():
    regions = [
        {"questionId": "q_2", "index": 2, "pageIndex": 0, "x": 0.14, "y": 0.27, "w": 0.59, "h": 0.13, "confidence": 0.96},
        {"questionId": "q_2_2", "index": 2, "pageIndex": 0, "x": 0.16, "y": 0.38, "w": 0.69, "h": 0.15, "confidence": 0.96},
    ]

    merged = merge_canonical_regions(regions, {"q_2": "q_2", "q_2_2": "q_2"})

    assert len(merged) == 1
    assert merged[0]["questionId"] == "q_2"
    assert merged[0]["x"] == 0.14
    assert merged[0]["y"] == 0.27
    assert round(merged[0]["w"], 2) == 0.71
    assert round(merged[0]["h"], 2) == 0.26


def test_cross_page_regions_remain_separate():
    regions = [
        {"questionId": "q_7", "index": 7, "pageIndex": 0, "x": 0.1, "y": 0.8, "w": 0.8, "h": 0.15},
        {"questionId": "q_7", "index": 7, "pageIndex": 1, "x": 0.1, "y": 0.0, "w": 0.8, "h": 0.2},
    ]
    assert len(merge_canonical_regions(regions, {"q_7": "q_7"})) == 2
```

- [ ] **Step 2: Confirm failure**

Run: `python3 -m pytest backend/python-worker/tests/test_question_layout.py -q`

Expected: import failure for `merge_canonical_regions`.

- [ ] **Step 3: Implement canonical grouping and union**

Add `merge_canonical_regions(regions, id_map, anchor_regions=None)` that maps IDs first, groups by `(canonicalQuestionId, pageIndex)`, sorts by `y`, and unions only when rectangles overlap or vertical gap is at most `0.02` and horizontal overlap divided by the narrower width is at least `0.25`. Keep cross-page regions separate and record `mergedFromRegions`.

Call it at the end of `_build_paper_layout` using `task.get("canonicalization", {}).get("idMap", {})`.

- [ ] **Step 4: Run layout tests**

Run: `python3 -m pytest backend/python-worker/tests/test_question_layout.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/python-worker/app/question_layout.py backend/python-worker/tests/test_question_layout.py
git commit -m "feat: merge canonical layout regions"
```

### Task 4: Integrate canonicalization into import and expose worker preview

**Files:**
- Modify: `backend/python-worker/app/import_services.py`
- Modify: `backend/python-worker/app/worker_routes.py`
- Modify: `backend/python-worker/tests/test_import_services.py`
- Modify: `backend/python-worker/tests/test_question_canonicalization.py`

- [ ] **Step 1: Add failing import and endpoint tests**

Use this exact paper/answer fixture and assertion:

```python
task = {"id": "task-1", "paperOcrJobId": "ocr-1"}
outputs = {
    "markdown": "1. 第一题\n参考答案与试题解析\n1. 第一题\n【解答】解析",
    "questions": [
        {"id": "q_1", "number": 1, "stemMarkdown": "第一题", "sourceEvidence": {"start": 0, "end": 5}},
        {"id": "q_1_2", "number": 1, "stemMarkdown": "第一题", "analysis": "解析", "sourceEvidence": {"start": 16, "end": 30}},
    ],
}
result = canonicalize_import_outputs(task, outputs)
assert result["summary"]["beforeQuestionCount"] == 2
assert result["summary"]["afterQuestionCount"] == 1
assert result["questions"][0]["analysis"] == "解析"
assert result["blockingIssues"] == []
```

Add this FastAPI route assertion with `safe_read_job` patched to return the fixture outputs:

```python
with patch("app.worker_routes.safe_read_job", return_value={"outputs": outputs}):
    response = client.post("/worker/import-tasks/canonicalization/preview", json={"task": task})
assert response.status_code == 200
body = response.json()
assert body["applyToken"]
assert body["summary"] == {"beforeQuestionCount": 2, "afterQuestionCount": 1, "mergedQuestionCount": 1}
assert len(body["questions"]) == 1
assert read_store() == store_before
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `python3 -m pytest backend/python-worker/tests/test_import_services.py backend/python-worker/tests/test_question_canonicalization.py -q`

Expected: missing `canonicalize_import_outputs` and route failures.

- [ ] **Step 3: Implement import adapter and preview route**

Add `canonicalize_import_outputs(task, outputs)` in `import_services.py`. It must call `build_canonicalization_plan`, `apply_canonicalization`, rebuild import-question maps with stable IDs, attach `canonicalization` metadata, and compute an SHA-256 `applyToken` over task ID, OCR job ID, and the canonicalized question payload.

Add this route in `worker_routes.py`:

```python
@app.post("/worker/import-tasks/canonicalization/preview")
def preview_import_task_canonicalization(payload: dict[str, Any]) -> dict[str, Any]:
    task = dict(payload.get("task") or payload)
    job = safe_read_job(task.get("paperOcrJobId"))
    if not job:
        raise HTTPException(status_code=404, detail="Paper OCR job not found")
    outputs = job.get("outputs") if isinstance(job.get("outputs"), dict) else {}
    return canonicalize_import_outputs(task, outputs)
```

During new OCR import, run canonicalization before `build_import_questions` persists duplicate parents. If the plan has blocking review items, preserve candidates and set `canonicalization.requiresReview=true` rather than deleting them.

- [ ] **Step 4: Run Python regression suite**

Run: `python3 -m pytest backend/python-worker/tests -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/python-worker/app/import_services.py backend/python-worker/app/worker_routes.py backend/python-worker/tests
git commit -m "feat: canonicalize import OCR output"
```

### Task 5: Persist canonicalization snapshots and apply/rollback in Java

**Files:**
- Create: `backend/src/main/java/com/aigeneration/questionbank/domain/entity/ImportTaskSnapshotEntity.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/domain/mapper/ImportTaskSnapshotMapper.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportTaskCanonicalizationService.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/domain/controller/ImportTaskCanonicalizationController.java`
- Modify: `backend/src/main/resources/schema.sql`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/migration/SchemaMigrator.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ImportTaskCanonicalizationServiceTest.java`
- Modify: `backend/src/test/java/com/aigeneration/questionbank/DomainControllerTest.java`

- [ ] **Step 1: Add failing service tests**

Create four named tests: `previewDoesNotWrite`, `applyRejectsStalePreviewToken`, `applySnapshotsBeforeSync`, and `rollbackRestoresLatestSnapshot`. The stale-token assertion is:

```java
@Test
void applyRejectsStalePreviewToken() {
    when(worker.postJson(anyString(), any())).thenReturn(Map.of("applyToken", "fresh", "questions", List.of()));
    assertThrows(ResponseStatusException.class, () -> service.apply("task-1", Map.of("applyToken", "stale")));
    verifyNoInteractions(snapshotMapper);
}
```

- [ ] **Step 2: Run the focused Java test and confirm failure**

Run: `mvn -q -f backend/pom.xml -Dtest=ImportTaskCanonicalizationServiceTest test`

Expected: compilation fails because the service and entity do not exist.

- [ ] **Step 3: Add snapshot schema, entity, mapper, service, and controller**

Add table `java_import_task_snapshots(id, task_id, snapshot_type, version, snapshot_json, created_at)` to both schema paths.

Implement controller endpoints:

```java
@PostMapping("/api/import-tasks/{taskId}/canonicalization/preview")
public Map<String, Object> preview(@PathVariable String taskId) {
    return service.preview(taskId);
}

@PostMapping("/api/import-tasks/{taskId}/canonicalization/apply")
public Map<String, Object> apply(@PathVariable String taskId, @RequestBody Map<String, Object> payload) {
    return service.apply(taskId, payload);
}

@PostMapping("/api/import-tasks/{taskId}/canonicalization/rollback")
public Map<String, Object> rollback(@PathVariable String taskId) {
    return service.rollbackLatest(taskId);
}
```

`apply` must fetch a fresh worker preview, compare the token with the submitted token, persist the current Java task snapshot, call `ImportQuestionSyncService.syncQuestions`, update task `raw_json` with canonicalization and paperLayout, and update `question_count` in one transaction. `rollbackLatest` restores task JSON and questions from the latest snapshot.

- [ ] **Step 4: Add MockMvc endpoint coverage and run tests**

Run: `mvn -q -f backend/pom.xml -Dtest=ImportTaskCanonicalizationServiceTest,DomainControllerTest test`

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/main backend/src/test
git commit -m "feat: apply and rollback question canonicalization"
```

### Task 6: Build the unified visual model and restore option images

**Files:**
- Create: `local-platform/src/lib/question-visual-model.ts`
- Create: `local-platform/src/lib/question-visual-model.test.ts`
- Modify: `local-platform/src/components/ui/MarkdownRenderer.tsx`
- Modify: `local-platform/src/components/question-bank/QuestionPreview.tsx`
- Modify: `local-platform/src/lib/question.ts`
- Modify: `local-platform/src/lib/question.test.ts`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportQuestionSyncService.java`
- Modify: `backend/src/test/java/com/aigeneration/questionbank/DomainControllerTest.java`

- [ ] **Step 1: Add failing visual-model tests**

```typescript
import { buildQuestionVisualModel } from "./question-visual-model";

it("prefers structured option images over text-only tasks", () => {
  const model = buildQuestionVisualModel({
    type: "choice",
    manualMarkdown: "题干\\n\\begin{tasks}(2)\\n\\task 食品夹\\n\\task 船桨\\n\\end{tasks}",
    images: [
      { imageId: "a", label: "图1", url: "/api/a.jpg" },
      { imageId: "b", label: "图2", url: "/api/b.jpg" },
    ],
    options: [
      { label: "A", contentMarkdown: "![](图1) 食品夹" },
      { label: "B", contentMarkdown: "![](图2) 船桨" },
    ],
  });
  expect(model.options.map((option) => option.contentMarkdown)).toEqual([
    "![](图1) 食品夹",
    "![](图2) 船桨",
  ]);
  expect(model.issues).toEqual([]);
});
```

Add these concrete assertions:

```typescript
it("falls back to markdown tasks when structured options are absent", () => {
  const model = buildQuestionVisualModel({ type: "choice", manualMarkdown: "题干\\n\\begin{tasks}(2)\\n\\task A1\\n\\task B1\\n\\end{tasks}" });
  expect(model.options.map((item) => item.content)).toEqual(["A1", "B1"]);
});

it.each(["图1", "images/a.jpg", "/api/a.jpg"])("resolves %s", (ref) => {
  expect(resolveVisualImage(ref, [{ imageId: "a", label: "图1", path: "root/images/a.jpg", url: "/api/a.jpg" }])).toBe("/api/a.jpg");
});

it("reports placement conflicts without hiding the option image", () => {
  const model = buildQuestionVisualModel({
    type: "choice",
    images: [{ imageId: "a", label: "图1", url: "/api/a.jpg" }],
    options: [{ label: "A", contentMarkdown: "![](图1) A1" }],
    imagePlacements: [{ imageId: "a", target: { kind: "option", optionLabel: "B" } }],
  });
  expect(model.options[0].contentMarkdown).toContain("![](图1)");
  expect(model.issues[0].code).toBe("placement-conflict");
});
```

- [ ] **Step 2: Confirm frontend failure**

Run: `npm --prefix local-platform test -- --run src/lib/question-visual-model.test.ts`

Expected: module-not-found failure.

- [ ] **Step 3: Implement the visual model and renderer integration**

Export:

```typescript
export type QuestionVisualModel = {
  stemMarkdown: string;
  options: QuestionOption[];
  images: QuestionImage[];
  issues: Array<{ code: string; message: string; imageId?: string }>;
};

export function buildQuestionVisualModel(question: any): QuestionVisualModel {
  const images = ensureQuestionImageLabels(getQuestionImages(question));
  const parsed = getQuestionMarkdownParts(
    question.manualMarkdown || question.stemMarkdown || "",
    question.type || "",
    [],
    images,
  );
  const structured = normalizeQuestionOptions(question.options, images);
  const options = structured.length > 0 ? mergeOptionImageRefs(structured, parsed.options, images) : parsed.options;
  return {
    stemMarkdown: parsed.stemMarkdown,
    options,
    images,
    issues: visualPlacementIssues(options, images, question.imagePlacements || []),
  };
}
```

`MarkdownRenderer` must accept the visual-model options without reparsing text-only tasks over them. Replace the image `onError` behavior that sets `display:none` with React state that renders `图片加载失败: <label/filename>` visibly. `QuestionPreview` must display visual issues below the corresponding option grid.

- [ ] **Step 4: Make Java standardized-result saving atomic across visual fields**

In `ImportQuestionSyncService.updateStandardizedResult`, parse `aiResponse.options` when present; otherwise derive options from the standardized Markdown using existing normalized response fields. Update `manual_markdown`, `options_json`, `images_json`, and `image_placements_json` in the same entity update. Preserve current structured options when the AI response contains no richer option structure.

Add a Java test that starts with option image refs, applies a text standardization response, and verifies `options_json` still contains all refs.

- [ ] **Step 5: Run frontend and Java focused tests**

Run:

```bash
npm --prefix local-platform test -- --run src/lib/question-visual-model.test.ts src/lib/question.test.ts
mvn -q -f backend/pom.xml -Dtest=DomainControllerTest test
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```bash
git add local-platform/src backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportQuestionSyncService.java backend/src/test/java/com/aigeneration/questionbank/DomainControllerTest.java
git commit -m "fix: render and preserve option images"
```

### Task 7: Persist standardization batch jobs and expose lifecycle APIs

**Files:**
- Create: `backend/src/main/java/com/aigeneration/questionbank/domain/entity/StandardizationBatchJobEntity.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/domain/entity/StandardizationBatchItemEntity.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/domain/mapper/StandardizationBatchJobMapper.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/domain/mapper/StandardizationBatchItemMapper.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/domain/service/StandardizationBatchService.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/domain/controller/StandardizationBatchController.java`
- Modify: `backend/src/main/resources/schema.sql`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/migration/SchemaMigrator.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/StandardizationBatchServiceTest.java`

- [ ] **Step 1: Add failing job creation and exclusivity tests**

```java
@Test
void createBuildsOneItemPerCanonicalQuestionAndRejectsSecondActiveJob() {
    when(questionService.listByTask("task-1")).thenReturn(List.of(question("q1"), question("q2")));
    Map<String, Object> created = service.create("task-1");
    assertEquals(2, created.get("totalQuestions"));
    assertThrows(ResponseStatusException.class, () -> service.create("task-1"));
}
```

- [ ] **Step 2: Confirm failure**

Run: `mvn -q -f backend/pom.xml -Dtest=StandardizationBatchServiceTest test`

Expected: compilation failure for missing batch classes.

- [ ] **Step 3: Add schema/entities/mappers and lifecycle service**

Create `java_standardization_batch_jobs` with `id`, `task_id`, `status`, total/completed/success/failed counts, `max_concurrency`, cancellation timestamp, and lifecycle timestamps. Create `java_standardization_batch_items` with `id`, `job_id`, `question_id`, `status`, `input_hash`, attempts/counts, error, and lifecycle timestamps. The public service surface is:

```java
public Map<String, Object> create(String taskId);
public Map<String, Object> get(String taskId, String jobId);
public Map<String, Object> cancel(String taskId, String jobId);
public Map<String, Object> resume(String taskId, String jobId);
public Map<String, Object> retryFailed(String taskId, String jobId);
```

`create` calls `ImportTaskCanonicalizationService.requireReadyForStandardization(taskId)` and returns HTTP 409 for any blocking issue.

Expose:

```java
@PostMapping("/api/import-tasks/{taskId}/standardization-jobs")
@GetMapping("/api/import-tasks/{taskId}/standardization-jobs/{jobId}")
@PostMapping("/api/import-tasks/{taskId}/standardization-jobs/{jobId}/cancel")
@PostMapping("/api/import-tasks/{taskId}/standardization-jobs/{jobId}/resume")
@PostMapping("/api/import-tasks/{taskId}/standardization-jobs/{jobId}/retry-failed")
```

- [ ] **Step 4: Run focused tests**

Run: `mvn -q -f backend/pom.xml -Dtest=StandardizationBatchServiceTest test`

Expected: job creation, exclusivity, cancel, resume, and failed-item reset tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/main backend/src/test/java/com/aigeneration/questionbank/StandardizationBatchServiceTest.java
git commit -m "feat: persist standardization batch jobs"
```

### Task 8: Execute batch items with bounded concurrency, checkpointing, retry, and recovery

**Files:**
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/StandardizationBatchService.java`
- Modify: `backend/src/test/java/com/aigeneration/questionbank/StandardizationBatchServiceTest.java`
- Modify: `backend/src/main/resources/application.yml`
- Modify: deployment environment template

- [ ] **Step 1: Add failing concurrency and recovery tests**

Use latches and atomics around a mocked standardizer:

```java
AtomicInteger active = new AtomicInteger();
AtomicInteger peak = new AtomicInteger();
when(ai.standardizeImportQuestion(anyString(), anyString(), anyMap())).thenAnswer(invocation -> {
    int now = active.incrementAndGet();
    peak.accumulateAndGet(now, Math::max);
    release.await(2, TimeUnit.SECONDS);
    active.decrementAndGet();
    return Map.of("writeResult", true);
});
service.start(jobId);
assertTrue(started.await(2, TimeUnit.SECONDS));
assertEquals(2, peak.get());
```

Add the named tests `questionIsSavedOnce`, `retryableFailureStopsAfterThreeTotalAttempts`, `cancelStopsClaimingNewItems`, `successfulInputHashIsReused`, and `startupRecoveryRequeuesRunningItems`. Each test must query the item mapper after execution and assert the persisted status/attempt count, not only mock invocation counts.

- [ ] **Step 2: Confirm the tests fail**

Run: `mvn -q -f backend/pom.xml -Dtest=StandardizationBatchServiceTest test`

Expected: concurrency/recovery assertions fail.

- [ ] **Step 3: Implement the bounded executor and item processor**

Use a Spring-managed `ThreadPoolTaskExecutor` with core/max pool size 2 and queue capacity 100. For each claimed question, call `AiFlowOrchestrationService.standardizeImportQuestion(taskId, questionId, Map.of("markdown", markdown, "write", true))` once with the complete editable Markdown. Do not submit individual answer/analysis fields concurrently. Persist item status after every transition and recalculate job totals transactionally.

Retry only timeouts, 429, and 5xx responses with 2-second and 5-second delays. Hash canonical question ID, editable Markdown, answer, analysis, sub-questions, and standardizer version. Reuse an earlier successful item with the same hash. On `ApplicationReadyEvent`, change stale `running` items to `queued` and restart non-cancelled jobs.

- [ ] **Step 4: Configure both task and endpoint limits to 2**

Add deployment defaults:

```dotenv
LLM_STANDARDIZE_MAX_CONCURRENCY=2
LLM_EXTERNAL_MAX_CONCURRENCY=2
```

Keep Java executor concurrency configurable as `AI_STANDARDIZATION_MAX_CONCURRENCY` with default and maximum 2 for this release.

- [ ] **Step 5: Run Java tests**

Run: `mvn -q -f backend/pom.xml test`

Expected: all Java tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/src backend/.env.example .env.example deploy 2>/dev/null || true
git commit -m "feat: run standardization batches concurrently"
```

### Task 9: Replace browser loop with canonicalization and durable batch UI

**Files:**
- Modify: `local-platform/src/lib/api.ts`
- Modify: `local-platform/src/components/question-bank/ImportWorkbenchTask.tsx`
- Create: `local-platform/src/components/question-bank/ImportWorkbenchTask.test.tsx`

- [ ] **Step 1: Add failing UI tests**

Mock APIs and assert that a blocked task shows “整理题目结构”, preview shows `72 -> 36`, applying refreshes the task, starting standardization makes exactly one create-job request, progress renders question/item counts and concurrency, and cancel/resume use job endpoints. Assert no per-unit `standardizeAi` calls occur.

```typescript
expect(screen.getByText("已完成 12/36 道题 · 38/95 个内容项 · 并发 2")).toBeInTheDocument();
expect(api.standardizeAi).not.toHaveBeenCalled();
```

- [ ] **Step 2: Confirm failure**

Run: `npm --prefix local-platform test -- --run src/components/question-bank/ImportWorkbenchTask.test.tsx`

Expected: missing API/component behavior failures.

- [ ] **Step 3: Add API methods**

Add `previewCanonicalization`, `applyCanonicalization`, `rollbackCanonicalization`, `createStandardizationJob`, `getStandardizationJob`, `cancelStandardizationJob`, `resumeStandardizationJob`, and `retryFailedStandardizationJob` to `api.ts` with the approved paths.

- [ ] **Step 4: Implement canonicalization dialog and durable polling**

Delete the browser `for (const unit of units)` standardization loop. Before creating a job, check task canonicalization blocking issues. Poll an active job every 1.5 seconds while queued/running/cancelling and stop polling at terminal states. Keep the terminal summary visible. Add buttons for cancel, resume, retry failed, preview apply, and rollback.

- [ ] **Step 5: Run frontend tests and build**

Run:

```bash
npm --prefix local-platform test -- --run
npm --prefix local-platform run build
```

Expected: all Vitest tests pass and Vite build exits 0.

- [ ] **Step 6: Commit**

```bash
git add local-platform/src
git commit -m "feat: manage canonicalization and standardization jobs"
```

### Task 10: Update contracts, run full regression, and deploy the branch build

**Files:**
- Modify: `contracts/openapi/question-engine.openapi.yaml`
- Modify: generated SDK artifacts required by `scripts/check_question_engine_contract.py`
- Modify: `docs/delivery/OPERATIONS_GUIDE.md`
- Modify: `scripts/smoke_deploy_basic.py` if new health assertions belong there

- [ ] **Step 1: Add contract paths and schemas**

Add the eight approved API paths, `CanonicalizationPreview`, `CanonicalizationApplyRequest`, `StandardizationBatchJob`, `StandardizationBatchItem`, and their status enums to OpenAPI. Include stale-token and active-job `409` responses. Run `python3 scripts/generate_question_engine_sdk.py` if present; otherwise run the generator command documented beside the existing generated SDK and verify with `python3 scripts/check_question_engine_contract.py`.

- [ ] **Step 2: Run contract and full local verification**

Run:

```bash
python3 -m pytest backend/python-worker/tests -q
mvn -q -f backend/pom.xml test
npm --prefix local-platform test -- --run
npm --prefix local-platform run build
python3 scripts/check_question_engine_contract.py
```

Expected: all Python, Java, frontend, build, and contract checks pass with exit code 0.

- [ ] **Step 3: Run the real OCR fixture read-only**

Run canonicalization preview against the saved `ocr_20260712_143523_7458eae4` result and assert:

- `q_2_2` maps to `q_2`.
- the page-0 index-2 regions become one region.
- option A-D image URLs resolve successfully.
- preview renders four option images in the frontend component test fixture.
- standardization plan contains canonical questions only.

Do not apply the preview to server data during this verification step.

- [ ] **Step 4: Commit contracts and operations documentation**

```bash
git add contracts docs scripts generated-sdk 2>/dev/null || true
git commit -m "docs: publish canonicalization and batch job contracts"
```

- [ ] **Step 5: Package and back up the server**

Use `scripts/package_delivery.sh` from the feature worktree. Upload the artifact to `$REMOTE_HOME`, create a timestamped backup of `$DEPLOY_DIR` excluding `.env`, `server-data`, the MinerU venv, build outputs, and node_modules, and preserve `$DEPLOY_DIR/server-data` unchanged.

- [ ] **Step 6: Build and deploy without merging main**

On the server run:

```bash
mvn -q -f backend/pom.xml -DskipTests package
npm --prefix local-platform ci
npm --prefix local-platform run build
python3 scripts/check_question_engine_contract.py
sudo docker compose -f docker-compose.server.yml up -d --build question-engine
```

Expected: image build succeeds and `ai_generation_docker-question-engine-1` becomes healthy.

- [ ] **Step 7: Run public smoke and guarded current-task preview**

Run:

```bash
AI_GENERATION_BASE_URL=http://120.211.112.121:8018 \
AI_GENERATION_FRONTEND_URL=http://120.211.112.121:5173 \
PYTHON_WORKER_URL=http://120.211.112.121:8018 \
python3 scripts/smoke_deploy_basic.py
```

Then request canonicalization preview for `import_task_20260712_143523_4587b484`. Verify summary, four option images, and one merged index-2 region. Do not apply server data automatically; present the preview summary for explicit data-mutation confirmation.

- [ ] **Step 8: Final branch verification**

Run:

```bash
git status --short
git merge-base --is-ancestor codex/image-placement-upgrade main && exit 1 || true
```

Expected: clean worktree and `codex/image-placement-upgrade` remains unmerged to `main`.
