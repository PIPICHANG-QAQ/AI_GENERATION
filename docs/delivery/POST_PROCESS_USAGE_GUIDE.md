# OCR Post Process 使用说明书

## 1. 适用范围

本文说明如何把任意 OCR provider 的识别结果接入现有题库后处理能力。当前稳定边界是：

```text
原始文件
  -> OCR provider
  -> provider adapter
  -> CanonicalOcrBundle (canonical-ocr-bundle.v1)
  -> OcrPostProcessingPipeline
  -> 兼容现有 OCR outputs
  -> Java 导入任务、人工校验与题库入库
```

Post Process 负责拆题、选项和小问恢复、题图归属、公式处理、结构校验、必要的 AI 补全以及布局证据整理。它不负责调用具体 OCR 引擎，也不负责平台用户、权限、审核流或最终题库主数据。

## 2. 交付和 SDK 决策

当前采用两层交付，不再复制一套独立的 Java/TypeScript“算法 SDK”：

| 使用场景 | 交付入口 | 说明 |
| --- | --- | --- |
| 公司平台或前端调用完整题库能力 | `question-engine` Java/TypeScript SDK | 通过稳定 HTTP API 创建任务、查询结果、获取能力描述；OpenAPI 版本 `1.2.0` |
| 在 Python worker 内嵌入新 OCR provider | `app.ocr` Python 包入口 | 使用 `CanonicalOcrBundle` 和 `OcrPostProcessingPipeline.run_bundle()`，不依赖 MinerU 私有结构 |

暂不发布独立远程 Post Process SDK/HTTP 接口，原因是当前后处理仍需要同一 worker 的任务记录、OCR artifact tree、图片文件和运行配置。若直接把 `run_bundle()` 包装成公网接口，会遗漏大文件传输、对象存储解析、鉴权、幂等、配额和任务状态等必要契约。

后续只有在以下条件同时满足时，才应新增独立 Post Process Service SDK：

1. `artifactRoot` 被受控的 Artifact Resolver 或对象存储 URI 替代；
2. 输入支持 manifest 上传/引用并有完整性校验；
3. 定义异步 job、幂等键、超时、重试和取消语义；
4. 建立租户、权限、审计、资源配额和敏感数据规则；
5. 使用黄金样本证明服务化前后题数、选项、小问、题图、公式和性能无回退。

## 3. 稳定 Python 入口

```python
from app.ocr import (
    CanonicalOcrBundle,
    OcrAsset,
    OcrLayoutBlock,
    OcrPage,
    OcrPostProcessingPipeline,
    SourceDocumentRef,
)
```

上述符号是 provider-neutral 的嵌入式入口。MinerU 私有文件名和 JSON 字段只允许出现在 `app.ocr.mineru_adapter.MineruOcrBundleAdapter`；新 provider 应提供自己的 adapter。

## 4. CanonicalOcrBundle v1

### 4.1 必填字段

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `schemaVersion` | string | 固定为 `canonical-ocr-bundle.v1` |
| `documentId` | string | 必须与当前 OCR job id 一致 |
| `inputSha256` | string | 原文件内容哈希；无法读取原文件时可使用规范 Markdown 哈希 |
| `canonicalMarkdown` | string | 非空；provider 归一后的完整 OCR Markdown |
| `artifactRoot` | string | 兼容期显式必需；必须是已存在的只读工件目录 |

### 4.2 可选证据

| 字段 | 用途 |
| --- | --- |
| `assets[]` | 图片等 OCR 资产；Markdown 中的本地图片引用必须能在资产表中解析 |
| `pages[]` | 页码、页面宽高和可选页图引用 |
| `layoutBlocks[]` | 文本/图片块的页码、bbox、阅读顺序、Markdown offset 和图片引用 |
| `sourceDocumentRef` | 同机原文件路径或受控 URI |
| `markdownArtifactPath` / `jsonArtifactPath` | 相对 `artifactRoot` 的持久化工件路径 |
| `producer` | provider 名称、版本等非业务元数据 |
| `nativeArtifacts[]` | 供诊断使用的 provider 原生工件清单；后处理不能依赖私有字段 |
| `capabilities[]` | provider 实际提供的证据能力 |
| `json` | 归一化或原生 JSON 证据；不得替代稳定字段 |

### 4.3 能力等级

| 等级 | 最低证据 | 预期效果 |
| --- | --- | --- |
| L0 | Markdown + artifactRoot；不要求 assets/layout | 可进行基础拆题和公式处理，复杂题图/版面可能需要人工复核 |
| L1 | Markdown + embedded-images | 可建立题图库并处理 Markdown 图片引用 |
| L2 | L1 + layout-bbox + source-page | 可使用二维版面证据提高题目框、选项和题图归属准确度 |

能力等级表示可用证据，不代表准确率承诺。adapter 必须如实声明，不得伪造 bbox、页尺寸或图片引用。

## 5. 最小接入示例

