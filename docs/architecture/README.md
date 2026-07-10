# 架构图索引与版本治理

本文治理 `docs/architecture` 下的 Mermaid 源图和 SVG 渲染图。当前基准为 2026-07-10 的产品 v15、OpenAPI `1.1.0` 和服务器部署 v15。

补充结构评审文档：

- `CODE_STRUCTURE_PORTABILITY_REVIEW.md`：代码结构、能力封装、可迁移性和模块化风险评审，当前记录 `PaperLayoutCapability` 封装结论。

## 当前图谱

| 图 | 状态 | 维护用途 | 当前结论 |
| --- | --- | --- | --- |
| `ocr-flow.mmd` / `ocr-flow.svg` | current-primary | OCR-Flow 端到端主链路，包含结构契约、拆题、LLM 路由、首次返回前自动标准化、重扫、AI 辅助、布局解析框解耦和人工校验 | 保留为 OCR 算法和导入主流程的权威图 |
| `import-ocr-workbench-flow.mmd` / `import-ocr-workbench-flow.svg` | current-primary | 导入工作台产品流程，包含任务创建、轮询、结构契约、自动标准化、布局解析框只读定位、重扫、AI 解析全部、人工保存和入库 | 保留为前端/产品视角，不再扩展底层 OCR 算法细节 |
| `platform-openapi-sdk-overview.mmd` / `platform-openapi-sdk-overview.svg` | current-primary | 平台集成、OpenAPI、SDK、能力边界 | 保留为 SDK/TOGO 移交主图 |
| `server-ocr-flow.mmd` / `server-ocr-flow.svg` | current-support | 服务器部署、GPU0/GPU1、常驻 MinerU API、自动标准化并发、布局解析框开关、外部模型边界 | 保留为服务器运维图，不放入通用平台部署前置要求 |
| `engine-boundary.mmd` / `engine-boundary.svg` | current-support | question-engine、平台、local-platform、Python worker 的职责边界 | 保留为模块边界总览 |
| `local-platform-overview.mmd` / `local-platform-overview.svg` | current-support | local-platform 作为本地演示壳的模块关系 | 保留，但不得作为公司平台生产架构依据 |
| `java-transition-flow.mmd` / `java-transition-flow.svg` | historical-reference | 从旧原型/legacy worker 迁移到 Java 主后端的历史参考 | 不再作为当前运行主图扩展；后续可移动到 archive |

## 重复与合并结论

- `ocr-flow` 与 `import-ocr-workbench-flow` 有 OCR 导入链路重叠，但读者不同：前者是算法/后端主链路，后者是工作台产品流程。当前不合并。
- `engine-boundary` 与 `platform-openapi-sdk-overview` 都描述平台集成，但层级不同：前者讲职责边界，后者讲 OpenAPI/SDK 调用关系。当前不合并。
- `local-platform-overview` 与 `import-ocr-workbench-flow` 都涉及本地前端，但前者是本地小平台总览，后者是导入工作台细节。当前不合并。
- `java-transition-flow` 与 `engine-boundary` 存在历史迁移信息重叠。当前保留为历史参考；后续文档瘦身时优先将它移入 `docs/architecture/archive/` 或 ADR 附录。

## 版本规则

- `.mmd` 是唯一可编辑源文件，`.svg` 是渲染产物。
- 每个 `.mmd` 顶部必须包含：
  - `Version`
  - `Status`
  - `Scope`
- 状态取值：
  - `current-primary`：当前主图，产品/开发/交付优先引用。
  - `current-support`：当前辅助图，用于特定视角或部署环境。
  - `historical-reference`：历史参考图，不再承载新功能主流程。
  - `deprecated`：准备删除或迁移的图，必须先在本文说明替代图。
- 新增或修改接口、SDK、部署、OCR/AI 关键链路时，必须同时检查相关主图：
  - OCR/拆题/AI 链路：`ocr-flow.mmd`
  - 导入工作台 UI/API：`import-ocr-workbench-flow.mmd`
  - OpenAPI/SDK：`platform-openapi-sdk-overview.mmd`
  - 服务器算力/部署：`server-ocr-flow.mmd`

## 渲染命令

修改 `.mmd` 后运行：

```bash
npx -y @mermaid-js/mermaid-cli -i docs/architecture/ocr-flow.mmd -o docs/architecture/ocr-flow.svg
npx -y @mermaid-js/mermaid-cli -i docs/architecture/import-ocr-workbench-flow.mmd -o docs/architecture/import-ocr-workbench-flow.svg
npx -y @mermaid-js/mermaid-cli -i docs/architecture/platform-openapi-sdk-overview.mmd -o docs/architecture/platform-openapi-sdk-overview.svg
npx -y @mermaid-js/mermaid-cli -i docs/architecture/server-ocr-flow.mmd -o docs/architecture/server-ocr-flow.svg
npx -y @mermaid-js/mermaid-cli -i docs/architecture/engine-boundary.mmd -o docs/architecture/engine-boundary.svg
npx -y @mermaid-js/mermaid-cli -i docs/architecture/local-platform-overview.mmd -o docs/architecture/local-platform-overview.svg
npx -y @mermaid-js/mermaid-cli -i docs/architecture/java-transition-flow.mmd -o docs/architecture/java-transition-flow.svg
```

交付前至少运行：

```bash
python scripts/check_question_engine_contract.py
python scripts/package_question_engine_delivery.py --check-only --include-local-platform
```
