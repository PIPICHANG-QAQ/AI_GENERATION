# 题库能力发动机交付边界

## 结论

当前项目应拆成两层：

```text
题库能力发动机 question-engine
  Java 主能力 API + Python 必要 worker

本地小平台 local-admin
  Vite React 页面、Replit 原型、演示数据、截图和本地闭环体验
```

公司交付时应优先交付 `question-engine`，不要把本地小平台页面、原型图、演示数据和截图作为核心能力交付物。

## Engine 已封装模块

Java 已新增能力目录：

```http
GET /api/engine
GET /api/engine/modules
GET /api/engine/modules/{moduleCode}
GET /api/engine/interfaces
GET /api/engine/supplemental-capabilities
GET /api/engine/platform-requirements
GET /api/engine/delivery-boundary
```

四个可二次开发模块：

| 模块 | 能力边界 | Java 化状态 | Python 补充 |
| --- | --- | --- | --- |
| `question-import` 题目导入 | 试卷/答案上传、OCR-Flow、任务状态、原文件预览、待校验题目、标准题目包 | Java 管任务元数据、状态机、文件记录、导入题、导入题图、重试入口和标准题目包 | OCR worker、AI worker |
| `question-bank` 题库 | 题目 CRUD、搜索筛选、题图、答案解析、来源追踪、入库 bridge | Java 管题库题目主快照、题库题图上传/访问、AI 解析结果写回 | AI worker |
| `paper-assembly` 组卷中心 | 手动选题、规则选题、排序赋分、卷头、预览、导出 | Java 管试卷定义、题目引用、分值、导出任务元数据和导出文件存储 | Pandoc/LaTeX 导出 worker |
| `knowledge-base` 知识点库 | 知识点 CRUD、搜索、题目知识点候选关联 | Java 已管本地知识点快照 | 无 |

## 已补充封装能力

Java 已新增能力总目录：

```http
GET /api/capabilities
GET /api/capabilities/review-workbench
GET /api/capabilities/ai-flow
GET /api/capabilities/ai-flow/runtime
GET /api/capabilities/export-flow
GET /api/capabilities/export-flow/runtime
GET /api/capabilities/file-flow
GET /api/capabilities/file-flow/runtime
GET /api/capabilities/callback-flow
GET /api/capabilities/sdk-openapi
```

| 能力 | 边界 | Java 化状态 | Python 补充 |
| --- | --- | --- | --- |
| `review-workbench` | 可嵌入人工校验工作台，包含题干、答案、解析、题图、原文件预览和保存状态协议 | Java 提供任务、题目、题图和题目包 API；本地 React 页面只是演示壳 | 无 |
| `ai-flow` | AI 标准化候选、AI 解析、答案解析匹配、确定性 LaTeX 分隔符修复、题图随解析进入多模态模型上下文和模型运行时状态 | Java 创建 AI job、从 file-flow 读取题图并转为 worker 内部图片输入、调用 Python worker、记录成功/失败；标准化默认返回候选并等待人工应用保存，解析结果写回导入题或题库题 | `/worker/ai/standardize`、`/worker/ai/analysis` |
| `export-flow` | Markdown 中间文件、DOCX/PDF 导出、公式和题图导出 | Java 创建导出 job、调用 Python render worker、保存导出文件元数据和下载响应 | `/worker/export/render`、`/worker/export-flow` |
| `file-flow` | 原文件、题图、OCR 产物、导出文件的存储和访问协议 | Java 管 LOCAL/MINIO 文件存储、导入原文件、导入题图、题库题图和导出文件 | Python 只读取临时路径或 worker 产物 |
| `callback-flow` | 任务完成、失败、可重试、超时等事件回调协议 | Java 已提供 HTTP 回调事件表、HMAC 签名、幂等键、失败记录、到期重试扫描和 dead_letter 状态 | 无 |
| `sdk/openapi` | OpenAPI、Knife4j、能力目录和 SDK 生成边界 | 已提供静态 `question-engine.v1.yaml`、`/v3/api-docs`、`/doc.html` 和 generated TypeScript/Java SDK | 无 |

