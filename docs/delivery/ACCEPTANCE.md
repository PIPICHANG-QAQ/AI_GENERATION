# 本期验收标准

## 文档定位

本文件描述当前本期验收标准。项目不再按历史阶段口径拆分，统一验收 `question-engine` 能力服务、Java 主后端、Python worker 和 `local-platform` 本地小平台。

## 本地部署与启动

- `./scripts/deploy_local.sh` 能在干净迁移目录中自动安装基础 worker 依赖和前端依赖、自动避让被其它项目占用的默认端口、启动 Python worker / Java backend / 前端、完成健康检查并通过 basic smoke。
- `./scripts/deploy_local.sh --with-mineru` 能安装或复用 MinerU，重启 worker，并通过 OCR smoke。
- `./scripts/deploy_local.sh --with-ai` 在未配置 `DASHSCOPE_API_KEY` 或 `ALIYUN_LLM_API_KEY` 时必须启动前失败并给出明确提示；配置 Key 后必须通过 AI smoke。
- `.run/deploy.env` 必须记录实际端口和 URL，`.run/pids/` 必须记录三类服务 PID，`.run/logs/` 必须记录三类服务日志。
- 部署脚本健康检查失败时必须输出相关日志最后 80 行。
- `./scripts/health_watchdog.sh --once` 必须能读取 `.run/deploy.env` 并检查 Python worker、Java backend、前端、Java worker bridge；失败时必须输出 `.run/logs/` 日志尾部。
- Python worker 部署默认不得启用 `uvicorn --reload`；只有 `--dev-reload` 或开发兼容入口才允许启用 reload。
- `./scripts/install_backend.sh` 能安装或同步 Python worker 基础依赖。
- `python scripts/check_mineru.py` 能返回 MinerU 是否已安装和可用。
- `./scripts/start_java_backend.sh` 能启动 Java 主后端，默认端口 `8018`。
- `./scripts/start_project_with_java_backend.sh` 作为开发兼容入口，必须转调 `deploy_local.sh --dev-reload`。
- Java 服务运行时必须使用 JDK 17，`/api/java/health` 中 `javaVersion` 应以 `17` 开头。
- `GET /api/java/health` 返回 `success=true`、`status=ok` 和服务名 `ai-question-bank-java`。
- `GET /api/java/worker` 在 Python worker 可达时返回 `reachable=true`，不可达时返回明确错误。
- `GET /api/health` 通过 Java `8018` 访问时应能代理到 Python worker 并返回正常。
- 前端默认访问 Java backend `http://localhost:8018`。
- `local-platform` 可以启动，并在 `http://localhost:5173` 访问。
- 本地默认模式不强制连接 MySQL、Redis、MinIO 或 MQ。
- Java 默认 H2 本地库可启动；启用 `mysql` profile 时可通过环境变量连接 MySQL。

## 目录与交付边界

- 根目录应保留 `backend/`、`local-platform/`、`question-engine/`、`docs/` 和 `scripts/`。
- 旧 `backend-java/`、旧 `frontend/`、历史 `protocal/`、`artifacts/` 和 `tmp/` 不应作为当前源码目录存在。
- `backend/` 是唯一后端目录，Java 是主后端。
- `backend/python-worker/` 只保留 OCR、AI、LaTeX 和导出 worker 能力。
- `local-platform/` 是本地演示小平台，不属于公司平台交付核心。
- `question-engine/README.md` 必须说明能力发动机交付范围和排除范围。
- `GET /api/engine/delivery-boundary` 必须包含 Java engine/capability/domain/common/config/migration/proxy 代码路径，并排除 `local-platform`、历史原型仓库和 `backend/storage`。

## 能力目录与平台契约

