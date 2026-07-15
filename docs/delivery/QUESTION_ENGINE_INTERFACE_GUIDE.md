# question-engine 封装接口说明书

## 1. 文档目的

本文面向要集成或二次开发 `question-engine` 的平台后端、前端和算法工程师，说明：

- `question-engine` 的作用和边界。
- OCR-Flow 在完整题目加工流程中的调用位置。
- 公司平台应优先调用哪些 Java 能力接口。
- 创建加工任务、查询任务、获取标准题目包、人工校验、AI 解析、题图、导出和回调的出入参。
- Python worker 在工程中的职责，以及平台侧不应直接依赖的兼容接口。

本说明书是开发者使用入口；正式机器可读契约以 `question-engine/openapi/question-engine.v1.yaml` 为准。当前 OpenAPI 契约版本为 `1.2.0`，新增强类型 OCR provider/Post Process 能力描述，`question-package.v1` 输出包结构保持兼容。

## 2. question-engine 作用

`question-engine` 是“试卷到标准题目数据包”的加工能力层，不是完整题库业务系统。

它负责：

- 接收试卷文件和可选答案文件。
- 调用 OCR-Flow 识别原始试卷内容。
- 抽取题目、题图、答案、解析、选项、小问 / 子题、空位占位和公式校验信息。
- 调用 AI-Flow 做 Markdown/LaTeX 标准化、AI 解析、答案回填和答案解析匹配。
- 提供人工校验工作台所需的任务、题目、题图和原文件预览接口。
- 输出 `question-package.v1` 标准题目包。
- 可选导出 Markdown/DOCX/PDF。
- 通过 callback-flow 向平台通知任务完成、失败或可重试事件。

题图归属兼容说明：

- 导入题继续使用既有 `images[]` 和 `imagePlacements[]`，没有新增破坏性 API 字段。
- worker/Java 题目原始快照可附带 `imagePlacementValidation`，其中 `blockingReasons` 是稳定机器码；Java 会将其放入单题和全局标准化的 `structuredHints`。
- `POST /api/import-tasks/{taskId}/canonicalization/preview` 可附带 `structureDiffs[]`，列出 `optionCountBefore/After`、题图 `oldTarget/newTarget`、confidence 和 alternatives。apply/rollback 路径不变。
- OpenAPI `1.2.0` 只增强 OCR-Flow 能力描述类型；题目快照/preview 的可扩展字段以及 `question-package.v1` 的 `images` 与 `imagePlacements` 结构保持兼容。

平台负责：

- 用户、租户、学校、机构、教师身份。
- 权限、菜单、审核流、发布状态。
- 最终题库主表、题目版本和业务状态。
- 权威知识点主数据。
- 平台文件中心或对象存储的最终归档。
- API 网关、鉴权、限流和生产级 MQ/监控。

## 3. 运行入口

本地默认地址：

```text
Java 主后端：http://localhost:8018
Python worker：http://127.0.0.1:8000
本地小平台：http://localhost:5173
```

平台集成只应依赖 Java 主后端：

```text
Base URL: http://localhost:8018
```

不要把 Python worker 的 `/api/*` 兼容接口作为平台正式集成入口。Python worker 只应被 Java 内部调用。

## 4. 总体调用链路

```text
平台应用 / 本地小平台
  |
  | 1. POST /api/capabilities/question-processing/jobs
  v
Java question-engine
  |
  | 2. 保存试卷/答案原文件到 file-flow
  | 3. 创建导入任务元数据
  | 4. 调用 Python worker /worker/ocr
  v
Python OCR-Flow worker
  |
  | 5. 选择 OCR provider，默认 MinerU
  | 6. 处理 .pdf/.docx/.md/.markdown/.doc/.pptx/.xlsx/.jpg/.jpeg/.png/.webp/.tif/.tiff 文件
  | 7. 收集 Markdown、JSON、题图和 OCR 原始文本，并执行选项/空位结构保护与视觉修复
  v
Java question-engine
  |
  | 8. 同步 OCR job 状态、导入题、题图和失败原因
  | 9. 提供人工校验和 AI-Flow 接口
  | 10. 输出 question-package.v1
  v
平台最终题库 / 审核流 / 发布流
```

OCR-Flow 的调用位置在第 4 到第 7 步。平台通常不直接调用 OCR worker，而是通过 Java 的 `question-processing` 创建加工任务，由 Java 编排 OCR、文件存储、状态和结果同步。

## 5. 推荐接入顺序

1. 检查能力目录。
2. 创建题目加工任务。
3. 轮询任务状态，或配置 callback-flow 接收事件。
4. 打开人工校验工作台或调用任务详情接口完成校验。
5. 调用 AI 标准化/AI 解析接口补全题目。
6. 获取 `question-package.v1`。
7. 平台侧写入最终题库、进入审核流或发布流。

## 6. 能力目录接口

### 6.1 获取 engine 目录

```http
GET /api/engine
```

