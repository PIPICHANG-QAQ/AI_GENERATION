# 开发手册

本文面向接手本项目的后端、前端、平台集成和交付工程师。目标是解决“文档太多太散，不知道什么时候读什么”的问题。

## question-engine / SDK 能解决什么

`question-engine` 是 OCR 试卷处理插件的稳定能力边界，不是完整教育平台。它解决这些问题：

- 接收试卷和可选答案文件，创建异步加工任务。
- 调用 OCR-Flow，把 PDF、图片、Office 文档或 Markdown 转为统一 OCR 产物。
- 拆题、识别题型、选项、题图、答案和解析。
- 对 Markdown + LaTeX 做公式标准化和渲染校验。
- 调用 AI 标准化或 AI 解析，补全答案、解析、知识点、难度和分值候选。
- 提供人工校验工作台和题图管理能力。
- 输出平台可消费的 `question-package.v1`。
- 通过 callback-flow 把任务状态通知平台。
- 通过 OpenAPI 和 SDK 给平台团队稳定接入方式。

它不负责用户、权限、租户、学校、最终题库主表、审核流、发布状态、班级课程作业考试等平台业务。

## 先读顺序

新开发者建议按下面顺序阅读：

| 顺序 | 文档 | 目的 |
| --- | --- | --- |
| 1 | [根 README](../../README.md) | 启动项目，理解仓库整体范围 |
| 2 | [docs 索引](../README.md) | 看清文档分层和入口 |
| 3 | [Engine 交付边界](../architecture/ENGINE_DELIVERY_BOUNDARY.md) | 判断哪些能力属于插件，哪些属于平台 |
| 4 | [接口清单](../delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md) | 理解平台可调用接口、出入参、回调和 SDK |
| 5 | [SDK 使用说明](../../question-engine/sdk/USAGE.md) | 了解平台如何用 SDK 创建任务、轮询和取题目包 |
| 6 | [后端结构说明](../../backend/README.md) | 理解 Java backend 和 Python worker 代码放置规则 |
| 7 | [OCR 阶段规格](../product/OCR_PHASE_1_SPEC.md) | 改 OCR、AI、公式、题图或人工校验前读 |
| 8 | [题库二期规格](../product/QUESTION_BANK_PHASE_2_SPEC.md) | 改导入、题库、组卷、知识点或导出前读 |
| 9 | [部署与运维指南](../delivery/OPERATIONS_GUIDE.md) | 部署、排障、性能评估和生产配置前读 |
| 10 | [贡献与同步规则](CONTRIBUTING.md) | 每次改代码前读，避免接口、SDK、文档和测试漏同步 |
| 11 | [验收标准](../delivery/ACCEPTANCE.md) | 提测、预发、交付包验收前读 |

## 按任务查文档