- `GET /api/engine` 必须返回能力发动机编码 `question-engine`。
- `GET /api/engine` 必须返回四个主模块：`question-import`、`question-bank`、`paper-assembly`、`knowledge-base`。
- `GET /api/engine` 必须返回六个补充能力：`review-workbench`、`ai-flow`、`export-flow`、`file-flow`、`callback-flow`、`sdk-openapi`。
- `GET /api/engine/modules/question-import` 必须说明题目导入模块依赖 OCR-Flow、AI-flow、file-flow 和 review-workbench。
- `GET /api/engine/modules/paper-assembly` 必须说明组卷模块依赖题库能力和 export-flow。
- `GET /api/capabilities` 必须包含 `ocr-flow`、`question-processing`、`review-workbench`、`ai-flow`、`export-flow`、`file-flow`、`callback-flow` 和 `sdk-openapi`。
- 能力 API 不得被 Python fallback 代理拦截。
- `GET /api/capabilities/question-processing` 必须返回能力编码、包版本 `question-package.v1`、输入输出边界、worker 入口和平台自有职责。
- `POST /api/capabilities/question-processing/jobs` 必须能创建加工任务并返回 `ProcessingJob`。
- `GET /api/capabilities/question-processing/jobs/{jobId}` 必须返回任务视图，包括中文业务状态和稳定英文 `processingStatus`。
- `GET /api/capabilities/question-processing/jobs/{jobId}/question-package` 必须返回 `question-package.v1`，包含任务、原文件、题目、题图、答案、解析、知识点候选、难度候选、分值候选和 source evidence。
- `question-engine/openapi/question-engine.v1.yaml` 必须存在，并作为平台契约和 SDK 的源头。
- `question-engine/sdk/generated/typescript` 和 `question-engine/sdk/generated/java` 必须存在，并至少覆盖能力目录、engine 目录、加工任务创建/查询和题目包获取。
- `question-engine/sdk/examples` 只能作为旧手写 SDK 示例，不得作为平台正式集成主入口。

## OCR-Flow

- `GET /api/capabilities/ocr-flow` 必须返回 provider 合约、默认 provider、配置键和 worker endpoints。
- `GET /api/capabilities/ocr-flow/runtime` 在 Python worker 可达时必须返回 `selectedProvider`、`availableProviders`、`allowedExtensions` 和 provider 状态。
- OCR 上传必须支持 `.pdf`、图片、`.md/.markdown`、`.doc`、`.docx`、`.pptx`、`.xlsx`。
- `.md/.markdown` 必须直接进入结构化解析。
- `.doc` 必须先转换为 `.docx`，转换失败时返回明确错误。
- 当前 OCR provider 缺失或不可用时，页面必须显示明确错误；PDF、图片和 Office 导入任务必须在创建前失败，不得生成空的 `OCR failed` 任务。
- OCR 成功后必须返回 `sections`、`questions`、`splitter`、`mathValidation` 和图片资源。
- worker 的 `library_store.json` 和 OCR job JSON 必须使用原子写入和 `.bak` 备份；主文件损坏时应优先回退备份，不得直接让导入任务列表清空。
- Java 导入任务详情在 worker 兼容 store 缺失任务时必须回退 `java_import_tasks` 持久快照；当 OCR job 已成功且题目未同步时，应通过内部恢复接口按 OCR job 重建题目。
- 大题必须包含标题、题型和其下题目列表。
- 每道题必须包含题号、题型、题干、题图数组、选项数组和小问字段；新字段为 `subQuestions`，兼容字段 `children` 必须同步返回。
- 含小问的大题必须把答案、解析、题型、难度、分值和知识点落在各小问上，父题 `answer` / `analysis` 保持为空。
- 选择题的 `stemMarkdown` 不应包含 A/B/C/D 选项正文；`- A.`、`A．`、`A、`、`(A)`、标准 `tasks`、误识别 `ttasks` 和裸 `\task` 行必须拆入 `options` 并在人工校验、题库和组卷预览中独立渲染。
- 人工校验和题库编辑不得把选择题选项拆成独立输入控件；已有 `options` 但源码无选项块时，前端必须自动补成标准 `tasks` 块，用户在同一个题干源码 textarea 中编辑 `\task` 内容，保存时解析回 `stemMarkdown + options`。
- 图片相对路径必须解析为后端可访问资源。
- 大模型未配置或调用失败时，OCR 任务仍应成功返回本地规则拆题结果。
- OCR 结果必须说明拆题来源和兜底原因。

## 公式、题图与 Markdown 渲染

- Markdown 中行内公式 `$...$` 和块级公式 `$$...$$` 必须被渲染为数学公式。
- 合法块级公式不应被误判为连续公式边界错误。
- OCR 产生的异常公式边界应被本地标准化为可渲染 Markdown。
- 公式分隔符、花括号、方括号或环境仍不匹配时，后端应返回 warning，前端应展示需复核状态。
- 疑似指数被识别为引号等语义 OCR 错误时，应提示使用 AI 标准化或人工复核。
- OCR 自动语义修复只有在大模型已配置、置信度足够且修复后风险降低时才可自动写回；人工触发的 AI 标准化默认只返回候选，必须经人工应用保存。
- 题图必须作为题干内容展示。
- 题目保存和入库时必须同时保留 `images` 结构化字段和 Markdown 图片引用。
- 人工校验、题库列表、题库编辑、组卷选题池和导出都必须能看到题图。

## AI-flow

