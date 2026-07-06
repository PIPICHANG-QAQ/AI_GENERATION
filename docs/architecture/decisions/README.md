# 架构决策记录

本目录保存影响 `question-engine` 长期交付边界的 ADR。新增重大架构选择时，必须新增一份 ADR，而不是只在代码或 PR 描述里说明。

当前 ADR：

- `0001-java-main-backend.md`：Java 作为主后端和平台能力 API 入口。
- `0002-python-worker-boundary.md`：Python 只保留 OCR/AI/export worker 能力。
- `0003-mineru-default-ocr-provider.md`：默认使用 MinerU provider，同时保留 OCR provider 替换边界。
- `0004-local-h2-dev-mode.md`：本地默认 H2 + 本地文件，生产切换 MySQL + 对象存储。

历史 ADR：

- `../decisions/0001-use-mineru-for-ocr.md`
