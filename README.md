# AI 题库应用

本仓库是 AI 题库应用工程。当前正在从完整题库系统收敛为“本地小平台 + 题目加工能力服务”：本地仍保留导入 OCR 工作台、题库中心、组卷中心和知识点库用于闭环验证；对公司教育生态平台输出的是试卷 OCR、题目结构化、AI 标准化/解析、人工校验和标准题目包能力。

面向公司交付时，核心子项目应理解为 `question-engine`：Java 能力 API + Python 必要 worker。本地小平台页面、Replit 原型、截图和演示数据不属于 engine 交付范围。

## 当前范围

- 浏览器上传试卷文件。
- Java 主后端作为默认 API 入口，已接管知识点、题库题目和试卷基础 CRUD；导入任务基础管理会同步元数据、OCR job 状态快照、派生 OCR 状态、失败原因、任务状态、导入题、题图快照和上传原文件存储元数据到 Java 表；导入任务原文件预览优先由 Java 从本地文件存储或 MinIO 返回，旧任务回退 Python；导入题入库入口会将 Python 返回的入库题同步到 Java 题库表。
- Java 已接管导入题/题库题题图上传、图片库和图片访问，统一写入 `file-flow`；AI 标准化/解析由 Java 创建 job 并调用 Python worker，AI 标准化默认返回候选源码/预览并等待人工应用，只有显式写回且通过低置信和严重 LaTeX 风险闸门时才覆盖题干；AI 解析会把答案和解析写回题目；试卷导出由 Java 创建导出 job、调用 Python render worker 并保存导出文件。
- 导入任务列表现在以 Java 持久化快照立即返回，避免 Python worker OCR 忙、reload 或临时不可达时让“任务记录”长时间加载；任务创建和详情仍负责同步 worker 最新状态。
- Java 新增题目加工能力 API `/api/capabilities/question-processing`，用于输出能力描述、加工任务视图和标准题目包 `question-package.v1`，平台应优先对接该能力边界，而不是直接依赖本地题库业务表。
- Java 新增 engine 能力目录 `/api/engine`，封装题目导入、题库、组卷中心和知识点库四个模块，说明平台接入要求和交付代码边界。
- Java 新增能力总目录 `/api/capabilities`，在 `ocr-flow`、`question-processing` 之外，继续封装 `review-workbench`、`ai-flow`、`export-flow`、`file-flow`、`callback-flow` 和 `sdk-openapi`，用于把核心能力与本地小平台页面隔离。
- Java 新增 callback-flow HTTP 回调签名、事件记录和手动重试入口；SDK 草案位于 `question-engine/sdk`。
- 后端接收文件并创建 OCR-Flow 任务。
- OCR-Flow 默认调用 MinerU 命令行执行 OCR 和文档解析，同时通过 provider 边界预留替换其它 OCR 引擎的空间。
- OCR 成功后进入证据驱动拆题流水线：本地先识别大题/题号/小问/选项/题图候选边界；高置信边界直接跳过 `llm-boundary-refine`，低置信边界按题段分片并受控并发调用 OpenAI 兼容大模型确认边界；最后按 OCR 原文切片构建结构并做证据校验，未配置或失败时按分片回退本地规则。
- OCR outputs 会返回 `boundaryConfidence`、`autoSemanticRepair` 和脱敏 `llmMetrics`；指标只包含调用类型、provider、model、状态、耗时和 chunk/item 数，不记录 prompt、密钥、完整 OCR 文本或图片 base64。
- 对题干、选项和子题进行公式标准化与校验，减少 OCR 公式边界错误导致的渲染失败。
- 支持题目人工校验编辑，使用 Markdown + LaTeX 双栏源码/预览模式。
- 支持确定性公式标准化/校验、LaTeX 分隔符修复和 AI 标准化候选。
- 前端已接入 Replit 原型后台界面：题库中心、题目导入、组卷中心和知识点库统一使用组件化后台布局，并继续通过 Java backend 调用现有业务接口。
- 前端提供导入 OCR 工作台：创建导入任务后直接进入，左侧预览试卷/答案原文件，右侧人工校验并入库。
- 支持查看 Markdown、JSON 和抽取出的图片资源。
- 题图作为题干内容保存和展示：题目保留 `images` 结构化字段，同时在题干 Markdown 中保留图片引用。
- 题库中心支持新建导入任务，填写学段、学科、年级、地区、年份、标题。
- 导入任务支持上传试卷和答案，并生成待校验题目。
- AI 可补全题型、答案、解析、知识点、难度和分值。
- 支持单题入库、批量入库、题库搜索和题目删除。
- 题库和人工校验支持大题小问结构，小问可分别保存题干、答案、解析、题型、难度、分值和知识点；可编辑小问支持单独添加/删除，并保留小问级 `AI 标准化` 与 `AI 解析` 按钮，AI 结果只回写当前小问；组卷中心支持按小问选择纳入试卷，选择结果只保存在试卷层。
- 组卷中心支持手动选题并导出 Word/PDF；导出优先生成 Markdown + LaTeX 中间文件，再通过 Pandoc 转为 DOCX/PDF，未安装 Pandoc 时回退旧导出。
- 知识点库支持新增、编辑和删除知识点，基础 CRUD 已迁移到 Java 数据层。
- 所有项目文档统一维护在 `/docs` 目录。