用途：

- 查看 `question-engine` 提供的四个模块：题目导入、题库、组卷中心、知识点库。
- 查看平台必须提供的能力。
- 查看交付边界。

返回核心字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `code` | string | 固定为 `question-engine` |
| `modules` | array | 四个可二次开发模块 |
| `supplementalCapabilities` | array | review-workbench、ai-flow、export-flow、file-flow、callback-flow、sdk-openapi |
| `platformRequirements` | array | 平台侧必须提供或建议提供的能力 |
| `deliveryBoundary` | object | engine 交付包含和排除范围 |

### 6.2 获取能力总目录

```http
GET /api/capabilities
```

用途：

- 查看平台可接入的稳定能力。
- 判断哪些能力属于 core，哪些属于 supplemental。

重要能力：

| 能力 | 说明 |
| --- | --- |
| `question-processing` | 试卷到标准题目包主能力 |
| `ocr-flow` | OCR provider 和 OCR 产物收集能力 |
| `review-workbench` | 人工校验工作台能力 |
| `ai-flow` | AI 标准化、解析、答案回填 |
| `export-flow` | Markdown/DOCX/PDF 导出 |
| `file-flow` | 原文件、题图、OCR 产物和导出文件存储 |
| `callback-flow` | 任务事件回调、重试、死信 |
| `sdk-openapi` | OpenAPI 和 SDK 生成入口 |

### 6.3 获取 question-engine 接口清单

```http
GET /api/engine/interfaces
```

用途：

- 给平台后端、前端和 SDK 生成流程提供一份扁平接口清单。
- 对接评审时快速确认哪些接口属于 `question-engine`，哪些只是 Python worker 内部接口。
- 验收时检查四个模块和补充能力是否已经暴露 Java 入口。

返回数组字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `groupCode` | string | 所属模块或补充能力编码，例如 `question-import`、`ai-flow` |
| `groupName` | string | 所属模块或补充能力名称 |
| `method` | string | HTTP 方法；目录端点未声明具体方法时为 `ANY` |
| `path` | string | Java API 路径模板 |
| `description` | string | 所属能力边界说明 |
| `audience` | string | 推荐调用方，当前为 `platform-api` |
| `source` | string | 清单来源：`engine-catalog`、`engine-module` 或 `supplemental-capability` |

核心分组：

| 分组 | 主要接口 |
| --- | --- |
| `engine-catalog` | `/api/engine`、`/api/engine/modules`、`/api/engine/interfaces`、`/api/engine/platform-requirements`、`/api/engine/delivery-boundary` |
| `capability-catalog` | `/api/capabilities` |
| `ocr-flow` | `/api/capabilities/ocr-flow`、`/api/capabilities/ocr-flow/runtime` |
| `question-import` | `/api/capabilities/question-processing`、`/api/capabilities/question-processing/jobs`、`/api/import-tasks`、`/api/import-tasks/{taskId}`、`/api/import-tasks/{taskId}/source/{paper|answer}`、`/api/import-tasks/{taskId}/rescan` |
| `question-bank` | `/api/question-bank/questions`、`/api/question-bank/questions/{id}`、`/api/import-tasks/{taskId}/questions/{questionId}/bank`、`/api/import-tasks/{taskId}/bank` |
| `paper-assembly` | `/api/papers`、`/api/papers/{id}`、`/api/papers/{id}/export` |
| `knowledge-base` | `/api/knowledge-points`、`/api/knowledge-points/{id}` |
| 补充能力 | `review-workbench`、`ai-flow`、`export-flow`、`file-flow`、`callback-flow`、`sdk-openapi` 暴露的 Java 入口 |

## 7. 题目加工主接口

### 7.1 获取题目加工能力描述

```http
GET /api/capabilities/question-processing
```

用途：

- 获取 `question-processing` 的输入、输出、worker 依赖和平台职责。
- 平台接入前可用它做能力探测。

### 7.2 创建题目加工任务

```http
POST /api/capabilities/question-processing/jobs
Content-Type: multipart/form-data
```

表单参数：

| 字段 | 必填 | 类型 | 说明 |
| --- | --- | --- | --- |
| `paperFile` | 是 | file | 试卷原文件，支持 PDF、DOCX、Markdown、图片等 OCR provider 可处理格式 |
| `answerFile` | 否 | file | 答案/解析文件。可为空；如果试卷本身带答案解析，也可以只传 `paperFile` |
| `stage` | 否 | string | 学段，例如 `初中`、`高中` |
| `subject` | 否 | string | 学科，例如 `数学` |
| `grade` | 否 | string | 年级，例如 `九年级` |
| `region` | 否 | string | 地区，例如 `四川成都` |
| `year` | 否 | string | 年份，例如 `2019` |
| `title` | 否 | string | 任务标题或试卷名称 |

当前本地默认配置声明并验收通过的后缀：

