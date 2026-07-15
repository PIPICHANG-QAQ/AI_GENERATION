# question-engine 交付包边界

本文定义 `question-engine` 作为 OCR 试卷处理插件交付给公司平台开发团队时，交付包应包含什么、必须排除什么、如何打包、如何验收包内容。

## 1. 交付目标

交付包只交付“试卷到标准题目包”的能力服务和平台接入材料：

```text
平台系统
  -> OpenAPI / SDK
  -> Java backend 能力 API
  -> Python worker OCR / AI / export 执行能力
  -> question-package.v1
  -> 平台自有题库、知识点、审核、权限、文件中心
```

交付包不应携带本地运行产物、历史原型仓库、依赖缓存、OCR 产物、测试临时文件和开发 IDE 配置。

## 2. 必须包含

| 路径 | 是否必选 | 用途 |
| --- | --- | --- |
| `README.md` | 必选 | 仓库和本地启动总入口 |
| `.env.example` | 必选 | 环境变量模板，不含真实密钥 |
| `.dockerignore` | 必选 | Docker 构建上下文排除规则，避免把运行数据和依赖缓存打进镜像 |
| `Dockerfile` | 必选 | 单容器演示/预发镜像构建入口 |
| `docker-compose.server.yml` | 必选 | GPU 服务器单容器部署模板 |
| `deploy/nginx.conf` | 必选 | 容器内 nginx 同源前端/API 代理配置 |
| `backend/README.md` | 必选 | 后端代码结构说明 |
| `backend/pom.xml` | 必选 | Java backend 构建配置 |
| `backend/src/main/java/` | 必选 | Java 主后端源码 |
| `backend/src/main/resources/` | 必选 | Java 配置、schema、profile |
| `backend/src/test/` | 必选 | Java 回归测试 |
| `backend/python-worker/README.md` | 必选 | Python worker 边界说明 |
| `backend/python-worker/pyproject.toml` | 必选 | Python worker 依赖和可编辑安装配置 |
| `backend/python-worker/app/` | 必选 | OCR、AI、导出 worker 源码 |
| `backend/python-worker/app/ocr/` | 必选 | CanonicalOcrBundle、MinerU adapter 和统一 Post Process 入口 |
| `backend/python-worker/app/question_layout.py` | 必选 | 复核工作台布局解析框能力，封装 `PaperLayoutCapability`、页图渲染和题目 bbox |
| `backend/python-worker/tests/` | 必选 | Python worker 单元测试源码，供迁移后自检 |
| `question-engine/README.md` | 必选 | engine 交付入口 |
| `question-engine/openapi/question-engine.v1.yaml` | 必选 | 平台接入机器可读契约 |
| `question-engine/sdk/README.md` | 必选 | SDK 目录说明 |
| `question-engine/sdk/USAGE.md` | 必选 | SDK 使用手册 |
| `question-engine/sdk/RELEASE.md` | 必选 | SDK 发布、版本和兼容策略 |
| `question-engine/sdk/generated/` | 必选 | 生成型 TypeScript / Java SDK |
| `question-engine/sdk/examples/` | 可选 | 旧手写示例，仅参考 |
| `docs/` | 必选 | 规格、交付、部署、安全、验收、运行手册 |
| `docs/delivery/POST_PROCESS_USAGE_GUIDE.md` | 必选 | OCR provider/Post Process 接入契约、SDK 决策和质量门禁 |
| `examples/platform-integration/` | 必选 | 平台最小接入样例 |
| `scripts/check_question_engine_contract.py` | 必选 | 契约、SDK、文档同步检查 |
| `scripts/check_project_portability.py` | 必选 | 迁移可用性检查，拦截绝对路径、坏 venv、坏 symlink 和运行产物泄漏 |
| `scripts/deploy_local.sh` | 必选 | 本地迁移一键部署入口，自动安装依赖、避让端口、启动、健康检查和分层 smoke |
| `scripts/test_python_worker.sh` | 必选 | Python worker 单元测试入口，固定 worker import path |
| `scripts/smoke_deploy_basic.py` | 必选 | 基础部署 smoke，不依赖 MinerU 或 AI Key |
| `scripts/smoke_ocr.py` | 必选 | MinerU/OCR smoke |
| `scripts/smoke_ai.py` | 必选 | AI 标准化/解析 smoke |
| `scripts/acceptance_question_engine_plugin.py` | 必选 | 平台插件级验收脚本 |
| `scripts/package_question_engine_delivery.py` | 必选 | 交付包打包和清单校验脚本 |
| `scripts/build_mineru_wheelhouse.sh` | 可选 | 生成 MinerU 离线 wheelhouse 大包 |
| `scripts/start_java_backend.sh` | 可选 | 本地启动 Java backend |
| `scripts/start_project_with_java_backend.sh` | 可选 | 本地一键启动闭环 |
| `scripts/install_frontend.sh` | 可选 | 本地小平台前端依赖安装 |
| `scripts/install_backend.sh` / `scripts/install_mineru.sh` / `scripts/check_mineru.py` | 可选 | 本地依赖安装和 OCR provider 检查 |
| `docker-compose.local.yml` | 可选 | 本地 MySQL/Redis/MinIO 联调 |
| `vendor/mineru-wheelhouse/` | 可选 | MinerU 和 Python worker 依赖离线部署大包，使用 `--include-mineru-wheelhouse` 才打入交付包 |

