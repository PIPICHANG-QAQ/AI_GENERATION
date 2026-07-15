# 架构决策 0001：一期 OCR-Flow 默认使用 MinerU Provider

## 状态

历史参考。默认使用 MinerU 的决定仍有效；provider 边界部分已由 ADR 0003 和 ADR 0006 取代。

## 背景

AI 题库应用需要先完成整卷 OCR，才能继续做题目拆分、题图匹配、解析补全和题库入库。一期目标是验证 OCR 质量，而不是直接设计最终题库数据模型。

## 决策

一期使用 MinerU 作为本地 OCR 和文档解析默认 provider。后端通过命令行集成：

```bash
mineru -p <input_path> -o <output_path> -b pipeline
```

从 2026-06-30 起，业务层不再直接依赖 MinerU，而是依赖 `ocr-flow` 统一能力边界：

- Python worker 中由 `backend/app/ocr_flow.py` 封装 `OcrProvider`。
- `OCR_FLOW_PROVIDER=mineru` 是当前默认配置。
- `OCR_FLOW_EXTENSIONS` 控制 provider 文件类型。
- Java 主后端通过 `/api/capabilities/ocr-flow` 暴露 provider 合约和运行时状态。

## 影响

- 后端不依赖 MinerU 内部 Python API，降低版本升级风险。
- 模型下载和首次初始化属于本地环境问题。
- Markdown、JSON 和图片资源输出可以先被人工复核，再进入后续题目结构化阶段。
- 当前实现的替换契约以 ADR 0006 的 `Provider -> Adapter -> CanonicalOcrBundle -> Post Process` 为准；本条仅保留历史背景。
