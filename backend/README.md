# Backend

本目录是项目唯一后端目录，以 Java Spring Boot 为主后端，Python 只作为必要 worker 保留。

本文面向后续参与 question-engine/backend 开发的工程师，重点说明代码放置位置、Java 后端分层、各模块职责、Java 与 Python worker 的边界，以及新增功能时应该优先修改哪些文件。

相关总体文档见 `../docs/README.md`。理解后端边界时优先阅读 `../docs/delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md`、`../docs/architecture/ENGINE_DELIVERY_BOUNDARY.md`、`../docs/architecture/TECHNICAL_DESIGN.md` 和 `../docs/product/OCR_PHASE_1_SPEC.md`。

## 目录总览

```text
backend/
├── pom.xml
├── README.md
├── src/
│   ├── main/
│   │   ├── java/com/aigeneration/questionbank/
│   │   └── resources/
│   └── test/java/com/aigeneration/questionbank/
├── python-worker/
│   └── app/
└── storage/
```

## 目录边界

- `src/main/java`：Java 主后端，承载业务 API、能力目录、任务状态、数据表、文件存储和平台接入契约。
- `src/main/resources`：Java 配置、数据库 schema、本地 profile 和企业化 profile。
- `src/test`：Java 回归测试，覆盖 system、engine、capability、domain、桥接、文件流、AI、导出和回调。
- `python-worker`：Python OCR/AI/导出 worker，保留 MinerU、模型调用、LaTeX 处理、Pandoc 导出和短期兼容接口。
- `storage`：本地开发运行数据。企业交付时应替换为 MySQL、MinIO 和平台文件中心。

新增业务 API 应优先放在 Java。Python worker 不再承载新的前端业务接口，只提供 `/worker/*` 和短期兼容桥。

## Java 后端总体结构

Java 主包为：

```text
src/main/java/com/aigeneration/questionbank/
├── AiQuestionBankApplication.java
├── common/
├── config/
├── controller/
├── engine/
├── capability/
├── domain/
├── migration/
└── proxy/
```

整体调用方向：

```text
Controller
  -> Service
    -> Mapper / PythonWorkerClient / JavaFileStorageService
      -> Database / Local File / MinIO / Python worker
```

代码依赖原则：

- `controller` 只做 HTTP 入参、路径和 OpenAPI 注解，不直接写数据库。
- `service` 承载业务编排、状态推导、worker 调用和数据转换。
- `mapper` 只做 MyBatis-Plus 表访问，不写业务规则。
- `entity` 只表示 Java 数据表结构，不承载流程逻辑。
- `support` 放跨领域的小工具，例如 ID 和 JSON 辅助。
- `capability` 和 `engine` 是对外交付契约目录，不应塞入复杂业务执行逻辑。
- `python-worker` 只执行 OCR/AI/导出等能力，不新增平台业务状态。

## `AiQuestionBankApplication.java`

Spring Boot 启动入口。

职责：

- 启动 Java backend。
- 扫描 `com.aigeneration.questionbank` 下的 controller、service、mapper、configuration。
- 作为测试类 `@SpringBootTest` 的启动配置。

## `common/`

通用基础组件。

```text
common/
├── ApiResponse.java
└── TraceIdFilter.java
```

- `ApiResponse`：统一响应包装，主要用于系统健康检查等简单接口。
- `TraceIdFilter`：为每个请求生成或透传 trace id，并放入 MDC，便于日志串联。

新增全局过滤器、统一响应、跨模块通用基础对象时放这里。不要把业务对象放在 `common`。

## `config/`

配置绑定和基础 Web 配置。

```text
config/
├── CorsConfig.java
├── EnterpriseProperties.java
├── JavaStorageProperties.java
├── PythonWorkerProperties.java
└── SmartRagStackProperties.java
```

- `CorsConfig`：跨域配置。
- `PythonWorkerProperties`：Python worker 开关、baseUrl、健康检查路径和超时。
- `JavaStorageProperties`：Java 本地文件存储根目录。
- `EnterpriseProperties`：企业化部署相关配置，包含 MySQL、Redis、MinIO、MQ。
- `SmartRagStackProperties`：后端依赖版本清单，对外暴露给系统接口和排障使用。

新增配置项时：

1. 先在 `application.yml` 增加配置和注释。
2. 再在对应 `*Properties` 类中增加字段、getter/setter 和 JavaDoc。
3. 业务代码只注入 properties 类，不直接散落读取环境变量。

## `controller/`