## 3. 必须排除

| 路径或模式 | 排除原因 |
| --- | --- |
| `.git/` | 版本库元数据，不属于交付物 |
| `.DS_Store` | macOS 本地系统文件 |
| `.idea/`、`.vscode/` | IDE 本地配置 |
| `.env`、`.env.*` | 可能包含真实密钥，`.env.example` 例外 |
| `backend/storage/` | 本地 OCR、上传、导出运行数据 |
| `backend/target/` | Java 编译和测试产物 |
| `backend/python-worker/.venv/` | 本地 Python 虚拟环境 |
| `**/__pycache__/`、`**/*.pyc` | Python 缓存 |
| `local-platform/node_modules/` | 前端依赖缓存 |
| `local-platform/dist/` | 前端构建产物 |
| `protocal/` | 历史 Replit 原型仓库，不是 engine 交付物 |
| `tmp/`、`artifacts/` | 临时文件或历史产物 |
| `*.log` | 本地日志 |
| `*.key`、`*.pem`、`*.p12` | 密钥和证书 |

`backend/python-worker/.venv/` 绝不能通过压缩包、网盘或 rsync 交付给另一台机器。Python venv 内的 `bin/python` 和 console script shebang 通常包含创建机器上的绝对路径；跨用户或跨目录复制后会出现 `no such file or directory: backend/python-worker/.venv/bin/python`。目标机器必须用 `./scripts/install_backend.sh` 或 `./scripts/install_mineru.sh` 本地重建。

交付包也不携带系统级 TeX 环境。目标机器如果需要高质量 PDF 导出，必须自行安装 `xelatex` 以及 `ctex`、`amsmath`、`amssymb`、`graphicx`、`tabularx`、`array`、`tcolorbox` 等 LaTeX 包；缺失时 PDF 会自动回退 ReportLab 文本版，复杂公式会降级。

## 4. 打包命令

先做只检查不产包：

```bash
python scripts/package_question_engine_delivery.py --check-only
```

生成交付包：

```bash
python scripts/package_question_engine_delivery.py
```

默认输出：

```text
dist/question-engine-delivery.tar.gz
dist/question-engine-delivery-manifest.json
```

生成带明确版本名的 TOGO 移交包：

```bash
python scripts/package_question_engine_delivery.py \
  --include-local-platform \
  --release-name AI_GENERATION_TOGO_20260709_v14
```

输出：

```text
dist/AI_GENERATION_TOGO_20260709_v14.tar.gz
dist/AI_GENERATION_TOGO_20260709_v14_MANIFEST.json
```

如需把本地小平台演示壳也打进包：

```bash
python scripts/package_question_engine_delivery.py --include-local-platform
```

正式平台插件交付默认不包含 `local-platform/`。它只作为本地工作台 example，平台应参考 `docs/product/LOCAL_PLATFORM_AS_EXAMPLE.md`，不要复制本地页面适配层作为正式 SDK。

如需把 MinerU 离线部署大包也打进包，先构建 wheelhouse：

