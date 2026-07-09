# 贡献指南

本文定义后续开发者修改 `question-engine`、backend、SDK、OpenAPI 和文档时必须遵守的流程。

## 1. 开发前判断归属

先判断需求属于哪一类：

| 类型 | 优先修改 |
| --- | --- |
| 平台可调用能力 | `backend/src/main/java/com/aigeneration/questionbank/capability`、`question-engine/openapi`、`question-engine/sdk` |
| engine 目录或交付边界 | `backend/src/main/java/com/aigeneration/questionbank/engine`、`docs/architecture/ENGINE_DELIVERY_BOUNDARY.md` |
| 本地题库/组卷/知识点业务 | `backend/src/main/java/com/aigeneration/questionbank/domain` |
| OCR/AI/导出执行能力 | `backend/python-worker/app` |
| 平台接入文档 | `docs/delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md`、`question-engine/sdk/USAGE.md` |
| 本地小平台 example | `local-platform/`、`docs/product/LOCAL_PLATFORM_AS_EXAMPLE.md` |

新增平台业务状态不得放入 Python worker。

## 2. 修改接口的固定流程

如果新增或修改平台可调用接口，必须同步：

1. Java controller/service/model。
2. OpenAPI：`question-engine/openapi/question-engine.v1.yaml`。
3. TypeScript SDK：`question-engine/sdk/generated/typescript`。
4. Java SDK：`question-engine/sdk/generated/java`。
5. 接口说明：`docs/delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md`。
6. SDK 使用说明：`question-engine/sdk/USAGE.md`。
7. 最小接入样例：`examples/platform-integration/`。
8. 测试：Java test 或平台验收脚本。
9. 变更记录：`docs/CHANGELOG.md`。

检查命令：

```bash
python question-engine/sdk/generate-sdk.py
python scripts/check_question_engine_contract.py
```

## 3. 修改状态或错误的固定流程

如果新增 `processingStatus`、错误码、失败原因或重试策略，必须同步：

- `docs/delivery/ERROR_AND_STATUS_GUIDE.md`
- `question-engine/openapi/question-engine.v1.yaml`
- SDK model
- 平台验收脚本
- `docs/delivery/ACCEPTANCE.md`

状态语义不能只写在代码注释里。

## 4. 修改部署或配置的固定流程

如果新增环境变量、profile、端口、对象存储、MQ、Redis、worker 配置，必须同步：

- `backend/src/main/resources/application.yml`
- `.env.example`
- `docs/delivery/OPERATIONS_GUIDE.md`
- `README.md`

生产敏感信息只能写变量名和占位符。

## 5. 修改 Python worker 的固定流程

Python worker 只允许承载：

- OCR provider。
- 拆题。
- AI 标准化/解析。
- Markdown/LaTeX 处理。
- DOCX Pandoc 导出。
- PDF XeLaTeX 预览模板导出。
- Java 仍需调用的兼容桥。

修改后至少执行：

```bash
python -m compileall backend/python-worker/app
```

如果影响 OCR provider，必须同步：

- `docs/product/OCR_PHASE_1_SPEC.md`
- `docs/delivery/OPERATIONS_GUIDE.md`

如果影响拆题、选择题选项、小问、题图归属、空位题占位或 AI 标准化提示词，必须同步：

- `docs/product/OCR_PHASE_1_SPEC.md`
- `docs/architecture/TECHNICAL_DESIGN.md`
- `docs/architecture/ocr-flow.mmd`
- `docs/delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md`
- `docs/CHANGELOG.md`
- `backend/python-worker/tests`

## 6. 测试要求

| 改动 | 最低测试 |
| --- | --- |
| Java controller/service | `cd backend && mvn test` |
| OpenAPI/SDK | `python question-engine/sdk/generate-sdk.py`、`python scripts/check_question_engine_contract.py` |
| Python worker | `./scripts/test_python_worker.sh`、`python -m compileall backend/python-worker/app` |
| 平台能力主链路 | `python scripts/acceptance_question_engine_plugin.py` |
| 本地部署 | `./scripts/deploy_local.sh`、`./scripts/smoke_deploy_basic.py` |
| OCR / MinerU | `./scripts/deploy_local.sh --with-mineru`、`./scripts/smoke_ocr.py` |
| AI 链路 | `./scripts/deploy_local.sh --with-ai`、`./scripts/smoke_ai.py` |
| 本地小平台完整业务 | `python scripts/smoke_local_platform_business.py` |
| 文件类型 | `python scripts/smoke_import_file_types.py` |