系统级控制器。

```text
controller/
└── SystemController.java
```

`SystemController` 提供 Java 后端系统接口：

- `/api/java/health`：Java backend 健康检查。
- `/api/java/system/versions`：版本清单。
- `/api/java/system/runtime`：运行时环境摘要。
- `/api/java/system/config`：关键配置摘要。
- `/api/java/system/dependencies`：依赖分组。

业务接口不要放在该包。业务接口应放在 `domain/controller`、`capability/controller` 或 `engine/controller`。

## `engine/`

question-engine 总目录和交付边界。

```text
engine/
├── controller/
│   └── EngineCatalogController.java
├── model/
│   └── EngineModels.java
└── service/
    └── EngineCatalogService.java
```

职责：

- 说明 question-engine 是什么。
- 暴露四个核心模块：
  - `question-import`
  - `question-bank`
  - `paper-assembly`
  - `knowledge-base`
- 暴露补充能力：
  - `review-workbench`
  - `ai-flow`
  - `export-flow`
  - `file-flow`
  - `callback-flow`
  - `sdk-openapi`
- 暴露平台必须提供的能力，例如用户/租户、对象存储、worker、大模型、异步和监控。
- 暴露交付边界和接口清单。

主要接口：

- `GET /api/engine`
- `GET /api/engine/modules`
- `GET /api/engine/modules/{code}`
- `GET /api/engine/supplemental-capabilities`
- `GET /api/engine/platform-requirements`
- `GET /api/engine/delivery-boundary`
- `GET /api/engine/interfaces`

新增 engine 模块或调整平台交付边界时，优先改：

- `EngineCatalogService`
- `EngineModels`
- 对应测试 `SystemControllerTest`

## `capability/`

面向平台集成的能力目录和能力接口。

```text
capability/
├── controller/
│   ├── CallbackFlowController.java
│   ├── CapabilityCatalogController.java
│   ├── ExportFlowJobController.java
│   ├── OcrFlowCapabilityController.java
│   └── QuestionProcessingCapabilityController.java
├── model/
│   └── QuestionProcessingCapabilityModels.java
└── service/
    ├── CapabilityCatalogService.java
    ├── OcrFlowCapabilityService.java
    └── QuestionProcessingCapabilityService.java
```

### controller

- `CapabilityCatalogController`：`/api/capabilities` 能力总目录。
- `OcrFlowCapabilityController`：`/api/capabilities/ocr-flow`，OCR provider 能力描述和 runtime。
- `QuestionProcessingCapabilityController`：`/api/capabilities/question-processing`，主加工能力入口，包括任务创建、任务查询和标准题目包输出。
- `ExportFlowJobController`：`/api/capabilities/export-flow/jobs`，导出 job 查询。
- `CallbackFlowController`：`/api/capabilities/callback-flow`，回调 runtime、测试发送、事件列表和重试。

### model

- `QuestionProcessingCapabilityModels`：标准题目包、加工任务视图、题图、公式校验、来源证据和告警 record。

这些模型是面向平台和 SDK 的契约，不应随意改字段名。确需变更时要同步 OpenAPI、SDK 文档、测试和调用方。

### service

- `CapabilityCatalogService`：聚合所有补充能力描述和 runtime。
- `OcrFlowCapabilityService`：描述 OCR-Flow provider 合约、配置键、worker 端点和 runtime。
- `QuestionProcessingCapabilityService`：把导入任务、导入题、题图和 OCR 状态组合成标准 `question-package.v1`。

新增能力目录时：

1. 在 `CapabilityCatalogService` 增加能力描述。
2. 如果有 API，新增 `capability/controller`。
3. 如果有稳定出参，新增 `capability/model`。
4. 在 `EngineCatalogService.interfaces()` 中确保接口能进入清单。
5. 补充 `SystemControllerTest` 或领域测试。

## `domain/`

核心业务域。这里是 Java backend 的主要业务实现。

```text
domain/
├── controller/
├── entity/
├── mapper/
├── service/
└── support/
```

### `domain/controller/`

业务 HTTP API 层。

```text
domain/controller/
├── AiFlowController.java
├── BankQuestionController.java
├── ImportTaskBankBridgeController.java
├── ImportTaskMetadataBridgeController.java
├── ImportTaskOrchestrationController.java
├── KnowledgePointController.java
├── PaperController.java
└── QuestionImageFlowController.java
```

控制器职责：

