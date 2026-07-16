# OCR Flow Modularization and Portability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有“OCR + 题目后处理”能力整理成可由公司题库独立接入的 Java 主能力与 Python 算法 worker，在不改变现有业务流程、算法顺序、性能和准确率的前提下，形成稳定 OpenAPI、Java/TypeScript SDK 和可选复核组件。

**Architecture:** 采用模块化单体与渐进式替换。Java 逐步成为任务、文件、状态、幂等、重试、批处理和标准题目包的唯一事实源；Python 保留 MinerU、视觉、版面、拆题、题图归属、公式和 AI 结果保护等准确率敏感 worker 能力。旧接口先由 façade 保持兼容，所有切换必须经过 golden corpus、shadow compare、性能门禁和 feature flag，禁止大爆炸式重写。

**Tech Stack:** Java 17、Spring Boot 3.3、MyBatis Plus、H2/MySQL、OkHttp、Python 3/FastAPI/MinerU/PIL/Pix2Text、React 18/TypeScript/Vite/Vitest、OpenAPI 3.0、OpenAPI Generator、Maven、npm。

**Planning basis:** `docs/architecture/CODE_STRUCTURE_PORTABILITY_REVIEW.md`、`docs/architecture/ENGINE_DELIVERY_BOUNDARY.md`、现有 OpenAPI/SDK 目录、Java/Python/前端代码审计及当前测试基线。

---

> **Evidence update — 2026-07-16 (Asia/Shanghai):** Phase 0 的内置 replay golden、benchmark 工具、配置契约和边界检查已有实现与本地验证证据；受控 20 份真实样卷、正式发布性能基线、Java 唯一事实源、SDK 正式发布、灰度/回滚、权限、题目版本、审核、MQ 和超时扫描器仍未完成。

## 0. 执行范围与硬性底线

本计划替换的是公司题库中的“题目采集和加工链路”，不是迁移整个 `local-platform`。

公司平台继续负责：

- 用户、租户、学校、权限和审计。
- 最终题库主表、题目版本、审核、发布和删除策略。
- 权威知识点、组卷、考试、作业等业务。
- 最终文件归档和下载权限。

OCR Flow Engine 只负责：

- 试卷/答案文件接收和 OCR 执行。
- 版面、拆题、小问、选项、题图和题图归属。
- Markdown/LaTeX 规范化、AI 标准化和 AI 解析。
- 人工复核所需的只读原文件定位和题目草稿接口。
- 输出兼容的 `question-package.v1`。

任何“代码整理”提交都不得同时修改以下行为：

- OCR 节点顺序、算法调用顺序、阈值、Prompt、fallback。
- LLM endpoint 顺序、缓存键、TTL、重试次数和并发默认值。
- 题目数量、题号顺序、父子题、小问、选项和题图归属。
- 风险题进入人工复核的条件。
- 单题/全局标准化的写回门禁。
- API 响应字段、轮询周期和现有 asset URL。

### 0.1 Java / Python 最终职责判定

| 归属 | 保留/迁移能力 | 原因 |
| --- | --- | --- |
| Java | 对外 API、Processing Task、题目草稿、revision、文件元数据、幂等、outbox、状态机、重试、批任务、回调、OpenAPI/SDK、发布与审计 | 事务、一致性、可恢复性和公司平台集成能力 |
| Python worker | MinerU/provider、PDF/Office/图片预处理、版面与 bbox、题目边界、小问/选项、题图归属、视觉修复、公式/Markdown、Prompt/响应保护、导出渲染 | 与模型/图像生态耦合，且直接影响识别准确率 |
| 条件式 Java | canonicalization preview | 仅在完整输入/输出契约冻结、20 份样卷逐字段 100% 一致和两个预发周期通过后切换 |
| 本计划不迁 | local-platform 的题库、知识点、组卷、权限、审核、最终入库 | 属于公司业务平台，不是 OCR Flow 核心技术 |

## 1. 总体阶段与依赖

```text
Phase 0  基线冻结和架构门禁
   ↓
Phase 1  Worker 契约、Port 和统一 Transport
   ↓
Phase 2  Python 原地无行为模块化
   ↓
Phase 3  Java 领域模型与任务唯一事实源
   ↓
Phase 4  单题/批处理后处理能力收敛
   ↓
Phase 5  OpenAPI、SDK 和复核前端模块
   ↓
Phase 6  条件式 Java 化、灰度、发布和兼容层退场
```

每个 Phase 是独立发布检查点。上一阶段的准确率、性能和回滚演练没有通过时，不得开始下一阶段。

## 2. 统一验收门禁

### 2.1 准确率与内容一致性

- normalized golden 中题目结构必须零差异。
- 题目数量、顺序、父题/小问关系必须完全一致。
- 选项标签、文本、顺序和图片必须完全一致。
- `images`、`imagePlacements`、人工覆盖和 review 原因必须完全一致。
- Markdown、LaTeX、答案、解析、warning 和 validation 不能丢失。
- LLM/OCR provider 调用数量和调用顺序必须完全一致。
- 新实现不得把原本的风险题自动应用。

### 2.2 性能门禁

- 以相同机器、相同数据、相同 provider 配置连续运行 5 次，去掉最高和最低值。
- p50 增幅超过 2%：警告并人工复核。
- p95 增幅超过 3%：阶段失败。
- 吞吐下降超过 3%：阶段失败。
- 峰值 RSS 增幅超过 5%：阶段失败。
- OCR/LLM 调用次数增加：直接失败，不使用耗时容差豁免。
- 前端切换不得增加轮询频率、重复请求或隐式双读。

### 2.3 兼容与回滚

- 每个任务独立提交，不跨阶段形成大提交。
- 先增加 façade/adapter，再迁调用方，最后删除旧实现。
- 所有新主链必须有 feature flag，默认关闭。
- shadow 只比较，不得写入正式题目。
- 数据库变更只能 additive；兼容期内不删表、不删列。
- 旧 API、旧 SDK façade 至少保留两个 MINOR 版本或 90 天，取时间更长者。
- `question-package.v1` 在本计划中保持版本不变。

## 3. 文件结构目标

### 3.1 Java 包边界

```text
backend/src/main/java/com/aigeneration/questionbank/ocrflow/
  contract/                    稳定内部 DTO 和错误模型
  domain/question/             统一题目、选项、小问和题图模型
  domain/job/                  Processing Job 状态与转换规则
  application/importflow/      创建、刷新、重扫、重试和结果摄取
  application/standardization/ 单题标准化 Use Case
  application/analysis/        单题解析 Use Case
  application/*/batch/         durable batch coordinator
  port/                        Worker、Repository、Storage ports
  adapter/worker/              Python worker HTTP adapter
  adapter/persistence/         MyBatis adapter 和 JSON codec
```

第一轮只建立包边界，不拆多个 Java 服务或多个仓库。

### 3.2 Python 包边界

```text
backend/python-worker/app/
  contracts/       worker v1 DTO、错误、manifest
  runtime/         配置、HTTP app、job/attempt store、flow state
  routes/          worker v1、system、export、legacy compatibility
  ocr/             provider、execution、output collection、pipeline
  ai/              runtime、router、boundary、standardization、analysis
  standardization/ cache、context、guards、service
  canonicalization/service.py
  legacy/          兼容期业务实现；最终删除
```

现有 `worker_base.py`、`ocr_processing.py`、`llm_splitter.py`、`import_services.py` 在迁移期保留显式兼容 façade。

### 3.3 对外交付物

```text
question-engine/openapi/question-engine.v1.yaml
question-engine/sdk/typescript/
question-engine/sdk/java/
question-engine/review-core/
question-engine/review-react/      可选
```

`local-platform` 只作为 SDK 和组件的端到端示例消费者。

---

## Phase 0：冻结行为、性能和边界

### Task 1：建立可归一化的 OCR Flow golden corpus

**Files:**

- Create: `tests/ocrflow-golden/manifest.json`
- Create: `tests/ocrflow-golden/gates.json`
- Create: `tests/ocrflow-golden/README.md`
- Create: `scripts/ocrflow_golden.py`
- Create: `scripts/test_ocrflow_golden.py`
- Modify: `.gitignore`
- Create: `backend/src/test/resources/golden/ocrflow/processing-job.json`
- Create: `backend/src/test/resources/golden/ocrflow/question-package.json`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/OcrFlowCompatibilityTest.java`

- [x] **Step 1: 写 comparator 的失败测试**

测试必须证明时间戳、traceId 和随机 jobId 会被归一化，而题目顺序、选项、图片和 placement 的任何变化都会失败：

```python
def test_compare_rejects_option_and_placement_changes():
    expected = {"questions": [{"id": "q1", "options": [{"label": "A", "content": "甲"}],
                               "imagePlacements": [{"imageId": "i1", "target": {"kind": "option", "optionLabel": "A"}}]}]}
    actual = {"questions": [{"id": "q1", "options": [{"label": "A", "content": "乙"}],
                             "imagePlacements": [{"imageId": "i1", "target": {"kind": "stem"}}]}]}
    differences = compare_payloads(expected, actual)
    assert "questions[0].options[0].content" in differences
    assert "questions[0].imagePlacements[0].target.kind" in differences
```

- [x] **Step 2: 运行测试并确认 RED**

```bash
python3 scripts/test_ocrflow_golden.py
```

Expected: import failure because `scripts/ocrflow_golden.py` does not exist.

2026-07-16 重建 RED 证据：在 `9b29c84^` 临时 worktree 中恢复 `9b29c84` 的 `scripts/test_ocrflow_golden.py`，退出码 1，匹配 `No module named.*ocrflow_golden|ModuleNotFoundError|ImportError|No such file.*ocrflow_golden`。

- [x] **Step 3: 实现 manifest 和归一化 comparator**

`manifest.json` 至少登记已脱敏的 Markdown 闭环样本：

```json
{
  "schemaVersion": "ocrflow-golden.v1",
  "cases": [
    {
      "id": "platform-markdown-basic",
      "paper": "docs/samples/platform-integration/paper.md",
      "answer": "docs/samples/platform-integration/answer.md",
      "expected": "docs/samples/platform-integration/expected-question-package.v1.json"
    }
  ]
}
```

Comparator 只归一化 `createdAt`、`updatedAt`、`startedAt`、`finishedAt`、`traceId` 和可配置随机 ID；数组顺序、字符串内容、图片目标、warning 和 validation 均不得忽略。

CLI 明确定义两种互斥 compare 模式，后续不得混用参数语义：

- `compare --manifest <manifest>`：按 manifest 运行当前实现（默认使用 case 的 `provider-output` replay），与每个 case 的 expected package 比较；供每个重构任务的准确率门禁使用。
- `compare --baseline <json> --candidate <json>`：只比较两个已捕获聚合产物；供 comparator 自测、历史报告复核和离线审计使用。

两种模式均生成机器可读 diff，参数缺失、同时传两种模式或受控发布 corpus 不完整时返回非零退出码。

- [x] **Step 4: 增加 Java 兼容性测试**

`OcrFlowCompatibilityTest` 读取冻结 JSON，通过现有 `QuestionProcessingCapabilityService` 生成结果并做递归比较。禁止使用只比较字段存在性的断言。

- [ ] **Step 5: 补齐真实样卷门禁**

在不提交敏感原卷的前提下，通过 `OCRFLOW_GOLDEN_ROOT` 加载至少 20 份脱敏或受控样卷，必须覆盖图片选项、跨页选项、复合题、小问题图、答案区重复题、表格、双栏、公式和页眉噪声。每个 case 固定采用 `case.json`、`paper/`、可选 `answer/`、`provider-output/`、`expected/question-package.json` 结构；实施负责人维护内容，发布负责人验证完整性和 SHA-256。受控根目录由 CI secret 或只读制品挂载提供，`.gitignore` 排除 `.artifacts/ocrflow-*` 和任何本地敏感副本。缺少该目录时本地单元测试可跳过，但发布验收不得跳过。

- [x] **Step 6: 运行测试并确认 GREEN**

```bash
python3 scripts/test_ocrflow_golden.py
mvn -q -f backend/pom.xml -Dtest=OcrFlowCompatibilityTest test
python3 scripts/ocrflow_golden.py capture \
  --manifest tests/ocrflow-golden/manifest.json \
  --mode replay \
  --output .artifacts/ocrflow-golden/baseline.json
python3 scripts/ocrflow_golden.py compare \
  --baseline .artifacts/ocrflow-golden/baseline.json \
  --candidate .artifacts/ocrflow-golden/baseline.json
```

Expected: all tests pass.

2026-07-16 验证结果：`python3 scripts/test_ocrflow_golden.py` 32 tests OK；`mvn -q -f backend/pom.xml -Dtest=OcrFlowCompatibilityTest test` 退出码 0；`ocrflow_golden.py capture --mode replay` 输出 `status=captured`；`ocrflow_golden.py compare --baseline ... --candidate ...` 输出 `status=equal`。受控样卷因 `OCRFLOW_GOLDEN_ROOT` 未配置仍按 Step 5 保持未完成。

- [x] **Step 7: Commit**

```bash
git add .gitignore tests/ocrflow-golden scripts/ocrflow_golden.py scripts/test_ocrflow_golden.py \
  backend/src/test/resources/golden/ocrflow \
  backend/src/test/java/com/aigeneration/questionbank/ocrflow/OcrFlowCompatibilityTest.java
git commit -m "test: freeze ocr flow compatibility baseline"
```

Historical commit: `9b29c84 test: freeze ocr flow compatibility baseline`.

### Task 2：建立性能、调用次数和配置基线

**Files:**

- Create: `scripts/benchmark_ocrflow.py`
- Create: `scripts/test_benchmark_ocrflow.py`
- Create: `tests/ocrflow-performance/baseline-ref.json`
- Create: `backend/python-worker/tests/test_worker_configuration_contract.py`
- Create: `docs/development/OCRFLOW_BASELINE.md`
- Modify: `tests/ocrflow-golden/gates.json`

- [x] **Step 1: 写配置契约测试**

锁定当前 `LLM_*_CONCURRENCY`、`LLM_*_MAX_ATTEMPTS`、`OCR_AUTO_*`、`OCR_VISUAL_REPAIR_*` 和 `MINERU_*` 默认值，并断言 `OCR_FLOW_STEP_DEFINITIONS` 的 id 与顺序。

- [x] **Step 2: 运行目标测试并保存当前失败/通过状态**

```bash
cd backend/python-worker
PYTHONPATH=. .venv/bin/python -m pytest tests/test_worker_configuration_contract.py -q -p no:cacheprovider
```

Expected: RED until the contract test and baseline fixture are complete.

2026-07-16 验证结果：`PYTHONPATH=backend/python-worker ... pytest backend/python-worker/tests/test_worker_configuration_contract.py -q -p no:cacheprovider` 为 3 passed。重建 RED 尝试显示该目标测试在 `a514eac^` + 恢复测试文件状态下已通过，因此记录当前通过状态，不伪造 RED。

- [x] **Step 3: 实现可归档、可恢复的 benchmark CLI**

CLI 提供 `baseline`、`archive`、`restore` 和 `compare` 子命令，必须输出 JSON，包含 `caseId`、`runs`、`p50Ms`、`p95Ms`、`throughputPerMinute`、`peakRssMb`、`ocrProviderCalls`、`llmProviderCalls`、`cacheHits` 和环境指纹。结构/准确率测试使用固定 `provider-output` replay，保证不受模型波动影响；性能测试使用固定 provider 配置的 live 环境并记录 provider/model/version。它只调用现有接口，不修改生产逻辑。

`archive` 把 baseline 以内容 SHA 命名写入只追加的 `OCRFLOW_BASELINE_PUBLISH_ROOT`，并生成可提交的 `tests/ocrflow-performance/baseline-ref.json`；ref 至少记录 artifact id、SHA-256、golden manifest SHA、provider/model/version、环境指纹和采集提交。已存在 artifact id 但 bytes 不同必须失败。`restore` 从发布/CI 注入的只读 `OCRFLOW_BASELINE_READ_ROOT` 读取该 artifact，逐项校验 ref 与实际 SHA、corpus 和环境指纹后恢复到 `.artifacts/ocrflow-baseline/current.json`；不得联网猜测“最近一次”基线，也不得在发布时现场重录。后续任务中的简写 `benchmark_ocrflow.py compare` 固定读取这个已恢复文件，运行 5 次生成 `.artifacts/ocrflow-baseline/candidate.json`，并自动使用 `tests/ocrflow-golden/gates.json`；任一文件缺失或指纹不匹配时必须失败，不能隐式跳过。

- [x] **Step 4: 固化双门槛**

`gates.json` 使用以下规则：

```json
{
  "warning": {"p50RatioMax": 1.02, "p95RatioMax": 1.00, "throughputRatioMin": 1.00},
  "failure": {"p95RatioMax": 1.03, "throughputRatioMin": 0.97, "peakRssRatioMax": 1.05},
  "providerCallDeltaMax": 0,
  "normalizedContentDiffMax": 0
}
```

- [x] **Step 5: 记录既有 router regression 差异**

当前 `scripts/regression_ocr_flow_router.py` 期待 `local → external`，而静态审计时现状只返回 `external`。先由 golden 与线上行为确认哪一个是有效基线；只能修正过期测试预期，不能为了通过脚本修改生产路由。

- [ ] **Step 6: 运行基线套件**

```bash
cd <repository-root>
python3 scripts/test_benchmark_ocrflow.py
./scripts/test_python_worker.sh
backend/python-worker/.venv/bin/python -m pytest backend/python-worker/tests -q -p no:cacheprovider
mvn -q -f backend/pom.xml test
npm --prefix local-platform test -- --run
npm --prefix local-platform run build
python3 scripts/benchmark_ocrflow.py baseline \
  --manifest tests/ocrflow-golden/manifest.json \
  --runs 5 \
  --output .artifacts/ocrflow-baseline/current.json
python3 scripts/benchmark_ocrflow.py archive \
  --input .artifacts/ocrflow-baseline/current.json \
  --store-root "$OCRFLOW_BASELINE_PUBLISH_ROOT" \
  --ref tests/ocrflow-performance/baseline-ref.json
python3 scripts/benchmark_ocrflow.py restore \
  --ref tests/ocrflow-performance/baseline-ref.json \
  --store-root "$OCRFLOW_BASELINE_READ_ROOT" \
  --output .artifacts/ocrflow-baseline/restored.json
python3 scripts/benchmark_ocrflow.py compare \
  --baseline .artifacts/ocrflow-baseline/restored.json \
  --candidate .artifacts/ocrflow-baseline/current.json \
  --gates tests/ocrflow-golden/gates.json
```

Expected baseline: Python pytest 至少保持当前 183 passed，unittest 至少保持当前 157 tests OK，Java 全量测试通过。

- [x] **Step 7: Commit**

```bash
git add scripts/benchmark_ocrflow.py scripts/test_benchmark_ocrflow.py \
  tests/ocrflow-performance/baseline-ref.json \
  backend/python-worker/tests/test_worker_configuration_contract.py \
  docs/development/OCRFLOW_BASELINE.md tests/ocrflow-golden/gates.json
