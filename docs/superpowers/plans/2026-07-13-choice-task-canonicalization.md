# Choice Task Canonicalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure every image choice is serialized as one atomic `\\task <image> <text>` entry and allow structural canonicalization to apply while unrelated image-placement review items remain visible.

**Architecture:** Treat high-confidence or manually confirmed `imagePlacements` as the authoritative mapping between image assets and option labels, then reconcile option Markdown before building the canonical import preview. Keep all placement issues in `blockingIssues` for global-standardization safety, but expose `applyBlockingIssues` containing only structural canonicalization conflicts so the guarded apply endpoint can distinguish the two workflows. Add a client-side serializer guard so stale stored questions still display and save one atomic task per option.

**Tech Stack:** Python 3 / pytest-unittest worker, Java 17 / Spring Boot / JUnit-Mockito backend, TypeScript / React / Vitest frontend.

---

### Task 1: Reconcile trusted option image placements in the worker

**Files:**
- Modify: `backend/python-worker/app/question_markdown.py`
- Modify: `backend/python-worker/app/import_services.py`
- Test: `backend/python-worker/tests/test_import_services.py`

- [ ] **Step 1: Write the failing option-reconciliation test**

Add a test that supplies four options with image references incorrectly stored as A=`图1`, B=`图2+图3`, C=`图4`, D=no image, plus trusted A/B/C/D placements. Assert canonical preview options become exactly `![](图1) 食品夹`, `![](图2) 船桨`, `![](图3) 修枝剪刀`, and `![](图4) 托盘天平`.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
cd backend/python-worker
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_import_services.py -k trusted_option_image_placements
```

Expected: failure showing `图3` remains in B or `图4` remains in C.

- [ ] **Step 3: Implement the minimal reconciler**

Add a worker helper that:

```python
def reconcile_choice_option_image_refs(question: dict[str, Any]) -> bool:
    # Normalize images/options, select option placements that are confirmed,
    # overridden, or auto with confidence >= 0.95, remove only those image
    # references from every option, then prepend each token to its target option
    # in placement order. Update content and contentMarkdown atomically.
```

Call it after layout placement reconciliation and before import questions are built. Call it again after existing-question preservation so generated trusted placement changes cannot leave stale option Markdown behind.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run the same focused pytest command. Expected: one matching test passes.

### Task 2: Separate structural apply blockers from placement-review blockers

**Files:**
- Modify: `backend/python-worker/app/import_services.py`
- Test: `backend/python-worker/tests/test_import_services.py`

- [ ] **Step 1: Write the failing preview-contract test**

Create a canonical preview containing a placement validation blocker but no duplicate-question review. Assert:

```python
assert result["applyBlockingIssues"] == []
assert result["blockingIssues"][0]["type"] == "image-placement-validation"
```

Also retain the existing ambiguous-duplicate test and assert its structural code appears in both arrays.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
cd backend/python-worker
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_import_services.py -k 'apply_blocking or canonicalize_import_outputs'
```

Expected: `applyBlockingIssues` is missing.

- [ ] **Step 3: Add the preview field without weakening standardization safety**

Use the canonical plan's structural blockers for the new field:

```python
apply_blocking_issues = copy.deepcopy(plan.get("blockingIssues") or [])
blocking_issues = [*apply_blocking_issues, *placement_blocking_issues]
```

Return both fields. Leave `canonicalization.requiresReview` and `blockingIssues` based on all issues.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the same focused pytest command and expect all selected tests to pass.

### Task 3: Serialize each frontend option as one atomic task

**Files:**
- Modify: `local-platform/src/lib/question.ts`
- Test: `local-platform/src/lib/question.test.ts`

- [ ] **Step 1: Write the failing serializer test**

Create a question matching server task 12 question 2: stale option Markdown plus correct A/B/C/D placements. Assert `getQuestionMarkdown(question)` contains exactly four lines:

```latex
\task ![](图1) 食品夹
\task ![](图2) 船桨
\task ![](图3) 修枝剪刀
\task ![](图4) 托盘天平
```