- 接收 HTTP 请求。
- 声明 path、method、query、path variable、multipart 参数。
- 使用 `@Operation` 补充接口说明。
- 调用对应 service。
- 不直接访问 mapper。
- 不直接拼装复杂业务状态。

各控制器说明：

- `ImportTaskMetadataBridgeController`
  - 导入任务列表、创建、详情、更新、删除、批量删除、原文件预览。
  - Java API 入口仍兼容历史 `/api/import-tasks`。
  - 内部通过 bridge service 调 worker，并同步 Java 表。
- `ImportTaskOrchestrationController`
  - 导入任务重试入口。
  - 当前主要重试失败 OCR job。
- `ImportTaskBankBridgeController`
  - 导入题入库入口。
  - 单题入库和整任务批量入库。
- `QuestionImageFlowController`
  - 导入题和题库题的题图上传、题图库选择、题图预览。
- `AiFlowController`
  - 导入题/题库题 AI 标准化。
  - 导入题/题库题 AI 解析。
  - 临时 Markdown AI 处理。
  - AI job 查询。
- `BankQuestionController`
  - 题库题 CRUD 和筛选。
- `PaperController`
  - 试卷 CRUD 和导出入口。
- `KnowledgePointController`
  - 知识点 CRUD。

新增业务接口时，优先按业务域放到已有 controller；只有形成新的稳定能力边界时才新增 controller。

### `domain/entity/`

数据库实体层，与 `schema.sql` 中的 Java 表对应。

```text
domain/entity/
├── AiJobEntity.java
├── BankQuestionEntity.java
├── CallbackEventEntity.java
├── ExportJobEntity.java
├── ImportQuestionEntity.java
├── ImportQuestionImageEntity.java
├── ImportTaskEntity.java
├── KnowledgePointEntity.java
├── PaperEntity.java
└── StorageFileEntity.java
```

实体与表关系：

- `KnowledgePointEntity` -> `java_knowledge_points`
- `BankQuestionEntity` -> `java_bank_questions`
- `ImportTaskEntity` -> `java_import_tasks`
- `ImportQuestionEntity` -> `java_import_questions`
- `ImportQuestionImageEntity` -> `java_import_question_images`
- `StorageFileEntity` -> `java_storage_files`
- `PaperEntity` -> `java_papers`
- `ExportJobEntity` -> `java_export_jobs`
- `AiJobEntity` -> `java_ai_jobs`
- `CallbackEventEntity` -> `java_callback_events`

实体只描述字段、表名和 getter/setter。业务状态推导、JSON 解析、worker 调用不要放在 entity。

### `domain/mapper/`

MyBatis-Plus Mapper 层。

```text
domain/mapper/
├── AiJobMapper.java
├── BankQuestionMapper.java
├── CallbackEventMapper.java
├── ExportJobMapper.java
├── ImportQuestionImageMapper.java
├── ImportQuestionMapper.java
├── ImportTaskMapper.java
├── KnowledgePointMapper.java
├── PaperMapper.java
└── StorageFileMapper.java
```

当前 Mapper 基本继承 `BaseMapper<T>`，查询条件主要在 service 中用 `QueryWrapper` 或 `LambdaQueryWrapper` 组织。

如需复杂 SQL：

- 优先确认是否能用 MyBatis-Plus wrapper。
- 必须写自定义 SQL 时，将方法声明放 mapper，并明确命名。
- 不要把业务编排写进 mapper。

### `domain/service/`

业务核心服务层。

```text
domain/service/
├── AiFlowOrchestrationService.java
├── BankQuestionService.java
├── CallbackFlowService.java
├── ImportQuestionSyncService.java
├── ImportTaskBankBridgeService.java
├── ImportTaskMetadataBridgeService.java
├── ImportTaskMetadataService.java
├── ImportTaskOrchestrationService.java
├── JavaFileStorageService.java
├── KnowledgePointService.java
├── PaperExportFlowService.java
├── PaperService.java
├── PythonWorkerClient.java
└── QuestionImageFlowService.java
```

服务职责按业务链路划分。

#### 导入任务链路

- `ImportTaskMetadataBridgeService`
  - Java 到 Python worker 的导入任务桥。
  - 创建任务时先保存上传文件到 Java 文件存储。
  - worker 创建成功后，把临时文件业务 ID 改成真实任务 ID。
  - 调用 worker 后同步 Java 侧任务和题目快照。
  - 原文件预览优先使用 Java 文件存储，历史任务才回退 worker。