- `GET /api/capabilities/ai-flow/runtime` 在 Python worker 可达时必须返回大模型启用状态、配置状态、provider、model 和 worker endpoint。
- AI runtime 不得返回 API Key。
- `GET /api/capabilities/ai-flow/jobs` 必须由 Java 返回 AI job 列表，支持按 targetType、targetId 和 status 过滤。
- 导入题和题库题 AI 标准化必须由 Java 创建 job、调用 Python worker，并记录成功或失败。
- 导入题 AI 标准化必须参考同题原始 OCR 文本。
- 题库题如果来自导入任务，AI 标准化必须能回溯源导入任务 OCR 文本。
- AI 标准化默认必须返回候选 `markdown`、`writeResult=false` 和 AI job 记录，不得直接覆盖题目 `manualMarkdown`。
- AI 标准化只有在请求显式传入 `writeResult=true` 或 `apply=true`，且候选非低置信、`candidateSevereIssues` 为空、未设置 `writeBlocked=true` 时，才允许由 Java 写回题目。
- AI 标准化如果从当前题干或同题 OCR 上下文中抽取出本题 `answer` 或 `analysis`，前端只应在用户应用候选时回填对应字段；未返回时不得清空用户当前内容。
- AI 标准化应返回严重 LaTeX 风险诊断，并在确定性分隔符修复命中时返回 `standardizer.latexDelimiterRepaired=true`。
- 导入题和题库题 AI 解析必须由 Java 创建 job、调用 Python worker，并在模型返回答案或解析时写回对应题目草稿。
- 带题图的导入题或题库题执行 AI 解析时，Java 必须把题目已保存题图转成模型可读图片输入发给 Python worker；AI job 查询结果不得暴露完整内联 base64 图片。
- AI 解析返回答案时，前端必须自动回填答案；模型未返回答案时，不得清空用户当前答案。
- 未配置大模型时，AI 接口必须返回明确错误，不得泄露密钥。

## 导入任务与人工校验

- 后端必须提供导入任务列表、创建、详情、重命名、删除和批量删除接口。
- 新建导入任务必须包含学段、学科、年级、地区、年份和标题。
- 新建导入必须支持上传试卷文件和答案文件。
- 创建导入任务后必须直接进入该任务的导入 OCR 工作台。
- Java 创建导入任务时必须先保存原文件副本和文件元数据，再调用 Python worker。
- Java 调用 Python worker 失败时必须清理本次未关联成功的文件副本和元数据。
- `GET /api/import-tasks/{taskId}/source/{paper|answer}` 必须由 Java 优先返回原文件预览；历史任务没有 Java 文件记录时可回退 Python。
- 导入任务状态必须包含：处理中、待校验、部分完成、已完成、失败、可重试。
- 导入任务状态必须由 Java 根据 OCR 状态、失败原因、重试标记和题目状态派生。
- Java bridge 返回的任务对象必须回填 Java 派生后的 `status`、`paperOcrStatus`、`answerOcrStatus` 和 `failureReason`。
- 导入题状态必须包含：待校验、已校验、已入库。
- OCR 完成后必须生成待校验题目。
- 配置大模型后，导入题目应自动补全题型、答案、解析、知识点、难度和分值。
- 教师上传的试卷或答案 OCR 文本包含答案解析时，AI 补全必须尝试按题号和题干语义匹配到对应题。
- 缺少答案或解析的题保持空值，并提示复核。
- 缺少 OCR 原文证据的模型答案/解析不得自动写入。
- 人工校验时必须能修改 Markdown + LaTeX、题型、答案、解析、知识点、难度和分值。
- 人工校验时必须支持复合编辑器，能维护大题题干以及每个小问的题干、答案、解析、分值和知识点。
- 人工校验预览态必须渲染题目解析，不能显示原始源码。
- 保存人工编辑时，如果本地标准化会引入更严重 LaTeX 风险，后端必须保留用户提交内容。
- 已校验题目必须支持单题入库和批量入库。
- `POST /api/import-tasks/{taskId}/retry` 必须由 Java 接管，失败 OCR job 可重试时应调用 Python worker retry 并回写状态。

## file-flow

- `GET /api/capabilities/file-flow/runtime` 必须返回当前 LOCAL/MINIO 存储模式、本地根目录、MinIO bucket 摘要和 engine 管理的业务文件类型。
- Java 必须提供 `java_storage_files` 表，用于保存业务归属、字段名、原始文件名、内容类型、大小、存储类型、本地路径或 MinIO object key。
- 默认本地模式下，Java 上传文件副本必须写入 `java-storage.local-root`。
- 启用 MinIO 时，应通过 MinIO SDK 写入配置 bucket。
- 导入题题图上传、导入题图片库、题库题题图上传、题库题图片库和图片访问必须由 Java `file-flow` 接管。
- 每个导入任务必须能返回任务级题图库。
- 人工校验题目必须支持本地上传题图，也必须支持从当前任务题图库选择题图并关联到当前题目。
- 历史 Python 图片 URL 可以作为兼容回退。

