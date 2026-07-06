# Question Engine SDK 发布说明

本文说明 `question-engine/sdk` 如何发布、版本如何管理、兼容性如何判断，以及平台团队如何升级。

## 1. 当前形态

当前 SDK 是检入仓库的 generated 源码，不是已发布 npm 包或 Maven artifact。

目录：

```text
question-engine/sdk/generated/typescript
question-engine/sdk/generated/java
```

契约源头：

```text
question-engine/openapi/question-engine.v1.yaml
```

当前轻量校验脚本：

```bash
python question-engine/sdk/generate-sdk.py
python scripts/check_question_engine_contract.py
```

`generate-sdk.py` 当前仍不是完整 OpenAPI Generator，但已经会做以下发布前校验：

- OpenAPI 基础版本和关键路径存在。
- `operationId` 不重复且覆盖 SDK 预期方法。
- `securitySchemes`、全局 security 和生产 header 契约存在。
- 所有 `#/components/schemas/*`、`#/components/parameters/*`、`#/components/securitySchemes/*` 引用可解析。
- `ProcessingJob`、`QuestionPackage`、`ProcessedQuestion`、callback 等关键 schema 的 required 字段未被误删。
- checked-in TypeScript / Java SDK 文件存在且包含核心方法。

它仍不负责根据 OpenAPI 重写 SDK 源码。正式发布 npm/Maven 包前，建议接入 OpenAPI Generator 或平台统一 SDK 生成流水线。

## 2. 版本规则

OpenAPI `info.version` 是平台契约版本。

建议版本格式：

```text
MAJOR.MINOR.PATCH
```

| 版本段 | 什么时候变 |
| --- | --- |
| `MAJOR` | 删除字段、改字段含义、改路径、改状态枚举、破坏旧 SDK 行为 |
| `MINOR` | 新增接口、新增可选字段、新增能力，不破坏旧调用方 |
| `PATCH` | 文档、示例、非破坏性 bug fix、SDK 内部修复 |

`question-package.v1` 是输出数据包版本，和 OpenAPI 版本不是同一个概念。只要标准题目包结构发生破坏性变化，应升级 `question-package` 版本并保留兼容说明。

## 3. 发布方式

### 3.1 当前源码 vendoring

平台团队可以把 generated SDK 源码复制到平台工程：

```text
question-engine/sdk/generated/typescript
question-engine/sdk/generated/java
```

适合早期联调，但需要平台团队手动同步版本。

### 3.2 私有 npm 包

推荐 TypeScript SDK 后续发布为内部 npm 包：

```text
@company/question-engine-sdk
```

发布内容：

- `QuestionEngineClient.ts`
- `models.ts`
- `index.ts`
- README 和版本说明

### 3.3 私有 Maven artifact

推荐 Java SDK 后续发布为内部 Maven artifact：

```text
com.aigeneration:question-engine-sdk:<version>
```

发布内容：

- `QuestionEngineClient`
- `QuestionEngineModels`
- Jackson 依赖声明
- JDK 17 兼容说明

### 3.4 平台 CI 自生成

长期推荐平台 CI 从 OpenAPI 生成 SDK：

```text
question-engine/openapi/question-engine.v1.yaml
  -> OpenAPI Generator
  -> 平台统一 SDK 风格
```

仓库内 generated SDK 仍作为参考实现和兼容样例。

## 4. 发布前检查

每次发布 SDK 前必须执行：

```bash
python question-engine/sdk/generate-sdk.py
python scripts/check_question_engine_contract.py
cd backend && mvn test
```

如果接口契约变化，还必须检查：

- `docs/delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md`
- `question-engine/sdk/USAGE.md`
- `examples/platform-integration/`
- `docs/CHANGELOG.md`
- `docs/delivery/ERROR_AND_STATUS_GUIDE.md`

## 5. 兼容性要求

非破坏性变化：

- 新增可选字段。
- 新增接口。
- 新增状态但旧状态含义不变。
- 新增 warning 类型。
- 新增 runtime 字段。

破坏性变化（breaking change）：

- 删除字段。
- 必填字段改名或改类型。
- `processingStatus` 枚举删除或语义变化。
- `question-package.v1` 字段语义变化。
- endpoint path 或 HTTP method 变化。
- callback 签名算法变化。

破坏性变化（breaking change）必须：

1. 升级 MAJOR 版本。
2. 更新迁移指南。
3. 保留旧版本兼容窗口。
4. 提供测试样例。

## 6. 平台升级流程

平台升级 SDK 应按以下流程：

1. 阅读 `docs/CHANGELOG.md`。
2. 对比 `question-engine/openapi/question-engine.v1.yaml`。
3. 更新 SDK 源码或依赖版本。
4. 跑平台编译和单元测试。
5. 在预发环境执行 `scripts/acceptance_question_engine_plugin.py`。
6. 对至少一份脱敏样卷完成端到端加工。
7. 确认 callback、文件访问和权限仍符合平台安全策略。

## 7. 当前限制

- TypeScript SDK 已包含 multipart helper。
- Java SDK 当前主要覆盖 JSON API；multipart 创建任务建议平台用 OpenAPI Generator 生成，或参考 `examples/platform-integration/java`。
- 当前 `generate-sdk.py` 是增强型轻量校验器，不替代完整 OpenAPI Generator。
- SDK 不管理认证、租户、权限、审计和限流，只透传平台 header。