```text
.md, .markdown, .pdf,
.png, .jpg, .jpeg, .webp, .tif, .tiff,
.doc, .docx, .pptx, .xlsx
```

说明：

- `.md` / `.markdown` 走 Markdown 直读。
- `.doc` 会先尝试转换为 `.docx`，再进入 OCR provider。
- `.pdf`、图片、`.docx`、`.pptx`、`.xlsx` 走 OCR provider，默认 MinerU。
- 创建任务前会检查 OCR provider runtime；如果 MinerU 未安装或 `MINERU_COMMAND` 不可用，请求返回 503，不会创建导入任务。
- 运行 `./scripts/smoke_import_file_types.py` 可以逐后缀创建导入任务并验证至少生成 1 道题。

示例：

```bash
curl -X POST "http://localhost:8018/api/capabilities/question-processing/jobs" \
  -F "stage=初中" \
  -F "subject=数学" \
  -F "grade=九年级" \
  -F "region=四川成都" \
  -F "year=2019" \
  -F "title=2019年四川成都中考数学试卷" \
  -F "paperFile=@/path/to/paper.pdf" \
  -F "answerFile=@/path/to/answer.pdf"
```

返回 `ProcessingJob`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `jobId` | string | 加工任务 ID，后续所有查询都使用它 |
| `title` | string | 任务标题 |
| `stage` / `subject` / `grade` | string | 学段、学科、年级 |
| `status` | string | Java 业务状态：处理中、待校验、部分完成、已完成、失败、可重试 |
| `processingStatus` | string | 面向平台的归一化状态 |
| `failureReason` | string | 失败原因 |
| `questionCount` | number | 已同步的题目数量 |
| `sourceFiles` | array | 原文件预览入口 |
| `paperOcr` | object | 试卷 OCR job 状态 |
| `answerOcr` | object | 答案 OCR job 状态 |
| `createdAt` / `updatedAt` | string | 创建和更新时间 |

### 7.3 查询题目加工任务列表

```http
GET /api/capabilities/question-processing/jobs
```

用途：

- 平台任务列表或本地管理页展示。
- 当前返回全量任务视图；生产环境可以再加分页、租户过滤和权限过滤。

### 7.4 查询单个题目加工任务

```http
GET /api/capabilities/question-processing/jobs/{jobId}
```

用途：

- 轮询任务状态。
- 获取原文件预览地址。
- 判断是否进入人工校验或是否可重试。

状态建议：

| 状态 | 平台动作 |
| --- | --- |
| `处理中` | 继续轮询或等待回调 |
| `待校验` | 打开人工校验工作台 |
| `部分完成` | 允许校验已识别题目，同时提示有部分失败 |
| `已完成` | 可获取标准题目包并入平台题库 |
| `失败` | 展示失败原因 |
| `可重试` | 调用重试入口或提示人工重试 |

### 7.5 获取标准题目包

```http
GET /api/capabilities/question-processing/jobs/{jobId}/question-package
```

用途：

- 平台最终入库的推荐数据来源。
- 避免平台直接读取本地小平台业务接口或 Java 内部表。

返回 `QuestionPackage`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `packageVersion` | string | 当前为 `question-package.v1` |
| `capability` | string | 当前为 `question-processing` |
| `job` | object | `ProcessingJob` 快照 |
| `questions` | array | 标准化题目数组 |
| `warnings` | array | 任务级告警 |

`ProcessedQuestion` 主要字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `questionId` | string | engine 内部题目 ID |
| `sourceQuestionId` | string | OCR/原始来源题目 ID，仅用于追踪来源；当 OCR 正文区和答案解析区重复出现 `q_1..q_n` 时，后续重复项会追加 `__occurrence_2` 等后缀，避免被导入题快照覆盖 |
| `number` | number | 平台展示题号，按导入题生成顺序自动递增；不得再用 OCR 扫描题号作为展示编号或去重依据 |
| `status` | string | 题目校验状态 |
| `type` | string | 题型候选 |
| `stemMarkdown` | string | 推荐题干 Markdown；空位题、补全题和横线题应保留 `____` / `(____)` 占位 |
| `originalStemMarkdown` | string | OCR 初始题干 Markdown |
| `answer` | string | 答案 |
| `analysis` | string | 解析 |
| `options` | array | 选择题选项，元素为 `QuestionOption`；OCR-flow 会把 `- A.`、`A．`、`A、`、`(A)`、标准 `tasks`、误识别 `ttasks` 和裸 `\task` 行拆为独立选项，`stemMarkdown` 不应再混入选项正文；人工校验 UI 可把该字段重新物化为题干源码里的 `tasks` 块，供用户在同一 textarea 中编辑 |
| `subQuestions` | array | 小问，元素为 `QuestionChild`；新接入优先使用该字段 |
| `children` | array | 兼容旧字段，内容应与 `subQuestions` 保持一致 |
| `images` | array | 题图，元素为 `QuestionImage` |
| `knowledgePointIdCandidates` | array | 知识点 ID 候选 |
| `knowledgePointCandidates` | array | 知识点名称候选 |
| `difficultyCandidate` | string | 难度候选 |
| `scoreCandidate` | number | 分值候选 |
| `mathValidation` | object | 公式校验结果 |
| `warnings` | array | 题目级告警 |
| `sourceEvidence` | object | 来源证据，包括答案/解析证据和是否使用 OCR 原文 |
| `raw` | object | 扩展字段，平台不应强依赖 |