| 任务 | 应阅读 | 看完应明确 |
| --- | --- | --- |
| 不确定需求是不是 engine 做 | [Engine 交付边界](../architecture/ENGINE_DELIVERY_BOUNDARY.md)、[接口清单](../delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md) | 需求属于插件、本地小平台还是平台自研 |
| 接入 SDK 创建加工任务 | [SDK 使用说明](../../question-engine/sdk/USAGE.md)、[接口清单](../delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md)、[OpenAPI](../../question-engine/openapi/question-engine.v1.yaml) | 如何上传文件、轮询任务、获取 `question-package.v1` |
| 新增或修改 Java 接口 | [后端结构说明](../../backend/README.md)、[技术设计](../architecture/TECHNICAL_DESIGN.md)、[贡献与同步规则](CONTRIBUTING.md) | Controller、Service、Model、OpenAPI、SDK、测试如何同步 |
| 修改 `/api/engine` 或能力目录 | [Engine 交付边界](../architecture/ENGINE_DELIVERY_BOUNDARY.md)、[接口清单](../delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md) | 模块、能力目录和平台职责如何保持一致 |
| 修改 question-processing | [接口清单](../delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md)、[SDK 使用说明](../../question-engine/sdk/USAGE.md)、[验收标准](../delivery/ACCEPTANCE.md) | 加工任务、任务视图、标准题目包和验收脚本是否一致 |
| 替换 MinerU 或改 OCR provider | [OCR 阶段规格](../product/OCR_PHASE_1_SPEC.md)、[Python worker README](../../backend/python-worker/README.md)、[运维指南](../delivery/OPERATIONS_GUIDE.md) | provider 输入输出、配置、runtime 和替换路径 |
| 修改 AI 标准化、AI 解析、答案解析匹配 | [OCR 阶段规格](../product/OCR_PHASE_1_SPEC.md)、[技术设计](../architecture/TECHNICAL_DESIGN.md)、[后端结构说明](../../backend/README.md) | AI worker、Java job、标准化候选、写回闸门、题图上下文和验收点 |
| 修改题图、图片库、文件访问 | [接口清单](../delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md)、[技术设计](../architecture/TECHNICAL_DESIGN.md)、[安全契约](../delivery/SECURITY_AND_INTEGRATION_CONTRACT.md) | file-flow、访问权限、SDK 方法和平台文件边界 |
| 修改组卷或导出 | [题库二期规格](../product/QUESTION_BANK_PHASE_2_SPEC.md)、[技术设计](../architecture/TECHNICAL_DESIGN.md)、[运维指南](../delivery/OPERATIONS_GUIDE.md) | 组卷流程、试卷数据、导出 job 和 Pandoc worker 边界 |
| 修改知识点库 | [题库二期规格](../product/QUESTION_BANK_PHASE_2_SPEC.md)、[后端结构说明](../../backend/README.md) | 知识点 CRUD、题目关联和 Java 数据层边界 |
| 修改本地小平台页面 | [本地小平台 Example](../product/LOCAL_PLATFORM_AS_EXAMPLE.md)、[题库二期规格](../product/QUESTION_BANK_PHASE_2_SPEC.md)、[renders](../renders/README.md) | 哪些页面行为可参考，哪些不能当正式平台契约 |
| 做安全或生产接入评审 | [安全契约](../delivery/SECURITY_AND_INTEGRATION_CONTRACT.md)、[接口清单](../delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md)、[运维指南](../delivery/OPERATIONS_GUIDE.md) | 鉴权、header、callback 签名、文件访问、限流和审计边界 |
| 做验收或冒烟测试 | [验收标准](../delivery/ACCEPTANCE.md)、[贡献与同步规则](CONTRIBUTING.md)、[根 README](../../README.md) | 必测接口、验收脚本、业务冒烟脚本和通过标准 |
| 打交付包 | [交付包说明](../delivery/DELIVERY_PACKAGE.md)、[安全契约](../delivery/SECURITY_AND_INTEGRATION_CONTRACT.md)、[运维指南](../delivery/OPERATIONS_GUIDE.md) | 包含/排除路径、清理规则、打包命令和生产要求 |
| 排查生产问题 | [运维指南](../delivery/OPERATIONS_GUIDE.md)、[错误码与状态机](../delivery/ERROR_AND_STATUS_GUIDE.md) | 故障现象、排查路径、恢复动作和状态解释 |

## 文档分工

Product 文档回答“业务应该怎样表现”：

- [PRD](../product/PRD.md)：产品目标、用户、范围和非目标。
- [OCR 阶段规格](../product/OCR_PHASE_1_SPEC.md)：OCR、AI、公式、题图、人工校验和 provider 替换。
- [题库二期规格](../product/QUESTION_BANK_PHASE_2_SPEC.md)：导入、题库、组卷、知识点和导出。
- [本地小平台 Example](../product/LOCAL_PLATFORM_AS_EXAMPLE.md)：本地页面如何演示能力，平台哪些地方不能照搬。

Architecture 文档回答“代码和系统边界怎么分”：

- [技术设计](../architecture/TECHNICAL_DESIGN.md)：跨模块技术实现。
- [Engine 交付边界](../architecture/ENGINE_DELIVERY_BOUNDARY.md)：交付边界、Java/Python 分工和平台职责。
- [ADR](../architecture/decisions/README.md)：关键架构决策及背景。

Delivery 文档回答“平台如何接入、部署、验收、运维”：

