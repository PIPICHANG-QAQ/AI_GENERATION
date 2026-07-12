# Image Placement Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent cross-question image contamination, preserve image ownership evidence, and render stem/option images in their correct targets end to end.

**Architecture:** Add a deterministic `image-placement` layer between boundary construction and persistence. Markdown offsets remain authoritative, layout geometry supplies non-destructive corroboration, and ambiguous images remain unassigned. Persist placements alongside existing image arrays for compatibility, then make the frontend and exporter consume the explicit ownership model.

**Tech Stack:** Python 3.10/FastAPI worker, Java 17+/Spring Boot/MyBatis Plus, React/TypeScript/Vite, pytest, JUnit, Maven.

---

### Task 1: Freeze Real Regressions and Correct Fallback Selection

**Files:**
- Modify: `backend/python-worker/tests/test_ocr_processing.py`
- Modify: `backend/python-worker/tests/test_question_boundary.py`
- Modify: `backend/python-worker/app/ocr_processing.py`
- Modify: `backend/python-worker/app/question_boundary.py`

- [x] **Step 1: Write failing tests for legacy cross-question merge**

Add a test that creates q1 with four image refs, q2 without images, and a legacy result that places the same four images on q2. Assert `merge_legacy_images` does not duplicate assets already owned by q1.

- [x] **Step 2: Run the focused test and verify RED**

Run: `pytest tests/test_question_boundary.py -k legacy_images -v`
Expected: FAIL because q2 receives q1 images.

- [x] **Step 3: Implement evidence-aware legacy merge**

Track image keys already assigned in the primary structure. Copy legacy images only when they are unique to that legacy question and do not conflict with another primary owner. Record `imageWarnings` for rejected candidates.

- [x] **Step 4: Write failing test for invalid whole-document fallback**

Patch `validate_structure` to return invalid for both primary and legacy candidates and assert `collect_outputs` keeps the primary candidate with `fallback=false`, `requiresReview=true`, and both validation reports.

- [x] **Step 5: Run the test and verify RED**

Run: `pytest tests/test_ocr_processing.py -k invalid_fallback -v`
Expected: FAIL because legacy replaces primary unconditionally.

- [x] **Step 6: Implement candidate quality selection**

Add a small pure helper that compares validity, question evidence coverage, option completeness, and image-reference coverage. Never replace a primary candidate with an invalid lower-quality fallback.

- [x] **Step 7: Run focused and full Python tests**

Run: `pytest tests/test_ocr_processing.py tests/test_question_boundary.py -q`
Expected: PASS.

### Task 2: Preserve Explicit Image Placement Evidence

**Files:**
- Create: `backend/python-worker/app/image_placement.py`
- Create: `backend/python-worker/tests/test_image_placement.py`
- Modify: `backend/python-worker/app/question_boundary.py`
- Modify: `backend/python-worker/app/question_markdown.py`
- Modify: `backend/python-worker/app/ocr_processing.py`

- [x] **Step 1: Write failing tests for explicit option spans**

Define the wished-for API:

```python
placements = build_image_placements(question_boundary, images, layout_items=[])
assert placements[0]["target"] == {"kind": "option", "optionLabel": "A"}
assert placements[0]["inference"]["method"] == "explicit-offset"
```

Cover stem, A-D option, subquestion and unassigned targets.

- [x] **Step 2: Run tests and verify RED**

Run: `pytest tests/test_image_placement.py -v`
Expected: ERROR/FAIL because `app.image_placement` does not exist.

- [x] **Step 3: Implement the minimal placement module**

Implement pure helpers for image keys, interval containment, stable placement IDs, explicit target inference, confidence, reasons and warnings. Preserve `markdownStart/end/pageIndex/bbox` when available.

- [x] **Step 4: Integrate placements into question construction**

Use normalized option/subquestion spans before their offsets are discarded. Attach `imagePlacements` to parent and child questions, and keep `images[]` unchanged for compatibility.

- [x] **Step 5: Add consistency validation**

Reject dangling image IDs and duplicate non-shared high-confidence owners. Warn for choice questions with zero options, unassigned images, and image refs that point to another target.

- [x] **Step 6: Verify GREEN**

Run: `pytest tests/test_image_placement.py tests/test_question_boundary.py -q`
Expected: PASS.

### Task 3: Add Non-Destructive Geometry Reconciliation

**Files:**
- Modify: `backend/python-worker/app/image_placement.py`
- Modify: `backend/python-worker/app/question_layout.py`
- Modify: `backend/python-worker/app/ocr_processing.py`
- Modify: `backend/python-worker/tests/test_image_placement.py`
- Modify: `backend/python-worker/tests/test_question_layout.py`

- [x] **Step 1: Write failing tests for two-column option grids**

Build A/B/C/D label bboxes and four image bboxes whose serialized order differs from visual option order. Assert geometry assigns one image to each option label.

- [x] **Step 2: Verify RED**

Run: `pytest tests/test_image_placement.py -k geometry -v`
Expected: FAIL because geometry reconciliation is absent.

- [x] **Step 3: Expose read-only layout evidence**

Return normalized `blockId/type/text/imageRef/pageIndex/bbox` nodes from `question_layout` without mutating question boundaries.

- [x] **Step 4: Implement geometry scoring**

Score same-page containment, option-cell proximity, row/column agreement and question-region containment. Use geometry only when explicit offset is absent or to lower confidence on conflict. Keep `unassigned` when the best/second-best margin is insufficient.