`QuestionChild` 主要字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 小问 ID |
| `label` | string | 小问标签，例如 `(1)` |
| `type` | string | 小问题型 |
| `difficulty` | string | 小问难度 |
| `score` | number | 小问分值，仅作展示或题库元数据 |
| `stemMarkdown` / `manualMarkdown` | string | 小问题干；小问为空位题时同样保留 `____` / `(____)` 占位 |
| `answer` | string | 小问答案 |
| `analysis` | string | 小问解析 |
| `knowledgePointIds` / `knowledgePoints` | array | 小问知识点 |
| `images` | array | 小问题图 |

当 `subQuestions` 非空时，父题自身 `answer` / `analysis` 应为空；答案和解析由各小问承载。

## 8. OCR-Flow 调用位置和接口

### 8.1 平台侧推荐调用方式

平台侧不直接调用 OCR-Flow。推荐：

```http
POST /api/capabilities/question-processing/jobs
```

Java 会在内部完成：

1. 保存 `paperFile` / `answerFile` 到 `file-flow`。
2. 创建导入任务。
3. 调用 Python worker `/worker/ocr`。
4. 同步 OCR job 状态、OCR 结果、题目和题图。
5. 暴露 `ProcessingJob` 和 `QuestionPackage`。

AI 标准化中的答案/解析提取由大模型语义分析完成。Python worker 的程序脚本只做确定性兜底：当模型已经返回 `answer` 或 `analysis` 后，删除 `markdown` 中明确的答案/解析残留块，避免同一内容同时出现在题干和答案解析字段。

选择题选项标准化同样以大模型语义分析为主。模型应把清晰可识别的选项输出为标准 `\begin{tasks}(4) ... \task ... \end{tasks}` 中间格式；worker 会容错识别 `ttasks` 和裸 `\task`，但对外稳定结果应收敛到标准 `tasks` 和 `options`。

空位题、补全题和横线题的占位保护由 worker 做确定性归一。OCR 或 AI 候选中的下划线、空括号、公式等号后的缺失位置应收敛为 `____` / `(____)`；短数字、字母、标点 OCR 噪声只会在已判定为空位题时转为占位。平台消费 `question-package.v1` 时应把这些占位当作题干结构保存和渲染，不应把它们写入答案字段，也不应让大模型直接补答案覆盖题干。

当主 OCR 已经低置信时，worker 会对空位题执行 `visual-repair`：根据 OCR bbox 裁出题目 crop，本地检测长横线；如果配置了 `PIX2TEXT_COMMAND`，只对该题 crop 调用 Pix2Text 二次 OCR。Pix2Text 候选必须更完整且题号不冲突才会写回题干；否则只作为 `visualRepair` 元数据保留，供人工校验参考。

### 8.2 查询 OCR-Flow 能力描述

```http
GET /api/capabilities/ocr-flow
```

用途：

- 查看当前 provider 合约。
- 查看可替换 OCR 引擎时必须保持的输出结构。

关键字段：

| 字段 | 说明 |
| --- | --- |
| `defaultProvider` | 默认 provider，目前是 `mineru` |
| `providerContract.status` | provider 可用性、命令位置、版本和错误原因 |
| `providerContract.run` | 输入 jobId、uploadPath、runtime，原生结果经 adapter 转成统一 OCR 证据包 |
| `providerContract.outputSchema` | 固定为 `canonical-ocr-bundle.v1` |
| `providerContract.requiredEvidence` | documentId、inputSha256、canonicalMarkdown |
| `postProcessContract.inputSchema` | Post Process 接收的统一证据包版本 |
| `postProcessContract.entrypoint` | Python worker 内的稳定嵌入式入口 |
| `postProcessContract.outputCompatibility` | 兼容现有 `collect_outputs` 外观 |
| `configKeys` | OCR provider 相关环境变量 |
| `workerEndpoints` | Java 内部调用的 worker 接口 |

### 8.3 查询 OCR-Flow 运行时

```http
GET /api/capabilities/ocr-flow/runtime
```

用途：

- 检查 Python worker 是否可达。
- 检查 MinerU 或其它 OCR provider 是否可用。
- 检查当前允许的文件扩展名和超时配置。

生产环境可把该接口接入健康检查或运维诊断。

### 8.4 Python worker 内部接口

