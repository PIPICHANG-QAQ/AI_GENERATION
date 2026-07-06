# 文档索引

本目录保存项目相关文档。一级目录只保留入口文件和主题子目录，避免所有文档堆在 `/docs` 根目录。

## 推荐入口

- [开发手册](development/DEVELOPMENT_GUIDE.md)：新开发者先读，说明 question-engine/SDK 能解决什么问题、阅读顺序、按任务查文档方式和项目搭建路径。
- [贡献与同步规则](development/CONTRIBUTING.md)：每次改代码前读，说明接口、OpenAPI、SDK、测试、文档和部署配置的固定同步流程。
- [接口清单](delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md)：平台开发者对接 question-engine 时读，说明核心接口、出入参、回调、SDK 和不推荐接入方式。
- [交付包说明](delivery/DELIVERY_PACKAGE.md)：交付给平台团队前读，说明包含/排除目录、打包命令和验收规则。

## 目录结构

```text
docs/
  README.md
  CHANGELOG.md
  product/        产品范围、OCR 规格、本地小平台 example
  architecture/   技术设计、交付边界、架构图、ADR
  delivery/       接口、安全、部署运维、错误状态、验收、交付包
  development/    开发手册、贡献规则、同步检查清单
  example/        local-platform 作为 example 的流程图
  renders/        界面线框图、渲染图和截图
  samples/        脱敏样卷和预期输出
```

## Product

- [PRD](product/PRD.md)：本期 question-engine 题库加工能力与本地小平台产品需求。
- [OCR 阶段规格](product/OCR_PHASE_1_SPEC.md)：OCR-Flow、选择题/空位题结构保护、视觉修复、AI 标准化、AI 解析、公式校验、人工校验和 OCR provider 替换边界。
- [题库二期规格](product/QUESTION_BANK_PHASE_2_SPEC.md)：题目导入、题库中心、小问复合题、按小问组卷、知识点库、导出和平台集成输出。
- [本地小平台 Example](product/LOCAL_PLATFORM_AS_EXAMPLE.md)：说明 `local-platform` 如何演示 question-engine 能力，包括 `subQuestions` 和试卷层 `subSelections`，哪些流程可参考，哪些本地实现不应依赖。

## Architecture

- [技术设计](architecture/TECHNICAL_DESIGN.md)：后端、前端、存储、MinerU、大模型拆题、选择题/空位题结构保护、题目 crop 视觉修复、公式标准化、AI 语义修复和人工编辑集成设计。
- [Engine 交付边界](architecture/ENGINE_DELIVERY_BOUNDARY.md)：题库能力发动机交付边界、平台职责、Java/Python 分工和本地小平台排除范围。
- [架构决策记录](architecture/decisions/README.md)：Java 主后端、Python worker、MinerU provider、本地 H2 模式等关键 ADR。
- `architecture/*.mmd` / `architecture/*.svg`：Mermaid 架构图和流程图。

## Delivery

- [接口清单](delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md)：question-engine 封装接口说明书，包含 `question-package.v1`、选择题/空位题输出约束、小问字段和组卷 `subSelections`。
- [安全与集成契约](delivery/SECURITY_AND_INTEGRATION_CONTRACT.md)：平台鉴权、上下文 header、callback 签名、文件访问和限流责任边界。
- [部署与运维指南](delivery/OPERATIONS_GUIDE.md)：生产部署、环境变量、启动顺序、健康检查、回滚、排障树和性能基准。
- [错误码与状态机](delivery/ERROR_AND_STATUS_GUIDE.md)：正式错误码、状态机、可重试规则和平台展示建议。
- [验收标准与验收套件](delivery/ACCEPTANCE.md)：本期统一验收标准和插件级验收脚本。
- [交付包说明](delivery/DELIVERY_PACKAGE.md)：交付包边界、清理规则、打包方式和交付前检查。

## Development

- [开发手册](development/DEVELOPMENT_GUIDE.md)：文档导航、阅读顺序和任务到文档映射。
- [贡献与同步规则](development/CONTRIBUTING.md)：新增接口、改 OpenAPI、改 SDK、加测试、更新文档的固定流程。

## Supporting Material

- [example](example/README.md)：`local-platform` 调用 SDK/question-engine 的 SVG 时序图和业务流程图。
- [renders](renders/README.md)：界面线框图、渲染图和截图。
- [samples](samples/README.md)：脱敏样卷、答案文件和预期 `question-package.v1`。
- [CHANGELOG](CHANGELOG.md)：项目变更记录。

## 本地验证脚本

- `../scripts/start_project_with_java_backend.sh`：默认重启并启动 Python worker、Java backend 和 local-platform。
- `../scripts/smoke_local_platform_business.py`：本地小平台基础业务冒烟测试。
- `../scripts/acceptance_question_engine_plugin.py`：平台插件级验收脚本。
- `../scripts/package_question_engine_delivery.py`：交付包打包和边界检查脚本。
