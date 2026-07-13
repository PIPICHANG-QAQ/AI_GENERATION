# OCR Nested Subquestion Images Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep OCR images owned by their actual subquestion, remove trailing document-title noise, expose nested images in the task library, and prevent AI standardization from dropping or moving them.

**Architecture:** Python remains responsible for evidence-based OCR boundaries and candidate validation. Java recursively materializes the existing parent/subquestion JSON image tree into a searchable index without changing ownership. React edits child images inside the child form and persists them through the existing whole-question update API.

**Tech Stack:** Python 3.10+/unittest, Java 17/Spring Boot/MyBatis Plus/JUnit, React 18/TypeScript/Vite.

---

### Task 1: Trim split exam titles without losing child images

**Files:**
- Modify: `backend/python-worker/app/question_boundary.py`
- Test: `backend/python-worker/tests/test_question_boundary.py`

- [ ] **Step 1: Write the failing q37-style boundary test**

```python
def test_trims_split_exam_title_after_last_subquestion_but_keeps_both_images(self):
    markdown = """37. 装置测试，求：
(1) 第一问；
(2) 第二问；
(3) A 和 B 的重力。\n\n![](images/q37-a.png)\n\n![](images/q37-b.png)
# 2018-2019学年四川省成都市天府新区八年级（下）期末物理试
# 卷
"""
    assets = [
        {"name": "q37-a.png", "path": "images/q37-a.png", "url": "/a.png"},
        {"name": "q37-b.png", "path": "images/q37-b.png", "url": "/b.png"},
    ]
    structured = build_structure_from_boundaries(markdown, detect_local_boundaries(markdown, assets), assets)
    parent = structured["sections"][0]["questions"][0]
    child = parent["subQuestions"][2]
    self.assertEqual([], parent["images"])
    self.assertEqual(["images/q37-a.png", "images/q37-b.png"], [image["path"] for image in child["images"]])
    self.assertNotIn("2018-2019学年", child["stemMarkdown"])
```

- [ ] **Step 2: Run the focused test and verify it fails for the split title**

Run: `cd backend/python-worker && uv run python -m unittest tests.test_question_boundary.QuestionBoundaryTest.test_trims_split_exam_title_after_last_subquestion_but_keeps_both_images -v`

Expected: FAIL because the first title line does not end in `试卷/考试/真题`.

- [ ] **Step 3: Extend only the tail-title regex**

Add a bounded school-year alternative that recognizes `YYYY-YYYY学年...期末...试` at a Markdown heading boundary. Keep `trim_non_question_tail_end()` range-based so image offsets before the title remain valid.

- [ ] **Step 4: Run boundary tests**

Run: `cd backend/python-worker && uv run python -m unittest tests.test_question_boundary -v`

Expected: PASS.

### Task 2: Recursively index nested images in both task-library implementations

**Files:**
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportQuestionSyncService.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/QuestionImageFlowService.java`
- Modify: `backend/python-worker/app/import_services.py`
- Test: `backend/src/test/java/com/aigeneration/questionbank/DomainControllerTest.java`
- Test: `backend/python-worker/tests/test_import_services.py`

- [ ] **Step 1: Write failing Java and Python task-library tests**

The Java test synchronizes a parent with `images=[]` and child `(3)` with two images, then asserts:

```java
mockMvc.perform(get("/api/import-tasks/nested_image_task/image-library"))
    .andExpect(jsonPath("$.items.length()").value(2))
    .andExpect(jsonPath("$.items[0].ownerKind").value("subQuestion"))
    .andExpect(jsonPath("$.items[0].ownerLabel").value("(3)"));
