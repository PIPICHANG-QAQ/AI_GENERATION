# ADR 0001: Java 作为主后端

## 状态

Accepted

## 背景

项目从本地题库系统收敛为可交付的 OCR 试卷处理能力服务。平台接入需要稳定 API、OpenAPI、SDK、任务状态、文件元数据、回调、监控和企业化配置。

Python 原始链路适合快速实现 OCR/AI/导出，但不适合作为公司平台长期业务 API 和企业化接入层。

## 决策

Java Spring Boot backend 作为唯一主后端：

- 暴露 `/api/capabilities/*` 和 `/api/engine`。
- 维护任务、题目、文件、AI job、导出 job、callback event 元数据。
- 管理 OpenAPI/SDK 对外契约。
- 对接 MySQL、对象存储、Redis/MQ、监控和平台网关。
- 内部调用 Python worker。

## 后果

正向影响：

- 平台集成边界更稳定。
- OpenAPI 和 SDK 更容易纳入企业交付流程。
- Java 可以承载长期业务状态和企业依赖。

代价：

- Java 与 Python 之间需要维护 bridge。
- 短期存在部分兼容路由。
- 新增能力必须同时考虑契约、SDK、文档和测试。

## 约束

新增平台业务 API 必须优先进入 Java。

Python worker 不得新增平台业务状态。