```bash
./scripts/build_mineru_wheelhouse.sh
python scripts/package_question_engine_delivery.py --include-mineru-wheelhouse
```

`vendor/mineru-wheelhouse/` 是当前 Python 版本、操作系统和 CPU 架构对应的离线依赖集合。它不是 `.venv`，可以随交付包迁移；目标机器仍需用 `./scripts/deploy_local.sh --with-mineru` 或 `./scripts/install_mineru.sh` 在本机重建虚拟环境。

生成包含本地小平台前端源码的直接交付目录：

```bash
TOGO_DIR="${TOGO_DIR:-$HOME/AI_GENERATION_TOGO}"
rm -rf "$TOGO_DIR"
python scripts/package_question_engine_delivery.py \
  --include-local-platform \
  --release-name AI_GENERATION_TOGO_20260709_v14 \
  --output /tmp/ai-generation-delivery.tar.gz \
  --manifest /tmp/ai-generation-delivery-manifest.json
mkdir -p "$TOGO_DIR"
tar -xzf /tmp/ai-generation-delivery.tar.gz -C "$TOGO_DIR"
(cd "$TOGO_DIR" && python scripts/package_question_engine_delivery.py --check-only --include-local-platform)
```

该目录不得包含 `.venv`、`backend/storage`、`backend/target`、`node_modules`、`local-platform/dist` 或真实 `.env`。目标机器必须重新安装依赖。
`python scripts/check_project_portability.py` 需要在目标机器执行依赖安装后再运行，因为干净交付目录按设计不包含 `backend/python-worker/.venv/` 和 `local-platform/node_modules/`。

如果要在目标服务器使用 `docker-compose.server.yml`，需先在 TOGO 目录本机生成镜像构建产物：

```bash
(cd backend && mvn clean -DskipTests package)
(cd local-platform && npm ci && npm run build)
docker compose -f docker-compose.server.yml up -d --build
```

Docker 部署仍不得复用其它机器的 `vendor/mineru-venv`；`HOST_MINERU_VENV` 指向目标服务器本机重建后的 MinerU venv。

## 5. 迁移后启动流程

开发团队拿到交付目录后，按以下顺序执行：

```bash
cd AI_GENERATION_TOGO
cp .env.example .env
# 编辑 .env，填入模型网关、模型名、API Key、文件存储、数据库等目标环境配置

./scripts/deploy_local.sh --with-mineru
```

交付体验和 OCR 验收默认使用 `--with-mineru`。如果交付目录包含 `vendor/mineru-wheelhouse/`，安装脚本会优先从离线大包安装 MinerU；启动后会运行 basic smoke 和 OCR smoke。

只需要验证服务连通时，可以执行不带参数的基础部署：

```bash
./scripts/deploy_local.sh
```

不带参数的 `deploy_local.sh` 只完成基础依赖安装、端口选择、Python worker / Java backend / 前端启动、健康检查和 basic smoke。它默认不要求 MinerU 或大模型 Key，因此只代表“基础部署成功”。

默认部署不能代表 PDF、图片或 Office 文件 OCR 可用。创建这类导入任务前，Java backend 会先检查 worker 的 OCR provider runtime；如果 MinerU 未安装或 `MINERU_COMMAND` 不可用，接口会返回 503 并提示执行 `./scripts/deploy_local.sh --with-mineru`，不会再生成一个马上进入 `OCR failed` 的任务。

需要验证 OCR 时执行：

```bash
./scripts/deploy_local.sh --with-mineru
```

需要验证 AI 全链路时，先在 `.env` 或 shell 环境中配置 `DEEPSEEK_API_KEY`；兼容旧部署时也可配置 `DASHSCOPE_API_KEY` 或 `ALIYUN_LLM_API_KEY`，再执行：

```bash
./scripts/deploy_local.sh --with-ai
```

如果必须使用固定端口，执行：

```bash
./scripts/deploy_local.sh --strict-ports
```

脚本默认端口为 `8000/8018/5173`。如果端口被另一个项目占用，会自动避让到后续空闲端口，并把实际端口、访问地址和运行模式写入 `.run/deploy.env`。运行日志和 PID 分别写入 `.run/logs/` 与 `.run/pids/`；健康检查失败时会自动输出相关日志末尾内容。