- [接口清单](../delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md)：平台接口和 SDK。
- [安全契约](../delivery/SECURITY_AND_INTEGRATION_CONTRACT.md)：生产鉴权、上下文、签名、文件访问和限流。
- [部署与运维指南](../delivery/OPERATIONS_GUIDE.md)：部署、回滚、排障和性能容量建议。
- [错误码与状态机](../delivery/ERROR_AND_STATUS_GUIDE.md)：状态、错误码、重试规则和展示建议。
- [验收标准](../delivery/ACCEPTANCE.md)：验收标准和插件级验收套件。
- [交付包说明](../delivery/DELIVERY_PACKAGE.md)：交付目录、排除目录、打包和验收包内容。

Development 文档回答“改代码时必须同步什么”：

- [贡献与同步规则](CONTRIBUTING.md)：新增接口、改 OpenAPI、改 SDK、加测试、更新文档的固定流程。

## 项目搭建顺序

1. 阅读 [根 README](../../README.md) 的本地启动说明。
2. 复制 `.env.example` 为 `.env`，按需配置 DeepSeek / OpenAI 兼容 LLM、MinIO、MySQL、Redis/MQ。
3. 启动基础本地环境：`./scripts/deploy_local.sh`。
4. 需要验证 OCR 时执行：`./scripts/deploy_local.sh --with-mineru`。
5. 需要验证 AI 时优先配置 `DEEPSEEK_API_KEY`；兼容旧部署时也可配置 `DASHSCOPE_API_KEY` 或 `ALIYUN_LLM_API_KEY`，然后执行：`./scripts/deploy_local.sh --with-ai`。
6. 打开部署脚本输出的前端 URL 验证本地小平台；实际端口见 `.run/deploy.env`。
7. 调用部署脚本输出的 Java backend URL 下 `/api/java/health`、`/api/java/worker`、`/api/capabilities` 验证能力入口。
8. 运行基础检查：

不要从其它电脑复制 `backend/python-worker/.venv`。如果目录已经存在但来自旧机器，部署脚本和安装脚本会检测坏的 `bin/python` 或 `mineru`/`uvicorn` shebang 并自动重建。

```bash
python scripts/check_question_engine_contract.py
python question-engine/sdk/generate-sdk.py
python scripts/check_project_portability.py
./scripts/test_python_worker.sh
./scripts/smoke_deploy_basic.py
python scripts/package_question_engine_delivery.py --check-only --include-local-platform
```

## 改代码前后检查

改代码前：

1. 先判断影响范围：接口、状态、部署、存储、SDK、前端、OCR provider、AI、导出、callback、验收。
2. 根据上面的任务表读对应文档。
3. 阅读 [贡献与同步规则](CONTRIBUTING.md)。

改代码后：

1. 更新受影响的 Product / Architecture / Delivery / Development 文档。
2. 如果接口变了，更新 `question-engine/openapi/question-engine.v1.yaml` 和 SDK。
3. 如果状态或错误变了，更新 [错误码与状态机](../delivery/ERROR_AND_STATUS_GUIDE.md)。
4. 如果部署或配置变了，更新 [部署与运维指南](../delivery/OPERATIONS_GUIDE.md) 和根 README。
5. 至少运行文档和契约检查：

```bash
python scripts/check_question_engine_contract.py
python scripts/check_project_portability.py
./scripts/test_python_worker.sh
python scripts/package_question_engine_delivery.py --check-only --include-local-platform
```

## 常见问题

| 问题 | 先读 |
| --- | --- |
| 这个需求到底是不是 engine 做？ | [Engine 交付边界](../architecture/ENGINE_DELIVERY_BOUNDARY.md) |
| 我要调哪个接口？ | [接口清单](../delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md)、[SDK 使用说明](../../question-engine/sdk/USAGE.md) |
| OpenAPI 是不是源头？ | [OpenAPI](../../question-engine/openapi/question-engine.v1.yaml)、[贡献与同步规则](CONTRIBUTING.md) |
| Python 还能不能新增业务接口？ | [Python worker README](../../backend/python-worker/README.md)、[Engine 交付边界](../architecture/ENGINE_DELIVERY_BOUNDARY.md) |
| OCR provider 怎么换？ | [OCR 阶段规格](../product/OCR_PHASE_1_SPEC.md) |
| 本地小平台能不能直接复制到公司平台？ | [本地小平台 Example](../product/LOCAL_PLATFORM_AS_EXAMPLE.md) |
| 改完应该测什么？ | [验收标准](../delivery/ACCEPTANCE.md)、[贡献与同步规则](CONTRIBUTING.md) |
