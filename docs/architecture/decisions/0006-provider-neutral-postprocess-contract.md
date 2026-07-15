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

## 结果

- 更换 OCR provider 时只新增 provider 和 adapter，不复制题库后处理算法。
- provider 可按 L0/L1/L2 如实提供证据，低能力输入通过人工复核而不是伪造信息。
- 现有功能、调用顺序、性能和准确率基线保持不变。
- 当前兼容期仍保留只读 `artifactRoot` 和 worker job 上下文；这是后续服务化需要移除的约束。

## 验证

- 契约序列化和输入校验测试；
- 默认 MinerU adapter 回归测试；
- `run(jobId)` 与 `run_bundle(bundle)` 等价测试；
- 黄金样本的题数、选项、小问、题图、公式、调用数和性能对比。