- `ImportTaskMetadataService`
  - Java 侧导入任务快照服务。
  - 根据 worker 返回的 OCR job、题目状态、失败原因推导中文任务状态。
  - 同步 `java_import_tasks`。
  - 任务变化时触发 `ImportQuestionSyncService` 同步题目。

- `ImportQuestionSyncService`
  - 同步导入题和导入题图。
  - 支持 AI 结果回写。
  - 支持人工追加题图。
  - 同步时删除 worker 最新结果中已经不存在的题目。

- `ImportTaskOrchestrationService`
  - 导入任务编排服务。
  - 当前主要负责失败 OCR job 重试。

- `ImportTaskBankBridgeService`
  - 调用 worker 入库接口。
  - 将 worker 返回的题库题 payload upsert 到 Java 题库题表。

#### 题库链路

- `BankQuestionService`
  - 题库题 CRUD。
  - 题目筛选。
  - 题图追加。
  - AI 标准化/解析结果回写。
  - 导入题入库后的 upsert。

- `QuestionImageFlowService`
  - 导入题题图上传。
  - 题库题题图上传。
  - 从任务题图库选择题图。
  - 题图预览，优先 Java 文件存储，必要时回退 worker。

#### AI 链路

- `AiFlowOrchestrationService`
  - Java 侧 AI 标准化和 AI 解析编排。
  - 创建 `java_ai_jobs` 记录。
  - 调 Python worker `/worker/ai/standardize` 和 `/worker/ai/analysis`。
  - 读取题图并转成 data URL 传给 worker。
  - 限制 AI 请求内联图片数量和大小。
  - AI job 请求日志会脱敏内联图片数据。
  - 根据目标类型回写导入题或题库题。

#### 组卷和导出链路

- `PaperService`
  - 试卷 CRUD。
  - 题目引用展开。
  - 简单规则选题。
  - 分值构建。
  - 试卷响应序列化。

- `PaperExportFlowService`
  - 创建导出 job。
  - 调 Python worker `/worker/export/render`。
  - 保存导出文件到 Java 文件存储。
  - 返回 inline 文件响应。

#### 文件和回调链路

- `JavaFileStorageService`
  - 统一保存导入原文件、导入题图、题库题图、导出文件。
  - 支持 LOCAL 和 MINIO 两种存储。
  - 提供 inline 预览、字节读取、data URL 生成。
  - 本地路径有根目录校验，避免路径逃逸。

- `CallbackFlowService`
  - 创建 callback event。
  - HMAC-SHA256 签名。
  - HTTP 投递。
  - 失败重试和死信状态。
  - 暂未接入 MQ 时使用本地表兜底。

- `PythonWorkerClient`
  - Java 到 Python worker 的统一 HTTP 客户端。
  - 负责 JSON 请求、文件响应、超时、错误转换和响应头复制。

#### 基础业务

- `KnowledgePointService`
  - 本地知识点 CRUD。
  - 企业平台已有权威知识点时，可改造成只读同步或映射缓存。

新增 service 时，应先判断它属于哪条链路。若只是已有链路的一个步骤，优先放入已有 service；只有职责边界独立且被多个控制器复用时才新增 service。

### `domain/support/`

领域通用工具。

```text
domain/support/
├── Ids.java
└── JsonSupport.java
```

- `Ids`：生成带业务前缀的 ID。
- `JsonSupport`：统一读写 JSON 字符串字段，避免 service 中重复处理 Jackson 类型。

## `migration/`

启动时迁移和 schema 兼容。

```text
migration/
├── LibraryStoreMigrator.java
└── SchemaMigrator.java
```

- `LibraryStoreMigrator`
  - 从历史 `storage/library_store.json` 迁移数据到 Java domain 表。
  - 默认由 `java-domain.migration.enabled` 控制。
  - 迁移导入任务、知识点、题库题和试卷。

- `SchemaMigrator`
  - 启动时补齐当前版本新增表和列。
  - 主要用于本地开发、H2 和已有库兼容。
  - 生产环境建议使用受控迁移工具替代。

新增表时需要同步：

1. `src/main/resources/schema.sql`
2. 对应 `entity`
3. 对应 `mapper`
4. 如需兼容旧库，补 `SchemaMigrator`
5. 测试覆盖表结构相关流程

## `proxy/`

Python worker API 代理过滤器。

```text
proxy/
└── PythonWorkerProxyFilter.java
```

职责：

- 拦截仍未被 Java 接管的 `/api/**` 请求。
- 转发到 Python worker。
- Java 已接管的路径跳过代理，交给 Spring MVC controller。
- 过滤逐跳 HTTP header。

