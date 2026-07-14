# ADR 0003: 默认使用 MinerU OCR provider

## 状态

Accepted

## 背景

试卷 PDF 和图片中包含公式、题图、版面结构和多列排版。项目需要先获得可本地运行的 OCR 能力，并保留未来替换 OCR provider 的空间。

## 决策

默认 OCR provider 使用 MinerU CLI。

同时采用两级边界隔离业务层：

- `OcrProvider` 只负责把上传文件转换为已验证的 `CanonicalOcrBundle`，不能调用题库后处理或写入平台任务状态。
- `ocr_execution` 在 Provider 成功后统一调度后处理；Provider 失败则不进入后处理。
- `MineruOcrBundleAdapter` 将 MinerU 的目录和私有 JSON 转为 `CanonicalOcrBundle v1`。
- 题库后处理只从 Bundle 读取 Markdown、图片、页面、布局块、阅读顺序、Markdown offset 与源文件证据；原始 Provider 信息仅用于审计。
- Bundle 会随成功 job 持久化；后续 outputs 刷新优先复用它，只有历史 job 缺少 Bundle 时才走 MinerU 兼容适配。
- provider 运行时由 `/api/capabilities/ocr-flow/runtime` 暴露。
- 替换 provider 时实现 Bundle Adapter，而不是复制题库后处理流程。

## 后果

正向影响：

- 本地和预发环境可以快速跑通 OCR。
- 对公式和文档解析更友好。
- 后续可以替换为平台统一 OCR 服务，且保留当前拆题、题图、选项、小问、视觉修复和 AI 兜底策略。

代价：

- 需要安装和维护 MinerU。
- 大文件耗时和资源消耗较高。
- provider 输出差异需要在 Adapter 中归一化；达到 L2（Markdown、图片、页码/尺寸、bbox、阅读顺序、源文件/页图）前不得宣称与 MinerU 同等题图准确率。
- 兼容期的视觉修复仍依赖只读本地 `artifactRoot`，外部 Provider 需要物化其图片和页图；后续由 `ArtifactResolver` 消除该限制。

## 约束

不得在平台业务代码或题库后处理代码中直接依赖 MinerU 内部目录结构。

MinerU 特有的文件名、`_middle.json` / `content_list` 选择与字段映射只能位于 `MineruOcrBundleAdapter`。`*_middle.json` 优先级、Markdown offset 对齐、题图资产路径和既有回退规则必须保持不变。

替换 provider 必须更新：

- `docs/product/OCR_PHASE_1_SPEC.md`
- `docs/delivery/OPERATIONS_GUIDE.md`
- `scripts/acceptance_question_engine_plugin.py` 如有必要