## 本轮已新增稳定入口

```http
GET  /api/import-tasks/{taskId}/image-library
POST /api/import-tasks/{taskId}/questions/{questionId}/images
GET  /api/import-tasks/{taskId}/questions/{questionId}/images/{imageId}

GET  /api/question-bank/questions/{questionId}/image-library
POST /api/question-bank/questions/{questionId}/images
GET  /api/question-bank/questions/{questionId}/images/{imageId}

POST /api/import-tasks/{taskId}/questions/{questionId}/standardize/ai
POST /api/import-tasks/{taskId}/questions/{questionId}/analysis
POST /api/question-bank/questions/{questionId}/standardize/ai
POST /api/question-bank/questions/{questionId}/analysis
GET  /api/capabilities/ai-flow/jobs
GET  /api/capabilities/ai-flow/jobs/{jobId}

GET  /api/papers/{paperId}/export?format=docx|pdf
GET  /api/capabilities/export-flow/jobs
GET  /api/capabilities/export-flow/jobs/{jobId}

POST /api/import-tasks/{taskId}/retry
GET  /api/capabilities/callback-flow/runtime
POST /api/capabilities/callback-flow/test
GET  /api/capabilities/callback-flow/events
POST /api/capabilities/callback-flow/events/{eventId}/retry
POST /api/capabilities/callback-flow/events/retry-due
```

OpenAPI 和 SDK 已放在：

- `question-engine/openapi/question-engine.v1.yaml`
- `question-engine/sdk/generated/typescript`
- `question-engine/sdk/generated/java`
- `question-engine/sdk/README.md`

面向其他开发者的接口使用说明见：

- `docs/delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md`

该说明书解释 `question-engine` 的作用、OCR-Flow 在加工链路中的调用位置、平台推荐调用顺序、核心接口出入参、AI/题图/导出/callback-flow 使用方式和不推荐的接入方式。

## 建议交付代码范围

包含：

- `backend/src/main/java/com/aigeneration/questionbank/engine`
- `backend/src/main/java/com/aigeneration/questionbank/capability`
- `backend/src/main/java/com/aigeneration/questionbank/domain`
- `backend/src/main/java/com/aigeneration/questionbank/common`
- `backend/src/main/java/com/aigeneration/questionbank/config`
- `backend/src/main/java/com/aigeneration/questionbank/migration`
- `backend/src/main/resources`
- `backend/pom.xml`
- `backend/python-worker/app/ocr_flow.py`
- `backend/python-worker/app/llm_splitter.py`
- `backend/python-worker/app/math_normalizer.py`
- Python worker 中被上述文件依赖的最小启动代码

排除：

- `local-platform/`
- 历史 `protocal/` 原型仓库
- `docs/renders/`
- `backend/storage/`
- Replit 原型、截图、演示数据、本地调试产物
- 本地小平台页面相关代码

## 平台必须提供

平台负责“车架、权限、组织、最终业务流”，engine 只提供能力。

必需项：

- 用户、租户、学校/机构、教师身份上下文。
- 权限和菜单入口。
- MySQL 或平台数据库。
- 对象存储或文件中心。
- OCR provider 配置。
- 大模型配置，若需要自动拆题、标准化和解析。
- 任务状态轮询或回调接收机制。
- 最终题库入库、题目版本、审核流和发布状态。
- 平台权威知识点主数据，若已有统一知识体系。

可选项：

- Redis 缓存、限流和任务状态缓存。
- RocketMQ 或其它 MQ，承载 OCR/AI 长任务异步化。
- Prometheus、日志采集和 traceId 链路。
- SDK、OpenAPI 网关和嵌入式校验工作台入口。

## Java / Python 分工

Java 应继续承载：

- 四个模块的能力 API。
- 导入任务状态机。
- 数据表和元数据同步。
- 文件存储元数据和访问控制。
- 题库题目、试卷、知识点 CRUD。
- 标准题目包输出。
- 平台接入契约、回调和鉴权适配。

Python 只保留必要补充：

