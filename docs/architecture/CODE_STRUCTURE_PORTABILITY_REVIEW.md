# 代码结构与可迁移性评审

日期：2026-07-09

## 结论

当前项目仍然基本保持最初的可迁移、模块化交付方向：`question-engine` 作为能力发动机，Java 主后端提供稳定 API、状态和文件编排，Python worker 承担 OCR / AI / LaTeX / 导出等可替换执行能力，`local-platform` 保持为本地演示工作台。

本轮已把“布局解析框”在代码层封装为 `PaperLayoutCapability`，它对外只暴露 `paperLayout`、页图渲染和题图几何辅助能力；前端和 Java bridge 不需要理解 MinerU 的内部目录、`_middle.json` 或 `content_list` 差异。

整体评级：

| 维度 | 当前状态 | 说明 |
| --- | --- | --- |
| 可迁移性 | 基本达标 | 有 TOGO/交付脚本、OpenAPI/SDK、portability check、Docker server compose；真实密钥和运行数据未纳入交付包 |
| 模块化 | 基本达标 | Java capability / engine / domain 分层清晰；Python worker 能力模块已拆分，但部分模块仍偏大 |
| OCR provider 可替换性 | 中等偏好 | `ocr_flow.py` 已有 provider 抽象；但布局框、视觉修复、题图归属仍默认消费 MinerU 产物结构，需要通过 worker 统一 outputs 继续隔离 |
| 前端可替换性 | 中等 | `local-platform` 是演示壳，API adapter 相对集中；但工作台组件仍较大，后续嵌入正式平台时建议拆出 layout overlay / question editor 子组件包 |
| 服务器可复现性 | 基本达标 | `docker-compose.server.yml`、`docs/server`、GPU 分配和 MinerU 缓存策略已文档化；公网 80 入站仍受上游网络限制 |

## 已形成的能力边界

### Java 主后端

- `engine`：题目导入、题库、组卷、知识点的能力目录。
- `capability`：`ocr-flow`、`question-processing`、`ai-flow`、`export-flow`、`file-flow`、`callback-flow`、`sdk-openapi`。
- `domain`：导入任务、题库题目、题图、文件元数据、AI job、导出 job 的本地业务持久化。
- `proxy`：仅兜底转发未接管的 worker API，已经避免把业务主入口长期绑定在 Python worker 上。

### Python worker

- `ocr_flow.py` / `ocr_execution.py`：OCR provider 抽象、Markdown 直读、MinerU 调用、`.doc` 预转换。
- `ocr_processing.py`：OCR 产物收集、拆题、题图、题目结构生成。
- `question_boundary.py`：本地边界、LLM 边界确认、分片并发和结构校验。
- `question_layout.py`：`PaperLayoutCapability`，生成只读布局解析框和页图渲染。
- `math_normalizer.py` / `visual_repair.py` / `question_markdown.py`：公式、视觉证据和 Markdown 规范化能力。
- `export_service.py`：DOCX/PDF 导出渲染 worker。

### 前端 local-platform

- `ImportWorkbenchTask`：导入任务详情、原文件预览、布局解析框、人工校验和批量操作。
- `QuestionCard` / Markdown renderer / question helpers：题目编辑、预览和图片引用。
- 仍定位为演示工作台，不作为公司正式平台 UI 的强制交付物。

## 本轮布局解析框封装结果

代码边界：

- 新增 `PaperLayoutCapability` 对象，能力 ID 为 `paper-layout-box`。
- 保留旧兼容入口：
  - `attach_paper_layout(task, job)`
  - `build_paper_layout(task, job)`
  - `render_source_page(task, job, page_index)`
  - `question_image_refs_by_layout(output_dir, limit)`
- 内部实现改为 private helper，避免 worker 路由和 OCR 处理逻辑直接依赖实现细节。

数据边界：

- 对外只返回 `paperLayout.capability`、`pages[]`、`regions[]`、`warnings[]`。
- `regions[]` 是父题级范围，绑定平台 `questionId`，编号使用平台导入顺序。
- 坐标源优先使用 MinerU `_middle.json` 的 `page_size` 和 block bbox；缺失时回退 `content_list`。
- 前端只消费归一化坐标，不关心 MinerU 坐标系。

## 仍需治理的结构风险

1. Python worker 的导入链路仍承担较多职责。
   - 风险：`ocr_processing.py` 与 `worker_routes.py` 仍是高变动点，未来多人并行开发容易互相影响。
   - 建议：继续按 capability 拆分为 `import_task_capability`、`question_structure_capability`、`figure_capability` 等小边界。

2. `local-platform` 工作台组件偏大。
   - 风险：布局框、OCR 状态、人工校验、AI 批处理和题图操作集中在同一组件，正式平台嵌入时复用粒度不够。
   - 建议：拆出 `SourcePreviewWithLayout`、`ImportTaskToolbar`、`ReviewQuestionList`，并把 API 类型放入共享 SDK 或 adapter。

3. OCR provider 替换还没有完全摆脱 MinerU 产物习惯。
   - 风险：布局框、视觉修复、题图归属依赖 `middle/content_list/bbox/page_idx` 这类字段。
   - 建议：在 `ocr-flow` 统一输出中固化 provider-neutral 的 `layoutBlocks[]`，MinerU adapter 负责把 `_middle.json` 转换进去；业务能力只读 `layoutBlocks[]`。

4. Java/Python 状态双写仍存在兼容负担。
   - 风险：历史 JSON store、Java H2/MySQL 表和 worker job JSON 同时存在，排障成本高。
   - 建议：继续把任务状态、题目快照和文件元数据主源收敛到 Java；worker 只保留执行 job 和产物文件。

5. 文档和流程图需要随能力边界持续版本化。
   - 风险：功能快速迭代后，流程图容易滞后于代码。
   - 建议：每次新增或改能力时同步检查 `docs/architecture/README.md` 中列出的 current-primary 图，以及 `docs/delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md`。

## 下一步建议

- 短期：把 `PaperLayoutCapability` 的接口形态纳入 worker runtime/capabilities 返回，方便平台探测是否支持布局框。
- 中期：在 OCR outputs 中增加 provider-neutral `layoutBlocks[]`，让布局解析框、视觉修复、题图归属都不直接读取 MinerU 文件。
- 中期：拆分 `ImportWorkbenchTask` 前端组件，形成可迁移的 `SourcePreviewWithLayout`。
- 长期：Java 主后端接管更多 job 编排与异步队列，Python worker 只作为无状态执行器。
