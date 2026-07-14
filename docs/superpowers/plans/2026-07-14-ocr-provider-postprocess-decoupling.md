# OCR Provider 与题目后处理解耦 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 MinerU OCR 制品显式转换为 provider-neutral bundle，并使后处理可直接消费该 bundle，且旧 jobId 入口输出不变。

**Architecture:** 第一轮采用兼容型 canonical bundle。MinerU Adapter 负责唯一一次识别现有文件名和私有 JSON；`OcrPostProcessingPipeline` 只接收 bundle 并调用保留顺序的算法。旧入口只组装 bundle 后委托新入口。

**Tech Stack:** Python 3、FastAPI、Pydantic、pytest、现有 MinerU 制品、现有 OCR golden/benchmark 工具。

---

### Task 1: 定义 Canonical OCR Bundle

**Files:**
- Create: `backend/python-worker/app/ocr/contracts.py`
- Test: `backend/python-worker/tests/test_ocr_postprocess_contracts.py`

- [ ] 写失败测试：L2 bundle 的 layout、assets 和 source ref 可被序列化；Markdown、图片引用和 bbox 非法时抛出确定性错误。
- [ ] 运行：`PYTHONPATH=. .venv/bin/python -m pytest tests/test_ocr_postprocess_contracts.py -q -p no:cacheprovider`，确认失败原因是模块不存在。
- [ ] 实现最小 dataclass/validator：`CanonicalOcrBundle`、`OcrAsset`、`OcrLayoutBlock`、`OcrPage`、`SourceDocumentRef`。
- [ ] 重跑测试并提交。

### Task 2: MinerU Adapter

**Files:**
- Create: `backend/python-worker/app/ocr/mineru_adapter.py`
- Test: `backend/python-worker/tests/test_mineru_ocr_adapter.py`

- [ ] 写失败测试：由 fixture 目录构造 bundle，保留 Markdown、图片资源、content-list layout block、middle 优先 layout block、页面尺寸和上传源文件。
- [ ] 运行该测试并确认失败原因是 adapter 不存在。
- [ ] 最小实现 `MineruOcrBundleAdapter.from_job(jobId)`；唯一允许识别 MinerU 文件名和字段。
- [ ] 重跑测试、既有 OCR processing 测试并提交。

### Task 3: Bundle 驱动的后处理外观

**Files:**
- Modify: `backend/python-worker/app/ocr/postprocess_pipeline.py`
- Modify: `backend/python-worker/app/ocr_processing.py`
- Test: `backend/python-worker/tests/test_ocr_postprocess_pipeline.py`

- [ ] 写失败测试：`pipeline.run_bundle(bundle)` 产生与旧 `collect_outputs(jobId)` 相同的 outputs；旧入口委托 adapter 与 bundle pipeline。
- [ ] 运行该测试并确认失败。
- [ ] 提取显式 bundle 入参和兼容 context；算法阶段、写入步骤、返回字段与异常语义不变。
- [ ] 重跑 focused tests，确认全部通过并提交。

### Task 4: 契约边界与兼容回归

**Files:**
- Modify: `backend/python-worker/tests/test_ocr_flow.py`
- Modify: `backend/python-worker/tests/test_ocr_processing.py`
- Test: `backend/python-worker/tests/test_ocr_postprocess_contracts.py`

- [ ] 写失败测试：provider runtime 只负责扫描并把 postprocess 调度给统一 pipeline；显式 bundle 不需要 provider 名称或输出目录扫描。
- [ ] 运行失败测试。
- [ ] 只作调用边界改动，保留 `OcrFlowRuntime.collect_outputs` 兼容签名与 job 状态。
- [ ] 运行 Python 全量、golden replay 和 benchmark compare；提交。

### Task 5: 文档与交接

**Files:**
- Modify: `docs/architecture/CODE_STRUCTURE_PORTABILITY_REVIEW.md`
- Modify: `docs/architecture/decisions/0003-mineru-default-ocr-provider.md`

- [ ] 记录 bundle v1、L0/L1/L2、兼容期限制和腾讯 Adapter 接入条件。
- [ ] 运行 portability 检查并提交。