如果因为环境缺失不能运行某项测试，必须在变更说明中写明原因。

## 7. 文档要求

代码改动不得只改代码。以下变化必须更新文档：

- 接口、字段、状态、错误码变化。
- SDK 方法变化。
- 部署、配置、启动方式变化。
- 安全、权限、回调、文件访问变化。
- OCR provider 或 AI provider 变化。
- OCR 拆题、选择题选项、空位题占位、小问结构、题图引用或 AI 标准化规则变化。
- 交付包边界变化。
- 性能、并发、超时建议变化。

安全、权限、回调签名、上下文 header、文件访问或限流责任发生变化时，必须同步 `docs/delivery/SECURITY_AND_INTEGRATION_CONTRACT.md`。

## 8. 提交前自查

提交前执行：

```bash
python scripts/check_question_engine_contract.py
python question-engine/sdk/generate-sdk.py
python scripts/check_project_portability.py
python scripts/package_question_engine_delivery.py --check-only --include-local-platform
./scripts/test_python_worker.sh
cd backend && mvn test
```

文档-only 改动至少执行：

```bash
python scripts/check_question_engine_contract.py
python scripts/check_project_portability.py
python scripts/package_question_engine_delivery.py --check-only --include-local-platform
```

## 9. 不接受的改动

- 把真实密钥写入仓库。
- 把 `backend/storage/`、`backend/target/`、`.venv/`、`node_modules/` 打进交付包。
- 让平台正式接入 Python worker。
- 修改 OpenAPI 但不更新 SDK。
- 修改状态语义但不更新错误状态文档。
- 用本地小平台 adapter 替代正式 SDK。

## 10. 开发检查清单

每次代码迭代前先确认本次需求是否改变行为、接口、界面、部署、存储、验证方式或架构，并检查 `/docs` 下哪些文档会受影响。OCR-Flow、AI 校验、题库闭环和 question-engine 能力边界必须保持可回归；本地小平台只能复用同一套 Markdown + LaTeX 编辑、题图和公式标准化能力，不应形成第二套业务规则。

编码过程中必须遵守：

- 运行产物不要进入版本控制。
- `backend/python-worker/.venv` 必须在当前机器用安装脚本重建，不能跨机器复制；venv 内的 Python 和 console script 会包含创建机器的绝对路径。
- API Key、模型密钥、访问令牌等敏感信息只能通过环境变量或本地未提交配置提供。
- `.env` 可以用于本地调试，但必须保持在 `.gitignore` 中。
- 项目文档放在 `/docs` 目录，根目录 `README.md` 只作为启动入口。
- 涉及题目展示、人工校验、入库或组卷时，必须检查题图是否同时保留在 `images` 字段和题干 Markdown 图片引用中。
- 涉及 OCR 拆题或 AI 标准化时，必须先把问题抽象为通用结构能力，例如边界确认、选项识别、空位占位、小问归属、题图归属或答案解析证据回溯；不得只针对单张截图、单个题号或单段文本硬编码。
- 涉及选择题、空位题或小问识别时，至少补一组非截图依赖的回归样例，覆盖同类泛化 cue，而不是只覆盖当前失败样本。
- 涉及前端布局时，必须检查桌面、中等窗口和窄窗口下是否存在内容遮挡、横向溢出或操作按钮不可点击。

新增或改变 `question-engine` 能力时，必须先确认能力归属：`question-processing`、`ocr-flow`、`review-workbench`、`ai-flow`、`export-flow`、`file-flow`、`callback-flow` 或 `sdk-openapi`。如果新增或改变平台可调用接口，必须同步更新 OpenAPI、SDK、接口清单、验收脚本和变更记录。

推荐完整验证命令：

```bash
python question-engine/sdk/generate-sdk.py
python scripts/check_question_engine_contract.py
python scripts/check_project_portability.py
./scripts/test_python_worker.sh
(cd backend && JAVA_HOME=$(/usr/libexec/java_home -v 17) mvn test)
(cd local-platform && npm run build)
./scripts/deploy_local.sh
./scripts/smoke_deploy_basic.py
./scripts/smoke_local_platform_business.py
```

