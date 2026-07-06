# Generated SDK

本目录是 `question-engine/openapi/question-engine.v1.yaml` 对应的生成型 SDK 输出。

- `typescript/`：浏览器或前端管理端使用的 TypeScript client 和模型类型。
- `java/`：平台服务端使用的 Java client 和 record 模型。

`examples/` 目录中的旧手写 client 只作为调用示例保留，不再作为平台正式对接主入口。

当前轻量生成器只校验 OpenAPI 源文件和已检入 SDK 文件是否存在；在接入完整 OpenAPI Generator 前，新增能力必须同步更新 OpenAPI、TypeScript SDK、Java SDK、接口说明和回归测试。
