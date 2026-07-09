# AI Standardize Reliable Candidates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AI standardization faster and safer by returning deterministic local/OCR candidates before calling LLM, and by blocking unsafe candidates from being applied.

**Architecture:** The worker standardizer first repairs deterministic LaTeX delimiter damage, then checks trusted OCR context as a fallback, then uses a cached LLM call only when local and OCR candidates remain unsafe. Java must keep current edit text separate from trusted OCR context. The frontend renders candidate source metadata and disables applying candidates that fail render/safety validation.

**Tech Stack:** Python worker (`backend/python-worker/app`), Java Spring backend (`backend/src/main/java`), React local platform (`local-platform/src`), unittest, Maven, Vite build, local deploy smoke.

---

## Root Cause Evidence

- The failing sample is import task `import_task_20260706_213341_22989903`, question `import_question_20260706_213436_2115c068`.
- `manualMarkdown` is severely damaged with nested `$`, `\frac$`, and `$$$$`.
- The original OCR `stemMarkdown` for the same question has no severe LaTeX issues.
- A real standardize call returned HTTP 200 but took about 45.8 seconds and produced a candidate with display math next to `(2)`, which can still render poorly in the frontend.

## Tasks

### Task 1: Trusted OCR Fallback Before LLM

**Files:**
- Modify: `backend/python-worker/app/import_services.py`
- Test: `backend/python-worker/tests/test_import_services.py`
- Modify: `docs/superpowers/plans/2026-07-06-ai-standardize-reliable-candidates.md`

- [x] Add a failing Python test where damaged current markdown and clean trusted OCR context return the OCR candidate without calling LLM.
- [x] Implement trusted OCR fallback independent of LLM configured state.
- [x] Ensure fallback metadata marks `source=ocr-fallback`, `rawOcrFallbackUsed=true`, and `candidateSevereIssues=[]`.
- [x] Run `PYTHONPATH=backend/python-worker backend/python-worker/.venv/bin/python -m unittest discover -s backend/python-worker/tests -p test_import_services.py`.
- [x] Run `./scripts/test_python_worker.sh` and `python -m compileall backend/python-worker/app`.
- [x] Update this task checklist.

### Task 2: Render-Safe Candidate Post-Processing

**Files:**
- Modify: `backend/python-worker/app/import_services.py`
- Test: `backend/python-worker/tests/test_import_services.py`
- Modify: `local-platform/src/components/question-bank/StandardizeCandidatePanel.tsx`
- Modify: `docs/superpowers/plans/2026-07-06-ai-standardize-reliable-candidates.md`

- [x] Add a failing Python test for `$$...$$(2)` display math adjacency.
- [x] Add display math normalization so block math delimiters are on their own lines.
- [x] Add render validation metadata to standardizer responses.
- [x] Disable frontend candidate apply when render validation or severe candidate validation fails.
- [x] Run Python worker tests and local-platform build.
- [x] Update this task checklist.

### Task 3: Short-Term Standardize Cache

**Files:**
- Modify: `backend/python-worker/app/import_services.py`
- Test: `backend/python-worker/tests/test_import_services.py`
- Modify: `.env.example`
- Modify: `docs/delivery/OPERATIONS_GUIDE.md`
- Modify: `docs/superpowers/plans/2026-07-06-ai-standardize-reliable-candidates.md`

- [x] Add a failing test proving repeated identical standardize requests reuse cached LLM results.
- [x] Implement TTL cache keyed by current markdown, trusted OCR context, and structured hints.
- [x] Add `AI_STANDARDIZE_CACHE_TTL_SECONDS` to config docs.
- [x] Run worker tests and compileall.
- [x] Update this task checklist.

### Task 4: Java Context Separation

**Files:**
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/AiFlowOrchestrationService.java`
- Test: `backend/src/test/java/com/aigeneration/questionbank/DomainControllerTest.java`
- Modify: `docs/product/OCR_PHASE_1_SPEC.md`
- Modify: `docs/architecture/TECHNICAL_DESIGN.md`
- Modify: `docs/superpowers/plans/2026-07-06-ai-standardize-reliable-candidates.md`

- [x] Add or update Java test to assert worker standardize requests do not mix current manual markdown into trusted OCR context.
- [x] Remove `manualMarkdown` from Java `importRawContext` and `bankRawContext`.
- [x] Keep current edit text only in request `markdown`.
- [x] Run `cd backend && JAVA_HOME=$(/usr/libexec/java_home -v 17) mvn test`.
- [x] Update affected docs and this task checklist.

### Task 5: End-to-End Verification

**Files:**
- Modify: `docs/CHANGELOG.md`
- Modify: `docs/delivery/ACCEPTANCE.md`
- Modify: `docs/superpowers/plans/2026-07-06-ai-standardize-reliable-candidates.md`

- [x] Run full Python worker tests and compileall.
- [x] Run Java tests.
- [x] Run `cd local-platform && npm run build`.
- [x] Run `./scripts/deploy_local.sh --skip-smoke` and `./scripts/smoke_deploy_basic.py`.
- [x] If AI key is configured, run one real AI standardize request for the known damaged question and verify it returns a non-LLM OCR fallback quickly.
- [x] Run documentation/package checks.
- [x] Update changelog, acceptance, and this task checklist.
