# ADR 0002: Python worker 边界

## 状态

Accepted

## 背景

OCR provider、Markdown/LaTeX 处理、AI prompt 编排和 Pandoc 导出已有稳定 Python 实现。完全重写到 Java 会增加风险，并拖慢交付。

同时，平台不能直接依赖 Python worker 的兼容 `/api/*` 路由，否则会绕过 Java 能力契约、OpenAPI、SDK、任务状态和安全边界。

## 决策

Python worker 只保留执行能力：

- OCR provider 调用。
- OCR 产物收集。
- 拆题。
- Markdown/LaTeX 标准化。
- AI 标准化和 AI 解析。
- Pandoc/XeLaTeX 导出。
- Java 仍需调用的短期兼容桥。

平台正式集成只调用 Java backend。

## 后果

正向影响：

- 保留 Python 生态对 OCR/AI/文档渲染的优势。
- Java 可以统一平台契约和安全边界。
- provider 替换成本较低。

代价：

- Java 和 Python 之间存在网络调用和超时管理。
- 需要运维两个进程。
- 需要逐步下线旧 `/api/*` 兼容桥。

## 约束

生产环境不应暴露 Python worker 给平台前端或公网。

`PYTHON_WORKER_API_PROXY_ENABLED` 生产建议关闭。