以下接口由 Java 调用，平台不应直接依赖：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/worker/ocr-flow` | OCR provider 运行时摘要 |
| `POST` | `/worker/ocr` | 创建 OCR job |
| `GET` | `/worker/ocr/{jobId}` | 查询 OCR job |
| `GET` | `/worker/ocr/{jobId}/result` | 获取 OCR 结果 |
| `POST` | `/worker/ocr/{jobId}/retry` | 重试 OCR job |

未来替换 MinerU 时，应新增 Python `OcrProvider` 和 provider adapter，输出 `CanonicalOcrBundle` 后进入统一 Post Process，而不是改 Java 业务 API。详细字段和示例见 [OCR Post Process 使用说明书](POST_PROCESS_USAGE_GUIDE.md)。

## 9. 人工校验和原文件预览

本地小平台使用这些接口完成人工校验工作台。公司平台可以选择嵌入本地工作台，也可以重写前端后调用同一批 Java API。

常用接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/import-tasks/{jobId}` | 获取导入任务详情和题目 |
| `GET` | `/api/import-tasks/{jobId}/source/paper` | 预览试卷原文件 |
| `GET` | `/api/import-tasks/{jobId}/source/answer` | 预览答案原文件 |
| `GET` | `/api/import-tasks/{jobId}/source/paper/pages/{pageIndex}` | 获取试卷单页页图，用于布局解析框叠加 |
| `PUT` | `/api/import-tasks/{jobId}/questions/{questionId}` | 保存人工校验后的题目 |
| `POST` | `/api/import-tasks/{jobId}/questions/{questionId}/bank` | 单题入库到本地 Java 题库快照 |
| `POST` | `/api/import-tasks/{jobId}/bank` | 批量入库到本地 Java 题库快照 |
| `POST` | `/api/import-tasks/{jobId}/rescan` | 重新 OCR 扫描原始试卷/答案文件，保留已提取和已编辑题目 |

说明：

- `/api/import-tasks/{jobId}/source/{paper|answer}` 优先从 Java 文件存储读取；旧任务没有 Java 文件记录时回退 Python。
- `/api/import-tasks/{jobId}` 在试卷 OCR 成功后会返回 `paperLayout`，结构为 `capability`、`pages[]`、`regions[]`、`warnings[]`。`regions` 为父题级范围，坐标是 0-1 归一化的原始 OCR bbox；编号使用平台导入顺序，`questionId` 绑定右侧父题卡片。
- `/api/import-tasks/{jobId}/source/paper/pages/{pageIndex}` 由 Python worker 按 OCR 使用的渲染尺寸生成页图，Java bridge 透传给前端；多页 PDF 使用从 `0` 开始的 `pageIndex`，答案文件暂不提供布局框页图。
- 布局解析框由 Python worker `PaperLayoutCapability` 封装，优先读取 MinerU `_middle.json` 的 `page_size` 和 block bbox，缺失时回退 `content_list`；前端不需要理解 MinerU 内部坐标，只消费 `paperLayout.pages/regions/warnings`。
- 前端开启布局解析框后，应把 `regions` 叠加到对应 `pages`，点击范围框后定位到右侧父题卡片；缺少可靠坐标、原文件缺失或 PDF 渲染失败时，应展示 `paperLayout.warnings` 并允许继续人工校验。
- `/api/import-tasks/{jobId}/rescan` 只重新投递已有 OCR job；任务、试卷 OCR 或答案 OCR 正在处理中时返回 `409`，前端应保持当前轮询并提示用户等待。
- 重扫启动后 Java 会把 `status`、`paperOcrStatus` 和可选 `answerOcrStatus` 切为 `处理中`；worker 同步 OCR job 最新状态时不会覆盖已有 `questions`，真实“重扫后重新提题并合并”需要另行定义合并规则。
- 选择题选项不要拆成独立编辑面板；工作台应把结构化 `options` 物化为题干源码中的 `\begin{tasks}(4)` / `\task` / `\end{tasks}`，用户在同一源码 textarea 中修改，保存时再解析回 `stemMarkdown + options`。
- 空位题占位不要拆成答案输入框；工作台应在同一 Markdown 源码中保留 `____` / `(____)`，用户可以人工增删占位，AI 候选不能绕过人工确认直接把占位替换成答案。
- 含小问的大题应使用复合编辑器；保存人工校验结果时请求体可携带 `subQuestions`，服务端同步返回 `subQuestions` 与兼容字段 `children`。
- 平台如果自管最终题库，不一定要调用本地入库接口；可以直接消费 `question-package.v1`。

## 10. AI-Flow 接口

AI-Flow 用于修复 Markdown/LaTeX、生成解析、自动回填答案和匹配答案解析。

导入题：

```http
POST /api/import-tasks/{jobId}/questions/{questionId}/standardize/ai
POST /api/import-tasks/{jobId}/questions/{questionId}/analysis
```

题库题：

```http
POST /api/question-bank/questions/{questionId}/standardize/ai
POST /api/question-bank/questions/{questionId}/analysis
```

临时文本：