- OCR provider worker。
- AI 标准化 worker。
- AI 解析 worker。
- LaTeX/公式处理。
- Pandoc 导出 worker。

本轮 Java 化进度：

1. 题图上传、访问和图片库接口已迁到 Java，导入题和题库题均走 `file-flow`。
2. 试卷导出任务元数据和导出文件存储已迁到 Java，Python 只提供 `/worker/export/render` 生成文件。
3. AI 标准化/解析已由 Java 创建 job 并调用 Python worker；AI 标准化默认返回候选并由人工应用保存，worker 会先做确定性 LaTeX 分隔符修复和风险校验；AI 解析会把题目已保存题图一并送入多模态模型上下文，并把答案和解析写回导入题或题库题。
4. 导入任务重试入口和 callback-flow 已由 Java 编排；callback-flow 已具备本地幂等、到期重试扫描和 dead_letter 状态，MQ provider 仍以配置契约和本地表 fallback 形式保留。
5. 已提供静态 OpenAPI、Knife4j 入口和 generated TypeScript/Java SDK，本地页面继续作为演示壳。

## 后续继续升级点

- 接入真实 MQ provider，例如 RocketMQ，把导入、AI 和导出长任务从同步 worker 调用升级为异步消息编排。
- 增加 Java 定时超时扫描器，按任务类型和 SLA 自动标记超时、触发 callback-flow 和可重试状态。
- 将 callback-flow 的本地重试扫描升级为真实 MQ 死信队列、平台级幂等键校验和可观测重试策略。
- 让 Python worker 全量改为读取 Java 发放的对象存储临时 URL 或临时本地文件，不再依赖 Python 自有业务文件路径。
- 将 generated SDK 升级为可发布包：TypeScript npm package、Java Maven module，并纳入 CI 标准 OpenAPI generator。

## 题目加工能力服务架构

当前项目后续不再定位为公司教育生态平台里的完整题库系统，而是定位为“试卷到标准题目数据包的加工能力服务”。它负责把试卷和答案文件加工成平台可消费的标准题目数据包，并提供可嵌入的人工校验工作台。公司教育生态平台负责用户、权限、组织、知识点主数据、最终题库入库、审核流、发布状态和长期文件归档。

能力层负责接收试卷文件和可选答案文件，完成 OCR、版面解析、图片抽取、拆题、题型识别、选项识别、题图归属、AI 标准化 Markdown + LaTeX、AI 生成或补全答案解析，并输出标准题目数据包。平台负责用户、角色、权限、租户、学校、机构、最终题库表结构、题目版本、审核流、发布状态、班级课程作业考试等业务应用，以及文件中心最终归档和访问权限。

本地项目仍然可以作为一个小平台运行，保留题目导入、题库中心、组卷中心和知识点库，用于开发、演示和端到端验证。但代码边界上要逐步形成两层：

```text
本地小平台业务层
  题目导入 / 题库中心 / 组卷中心 / 知识点库
  用于本地闭环和演示
        |
        v
题目加工能力层
  /api/capabilities/ocr-flow
  /api/capabilities/question-processing
  ProcessingJob / QuestionPackage / SourceFilePreview
        |
        v
Python worker 能力执行
  OCR / AI 标准化 / AI 解析 / 导出
```

平台对接时应优先消费 `questionPackage`，而不是直接读取本项目内部 Java 表或 Python JSON 文件。OCR 引擎替换时应优先保持 `ocr-flow` outputs 结构不变。

后续演进优先级：

1. 把人工校验保存和状态流转收敛到能力层，形成 `QuestionPackage` 的唯一主状态。
2. 让 Python worker 只接收 Java 提供的文件 URL 或临时路径，不再维护导入任务业务状态。
3. 引入平台回调字段：`externalBizId`、`tenantId`、`callbackUrl`。
4. MinIO 成为文件主路径，Java 管 source preview、下载和临时访问。
5. 提供 OpenAPI 文档和轻量 SDK。
6. 提供可嵌入校验工作台入口，例如 `/embed/question-processing/jobs/{jobId}`。