用户账号、权限、题目版本、企业平台审核流、真实 MQ 异步编排、超时扫描器和 SDK 发布包仍属于后续范围。

## 项目结构

```text
backend/      唯一后端：Java 主后端 + python-worker 必要执行能力
local-platform/ Vite + React 本地演示小平台
question-engine/ SDK 和能力发动机交付说明
docs/         PRD、技术设计、开发规范、验收标准、架构图、渲染图
scripts/      本地安装和 MinerU 检测脚本
```

## 本地启动

推荐使用一键本地部署入口。交付目录已包含 MinerU 离线 wheelhouse 时，默认按可 OCR 的本地体验启动：

```bash
./scripts/deploy_local.sh --with-mineru
```

它会自动检查并安装基础依赖、优先从 `vendor/mineru-wheelhouse/` 安装 MinerU、选择可用端口、启动 Python worker / Java backend / 前端、等待健康检查，并运行基础部署 smoke 和 OCR smoke。

只检查服务连通和基础页面时，可以使用更轻量的基础部署：

```bash
./scripts/deploy_local.sh
```

默认命令只代表服务连通和基础页面可用，不安装或验证 MinerU。上传 PDF、图片、DOCX、PPTX、XLSX 等需要 OCR provider 的文件前，必须使用 `--with-mineru` 或配置可用的 `MINERU_COMMAND`；否则创建导入任务会直接返回 OCR provider 不可用，不再生成必然失败的任务。

需要重新安装并验证 MinerU/OCR 时，也直接执行：

```bash
./scripts/deploy_local.sh --with-mineru
```

生成 TOGO 交付目录时如需把 MinerU 离线部署大包一并带上，先构建 wheelhouse，再用带大包参数打包：

```bash
./scripts/build_mineru_wheelhouse.sh
python scripts/package_question_engine_delivery.py --include-local-platform --include-mineru-wheelhouse
```

大包会放在 `vendor/mineru-wheelhouse/`。目标机器仍不要复制 `.venv`；执行 `./scripts/deploy_local.sh --with-mineru` 时会优先从该 wheelhouse 本机重建 worker venv 和 MinerU 命令。

需要验证 AI 标准化和 AI 解析时，先在 `.env` 或 shell 环境中配置 `DEEPSEEK_API_KEY`、`DASHSCOPE_API_KEY` 或 `ALIYUN_LLM_API_KEY`，再执行：

```bash
./scripts/deploy_local.sh --with-ai
```

`--with-ai` 不作为默认启动项，因为它需要本地密钥并会调用真实模型服务。

如果 `8000/8018/5173` 被其它项目占用，部署脚本默认自动避让到后续空闲端口，并在结束时输出实际访问地址。必须固定端口时使用：

```bash
./scripts/deploy_local.sh --strict-ports
```

部署运行状态写入：

```text
.run/deploy.env
.run/pids/
.run/logs/
```

健康检查失败时，脚本会自动输出对应服务日志的最后 80 行。

`backend/python-worker/.venv` 是本机虚拟环境，不是可复制的交付物。部署到另一台电脑时不要复用旧 `.venv`；如果目录来自其它机器导致 `bin/python`、`mineru` 或 `uvicorn` 指向不存在的绝对路径，直接执行 `./scripts/deploy_local.sh` 或 `./scripts/deploy_local.sh --with-mineru`，脚本会检测并重建不可用的虚拟环境。

手动安装和检查命令仍可用于排障：

```bash
./scripts/install_backend.sh
./scripts/install_frontend.sh
./scripts/install_mineru.sh
./scripts/test_python_worker.sh
python scripts/check_mineru.py
python scripts/check_project_portability.py
```

可选：安装 Pandoc 和 XeLaTeX 以获得更稳定的数学公式 Word/PDF 导出。未安装时后端会回退旧导出。

```bash
which pandoc
which xelatex
```