```http
POST /api/markdown/standardize/ai
POST /api/ai/analysis
```

典型请求体：

```json
{
  "markdown": "已 OCR 或人工编辑后的题干 Markdown",
  "questionType": "choice",
  "answer": "",
  "analysis": "",
  "rawOcrText": "OCR 原始文本，推荐传入，便于模型修复公式和匹配答案解析",
  "images": [
    {
      "name": "figure-1.png",
      "url": "/api/import-tasks/job_1/questions/q_1/images/image_1"
    }
  ],
  "knowledgePoints": ["二次函数"],
  "difficulty": "medium",
  "writeResult": false
}
```

典型返回：

```json
{
  "jobId": "ai_job_xxx",
  "status": "success",
  "markdown": "修复后的 Markdown",
  "writeResult": false,
  "writeSkippedReason": "AI 标准化结果已作为候选返回，等待人工预览后应用保存",
  "answer": "A",
  "analysis": "解析内容",
  "questionType": "choice",
  "knowledgePoints": ["二次函数"],
  "difficulty": "medium"
}
```

规则：

- Java 创建 AI job 并记录状态。
- Python worker 只负责模型调用和公式/Markdown 修复。
- AI 标准化默认只返回候选 Markdown 和候选预览所需元数据，不直接覆盖导入题或题库题；前端/平台应让用户预览后应用，再走保存接口持久化。
- 只有显式传入 `writeResult=true` 或 `apply=true` 时，Java 才尝试写回 AI 标准化结果；若候选低置信、`candidateSevereIssues` 非空、`writeBlocked=true`、`applyBlocked=true` 或 `renderValidation.valid=false`，响应会保持 `writeResult=false` 并返回 `writeSkippedReason`。
- 导入题和来自导入任务的题库题会由 Java 回溯同题原始 OCR 片段传给 worker；严重 LaTeX 损坏时，worker 可直接用更完整的原始 OCR 片段作为候选并标记 `rawOcrFallbackUsed=true`。
- worker 会先做确定性 LaTeX 分隔符修复：展示公式 `$$...$$` 内部嵌套单 `$`、行内公式被 `\div`/`\leq` 等运算符切断时，可在不调用大模型的情况下生成可渲染候选，并在 `standardizer.latexDelimiterRepaired=true` 中标记。
- 当前编辑稿严重损坏且同题原始 OCR 题段更可靠时，worker 可直接返回 `standardizer.source=ocr-fallback`、`rawOcrFallbackUsed=true` 的候选，不再调用 LLM。
- 空位题 AI 标准化必须保留 `____` / `(____)` 占位；模型可以根据 OCR 证据修正缺失或乱码占位，但不能直接求解并把答案填进 `markdown`。
- worker 对候选执行本地公式标准化前后会比较严重风险；如果本地标准化会重新引入严重 LaTeX 风险，会保留候选原文并在 `standardizer.warnings` 中记录。
- AI 解析返回 `answer` 或 `analysis` 时，Java 会写回导入题或题库题。
- AI 解析会携带题图：调用导入题或题库题专用解析接口时，请求体可省略 `images`，Java 会读取当前题目已保存的 `images`，优先从 `file-flow` 的 Java 存储读取图片，旧 OCR 图片会通过 worker 文件接口回退读取，然后转成模型可消费的 `imageDataUrl` 发给大模型。
- `imageDataUrl` 只用于 Java 到 Python worker 的内部解析请求；`GET /api/capabilities/ai-flow/jobs` 返回的 job request 会把内联图片内容脱敏为占位文本，避免把 base64 图片写入任务查询结果。
- 导入工作台“AI 解析全部”不新增后端批量接口，前端顺序调用单题 AI 解析和保存接口：默认只补齐未入库且缺少解析的题目，可选择覆盖已有解析；普通题按整题生成，复合大题按小问生成，提示词包含父题材料和当前小问题干，答案使用当前小问答案；失败项只计入汇总，不中断整批。
- AI 批量解析写回后不得自动改变题目校验状态，仍需人工从“待校验”确认后再入库。生产高并发场景如果需要大量批处理，应迁移为 Java `ai-flow` 队列任务，并增加租户级、用户级和 endpoint 级限流。
- 导入工作台“全局标准化”不新增后端批量接口，前端顺序调用现有标准化接口和导入题保存接口：父题题干使用 `/api/import-tasks/{jobId}/questions/{questionId}/standardize/ai` 以获得同题 OCR 上下文，答案、解析和小问题干使用 `/api/markdown/standardize/ai`；成功项通过 `PUT /api/import-tasks/{jobId}/questions/{questionId}` 自动保存。
- 全局标准化写回前必须检查 `standardizer.applyBlocked`、`standardizer.candidateSevereIssues` 和 `standardizer.renderValidation`。候选不可安全应用时只计入失败，不得覆盖当前人工校验稿；题目校验状态保持不变。
- 如果要提高 LaTeX 修复精度，调用方应尽量传 `rawOcrText`，不要只传渲染后的文本。

