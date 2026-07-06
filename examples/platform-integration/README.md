# Platform Integration Examples

本目录给平台开发团队提供最小接入样例。它不是本地小平台，也不是正式业务页面，只展示如何从平台服务调用 `question-engine`。

## 前置条件

先启动或准备一个 Java backend 地址：

```bash
export QUESTION_ENGINE_BASE_URL=http://localhost:8018
```

平台生产环境还应设置：

```bash
export QUESTION_ENGINE_TOKEN=<platform-token>
export QUESTION_ENGINE_TENANT_ID=tenant-001
export QUESTION_ENGINE_OPERATOR_ID=teacher-001
```

## TypeScript

示例文件：

```text
typescript/src/index.ts
```

运行方式由平台工程决定。该示例直接引用仓库内 generated SDK：

```ts
import { QuestionEngineClient } from "../../../question-engine/sdk/generated/typescript";
```

它演示：

1. 创建 client。
2. 检查能力目录。
3. 读取 engine 接口清单。
4. 轮询已有 job。
5. 获取 `question-package.v1`。

multipart 创建任务在 `question-engine/sdk/USAGE.md` 中有浏览器和 Node/BFF 说明，平台生产环境推荐由平台后端接收文件后再调用 engine。

## Java

示例文件：

```text
java/src/main/java/com/aigeneration/examples/PlatformIntegrationExample.java
```

示例依赖 generated Java SDK 和 Jackson。当前仓库 SDK 还不是 Maven artifact，平台可以：

1. 把 `question-engine/sdk/generated/java/src/main/java` 复制到平台工程。
2. 或把 generated Java SDK 发布为内部 Maven artifact。
3. 或由平台 CI 从 OpenAPI 生成自有 SDK。

## 样例输入输出

脱敏输入和预期输出见：

```text
docs/samples/platform-integration/
```

## 不要复制的内容

- 不要复制 `local-platform/src/lib/api.ts` 作为正式 SDK。
- 不要直接调用 Python worker。
- 不要把本地 H2 或本地文件目录作为平台主数据。
- 不要依赖 `raw` 字段做正式业务逻辑。
