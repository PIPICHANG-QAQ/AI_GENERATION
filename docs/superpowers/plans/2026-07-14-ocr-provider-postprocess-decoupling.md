# OCR Provider 与题目后处理解耦 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 MinerU OCR 制品显式转换为 provider-neutral bundle，并使后处理可直接消费该 bundle，且旧 jobId 入口输出不变。

**Architecture:** 第一轮采用兼容型 canonical bundle。MinerU Adapter 负责唯一一次识别现有文件名和私有 JSON；`OcrPostProcessingPipeline` 只接收 bundle 并调用保留顺序的算法。旧入口只组装 bundle 后委托新入口。

**Tech Stack:** Python 3、FastAPI、Pydantic、pytest、现有 MinerU 制品、现有 OCR golden/benchmark 工具。

---

> **Evidence update — 2026-07-16 (Asia/Shanghai):** 18/18 implementation checklist items below have source, commit, and verification evidence. Four RED checkpoints are reconstructed evidence, not original preserved output: each was reproduced in a temporary worktree at the implementation commit's parent with the corresponding test file restored from the implementation commit, and each failed with the expected missing module/API/boundary reason. Task 4 full verification passed on 2026-07-16 with Python full test suite, OCR golden replay, OCR boundary checks, and benchmark comparison tool output `status=equal`.

### Task 1: 定义 Canonical OCR Bundle

**Files:**
- Create: `backend/python-worker/app/ocr/contracts.py`
- Test: `backend/python-worker/tests/test_ocr_postprocess_contracts.py`

- [x] 写失败测试：L2 bundle 的 layout、assets 和 source ref 可被序列化；Markdown、图片引用和 bbox 非法时抛出确定性错误。
- [x] 运行：`PYTHONPATH=. .venv/bin/python -m pytest tests/test_ocr_postprocess_contracts.py -q -p no:cacheprovider`，确认失败原因是模块不存在。2026-07-16 重建 RED 证据：在 `27f3f98^` 临时 worktree 中恢复 `27f3f98` 的测试文件，退出码 2，匹配 `ModuleNotFoundError|No module named.*contracts|ImportError`。
- [x] 实现最小 dataclass/validator：`CanonicalOcrBundle`、`OcrAsset`、`OcrLayoutBlock`、`OcrPage`、`SourceDocumentRef`。
- [x] 重跑测试并提交。

### Task 2: MinerU Adapter

**Files:**
- Create: `backend/python-worker/app/ocr/mineru_adapter.py`
- Test: `backend/python-worker/tests/test_mineru_ocr_adapter.py`

- [x] 写失败测试：由 fixture 目录构造 bundle，保留 Markdown、图片资源、content-list layout block、middle 优先 layout block、页面尺寸和上传源文件。
- [x] 运行该测试并确认失败原因是 adapter 不存在。2026-07-16 重建 RED 证据：在 `9336eb4^` 临时 worktree 中恢复 `9336eb4` 的测试文件，退出码 2，匹配 `ModuleNotFoundError|No module named.*mineru_adapter|ImportError`。
- [x] 最小实现 `MineruOcrBundleAdapter.from_job(jobId)`；唯一允许识别 MinerU 文件名和字段。
- [x] 重跑测试、既有 OCR processing 测试并提交。

### Task 3: Bundle 驱动的后处理外观

**Files:**
- Modify: `backend/python-worker/app/ocr/postprocess_pipeline.py`
- Modify: `backend/python-worker/app/ocr_processing.py`
- Test: `backend/python-worker/tests/test_ocr_postprocess_pipeline.py`

- [x] 写失败测试：`pipeline.run_bundle(bundle)` 产生与旧 `collect_outputs(jobId)` 相同的 outputs；旧入口委托 adapter 与 bundle pipeline。
- [x] 运行该测试并确认失败。2026-07-16 重建 RED 证据：在 `3f50450^` 临时 worktree 中恢复 `3f50450` 的测试文件，退出码 1，匹配 `AttributeError|ImportError|ModuleNotFoundError|run_bundle|from_bundle|No module named`。
- [x] 提取显式 bundle 入参和兼容 context；算法阶段、写入步骤、返回字段与异常语义不变。
- [x] 重跑 focused tests，确认全部通过并提交。

### Task 4: 契约边界与兼容回归

**Files:**
- Modify: `backend/python-worker/tests/test_ocr_flow.py`
- Modify: `backend/python-worker/tests/test_ocr_processing.py`
- Test: `backend/python-worker/tests/test_ocr_postprocess_contracts.py`

- [x] 写失败测试：provider runtime 只负责生成 OCR 工件；执行编排层在工件成功后调用统一 pipeline；显式 bundle 不需要 provider 名称或目录扫描。
- [x] 运行失败测试。2026-07-16 重建 RED 证据：在 `31bdfea^` 临时 worktree 中恢复 `31bdfea` 的测试文件，退出码 2，匹配 `AttributeError|AssertionError|collect_outputs|provider|pipeline|FAILED`。
- [x] 只作调用边界改动，移除 `OcrFlowRuntime.collect_outputs`，保留最终 job 状态和 `outputs` 外观。
- [x] 运行 Python 全量、golden replay 和 benchmark compare；提交。2026-07-16 验证结果：`pytest backend/python-worker/tests` 366 passed + 51 subtests；`test_ocrflow_golden.py` 32 tests OK；`test_check_ocrflow_boundaries.py` 46 tests OK；`test_benchmark_ocrflow.py` 8 tests OK，工具输出 `status=equal`。

### Task 5: 文档与交接

**Files:**
- Modify: `docs/architecture/CODE_STRUCTURE_PORTABILITY_REVIEW.md`
- Modify: `docs/architecture/decisions/0003-mineru-default-ocr-provider.md`

- [x] 记录 bundle v1、L0/L1/L2、兼容期限制和腾讯 Adapter 接入条件。
- [x] 运行 portability 检查并提交。