## 11. 题图和 file-flow 接口

导入题题图：

```http
GET  /api/import-tasks/{jobId}/image-library
POST /api/import-tasks/{jobId}/questions/{questionId}/images
POST /api/import-tasks/{jobId}/questions/{questionId}/images/select
GET  /api/import-tasks/{jobId}/questions/{questionId}/images/{imageId}
```

题库题题图：

```http
GET  /api/question-bank/questions/{questionId}/image-library
POST /api/question-bank/questions/{questionId}/images
GET  /api/question-bank/questions/{questionId}/images/{imageId}
```

上传题图：

```bash
curl -X POST "http://localhost:8018/api/import-tasks/{jobId}/questions/{questionId}/images" \
  -F "files=@/path/to/figure.png"
```

从当前 OCR 任务题图库选择题图：

```bash
curl -X POST "http://localhost:8018/api/import-tasks/{jobId}/questions/{questionId}/images/select" \
  -H "Content-Type: application/json" \
  -d '{
    "imageIds": ["image_123"]
  }'
```

说明：

- Java 会把题图写入 `java_storage_files`。
- 本地模式写入 `backend/storage/java_files`。
- 企业模式可通过 MinIO 配置切到对象存储。
- `QuestionImage.url` 可直接用于前端渲染。
- 每个导入任务都有独立的任务题图库；人工校验时可以本地上传，也可以从这个任务题图库选择并挂到当前题。
- 任务题图库选择只接受当前 `jobId` 下已经存在的图片，服务端会按 `imageId` / `id` / `url` / `path` 匹配并去重。

## 12. 组卷和导出接口

本地组卷接口：

```http
POST /api/papers
PUT /api/papers/{paperId}
GET /api/papers/{paperId}
GET /api/papers
```

`paper.create` / `paper.update` 可接受 `subSelections: Record<questionId, subId[]>`。`paper.get` / `paper.list` 原样返回 `subSelections`，并在每道题中内嵌完整 `subQuestions`。当某题选择记录缺失、为空或与当前题的小问无交集时，前端和导出链路按全选处理；只要大题在试卷内，至少应保留一个小问。`scores[questionId]` 仍是试卷计分口径，小问 `score` 只用于展示所选小问合计。修改 `subSelections` 不得修改题库原题。

试卷导出：

```http
GET /api/papers/{paperId}/export?format=docx|pdf&variant=teacher|student
```

导出 job 查询：

```http
GET /api/capabilities/export-flow/jobs
GET /api/capabilities/export-flow/jobs/{jobId}
GET /api/capabilities/export-flow/runtime
```

说明：

- Java 创建导出 job、记录状态和导出文件。
- Python worker `/worker/export/render` 只负责 DOCX/PDF 文件渲染，不保存导出 job 元数据。
- DOCX 主路径是生成 Markdown + LaTeX 中间文件后通过 Pandoc 转换，数学公式进入 Word 原生公式对象。
- PDF 主路径是专用 XeLaTeX 预览模板，保留数学公式、题型徽标、小问卡片、题图、选项和解答题作答区；不再把 PDF 主路径建立在 Pandoc PDF 上。
- 未安装 Pandoc 时 DOCX 走旧 fallback；未安装 XeLaTeX 或缺少 `ctex`、`tcolorbox`、`tabularx` 等 LaTeX 包时 PDF 走 ReportLab fallback，复杂公式会降级为文本，应优先修复运行环境。

## 13. callback-flow 接口

运行时：

```http
GET /api/capabilities/callback-flow/runtime
```

创建测试回调：

```http
POST /api/capabilities/callback-flow/test
Content-Type: application/json
```

请求体：

```json
{
  "callbackUrl": "https://platform.example.com/question-engine/callback",
  "eventType": "processing.completed",
  "aggregateType": "processingJob",
  "aggregateId": "job_123",
  "idempotencyKey": "processing.completed:job_123",
  "maxRetryCount": 3,
  "secret": "platform-secret",
  "payload": {
    "jobId": "job_123",
    "status": "已完成"
  }
}
```

事件查询和重试：

```http
GET  /api/capabilities/callback-flow/events?status=failed
POST /api/capabilities/callback-flow/events/{eventId}/retry
POST /api/capabilities/callback-flow/events/retry-due
```

签名请求头：

| Header | 说明 |
| --- | --- |
| `X-Question-Engine-Event` | 事件类型 |
| `X-Question-Engine-Event-Id` | 事件 ID |
| `X-Question-Engine-Signature` | `sha256=` + HMAC-SHA256(payload, secret) |

事件状态：

| 状态 | 说明 |
| --- | --- |
| `pending` | 已创建，未发送 |
| `sent` | 已发送成功 |
| `failed` | 发送失败，可按 `nextRetryAt` 重试 |
| `dead_letter` | 达到最大重试次数，进入死信状态 |

