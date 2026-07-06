# 生产部署手册

本文面向平台开发和运维团队，说明如何把 `question-engine` 部署为公司平台可调用的 OCR 试卷处理插件。

## 1. 部署组件

| 组件 | 必选 | 职责 |
| --- | --- | --- |
| Java backend | 必选 | 对外能力 API、任务状态、文件元数据、OpenAPI/SDK 契约、callback-flow |
| Python worker | 必选 | OCR provider 调用、拆题、公式处理、AI 标准化/解析、Pandoc 导出 |
| MySQL | 生产必选 | Java 业务表、任务表、题目快照、callback event |
| 对象存储 / MinIO | 生产必选 | 上传原文件、题图、OCR 产物、导出文件 |
| Redis | 推荐 | 缓存、限流、分布式锁或后续任务队列辅助 |
| MQ | 推荐 | 生产异步任务、重试、削峰和死信 |
| OCR provider | 必选 | 默认 MinerU，可替换其它 provider |
| LLM provider | 可选但推荐 | AI 拆题、AI 标准化、AI 解析 |
| Pandoc + XeLaTeX | 可选 | DOCX/PDF 导出 |

Python worker 的 `.venv` 必须在目标机器本地创建，不得从开发机或交付包复制。虚拟环境里的 Python 解释器和 `mineru`、`uvicorn` 等 console script 会记录绝对路径；换用户、换目录或换机器后通常不可用。

## 2. 推荐拓扑

```text
平台网关 / 平台服务
  -> Java backend:8018
     -> Python worker:8000
     -> MySQL
     -> Redis / MQ
     -> MinIO / 平台对象存储
     -> DeepSeek / OpenAI-compatible LLM
     -> MinerU / OCR provider
```

Python worker、MySQL、Redis、MQ、MinIO 不应暴露公网。

## 3. 环境要求

| 项 | 要求 |
| --- | --- |
| Java | JDK 17 |
| Maven | 3.8+ |
| Python | 3.10+ |
| OS | Linux 生产环境；macOS 仅用于本地开发 |
| 内存 | Java backend 建议 2 GB 起；Python OCR worker 视 OCR provider 至少 4 GB 起 |
| 磁盘 | 临时文件目录需能容纳上传文件、OCR 产物和导出文件 |
| 网络 | Java 能访问 worker、数据库、对象存储、LLM provider |

## 4. Java backend 配置

核心环境变量：

