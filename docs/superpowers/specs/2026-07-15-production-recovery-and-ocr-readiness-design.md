# 生产恢复与 OCR Readiness 加固设计

## 1. 背景与已确认根因

本设计面向 2026-07-15 的本地与服务器生产恢复。服务器任务标题为“123”，内部任务 ID 为 `import_task_20260715_065444_e0d1c55f`，试卷 OCR job 为 `ocr_20260715_065444_6f78252a`。原文件能够预览，但试卷 OCR 状态为 `failed`，题目数为 0。

只读诊断确认：

- Java backend、Python worker 和 MinerU API 进程均可启动；
- OCR runtime 只通过 `mineru --version` 判定 provider 可用，因此返回 `installed=true`；
- 真实解析进入 MinerU pipeline 后，Jinja2 导入 MarkupSafe 失败；
- 服务器 `vendor/mineru-venv` 中 `markupsafe` 只剩 `__pycache__/*.pyc`，缺少 `__init__.py`、`_native.py` 和扩展文件；
- Python 将该目录识别为空 namespace package，最终产生 `ImportError: cannot import name 'Markup' from 'markupsafe'`；
- 同一任务重试后复现相同错误。

因此根因不是文件上传、Java 路由、GPU 不可见或 MinerU API 不可达，而是服务器 MinerU venv 不完整，同时现有健康检查无法识别“命令可执行但运行依赖损坏”的假健康状态。

## 2. 目标

本轮必须达到以下结果：

1. 现有未提交的 provider-neutral OCR、OpenAPI、SDK、测试和文档改动得到保留，不被恢复工作覆盖。
2. MinerU provider readiness 能识别关键依赖缺失、深度 import 失败和 API 不可用。
3. MinerU venv 可在本地或服务器指定目录中确定性重建，验证成功后再切换为活动环境。
4. 本地 Java、Python worker、前端和 MinerU 可启动并通过代码级、契约级和运行态验收。
5. 新交付包先在服务器 staging 校验，再部署到生产目录。
6. 服务器 OCR 恢复后先通过小样本，再重试任务“123”；真实任务必须产出题目并进入待校验或完成状态。
7. 所有部署步骤都有明确回滚点，不删除现有任务、原文件、数据库、模型缓存和历史 venv。
8. provider 解耦计划和模块化计划只同步有证据的检查项，未完成项保持未勾选。

## 3. 非目标与后续子项目

本轮不把下列独立业务能力混入生产恢复补丁：

- 用户账号、认证、租户权限和角色授权；
- 题目版本、修订历史和审计记录；
- 企业审核流和审批状态机；
- 真实 MQ、outbox 和异步消费治理；
- 超时扫描器、租约回收和任务补偿；
- 正式 npm/Maven SDK 发布流水线。

生产恢复完成后按上述顺序分别进行“设计 → 实施计划 → TDD 实现 → 独立验收”。每个子项目必须能独立交付和回滚。

## 4. 方案比较与选择

### 4.1 采用：宿主机 venv 原子重建与深度 readiness

继续使用服务器当前的宿主机 MinerU venv 挂载方式，但把安装、验证和切换做成可重复流程。新环境安装在临时目录，完成完整性和运行时检查后，再原子替换活动路径。

优点是改动小、恢复快、可沿用当前 GPU 和模型缓存配置。缺点是宿主机仍承担 Python 依赖生命周期，因此必须由脚本和部署门禁保护。

### 4.2 未采用：把 MinerU 完全打入 question-engine 镜像

该方案环境更不可变，但会显著增加镜像体积、CUDA 兼容复杂度和构建时间，也会把 MinerU 与 Java/前端发布节奏绑定。本轮不采用。

### 4.3 未采用：拆分独立 MinerU 服务

该方案长期边界更清晰，但需要额外设计鉴权、异步任务、制品传输、幂等、超时和容量治理，超出生产恢复范围。本轮保留现有同容器进程模型。

## 5. 总体架构与执行顺序

```text
保留现有工作区改动
  -> 生产恢复分支
  -> RED：残缺依赖仍被判为 installed 的回归测试
  -> 深度 MinerU runtime probe
  -> 可指定目标目录的 venv 构建与验证
  -> 本地全量测试和运行态 smoke
  -> 构建可追溯交付包
  -> 服务器 staging 静态与依赖校验
  -> mineru-venv.new 完整安装和验证
  -> 原子切换活动 venv
  -> 重建/重启 question-engine
  -> 小样本 OCR
  -> 重试任务“123”
  -> 业务闭环与日志验收
  -> 证据化同步计划、changelog 和 runbook
```

## 6. 组件设计

### 6.1 MinerU runtime probe

readiness 由三层证据组成：

1. `mineru --version` 成功；
2. 与 MinerU pipeline 同一 Python 解释器能够导入关键依赖和运行入口；
3. 启用 MinerU API 时，API readiness 能在限定时间内响应。

深度 import 至少覆盖：

- `markupsafe.Markup`；
- `jinja2.Environment`；
- `transformers`；
- MinerU pipeline 的模型初始化模块或等价稳定入口。

readiness 返回结构保留现有 `installed`、`command`、`version` 字段，并增加不含敏感信息的检查结果。任一必选检查失败时 `installed=false`，错误中指出失败层级和异常摘要。

### 6.2 确定性 venv 构建

安装入口支持显式目标目录。服务器构建流程使用 `vendor/mineru-venv.new-<timestamp>`，不在活动 venv 内执行增量修补。