## 题库中心

- 题库中心必须支持搜索题干、答案、解析和知识点。
- 题库中心必须支持按题型、难度、知识点、学科、年级、地区和年份筛选。
- 筛选面板必须稳定，不得在切换页面后排版混乱。
- 题库中心必须支持题目新增、查看、修改、删除和批量删除。
- 修改题目时必须复用 Markdown + LaTeX 校验逻辑。
- 含小问题目必须显示“含 N 小问”标识，并在查看和编辑态逐个渲染小问题干、答案和解析。
- 题库题创建、更新和导入题入库必须持久化 `subQuestions`，且不得把小问答案/解析写到父题答案/解析。
- 修改题目时必须复用人工校验的 AI 解析和题图管理能力。
- 题库题上传题图必须写入后端图片接口，返回地址在前端可正常显示。

## 知识点库

- 知识点库必须支持按名称、学科、年级和说明筛选。
- 知识点库必须支持新增、编辑、删除、批量删除和列表查看。
- 新建知识点时名称必填，默认学科为数学、年级为高一。
- 删除操作必须二次确认。

## 组卷中心与导出

- 组卷中心必须支持试卷列表、新建试卷选题和试卷编辑器三种视图。
- 试卷必须包含学科、年级字段。
- 试卷列表必须支持按关键词、学科和年级联合筛选。
- 选题页必须支持关键词、题型、难度、学科、年级、地区、年份和知识点筛选。
- 勾选状态必须跨分页和跨筛选保留。
- 新建选题列表勾选含小问的大题时必须默认全选所有小问，并支持展开后按小问取消/勾选。
- 已选数量和清空已选必须可见。
- 未选择题目不得进入试卷编辑器。
- 二次编辑试卷追加题目时，必须复用新建试卷的完整选题交互。
- 已在试卷中的题目必须禁用。
- 试卷编辑器必须支持标题、学科、年级、副标题/考试名称、学校、考试时长、考生须知、答案解析显示策略和试卷头预览。
- 试卷编辑器必须支持编辑 `subSelections`，展示已选 N/M 和所选小问合计分，且不允许取消到 0 个小问。
- `paper.create` / `paper.update` 必须接受可选 `subSelections`；`paper.get` / `paper.list` 必须原样返回，并内嵌完整 `subQuestions`。
- 缺失、空或失效的 `subSelections[questionId]` 必须按全选处理，兼容旧试卷。
- 修改试卷小问选择不得修改题库原题；试卷计分仍以 `scores[questionId]` 为准。
- 发布试卷时标题必填，题目数量必须大于 0。
- 点击发布后必须先展示发布前预览，用户确认后才能保存发布。
- 发布前预览和导出必须只渲染所选小问；无小问题目按整题渲染。
- `GET /api/capabilities/export-flow/runtime` 在 Python worker 可达时必须返回 Pandoc、XeLaTeX、中文字体、导出格式和 fallback 状态。
- `GET /api/capabilities/export-flow/jobs` 必须由 Java 返回导出 job 列表。
- `GET /api/papers/{paperId}/export` 必须由 Java 创建导出任务、调用 Python worker 生成文件、保存导出文件并返回下载响应。
- DOCX/PDF 导出优先走 Markdown + Pandoc 链路。
- 导出必须包含卷头、题目、答案、解析、分值和题图。
- PDF 页面渲染后不能出现明显乱码、空白页或公式被粗糙文本替换的问题。

## callback-flow

- `GET /api/capabilities/callback-flow/runtime` 必须返回 HTTP 回调签名算法、事件类型、本地事件表状态和 MQ 配置摘要。
- `POST /api/capabilities/callback-flow/test` 必须能创建 Java callback event。
- HTTP 回调必须携带 `X-Question-Engine-Signature`。
- callback event 必须记录发送成功或失败。
- 手动重试入口必须可用。
- callback event 必须支持 `idempotencyKey`，重复请求不得创建重复事件。
- callback event 超过 `maxRetryCount` 后必须进入 `dead_letter` 状态。
- `POST /api/capabilities/callback-flow/events/retry-due` 必须能扫描并重试到期失败事件。

## 前端界面

