# ADR 0003: 默认使用 MinerU OCR provider

## 状态

Accepted

## 背景

试卷 PDF 和图片中包含公式、题图、版面结构和多列排版。项目需要先获得可本地运行的 OCR 能力，并保留未来替换 OCR provider 的空间。

## 决策

默认 OCR provider 使用 MinerU CLI。

同时通过 `ocr-flow` 抽象隔离业务层：

- 业务层只依赖 Markdown、JSON、assets、questions、mathValidation 等统一输出。
- provider 运行时由 `/api/capabilities/ocr-flow/runtime` 暴露。
- 替换 provider 时实现相同输出结构。

## 后果

正向影响：

- 本地和预发环境可以快速跑通 OCR。
- 对公式和文档解析更友好。
- 后续可以替换为平台统一 OCR 服务。

代价：

- 需要安装和维护 MinerU。
- 大文件耗时和资源消耗较高。
- provider 输出差异仍需归一化。

## 约束

不得在平台业务代码中直接依赖 MinerU 内部目录结构。

替换 provider 必须更新：

- `docs/product/OCR_PHASE_1_SPEC.md`
- `docs/delivery/OPERATIONS_GUIDE.md`
- `scripts/acceptance_question_engine_plugin.py` 如有必要
