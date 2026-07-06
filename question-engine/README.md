# question-engine 交付说明

此目录是题库能力发动机的交付入口说明，不包含本地小平台页面代码。

当前 engine 代码仍在主工程中维护，交付切割线以 Java 包和文档为准：

- Java 能力目录：`backend/src/main/java/com/aigeneration/questionbank/engine`
- 接口清单：`GET /api/engine/interfaces`
- 能力 API：`/api/engine`、`/api/capabilities`、`/api/capabilities/ocr-flow`、`/api/capabilities/question-processing`
- AI 编排：`/api/capabilities/ai-flow/jobs`
- 导出编排：`/api/capabilities/export-flow/jobs`
- 文件协议：导入原文件、导入题图、题库题图和导出文件由 Java `file-flow` 管理
- 回调协议：`/api/capabilities/callback-flow/runtime`、`/api/capabilities/callback-flow/events`
- OpenAPI 契约：`question-engine/openapi/question-engine.v1.yaml`
- SDK 使用说明：`question-engine/sdk/USAGE.md`
- SDK 发布说明：`question-engine/sdk/RELEASE.md`
- 生成型 SDK：`question-engine/sdk/generated/typescript`、`question-engine/sdk/generated/java`
- 手写 SDK 示例：`question-engine/sdk/examples`
- 平台最小接入样例：`examples/platform-integration`
- 开发者接口说明书：`docs/delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md`
- 生产安全契约：`docs/delivery/SECURITY_AND_INTEGRATION_CONTRACT.md`
- 部署手册：`docs/delivery/OPERATIONS_GUIDE.md`
- 插件级验收：`docs/delivery/ACCEPTANCE.md`
- 本地小平台 example 说明：`docs/product/LOCAL_PLATFORM_AS_EXAMPLE.md`
- 详细边界：`docs/architecture/ENGINE_DELIVERY_BOUNDARY.md`

后续如果要拆成独立 Maven 子模块，建议模块名为 `question-engine-core`，只包含：

- engine 能力目录
- capability 能力 API
- domain 服务和实体
- config/common/migration
- Python worker 调用配置
- SDK/OpenAPI 交付说明

不应包含：

- `local-platform/`
- 历史 Replit 原型仓库
- 本地截图和原型资产
- `backend/storage/` 演示数据