assertThat(importQuestionSyncService.listImages(parentId)).isEmpty();
```

The Python test calls `import_task_image_library(task)` with the same tree and checks the two resources carry child ownership.

- [ ] **Step 2: Run focused tests and observe missing nested entries**

Run:

```bash
cd backend && mvn -Dtest=DomainControllerTest#nestedSubQuestionImagesAreIndexedWithoutBecomingParentImages test
cd backend/python-worker && uv run python -m unittest tests.test_import_services.ImportServicesTest.test_task_image_library_indexes_nested_subquestion_images -v
```

Expected: FAIL because both current indexers ignore `subQuestions[].images` ownership.

- [ ] **Step 3: Replace parent-only Java sync with image-tree sync**

Implement a private tree walker that:

```java
syncImageTree(taskId, questionId, parentImages, children, updatedAt);
// parent owner: question/questionId
// child owner: subQuestion/child.id/child.label/subQuestions[index]
```

Store owner metadata in `rawJson`, dedupe by physical asset key, and preserve all owners. Make `listImages(questionId)` return parent-owned rows only so capability views do not treat child images as parent images. Rebuild the tree after OCR sync, manual subquestion updates, AI writes, and parent upload replacement.

- [ ] **Step 4: Make Python task library recursively aggregate question ownership**

Keep OCR output assets, then walk `task.questions` and merge parent/child ownership into the matching resource. Do not copy the image into `question.images`.

- [ ] **Step 5: Run focused and full backend tests**

Run:

```bash
cd backend && mvn -Dtest=DomainControllerTest test
cd backend/python-worker && uv run python -m unittest tests.test_import_services -v
```

Expected: PASS.

### Task 3: Preserve child image assets and references through standardization

**Files:**
- Modify: `backend/python-worker/app/import_services.py`
- Modify: `backend/python-worker/app/question_markdown.py`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportQuestionSyncService.java`
- Test: `backend/python-worker/tests/test_import_services.py`
- Test: `backend/src/test/java/com/aigeneration/questionbank/DomainControllerTest.java`

- [ ] **Step 1: Write failing candidate and Java merge tests**

Create a parent whose child `(3)` has two images and two refs. The Python candidate returns child text without images/refs; validation must reject an actual dropped-ref candidate, while normal AI text enrichment must preserve the current child images. The Java AI response must not overwrite a non-empty current child image list.

- [ ] **Step 2: Verify the tests fail on current replacement behavior**

Run focused Python and Java test methods and confirm the image list or reference is lost before changing production code.

- [ ] **Step 3: Merge AI child text into current child structure**

Use current subquestions as the structural base:

```python
sub_questions = normalize_sub_questions(current_sub_questions, response.get("subQuestions"))
```

Add child-level required-image validation and make `ensure_question_images_in_markdown()` traverse whichever of `subQuestions` or `children` is present. Preserve `imagePlacements` from the current child.

- [ ] **Step 4: Harden Java AI child merge**

Do not overwrite a non-empty target `images` or `imagePlacements` from an AI response. After the merge, rebuild the recursive image index.

- [ ] **Step 5: Run standardization regressions**

Run:

```bash
cd backend/python-worker && uv run python -m unittest tests.test_import_services tests.test_question_boundary -v
cd backend && mvn -Dtest=DomainControllerTest test
```

Expected: PASS.

### Task 4: Add child-scoped image management and ownership hints

**Files:**
- Modify: `local-platform/src/lib/question.ts`
- Modify: `local-platform/src/components/question-bank/QuestionImageUploader.tsx`
- Modify: `local-platform/src/components/question-bank/QuestionCard.tsx`
- Modify: `local-platform/src/components/question-bank/QuestionEditor.tsx`

- [ ] **Step 1: Extend the image view type with owner metadata**

Add optional `ownerKind`, `ownerId`, `ownerLabel`, and `owners` fields. Change physical dedupe keys to prefer `storageFileId`, URL, and path before database index IDs.

- [ ] **Step 2: Show ownership in the task library**

Render a compact overlay such as `小问 (3)` or `父题`, based only on response metadata.

- [ ] **Step 3: Add a child-only image change handler**

For one subquestion, remove deleted refs and append new refs only in that subquestion's Markdown, answer, analysis, options, and `images`. Do not mutate parent images or siblings.

- [ ] **Step 4: Render `QuestionImageUploader` inside each child editor**

Pass `sub.images` and `taskImageLibrary`; selection remains a draft until the existing whole-question save persists `subQuestions[].images`.

- [ ] **Step 5: Build the frontend**

Run: `cd local-platform && npm run build`

Expected: TypeScript and Vite build exit 0.

### Task 5: Full verification and scope review

**Files:**
- Verify all modified files.

- [ ] **Step 1: Run the complete Python worker suite**

Run: `cd backend/python-worker && uv run python -m unittest discover -s tests -v`

- [ ] **Step 2: Run the complete Java suite**

Run: `cd backend && mvn test`

- [ ] **Step 3: Build the frontend**

Run: `cd local-platform && npm run build`

- [ ] **Step 4: Review the diff against the ownership invariant**

Confirm every changed line supports one of: tail filtering, nested index, standardization conservation, child editor, or the already-present removal of unsafe equal-count option-image guessing. Confirm no code promotes child images into parent `images`.