```python
import hashlib
from pathlib import Path

from app.ocr import CanonicalOcrBundle, OcrPostProcessingPipeline

job_id = "ocr-job-20260715-001"
artifact_root = Path("/data/ocr/jobs") / job_id
markdown_path = artifact_root / "paper.md"
markdown = markdown_path.read_text(encoding="utf-8")

bundle = CanonicalOcrBundle(
    document_id=job_id,
    input_sha256=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
    canonical_markdown=markdown,
    artifact_root=str(artifact_root),
    markdown_artifact_path="paper.md",
    producer={"name": "tencent-ocr", "version": "example"},
    capabilities=frozenset({"markdown"}),
)

outputs = OcrPostProcessingPipeline().run_bundle(bundle)
```

该示例是嵌入 worker 的调用方式，不是无状态库调用。当前实现要求 `documentId` 对应的 worker job 和工件上下文已建立。生产接入应让 provider 实现 `OcrProvider`，由 `ocr_execution._run_provider_then_postprocess()` 统一完成状态、manifest 持久化和异常处理。

## 6. 新 Provider 接入步骤

1. 实现 provider 的可用性检查和 `run(OcrProviderRequest)`。
2. 在 provider adapter 中把原生结果转成 `CanonicalOcrBundle`。
3. 成功时返回 `OcrProviderResult(success=True, bundle=bundle, metadata=...)`。
4. 注册 provider，并通过 `OCR_FLOW_PROVIDER` 选择；按需调整 `OCR_FLOW_EXTENSIONS`。
5. 禁止 provider 直接调用拆题、标准化、AI 或题库写入逻辑。
6. 使用相同黄金样本对比默认 MinerU 与新 provider 的 bundle 和最终 outputs。

推荐目录：

```text
app/ocr/
  contracts.py             # 公共输入契约
  postprocess_pipeline.py  # 统一后处理入口
  mineru_adapter.py        # MinerU 私有适配
  <provider>_adapter.py    # 新 provider 私有适配
```

## 7. 校验规则

进入后处理前至少执行以下校验：

- schema 版本受支持；
- `documentId`、`inputSha256`、`canonicalMarkdown`、`artifactRoot` 非空；
- `documentId` 与当前 job 一致；
- `artifactRoot` 必须解析为已存在目录；
- Markdown 图片引用可在 `assets` 中解析；
- 页码唯一且非负，页面尺寸为正；
- bbox 为 `[x0, y0, x1, y1]` 且坐标有序；
- 非空 `markdownArtifactPath`、`jsonArtifactPath`、`assets[].path` 和 `nativeArtifacts[].path` 必须是 `artifactRoot` 内真实存在的相对文件；绝对路径和包含 `..` 的路径一律拒绝；
- `sourceDocumentRef.path` 是原文件引用，不受 artifactRoot 包含性约束。

契约错误应直接失败并记录明确原因，不允许静默降级成错误题目结构。

## 8. 输出与兼容性

`run_bundle()` 当前复用既有 `collect_outputs_impl()`。确定性工件测试已验证默认 adapter 的 `run(jobId)` 与显式 `run_bundle(bundle)` 归一化 outputs 一致；该证据不等同于受控真实语料准确率或性能结论。主要输出包括：

- `questions`、`sections` 和题目结构证据；
- `assets`、题图库、`imagePlacements` 和布局信息；
- `mathValidation`、边界置信度和人工复核原因；
- 现有标准化、AI 补全及指标元数据。

provider 替换不得要求 Java API、前端工作台或题库模型理解 provider 私有结构。

## 9. 测试与质量门禁

基础契约测试：

```bash
cd backend/python-worker
.venv/bin/python -m pytest -q tests/test_ocr_postprocess_contracts.py
```

完整改动至少检查：

1. bundle 序列化/恢复和非法输入；
2. provider adapter 对同一工件的确定性；
3. `run(jobId)` 与 `run_bundle(bundle)` 在确定性工件上的归一化输出等价；
4. 黄金样本的题数、选项数、小问数、题图资产守恒和 placement；
5. LLM/OCR 调用数量、顺序和并发无意外变化；
6. 延迟、内存和工件体积通过受控 baseline 比较；当前 `tests/ocrflow-performance/baseline-ref.json` 仍为 `pending-controlled-baseline`，门禁未完成；
7. 失败时保留可诊断 manifest，且不覆盖人工校验结果。

## 10. 常见问题

### Markdown 中有图片，但 bundle 校验失败

确认 `assets[].path/name/url` 至少有一个能解析 Markdown 引用。若 Markdown 位于子目录，设置正确的 `markdownArtifactPath`，相对图片路径会以该文件所在目录解析。

### 新 provider 只有文字，没有 bbox

按 L0 提供真实证据即可。不要制造坐标。后处理会保留基础识题能力，对依赖几何证据的题目进入人工复核。

### 是否可以从 Java 直接调用 run_bundle

当前不建议。Java/平台调用现有 Question Engine SDK；Python worker 内的 provider 通过 `app.ocr` 嵌入式入口调用。待 Artifact Resolver 和异步服务契约完成后，再评估独立远程 Post Process SDK。

当前已有结构、工具和确定性工件回归证据；受控真实试卷语料 gate 与受控性能 baseline 均仍待建立，不得用本地临时 benchmark 结果替代。