Assert no option image token occurs before or after another option's `\\task` body.

- [ ] **Step 2: Run the focused Vitest and verify RED**

```bash
cd local-platform
npx vitest run src/lib/question.test.ts
```

Expected: output still contains multiline stale B/C ownership.

- [ ] **Step 3: Add a defensive question serializer**

Before `withEditableChoiceOptions`, derive display options by applying only trusted option placements to known image tokens. Normalize each task body to one physical line while preserving LaTeX commands, and emit exactly one `\\task` per structured option.

- [ ] **Step 4: Run the focused Vitest and verify GREEN**

Run the same Vitest command. Expected: all question tests pass.

### Task 4: Enable structure apply while preserving placement warnings

**Files:**
- Modify: `local-platform/src/lib/placement-review.ts`
- Modify: `local-platform/src/lib/placement-review.test.ts`
- Modify: `local-platform/src/components/question-bank/ImportWorkbenchTask.tsx`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportTaskCanonicalizationService.java`
- Modify: `backend/src/test/java/com/aigeneration/questionbank/ImportTaskCanonicalizationServiceTest.java`

- [ ] **Step 1: Write failing frontend and Java tests**

Frontend: give `blockingIssues` one placement item and `applyBlockingIssues: []`; assert structure review is not apply-blocking but is still review-required.

Java: mock a fresh preview with matching token, placement `blockingIssues`, and empty `applyBlockingIssues`; assert `apply()` snapshots and syncs. Add a second test where `applyBlockingIssues` contains `ambiguous-duplicate-question` and assert HTTP 409 with no writes.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
cd local-platform
npx vitest run src/lib/placement-review.test.ts
cd ../backend
mvn -q -Dtest=ImportTaskCanonicalizationServiceTest test
```

Expected: frontend reports blocking and Java rejects the placement-only preview.

- [ ] **Step 3: Implement explicit apply blocking**

Make frontend `blocking` use `applyBlockingIssues`, with fallback to `blockingIssues` only when the new field is absent. Add `reviewRequired` based on all blockers, keep global standardization checking `blockingIssues`, enable the apply button when only placement review remains, and show text explaining that image ownership still requires per-question review.

Make Java `apply()` check `applyBlockingIssues`; for backward compatibility, fall back to `blockingIssues` when the worker response omits the new field. Keep `requireReadyForStandardization()` unchanged so global standardization still blocks on all placement issues.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the same frontend and Java commands. Expected: all selected tests pass.

### Task 5: Full verification, commit, deployment, and real-task regression

**Files:**
- Verify all modified source and test files
- Deploy the built backend JAR, frontend `dist`, and Python worker source

- [ ] **Step 1: Run all worker tests**

```bash
cd backend/python-worker
PYTHONPATH=. .venv/bin/python -m pytest -q
```

Expected: zero failures.

- [ ] **Step 2: Run all Java tests**

```bash
cd backend
mvn test
```

Expected: BUILD SUCCESS.

- [ ] **Step 3: Run frontend tests and production build**

```bash
cd local-platform
npm test -- --run
npm run build
```

Expected: all tests pass and production build exits zero.

- [ ] **Step 4: Commit and push the feature and main refs**

Stage only files from this plan, commit with a focused message, push `codex/image-placement-upgrade`, then fast-forward remote `main` without modifying the dirty main worktree.

- [ ] **Step 5: Deploy and verify server task 12**

Sync source plus fresh frontend/backend build artifacts, rebuild/restart services, and verify health endpoints. Request task 12 canonical preview and assert:

```text
question 2 options: A=图1食品夹, B=图2船桨, C=图3修枝剪刀, D=图4托盘天平
applyBlockingIssues: []
blockingIssues: placement review entries remain visible
```

Apply the fresh token through the normal guarded endpoint, then fetch task 12 again and verify the editor source is backed by four atomic option records. Confirm global standardization is still blocked while unresolved placement review entries remain.
