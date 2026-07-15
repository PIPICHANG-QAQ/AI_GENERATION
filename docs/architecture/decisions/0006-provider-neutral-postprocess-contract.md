# ADR 0006：使用 CanonicalOcrBundle 解耦 OCR Provider 与题库后处理

- 状态：已接受
- 日期：2026-07-15
- 决策范围：OCR provider、Python worker、Post Process、Question Engine SDK

## 背景

题库识别质量依赖拆题、选项/小问恢复、题图归属、公式处理和人工复核等后处理能力。若这些能力直接读取 MinerU 私有目录和 JSON 字段，更换腾讯 OCR 或其它 provider 时会复制算法、改变调用顺序，并增加准确率和性能回退风险。

## 决策

1. OCR provider 只负责识别和生成原生工件。
2. 每个 provider 通过私有 adapter 输出 `canonical-ocr-bundle.v1`。
3. `OcrPostProcessingPipeline.run_bundle()` 是统一后处理入口。
4. MinerU 私有目录、文件名和字段只允许由 `MineruOcrBundleAdapter` 解释。
5. 现有 `collect_outputs` 外观作为兼容输出保留，不改变 Java、前端和题库业务流程。
6. 现有 Question Engine Java/TypeScript SDK 继续作为平台远程 SDK；`app.ocr` 作为 Python worker 内嵌入口。
7. 在 Artifact Resolver、异步任务、安全和配额契约完成前，不新增独立公网 Post Process API/SDK。
8. 在当前兼容期，`artifactRoot` 是显式必需证据；它必须是已存在目录，所有已声明 Markdown、JSON、asset 和 native artifact 路径必须是目录内真实存在的相对文件。原文件 `sourceDocumentRef.path` 例外。
9. `run_bundle()` 不扫描 `artifactRoot` 中未声明的 provider-native 文件；视觉上下文只由 `layoutBlocks`、`pages` 和 `sourceDocumentRef` 构建，派生 crop 写入 worker 的 job-scoped `postprocess` scratch。原生文件名扫描只保留在真正的 legacy `collect_outputs_impl(bundle=None)` 兼容路径。

## 结果

- 更换 OCR provider 时只新增 provider 和 adapter，不复制题库后处理算法。
- provider 可按 L0/L1/L2 如实提供证据，低能力输入通过人工复核而不是伪造信息。
- 确定性工件级 parity 已证明兼容入口与 bundle 入口复用同一真实后处理实现；这不构成受控真实语料准确率或性能不回退结论。
- 当前兼容期仍保留只读 `artifactRoot` 和 worker job 上下文；root 只用于校验和读取已声明工件，不承载派生写入。这仍是后续服务化需要移除的约束。

## 验证

- 契约序列化和输入校验测试；
- 默认 MinerU adapter 回归测试；
- legacy `collect_outputs_impl(bundle=None)` 与 adapter `run_bundle(bundle)` 的真实工件级等价测试；
- 未声明 provider-native 文件、外部 symlink 和只读 artifactRoot 回归测试；
- 结构、工具和 golden replay 回归；
- 待完成：受控真实语料的题数、选项、小问、题图、公式和调用数 gate；
- 待完成：从已审核制品归档的受控性能 baseline。`baseline-ref` 保持 `pending-controlled-baseline`，不得现场伪造 compare。