PDF 中文字体可通过 `.env` 配置：

```text
PANDOC_CJK_FONT=Songti SC
```

可选：启用大模型拆题。真实密钥不要提交到仓库。推荐复制本地配置文件：

```bash
cp .env.example .env
```

然后在 `.env` 中按实际 Key 类型填写。使用 DeepSeek 官方 Key 时：

```text
DEEPSEEK_API_KEY=你的 DeepSeek API Key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
LLM_PROVIDER=deepseek
```

如果需要沿用旧部署 Key，则保留原 OpenAI 兼容网关，只切模型名：

```text
DASHSCOPE_API_KEY=旧部署或平台网关 Key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=deepseek-v4-pro
LLM_PROVIDER=dashscope
```

`DASHSCOPE_*` 变量名会继续保留，用于兼容旧部署和平台模型网关。拆题阶段会先执行 `local-boundary-detect`、`llm-boundary-refine`、`question-structure-build`、`sub-question-split` 和 `structure-validate`，模型只返回边界，不直接生成题干正文。

OCR-Flow LLM 效率相关开关默认保守启用：

```text
LLM_MAX_CONCURRENCY=1
LLM_BOUNDARY_CHUNK_SIZE=5
LLM_METRICS_ENABLED=true
LLM_ROUTER_MODE=external
LOCAL_LLM_ENABLED=false
LOCAL_LLM_BASE_URL=http://127.0.0.1:8001/v1
LOCAL_LLM_MODEL=aux-qwen3-32b-fp8
LOCAL_LLM_MAX_CONCURRENCY=4
LOCAL_LLM_DISABLE_THINKING=true
LLM_EXTERNAL_FALLBACK_ENABLED=true
LLM_EXTERNAL_MAX_CONCURRENCY=1
LLM_ROUTER_CACHE_ENABLED=true
LLM_ROUTER_CACHE_TTL_SECONDS=300
OCR_AUTO_SEMANTIC_REPAIR_MODE=skip
OCR_VISUAL_REPAIR_MAX_CONCURRENCY=2
OCR_VISUAL_REPAIR_PRELOAD_ENABLED=true
OCR_VISUAL_REPAIR_PRELOAD_MAX_PAGES=4
AI_STANDARDIZE_CACHE_TTL_SECONDS=300
```

本地开发默认 `LLM_ROUTER_MODE=external` 且 `LOCAL_LLM_ENABLED=false`。服务器部署可启用 hybrid：`LLM_ROUTER_MODE=hybrid`、`LOCAL_LLM_ENABLED=true`、`LOCAL_LLM_BASE_URL=http://vllm-aux:8000/v1`。服务器 hybrid 下，高置信本地边界不调用边界模型，低置信样本才分片确认；`boundary_refine` 默认直接走外部满血模型，避免本地小模型在边界确认阶段耗时过长或输出不稳定；小问结构确认和 AI 标准化仍优先走本地 `aux-qwen3-32b-fp8`，调用失败、JSON/schema 失败、结构校验失败或风险评分过高时升级外部满血模型；AI 解析和复杂推理继续走外部模型。Qwen3 类本地模型建议保持 `LOCAL_LLM_DISABLE_THINKING=true`，避免 reasoning 文本污染 JSON 输出。`OCR_AUTO_SEMANTIC_REPAIR_MODE=skip` 表示 OCR 主链路不自动执行语义修复，人工校验里的 AI 标准化/AI 解析仍可按需触发。只有压测或明确需要 OCR 返回前自动修复时，才建议把语义修复切到 `inline` 或 `inline-concurrent`，并根据模型网关限流调整 `LLM_MAX_CONCURRENCY`。

人工触发 AI 标准化会先尝试本地确定性修复和可信 OCR 兜底，只有仍需模型判断时才调用 LLM；`AI_STANDARDIZE_CACHE_TTL_SECONDS` 用于缓存成功的 LLM 标准化候选，设为 `0` 可关闭。

后端启动时会自动读取项目根目录 `.env` 和 `backend/.env`。如果同时存在 shell 环境变量和 `.env`，以 shell 环境变量为准。

手动启动 Python worker：

```bash
source backend/python-worker/.venv/bin/activate
uvicorn app.main:app --app-dir backend/python-worker --host 127.0.0.1 --port 8000
```

启动 Java 主后端：

```bash
./scripts/start_java_backend.sh
```

脚本会在 macOS 上优先使用本机 JDK 17，与 SmartRAG 后端 Java 版本保持一致。

Java 服务默认监听：