- 首屏必须是题库业务后台，不是介绍页。
- 左侧导航必须包含题目导入、题库中心、组卷中心、知识点库。
- 导入 OCR 工作台左侧必须预览试卷原文件，并可切换答案原文件。
- 原文件预览失败时必须展示明确错误，不能把 JSON 错误当作 PDF/图片渲染。
- 右侧默认展示题目标签，不默认展示整篇 OCR Markdown。
- 题目标签页必须按大题分组展示。
- 每道题必须独立卡片展示题干、题图、答案、解析和题型扩展内容。
- 桌面和移动宽度下布局都可用，不得出现表单、源码、预览或按钮互相遮挡。

## 工程化验证

- `cd backend && JAVA_HOME=$(/usr/libexec/java_home -v 17) mvn test` 必须通过。
- `backend/python-worker/.venv/bin/python -m py_compile backend/python-worker/app/*.py` 必须通过。
- `PYTHONPATH=backend/python-worker backend/python-worker/.venv/bin/python -c "from app.main import app; print(app.title)"` 必须能导入 FastAPI app。
- `cd local-platform && npm run build` 必须通过。
- `GET /api/java/stack` 必须返回与 SmartRAG 对齐的 Java 技术栈版本清单。
- `GET /api/java/enterprise` 必须返回 MySQL、Redis、MinIO、MQ 和 Prometheus 配置摘要。
- 大模型状态接口不得泄露密钥。
- 运行产物、存储数据、构建目录和虚拟环境不得作为交付源码。

## 插件级验收套件

插件交付验收以 `question-engine` 的稳定能力边界为准，不以本地小平台页面是否可用作为唯一标准。平台验收必须覆盖 Java backend 能力目录、engine 目录、OCR runtime 诊断、加工任务创建、任务轮询、`question-package.v1` 获取、题图库、题图上传、AI 标准化、callback 签名投递、非法文件失败和可选大文件样本。

验收前先启动本地环境或准备预发环境地址：

```bash
export QUESTION_ENGINE_BASE_URL=http://<pre-java-host>:8018
curl $QUESTION_ENGINE_BASE_URL/api/java/health
curl $QUESTION_ENGINE_BASE_URL/api/java/worker
curl $QUESTION_ENGINE_BASE_URL/api/capabilities
```

最小验收命令：

```bash
python scripts/acceptance_question_engine_plugin.py \
  --base-url ${QUESTION_ENGINE_BASE_URL:-http://localhost:8018}
```

脚本会自动生成脱敏 Markdown 样卷，创建 `question-processing` job，轮询任务，读取标准题目包，查询任务题图库，上传题图，调用首题 AI 标准化，验证 callback-flow 测试事件，并上传非法文件确认失败。

大文件验收不放进普通 PR CI，建议在预发发布或交付包验收阶段执行：

```bash
python scripts/acceptance_question_engine_plugin.py \
  --base-url http://<pre-java-host>:8018 \
  --large-file-mb 20 \
  --timeout-seconds 900
```

如果预发环境未配置 LLM，可以增加 `--skip-ai`；如果 Java backend 无法访问脚本本地 callback server，可以传入 `--callback-url https://platform.example.com/question-engine/callback-test`；如果平台暂不验收 callback，可以增加 `--skip-callback`，但交付记录中必须说明原因和补验时间。

通过标准：

- 所有必选检查输出 `OK`。
- `question-package.v1` 中 `packageVersion` 必须是 `question-package.v1`。
- `questions` 至少包含 1 道题。
- 每道题至少包含 `questionId`、`stemMarkdown`、`options`、`images`、`mathValidation`、`sourceEvidence`。
- 非法文件类型必须返回 4xx 或明确失败，不允许进入成功状态。
- callback 必须携带签名头，验收脚本会用 callback secret 对原始 body 计算 HMAC-SHA256 并校验签名值。

常见失败优先级：

| 失败项 | 优先排查 |
| --- | --- |
| Java health 失败 | Java 进程、端口、profile、数据库 |
| worker 失败 | Python worker 是否启动、`PYTHON_WORKER_BASE_URL` |
| OCR runtime 失败 | MinerU 是否安装、`MINERU_COMMAND`、文件权限 |
| 创建 job 失败 | multipart 字段、文件类型、上传大小 |
| 轮询超时 | OCR provider 耗时、worker 日志、超时配置 |
| question package 为空 | 拆题失败、输入样卷格式、OCR 结果 |
| AI 标准化失败 | LLM key、模型网关、限流、题图 base64 |
| callback 失败 | callback URL 可达性、secret、网关策略 |
| 非法文件未失败 | 文件类型校验或 provider allowed extensions 配置 |