构建完成后依次验证：

- Python、pip/uv 和 console scripts 可用；
- package metadata 与关键源文件存在；
- 深度 import probe 通过；
- `mineru --version` 通过；
- 最小 provider/API smoke 通过。

验证全部通过后，把旧 venv 重命名为带时间戳备份，再把新 venv 重命名为活动路径。任何验证失败都删除或隔离新目录，不改活动路径。

### 6.3 启动与部署门禁

本地 `--with-mineru` 和服务器启动入口在启动服务前执行同一 runtime probe。provider 不可用时启动或 OCR 能力必须明确失败，不能只依赖 Java/worker HTTP health。

服务器发布采用 staging 目录验证交付包的结构、脚本、JAR、前端静态资源、OpenAPI/SDK 和配置键。生产 `.env`、`server-data` 和模型缓存不进入交付包，也不被 staging 覆盖。

### 6.4 计划同步

计划检查项按以下证据分类：

- `done`：有对应提交、自动化测试和必要运行记录；
- `partial`：部分实现但未通过该任务定义的完整门禁，保持未勾选并追加说明；
- `not-started`：没有可验证实现，保持未勾选。

provider 解耦计划和 215 项模块化计划不得根据文件存在或主观判断批量勾选。

## 7. 数据流与状态处理

OCR 请求继续经过：

```text
Java import task
  -> Python worker OCR job
  -> MinerU API/CLI
  -> provider adapter
  -> CanonicalOcrBundle
  -> OcrPostProcessingPipeline
  -> Java task snapshot
  -> review workbench
```

readiness 失败发生在创建 provider 任务之前。已有失败任务保留原 job、错误和原文件，恢复后通过现有 retry 入口重新投递；不创建替代任务，不删除失败记录。

任务“123”的重试必须满足：

- 使用原始上传文件；
- 通过 `POST /api/import-tasks/{taskId}/retry` 重用原 OCR job ID，并由 worker 将 `retryCount` 加一、清空旧错误和时间字段后重新执行；
- 最终 `paperOcrStatus=success`；
- 题目数大于 0；
- 原文件预览、布局、题图和结构化结果仍可读取。

## 8. 错误处理、回滚与安全

部署前记录并备份：

- 当前应用目录版本和交付 manifest；
- `.env` 的文件备份，权限不放宽；
- 数据库、任务 store 和 Java 文件存储的备份或可验证快照；
- 当前活动 MinerU venv 路径、Python 版本和关键包 manifest；
- 当前容器镜像 ID 和 Compose 配置摘要。

不复制或删除 `server-data/modelscope-cache`。不在日志、文档和 Git 中记录 API Key、密码、Authorization、完整 OCR 文本或图片 base64。

以下任一情况触发停止发布并回滚：

- 深度 runtime probe 失败；
- Java、worker、前端或 MinerU API health 失败；
- 小样本 OCR 失败；
- 任务“123”重试再次出现 provider 依赖错误；
- 数据库、原文件或历史任务不可读；
- 新增持续 traceback 或 GPU 分配偏离约定。

回滚顺序为：停止新容器、恢复旧镜像/应用版本、恢复旧 venv 活动路径、重启并执行基础 health。任务和数据默认不回滚；仅在明确证明发布过程修改了数据且备份验证通过时使用数据恢复。

## 9. 测试与验收矩阵

### 9.1 自动化测试

- 为残缺 MarkupSafe/关键 import 编写失败测试，先证明旧检查误报，再实现修复；
- Python worker 全量测试；
- Java JDK 17 全量测试；
- 前端 Vitest 和 production build；
- portability、OCR boundary、OpenAPI/SDK contract 检查；
- OCR golden、benchmark 和相关工具测试；
- `git diff --check` 与敏感信息扫描。

### 9.2 本地运行态

- `deploy_local.sh --with-mineru` 成功；
- Java、worker、前端和 OCR runtime 可访问；
- basic smoke、OCR smoke 和本地业务 smoke 通过；
- PDF、图片和已支持 Office 文件类型按现有 smoke 覆盖；
- 题图、人工校验、入库、组卷和导出闭环通过；
- 只有本地已存在有效模型 Key 时运行 AI smoke；没有 Key 时明确记录为外部条件未执行，不计为通过。

### 9.3 服务器运行态

- Java、worker、前端和 MinerU API health 通过；
- OCR runtime 显示深度 readiness 通过；
- GPU0 执行 AI_GENERATION/MinerU，GPU1 保持给 vLLM；
- 小样本 OCR 成功；
- 任务“123”重试后成功并产生题目；
- 原文件预览、题图、布局和 question package 可读取；
- 服务器业务 smoke 和适用的 AI/export smoke 通过；
- 发布后日志没有新的依赖 traceback、任务持久化错误和代理路由错误。

## 10. 完成定义

本轮只有在以下条件全部满足时才可标记完成：

1. runtime probe 的 RED/GREEN 回归证据完整；
2. 本地代码级和运行态验收完成，所有失败和跳过项有明确结论；
3. 服务器新 venv、应用版本和回滚点均可追溯；
4. 小样本与任务“123”均通过 OCR；
5. 服务日志和 GPU 分配符合预期；
6. provider 解耦计划、模块化计划、CHANGELOG、服务器 CHANGELOG 和 RUNBOOK 已按证据同步；
7. 未把六个后续企业子项目误报为本轮已完成；
8. 形成最终验收报告，包含命令、测试数量、耗时、失败/跳过项、部署版本和后续风险。