```text
Java 后端：http://localhost:8018
健康检查：http://localhost:8018/api/java/health
Python worker 连通性：http://localhost:8018/api/java/worker
SmartRAG 对齐版本：http://localhost:8018/api/java/stack
企业化配置入口：http://localhost:8018/api/java/enterprise
OCR-Flow 能力：http://localhost:8018/api/capabilities/ocr-flow
题目加工能力：http://localhost:8018/api/capabilities/question-processing
能力总目录：http://localhost:8018/api/capabilities
Engine 能力目录：http://localhost:8018/api/engine
AI job 列表：http://localhost:8018/api/capabilities/ai-flow/jobs
导出 job 列表：http://localhost:8018/api/capabilities/export-flow/jobs
回调运行时：http://localhost:8018/api/capabilities/callback-flow/runtime
```

当前阶段 Java 服务是前端默认 API 入口。Java 自身提供 `/api/java/*` 运维接口，并已接管 `/api/knowledge-points`、`/api/question-bank/questions`、`/api/papers` 的基础 CRUD；导入任务创建、列表、详情、重命名、单删、批量删除、原文件预览、重试、题图、AI 标准化/解析和试卷导出仍返回兼容现有前端的数据结构，但会同步或清理 Java 元数据表，并保存试卷/答案 OCR job 状态快照、派生 OCR 状态、失败原因、任务状态、导入题目、题图快照、AI job、导出 job、callback event 和上传/导出文件存储元数据；导入任务创建时 Java 会先保存试卷文件和可选答案文件副本，再调用 Python worker 创建 OCR job；`/api/import-tasks/{taskId}/source/{paper|answer}` 优先从 Java 文件存储读取并以内联方式返回，历史任务没有 Java 文件记录时回退 Python；导入题单题/批量入库会先调用 Python worker 保持现有校验和任务状态流转，再同步到 Java 题库表。

新增的 `/api/capabilities`、`/api/capabilities/ocr-flow` 和 `/api/capabilities/question-processing` 是后续平台集成的稳定能力边界。本地题库中心和组卷中心可以继续作为小平台使用；公司教育生态平台对接时，应消费能力 API 输出的 OCR-Flow 描述、`ProcessingJob`、`QuestionPackage`、六个补充能力契约或 `question-engine/sdk`，最终题库入库、权限、审核流和知识点主数据由平台侧负责。OCR 默认仍走 Python worker 中的 MinerU provider，但业务层只依赖 `ocr-flow` 的统一输出；AI 模型推理和 Pandoc 渲染仍在 Python worker，Java 负责业务编排、状态、写库和文件存储。这样可以把题目加工能力封装出来，同时保留 Python 中已经稳定的 MinerU、LaTeX、AI 标准化和 Pandoc 导出能力。

其他开发者接入 `question-engine` 时，先阅读 `docs/development/DEVELOPMENT_GUIDE.md`，按任务类型选择后续文档。平台实际调用优先阅读 `docs/delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md` 和 `question-engine/sdk/USAGE.md`；生产接入、安全评审、部署和排障阅读 `docs/delivery/SECURITY_AND_INTEGRATION_CONTRACT.md`、`docs/delivery/OPERATIONS_GUIDE.md`；交付打包阅读 `docs/delivery/DELIVERY_PACKAGE.md`。如果要参考本地小平台如何串起上传、OCR、人工复核、题图、AI 标准化/解析和本地入库流程，阅读 `docs/product/LOCAL_PLATFORM_AS_EXAMPLE.md`。这些文档共同说明能力作用、OCR-Flow 调用位置、核心接口、出入参、回调、SDK、本地 example 和不推荐接入方式。

Java 已接入 Redis Starter、MinIO SDK、Prometheus 和 `enterprise.*` 配置入口，但默认本地模式不强制连接 Redis、MinIO 或 MQ。上传原文件、题图和导出文件默认写入 `backend/storage/java_files`，启用 `ENTERPRISE_MINIO_ENABLED=true` 后可写入 MinIO。MySQL、Redis、MinIO 和真实 MQ 主路径切换会继续分阶段推进，当前本地仍可只启动 H2 + Java 本地文件副本 + Python worker。

一键启动 Java 入口版本：

```bash
./scripts/start_project_with_java_backend.sh
```

该脚本是开发兼容入口，内部转调 `./scripts/deploy_local.sh --dev-reload`。部署交付时优先直接使用 `deploy_local.sh`，默认不启用 Python worker reload。
开发模式下 `--dev-reload` 只监听 `backend/python-worker/app/**/*.py`，不会监听 `.venv/site-packages`，避免依赖库文件事件触发 worker 反复重启。

启动后可按层级运行冒烟测试：