本地长时间演示或迁移验收可增加 watchdog：

```bash
./scripts/health_watchdog.sh --once --with-mineru
./scripts/health_watchdog.sh --with-mineru --restart
```

watchdog 不保存密钥，只读取 `.run/deploy.env`、PID 和健康接口；失败时输出 `.run/logs/` 日志尾部，`--restart` 会重新执行一键部署入口。

如果交付目录不包含 `local-platform`，部署脚本会跳过前端，只启动 Java backend 和 Python worker。生产部署时可改用平台进程管理或容器托管，但仍必须在目标机器本地重建 worker venv，不得复制其它机器的 `.venv`。

## 6. 交付包验收

收到交付包后，平台团队应检查：

```bash
tar -tzf dist/question-engine-delivery.tar.gz | sort | sed -n '1,120p'
```

不得出现：

```text
protocal/
backend/storage/
backend/target/
backend/python-worker/.venv/
local-platform/node_modules/
local-platform/dist/
__pycache__/
.env
```

必须出现：

```text
question-engine/openapi/question-engine.v1.yaml
question-engine/sdk/generated/typescript/QuestionEngineClient.ts
question-engine/sdk/generated/java/src/main/java/com/aigeneration/questionengine/sdk/QuestionEngineClient.java
backend/src/main/java/com/aigeneration/questionbank/capability/controller/QuestionProcessingCapabilityController.java
backend/python-worker/app/ocr_flow.py
backend/python-worker/app/question_layout.py
backend/python-worker/tests/test_ocr_flow.py
docs/architecture/CODE_STRUCTURE_PORTABILITY_REVIEW.md
docs/development/DEVELOPMENT_GUIDE.md
docs/delivery/OPERATIONS_GUIDE.md
docs/delivery/SECURITY_AND_INTEGRATION_CONTRACT.md
docs/delivery/ERROR_AND_STATUS_GUIDE.md
docs/delivery/ACCEPTANCE.md
examples/platform-integration/README.md
scripts/acceptance_question_engine_plugin.py
scripts/deploy_local.sh
scripts/smoke_deploy_basic.py
scripts/smoke_ocr.py
scripts/smoke_ai.py
```

## 7. 交付前检查清单

交付前必须执行：

```bash
python scripts/check_question_engine_contract.py
python question-engine/sdk/generate-sdk.py
python scripts/check_project_portability.py
./scripts/test_python_worker.sh
python scripts/package_question_engine_delivery.py --check-only --include-local-platform
cd backend && mvn test
```

如果本地服务已启动，还应执行：

```bash
./scripts/smoke_deploy_basic.py
python scripts/acceptance_question_engine_plugin.py --base-url http://localhost:8018
```

## 8. 版本命名

建议交付包命名：

```text
question-engine-delivery-{YYYYMMDD}-{contractVersion}.tar.gz
AI_GENERATION_TOGO_{YYYYMMDD}_v{productVersion}.tar.gz
```

当前契约版本来自：

```text
question-engine/openapi/question-engine.v1.yaml -> info.version
```

交付包版本、OpenAPI 版本和 SDK 发布说明必须保持一致。

## 瘦身后项目结构约束

当前源码结构：

```text
backend/
  Java 主后端
  python-worker/
  storage/

local-platform/
  本地演示前端

question-engine/
  OpenAPI、SDK 和交付说明

docs/
  架构、产品、交付、开发文档

scripts/
  本地安装、启动、验收和打包脚本
```

已移除或不应交付的内容：

- `backend-java/`：已合并为唯一 `backend/`。
- 旧 Python 根后端：核心 worker 已移入 `backend/python-worker/`。
- `frontend/`：已迁移为 `local-platform/`。
- `protocal/`：Replit 原型仓库不属于正式交付。
- `artifacts/`、`tmp/`、`frontend/dist`、`frontend/node_modules`、`backend/target`：构建、截图或临时产物不进入交付包。

后续约束：

- Java 是唯一业务后端。
- Python 只做 worker。
- 本地平台只做演示壳。
- 新增稳定对外能力应优先进入 `backend/src/main/java/com/aigeneration/questionbank/capability` 或 `engine`。