git commit -m "test: add ocr flow performance gates"
```

Historical commit: `a514eac test: add ocr flow performance gates`. 正式 `tests/ocrflow-performance/baseline-ref.json` 仍为 `pending-controlled-baseline`，因此 Step 6 和 Phase 0 性能发布门禁保持未完成。

### Task 3：增加架构边界检查，禁止产生新的耦合

**Files:**

- Create: `config/ocrflow-boundaries.json`
- Create: `scripts/check_ocrflow_boundaries.py`
- Create: `scripts/test_check_ocrflow_boundaries.py`
- Modify: `scripts/check_project_portability.py`

- [x] **Step 1: 写失败测试**

测试临时源文件中的以下违规：Python worker 新增 `/api/question-bank`、Java `ocrflow` 包调用 Python `/api/**`、`review-core` 导入 React/DOM、worker 算法模块导入 `legacy`。

- [ ] **Step 2: 运行并确认 RED**

```bash
python3 scripts/test_check_ocrflow_boundaries.py
```

Expected: failure because the boundary checker does not exist.

- [x] **Step 3: 生成当前违规 allowlist**

`config/ocrflow-boundaries.json` 以“文件路径 + 稳定调用/路由模式”记录现有遗留依赖，不绑定会随编辑漂移的物理行号。Checker 必须满足“允许既有、禁止新增、allowlist 只能缩小”。不得把整个目录加入宽泛忽略列表。

- [x] **Step 4: 接入 portability check**

`check_project_portability.py` 调用 boundary checker，并在 allowlist 新增条目时失败。

- [x] **Step 5: 运行检查并确认 GREEN**

```bash
python3 scripts/test_check_ocrflow_boundaries.py
python3 scripts/check_ocrflow_boundaries.py
python3 scripts/check_project_portability.py
```

- [x] **Step 6: Commit**

```bash
git add config/ocrflow-boundaries.json scripts/check_ocrflow_boundaries.py \
  scripts/test_check_ocrflow_boundaries.py scripts/check_project_portability.py
git commit -m "test: enforce ocr flow module boundaries"
```

2026-07-16 验证结果：`test_check_ocrflow_boundaries.py` 46 tests OK；`check_ocrflow_boundaries.py` 输出 passed；`check_project_portability.py` 输出 passed。Historical commit: `afad3f8 test: enforce ocr flow module boundaries`。

### Phase 0 Exit Gate

- [ ] 20 份受控真实样卷 normalized golden 零差异。
- [ ] Python、Java、前端当前全量测试基线已记录。
- [ ] p50/p95、吞吐、RSS、provider 调用数已形成报告。
- [ ] router regression 的有效基线已由产品行为和线上证据确认。
- [ ] 未修改任何生产算法、阈值、Prompt 或状态逻辑。

---

## Phase 1：Worker 契约、Port 与唯一 Transport

### Task 4：定义 additive 的 Worker v1 契约

**Files:**

- Create: `question-engine/openapi/worker.v1.yaml`
- Create: `backend/python-worker/app/contracts/worker_v1.py`
- Create: `backend/python-worker/app/contracts/__init__.py`
- Create: `backend/python-worker/app/routes/worker_v1.py`
- Create: `backend/python-worker/app/routes/__init__.py`
- Create: `backend/python-worker/tests/test_worker_v1_contract.py`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/contract/WorkerModels.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/contract/WorkerModelsTest.java`
- Modify: `backend/python-worker/app/worker_base.py`
- Modify: `backend/python-worker/app/worker_routes.py`

- [ ] **Step 1: 写 Python/Java contract RED tests**

Python 测试提交 `schemaVersion`、`requestId`、`traceId`、`jobId`、`attemptId`、`inputSha256` 和 `pipelineVersion`，Java 测试对同一 fixture 反序列化再序列化，未知扩展字段必须保留。

- [ ] **Step 2: 定义统一 envelope**

Python Pydantic 模型：

```python
class WorkerRequestEnvelope(BaseModel):
    schemaVersion: Literal["worker-request.v1"] = "worker-request.v1"
    requestId: str
    traceId: str = ""
    jobId: str = ""
    attemptId: str = ""
    attemptNo: int = 0
    idempotencyKey: str = ""
    inputSha256: str = ""
    pipelineVersion: str
    payload: dict[str, Any]
```

Java 对应 record 必须使用 `@JsonAnySetter` 或显式 `extensions` 保留未知字段。

`WorkerModels` 在本任务中完整定义 `OcrCreateRequest/OcrJobAccepted/OcrJobSnapshot/OcrResult/RetryRequest`、预留但未发布 endpoint 的 `QuestionAssemblyRequest/QuestionAssemblyResponse`、`StandardizationRequest/StandardizationResponse`、`AnalysisRequest/AnalysisResponse`、`CanonicalizationRequest/CanonicalizationResponse`、`WorkerError` 和 artifact manifest；后续 Port 不再自行发明 Map 结构。Question assembly 的 OpenAPI path 与运行能力在 Task 9 同时发布，避免先出现一个有状态同名语义。

- [ ] **Step 3: 定义统一错误结构**

```json
{
  "code": "OCR_PROVIDER_TIMEOUT",
  "message": "provider timed out",
  "stage": "provider",
  "retryable": true,
  "requestId": "request-1",
  "jobId": "job-1",
  "attemptId": "attempt-1",
  "provider": "mineru",
  "details": {}
}
```

新增字段只能 additive；旧 `/worker/*` 和 `/api/*` 的响应保持原样。

- [ ] **Step 4: 新增 `/worker/v1/capabilities` 和 v1 wrapper**

第一轮 v1 路由只委托现有函数，至少提供 capabilities、OCR create/status/result/retry、canonicalization preview、standardize、analysis 和 export render。禁止在 wrapper 内复制算法。Question assembly 不在本任务发布，直到 Task 9 已完成无状态提取。

- [ ] **Step 5: 运行契约测试**

```bash
cd backend/python-worker
PYTHONPATH=. .venv/bin/python -m pytest tests/test_worker_v1_contract.py tests/test_ocr_flow.py -q -p no:cacheprovider
cd ../..
mvn -q -f backend/pom.xml -Dtest=WorkerModelsTest test
```

- [ ] **Step 6: 跑 golden 和 benchmark**

```bash
python3 scripts/ocrflow_golden.py compare --manifest tests/ocrflow-golden/manifest.json
python3 scripts/benchmark_ocrflow.py compare
```

Expected: normalized diff 0; provider call delta 0; performance gates pass.

- [ ] **Step 7: Commit**

```bash
git add question-engine/openapi/worker.v1.yaml backend/python-worker/app/contracts \
  backend/python-worker/app/routes/worker_v1.py backend/python-worker/tests/test_worker_v1_contract.py \
  backend/python-worker/app/worker_base.py backend/python-worker/app/worker_routes.py \
  backend/src/main/java/com/aigeneration/questionbank/ocrflow/contract \
  backend/src/test/java/com/aigeneration/questionbank/ocrflow/contract
git commit -m "feat: add versioned worker contract"
```

### Task 5：建立 Worker Ports 和唯一 Python HTTP Transport

**Files:**

- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/port/OcrWorkerPort.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/port/StandardizationWorkerPort.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/port/AnalysisWorkerPort.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/port/CanonicalizationWorkerPort.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/port/QuestionAssemblyWorkerPort.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/port/SourceRenderWorkerPort.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/port/WorkerRuntimePort.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/worker/PythonWorkerHttpTransport.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/worker/PythonOcrWorkerAdapter.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/worker/PythonAiWorkerAdapter.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/worker/PythonCanonicalizationWorkerAdapter.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/worker/PythonQuestionAssemblyWorkerAdapter.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/worker/PythonSourceRenderWorkerAdapter.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/adapter/worker/PythonWorkerHttpTransportTest.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/adapter/worker/PythonWorkerAdapterContractTest.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/PythonWorkerClient.java`

- [ ] **Step 1: 写 transport RED tests**

覆盖 method、URI、JSON、multipart 文件名、二进制响应头、4xx/5xx、超时和连接复用。测试服务器使用 JDK `HttpServer`，不增加新测试框架。

- [ ] **Step 2: 定义小型 Port**

```java
public interface StandardizationWorkerPort {
    WorkerModels.StandardizationResponse standardize(WorkerModels.StandardizationRequest request);
}

public interface OcrWorkerPort {
    WorkerModels.OcrJobAccepted create(WorkerModels.OcrCreateRequest request);
    WorkerModels.OcrJobSnapshot get(String jobId);
    WorkerModels.OcrResult getResult(String jobId);
    WorkerModels.OcrJobSnapshot retry(String jobId, WorkerModels.RetryRequest request);
}

public interface QuestionAssemblyWorkerPort {
    WorkerModels.QuestionAssemblyResponse assemble(WorkerModels.QuestionAssemblyRequest request);
}
```

`QuestionAssemblyWorkerPort` 和其 adapter 可以在本任务建立编译边界，但在 Task 9 之前不得注入生产调用链；其 contract test 只验证预定 method/path，不要求 worker 路由已可用。Port 不得返回 `ResponseEntity`、OkHttp `Response` 或 `Map<String,Object>`。

- [ ] **Step 3: 实现唯一 Transport**

`PythonWorkerHttpTransport` 统一 base URL、timeout、URI、JSON、multipart、文件响应、trace、错误映射和单例 OkHttpClient。不得改变当前各接口实际 timeout；先把现值显式传入 adapter。

- [ ] **Step 4: 让旧 Client 成为 façade**

`domain/service/PythonWorkerClient.java` 暂保留原公共方法和返回类型，内部委托新 Transport，保证旧调用方不同时改动。

- [ ] **Step 5: 逐个迁移 runtime 和 AI 调用点**

一个提交只迁一个调用方。优先顺序：runtime → canonicalization → AI → OCR → source render。`CallbackFlowService` 调的是外部回调，不属于本 Transport。

- [ ] **Step 6: 验证请求完全一致**

```bash
mvn -q -f backend/pom.xml \
  -Dtest=PythonWorkerHttpTransportTest,PythonWorkerAdapterContractTest,DomainControllerTest test
python3 scripts/ocrflow_golden.py compare --manifest tests/ocrflow-golden/manifest.json
```

- [ ] **Step 7: Commit**

```bash
git add backend/src/main/java/com/aigeneration/questionbank/ocrflow \
  backend/src/main/java/com/aigeneration/questionbank/domain/service/PythonWorkerClient.java \
  backend/src/test/java/com/aigeneration/questionbank/ocrflow
git commit -m "refactor: centralize python worker transport"
```

### Phase 1 Exit Gate

- [ ] 旧接口响应和请求 payload 逐字段一致。
- [ ] 所有新 OCR Flow Java 代码只依赖 Port，不依赖 OkHttp 或 Python URL。
- [ ] 新 v1 endpoint 仅是现有实现的 wrapper。
- [ ] golden、provider 调用数和性能门禁全部通过。

---

## Phase 2：Python Worker 原地无行为模块化

### Task 6：拆分 `worker_base.py`，保留兼容 façade

**Files:**

- Create: `backend/python-worker/app/runtime/config.py`
- Create: `backend/python-worker/app/runtime/__init__.py`
- Create: `backend/python-worker/app/runtime/http_app.py`
- Create: `backend/python-worker/app/runtime/job_store.py`
- Create: `backend/python-worker/app/runtime/ocr_flow_state.py`
- Create: `backend/python-worker/app/runtime/legacy_store.py`
- Create: `backend/python-worker/app/contracts/legacy_models.py`
- Create: `backend/python-worker/tests/test_worker_job_store.py`
- Create: `backend/python-worker/tests/test_worker_runtime.py`
- Modify: `backend/python-worker/app/worker_base.py`
- Modify: `backend/python-worker/app/worker_routes.py`

- [ ] **Step 1: 写 import identity 和状态顺序测试**

测试拆分前后的 `app`、锁、job store、provider registry 和 OCR flow 定义均为同一实例；禁止因 import 产生第二个缓存、锁或状态表。

- [ ] **Step 2: 按职责原样移动代码**

移动顺序：配置/路径 → DTO → OCR flow state → JSON job store → legacy store → job 创建/provider status。不得在移动时重命名 JSON 字段或改变 `.env` 加载时机。

- [ ] **Step 3: 将 `worker_base.py` 改为显式 façade**

只使用显式 re-export：

```python
from app.runtime.config import APP_ROOT, STORAGE_ROOT, OCR_JOBS_ROOT
from app.runtime.http_app import app
from app.runtime.job_store import load_ocr_job, save_ocr_job
from app.runtime.ocr_flow_state import OCR_FLOW_STEP_DEFINITIONS, update_ocr_flow_step
```

禁止再次使用 `import *`。

- [ ] **Step 4: 运行目标和全量测试**

```bash
cd backend/python-worker
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_worker_job_store.py tests/test_worker_runtime.py tests/test_ocr_flow.py -q -p no:cacheprovider
PYTHONPATH=. .venv/bin/python -m pytest tests -q -p no:cacheprovider
```

- [ ] **Step 5: 跑 golden/benchmark 并 Commit**

```bash
cd ../..
python3 scripts/ocrflow_golden.py compare --manifest tests/ocrflow-golden/manifest.json
python3 scripts/benchmark_ocrflow.py compare
git add backend/python-worker/app/runtime backend/python-worker/app/contracts/legacy_models.py \
  backend/python-worker/app/worker_base.py backend/python-worker/app/worker_routes.py \
  backend/python-worker/tests/test_worker_job_store.py backend/python-worker/tests/test_worker_runtime.py
git commit -m "refactor: split worker runtime foundations"
```

### Task 7：把 `ocr_processing.py` 提炼为唯一 pipeline 编排器

**Files:**

- Create: `backend/python-worker/app/ocr/structure_selection.py`
- Create: `backend/python-worker/app/ocr/__init__.py`
- Create: `backend/python-worker/app/ocr/output_collector.py`
- Create: `backend/python-worker/app/ocr/postprocess_pipeline.py`
- Create: `backend/python-worker/app/ocr/semantic_repair.py`
- Create: `backend/python-worker/tests/test_ocr_postprocess_pipeline.py`
- Modify: `backend/python-worker/app/ocr_processing.py`
- Modify: `backend/python-worker/app/ocr_execution.py`

- [ ] **Step 1: 写 pipeline 调用顺序测试**

使用 spies 锁定当前顺序：收集产物 → 本地边界 → 低置信 LLM → 候选选择 → 布局证据 → 题图校正 → 视觉修复 → legacy fallback → 数学规范化 → 可选语义修复 → manifest。

- [ ] **Step 2: 运行并确认 RED**

```bash
cd backend/python-worker
PYTHONPATH=. .venv/bin/python -m pytest tests/test_ocr_postprocess_pipeline.py -q -p no:cacheprovider
```

- [x] **Step 3: 先整体迁入 `OcrPostProcessingPipeline.run()`**

第一提交只包裹现有 `collect_outputs()`，不拆 helper；第二提交再按上述节点抽到四个模块。每次抽取都保持参数、返回结构和异常传播不变。

- [x] **Step 4: 保留 `ocr_processing.py` façade**

`collect_outputs(job_id)` 继续存在并直接调用单例 pipeline，旧测试和调用方不改签名。

- [ ] **Step 5: 验证**（Partial: focused/full Python tests 和服务器 smoke 已通过；受控 golden compare 与 benchmark compare 尚不能通过 `pending-controlled-baseline` 证明。）

```bash
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_ocr_processing.py tests/test_ocr_postprocess_pipeline.py \
  tests/test_question_boundary.py tests/test_question_layout.py \
  tests/test_image_placement.py tests/test_visual_repair.py -q -p no:cacheprovider
cd ../..
python3 scripts/ocrflow_golden.py compare --manifest tests/ocrflow-golden/manifest.json
python3 scripts/benchmark_ocrflow.py compare
```

- [x] **Step 6: Commit**

```bash
git add backend/python-worker/app/ocr backend/python-worker/app/ocr_processing.py \
  backend/python-worker/app/ocr_execution.py backend/python-worker/tests/test_ocr_postprocess_pipeline.py
git commit -m "refactor: extract ocr postprocess pipeline"
```

### Task 8：拆分 `llm_splitter.py`，确保只有一份运行时状态

**Files:**

- Create: `backend/python-worker/app/ai/runtime.py`
- Create: `backend/python-worker/app/ai/__init__.py`
- Create: `backend/python-worker/app/ai/router.py`
- Create: `backend/python-worker/app/ai/boundary.py`
- Create: `backend/python-worker/app/ai/standardization.py`
- Create: `backend/python-worker/app/ai/analysis.py`
- Create: `backend/python-worker/app/ai/enrichment.py`
- Create: `backend/python-worker/app/ai/normalization.py`
- Create: `backend/python-worker/tests/test_ai_module_parity.py`
- Modify: `backend/python-worker/app/llm_splitter.py`

- [ ] **Step 1: 写 transport/payload parity tests**

Mock HTTP transport，逐字段比较拆分前后的 endpoint 顺序、payload、timeout、retry、cache metadata、semaphore snapshot 和错误分类。

- [ ] **Step 2: 按低风险顺序移动**

先移动 normalization 和 payload builder，再移动 runtime/cache/semaphore/transport，然后移动 boundary，最后移动 standardization、analysis、enrichment。

- [ ] **Step 3: 保证单例唯一**

cache、endpoint semaphore、task semaphore 和 adaptive gate 只能在 `ai/runtime.py` 创建一次；各任务模块通过显式依赖引用，不得各自构造实例。

- [ ] **Step 4: 将 `llm_splitter.py` 缩为显式 façade**

保留所有当前公开函数名，使旧 import 不变。不得在这一任务中改 Prompt 文本、模型参数或 JSON 清洗规则。

- [ ] **Step 5: 验证**

```bash
cd backend/python-worker
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_ai_module_parity.py tests/test_llm_splitter.py \
  tests/test_adaptive_concurrency.py tests/test_ocr_processing.py -q -p no:cacheprovider
cd ../..
python3 scripts/ocrflow_golden.py compare --manifest tests/ocrflow-golden/manifest.json
python3 scripts/benchmark_ocrflow.py compare
```

- [ ] **Step 6: Commit**

```bash
git add backend/python-worker/app/ai backend/python-worker/app/llm_splitter.py \
  backend/python-worker/tests/test_ai_module_parity.py
git commit -m "refactor: split ai worker responsibilities"
```

### Task 9：拆分 `import_services.py`，隔离 worker 算法和 legacy 业务

**Files:**

- Create: `backend/python-worker/app/standardization/cache.py`
- Create: `backend/python-worker/app/standardization/__init__.py`
- Create: `backend/python-worker/app/standardization/context.py`
- Create: `backend/python-worker/app/standardization/guards.py`
- Create: `backend/python-worker/app/standardization/service.py`
- Create: `backend/python-worker/app/canonicalization/service.py`
- Create: `backend/python-worker/app/canonicalization/__init__.py`
- Create: `backend/python-worker/app/legacy/import_tasks.py`
- Create: `backend/python-worker/app/legacy/__init__.py`
- Create: `backend/python-worker/app/legacy/question_bank.py`
- Create: `backend/python-worker/app/legacy/papers.py`
- Create: `backend/python-worker/app/routes/compatibility_api.py`
- Create: `backend/python-worker/tests/test_standardization_module_parity.py`
- Create: `backend/python-worker/tests/test_question_assembly_worker.py`
- Modify: `question-engine/openapi/worker.v1.yaml`
- Modify: `backend/python-worker/app/import_services.py`
- Modify: `backend/python-worker/app/routes/worker_v1.py`

- [ ] **Step 1: 写标准化与 canonicalization parity tests**

覆盖 cache hit、OCR fallback、完整 tasks、图片选项、小问、严重 LaTeX、render validation、review reason 和候选写回建议。

- [ ] **Step 2: 原样移动 worker 算法**

保留：canonicalization preview、标准化缓存/保护、raw OCR context、候选生成/validation、Markdown/LaTeX 防损坏逻辑。

- [ ] **Step 3: 隔离 legacy 业务**

将 import task 同步、image library、question update、bank conversion、bank filter 和 paper selection/score 移到 `legacy/`。本任务不删除函数、不改变路由。

- [ ] **Step 4: 暴露无业务状态的题目组装命令**

在 `worker.v1.yaml` 中以 additive minor capability 新增 `QuestionAssemblyRequest/QuestionAssemblyResponse` 和 `POST /worker/v1/question-assemblies`，输入完整 `paperOcrResult`、可选 `answerOcrResult`、task options 和 pipeline version，输出 questions、paperLayout、canonicalization preview、warnings 和 metrics。它只能调用现有 `canonicalize_import_outputs()`、`build_import_questions()` 等已提取函数，不读取或写入 `library_store.json`。

测试必须把旧 `sync_import_task` 的输出与纯命令输出做 normalized 逐字段比较，覆盖试卷/答案合并、重复题、父子题和小问题图。

- [ ] **Step 5: 显式 façade 和 import 清理**

`import_services.py` 只显式 re-export；`worker_routes.py` 改成显式 import。全项目 `rg 'from app\..* import \*' backend/python-worker/app` 必须逐步归零。

- [ ] **Step 6: 验证**

```bash
cd backend/python-worker
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_standardization_module_parity.py tests/test_import_services.py \
  tests/test_question_assembly_worker.py tests/test_question_canonicalization.py \
  tests/test_question_markdown.py -q -p no:cacheprovider
PYTHONPATH=. .venv/bin/python -m pytest tests -q -p no:cacheprovider
cd ../..
python3 scripts/ocrflow_golden.py compare --manifest tests/ocrflow-golden/manifest.json
python3 scripts/benchmark_ocrflow.py compare
```

- [ ] **Step 7: Commit**

```bash
git add backend/python-worker/app/standardization backend/python-worker/app/canonicalization \
  backend/python-worker/app/legacy backend/python-worker/app/import_services.py \
  backend/python-worker/app/worker_routes.py backend/python-worker/app/routes/worker_v1.py \
  question-engine/openapi/worker.v1.yaml \
  backend/python-worker/app/routes/compatibility_api.py \
  backend/python-worker/tests/test_standardization_module_parity.py \
  backend/python-worker/tests/test_question_assembly_worker.py
git commit -m "refactor: isolate worker algorithms from legacy business"
```

### Task 10：增加 worker manifest 和 OCR attempt fencing

**Files:**

- Create: `backend/python-worker/app/runtime/worker_manifest.py`
- Create: `backend/python-worker/app/runtime/artifact_manifest.py`
- Create: `backend/python-worker/app/runtime/artifact_store.py`
- Create: `backend/python-worker/app/runtime/idempotency_store.py`
- Create: `backend/python-worker/tests/test_worker_manifest.py`
- Create: `backend/python-worker/tests/test_worker_attempt_fencing.py`
- Create: `backend/python-worker/tests/test_worker_artifact_store.py`
- Create: `backend/python-worker/tests/test_worker_idempotency.py`
- Modify: `backend/python-worker/app/runtime/job_store.py`
- Modify: `backend/python-worker/app/ocr_execution.py`
- Modify: `backend/python-worker/app/ocr_flow.py`
- Modify: `backend/python-worker/app/ocr_processing.py`
- Modify: `backend/python-worker/app/worker_routes.py`
- Modify: `backend/python-worker/app/contracts/worker_v1.py`
- Modify: `backend/python-worker/tests/test_worker_v1_contract.py`
- Modify: `question-engine/openapi/worker.v1.yaml`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/contract/WorkerModels.java`
- Modify: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/contract/WorkerModelsTest.java`

- [ ] **Step 1: 写 stale attempt 和 create crash-window RED tests**

覆盖：旧 attempt success/failed 不能覆盖新 attempt、连续 retry 只有最后一个可发布、worker 重启后恢复 active attempt、历史无 attempt 字段 job 可读、旧 asset URL 继续有效；相同 `idempotencyKey + inputSha256 + pipelineVersion` 的 create 必须返回同一 worker job，不得重复启动 provider。对 create 的每个持久化边界做 crash injection：reservation 落盘前、reservation 落盘后/provider enqueue 前、provider 已接受但 running 状态未落盘、running 后/HTTP 响应前。恢复后只能得到原 job、继续可证明尚未 enqueue 的 reservation，或进入 `uncertain/manual_review`，不能静默创建第二个 provider execution，也不能永久卡在无解释状态。

- [ ] **Step 2: 增加两类 manifest**

运行能力 manifest 包含 worker/contract/flow 版本和能力；attempt manifest 包含输入 SHA、provider/pipeline 版本、artifact 路径/SHA/大小/media type、result SHA 和时间信息。Manifest 放在 OCR 扫描目录之外，避免被主 JSON 选择逻辑误认。

- [ ] **Step 3: 实现单一 durable reservation 与 fencing 模型**

每次 create/retry 生成唯一 `attemptId` 和递增 `attemptNo`。Job 保存 `activeAttemptId`、`publishedAttemptId`；所有写入先在 job lock 内核对 active attempt。每个 attempt 使用隔离目录，只有 active attempt 成功后原子发布到兼容 `OUTPUT_ROOT/<jobId>`。

Create 幂等不能使用“先创建 job、再补 idempotency index”的两个独立事实。相同 `idempotencyKey + inputSha256 + pipelineVersion` 在同一个 job-store 临界区创建一条 durable reservation；reservation 本身同时保存确定性 `jobId`、request hash、attempt token 和 `reserved → submitting → running → completed|failed|uncertain` 状态，并在任何 provider enqueue 前以原子替换加 fsync 提交。不同 request hash 复用 key 返回 typed conflict；并发相同 key 只允许一个 owner 从 `reserved` 推进。

进入外部 provider 前先持久化 `submitting` 和稳定 provider request key。若 provider 支持原生幂等/按 request key 查询，重启后只用同 key 查询或重提并恢复原 job；若不支持，只有“尚未开始 enqueue”的 `reserved` 可自动继续，卡在 `submitting` 的记录必须转为 `uncertain/manual_review` 并禁止自动重跑。`running/completed` 重试只返回原 job。不得用删除 reservation 后重建来恢复。这样不宣称跨文件系统与外部 provider 的虚假原子事务，而是让每个半成品都有可证明的恢复路径。

这一状态必须进入 Worker v1 契约，而不是只存在 Python 内部：`OcrJobSnapshot` additive 返回 `executionState`、`retryAllowed`、`recoveryReason` 和稳定错误码 `OCR_EXECUTION_UNCERTAIN`；`uncertain` 固定 `retryAllowed=false`。Python/Java contract fixture 都覆盖旧响应缺字段、typed uncertain 和未知扩展字段，保证后续 Java owner 能识别并阻止换 key 自动重跑。

- [ ] **Step 4: 增加默认关闭开关**

`PYTHON_WORKER_ATTEMPT_FENCING_ENABLED=false` 保持旧行为。实现和测试通过不等于允许生产启用；生产从 `false` 改为 `true` 需要独立变更审批、基线比较和回滚窗口。灰度环境开启后，Java 仍消费同一公开结果路径。

- [ ] **Step 5: 验证并演练关闭开关**

```bash
cd backend/python-worker
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_worker_manifest.py tests/test_worker_attempt_fencing.py \
  tests/test_worker_artifact_store.py tests/test_worker_idempotency.py \
  tests/test_worker_v1_contract.py tests/test_ocr_processing.py -q -p no:cacheprovider
cd ../..
mvn -q -f backend/pom.xml -Dtest=WorkerModelsTest test
python3 scripts/ocrflow_golden.py compare --manifest tests/ocrflow-golden/manifest.json
PYTHON_WORKER_ATTEMPT_FENCING_ENABLED=false python3 scripts/benchmark_ocrflow.py compare
PYTHON_WORKER_ATTEMPT_FENCING_ENABLED=true python3 scripts/benchmark_ocrflow.py compare
```

- [ ] **Step 6: Commit**

```bash
git add backend/python-worker/app/runtime backend/python-worker/app/ocr_execution.py \
  backend/python-worker/app/ocr_flow.py backend/python-worker/app/ocr_processing.py \
  backend/python-worker/app/worker_routes.py backend/python-worker/tests/test_worker_manifest.py \
  backend/python-worker/tests/test_worker_attempt_fencing.py \
  backend/python-worker/tests/test_worker_artifact_store.py \
  backend/python-worker/tests/test_worker_idempotency.py \
  backend/python-worker/app/contracts/worker_v1.py backend/python-worker/tests/test_worker_v1_contract.py \
  question-engine/openapi/worker.v1.yaml \
  backend/src/main/java/com/aigeneration/questionbank/ocrflow/contract/WorkerModels.java \
  backend/src/test/java/com/aigeneration/questionbank/ocrflow/contract/WorkerModelsTest.java
git commit -m "feat: fence ocr worker attempts"
```

### Phase 2 Exit Gate

- [ ] Python 全量测试不少于当前基线，且 golden 零差异。
- [ ] `import *` 已从生产 worker 代码中清除。
- [ ] façade 仍保持旧函数签名和响应结构。
- [ ] `llm_splitter` 拆分后只有一份 cache/semaphore/adaptive gate。
- [ ] attempt fencing 默认关闭；开启/关闭分别通过 golden、并发发布、asset URL、性能和回滚演练。

---

## Phase 3：Java 领域模型、Repository 与唯一事实源

### Task 11：建立统一题目模型和 JSON round-trip codec

**Files:**

- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/domain/question/QuestionDocument.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/domain/question/QuestionOption.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/domain/question/SubQuestion.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/domain/question/QuestionImageRef.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/domain/question/ImagePlacement.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/domain/question/ImagePlacementTarget.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/domain/question/QuestionExtensionFields.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/persistence/QuestionEntityCodec.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/adapter/persistence/QuestionEntityCodecTest.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/capability/service/QuestionProcessingCapabilityService.java`

- [ ] **Step 1: 写 round-trip RED tests**

覆盖嵌套小问图片、placement、选项顺序、空字段和未知 Python 扩展字段。`decode → encode` 不得丢字段或重排数组。

- [ ] **Step 2: 实现不可变模型和 extensions**

模型不依赖 JPA/MyBatis、Spring、HTTP 或 Python DTO。未知字段保存在 `QuestionExtensionFields`，禁止只读后写回时丢失。

- [ ] **Step 3: 只做 shadow 题目包组装**

`QuestionProcessingCapabilityService` 同时生成旧/新题目包并在测试或诊断日志比较；公开响应仍返回旧结果。

- [ ] **Step 4: 验证**

```bash
mvn -q -f backend/pom.xml \
  -Dtest=QuestionEntityCodecTest,DomainControllerTest,OcrFlowCompatibilityTest test
python3 scripts/ocrflow_golden.py compare --manifest tests/ocrflow-golden/manifest.json
```

- [ ] **Step 5: Commit**

```bash
git add backend/src/main/java/com/aigeneration/questionbank/ocrflow/domain/question \
  backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/persistence/QuestionEntityCodec.java \
  backend/src/main/java/com/aigeneration/questionbank/capability/service/QuestionProcessingCapabilityService.java \
  backend/src/test/java/com/aigeneration/questionbank/ocrflow/adapter/persistence/QuestionEntityCodecTest.java
git commit -m "refactor: add stable question document model"
```

### Task 12：建立 Repository Port，保留现有表和 SQL

**Files:**

- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/port/QuestionRepository.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/port/ProcessingJobRepository.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/port/AiJobRepository.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/persistence/MyBatisQuestionRepository.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/persistence/MyBatisProcessingJobRepository.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/persistence/MyBatisAiJobRepository.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/adapter/persistence/QuestionRepositoryTest.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/adapter/persistence/ProcessingJobRepositoryTest.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportQuestionSyncService.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportTaskMetadataService.java`

- [ ] **Step 1: 写 Repository 语义测试**

锁定排序、按 task 查询、删除、图片关联、raw JSON 和事务边界。

- [ ] **Step 2: 实现 adapter**

复用当前 Mapper、表和 SQL，不在本任务拆 JSON 列或引入新 ORM。

- [ ] **Step 3: 把现有 Service 改为 façade**

`ImportQuestionSyncService` 和 `ImportTaskMetadataService` 保留公共签名，内部委托 repository。Controller 不更名。

- [ ] **Step 4: 验证和 Commit**

```bash
mvn -q -f backend/pom.xml \
  -Dtest=QuestionRepositoryTest,ProcessingJobRepositoryTest,DomainControllerTest test
git add backend/src/main/java/com/aigeneration/questionbank/ocrflow/port \
  backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/persistence \
  backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportQuestionSyncService.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportTaskMetadataService.java \
  backend/src/test/java/com/aigeneration/questionbank/ocrflow/adapter/persistence
git commit -m "refactor: add ocr flow repository ports"
```

### Task 13：收口 File Flow 和 AI 图片上下文

**Files:**

- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/port/FileStoragePort.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/file/SourceFileService.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/file/QuestionImageService.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/file/AiImageContextAssembler.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/file/SourceFileServiceTest.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/file/AiImageContextAssemblerTest.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/JavaFileStorageService.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/QuestionImageFlowService.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/AiFlowOrchestrationService.java`

- [ ] **Step 1: 写字节和图片顺序测试**

锁定 Content-Type、Content-Disposition、中文文件名、AI 图片顺序、当前 6 张上限和单张 8 MiB 限制。

- [ ] **Step 2: 让现有 Storage 实现 Port**

本任务不移动文件、不更换 provider、不改变 MinIO/LOCAL 选择。

- [ ] **Step 3: 提取 AI 图片 assembler**

从 `AiFlowOrchestrationService` 原样移动 MIME、大小、数量、data URL 和历史 Python 图片回退逻辑。

- [ ] **Step 4: 验证和 Commit**

```bash
mvn -q -f backend/pom.xml \
  -Dtest=AiImageContextAssemblerTest,SourceFileServiceTest,DomainControllerTest test
git add backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/file \
  backend/src/main/java/com/aigeneration/questionbank/ocrflow/port/FileStoragePort.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/service/JavaFileStorageService.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/service/QuestionImageFlowService.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/service/AiFlowOrchestrationService.java \
  backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/file
git commit -m "refactor: isolate ocr file flow"
```

### Task 14：让 Java 成为 Processing Task 唯一事实源

**Files:**

- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/importflow/CreateProcessingJobUseCase.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/importflow/GetProcessingJobUseCase.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/importflow/RefreshOcrExecutionUseCase.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/importflow/RetryOcrExecutionUseCase.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/importflow/OcrResultIngestionService.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/importflow/ProcessingStatusPolicy.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/importflow/WorkerDispatchCoordinator.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/domain/job/ProcessingJob.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/domain/job/ProcessingStatus.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/domain/job/WorkerDispatch.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/domain/entity/WorkerDispatchEntity.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/domain/mapper/WorkerDispatchMapper.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/importflow/CreateProcessingJobUseCaseTest.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/importflow/OcrResultIngestionServiceTest.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/importflow/WorkerDispatchCoordinatorTest.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/importflow/ProcessingJobOwnershipIntegrationTest.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/capability/service/QuestionProcessingCapabilityService.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportTaskMetadataBridgeService.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/entity/ImportTaskEntity.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/mapper/ImportTaskMapper.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/worker/PythonOcrWorkerAdapter.java`
- Modify: `backend/src/main/resources/schema.sql`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/migration/SchemaMigrator.java`
- Modify: `backend/src/main/resources/application.yml`

- [ ] **Step 1: 写 ownership RED tests**

测试关闭 Python `/api/import-tasks` 后，Java 仍能创建 task、保存文件、投递 paper/answer OCR、摄取结果、保存题目并恢复状态。创建入口覆盖 `Idempotency-Key`：响应丢失后以相同 caller/key/request hash 重试返回同一 task，相同 key 但不同文件或 metadata hash 返回 conflict。还必须模拟五个崩溃点：临时文件写入中断、最终对象已发布但数据库事务失败、dispatch 已提交但 HTTP 未发、HTTP 成功但 workerJobId 未落库、结果摄取中途失败；每种情况均能清理或幂等恢复，且数据库绝不能引用未完成文件。

- [ ] **Step 2: 增加三态迁移开关**

```yaml
ocrflow:
  migration:
    java-task-owner: legacy
```

允许值仅为 `legacy`、`shadow`、`java`。`shadow` 不写正式题目；`java` 才使用新主链。

本任务即对 `java_import_tasks` additive 增加 `ocrflow_owner VARCHAR(20) NOT NULL DEFAULT 'legacy'` 和 `rollout_config_version VARCHAR(80)`。创建任务时读取一次开关、把最终 owner 持久化；刷新、回调、重试、结果摄取都只读取任务已保存的 owner，不重新按当前配置判断。历史任务 migration 统一回填 `legacy`。因此即使部署期间配置变化，执行中的任务也不会换链；Task 25 只在这个既有粘滞字段之上增加百分比分流。

- [ ] **Step 3: 增加 durable dispatch/outbox**

新增 `java_worker_dispatches`，字段至少包含 `id/task_id/kind/input_sha256/pipeline_version/attempt_no/idempotency_key/status/worker_job_id/lease_owner/lease_expires_at/next_attempt_at/last_error/created_at/updated_at`，并建立唯一约束 `(task_id, kind, input_sha256, pipeline_version, attempt_no)`；paper、answer 和 assembly 都使用显式 kind。状态机冻结为 `queued → leased → submitted → acknowledged`，transport 失败从 `leased → retry_wait → leased`，达到只针对“同 idempotency key 提交”的最大 transport attempt 后进入 `dead`；不得把 dispatch retry 解释成重新执行 OCR provider。领取必须是单条条件更新，只允许 queued 或到期 retry_wait 且 lease 已过期的行；双实例、过期 lease、late submit 和 dead 不得复活均有测试。

同时对 `java_import_tasks` additive 增加 `processing_version BIGINT NOT NULL DEFAULT 0`、可空的 `caller_scope/create_idempotency_key/create_request_sha256`，对非空 `(caller_scope, create_idempotency_key)` 建立唯一约束。request SHA 由 paper/answer bytes SHA、稳定 metadata 和 pipeline version 计算；提供 key 时，相同 key/hash 读取原 task 和原 dispatch，不创建新 task，相同 key/不同 hash 返回 conflict。为保持旧调用兼容，未提供 key 时仍按现有语义创建新 task；官方新 SDK 始终发送 key。所有状态推进都以 `taskId + expected status + processing_version` 做单条 CAS 更新，禁止旧 callback、并发 refresh 或 retry 把终态回退。

创建任务时先流式写临时对象并计算 SHA-256，再使用由 `taskId + kind + sha256` 推导的确定性 final key 发布并回读校验；只有 final object 已 READY 后，才在一个数据库事务内保存 storage metadata、task 和 queued dispatch。数据库事务失败时 best-effort 删除本次无人引用的 final object；若清理失败只留下可按 deterministic key 审计/回收的 orphan，绝不能留下数据库悬空引用。相同 task/input 重试直接复用已校验的 final object，不重复上传。Coordinator 只能为 READY 文件提交 worker。

Coordinator 提交 worker 时使用持久 idempotency key；HTTP 成功但数据库更新失败时，重试必须由 worker 返回同一 job。`java` 模式启动前必须从 `/worker/v1/capabilities` 验证 `ocrCreateIdempotency=true`；若 Task 10 的 attempt fencing/idempotency 未经独立审批开启，切换必须 fail-closed 并继续保持 `legacy`，不能以“通常不会崩溃”为理由放行。测试必须覆盖两个实例同时领取 dispatch、callback 与 retry 竞争、旧版本状态提交和终态重复通知。

`PythonOcrWorkerAdapter` 必须把 Task 10 的 typed `OCR_EXECUTION_UNCERTAIN` 映射为 Java dispatch 的 additive `uncertain/manual_review` 终止态，并让 `ProcessingStatusPolicy` 投影到现有人工复核语义；不得按 transport failure、`retry_wait` 或 `dead` 处理。`RetryOcrExecutionUseCase` 对该状态默认拒绝自动 retry 和换 idempotency key 重跑；只有操作员先完成 provider reconciliation，或显式创建带审计原因的新 attempt，才能继续。状态和原因必须进入 job snapshot/运维审计。测试覆盖 Java 反序列化、状态投影、自动 retry 被拒绝、进程重启后仍被拒绝，以及显式人工裁决；不得通过吞掉未知 enum 回退成普通失败。

- [ ] **Step 4: 实现 Java 主链**

Java 先生成 task ID、保存文件和任务，再分别提交 paper/answer worker job；两个 OCR 结果完成后，通过 `QuestionAssemblyWorkerPort` 调用纯题目组装命令，最后由 Java 摄取 questions、layout、canonicalization 和 warnings。Worker job 只是 execution evidence；`java_import_tasks` 与 `java_import_questions` 是业务事实源。复用现有表，`raw_json` 只作为兼容快照。`shadow` 只复用 legacy 已产生的 worker request/result 事件来运行 planner 和 ingestion compare，禁止再次 create OCR job 或调用 provider；正式数据仍由 legacy 写入。

- [ ] **Step 5: 保留 Bridge façade**

现有 Controller 和 API 路径不变。Bridge 根据开关委托旧路径或新 Use Case，不允许长期双写。

- [ ] **Step 6: shadow 与 java 模式验证**

```bash
mvn -q -f backend/pom.xml \
  -Dtest=CreateProcessingJobUseCaseTest,OcrResultIngestionServiceTest,WorkerDispatchCoordinatorTest,ProcessingJobOwnershipIntegrationTest,DomainControllerTest test
python3 scripts/ocrflow_golden.py compare --manifest tests/ocrflow-golden/manifest.json
python3 scripts/benchmark_ocrflow.py compare
```

- [ ] **Step 7: Commit**

```bash
git add backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/importflow \
  backend/src/main/java/com/aigeneration/questionbank/ocrflow/domain/job \
  backend/src/main/java/com/aigeneration/questionbank/capability/service/QuestionProcessingCapabilityService.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportTaskMetadataBridgeService.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/entity/ImportTaskEntity.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/mapper/ImportTaskMapper.java \
  backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/worker/PythonOcrWorkerAdapter.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/entity/WorkerDispatchEntity.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/mapper/WorkerDispatchMapper.java \
  backend/src/main/resources/schema.sql backend/src/main/java/com/aigeneration/questionbank/migration/SchemaMigrator.java \
  backend/src/main/resources/application.yml \
  backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/importflow
git commit -m "feat: add java-owned processing job path"
```

### Phase 3 Exit Gate

- [ ] `java-task-owner=legacy` 与当前行为完全一致。
- [ ] `shadow` 零正式写入、零新增 provider 调用且逐字段比较通过。
- [ ] `java` 模式下关闭 Python import-task 业务接口仍能完整加工。
- [ ] `java` 模式只在 worker 明确宣告并通过 OCR create idempotency/fencing 门禁后可启用。
- [ ] Java 服务重启后任务、题目、题图和状态完整恢复。
- [ ] 文件提交与 dispatch/outbox 在五个崩溃点均能幂等恢复，不产生悬空文件引用或重复 provider 执行。
- [ ] 创建任务响应丢失重试返回同一 task；outbox 状态机、CAS lease、dead 和 assembly 唯一键测试通过。
- [ ] Python `library_store.json` 不再产生新任务业务写入。

---

## Phase 4：后处理 Use Case 与 durable batch 收敛

### Task 15：抽取单题标准化 Use Case

**Files:**

- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/standardization/StandardizeQuestionUseCase.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/standardization/StandardizationCommand.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/standardization/StandardizationResult.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/standardization/StandardizationContextAssembler.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/standardization/StandardizationWritePolicy.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/standardization/StandardizeQuestionUseCaseTest.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/standardization/StandardizationWritePolicyTest.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/AiFlowOrchestrationService.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/StandardizationRequestFactory.java`

- [ ] **Step 1: 写行为 parity tests**

覆盖 candidate、safe-to-apply、review-required、stale input、严重 LaTeX、render validation、applyBlocked 和 writeSkipped。

- [ ] **Step 2: 原样移动上下文与写回策略**

保留 `StandardizationRequestFactory` 当前字段和 input hash。不得在本任务统一 `standardization.v2` 与批缓存 `standardizer-v1` 指纹，因为这会改变缓存命中和模型调用数。

- [ ] **Step 3: 让旧 AI Service 成为 façade**

`standardizeImportQuestion()` 委托 Use Case；bank/ad-hoc 入口暂留 local-platform 兼容 adapter，不进入核心 OCR Flow 公共接口。

- [ ] **Step 4: 验证并 Commit**

```bash
mvn -q -f backend/pom.xml \
  -Dtest=StandardizeQuestionUseCaseTest,StandardizationWritePolicyTest,StandardizationRequestFactoryTest,DomainControllerTest test
python3 scripts/ocrflow_golden.py compare --manifest tests/ocrflow-golden/manifest.json
git add backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/standardization \
  backend/src/main/java/com/aigeneration/questionbank/domain/service/AiFlowOrchestrationService.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/service/StandardizationRequestFactory.java \
  backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/standardization
git commit -m "refactor: extract single standardization use case"
```

### Task 16：让全局标准化只调单题 Use Case

**Files:**

- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/standardization/batch/StandardizationBatchCoordinator.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/standardization/batch/StandardizationBatchItemRunner.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/standardization/batch/StandardizationBatchProgressMapper.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/standardization/batch/StandardizationBatchFingerprint.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/standardization/batch/StandardizationBatchParityTest.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/StandardizationBatchService.java`

- [ ] **Step 1: 写 single/global request parity test**

同一题的单题和全局路径发给 worker 的业务 request 必须一致；仅 `requestSource`、调度元数据和写回意图可以不同。

- [ ] **Step 2: 原样提取批调度**

保留 executor、maxConcurrency、2s/5s retry delay、取消、恢复、缓存和统计。Item runner 只能调用 `StandardizeQuestionUseCase`。本任务仍沿用当前单 Java coordinator 部署约束；在 Task 18 补齐数据库 lease 和跨 HTTP result idempotency 前，运行检查必须拒绝第二个 coordinator 实例，不能把“代码已拆分”误当作可横向扩容。

- [ ] **Step 3: 隔离现有 fingerprint**

把当前批缓存算法原样放进 `StandardizationBatchFingerprint`，不与单题 hash 合并。

- [ ] **Step 4: 单独确认 `retryFailed()` 疑点**

先补“重置后是否实际执行”的测试。若证明缺陷，另开 bugfix 计划和提交；本重构任务只保持当前行为，不顺手修复，但 Phase 5 SDK 不得公开/推荐 `retryFailed`，直到该测试给出明确通过结论或独立 bugfix 已验收。

- [ ] **Step 5: 验证并 Commit**

```bash
mvn -q -f backend/pom.xml \
  -Dtest=StandardizationBatchServiceTest,StandardizationBatchParityTest,StandardizeQuestionUseCaseTest test
python3 scripts/benchmark_ocrflow.py compare
git add backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/standardization/batch \
  backend/src/main/java/com/aigeneration/questionbank/domain/service/StandardizationBatchService.java \
  backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/standardization/batch
git commit -m "refactor: delegate global standardization to single use case"
```

### Task 17：抽取单题 AI 解析 Use Case

**Files:**

- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/analysis/AnalyzeQuestionUseCase.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/analysis/GenerateAnalysisCandidateUseCase.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/analysis/AnalysisCommand.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/analysis/AnalysisResult.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/analysis/AnalysisCandidate.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/analysis/AnalysisRequestFactory.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/analysis/AnalysisContextAssembler.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/analysis/AnalyzeQuestionUseCaseTest.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/AiFlowOrchestrationService.java`

- [ ] **Step 1: 写当前写回行为测试**

锁定普通题、小问、题图、已知答案、知识点、AI job 和成功后直接写回答案/解析的当前行为。

- [ ] **Step 2: 原样提取，并在内部拆开“生成候选/应用候选”**

`GenerateAnalysisCandidateUseCase` 只组装上下文、调用现有 AI 链并返回 `AnalysisCandidate`；允许保留现有 AI job 审计记录，但不得写 `java_import_questions`、图片树或题目 revision。`AnalyzeQuestionUseCase` 继续按当前顺序调用“生成候选 → 应用候选”，所以旧 API 的成功写回、失败语义和 provider 调用数不变。本阶段不增加 stale-input、新置信度门禁或人工确认，因为这些会改变现有行为。

- [ ] **Step 3: 用测试证明候选调用不写题，旧调用仍写题**

候选测试在调用前后比较题目行、图片树、`updatedAt` 和 raw JSON；旧 `AnalyzeQuestionUseCase` 测试继续断言答案、解析及 children 汇总被写回。两种路径复用同一个请求工厂和 AI transport，不复制 Prompt 或解析逻辑。revision 字段在紧随其后的 Task 18A 以 additive migration 引入后，再纳入候选无写入断言。

- [ ] **Step 4: 让旧 Service 成为 façade**

导入题解析委托 Use Case；bank/ad-hoc 暂留兼容 adapter。

- [ ] **Step 5: 验证并 Commit**

```bash
mvn -q -f backend/pom.xml -Dtest=AnalyzeQuestionUseCaseTest,DomainControllerTest test
python3 scripts/ocrflow_golden.py compare --manifest tests/ocrflow-golden/manifest.json
git add backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/analysis \
  backend/src/main/java/com/aigeneration/questionbank/domain/service/AiFlowOrchestrationService.java \
  backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/analysis
git commit -m "refactor: extract single analysis use case"
```

### Task 18A：在 durable batch 前建立题目 revision CAS 与 no-op replay

**Files:**

- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/error/QuestionRevisionConflictException.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/revision/QuestionRevisionPolicy.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/revision/QuestionRevisionPolicyTest.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/adapter/persistence/QuestionRevisionConcurrencyTest.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/adapter/persistence/QuestionRevisionMutationTest.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/entity/ImportQuestionEntity.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/mapper/ImportQuestionMapper.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportQuestionSyncService.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportTaskMetadataBridgeService.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/AiFlowOrchestrationService.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/QuestionImageFlowService.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/standardization/StandardizeQuestionUseCase.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/analysis/AnalyzeQuestionUseCase.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/analysis/GenerateAnalysisCandidateUseCase.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/port/QuestionRepository.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/persistence/MyBatisQuestionRepository.java`
- Modify: `backend/src/main/resources/schema.sql`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/migration/SchemaMigrator.java`

- [ ] **Step 1: 增加 revision 与稳定内容 hash**

对 `java_import_questions` additive 增加 `revision BIGINT NOT NULL DEFAULT 0` 和 `revision_content_sha256 VARCHAR(64)`。`QuestionRevisionPolicy` 对 type/status、stem/manual Markdown、answer/analysis、options/children、images/placements、difficulty/score、知识点和 math validation 生成稳定 hash；对象 key 排序但数组不排序，忽略 updatedAt、trace、AI job 和纯执行证据。

- [ ] **Step 2: 建立真实数据库 CAS**

`QuestionRepository.updateDraft(questionId, expectedRevision, patch)` 在短事务内锁定当前行、合并 patch 并计算新 hash，再以 `WHERE id = ? AND revision = ?` 更新；零行时区分 not-found 与 `QuestionRevisionConflictException`。事务外“先查再 updateById”禁止作为 CAS。

- [ ] **Step 3: 所有实质写入推进 revision，相同重放不推进**

旧保存、worker sync、题图更新、标准化 apply、解析 apply 和新 repository 保存都走同一 policy。新 hash 不同才在同一事务内 `revision+1`；相同 worker payload 重放、只读 refresh/轮询、候选生成和失败 AI job不得推进。旧 API 不新增 expectedRevision，业务响应和覆盖行为保持不变。

- [ ] **Step 4: 用真实调用链验证**

测试两个相同 expected revision 的并发更新只成功一个；旧保存/worker sync/题图/两类 AI apply 后旧 revision 失效；相同 worker result 连续摄取两次只推进一次；两类 candidate 不写题、不推进 revision。

- [ ] **Step 5: 验证并 Commit**

```bash
mvn -q -f backend/pom.xml \
  -Dtest=QuestionRevisionPolicyTest,QuestionRevisionConcurrencyTest,QuestionRevisionMutationTest,StandardizeQuestionUseCaseTest,AnalyzeQuestionUseCaseTest test
git add backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/error \
  backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/revision \
  backend/src/main/java/com/aigeneration/questionbank/ocrflow/port/QuestionRepository.java \
  backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/persistence/MyBatisQuestionRepository.java \
  backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/standardization/StandardizeQuestionUseCase.java \
  backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/analysis \
  backend/src/main/java/com/aigeneration/questionbank/domain/entity/ImportQuestionEntity.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/mapper/ImportQuestionMapper.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportQuestionSyncService.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportTaskMetadataBridgeService.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/service/AiFlowOrchestrationService.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/service/QuestionImageFlowService.java \
  backend/src/main/resources/schema.sql backend/src/main/java/com/aigeneration/questionbank/migration/SchemaMigrator.java \
  backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/revision \
  backend/src/test/java/com/aigeneration/questionbank/ocrflow/adapter/persistence/QuestionRevision*Test.java
git commit -m "feat: add revision-safe question mutations"
```

### Task 18：把“AI 解析全部”迁为 Java durable batch

**Files:**

- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/analysis/batch/AnalysisBatchService.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/analysis/batch/AnalysisBatchPlanner.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/analysis/batch/AnalysisBatchCoordinator.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/analysis/batch/AnalysisBatchItemRunner.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/ai/execution/AiExecutionResultAcknowledgementCoordinator.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/analysis/batch/AnalysisExecutionGuard.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/domain/controller/AnalysisExecutionSessionController.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/analysis/batch/SubQuestionAnalysisAccumulator.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/domain/entity/AnalysisBatchJobEntity.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/domain/entity/AnalysisBatchItemEntity.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/domain/entity/AnalysisExecutionLockEntity.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/domain/mapper/AnalysisBatchJobMapper.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/domain/mapper/AnalysisBatchItemMapper.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/domain/mapper/AnalysisExecutionLockMapper.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/domain/controller/AnalysisBatchController.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/analysis/batch/AnalysisBatchPlannerTest.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/analysis/batch/AnalysisBatchServiceTest.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/analysis/batch/AnalysisBatchRecoveryTest.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/ai/execution/AiExecutionResultAcknowledgementCoordinatorTest.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/analysis/batch/AnalysisExecutionGuardTest.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/analysis/batch/LegacyAnalysisSessionIntegrationTest.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/standardization/batch/StandardizationBatchMultiInstanceTest.java`
- Create: `local-platform/src/components/question-bank/ImportWorkbenchTask.analysis-session.test.tsx`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/entity/AiJobEntity.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/mapper/AiJobMapper.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/entity/StandardizationBatchItemEntity.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/mapper/StandardizationBatchItemMapper.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/StandardizationBatchService.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/controller/AiFlowController.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/AiFlowOrchestrationService.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/controller/ImportTaskMetadataBridgeController.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportTaskMetadataBridgeService.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/analysis/AnalyzeQuestionUseCase.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/port/WorkerRuntimePort.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/worker/PythonWorkerHttpTransport.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/contract/WorkerModels.java`
- Modify: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/contract/WorkerModelsTest.java`
- Modify: `backend/src/main/resources/application.yml`
- Modify: `backend/python-worker/app/contracts/worker_v1.py`
- Modify: `backend/python-worker/app/runtime/idempotency_store.py`
- Modify: `backend/python-worker/app/routes/worker_v1.py`
- Modify: `backend/python-worker/tests/test_worker_idempotency.py`
- Modify: `backend/python-worker/tests/test_worker_v1_contract.py`
- Modify: `question-engine/openapi/worker.v1.yaml`
- Modify: `backend/src/main/resources/schema.sql`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/migration/SchemaMigrator.java`
- Modify: `local-platform/src/lib/api.ts`
- Modify: `local-platform/src/components/question-bank/ImportWorkbenchTask.tsx`

- [ ] **Step 1: 写前端旧流程 parity tests**

锁定：排除已入库题、仅补空/覆盖模式、复合题按小问、无自动重试、单项失败继续、同一父题小问最终汇总保存。

- [ ] **Step 2: 增加 additive 表、execution lease 和跨 HTTP 幂等结果**

`java_analysis_batch_jobs` 和 `java_analysis_batch_items` 保存 question、target kind、sub-question index、input hash、`expected_revision`、status、response JSON、attempt、idempotency key、lease owner、lease expires at、result hash 和 `applied_at`。`java_ai_jobs` additive 增加 `input_hash/idempotency_key` 并建立唯一约束，重试复用同一 AI job。第一版 `maxConcurrency=1`，与当前浏览器顺序一致。领取 item 使用数据库 CAS lease；进程重启只能接管 lease 已过期的项，同一 idempotency key 的已完成结果不得再次调用 worker。

对带 v1 envelope idempotency key 的 `/worker/v1/ai/analysis` 和 `/worker/v1/ai/standardize` 启用同一 durable execution-result 状态机：key 同时绑定 operation、input SHA 和 pipeline version；记录至少有 `reserved → running → completed|failed|uncertain → acknowledged|tombstone`、owner token、fencing generation、lease/heartbeat、provider request key、response hash/response。请求必须先原子抢占并持久化 `reserved/running` 再调用 provider；并发同 key 只能由一个 owner 调用，其余请求等待已有执行或返回 typed `AI_EXECUTION_ACTIVE`，不能各自调用 provider。完成写入必须校验 owner/generation，Python 在 provider 成功后先以原子替换持久化完整 response hash/response，再返回 HTTP。

必须明确承认 provider 返回与 `completed` 落盘之间无法凭本地缓存实现 exactly-once：若 provider 支持原生 idempotency key/结果查询，恢复只能以原 provider request key查询或重提；若不支持，`running` owner 失联或 lease 到期一律转为 `uncertain/manual_review`，禁止自动再次调用 provider。Java 收到 `uncertain` 后把 item 置人工复核，不得换 key 重跑。Java 在“worker 已持久化 completed、但 Java DB 未提交”后用原 key 重试时必须拿到同一缓存结果。key 相同但 input hash 不同返回 typed conflict。旧 `/worker/ai/**` 和未带 key 的请求保持现状。worker 结果是可过期的执行证据，不是题目事实源；保留时长必须覆盖最大 batch 恢复窗口，清理不能早于 Java item 终态。测试覆盖并发同 key、等待方超时重试、provider 返回后/结果落盘前崩溃、worker 重启、无原生 provider idempotency 时进入 uncertain 且 provider 调用数不增加。

同一任务内把现有 standardization batch item additive 增加 `idempotency_key/result_hash/lease_owner/lease_generation/lease_expires_at`。领取以单条数据库 CAS 分配递增 generation，runner 按小于 lease 1/3 的周期 heartbeat；题目 apply、result hash 和 item success/failed 必须在同一事务内按 `itemId + owner + generation` 再做终态 fencing CAS。lease 已失效的 runner 的 late success/late failure 都只能记录 stale evidence，不得覆盖 item、重复应用题目或释放新 owner。标准化结果也通过同一 ack 协议确认后清理。`StandardizationBatchMultiInstanceTest` 用两个 coordinator 竞争和恢复同一 job，覆盖执行超过 lease、旧 owner late success、旧 owner late failure、heartbeat 中断和新 generation 接管，断言 item/题目只应用一次；能够由 provider 原生幂等恢复时 provider 调用数不增加，否则进入 uncertain/manual_review，原 maxConcurrency、优先级、缓存键和结果顺序不变。

同时在 Worker v1 增加幂等的 `POST /worker/v1/execution-results/{idempotencyKey}/ack`。Java 必须先在一个数据库事务内提交 item response hash、AI job response、必要的题目应用和终态，事务成功后由 acknowledgement coordinator 发送包含 input SHA/result SHA 的 ack；ack 丢失可无限重试，同 key/hash 重复 ack 返回同一结果。Python 仅在 ack 后开始 `AI_RESULT_ACK_RETENTION_DAYS` 清理计时。未 ack 结果在 `AI_RESULT_MAX_UNACKED_DAYS` 到期后只删除正文、保留“不允许自动重跑”的 tombstone；Java 遇到 tombstone 时把 item 置为 `recovery_expired/manual_review`，不得再次调用 provider。测试覆盖 Java 提交前崩溃、提交后 ack 丢失、重复 ack、hash 冲突、worker 重启、暂停超过保留期和 tombstone 恢复。

- [ ] **Step 3: 实现 durable coordinator**

提供 create/get/cancel/resume/retry-failed；不增加自动重试。Planner 在创建 item 时冻结 Task 18A 的 question revision/input hash。简单题应用时，把“保存 AI job response + 以 expected revision 更新题目 + 写 item result hash/appliedAt/success”放在同一个 Java 数据库事务；事务失败三者全部回滚。复合题先只持久化各 child result，全部就绪后在一个事务内锁定父题、验证父题 base revision、聚合 children 一次写回并把相关 item 置终态，禁止逐 child 重复 append。恢复时若 result hash 已 applied 直接返回终态；revision 已变化则置 `stale/manual_review`，不得覆盖人工新稿，也不得重复调用 provider。

`retry-failed` 是用户显式动作，不得复用已经终态的 execution key，也不得把所有 `failed` 都当作可重试。Worker/Java 必须冻结 `providerOutcome=NOT_SUBMITTED|DEFINITIVE_FAILURE|UNKNOWN` 和错误分类：只有可证明未提交，或 provider 已明确返回且按冻结策略标为 retryable 的 definitive failure 才令 `retryAllowed=true`；`UNKNOWN/uncertain/recovery_expired/stale/fenced_stale_result/validation/permanent` 全部 false。请求要求 `Idempotency-Key`，Java 先冻结 eligible item id/expected attempt/generation 的 request hash，再在一个事务内以 `batchJobId + retryRequestKey` 幂等登记请求，对每个允许项执行 `failed + expectedAttemptNo + leaseGeneration` CAS，递增 item attempt/generation，封存旧 execution 为 `superseded`，并创建绑定新 child key 的 AI job/outbox；新 key 由 `rootExecutionKey + newAttemptNo + priorExecutionId` 稳定推导。唯一约束至少覆盖 `(batch_item_id, attempt_no)` 和 `(batch_job_id, retry_request_key, batch_item_id)`。任一 item CAS 冲突整次事务回滚并返回 typed conflict，不允许静默得到部分新 attempts；同 key 但 request hash 已变化同样冲突，调用方刷新后用新 key 明确重试。

并发相同 retry key 或 HTTP 成功响应丢失后的重试必须返回同一组 new attempt，不增加 provider 调用；不同 key 才代表新的显式用户动作，仍需重新读取服务端 `retryAllowed`。旧 execution 的 late success/late failure 由 item generation fence，不能写题或改变新 attempt。测试覆盖 safe/unsafe 分类、同 key 并发、响应丢失、部分 item CAS 冲突、旧结果晚到及 provider 调用计数；性能门禁只允许一次明确用户重试带来的预期增量，重复传输不得增加调用。

- [ ] **Step 4: 以 feature flag 保留前端旧循环**

`ocrflow.analysis-batch.enabled=false` 默认不接受新 batch，后端先上线但前端不开启。新增 `java_analysis_execution_locks`，以 taskId 为主键互斥 `legacy-single` 与 `durable-batch`：两条路径都必须原子取得持久的 owner token 和递增 fencing generation，按小于 lease 1/3 的周期 heartbeat 续租；二者冲突返回 typed `ANALYSIS_EXECUTION_ACTIVE`。AI job 创建、worker execution reservation、题目 apply、batch item 终态必须携带相同 task lock token/generation，并在最终数据库事务中再次验证；lease 已失效的旧 owner 即使晚到也只能记录 `fenced_stale_result`，不得写题、完成 item 或释放新 owner 的锁。

真实旧流程不是一个 HTTP 请求，而是 `ImportWorkbenchTask` 的整轮浏览器循环：普通题调用 task-scoped analysis，复合题小问当前调用 `/api/ai/analysis`，最后再 PUT 父题 children。Task 18 必须增加 task-scoped `legacy-browser-session`，兼容路由固定为 `POST /api/import-tasks/{taskId}/analysis-execution-sessions`、`GET /api/import-tasks/{taskId}/analysis-execution-sessions/{sessionId}`、`POST /api/import-tasks/{taskId}/analysis-execution-sessions/{sessionId}/heartbeat`、`POST /api/import-tasks/{taskId}/analysis-execution-sessions/{sessionId}/units/{unitId}/analysis`、`POST /api/import-tasks/{taskId}/analysis-execution-sessions/{sessionId}/complete`。受管小问必须改调明确的 task/session-scoped unit 路由，不得再和合法 ad-hoc 共用 `/api/ai/analysis`。

开始整轮处理前取得 task lock owner token/fencing generation，并冻结每个目标题的 Task 18A base revision；前端按小于 lease 1/3 heartbeat，并在 `finally` 请求结束。普通题请求、session unit AI 请求和最终父题 PUT 都携带同一 session token，最终 PUT 还必须携带对应 base revision。`AiFlowController`、`AnalysisExecutionSessionController`、`ImportTaskMetadataBridgeController/Service` 和 `AnalyzeQuestionUseCase` 在调用 provider及最终写回前都验证 token/generation/revision；缺失、过期、revision 已变化或被新 generation fence 的请求必须失败，不能覆盖 batch/人工新稿。每个小问使用稳定的 `sessionId + parentQuestionId + subIndex + revision + inputSha256` execution key 调 Worker v1。

Session create/heartbeat/unit/complete 全部幂等，但 complete 绝不能等于立即 unlock：它只把 session 以 owner/generation CAS 从 `active` 转为 `closing`，停止接收新 unit，并返回 active execution blockers。只有该 session 的所有 worker execution 都已 `completed/failed` 且结果已 ack，或已通过 Task 19 reconciliation 得到终态裁决后，后台 finalizer 才能把 session 标记 `closed` 并释放同 generation task lock；任何 `running/orphaned/uncertain` 都继续阻挡 batch create。前端 `finally` 只是触发 closing，可轮询 closing 状态但无权强制解锁。tab 崩溃留下的 session 进入 orphaned reconciliation，不能靠 lease 到期静默清除。测试必须覆盖 unit HTTP 超时而 provider 仍在途时 complete 与 batch create 竞争、complete 响应丢失、重复 complete、closing 期间新 unit 被拒绝、ack 后自动释放和人工裁决后释放，并断言未决执行期间 provider 调用数不增加。

不属于导入任务的独立 `/api/ai/analysis` 在 batch flag 关闭时保持现状，但不能靠客户端自报 header 区分 workbench 与合法 ad-hoc。启用 batch 前必须把合法 ad-hoc 消费者迁到独立 capability/caller scope；caller scope 由服务端认证上下文或网关注入，浏览器 header 不能伪造。batch flag 开启时，可信 `workbench` scope 调旧 `/api/ai/analysis` 一律返回 `LEGACY_UNSCOPED_ANALYSIS_DISABLED`，只允许走 session unit route；没有可信 scope 的部署必须全局关闭旧 ad-hoc route后才能启用 batch。Task-scoped 旧前端先以默认关闭的兼容 flag 接入 session；只有所有已发布前端都带 session、等待至少一个最大旧 SPA/session TTL、遥测确认 workbench unscoped 调用为零后，才允许原子开启“禁用旧 route + 后端 guard + durable batch”。单题点击若没有外层 session，由后端建立只覆盖该请求的 `legacy-single` session。Worker 不声明 execution idempotency capability时 batch fail-closed。架构/集成测试覆盖普通题、小问、最终 PUT、tab 崩溃、heartbeat 丢失、旧页面调用通用 route 被拒绝、可信合法 ad-hoc、session 与 batch 竞争；任何受管调用绕过 guard/v1 reservation 都失败。无冲突请求的算法、Prompt、循环顺序和写回内容不变。

Lease 到期只允许新 coordinator 接管调度权，不等于允许重新调用 provider：它必须先读取同一 AI execution idempotency record；record 为 running 且无法向 provider确认时进入 `uncertain/manual_review`，不能启动第二次调用。`lock-zero` 和 drain 统计必须把 heartbeat 失联但尚未完成 reconciliation 的 execution 计入 `orphaned/uncertain`，不能把单纯过期当成安全清零。测试覆盖“legacy-single 仍运行时 lease 过期 → 新 generation 接管 → 旧结果晚到被拒绝”、heartbeat 中断、网络分区、旧 owner 误释放、drain 遇到 orphaned execution；并断言无重复题目写回，能原生幂等恢复时 provider 调用数不增加，否则明确转人工复核。Parity 测试使用 Phase 0 录制的 worker 响应或 mock transport，对旧 planner 和新 planner 做 capture-only 比较；禁止对同一真实任务同时运行旧流程和新 batch，禁止为比较重复调用 LLM。需要 live 预发时，只能复制到隔离任务和隔离数据库，且结果不写生产题目。

回退协议固定为：先关闭后端新 batch 创建 → 前端停止发起 batch → cancel 或 drain 全部 queued/running batch → reconciliation 清理所有 active/orphaned/uncertain execution 并确认 task lock 为零 → 才启用旧浏览器循环。不能只等待 lease 自然过期，也不能只切前端 flag；测试必须证明回退期间同一 task 不会同时进入两条 AI 链。

- [ ] **Step 5: 验证并 Commit**

```bash
mvn -q -f backend/pom.xml \
  -Dtest=AnalysisBatchPlannerTest,AnalysisBatchServiceTest,AnalysisBatchRecoveryTest,AiExecutionResultAcknowledgementCoordinatorTest,AnalysisExecutionGuardTest,LegacyAnalysisSessionIntegrationTest,StandardizationBatchMultiInstanceTest,WorkerModelsTest,DomainControllerTest test
cd backend/python-worker
PYTHONPATH=. .venv/bin/python -m pytest tests/test_worker_idempotency.py -q -p no:cacheprovider
cd ../..
npm --prefix local-platform test -- --run
git add backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/analysis/batch \
  backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/ai/execution \
  backend/src/main/java/com/aigeneration/questionbank/domain/entity/AnalysisBatch* \
  backend/src/main/java/com/aigeneration/questionbank/domain/entity/AnalysisExecutionLockEntity.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/entity/AiJobEntity.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/entity/StandardizationBatchItemEntity.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/mapper/AnalysisBatch* \
  backend/src/main/java/com/aigeneration/questionbank/domain/mapper/AnalysisExecutionLockMapper.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/mapper/AiJobMapper.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/mapper/StandardizationBatchItemMapper.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/service/StandardizationBatchService.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/controller/AiFlowController.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/service/AiFlowOrchestrationService.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/controller/ImportTaskMetadataBridgeController.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportTaskMetadataBridgeService.java \
  backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/analysis/AnalyzeQuestionUseCase.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/controller/AnalysisExecutionSessionController.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/controller/AnalysisBatchController.java \
  backend/src/main/java/com/aigeneration/questionbank/ocrflow/port/WorkerRuntimePort.java \
  backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/worker/PythonWorkerHttpTransport.java \
  backend/src/main/java/com/aigeneration/questionbank/ocrflow/contract/WorkerModels.java \
  backend/src/test/java/com/aigeneration/questionbank/ocrflow/contract/WorkerModelsTest.java \
  backend/python-worker/app/contracts/worker_v1.py \
  backend/python-worker/app/runtime/idempotency_store.py backend/python-worker/app/routes/worker_v1.py \
  backend/python-worker/tests/test_worker_idempotency.py backend/python-worker/tests/test_worker_v1_contract.py \
  question-engine/openapi/worker.v1.yaml \
  backend/src/main/resources/schema.sql \
  backend/src/main/java/com/aigeneration/questionbank/migration/SchemaMigrator.java \
  backend/src/main/resources/application.yml \
  backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/analysis/batch \
  backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/ai/execution \
  backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/standardization/batch/StandardizationBatchMultiInstanceTest.java \
  local-platform/src/lib/api.ts local-platform/src/components/question-bank/ImportWorkbenchTask.tsx \
  local-platform/src/components/question-bank/ImportWorkbenchTask.analysis-session.test.tsx
git commit -m "feat: add durable analysis batch"
```

### Phase 4 Exit Gate（后端 ready，不切生产前端）

- [ ] 单题和全局标准化共享唯一 Use Case。
- [ ] 单题/全局 worker 请求、调用数、缓存和写回决定保持基线。
- [ ] AI 解析 durable batch 第一版严格串行，planner 和录制响应结果与旧浏览器循环一致。
- [ ] lease、幂等结果提交和重启接管测试通过，provider 调用数不增加。
- [ ] standardization batch 两实例竞争测试通过；`retryFailed` 行为已有明确结论，未通过时不进入公开 SDK。
- [ ] analysis batch 的题目应用、AI job、item 终态处于同一事务，回退 drain/互斥测试通过。
- [ ] 后端 API 和数据库已 ready，但生产前端仍走旧循环；切换和回滚在 Task 21 完成。

---

## Phase 5：公开契约、真实 SDK 与复核模块

### Task 19：增加 typed Review Snapshot、Layout、OCR Flow、Candidate 和 Error

**Files:**

- Create: `question-engine/openapi/fixtures/review-snapshot.v1.json`
- Create: `question-engine/openapi/fixtures/standardization-candidate.v1.json`
- Create: `question-engine/openapi/fixtures/analysis-candidate.v1.json`
- Create: `question-engine/openapi/fixtures/standardization-batch.v1.json`
- Create: `question-engine/openapi/baselines/question-engine.v1.1.0.yaml`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ReviewSnapshotCharacterizationTest.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ReviewSnapshotControllerTest.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/file/QuestionImageUploadIdempotencyTest.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/execution/ExecutionSafetyContractTest.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/execution/ExecutionReconciliationControllerTest.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/execution/ExecutionReconciliationService.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/execution/ExecutionDrainReadinessService.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/domain/entity/ExecutionReconciliationEventEntity.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/domain/mapper/ExecutionReconciliationEventMapper.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ApiExceptionHandlerTest.java`
- Modify: `question-engine/openapi/question-engine.v1.yaml`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/capability/model/QuestionProcessingCapabilityModels.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/capability/service/QuestionProcessingCapabilityService.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/capability/controller/QuestionProcessingCapabilityController.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/entity/StorageFileEntity.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/mapper/StorageFileMapper.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/QuestionImageFlowService.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/JavaFileStorageService.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/common/ApiExceptionHandler.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/port/WorkerRuntimePort.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/worker/PythonWorkerHttpTransport.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/contract/WorkerModels.java`
- Modify: `backend/python-worker/app/contracts/worker_v1.py`
- Modify: `backend/python-worker/app/routes/worker_v1.py`
- Modify: `backend/python-worker/app/runtime/idempotency_store.py`
- Modify: `backend/python-worker/tests/test_worker_idempotency.py`
- Modify: `backend/python-worker/tests/test_worker_v1_contract.py`
- Modify: `question-engine/openapi/worker.v1.yaml`
- Modify: `backend/src/main/resources/schema.sql`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/migration/SchemaMigrator.java`
- Modify: `scripts/check_question_engine_contract.py`

- [ ] **Step 1: 冻结 1.1.0 契约基线**

保存当前 OpenAPI，并为真实工作台响应建立 fixture。后续只允许 additive 变更到 `1.2.0`。

- [ ] **Step 2: 增加只读 Review Snapshot**

新增：

```text
GET /api/capabilities/question-processing/jobs/{jobId}/review-snapshot
```

它只做 Java 快照的 typed projection，不触发 OCR、AI、同步或写回。

- [ ] **Step 3: 把 Task 18A 的 revision 能力投影到公开快照**

`ReviewSnapshot/QuestionDraft` 必须返回 Task 18A 已持久化的 `revision/revisionContentSha256`；新 façade 保存必须调用同一个 `QuestionRepository.updateDraft()`，不得在 controller/capability service 中另写一套“先查再保存”。Controller 测试重复覆盖并发 409、相同 worker result no-op 和 candidate 不推进 revision，防止公开层绕过已验证的 repository。

- [ ] **Step 4: 增加复核所需的稳定 capability façade**

```text
POST /api/capabilities/question-processing/jobs  (Idempotency-Key optional in 1.2; official SDK always sends it)
PUT /api/capabilities/question-processing/jobs/{jobId}/questions/{questionId}
POST /api/capabilities/question-processing/jobs/{jobId}/questions/{questionId}/images
POST /api/capabilities/question-processing/jobs/{jobId}/questions/{questionId}/standardization-candidates
POST /api/capabilities/question-processing/jobs/{jobId}/questions/{questionId}/analysis-candidates
GET /api/capabilities/question-processing/jobs/{jobId}/source/{kind}
GET /api/capabilities/question-processing/jobs/{jobId}/source/paper/pages/{pageIndex}
GET /api/capabilities/question-processing/jobs/{jobId}/standardization-jobs/active
POST /api/capabilities/question-processing/jobs/{jobId}/analysis-batches
GET /api/capabilities/question-processing/jobs/{jobId}/analysis-batches/active
GET /api/capabilities/question-processing/jobs/{jobId}/analysis-batches/{batchJobId}
POST /api/capabilities/question-processing/jobs/{jobId}/analysis-batches/{batchJobId}/cancel
POST /api/capabilities/question-processing/jobs/{jobId}/analysis-batches/{batchJobId}/resume
POST /api/capabilities/question-processing/jobs/{jobId}/analysis-batches/{batchJobId}/retry-failed  (requires Idempotency-Key)
GET /api/capabilities/question-processing/jobs/{jobId}/executions
POST /api/capabilities/question-processing/jobs/{jobId}/executions/{executionId}/reconcile
POST /api/capabilities/question-processing/jobs/{jobId}/executions/{executionId}/attempts  (requires Idempotency-Key)
GET /api/capabilities/question-processing/jobs/{jobId}/drain-readiness
```

这些入口委托现有 Java 保存、`QuestionImageFlowService`、候选 Use Case 和批任务实现；旧 `/api/import-tasks/**` 路径保持不变。为保持 1.1 客户端兼容，create header 在 1.2 契约中仍为 optional：缺失时保持当前“每次新建任务”语义，提供时按 Task 14 返回原任务或 typed conflict；官方 1.2 SDK 一律生成并发送 key。题目保存请求携带 `expectedRevision`，新入口在 revision 不一致时返回 typed conflict，不允许覆盖人工新稿；旧入口继续保持当前行为。

六个 analysis batch operationId 固定为 `createAnalysisBatch`、`getActiveAnalysisBatch`、`getAnalysisBatch`、`cancelAnalysisBatch`、`resumeAnalysisBatch`、`retryFailedAnalysisBatch`；create 使用 typed `CreateAnalysisBatchRequest`，retry-failed 使用 `RetryFailedAnalysisBatchRequest` 并要求 `Idempotency-Key`，其余请求/响应统一投影 Task 18 的 `PostProcessingBatchJob`，不另建第二套状态机。公开错误至少覆盖 `ANALYSIS_EXECUTION_ACTIVE`、`WORKER_RESULT_RECOVERY_EXPIRED`、`EXECUTION_RETRY_FORBIDDEN`、not found、conflict 和 service unavailable，保证 Task 20 生成的 Java/TypeScript SDK 能完成创建、轮询、取消、恢复和失败项重试。同 retry key 的 response loss 重试返回原 attempt 集合；SDK 自动生成 key，但允许调用方持久化并重用自己的 key。

四个运维控制面 operationId 固定为 `listJobExecutions`、`reconcileJobExecution`、`createAuditedExecutionAttempt`、`getJobDrainReadiness`。`list/get drain` 只读；reconcile 请求必须带 `expectedState/fencingGeneration/resolution/actor/reason/evidenceRef`，resolution 仅允许 `PROVIDER_CONFIRMED_NOT_STARTED`、`PROVIDER_RESULT_RECOVERED`、`ABANDONED_NO_RETRY`、`ACCEPT_RISK_FOR_NEW_ATTEMPT`，并以 CAS 写不可变审计事件。

创建新 attempt 只有上一条已裁决为允许时才可执行，并必须同时携带 reconciliation audit event id、`Idempotency-Key`、expected state/generation、actor/reason。数据库建立 `(source_execution_id, reconciliation_audit_event_id)` 唯一约束和 `(source_execution_id, attempt_request_key)` 唯一约束；在同一事务内 CAS 把 audit event 从 `applied_unconsumed` 标为 `consumed`、绑定唯一确定性 `newAttemptId`、创建相应的可恢复调度事实：OCR 写 Task 14 的 `java_worker_dispatches`，AI 写 Task 18 的 queued batch item/AI job，不另造旁路队列。并发点击或 HTTP 响应丢失后用同 key重试返回原 attempt；事件已被另一 key消费则 typed conflict，不能创建第二个 provider attempt。Worker reservation 使用该 `newAttemptId` 派生的稳定 idempotency key。测试覆盖双实例并发、提交后响应丢失、不同 key竞争，以及 worker dispatch/AI queued fact 已提交但 HTTP 回写失败。普通 `retry-failed` 不能绕过该控制面。

`DrainReadiness` 返回 `ready` 和按 OCR reservation、AI execution、task lock、batch item 分组的 blockers；lease 过期不自动从 blockers 消失。权限由公司平台 operator scope 负责，engine 仍强制 actor/reason/evidence、expected state 和 fencing CAS，禁止直接改库作为标准流程。

Java 控制面不能只改自己的数据库。Worker v1 同步增加内部 `GET /worker/v1/executions?jobId=...` 和 `POST /worker/v1/executions/{executionId}/reconcile`：前者统一投影 OCR reservation 与 AI execution-result，后者接收 Java 已提交的 `auditEventId/kind/expectedState/fencingGeneration/resolution/evidenceHash` 并在 Python durable store 做 CAS；重复同 auditEventId 幂等，不同裁决冲突。Java reconciliation 顺序固定为“数据库创建 pending audit event → worker CAS → 数据库把同 event 标记 applied”，任一步崩溃按同 eventId 恢复；只有两边 applied 后才能创建新 attempt或从 drain blockers 移除。`ExecutionDrainReadinessService` 必须联合查询 Java 和 worker，worker 不可达时 `ready=false`，不能把未知当作安全。Worker endpoint 只接受 Java 内部认证，不能由浏览器/SDK直连。

两个 candidate 请求同样必须携带 `expectedRevision`。服务端先确认当前 revision，再以该快照生成候选；响应固定返回 `baseRevision`、`inputSha256` 和 candidate 内容。应用候选时客户端必须把 `baseRevision` 原样作为 capability PUT 的 `expectedRevision`，不能先刷新并替换成“最新 revision”；候选生成后若题目发生任何实质变化，应用必须得到 `QUESTION_REVISION_CONFLICT` 并要求重新生成。测试覆盖“候选生成 → 另一写路径更新 → 旧候选应用失败”。

图片上传同时携带 `expectedRevision` 和调用方生成的 `idempotencyKey`。服务端必须在读取 multipart bytes 时自行计算 SHA-256；调用方 checksum 仅可作为附加校验，不能写成事实值。`java_storage_files` additive 增加 `content_sha256/ingestion_key`，并建立 `(business_type, business_id, ingestion_key)` 唯一约束：同 key、同服务端 SHA 返回原 file reference 和已提交结果，不重写文件、不重复追加题图、不再次推进 revision；同 key、不同 SHA 返回 typed conflict。流程为“写临时文件 → 把文件原子发布到最终 key 并回读校验 SHA → 数据库事务内登记 storage metadata 并 CAS 更新题图引用”；CAS/事务失败时数据库不得出现引用，并 best-effort 删除本次未被引用的最终对象。这样不会出现数据库先提交但文件 finalize 失败的悬空引用；即使成功后的 HTTP 响应丢失，历史迁移脚本重跑也不会产生重复资产。测试必须覆盖成功响应丢失重试、同 key 不同 bytes、final publish 失败和 DB 事务失败重试。成功响应返回稳定 Java file reference 和最新 revision。标准化候选复用现有默认不写回路径；解析候选只调用 Task 17 的 `GenerateAnalysisCandidateUseCase`，测试必须证明题目、图片树和 revision 不变。

- [ ] **Step 5: 定义 typed schema**

至少包含 `ReviewSnapshot`、`QuestionDraft`、`QuestionImageUploadResult`、`PaperLayoutV1`、`PaperLayoutPage`、`PaperLayoutRegion`、`OcrFlowSnapshot`、`OcrFlowStep`、`StandardizationCandidate`、`AnalysisCandidate`、`PostProcessingBatchJob`、`RetryFailedAnalysisBatchRequest`、`ExecutionSafety`、`ExecutionReconciliationRequest`、`ExecutionAttemptRequest`、`DrainReadiness`、`QuestionEngineError`。`ExecutionAttemptRequest` 必须含 reconciliation audit event id/expected state/generation/actor/reason，header 的 attempt request key 不得塞进 body 后丢失。两类 candidate 都要求 `baseRevision/inputSha256`；multipart 图片上传参数明确 `expectedRevision/idempotencyKey`，可选 client checksum 只能用于与服务端计算的 SHA-256 比较，不能作为服务端事实值；布局明确 `coordinateUnit=normalized`；region 的 questionId 可空。

所有 OCR execution、AI execution 和 batch item 必须以同一安全投影返回 `executionState`、`retryAllowed`、`manualActionRequired`、`recoveryReason`、`fencingGeneration`、`lastSafeTransitionAt`。`executionState` 冻结枚举至少包括 `queued/running/completed/failed/uncertain/orphaned/recovery_expired/stale/fenced_stale_result/abandoned`；其中 `uncertain/orphaned/recovery_expired/stale/fenced_stale_result/abandoned` 默认 `retryAllowed=false`。未知新状态在 SDK/review-core 中 fail-closed 为不可重试。`retry-failed`、resume 和创建新 attempt 的后端同样验证该字段及服务端事实，UI 禁用不能作为唯一保护。

- [ ] **Step 6: 修正现有 schema 漂移**

把 `writeResult/apply` 放到正确请求/结果结构，完整定义 canonicalization `structureDiffs/applyBlockingIssues` 和 batch execution/progress 字段；旧顶层字段继续保留。

- [ ] **Step 7: 错误模型 additive 化**

新增 `code/httpStatus/traceId/retryable/details/violations/timestamp/path`，但兼容期保留现有 `status/error/detail/message/path`。OpenAPI 建立 reusable `BadRequest/NotFound/Conflict/PayloadTooLarge/ValidationFailed/WorkerFailure/ServiceUnavailable` responses，并要求所有新 capability façade 的 400/404/409/413/422/500/502/503 显式引用 `QuestionEngineError` 和 `X-Trace-Id` header。至少冻结 `QUESTION_REVISION_CONFLICT`、`INGESTION_KEY_CONFLICT`、`CANDIDATE_STALE`、`WORKER_RESULT_RECOVERY_EXPIRED`、`EXECUTION_RETRY_FORBIDDEN`、`RECONCILIATION_EVIDENCE_REQUIRED`、`RECONCILIATION_ALREADY_CONSUMED`、`DRAIN_NOT_READY`、`LEGACY_UNSCOPED_ANALYSIS_DISABLED` 等 code 枚举，SDK 测试按 code 区分，不解析 message 文本。

- [ ] **Step 8: 验证**

```bash
mvn -q -f backend/pom.xml \
  -Dtest=ReviewSnapshotCharacterizationTest,ReviewSnapshotControllerTest,QuestionRevisionConcurrencyTest,QuestionRevisionMutationTest,QuestionImageUploadIdempotencyTest,ExecutionSafetyContractTest,ExecutionReconciliationControllerTest,ApiExceptionHandlerTest,DomainControllerTest test
cd backend/python-worker
PYTHONPATH=. .venv/bin/python -m pytest tests/test_worker_idempotency.py tests/test_worker_v1_contract.py -q -p no:cacheprovider
cd ../..
python3 scripts/check_question_engine_contract.py
```

- [ ] **Step 9: Commit**

```bash
git add question-engine/openapi backend/src/main/java/com/aigeneration/questionbank/capability \
  backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/execution \
  backend/src/main/java/com/aigeneration/questionbank/domain/entity/ExecutionReconciliationEventEntity.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/mapper/ExecutionReconciliationEventMapper.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/entity/StorageFileEntity.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/mapper/StorageFileMapper.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/service/QuestionImageFlowService.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/service/JavaFileStorageService.java \
  backend/src/main/java/com/aigeneration/questionbank/common/ApiExceptionHandler.java \
  backend/src/main/java/com/aigeneration/questionbank/ocrflow/port/WorkerRuntimePort.java \
  backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/worker/PythonWorkerHttpTransport.java \
  backend/src/main/java/com/aigeneration/questionbank/ocrflow/contract/WorkerModels.java \
  backend/python-worker/app/contracts/worker_v1.py backend/python-worker/app/routes/worker_v1.py \
  backend/python-worker/app/runtime/idempotency_store.py backend/python-worker/tests/test_worker_idempotency.py \
  backend/python-worker/tests/test_worker_v1_contract.py \
  backend/src/main/resources/schema.sql backend/src/main/java/com/aigeneration/questionbank/migration/SchemaMigrator.java \
  backend/src/test/java/com/aigeneration/questionbank/ReviewSnapshotCharacterizationTest.java \
  backend/src/test/java/com/aigeneration/questionbank/ReviewSnapshotControllerTest.java \
  backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/file/QuestionImageUploadIdempotencyTest.java \
  backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/execution \
  backend/src/test/java/com/aigeneration/questionbank/ApiExceptionHandlerTest.java \
  scripts/check_question_engine_contract.py
git commit -m "feat: add typed ocr flow review contract"
```

### Task 20：建立真实生成、可发布的 Java/TypeScript SDK

**Files:**

- Modify: `question-engine/sdk/generate-sdk.py`
- Modify: `question-engine/sdk/README.md`
- Modify: `question-engine/sdk/RELEASE.md`
- Create: `question-engine/package.json`
- Create: `question-engine/package-lock.json`
- Create: `scripts/release_question_engine_sdk.sh`
- Create: `scripts/test_install_question_engine_sdk.sh`
- Create: `question-engine/sdk/test_generate_sdk.py`
- Create: `question-engine/sdk/typescript/package.json`
- Create: `question-engine/sdk/typescript/tsconfig.json`
- Create: `question-engine/sdk/typescript/src/index.ts`
- Create: `question-engine/sdk/typescript/src/QuestionEngineClient.ts`
- Create: `question-engine/sdk/typescript/src/QuestionEngineApiError.ts`
- Generate and commit: `question-engine/sdk/typescript/src/generated/**`
- Create: `question-engine/sdk/typescript/test/QuestionEngineClient.test.ts`
- Create: `question-engine/sdk/typescript/test/QuestionEngineApiError.test.ts`
- Create: `question-engine/sdk/java/pom.xml`
- Create: `question-engine/sdk/java/src/main/java/com/aigeneration/questionengine/sdk/QuestionEngineClient.java`
- Create: `question-engine/sdk/java/src/main/java/com/aigeneration/questionengine/sdk/QuestionEngineApiException.java`
- Generate during build, do not commit: `question-engine/sdk/java/target/generated-sources/openapi/**`
- Create: `question-engine/sdk/java/src/test/java/com/aigeneration/questionengine/sdk/QuestionEngineClientTest.java`
- Create: `question-engine/sdk/java/src/test/java/com/aigeneration/questionengine/sdk/QuestionEngineModelsTest.java`

- [ ] **Step 1: 固定 OpenAPI Generator 版本**

`question-engine/package.json` 建立 npm workspace，第一阶段只登记 `sdk/typescript`；根 `package-lock.json` 固定精确版本的 `@openapitools/openapi-generator-cli`，`generate-sdk.py` 只能通过根 workspace 的本地 `npx --no-install` 二进制生成。Java 通过 Maven plugin 固定同一 generator 版本。生成输出分别进入 `src/generated` 和 `target/generated-sources/openapi`，禁止动态使用 latest；所有 npm/Maven 依赖不得使用浮动 latest 或版本区间不受 lock/BOM 控制。

- [ ] **Step 2: 实现薄 façade**

公开包名为 `@aigeneration/question-engine-sdk` 和 `com.aigeneration:question-engine-sdk`。Façade 处理 header provider、multipart、binary、timeout/abort、typed error；生成代码仅负责传输模型。公开 client 按 `processing`、`review`、`postprocessing`、`files`、`callbacks`、`operations` 分组，必须覆盖 review snapshot、人工稿保存、题图上传、原文件/页图、active batch、analysis batch、execution safety、reconciliation 和 drain readiness；不得把 local-platform 的题库 CRUD、知识点、组卷和最终入库包装进核心 SDK。`retryFailedAnalysisBatch` 和 `createAuditedExecutionAttempt` 必须接受可由调用方持久化复用的 idempotency key，自动生成只作为首次调用便利，响应对象回显 key；SDK 的响应重试拦截器必须复用原 key。`operations` 的写方法要求显式 operator context，不能提供省略 actor/reason/evidence/auditEventId 的便捷重载。

- [ ] **Step 3: 保留旧 generated 目录一个兼容周期**

旧目录只做 re-export/兼容，CI 禁止继续手工扩展。

- [ ] **Step 4: 把生成器改成真正 generate/check**

`generate-sdk.py --generate` 供开发者重建产物。CI 在**干净 checkout** 上不得先 generate，而是直接执行 `--check`：TypeScript 在临时目录重生成并与已提交 `src/generated` 逐文件比较；Java 因 `target/generated-sources` 不提交，只在临时/target 生成、编译，并校验 façade 覆盖全部 operationId，不做工作树 diff。`test_generate_sdk.py` 必须人为篡改临时 TS generated 文件，证明 `--check` 会失败，防止“先自动修正再检查”掩盖过期产物。

- [ ] **Step 5: 验证包**

```bash
npm --prefix question-engine ci
python3 question-engine/sdk/test_generate_sdk.py
python3 question-engine/sdk/generate-sdk.py --generate
python3 question-engine/sdk/generate-sdk.py --check
python3 scripts/check_question_engine_contract.py
npm --prefix question-engine/sdk/typescript test -- --run
npm --prefix question-engine/sdk/typescript run build
npm --prefix question-engine/sdk/typescript pack --dry-run
mvn -f question-engine/sdk/java/pom.xml clean test package
```

- [ ] **Step 6: Commit 可发布候选**

```bash
git add question-engine/package.json question-engine/package-lock.json question-engine/sdk \
  scripts/check_question_engine_contract.py scripts/release_question_engine_sdk.sh \
  scripts/test_install_question_engine_sdk.sh
git commit -m "feat: generate publishable question engine sdks"
```

- [ ] **Step 7: 从该 Commit 发布到测试私服并回读安装**

版本采用 SemVer，同一次 OpenAPI `1.2.0` 候选发布使用 `1.2.0-rc.N`；npm 先发 `next` dist-tag，Maven 发到 staging repository。`release_question_engine_sdk.sh` 只从 `NPM_CONFIG_REGISTRY/NPM_TOKEN/MAVEN_REPOSITORY_URL/MAVEN_SETTINGS_PATH` 读取配置，缺一即失败，不把 URL、账号或 token 写入仓库。发布后 `test_install_question_engine_sdk.sh` 在干净临时 TypeScript/Java consumer 中只从测试私服安装，调用 mock server 验证 create/review/candidate/image/batch/execution safety/reconciliation/new-attempt/drain/error，并断言 retry-failed/new-attempt 的响应重试复用原 idempotency key、未知 safety state fail-closed、`retryAllowed=false` 时 façade 不发普通 retry，再核对 tarball/jar 不含 local-platform、Python、样卷或密钥。

生产发布需要人工批准、Git tag 与 changelog；制品不可覆盖同版本。回退方式是 consumer 固定回上一 SemVer，并把 npm dist-tag 指回上一版本/Maven 依赖回退，不依赖删除已发布制品。

```bash
test -z "$(git status --porcelain)"
python3 question-engine/sdk/generate-sdk.py --check
./scripts/release_question_engine_sdk.sh --version 1.2.0-rc.1 --repository staging
./scripts/test_install_question_engine_sdk.sh --version 1.2.0-rc.1 --repository staging
```

### Task 21：让 local-platform 成为正式 SDK 的示例消费者

**Files:**

- Create: `local-platform/src/lib/question-engine-client.ts`
- Create: `local-platform/src/lib/review-snapshot-adapter.ts`
- Create: `local-platform/src/lib/question-engine-client.test.ts`
- Create: `local-platform/src/lib/review-snapshot-adapter.test.ts`
- Create: `local-platform/src/lib/execution-safety.ts`
- Create: `local-platform/src/lib/execution-safety.test.ts`
- Create: `local-platform/src/lib/runtime-config.ts`
- Create: `local-platform/src/lib/runtime-config.test.ts`
- Create: `local-platform/public/runtime-config.js`
- Modify: `local-platform/package.json`
- Modify: `local-platform/package-lock.json`
- Modify: `local-platform/index.html`
- Modify: `local-platform/src/vite-env.d.ts`
- Modify: `local-platform/src/lib/api.ts`
- Modify: `local-platform/src/components/question-bank/ImportWorkbenchTask.tsx`
- Modify: `local-platform/src/components/question-bank/QuestionCard.tsx`
- Modify: `local-platform/src/components/question-bank/StandardizeCandidatePanel.tsx`

- [ ] **Step 1: 以可复现的本地包依赖接入 SDK**

`local-platform/package.json` 使用精确依赖 `"@aigeneration/question-engine-sdk": "file:../question-engine/sdk/typescript"`，随后更新并提交 `package-lock.json`。CI 必须先完成 Task 20 的 SDK generate/build，再执行 local-platform 的 `npm ci`；禁止用 TypeScript path alias 绕过真实 npm 包入口，否则无法证明未来公司前端可独立安装。

- [ ] **Step 2: 写 SDK/legacy 响应与安全状态 parity tests**

比较题数/顺序/ID、小问、选项、图片/placement、layout/OCR flow、candidate 原因和 batch 计数。对 `uncertain/orphaned/recovery_expired/stale/fenced_stale_result` 逐一验证文案、人工处理提示和 `retryAllowed=false`；未知状态必须显示“状态未知，禁止自动重试”，不能回退成普通 failed。即使 UI 被绕过，mock server 也必须让普通 retry 返回 `EXECUTION_RETRY_FORBIDDEN`。

- [ ] **Step 3: 增加生产可即时更新的 runtime capability flags**

`index.html` 在应用 bundle 前加载 `runtime-config.js`，该文件以 `Cache-Control: no-store` 发布并写入 `window.__OCRFLOW_RUNTIME_CONFIG__`；读取失败 fail-closed 到 legacy。Vite 环境变量只作为本地开发默认值，生产回退不依赖重新 build。第一版矩阵均默认 false：

```text
questionEngineSdkEnabled
reviewSnapshotSdkEnabled
canonicalizationSdkEnabled
candidateSdkEnabled
imageSdkEnabled
standardizationBatchSdkEnabled
analysisBatchSdkEnabled
rescanSdkEnabled
reviewComponentsEnabled   (Task 22 使用)
```

全局 `questionEngineSdkEnabled` 是总门禁，各能力 flag 再做细分；Adapter 保持现有方法签名和 React Query key。运行时配置变更在刷新页面/下一任务时生效，已开始的 durable job 不换执行路径，必须按 Task 18 drain 协议处理。

- [ ] **Step 4: 逐能力迁移**

顺序：review snapshot → canonicalization → durable standardization → single standardize/analysis candidate → durable analysis batch → image library → rescan。每一步都先让 SDK adapter parity 测试通过，再只开启对应 runtime flag；单项稳定一个高峰窗口后才改为默认 true。Batch 进度必须使用 SDK `ExecutionSafety`：不可安全重试的项隐藏/禁用普通重试，展示 recovery reason 与运维处理入口提示；前端不得自行根据字符串 `failed` 推导可重试。题库 CRUD、知识点、组卷和入库仍留在本地 demo API。

- [ ] **Step 5: 预发双读、生产单读**

双读只在预发比较，不得在生产增加请求和同步负担。analysis batch 双读只能比较 planner 和录制响应，不得对同一题触发两次真实 AI 调用。启用 analysis batch 前，先发布 Task 18 的 legacy session 版本，等待一个最大旧 SPA/session TTL 并确认 workbench unscoped analysis 遥测为零；否则后端 batch flag 不得开启。回退 analysis batch 时先把后端 `ocrflow.analysis-batch.enabled=false`，再关闭前端 runtime flag，并按 Task 18/19 的 drain-readiness blockers 完成 reconciliation 后恢复旧浏览器循环；不能仅改一个前端布尔值。

- [ ] **Step 6: 验证并 Commit**

```bash
npm --prefix question-engine ci
python3 question-engine/sdk/generate-sdk.py --check
npm --prefix question-engine/sdk/typescript run build
npm --prefix local-platform ci
npm --prefix local-platform test -- --run
npm --prefix local-platform run build
git add local-platform/package.json local-platform/package-lock.json local-platform/src/lib \
  local-platform/public/runtime-config.js local-platform/index.html \
  local-platform/src/vite-env.d.ts \
  local-platform/src/components/question-bank/ImportWorkbenchTask.tsx \
  local-platform/src/components/question-bank/QuestionCard.tsx \
  local-platform/src/components/question-bank/StandardizeCandidatePanel.tsx
git commit -m "refactor: consume official question engine sdk"
```

### Task 22：抽取 headless review-core 和可选 React 组件

**Files:**

- Create: `question-engine/review-core/package.json`
- Create: `question-engine/review-core/tsconfig.json`
- Create: `question-engine/review-core/src/index.ts`
- Create: `question-engine/review-core/src/review-snapshot.ts`
- Create: `question-engine/review-core/src/ocr-flow.ts`
- Create: `question-engine/review-core/src/paper-layout.ts`
- Create: `question-engine/review-core/src/question-draft.ts`
- Create: `question-engine/review-core/src/candidates.ts`
- Create: `question-engine/review-core/src/batch-job.ts`
- Create: `question-engine/review-core/src/execution-safety.ts`
- Create: `question-engine/review-core/src/polling.ts`
- Create: `question-engine/review-core/src/review-snapshot.test.ts`
- Create: `question-engine/review-core/src/ocr-flow.test.ts`
- Create: `question-engine/review-core/src/paper-layout.test.ts`
- Create: `question-engine/review-core/src/question-draft.test.ts`
- Create: `question-engine/review-core/src/candidates.test.ts`
- Create: `question-engine/review-core/src/batch-job.test.ts`
- Create: `question-engine/review-core/src/execution-safety.test.ts`
- Create: `question-engine/review-core/src/polling.test.ts`
- Create: `question-engine/review-react/package.json`
- Create: `question-engine/review-react/tsconfig.json`
- Create: `question-engine/review-react/src/index.ts`
- Create: `question-engine/review-react/src/OcrFlowTimeline.tsx`
- Create: `question-engine/review-react/src/PaperLayoutViewer.tsx`
- Create: `question-engine/review-react/src/StandardizationCandidateView.tsx`
- Create: `question-engine/review-react/src/BatchJobProgress.tsx`
- Create: `question-engine/review-react/src/OcrFlowTimeline.test.tsx`
- Create: `question-engine/review-react/src/PaperLayoutViewer.test.tsx`
- Create: `question-engine/review-react/src/StandardizationCandidateView.test.tsx`
- Create: `question-engine/review-react/src/BatchJobProgress.test.tsx`
- Create: `local-platform/src/components/question-bank/review-components-switch.test.tsx`
- Create: `scripts/release_question_review_packages.sh`
- Create: `scripts/test_install_question_review_packages.sh`
- Modify: `question-engine/package.json`
- Modify: `question-engine/package-lock.json`
- Modify: `local-platform/package.json`
- Modify: `local-platform/package-lock.json`
- Modify: `local-platform/src/components/question-bank/ImportWorkbenchTask.tsx`

- [ ] **Step 1: 先抽纯 core**

只包含 selectors、OCR progress、layout 分组/坐标校验、candidate apply 判断、batch 终态/进度、execution safety/retry policy、draft patch 和 polling/backoff。安全策略只信服务端 `retryAllowed/manualActionRequired`，未知 enum fail-closed；禁止依赖 React、DOM、Tailwind、TanStack Query、local-platform route/toast。

- [ ] **Step 2: 把现有 helper 测试迁入 core**

迁移 `placement-review.test.ts`、`standardization-job.test.ts` 和相关纯函数测试，保持输入输出不变。

- [ ] **Step 3: 再抽四个无业务组件**

React 作为 peer dependency；组件不拥有 API client、轮询、路由、toast、最终入库或知识点。`PaperLayoutViewer` 接收 `resolveAssetUrl/onQuestionSelect`，candidate 组件接收 `renderMarkdown`。`BatchJobProgress` 必须展示安全状态、recovery reason 和人工处理标记，并仅通过回调暴露服务端允许的操作；`retryAllowed=false` 或未知状态不能触发 retry callback。

- [ ] **Step 4: 不抽完整 QuestionCard/Editor**

两者仍混有平台题库和知识点业务，本计划只复用无业务的 OCR Flow 子组件。

- [ ] **Step 5: 保留 legacy renderer 并增加独立 runtime 回退**

`ImportWorkbenchTask` 读取 Task 21 的 `reviewComponentsEnabled`：false 继续渲染当前本地 OCR timeline/layout/candidate/progress；true 才渲染 review-react。两条路径共享同一 adapter 数据，不因 UI 切换发起第二次请求。Parity test 在开/关两种模式比较 OCR 节点文本/状态、layout region 选择、candidate apply 禁用原因和 batch 进度；SDK data flags 与 renderer flag 可以独立组合。至少稳定一个高峰窗口后才把默认改为 true。

- [ ] **Step 6: 固定可安装的包依赖图**

根 `question-engine` workspace 增加 `review-core/review-react`，并只提交根 lockfile。发布 manifest 使用真实 SemVer：`review-core` 依赖 `@aigeneration/question-engine-sdk ^1.2.0`；`review-react` 依赖 `@aigeneration/question-review-core ^1.2.0`，React/ReactDOM 声明为 peer dependency。npm workspace 在仓库内自动链接相同版本，published package.json 中禁止出现 `file:`、绝对路径或 local-platform。local-platform 作为不发布的 demo 可继续用 `file:` 指向三个本地 package，但这不得进入任一 SDK/review tarball。

- [ ] **Step 7: 验证**

```bash
npm --prefix question-engine ci
python3 question-engine/sdk/generate-sdk.py --check
npm --prefix question-engine/sdk/typescript run build
npm --prefix question-engine/review-core test -- --run
npm --prefix question-engine/review-core run build
npm --prefix question-engine/review-react test -- --run
npm --prefix question-engine/review-react run build
npm --prefix question-engine/review-core pack --dry-run
npm --prefix question-engine/review-react pack --dry-run
./scripts/test_install_question_review_packages.sh --source local-tarballs
npm --prefix local-platform ci
npm --prefix local-platform test -- --run
npm --prefix local-platform run build
```

- [ ] **Step 8: Commit 可发布候选**

```bash
git add question-engine/review-core question-engine/review-react \
  question-engine/package.json question-engine/package-lock.json \
  scripts/release_question_review_packages.sh scripts/test_install_question_review_packages.sh \
  local-platform/package.json local-platform/package-lock.json \
  local-platform/src/components/question-bank/ImportWorkbenchTask.tsx \
  local-platform/src/components/question-bank/review-components-switch.test.tsx
git commit -m "refactor: extract portable ocr review modules"
```

- [ ] **Step 9: 从该 Commit 发布 staging 并做干净 consumer 验收**

先确认同版本 SDK 已在 staging，再以 `1.2.0-rc.N`/`next` 发布 review-core 和 review-react。Release script 在临时 staging 目录把内部依赖从稳定 `^1.2.0` 改为同一精确 RC 版本，打包后验证 tarball manifest，再删除临时目录；不得改写或提交源码 package.json。`test_install_question_review_packages.sh` 在没有源码相对目录的临时工程中只从 staging 安装三个包，执行 TypeScript build、React render smoke 和 package manifest 检查；回退与 SDK 相同，consumer 固定上一 SemVer，不覆盖或删除旧制品。

```bash
./scripts/release_question_review_packages.sh --version 1.2.0-rc.1 --repository staging
./scripts/test_install_question_review_packages.sh --version 1.2.0-rc.1 --repository staging
```

### Phase 5 Exit Gate

- [ ] OpenAPI `1.2.0` 只包含 additive 变更。
- [ ] 所有 operationId 在 Java/TS SDK 中有对应方法。
- [ ] SDK 可分别生成 npm tarball 和 Maven jar。
- [ ] local-platform 每个 SDK runtime capability flag 开/关均通过相同测试；生产切换无需重新构建前端。
- [ ] analysis batch 关闭遵循后端 stop-create → cancel/drain → lock-zero → 旧循环恢复，不产生双 AI 链。
- [ ] reviewComponentsEnabled 开/关 parity 通过，renderer 可独立于数据 adapter 回退。
- [ ] review-core 不依赖 React/DOM；review-react 不依赖 local-platform。

---

## Phase 6：条件式 Java 化、灰度和兼容层退场

### Task 23：只对 canonicalization 建立可执行 shadow，并条件式迁移 Java

**Files:**

- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/canonicalization/CanonicalizationShadowRunner.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/canonicalization/CanonicalizationShadowComparison.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/canonicalization/CanonicalizationApplyTokenService.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/domain/canonicalization/JavaCanonicalizationEngine.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/worker/SwitchingCanonicalizationWorkerAdapter.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/canonicalization/CanonicalizationShadowRunnerTest.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/canonicalization/CanonicalizationApplyTokenServiceTest.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/domain/canonicalization/JavaCanonicalizationEngineTest.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/adapter/worker/SwitchingCanonicalizationWorkerAdapterTest.java`
- Create: `backend/python-worker/tests/fixtures/deterministic-algorithms/canonicalization.json`
- Create: `backend/src/main/java/com/aigeneration/questionbank/domain/entity/CanonicalizationPreviewEntity.java`
- Create: `backend/src/main/java/com/aigeneration/questionbank/domain/mapper/CanonicalizationPreviewMapper.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportTaskCanonicalizationService.java`
- Modify: `backend/src/main/resources/schema.sql`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/migration/SchemaMigrator.java`
- Modify: `backend/src/main/resources/application.yml`

- [ ] **Step 1: 把既有 Port 真正接到可切换实现**

`ImportTaskCanonicalizationService` 仍只依赖 Phase 1 的 `CanonicalizationWorkerPort`。`SwitchingCanonicalizationWorkerAdapter` 同时持有既有 `PythonCanonicalizationWorkerAdapter` 和本地 `JavaCanonicalizationEngine`，让三种模式都走同一输入/输出契约；不再新建一个只在测试中存在的“候选算法”旁路。

- [ ] **Step 2: 写 shadow 不写入测试**

`python` 模式只执行现有 Python 路径；`shadow` 模式执行一次 Python 请求和一次本地 Java 计算，对外永远返回 Python 结果，只记录脱敏字段 diff、耗时和 input hash，不写题目、不应用结构、不重复调用任何 AI/provider；`java` 模式才返回 Java 结果。无论比较是否一致，shadow runner 都不得改变公开结果、数据库或 worker 调用数。

- [ ] **Step 3: 仅实现 canonicalization preview 的 Java 等价实现**

输入是完整 task/question snapshot，输出逐字段保留 Python canonicalization preview 的题序、children、structure diffs、apply blocking issues、warning、score 和 review decision。实现不读数据库、不写题目、不调用 AI。math normalization 仍嵌在 Python OCR/题目后处理主链，本计划不拆出或 Java 化，避免为了“最大 Java 化”破坏既有顺序和精度。

- [ ] **Step 4: 定义唯一开关和晋级门槛**

`ocrflow.canonicalization.engine=python|shadow|java` 默认 `python`。至少 20 份真实样卷、所有 canonicalization fixture、全量 golden 和连续两个预发观察周期逐字段 100% 一致，provider 调用增量为 0，p95/RSS 门禁通过后，才能单独审批进入 `java`。任何不一致均保持 `python`，不以“差异看起来合理”为放行理由。

- [ ] **Step 5: 演练即时回退**

每次 preview 持久化 opaque apply token，记录 task revision、input SHA、engine=`python|java`、engine/pipeline version、preview result SHA、过期时间和 appliedAt。Apply 必须在事务内验证这些字段及当前 engine；题目变化、引擎切换、token 过期或重复 apply 均返回 typed `CANONICALIZATION_PREVIEW_STALE`/idempotent result，禁止让 Python 应用 Java preview 或反向应用。

在不回滚数据库、不重启 Python worker 的前提下，把开关由 `java` 改回 `python`；所有尚未 apply 的 Java token稳定失效并要求重新 preview，已应用 token 保持可审计。随后重新运行 preview/apply parity 和历史题读取。切换审批、观察窗口和回退证据写入发布记录。

- [ ] **Step 6: 验证和 Commit**

```bash
mvn -q -f backend/pom.xml \
  -Dtest=CanonicalizationShadowRunnerTest,CanonicalizationApplyTokenServiceTest,JavaCanonicalizationEngineTest,SwitchingCanonicalizationWorkerAdapterTest,DomainControllerTest test
python3 scripts/ocrflow_golden.py compare --manifest tests/ocrflow-golden/manifest.json
python3 scripts/benchmark_ocrflow.py compare
git add backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/canonicalization \
  backend/src/main/java/com/aigeneration/questionbank/ocrflow/domain/canonicalization \
  backend/src/main/java/com/aigeneration/questionbank/ocrflow/adapter/worker/SwitchingCanonicalizationWorkerAdapter.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportTaskCanonicalizationService.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/entity/CanonicalizationPreviewEntity.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/mapper/CanonicalizationPreviewMapper.java \
  backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/canonicalization \
  backend/src/test/java/com/aigeneration/questionbank/ocrflow/domain/canonicalization \
  backend/src/test/java/com/aigeneration/questionbank/ocrflow/adapter/worker/SwitchingCanonicalizationWorkerAdapterTest.java \
  backend/python-worker/tests/fixtures/deterministic-algorithms/canonicalization.json \
  backend/src/main/resources/schema.sql backend/src/main/java/com/aigeneration/questionbank/migration/SchemaMigrator.java \
  backend/src/main/resources/application.yml
git commit -m "feat: add switchable canonicalization shadow"
```

### Task 24：准备 Python 业务 API 退场并迁移历史资产（不关闭 legacy）

**Files:**

- Create: `scripts/audit_python_legacy_assets.py`
- Create: `scripts/migrate_python_legacy_assets.py`
- Create: `scripts/test_migrate_python_legacy_assets.py`
- Create: `docs/delivery/OCRFLOW_LEGACY_ASSET_MIGRATION.md`
- Modify: `backend/python-worker/app/routes/compatibility_api.py`
- Modify: `backend/python-worker/app/runtime/legacy_store.py`
- Modify: `backend/python-worker/app/worker_routes.py`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportTaskMetadataBridgeService.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/proxy/PythonWorkerProxyFilter.java`
- Modify: `config/ocrflow-boundaries.json`
- Modify: `docs/delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md`
- Modify: `docs/delivery/OPERATIONS_GUIDE.md`

- [ ] **Step 1: 加入 legacy API 访问计数**

按 endpoint 记录兼容调用，不记录题目内容、Prompt 或图片 data URL。

- [ ] **Step 2: 先审计历史数据和资产，生成不可变 manifest**

`audit_python_legacy_assets.py` 只读扫描 `legacy_store`、`library_store.json`、worker 历史结果和仍被 Java 题目/子题引用的 Python 文件 URL，输出 manifest：legacy record type/id、source path、byte length、SHA-256、content type、引用 task/question/placement、目标 Java storage key 和迁移状态。路径必须位于显式 allowlist，符号链接越界、缺文件、hash 冲突或无法解析的引用一律阻塞下线；manifest 不包含题干、Prompt、答案或图片 base64。

- [ ] **Step 3: dry-run 后迁移历史资产到 Java File Flow**

`migrate_python_legacy_assets.py --dry-run` 先验证容量、目标冲突和权限；正式运行只调用 Task 19 的 capability 图片上传与 revision-CAS 题目更新接口，由 Java `QuestionImageFlowService/FileStoragePort` 保存资产并回填稳定 Java file reference，脚本不得直写 Java 数据库或 storage 目录。每项迁移后重新下载并复核 bytes/hash/content-type。迁移具备幂等键 `legacy-source-id + sha256`，重复运行不得产生重复文件。迁移前保留原目录只读备份；迁移失败只删除本次未被引用的目标临时对象，不删除源资产。

迁移测试至少覆盖：重复执行、同名不同 hash、缺文件、已迁移引用、子题/选项题图、父题共享图和历史 worker artifact。所有活动引用迁移完成前，Python 的 legacy asset **读取**路径必须保持可用；业务 CRUD 写入开关与资产读取开关分离，不能因为关闭 CRUD 让旧题图片失效。

同一题的多张图优先一次 multipart 批量提交并以一个 expected revision 原子替换；若受大小限制拆批，每批成功后必须重新读取最新 revision，不能持续复用 manifest 初始 revision。更新使用 typed draft merge，按原 image id/placement 精确替换父题、子题、选项或 shared 位置中的 Python URL，禁止统一追加到父题 `images`。CAS 冲突后执行三方合并：仅当当前值仍等于 manifest 的 legacy URL 才重试替换；人工已经修改/删除的位置进入 review report，不得覆盖。

- [ ] **Step 4: 验证 Java/前端无核心调用**

```bash
python3 scripts/check_ocrflow_boundaries.py
rg '"/api/(import-tasks|question-bank|papers|knowledge-points|ocr|markdown|ai)' \
  backend/src/main/java local-platform/src question-engine
```

以 boundary checker 为强制门禁；`rg` 只做人工补充审计。所有命中必须属于明确的 local-platform 业务或兼容 allowlist；OCR Flow 核心调用不得命中 Python `/api/**`。

- [ ] **Step 5: 增加相互独立、默认保持开启的兼容开关**

增加 `PYTHON_WORKER_LEGACY_API_ENABLED=true` 和 `PYTHON_WORKER_LEGACY_ASSET_READ_ENABLED=true`，本任务发布时两者都保持 `true`。API 开关关闭时业务 CRUD 返回稳定 `LEGACY_API_DISABLED`，asset-read 开关只控制历史资产读取；两者不得联动。此时只验证开关可关闭、可恢复，不在 Java 灰度前改变生产默认值。

- [ ] **Step 6: 产出退场 readiness 报告，但禁止删除实现**

报告包含 API 调用、asset read、manifest 完整率、未迁移引用、Java 恢复演练和 boundary 检查结果。即使全部为零，本任务也不得关闭或删除 legacy，因为 Task 26 的未命中灰度任务仍需使用旧链。Canonicalization 始终保留为接收完整 snapshot 的纯 worker 命令。

- [ ] **Step 7: 全量验证和 Commit**

```bash
python3 scripts/test_migrate_python_legacy_assets.py
python3 scripts/audit_python_legacy_assets.py --check-manifest .artifacts/legacy-assets/manifest.json
./scripts/test_python_worker.sh
backend/python-worker/.venv/bin/python -m pytest backend/python-worker/tests -q -p no:cacheprovider
mvn -q -f backend/pom.xml test
npm --prefix local-platform test -- --run
npm --prefix local-platform run build
python3 scripts/check_ocrflow_boundaries.py
python3 scripts/check_project_portability.py
git add backend/python-worker/app backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportTaskMetadataBridgeService.java \
  backend/src/main/java/com/aigeneration/questionbank/proxy/PythonWorkerProxyFilter.java \
  scripts/audit_python_legacy_assets.py scripts/migrate_python_legacy_assets.py \
  scripts/test_migrate_python_legacy_assets.py config/ocrflow-boundaries.json \
  docs/delivery/OCRFLOW_LEGACY_ASSET_MIGRATION.md docs/delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md \
  docs/delivery/OPERATIONS_GUIDE.md
git commit -m "chore: prepare python legacy retirement"
```

### Task 25：建立完整验收、打包和灰度决策工具

**Files:**

- Create: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/importflow/OcrFlowRolloutDecider.java`
- Create: `backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/importflow/OcrFlowRolloutDeciderTest.java`
- Create: `scripts/verify_ocrflow_release.sh`
- Create: `scripts/ocrflow_execution_control.sh`
- Create: `scripts/test_ocrflow_execution_control.sh`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/importflow/CreateProcessingJobUseCase.java`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportTaskMetadataBridgeService.java`
- Modify: `backend/src/main/resources/application.yml`
- Modify: `scripts/package_question_engine_delivery.py`
- Modify: `docs/delivery/ACCEPTANCE.md`
- Modify: `docs/delivery/DELIVERY_PACKAGE.md`
- Modify: `docs/delivery/OPERATIONS_GUIDE.md`
- Modify: `docs/delivery/ERROR_AND_STATUS_GUIDE.md`
- Modify: `docs/CHANGELOG.md`

- [ ] **Step 1: 建立一键只读验收脚本**

脚本依次执行 Python、Java、前端、OpenAPI/SDK、boundary、golden、performance、portability 和 package inspection；任一失败立即退出。Performance 前必须执行 `benchmark_ocrflow.py restore --ref tests/ocrflow-performance/baseline-ref.json --store-root "$OCRFLOW_BASELINE_READ_ROOT" --output .artifacts/ocrflow-baseline/current.json`，验证 artifact SHA、corpus、provider 和环境指纹后才允许 compare；干净 checkout、CI 和发布机都使用同一不可变 ref。缺少 store、artifact 或指纹不匹配直接失败，不允许现场重录基线绕过门禁。

`ocrflow_execution_control.sh` 是 Task 19 operator API 的薄运维入口，默认只执行 `list`/`drain-readiness`。`reconcile` 必须显式提供 base URL、job/execution id、expected state、fencing generation、actor、reason、evidence ref、resolution；`new-attempt` 还必须提供 reconciliation audit event id 和可持久复用的 idempotency key。两者都用 `--confirm-execution-id` 二次绑定目标；脚本不得接收数据库连接或直接改表。它输出 JSON 审计回执并在 `ready=false` 时返回非零。测试用 mock server 覆盖缺参数拒绝、stale generation、retry forbidden、重复同裁决幂等、同 attempt key 响应丢失、裁决事件重复消费和 blockers 未清零。

- [ ] **Step 2: 运行完整本地验收**

```bash
./scripts/verify_ocrflow_release.sh
```

Expected: all suites pass, golden diff 0, provider call delta 0, performance gates pass.

- [ ] **Step 3: 运行最小平台闭环**

```bash
python3 scripts/acceptance_question_engine_plugin.py \
  --base-url http://localhost:8018 \
  --paper-file docs/samples/platform-integration/paper.md \
  --answer-file docs/samples/platform-integration/answer.md \
  --skip-ai \
  --skip-callback
```

- [ ] **Step 4: 实现可复现、任务级粘滞的灰度决策**

配置使用 `ocrflow.migration.java-task-owner=legacy|shadow|java` 和 `ocrflow.migration.java-task-owner-percent=0..100`。`OcrFlowRolloutDecider` 以 `SHA-256(taskId + rolloutSalt)` 的稳定 bucket 决定新任务：`legacy` 全部旧链；`shadow` 仅命中比例运行无正式写入的 shadow；`java` 仅命中比例进入 Java 主链，其余仍走 legacy。它接入 Task 14 已建立的创建任务入口和 `ocrflow_owner/rollout_config_version` 字段，只决定尚未落库的新任务；之后百分比变化不得让同一任务中途换链。

测试覆盖 bucket 稳定性、0/100 边界、非法配置 fail-closed 到 legacy、不同实例一致、已有任务沿用持久 owner，以及 rolloutSalt 只在新一轮灰度前显式变更。

- [ ] **Step 5: 验证工具和灰度决策并 Commit**

```bash
mvn -q -f backend/pom.xml -Dtest=OcrFlowRolloutDeciderTest test
./scripts/test_ocrflow_execution_control.sh
git add backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/importflow/OcrFlowRolloutDecider.java \
  backend/src/test/java/com/aigeneration/questionbank/ocrflow/application/importflow/OcrFlowRolloutDeciderTest.java \
  backend/src/main/java/com/aigeneration/questionbank/ocrflow/application/importflow/CreateProcessingJobUseCase.java \
  backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportTaskMetadataBridgeService.java \
  backend/src/main/resources/application.yml \
  scripts/verify_ocrflow_release.sh scripts/ocrflow_execution_control.sh \
  scripts/test_ocrflow_execution_control.sh scripts/package_question_engine_delivery.py \
  docs/delivery docs/CHANGELOG.md
git commit -m "chore: add ocr flow rollout tooling"
```

### Task 26：执行灰度、回滚演练并默认关闭 Python legacy

**Files:**

- Create: `docs/delivery/OCRFLOW_ROLLOUT_EVIDENCE.md`
- Modify: `backend/python-worker/app/runtime/config.py`
- Modify: `backend/python-worker/app/routes/compatibility_api.py`
- Modify: `docs/delivery/OPERATIONS_GUIDE.md`
- Modify: `docs/delivery/ACCEPTANCE.md`
- Modify: `docs/CHANGELOG.md`

- [ ] **Step 1: 依次完成 shadow 和百分比灰度**

顺序为内部测试任务 → 脱敏历史任务 capture-only shadow → 5% 新任务 → 25% → 50% → 100%。每一级至少覆盖一个完整业务高峰窗口，并记录样本数、golden diff、provider 调用数、p95/RSS、失败率、人工复核率和任务 owner 分布；任何门禁失败立即停止升级。

- [ ] **Step 2: 按依赖拓扑演练回滚**

先把 `java-task-owner=legacy` 且 percent=0，停止分配新 Java task；等待所有 Java-owned 在途 task 原链完成，或显式取消。禁止仅因换成新 taskId 就立即在 legacy 重建：除 `java_worker_dispatches` 无 queued/leased/submitted/retry_wait 外，还必须查询 Task 10 reservation，确认 `reserved/submitting/running/uncertain` 全部完成 provider reconciliation 或人工裁决，且不存在可能晚到的 provider execution，才允许重建或关闭 worker attempt fencing/idempotency。

Analysis batch 先关闭后端 create、停止前端发起、cancel/drain 活动 batch；随后对 task lock、Java batch item 和 worker AI execution-result 联合 reconciliation，要求 `active/orphaned/uncertain` 全部归零或具有已记录的人工终止裁决，并验证旧 owner 的 fencing generation 已失效，才能恢复旧浏览器循环。不得把 lease 过期或 task lock 行消失视为清零。Canonicalization 先使旧 apply token 失效再回到 Python。最后分别切回 SDK data adapter、review components，并按需重新开启 legacy API/asset-read。每个开关单独演练，再按这套拓扑演练一次组合回滚；记录任务 ID、持久 owner、provider request key、reservation/execution 状态、fencing generation、provider 调用数、数据 hash 和恢复时长。

每个 task/job 都必须用 `ocrflow_execution_control.sh drain-readiness` 取得 `ready=true` 的签名审计回执；如有 blocker，只能经 `list → reconcile → 必要时 new-attempt → drain-readiness` 的受控链处理。任何 `uncertain` 不得由普通 `retry-failed` 清除。回滚证据文档保存 API traceId、裁决 actor/reason/evidence ref 和前后 fencing generation，不接受“人工确认过”这种无结构记录。

- [ ] **Step 3: 完成兼容观察和退场检查**

只有 100% 新任务连续通过门禁后才开始退场计时。以下条件必须同时满足：公开兼容期达到两个向后兼容 MINOR 版本或 90 天（取更长者）；最近 30 天 legacy API 零调用；`ocrflow_owner IN ('legacy','shadow')` 且状态非终态的任务为零；legacy/shadow dispatch、retry 和 recovery 队列为零；Task 24 manifest 活动引用 100% 迁移且 hash 通过；旧 asset read 最近 30 天零命中；Java 备份恢复演练通过。未满足任一条件时任务保持未完成。

- [ ] **Step 4: 默认关闭但保留可回退实现**

把 `PYTHON_WORKER_LEGACY_API_ENABLED` 默认值改为 `false` 并发布；asset read 只有零命中条件成立才同时默认关闭，否则继续只读。运行完整 release script，随后实际演练一次把开关恢复为 true；不得在本任务删除任何 legacy 源文件。

- [ ] **Step 5: 关闭后验证并独立 Commit**

```bash
./scripts/verify_ocrflow_release.sh
python3 scripts/audit_python_legacy_assets.py --check-manifest .artifacts/legacy-assets/manifest.json
git add backend/python-worker/app/runtime/config.py \
  backend/python-worker/app/routes/compatibility_api.py \
  docs/delivery/OCRFLOW_ROLLOUT_EVIDENCE.md docs/delivery/OPERATIONS_GUIDE.md \
  docs/delivery/ACCEPTANCE.md docs/CHANGELOG.md
git commit -m "chore: default python legacy api off"
```

### Task 27：额外观察后删除 Python 业务实现并做最终验收

**Files:**

- Delete: `backend/python-worker/app/legacy/import_tasks.py`
- Delete: `backend/python-worker/app/legacy/question_bank.py`
- Delete: `backend/python-worker/app/legacy/papers.py`
- Delete: `backend/python-worker/app/legacy/__init__.py`
- Delete: `backend/python-worker/app/routes/compatibility_api.py`
- Delete: `backend/python-worker/app/runtime/legacy_store.py`
- Modify: `backend/python-worker/app/worker_base.py`
- Modify: `backend/python-worker/app/worker_routes.py`
- Modify: `backend/python-worker/app/import_services.py`
- Modify: `backend/python-worker/tests/test_import_services.py`
- Modify: `config/ocrflow-boundaries.json`
- Modify: `scripts/package_question_engine_delivery.py`
- Modify: `docs/delivery/DELIVERY_PACKAGE.md`
- Modify: `docs/delivery/OPERATIONS_GUIDE.md`
- Modify: `docs/CHANGELOG.md`

- [ ] **Step 1: 等待额外 emergency window**

Task 26 默认关闭版本稳定运行至少 30 天、回滚演练成功且没有真实紧急恢复后才开始删除。若 legacy asset read 出现任何命中或 manifest 出现未迁移引用，本任务整体阻塞，不做部分删除，避免破坏历史题图片。

- [ ] **Step 2: 删除明确的业务实现和导入**

删除 import task、bank、paper、knowledge CRUD 与 `library_store.json` 业务读写，清理 façade/re-export 和 allowlist。保留 `/worker/v1/**`、OCR/AI 算法、canonicalization 和 export worker。删除后回滚只能部署 Task 26 已验证制品，不能依赖已删除的进程内开关。

- [ ] **Step 3: 删除后重新运行完整验收**

```bash
./scripts/verify_ocrflow_release.sh
./scripts/test_python_worker.sh
backend/python-worker/.venv/bin/python -m pytest backend/python-worker/tests -q -p no:cacheprovider
mvn -q -f backend/pom.xml test
npm --prefix local-platform ci
npm --prefix local-platform test -- --run
npm --prefix local-platform run build
python3 scripts/check_ocrflow_boundaries.py
python3 scripts/check_project_portability.py
python3 scripts/package_question_engine_delivery.py --inspect
```

Expected: all suites pass；交付包只含 Java engine、最小 Python worker、OpenAPI、SDK、必要脚本和文档，不含 local-platform 业务、演示数据库、敏感样卷、密钥、runtime storage 或已删除 legacy 模块。

- [ ] **Step 4: 独立 Commit**

```bash
git add -A backend/python-worker/app backend/python-worker/tests/test_import_services.py \
  config/ocrflow-boundaries.json scripts/package_question_engine_delivery.py \
  docs/delivery/DELIVERY_PACKAGE.md docs/delivery/OPERATIONS_GUIDE.md docs/CHANGELOG.md
git commit -m "refactor: remove python business storage and routes"
```

---

## 4. 最终 Definition of Done

- [ ] 公司平台只通过 Java API/SDK 调用 OCR Flow。
- [ ] 最终交付的 Python 对外只保留 `/worker/v1/**`，不再保存业务任务或题库主数据；兼容 wrapper 已按 Task 27 退场。
- [ ] Java 是任务、文件、状态、幂等、重试、批处理和题目草稿的唯一事实源。
- [ ] 布局、拆题、选项、题图归属、视觉修复和 Prompt 仍由经过 golden 保护的 Python worker 执行。
- [ ] 单题和全局标准化使用同一个 Use Case；全局只负责调度。
- [ ] 批量 AI 解析是可恢复的 Java job，第一版行为与旧浏览器串行逻辑一致。
- [ ] `question-package.v1` 与冻结基线兼容。
- [ ] Java/TypeScript SDK 可独立生成、测试、打包和发布。
- [ ] `review-core` 可独立使用；React 组件可选且不依赖 local-platform。
- [ ] local-platform 不属于 engine 运行时或交付包依赖。
- [ ] 20 份真实样卷 normalized golden 零差异。
- [ ] p95、吞吐、RSS 和 provider 调用数通过门禁。
- [ ] 所有 feature flag 均完成关闭与回滚演练。

## 5. 参考工作量与并行约束

以下是单名熟悉项目工程师的粗略工程量，不是交付日期承诺：

| 阶段 | 参考工作量 | 可并行内容 |
| --- | ---: | --- |
| Phase 0 | 3–5 个工作日 | Java/Python fixture 和 benchmark 可并行 |
| Phase 1 | 4–6 个工作日 | Worker DTO 与 Java Transport 测试可并行 |
| Phase 2 | 4–6 周 | 大文件必须依次拆；同一文件不可多人并改 |
| Phase 3 | 3–5 周 | Repository 与 File Flow 在 Port 完成后可并行 |
| Phase 4 | 3–4 周 | 标准化与解析 Use Case 可在统一模型后并行 |
| Phase 5 | 3–4 周 | Java/TS SDK 可并行；UI 必须等待契约稳定 |
| Phase 6 | 至少两个 MINOR/90 天兼容期 + 30 天 emergency window | shadow、灰度和兼容观察按环境并行，删除必须串行等待 |

关键串行依赖：

- 没有 Phase 0，不开始任何结构移动。
- 没有 Worker v1 和 Port，不切 Java task owner。
- 没有 Java task owner，不下线 Python 业务 CRUD。
- 没有 typed OpenAPI，不抽公共 review-core/React 组件。
- 没有 golden 100% parity，不把确定性算法切到 Java。

## 6. 明确排除项

- 不迁移 local-platform 的题库、知识点、组卷、权限和最终入库流程。
- 不在本计划中拆微服务、引入 MQ 或重构成多仓库。
- 不立即把 JSON 题目字段拆成大量关系表。
- 不 Java 化 MinerU、PDF/Office 预处理、bbox、视觉、布局、题图归属和导出渲染。
- 不在本计划中 Java 化 math normalization；它仍处于 Python OCR/题目后处理顺序中，除非未来能先独立冻结契约并证明全量零差异。
- 不在架构提交中修复 `StandardizationBatchService.retryFailed()` 等业务疑点。
- 不在结构整理时调整 Prompt、阈值、缓存、并发和 fallback。
- 不允许 Java/Python 长期双写业务数据。
