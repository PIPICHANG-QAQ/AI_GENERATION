# OCR Provider 与题目后处理解耦设计

## 目标

将题目后处理从 MinerU 的目录、文件名和私有 JSON 结构中解耦。任何 OCR 系统只要提供符合 `CanonicalOcrBundle v1` 的证据包，即可复用当前拆题、选项、题图归属、小问、视觉修复、公式和 AI 增强流程。

本次不改变已有题目业务、算法顺序、Prompt、阈值、回退策略、并发配置或公开 OCR 输出字段。

## 决策

采用“Provider 原始结果 → Provider Adapter → CanonicalOcrBundle → QuestionPostprocessService”的两阶段模型。

`CanonicalOcrBundle` 是唯一由后处理读取的 OCR 输入。Provider 名称和原始 JSON 只能存在于 `producer` 与 `nativeArtifacts`，后处理算法不得据此分支。旧 `collect_outputs(jobId)` 保留为兼容外观：它先通过 MinerU Adapter 构造 bundle，再调用新后处理入口。

## 能力等级

- L0：Markdown/文本；仅支持基础文本拆题。
- L1：L0 加图片资源和稳定图片引用；支持基础图文题。
- L2：L1 加页码、页面尺寸、阅读顺序、布局 bbox 与源文件或页面渲染引用；才允许声明与当前完整准确率对齐。

缺少 L2 的输入不会被伪装为完整能力：应返回能力告警和人工复核提示。第一轮只实现契约记录与验证，不改变现有流程的降级行为。

## CanonicalOcrBundle v1

必填字段：

- `schemaVersion`、`documentId`、`inputSha256`、`canonicalMarkdown`。
- `assets[]`：稳定 ID、相对路径、URL、大小、类型。
- `layoutBlocks[]`：文本/图片块、页码、bbox、页面尺寸、阅读顺序、图片路径。
- `sourceDocumentRef`：当前可读取上传文件的引用。
- `artifactRoot`：兼容期内只读制品根目录。
- `producer` 与 `nativeArtifacts`：审计信息，不作为后处理分支条件。

第一轮的 bundle 刻意保留 `artifactRoot`。这避免为了抽象而改变当前图片、页图与视觉 crop 的 I/O 路径；后续才由 Artifact Resolver 取代这个兼容字段。

## 不变式

- `*_middle.json` 优先、`*_content_list.json` 兜底的布局证据优先级不变。
- Markdown offset 与 layout block 的文本对齐规则不变。
- 题图资产路径/文件名匹配和人工确认保护不变。
- 视觉预处理与边界识别并行、视觉修复并发上限不变。
- 高置信本地边界跳过 LLM；低置信 LLM 兜底和结构校验回退不变。
- Provider 与 LLM 调用次数不因解耦增加。
- 原 `outputs` 的字段、嵌套和业务语义不变。

## 首轮范围

1. 新增 Python 强类型契约、Bundle 构造器及输入校验。
2. 新增 MinerU Adapter，将现有文件树转换为统一 bundle。
3. 将后处理入口改为接收 bundle；现有算法仍按原顺序执行。
4. 让旧 `collect_outputs(jobId)` 委托“MinerU Adapter + 新入口”。
5. 增加契约、Adapter、兼容输出与调用路径测试。

不在首轮实现：腾讯 SDK、Java 外部 API、SDK 发布、对象存储 Resolver、生产流量切换。它们依赖首轮 MinerU 零差异结果。

## 验收

- 既有 OCR flow、processing、postprocess facade 测试保持通过。
- 新 Bundle 输入与旧 `collect_outputs(jobId)` 对相同 MinerU 制品产生逐字段相同的 OCR outputs。
- 缺少 `canonicalMarkdown`、缺少图片引用或非法 bbox 的 bundle 被明确拒绝。
- L2 bundle 能保留页面、布局块和源文件引用。
- 不新增 OCR/LLM 调用；基准回放和性能门禁继续可执行。