当前 Java 已接管的主要路径包括：

- `/api/engine/**`
- `/api/capabilities/**`
- `/api/java/**`
- `/api/import-tasks/**`
- `/api/question-bank/questions/**`
- `/api/papers/**`
- `/api/knowledge-points/**`
- AI、题图、导出、回调相关路径

如果新增 Java controller 路径与历史 worker 路径重叠，需要检查 `PythonWorkerProxyFilter#isJavaDomainPath`，确保请求不会被错误代理到 worker。

## `src/main/resources`

```text
src/main/resources/
├── application.yml
└── schema.sql
```

- `application.yml`
  - server、Spring、数据源、Actuator、OpenAPI、Knife4j、worker、企业组件和本地存储配置。
  - 默认 profile 为 `test`。
  - MySQL profile 通过 `SPRING_PROFILES_ACTIVE=mysql` 开启。

- `schema.sql`
  - Java domain 表初始化脚本。
  - H2 本地开发和测试会使用。
  - 表结构应与 `domain/entity` 保持一致。

## `src/test`

```text
src/test/java/com/aigeneration/questionbank/
├── SystemControllerTest.java
└── DomainControllerTest.java
```

- `SystemControllerTest`
  - 覆盖健康检查、能力目录、OCR-Flow 描述、engine 目录和接口清单。

- `DomainControllerTest`
  - 覆盖 Java domain 业务闭环。
  - 使用 H2 内存库。
  - 使用 JDK `HttpServer` 模拟 Python worker。
  - 覆盖 CRUD、导入任务桥接、题图文件流、标准题目包、OCR 失败状态、AI 编排、导出和回调。

新增 Java 业务代码时，优先在这两个测试类中补场景；如果场景明显独立，可新增测试类，但仍应使用同样的 H2 和 MockMvc 风格。

## Python worker 结构

```text
python-worker/app/
├── main.py
├── worker_routes.py
├── worker_base.py
├── ocr_flow.py
├── ocr_execution.py
├── ocr_processing.py
├── import_services.py
├── question_markdown.py
├── math_normalizer.py
├── llm_splitter.py
└── export_service.py
```

Python worker 当前职责：

- OCR provider 执行，当前默认 MinerU。
- OCR 输出收集和结构化拆题。
- LaTeX/数学公式规范化。
- 大模型拆题、标准化和解析。
- Pandoc/DOCX/PDF 导出。
- 短期兼容历史 `/api/**` 接口。

主要文件说明：

- `main.py`：FastAPI 应用入口。
- `worker_routes.py`：worker 路由和历史兼容路由。
- `worker_base.py`：Pydantic 模型、本地 store、OCR job 文件和 runtime 辅助。
- `ocr_flow.py`：OCR provider 抽象和 MinerU provider。
- `ocr_execution.py`：OCR job 执行、Markdown 直通、DOC 转换、provider 调用。
- `ocr_processing.py`：OCR 输出收集、结构化题目解析、语义修复。
- `import_services.py`：历史本地导入任务、题库、组卷和题图服务。
- `question_markdown.py`：题目 Markdown、题图引用、选项拆分和编辑回写。
- `math_normalizer.py`：数学公式规范化和校验。
- `llm_splitter.py`：大模型拆题、标准化、解析和结果归一化。
- `export_service.py`：Markdown、DOCX、PDF、Pandoc 导出。

新增 Python 代码原则：

- 新 OCR provider 放 `ocr_flow.py`，并保持输出结构与现有 `collect_outputs` 兼容。
- 新 AI worker 能力放 `/worker/*` 路由，不新增面向前端的 `/api/*` 业务接口。
- 新导出格式优先扩展 `export_service.py` 和 `/worker/export/render`。
- 任何 worker 输出结构变化，都必须同步 Java service、能力目录、OpenAPI 文档和测试。

## 关键业务链路

### 题目导入和标准题目包

```text
POST /api/capabilities/question-processing/jobs
  -> QuestionProcessingCapabilityController
  -> QuestionProcessingCapabilityService
  -> ImportTaskMetadataBridgeService
  -> JavaFileStorageService 保存上传原文件
  -> Python worker 创建 OCR job
  -> ImportTaskMetadataService 同步任务状态
  -> ImportQuestionSyncService 同步题目和题图
```

查询标准题目包：