## 14. 标准错误处理

常见 HTTP 状态：

| 状态码 | 场景 |
| --- | --- |
| `400` | 缺少必要参数，例如未传 `paperFile` 或 jobId 为空 |
| `404` | 任务、题目、图片或导出文件不存在 |
| `502` | Java 调 Python worker 失败，或 OCR/AI/导出 worker 不可达 |
| `503` | Python worker 被禁用或未启动 |
| `500` | 未捕获的服务端异常，应查看 Java 日志和 traceId |

Java 响应通常会带 `X-Trace-Id` 或响应体 `traceId`，平台日志应记录该值，方便定位。

## 15. SDK 和 OpenAPI

正式契约：

```text
question-engine/openapi/question-engine.v1.yaml
```

SDK 目录：

```text
question-engine/sdk/generated/typescript
question-engine/sdk/generated/java
```

SDK 使用说明：

```text
question-engine/sdk/USAGE.md
```

本地小平台如何作为 example 使用：

```text
docs/product/LOCAL_PLATFORM_AS_EXAMPLE.md
```

当前 SDK 覆盖的能力：

| 能力 | TypeScript 方法 | Java 方法 |
| --- | --- | --- |
| 能力目录 | `listCapabilities` / `getEngineCatalog` / `getEngineInterfaces` | `listCapabilities` / `getEngineCatalog` / `getEngineInterfaces` |
| 加工任务 | `createProcessingJob` / `getProcessingJob` / `getQuestionPackage` | `getProcessingJob` / `getQuestionPackage` |
| 重新 OCR 扫描 | `rescanImportTask` | `rescanImportTask` |
| 任务题图库 | `getImportTaskImageLibrary` | `getImportTaskImageLibrary` |
| 选择任务题图 | `selectImportQuestionImages` | `selectImportQuestionImages` |
| 导入题 AI 标准化候选 | `standardizeImportQuestion` | `standardizeImportQuestion` |
| 导入题 AI 解析写回 | `analyzeImportQuestion` | `analyzeImportQuestion` |
| 题库题图库 | `getBankQuestionImageLibrary` | `getBankQuestionImageLibrary` |
| 题库题 AI 标准化候选 | `standardizeBankQuestion` | `standardizeBankQuestion` |
| 题库题 AI 解析写回 | `analyzeBankQuestion` | `analyzeBankQuestion` |
| callback-flow | `listCallbackEvents` / `retryCallbackEvent` | `listCallbackEvents` / `retryCallbackEvent` |

手写示例：

```text
question-engine/sdk/examples/typescript
question-engine/sdk/examples/java
```

建议：

- 平台新应用优先使用 OpenAPI 生成 SDK。
- 平台开发者先按 `question-engine/sdk/USAGE.md` 的最小闭环接入，再按需参考 `docs/product/LOCAL_PLATFORM_AS_EXAMPLE.md` 理解本地工作台交互。
- 不要直接复制本地小平台 `local-platform` 的 API 封装作为公司平台 SDK。
- `raw` 字段只做兼容和调试，不应作为平台强依赖字段。

## 16. 平台集成最小闭环

平台只想使用“试卷加工成题目包”能力时，最小闭环如下：

1. `GET /api/capabilities/question-processing` 检查能力可用。
2. `POST /api/capabilities/question-processing/jobs` 上传试卷和可选答案。
3. `GET /api/capabilities/question-processing/jobs/{jobId}` 轮询到 `待校验` 或 `已完成`。
4. 平台打开自己的校验页，或跳转/嵌入本地 review-workbench。
5. 可选调用 AI-Flow 接口补答案、解析和公式。
6. `GET /api/capabilities/question-processing/jobs/{jobId}/question-package` 获取标准题目包。
7. 平台把 `questions` 写入自己的题库主表。

## 17. 本地调试命令

启动：

```bash
./scripts/start_project_with_java_backend.sh
```

健康检查：

```bash
curl http://localhost:8018/api/java/health
curl http://localhost:8018/api/java/worker
curl http://localhost:8018/api/capabilities/question-processing
curl http://localhost:8018/api/capabilities/ocr-flow/runtime
```

查看本地页面：

```text
http://localhost:5173
```

## 18. 不推荐的接入方式

不要这样接入：

- 平台直接调用 Python worker `/api/*` 兼容接口。
- 平台依赖 `local-platform/src/lib/api.ts` 的本地页面封装。
- 平台直接读 `backend/storage` 下的演示文件。
- 平台把 `question-engine` 的本地 H2/JSON 数据当作最终业务主数据。
- 平台强依赖 `raw` 字段里的临时结构。

应该这样接入：

- 业务入口统一走 Java `/api/capabilities/*` 和 `/api/engine`。
- OCR/AI/导出执行能力由 Java 编排 Python worker。
- 最终入库以 `question-package.v1` 为准。
- 平台侧自管用户、权限、最终题库、审核流和发布流。