完成时必须说明代码变更、文档变更、已运行的验证命令和结果；如果某次代码变更确认不影响文档，也必须在交付说明中写明原因。

## 11. 新增能力变更模板

新增或修改一个平台可调用能力时，按这个顺序提交，避免未来开发者只改代码不改契约：

1. 在 Java `capability` 或 `engine` 目录补 Controller / Service / Model。
2. 在 `question-engine/openapi/question-engine.v1.yaml` 增加 path、operationId、request/response schema。
3. 更新 TypeScript 和 Java generated SDK，或至少在 `question-engine/sdk/generate-sdk.py` 中补齐预期 operationId 和 SDK 方法检查。
4. 更新 `docs/delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md` 的接口说明和调用示例。
5. 如果新增状态或错误，更新 `docs/delivery/ERROR_AND_STATUS_GUIDE.md`。
6. 如果涉及部署、依赖、环境变量、限流或回滚，更新 `docs/delivery/OPERATIONS_GUIDE.md`。
7. 补 Java 测试；如果能力落在 Python worker，补 Python 编译或单元测试。
8. 补 `scripts/acceptance_question_engine_plugin.py` 或最小 smoke 脚本覆盖。
9. 更新 `docs/CHANGELOG.md`。

提交说明至少包含：

```text
capability:
openapi:
sdk:
docs:
tests:
compatibility:
rollback:
```

## 12. OCR Provider 插件开发模板

替换或新增 OCR provider 时，必须保持 `ocr-flow` 统一 outputs 不变。最小开发模板：

1. 在 `backend/python-worker/app/ocr_flow.py` 新增 provider 类。
2. 实现 `name`、`status()`、`run(job_id, upload_path, runtime)`。
3. 在 provider 注册表中注册。
4. 新增配置项时同步 `.env.example`、`application.yml`、`docs/product/OCR_PHASE_1_SPEC.md` 和 `docs/delivery/OPERATIONS_GUIDE.md`。
5. 确保输出目录能被 `collect_outputs()` 找到 Markdown、JSON 和图片资源。
6. 更新 `GET /api/capabilities/ocr-flow/runtime` 相关测试或验收点。
7. 用至少一份脱敏样卷验证 `questions`、`assets`、`mathValidation`、`sourceEvidence` 不退化。

Provider 不允许直接写平台题库、用户权限、审核流或知识点主数据。

## 13. SDK 发布和升级模板

发布 SDK 前必须确认：

- OpenAPI `info.version` 已按 `MAJOR.MINOR.PATCH` 更新。
- `question-engine/sdk/RELEASE.md` 已说明兼容性、breaking change 和升级方式。
- `python question-engine/sdk/generate-sdk.py` 通过。
- `python scripts/check_question_engine_contract.py` 通过。
- `python scripts/check_project_portability.py` 通过。
- `examples/platform-integration/typescript` 和 `examples/platform-integration/java` 仍能编译或具备明确运行说明。
- 平台预发环境通过 `scripts/acceptance_question_engine_plugin.py`。

如果只是源码 vendoring，交付说明中必须写清楚平台拿到的是源码 SDK，不是 npm/Maven 已发布包。

## 14. 测试分层要求

后续测试按风险分层补齐：

| 层级 | 覆盖内容 | 推荐位置 |
| --- | --- | --- |
| Java 单元/MockMvc | Controller、Service、状态机、file-flow、callback-flow、question-package | `backend/src/test/java` |
| Python worker | OCR provider、Markdown 收集、AI 请求组装、DOCX Pandoc fallback、PDF XeLaTeX/ReportLab fallback | `backend/python-worker/tests` |
| 契约检查 | OpenAPI、SDK、文档同步、交付包边界 | `scripts/check_question_engine_contract.py` |
| 迁移检查 | 绝对路径、坏 venv、坏 symlink、运行产物泄漏 | `scripts/check_project_portability.py` |
| 插件验收 | 创建任务、轮询、题目包、题图、AI、callback、非法文件、大文件 | `scripts/acceptance_question_engine_plugin.py` |
| 平台样例 | TypeScript/Java 最小接入链路 | `examples/platform-integration` |

新增高风险能力时，不接受只有文档没有测试。