| 变量 | 生产建议 | 说明 |
| --- | --- | --- |
| `SERVER_PORT` | `8018` 或平台约定端口 | Java backend 监听端口 |
| `SPRING_PROFILES_ACTIVE` | `mysql` | 生产不要使用默认 H2 |
| `DB_URL` | MySQL JDBC URL | Java 主库 |
| `DB_USERNAME` / `DB_PASSWORD` | 平台密钥管理注入 | 数据库账号 |
| `PYTHON_WORKER_ENABLED` | `true` | 是否调用 worker |
| `PYTHON_WORKER_API_PROXY_ENABLED` | `false` | 生产建议关闭旧 `/api/*` proxy |
| `PYTHON_WORKER_BASE_URL` | worker 内网地址 | 例如 `http://question-engine-worker:8000` |
| `PYTHON_WORKER_CONNECT_TIMEOUT_MS` | `2000` 到 `5000` | 连接超时 |
| `PYTHON_WORKER_READ_TIMEOUT_MS` | `300000` 或按页数调整 | OCR/AI/导出读取超时 |
| `ENTERPRISE_MINIO_ENABLED` | `true` | 生产启用对象存储 |
| `MINIO_ENDPOINT` | 对象存储内网地址 | MinIO 或兼容 S3 服务 |
| `MINIO_BUCKET` | 平台 bucket | 文件存储桶 |
| `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | 平台密钥管理注入 | 对象存储账号 |
| `ENTERPRISE_REDIS_ENABLED` | 按平台决定 | Redis 开关 |
| `REDIS_HOST` / `REDIS_PORT` | 平台 Redis | 缓存或限流 |
| `ENTERPRISE_MQ_ENABLED` | 按平台决定 | MQ 开关 |
| `ROCKETMQ_NAME_SERVER` | 平台 MQ | 后续异步任务 |

生产必须确认：

```bash
curl http://<java-host>:8018/api/java/health
curl http://<java-host>:8018/api/java/worker
curl http://<java-host>:8018/api/capabilities
curl http://<java-host>:8018/api/engine/interfaces
```

## 5. Python worker 配置

核心环境变量：

| 变量 | 生产建议 | 说明 |
| --- | --- | --- |
| `OCR_FLOW_PROVIDER` | `mineru` 或平台 provider | OCR provider |
| `OCR_FLOW_EXTENSIONS` | 平台允许列表 | 文件后缀白名单 |
| `MINERU_COMMAND` | 绝对路径 | MinerU CLI 路径 |
| `MINERU_WHEELHOUSE` | `vendor/mineru-wheelhouse` | 可选 MinerU 离线 wheelhouse 路径 |
| `MINERU_TIMEOUT_SECONDS` | 按文件页数调整 | OCR 超时 |
| `ENABLE_LLM_SPLIT` | `true` 或 `false` | 是否启用大模型拆题 |
| `DEEPSEEK_API_KEY` | 密钥管理注入 | DeepSeek API Key，新部署推荐使用 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek 官方 OpenAI 兼容地址 |
| `DEEPSEEK_MODEL` | `deepseek-v4-pro` | DeepSeek 模型名 |
| `DASHSCOPE_API_KEY` | 密钥管理注入 | 兼容旧部署或平台模型网关；不要发到 DeepSeek 官方域名 |
| `DASHSCOPE_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` 或平台模型网关 | 旧部署 OpenAI 兼容地址 |
| `DASHSCOPE_MODEL` | `deepseek-v4-pro` 或平台指定模型 | 沿用旧 Key 时的模型名 |
| `LLM_PROVIDER` | `deepseek` / `dashscope` | 模型 provider 标识 |
| `LLM_SPLIT_TIMEOUT_SECONDS` | 按模型 SLA 调整 | LLM 超时 |
| `LLM_BOUNDARY_TIMEOUT_SECONDS` | 按模型 SLA 调整 | AI 边界确认超时 |
| `OCR_VISUAL_REPAIR_ENABLED` | `true` | 是否启用题目 crop、横线检测和可选二次 OCR |
| `OCR_VISUAL_REPAIR_PDF_RENDER_SCALE` | `2.0` | PDF 页面 crop 渲染倍率 |
| `OCR_VISUAL_REPAIR_MIN_UNDERLINE_WIDTH_RATIO` | `0.12` | 横线检测的最小宽度比例 |
| `OCR_VISUAL_REPAIR_APPLY_PIX2TEXT` | `true` | 是否允许高置信 Pix2Text 结果覆盖低置信空位题题干 |
| `PIX2TEXT_COMMAND` | 可选 | Pix2Text 命令模板，例如 `p2t {image}`；未配置且 PATH 无命令时跳过二次 OCR |
| `PIX2TEXT_TIMEOUT_SECONDS` | `45` | 单题 crop 二次 OCR 超时 |
| `PANDOC_CJK_FONT` | 平台安装字体 | PDF 中文字体 |
| `PLATFORM_SECURITY_CONTEXT_VALIDATION_ENABLED` | `true` | 生产启用 Java 侧上下文 header 兜底校验 |
| `PLATFORM_SECURITY_AUTHORIZATION_REQUIRED` | `true` | 生产要求 `Authorization` header |
| `PLATFORM_SECURITY_REQUIRED_HEADERS` | `X-Tenant-Id,X-Operator-Id` | 生产必填平台上下文 |

当前新部署推荐使用 DeepSeek OpenAI 兼容配置；`DASHSCOPE_*` / DashScope 变量继续保留，用于旧部署、阿里云百炼或平台自建 OpenAI 兼容模型网关。

首次部署或迁移机器时，推荐直接使用一键部署入口：

```bash
./scripts/deploy_local.sh
```

它会自动安装基础 worker 依赖和前端依赖，自动避让被其它项目占用的 `8000/8018/5173` 端口，按 Python worker -> Java backend -> frontend 的顺序启动，并运行 basic smoke。实际端口和 URL 写入 `.run/deploy.env`，PID 和日志写入 `.run/pids/` 与 `.run/logs/`。

开发调试时可以使用 `./scripts/deploy_local.sh --dev-reload`，但 reload 范围只允许监听 `backend/python-worker/app/**/*.py`。不得让 `uvicorn --reload` 监听 `backend/python-worker/.venv` 或 `site-packages`，否则依赖库运行时文件事件会触发 worker 反复重启，表现为导入任务列表、创建后跳转或详情轮询长时间加载。

交付体验或 OCR 验收应启用默认 MinerU OCR provider：

```bash
./scripts/deploy_local.sh --with-mineru
```

该命令会在缺少 MinerU 时自动执行安装，启动后运行 OCR smoke。安装 MinerU 后会重新启动 worker，因此不会出现运行中 worker 未重新探测 `mineru` 命令的问题。
如果交付目录包含 `vendor/mineru-wheelhouse/`，安装脚本会优先从该离线大包安装 MinerU；否则才访问公网包源。wheelhouse 只解决依赖下载问题，不能替代目标机器本机创建 `backend/python-worker/.venv`。
未启用 MinerU 时，Markdown 导入仍可用于基础连通验证；PDF、图片、DOCX、PPTX、XLSX 和 `.doc` 转换链路会在创建任务前返回 503，避免产生不可处理的失败任务。

如果需要验证 AI 标准化和 AI 解析，先配置 `DEEPSEEK_API_KEY`、`DASHSCOPE_API_KEY` 或 `ALIYUN_LLM_API_KEY`，再执行：

```bash
./scripts/deploy_local.sh --with-ai
```

`--with-ai` 不作为默认启动项，因为它需要本地未提交密钥，并会调用真实模型服务。

未配置 Key 时，`--with-ai` 会在启动前失败并给出明确提示。基础部署成功、OCR 可用和 AI 全链路可用是三个不同验收等级：

```bash
./scripts/smoke_deploy_basic.py
./scripts/smoke_ocr.py
./scripts/smoke_ai.py
```

手工安装脚本仍可用于排障：`./scripts/install_backend.sh`、`./scripts/install_frontend.sh`、`./scripts/install_mineru.sh`。这些脚本会检测 `backend/python-worker/.venv` 是否能在当前机器运行；如果发现 venv 中的解释器或 console script shebang 指向旧机器路径，会自动删除并重建。

不要把开发机的 `.venv`、`backend/storage`、`backend/target`、`node_modules`、`local-platform/dist` 或真实 `.env` 复制到目标机器。

部署完成后可运行一次 watchdog：

```bash
./scripts/health_watchdog.sh --once --with-mineru
```

需要本地长时间演示或联调时，可由独立终端持续守护：

```bash
./scripts/health_watchdog.sh --with-mineru --restart
```

watchdog 读取 `.run/deploy.env`、`.run/pids/` 和三端健康接口；失败时输出 `.run/logs/` 中三类服务的日志尾部。`--restart` 会转调 `deploy_local.sh`，并保留 `--with-mineru` / `--with-ai` 运行模式。

如果前端“任务记录”一直显示加载中，先检查 `GET /api/import-tasks` 是否能在 1 秒内返回。该接口应直接读取 Java 持久化快照；如果它阻塞，优先查看 Java 日志是否在等待 worker、以及 Python worker 是否因 reload 反复重启。任务详情接口可以同步 worker 最新状态，但任务列表不能依赖 worker 实时可用。

启动示例：

```bash
source backend/python-worker/.venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir backend/python-worker
```

生产建议用 systemd、Supervisor、容器编排或平台进程管理托管，不建议直接在 shell 中长期运行。

### 5.1 单机 Docker Compose 部署

如果目标是单台服务器上的演示、预发或轻量联调，可使用 `docker-compose.server.yml` 构建一个应用容器。该镜像包含：

- nginx：对外提供前端静态资源，并把 `/api/*`、`/actuator/*`、`/v3/api-docs`、`/swagger-ui/*`、`/doc.html` 和 `/webjars/*` 转发到 Java backend。
- Java backend：监听容器内 `8018`，也默认映射到宿主机 `APP_JAVA_PORT`。
- Python worker：监听容器内 `127.0.0.1:8000`，不映射到宿主机。
- MinerU：默认通过 `HOST_MINERU_VENV` 挂载服务器本机 venv，默认命令为 `${HOST_MINERU_VENV}/bin/mineru`。

默认基础镜像为 `SERVER_BASE_IMAGE=nvcr.io/nvidia/tensorrt:23.09-py3`，适合已有 NVIDIA Docker runtime 的 GPU 服务器；Compose 配置包含 `gpus: all`，使 MinerU 在容器内可访问宿主机 GPU。如果服务器没有该基础镜像，也可改为 `python:3.11-slim-bookworm`，但首次拉取 Docker Hub 可能较慢。

构建镜像前先生成 Java jar 和前端静态资源：

```bash
(cd backend && mvn -DskipTests package)
(cd local-platform && npm run build)
```

启动：

```bash
docker compose -f docker-compose.server.yml up -d --build
```

默认访问：

```text
Web 和同源 API：http://<server-host>/
Java backend：http://<server-host>:8018
```

运行时配置仍通过项目根目录 `.env` 或平台密钥管理注入。大模型密钥只配置为环境变量，例如 `DEEPSEEK_API_KEY`、`DASHSCOPE_API_KEY` 或 `ALIYUN_LLM_API_KEY`，不要写入 Dockerfile、镜像层或 Compose 文件。

容器默认把持久化数据挂载到宿主机 `./server-data:/data`。以下变量已在 Compose 中指向 `/data`：

```text
PYTHON_WORKER_STORAGE_ROOT=/data
DB_URL=jdbc:h2:file:/data/java_library;MODE=MySQL;DATABASE_TO_LOWER=TRUE;CASE_INSENSITIVE_IDENTIFIERS=TRUE
JAVA_STORAGE_LOCAL_ROOT=/data/java_files
JAVA_DOMAIN_LIBRARY_STORE_PATH=/data/library_store.json
```

端口可通过 `.env` 调整：

```text
APP_HTTP_PORT=80
APP_JAVA_PORT=8018
SERVER_BASE_IMAGE=nvcr.io/nvidia/tensorrt:23.09-py3
HOST_MINERU_VENV=/aa/AI_GENERATION_TOGO/backend/python-worker/.venv
```

检查：

```bash
curl http://<server-host>/api/java/health
curl http://<server-host>/api/java/worker
curl http://<server-host>/api/capabilities/ocr-flow/runtime
docker compose -f docker-compose.server.yml logs --tail=200 question-engine
```

正式生产仍建议拆分数据库、对象存储、Redis/MQ 和进程托管边界；单容器 Compose 主要用于迁移前的服务器算力验证和轻量部署。

## 6. 数据库初始化

Java 使用 `backend/src/main/resources/schema.sql` 建表。生产 MySQL 应：

1. 创建独立数据库。
2. 使用平台 DBA 管理账号和权限。
3. 首次发布前在预发库执行 `schema.sql`。
4. 保留 Flyway/Liquibase 或平台 DDL 流程作为后续演进目标。

当前 `SchemaMigrator` 会在启动时补齐部分列，适合本地和过渡期。正式生产库仍建议走受控 DDL。

## 7. 对象存储

生产推荐：

```text
ENTERPRISE_MINIO_ENABLED=true
MINIO_ENDPOINT=http://minio:9000
MINIO_BUCKET=question-engine
```

注意：

- bucket 权限默认私有。
- 下载/预览 URL 应通过平台网关或短期签名控制。
- Java 本地目录只作为 fallback 或临时目录。
- 定期清理 OCR 临时产物和导出临时文件。

## 8. 启动顺序

推荐顺序：

1. MySQL。
2. 对象存储 / MinIO。
3. Redis / MQ。
4. Python worker。
5. Java backend。
6. 平台服务或网关路由。

启动后依次检查：

```bash
curl http://<worker-host>:8000/api/health
curl http://<java-host>:8018/api/java/health
curl http://<java-host>:8018/api/java/worker
curl http://<java-host>:8018/api/capabilities/ocr-flow/runtime
curl http://<java-host>:8018/api/capabilities/file-flow/runtime
```

## 9. 发布和回滚

发布前：

```bash
python scripts/check_question_engine_contract.py
python question-engine/sdk/generate-sdk.py
python scripts/check_project_portability.py
cd backend && mvn test
python scripts/package_question_engine_delivery.py --check-only
```

预发验证：

```bash
python scripts/acceptance_question_engine_plugin.py --base-url http://<pre-java-host>:8018
```

回滚要求：

- Java backend、Python worker、OpenAPI/SDK 版本必须成组回滚。
- 如果数据库 DDL 已发布，必须确认旧版本能兼容新增列。
- OpenAPI breaking change 不允许静默回滚，应通知平台调用方。
- 回滚后重新执行健康检查、能力目录检查和一次最小加工任务。

## 10. 监控指标

必须监控：

- `/actuator/health`
- `/actuator/prometheus`
- Java 进程 CPU、内存、GC、线程数。
- Python worker CPU、内存、进程存活。
- OCR job 耗时、失败率、超时率。
- AI job 耗时、失败率、token 或费用指标。
- callback event `failed` / `dead_letter` 数量。
- 文件存储写入失败数量。
- MySQL 连接池和慢查询。

## 11. 生产禁用兼容代理

`PYTHON_WORKER_API_PROXY_ENABLED` 本地默认是 `true`，用于平滑迁移旧 `/api/*` 路由。生产平台接入必须优先使用：

- `/api/capabilities/*`
- `/api/engine`
- `question-engine/openapi/question-engine.v1.yaml`
- generated SDK

除非有明确过渡计划，生产建议：

```text
PYTHON_WORKER_API_PROXY_ENABLED=false
```

如果暂时不能关闭，必须把仍依赖的 `/api/*` 路径列入迁移清单，并设置下线日期。

## 12. 运行排障树

生产和预发排障先查四个入口：

```bash
curl http://<java-host>:8018/api/java/health
curl http://<java-host>:8018/api/java/worker
curl http://<java-host>:8018/api/capabilities/ocr-flow/runtime
curl http://<java-host>:8018/api/capabilities/callback-flow/runtime
```

如果 Java backend 不可用，优先检查 Java 进程、端口 `8018`、`SPRING_PROFILES_ACTIVE`、MySQL 连接、`schema.sql` 执行状态和启动日志中的 bean 初始化错误。恢复动作包括修正环境变量、重启 Java backend、回滚最近版本，或按平台数据库流程修复 DDL。

如果 Python worker 不可达，优先检查 worker 进程、端口 `8000`、Java `PYTHON_WORKER_BASE_URL`、容器网络和 worker 依赖导入错误。恢复动作包括重启 worker、修复虚拟环境或镜像、回滚 worker 版本、临时扩容 worker。

如果 OCR provider 不可用，优先运行 `python scripts/check_mineru.py` 并检查 `MINERU_COMMAND`、worker 临时目录权限、`OCR_FLOW_EXTENSIONS`、OCR 超时、输入文件是否损坏或加密。`check_mineru.py` 中 `installed=true` 表示入口可用；`versionProbeOk=false` 只表示 `mineru --version` 探测失败或超时。恢复动作包括修复 MinerU 安装、调整 `MINERU_TIMEOUT_SECONDS`、重传清晰文件，或切换到平台指定 OCR provider。

如果 DeepSeek / LLM 失败，优先检查 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`、`DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`、`DASHSCOPE_MODEL`、模型限流、余额、题图 base64 大小、`LLM_BOUNDARY_TIMEOUT_SECONDS` 和 `LLM_SPLIT_TIMEOUT_SECONDS`。如果沿用旧 Key，必须保留旧平台 OpenAI 兼容网关，不要把旧 Key 发到 DeepSeek 官方域名。AI 边界确认失败时会回退本地边界候选；AI 标准化失败不应阻断人工校验，可以降级为 OCR 结果人工修复。

如果 Pandoc / XeLaTeX 导出失败，优先检查 `pandoc`、`xelatex`、`PANDOC_CJK_FONT`、Markdown 中 LaTeX 语法和 worker 临时目录权限。恢复动作包括安装依赖、配置中文字体、先导出 Markdown 或修复题目 LaTeX。

如果 MinIO / 对象存储写入失败，优先检查 `ENTERPRISE_MINIO_ENABLED`、`MINIO_ENDPOINT`、bucket、access key、secret key、服务账号权限和文件大小限制。必要时可临时切回本地文件 fallback，但必须记录迁移回对象存储的计划。

如果 callback 投递失败，优先检查 callback URL 可达性、平台接收端鉴权、secret、HMAC 是否按原始 body 校验、平台返回码和幂等处理。单个事件可手动重试：

```bash
curl -X POST http://<java-host>:8018/api/capabilities/callback-flow/events/<eventId>/retry \
  -H 'Content-Type: application/json' \
  -d '{"secret":"<callback-secret>"}'
```

如果任务一直停留在 `PROCESSING`，按顺序检查 Java 任务状态、paper/answer OCR job status、worker 日志、Java 是否收到 worker 结果、数据库任务更新时间和 callback 是否仅通知失败。平台前端不应无限轮询，超过 SLA 后应提示“后台继续处理”，并让用户稍后查看。

如果页面提示导入任务 `Not Found` 或任务明明 OCR 成功但仍显示 running，优先访问 Java 详情接口 `GET /api/import-tasks/{taskId}`。Java 会优先返回 `java_import_tasks` 持久快照；当 worker 兼容 store 丢失任务且 OCR job 文件仍在时，会调用 `/worker/import-tasks/recover` 从 OCR job 快照重建题目并回写 Java 表。同一任务恢复有任务级并发锁，避免多次轮询重复恢复。

如果 `backend/storage/library_store.json` 或 `backend/storage/jobs/*.json` 损坏，Python worker 会优先读取同名 `.bak` 备份并把损坏主文件隔离为 `.corrupt-*`。出现该情况时应保留 `.bak` 和 `.corrupt-*` 文件用于排查，不要直接删除整个 `backend/storage`。

提交排障信息时至少提供：

```text
environment:
baseUrl:
traceId:
tenantId:
operatorId:
jobId:
processingStatus:
failureReason:
paper filename:
file size:
createdAt:
updatedAt:
java health:
worker health:
ocr runtime:
callback event id:
```

不要在工单中粘贴真实 API Key、callback secret、完整试卷原文或图片 base64。

## 13. 性能基准与容量建议

影响性能的主要因素包括文件页数、图片清晰度、公式密度、题图数量、是否启用 AI、是否导出 PDF、worker 并发和对象存储吞吐。当前建议作为交付前基线模板，具体数值需要平台预发环境用脱敏样卷实测后填写。

初始限制建议：

| 项 | 本地开发 | 预发建议 | 生产初始建议 |
| --- | --- | --- | --- |
| 单文件大小 | 200 MB 以内 | 100 MB 以内 | 50 MB 以内，按平台容量调整 |
| 单任务页数 | 50 页以内 | 30 页以内 | 20 页以内，超出拆分 |
| OCR 并发 | 1 | 2 到 4 | 按 worker 实测扩容 |
| AI 并发 | 1 | 2 到 5 | 由模型网关限流 |
| Java read timeout | 300 秒 | 300 到 900 秒 | 生产建议异步 + callback |
| callback 重试 | 本地手动 | 3 次 | 3 到 5 次，超过进死信 |

基准测试命令：

```bash
python scripts/acceptance_question_engine_plugin.py \
  --base-url http://<pre-java-host>:8018 \
  --paper-file docs/samples/platform-integration/paper.md \
  --answer-file docs/samples/platform-integration/answer.md \
  --timeout-seconds 600
```

大文件样本可使用 `--large-file-mb` 单独触发，避免拖慢普通开发验证：

```bash
python scripts/acceptance_question_engine_plugin.py \
  --base-url http://<pre-java-host>:8018 \
  --large-file-mb 20 \
  --timeout-seconds 900
```

记录模板：

| 日期 | 环境 | 文件类型 | 页数 | 大小 | 题数 | OCR 耗时 | AI 耗时 | 总耗时 | 成功率 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 待填写 | pre | PDF |  |  |  |  |  |  |  |  |

初始 SLA 建议：

- 10 页以内普通试卷：5 分钟内完成 OCR + 拆题。
- 20 页以内试卷：10 分钟内完成，建议用 callback 通知。
- 超过 20 页或 50 MB：平台提示拆分上传。
- AI 标准化失败不应阻断人工校验。
- 导出失败不应影响已生成题目包。

扩容优先级先看 Python worker，因为 OCR、AI 和 export 的主要消耗都在 worker。生产扩容建议按 OCR 并发扩 worker 实例，Java backend 保持无状态或轻状态，数据库保存任务状态，对象存储统一保存大文件，使用 MQ 分发 OCR / AI / export job，并由平台侧按租户做限流和排队。

## 14. 数据保留与清理策略

生产环境必须在平台侧明确 OCR 临时数据保留周期。建议初始策略：

| 数据 | 建议保留 | 清理责任 |
| --- | --- | --- |
| 上传原文件副本 | 7 到 30 天，或平台入库完成后清理 | 平台文件中心 / Java file-flow |
| OCR 中间 Markdown / JSON | 7 到 30 天，排障窗口后清理 | Java 定时任务或平台批处理 |
| 题图文件 | 跟随平台题目生命周期；未入库临时题图 30 天内清理 | 平台文件中心 |
| 导出 DOCX/PDF | 7 天或按下载中心策略 | 平台文件中心 |
| callback event | 30 到 90 天 | Java callback-flow 或平台 MQ |
| worker 临时目录 | 每日清理失败和过期任务目录 | Python worker 运维脚本 |

清理规则必须满足：

- 不删除仍处于 `PROCESSING`、`WAITING_REVIEW`、`RETRYABLE` 的任务文件。
- 删除对象存储文件前先确认数据库元数据不再被题目包引用。
- 清理失败要记录 `traceId`、`jobId`、object key 和失败原因。
- 生产不得依赖人工进入服务器手动删除目录作为常规策略。

当前项目尚未内置生产级定时清理器。平台交付时应由平台任务调度、对象存储生命周期策略或后续 Java 定时任务承接。