- [x] **Step 5: Integrate as `image-reconcile` output**

Add sanitized summary fields: assigned counts by target, conflicts, unassigned count and method counts. Do not expose image bytes.

- [x] **Step 6: Verify GREEN and layout isolation**

Run: `pytest tests/test_image_placement.py tests/test_question_layout.py tests/test_ocr_processing.py -q`
Expected: PASS, with existing PaperLayout behavior unchanged.

### Task 4: Persist and Publish Image Placements

**Files:**
- Modify: `backend/python-worker/app/worker_base.py`
- Modify: `backend/python-worker/app/import_services.py`
- Modify: `backend/src/main/resources/schema.sql`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/entity/ImportQuestionEntity.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/entity/BankQuestionEntity.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportQuestionSyncService.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/BankQuestionService.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/capability/service/QuestionProcessingCapabilityService.java`
- Modify: `backend/src/test/java/com/aigeneration/questionbank/DomainControllerTest.java`
- Modify: `question-engine/openapi/question-engine.v1.yaml`

- [x] **Step 1: Write failing Java persistence/API tests**

Save a question with stem and option placements, reload it, and assert the placement list remains byte-for-byte equivalent through import snapshot, bank question and question-package output.

- [x] **Step 2: Verify RED**

Run: `mvn -q -Dtest=DomainControllerTest test`
Expected: FAIL because placements are not persisted or serialized.

- [x] **Step 3: Add JSON persistence fields**

Add `image_placements_json` columns and entity accessors. Map `imagePlacements` in sync, update, bank import and capability serialization paths.

- [x] **Step 4: Extend Python payloads and OpenAPI**

Allow optional `imagePlacements` on import/bank payloads. Define `QuestionImagePlacement`, `ImagePlacementTarget`, evidence and inference schemas while keeping fields optional for old clients.

- [x] **Step 5: Verify GREEN**

Run: `mvn -q test`
Expected: PASS.

### Task 5: Stabilize Frontend Labels and Add Ownership Review

**Files:**
- Modify: `local-platform/src/lib/question.ts`
- Modify: `local-platform/src/components/question-bank/QuestionImageUploader.tsx`
- Modify: `local-platform/src/components/question-bank/QuestionEditor.tsx`
- Modify: `local-platform/src/components/question-bank/QuestionCard.tsx`
- Modify: `local-platform/package.json`
- Create: `local-platform/src/lib/question.test.ts`

- [x] **Step 1: Add frontend test runner and failing label tests**

Add Vitest and tests proving that adding/removing an image preserves labels for retained image keys and that frontend no longer auto-zips unassigned images to A-D.

- [x] **Step 2: Verify RED**

Run: `npm test -- --run src/lib/question.test.ts`
Expected: FAIL because retained images are renumbered and no test runner exists before dependency setup.

- [x] **Step 3: Fix stable label allocation**

Reserve labels only for images not present in the next set, then allocate retained keys first and new labels afterward.

- [x] **Step 4: Add placement-aware review controls**

Show a target selector per image: 未归属、题干、A-H、各小问. Update `imagePlacements` and the corresponding Markdown token atomically. Preserve the user-side removal of automatic option zip.

- [x] **Step 5: Block silent verification**

Display placement warnings and require explicit confirmation before marking a question verified when unassigned/conflicting placements remain.

- [x] **Step 6: Verify GREEN**

Run: `npm test -- --run && npm run build`
Expected: tests and TypeScript/Vite build pass.

### Task 6: Preserve Placement in Exports

**Files:**
- Modify: `backend/python-worker/app/export_service.py`
- Modify: `backend/python-worker/tests/test_export_service.py`

- [x] **Step 1: Write failing export tests**

Build a choice question with stem image and distinct A-D images. Assert generated Markdown keeps each image inside the corresponding option rather than emitting a single pre-option image block.

- [x] **Step 2: Verify RED**

Run: `pytest tests/test_export_service.py -k image_placement -v`
Expected: FAIL because exporter flattens all images.

- [x] **Step 3: Implement placement-aware rendering**

Resolve images by stable label/imageId and render stem, option and subquestion placements at their targets. Warn and omit unassigned images from formal export unless the caller explicitly chooses an appendix.

- [x] **Step 4: Verify GREEN**

Run: `pytest tests/test_export_service.py -q`
Expected: PASS.

### Task 7: Full Regression, Contract and Documentation

**Files:**
- Modify: `docs/CHANGELOG.md`
- Modify: `docs/product/OCR_PHASE_1_SPEC.md`
- Modify: `docs/product/QUESTION_BANK_PHASE_2_SPEC.md`
- Modify: `docs/delivery/ACCEPTANCE.md`
- Modify: `docs/architecture/TECHNICAL_DESIGN.md`
- Modify: `scripts/check_question_engine_contract.py`

- [x] **Step 1: Add contract checks**

Assert OpenAPI publishes optional `imagePlacements`, owner target enums and evidence fields.

- [x] **Step 2: Run all verification commands**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider
mvn -q test
npm test -- --run
npm run build
python scripts/check_question_engine_contract.py
git diff --check
```

Expected: all commands exit 0.

- [x] **Step 3: Update docs with behavior and rollback rules**

Document placement ownership, confidence, fallback selection, unassigned behavior, review blocking, export rules and shadow/canary metrics.

- [x] **Step 4: Self-review scope and generated artifacts**

Confirm no `.env`, storage data, OCR outputs, build outputs, node_modules or virtual environments are staged.