```text
GET /api/capabilities/question-processing/jobs/{jobId}/question-package
  -> QuestionProcessingCapabilityService
  -> ImportTaskMetadataService
  -> ImportQuestionSyncService
  -> QuestionProcessingCapabilityModels.QuestionPackage
```

### AI 标准化和解析

```text
POST /api/import-tasks/{taskId}/questions/{questionId}/standardize/ai
POST /api/import-tasks/{taskId}/questions/{questionId}/analysis
POST /api/question-bank/questions/{questionId}/standardize/ai
POST /api/question-bank/questions/{questionId}/analysis
  -> AiFlowController
  -> AiFlowOrchestrationService
  -> PythonWorkerClient
  -> /worker/ai/standardize 或 /worker/ai/analysis
  -> 回写 ImportQuestion 或 BankQuestion
```

### 题图上传和复用

```text
POST /api/import-tasks/{taskId}/questions/{questionId}/images
POST /api/question-bank/questions/{questionId}/images
  -> QuestionImageFlowController
  -> QuestionImageFlowService
  -> JavaFileStorageService
  -> ImportQuestionSyncService 或 BankQuestionService
```

### 试卷导出

```text
GET /api/papers/{paperId}/export
  -> PaperController
  -> PaperExportFlowService
  -> PaperService 读取试卷和题目
  -> PythonWorkerClient 调 /worker/export/render
  -> JavaFileStorageService 保存导出文件
```

### 回调投递

```text
POST /api/capabilities/callback-flow/test
POST /api/capabilities/callback-flow/events/{eventId}/retry
POST /api/capabilities/callback-flow/events/retry-due
  -> CallbackFlowController
  -> CallbackFlowService
  -> java_callback_events
```

## 数据表说明

核心表在 `src/main/resources/schema.sql` 中定义：

- `java_knowledge_points`：知识点快照。
- `java_bank_questions`：题库题快照。
- `java_import_tasks`：导入任务、OCR job 和状态。
- `java_import_questions`：导入题快照。
- `java_import_question_images`：导入题图快照。
- `java_storage_files`：Java 文件元数据。
- `java_papers`：试卷定义。
- `java_export_jobs`：导出 job。
- `java_ai_jobs`：AI job。
- `java_callback_events`：回调事件。

JSON 字段统一由 `JsonSupport` 读写。不要在多个 service 中手写 ad hoc JSON 解析逻辑。

## 运行和验证

常用 Java 验证：

```bash
cd backend
mvn test
```

Python worker 语法检查：

```bash
cd backend
python -m compileall python-worker/app
```

本地联调脚本见：

```text
../scripts/start_project_with_java_backend.sh
../scripts/smoke_local_platform_business.py
```

## 新增代码放置规则

新增功能前先判断它属于哪类：

- 系统健康、版本、运行时信息：`controller/SystemController.java`。
- question-engine 目录、模块、交付边界：`engine/*`。
- 面向平台的能力描述、标准题目包、能力 runtime：`capability/*`。
- 业务 CRUD、导入任务、题库、组卷、知识点、题图：`domain/controller` + `domain/service`。
- 数据表：`domain/entity` + `domain/mapper` + `schema.sql`。
- 文件存储：优先扩展 `JavaFileStorageService`。
- 调 Python worker：统一走 `PythonWorkerClient`。
- Python OCR provider：`python-worker/app/ocr_flow.py`。
- Python AI 能力：`python-worker/app/llm_splitter.py` 和 `/worker/*` 路由。
- Python 导出能力：`python-worker/app/export_service.py`。

新增接口时必须同步：

1. Controller JavaDoc 和 `@Operation`。
2. Service 方法 JavaDoc。
3. `EngineCatalogService.interfaces()` 或能力目录。
4. OpenAPI/接口文档，如涉及平台调用。
5. `src/test` 回归测试。
6. `../docs/CHANGELOG.md` 或相关规格文档。

## 开发注意事项

- Java 是默认业务入口；不要把新的前端业务 API 写回 Python worker。
- worker 可以保留短期兼容接口，但长期平台接入应走 Java API 和能力目录。
- 状态归属优先在 Java 表中体现，worker 只返回执行结果。
- 文件优先由 Java 记录元数据和提供预览；历史 worker 文件路径只作为回退。
- 能力目录和标准题目包字段属于平台契约，修改前必须评估兼容性。
- `PythonWorkerProxyFilter` 的路径判断会影响请求落点；新增 Java API 后要检查是否被代理误拦截。
- 任何跨 Java/Python 的输出结构变化，都要同时改测试，避免本地通过但平台调用失败。