```bash
./scripts/smoke_deploy_basic.py
./scripts/smoke_ocr.py
./scripts/smoke_ai.py
./scripts/smoke_local_platform_business.py
```

前端默认访问 `http://localhost:8018`。如果需要临时绕过 Java 直接访问 Python，可在启动前端时覆盖：

```bash
VITE_API_BASE=http://localhost:8000 npm run dev
```

可选：启动本地企业化依赖，用于后续逐步对齐 SmartRAG 技术栈：

```bash
docker compose -f docker-compose.local.yml up -d mysql redis minio
```

安装并启动前端：

```bash
cd local-platform
npm install
npm run dev
```

访问地址：

```text
前端：http://localhost:5173
Java 后端：http://localhost:8018
Python worker：http://localhost:8000
```

## 服务器 Docker 部署

服务器单机演示或联调可使用 Docker Compose 把前端、Java backend、Python worker 和 MinerU 放进同一个应用容器。容器内由 nginx 对外提供 Web 入口，并把 `/api/*`、`/actuator/*` 和接口文档路径转发到 Java backend；Python worker 和 MinerU 只在容器内供 Java 调用。

先生成 Java jar 和前端静态资源：

```bash
(cd backend && mvn -DskipTests package)
(cd local-platform && npm run build)
```

```bash
docker compose -f docker-compose.server.yml up -d --build
```

也可以直接使用服务器启动脚本，它会自动构建 jar、构建前端、启动 Docker 服务、执行健康检查并打印访问地址：

```bash
APP_PUBLIC_HOST=服务器公网IP ./scripts/start_server_docker.sh
```

`docker-compose.server.yml` 默认适配 GPU 服务器：基础镜像可通过 `SERVER_BASE_IMAGE` 配置，默认优先使用服务器已有的 `nvcr.io/nvidia/tensorrt:23.09-py3`；MinerU 通过 `HOST_MINERU_VENV` 挂载服务器本机 venv，默认路径为 `/home/user/AI_GENERATION_DOCKER/vendor/mineru-venv`。当前服务器约定 AI_GENERATION / MinerU OCR 通过 `NVIDIA_VISIBLE_DEVICES=0` 只暴露物理 GPU0，vLLM / aux-qwen3-32b-fp8 留在物理 GPU1；容器内只看得到这一张卡，因此 `OCR_CUDA_VISIBLE_DEVICES=0`。MinerU 默认使用 `MINERU_VIRTUAL_VRAM_SIZE=48` 和 `MINERU_HYBRID_BATCH_RATIO=16` 适配 48GB 级别显存。如果目标服务器没有该 venv，先在服务器上执行 `./scripts/deploy_local.sh --with-mineru` 或 `./scripts/install_mineru.sh` 生成，再启动 Docker。

默认端口：

```text
客户体验入口：http://服务器IP/
兼容调试入口：http://服务器IP:5173/
Java 后端直连：http://服务器IP:8018
Python worker：仅容器内监听 127.0.0.1:8000，不暴露公网
```

Docker 部署仍使用项目根目录 `.env` 注入大模型配置，例如 `DEEPSEEK_API_KEY`、`DASHSCOPE_BASE_URL` 和 `DASHSCOPE_MODEL`。真实密钥不要写入 Dockerfile、镜像或提交记录；把本机可用的 `.env` 安全复制到服务器项目目录即可保持相同 API Key。

持久化数据默认写入服务器项目目录下的 `server-data/`，包括 H2 数据库、上传文件、OCR 输出、导出文件和题图。重建镜像不会删除该目录。

健康检查：

```bash
curl http://服务器IP/api/java/health
curl http://服务器IP/api/java/worker
curl http://服务器IP/api/capabilities/ocr-flow/runtime
```

如果服务器已有 80 或 8018 端口占用，可在 `.env` 中调整：

```text
APP_HTTP_PORT=8080
APP_JAVA_PORT=18018
HOST_MINERU_VENV=/path/to/backend/python-worker/.venv
```

## 文档维护规则

新开发者或不熟悉当前任务边界时，先阅读 `/docs/development/DEVELOPMENT_GUIDE.md`，再根据任务进入具体规格、接口或代码结构文档。

每次改代码前必须阅读 `/docs/development/CONTRIBUTING.md`。如果行为、接口、界面、架构、部署、验证方式发生变化，必须在同一次迭代中同步更新 `/docs` 下受影响的文档。

交付给平台团队前必须执行：

```bash
python scripts/check_question_engine_contract.py
python question-engine/sdk/generate-sdk.py
python scripts/package_question_engine_delivery.py --check-only
```
