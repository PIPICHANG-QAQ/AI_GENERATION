# 变更记录

## 2026-07-15

- OCR provider 与题库后处理改为显式 `Provider -> Adapter -> CanonicalOcrBundle v1 -> Post Process` 边界；MinerU 私有字段收敛到 `MineruOcrBundleAdapter`，确定性工件测试验证两条入口的归一化 outputs 一致。受控真实语料与性能不回退 gate 仍待完成。
- `app.ocr` 公开 provider-neutral Python 嵌入式入口；新增 Post Process 使用说明书和 ADR，明确当前不发布第二套远程算法 SDK，平台继续使用 Question Engine Java/TypeScript SDK。
- 兼容期 `CanonicalOcrBundle` 明确要求真实 `artifactRoot`，统一拒绝绝对、越界或不存在的声明工件路径；`sourceDocumentRef.path` 保持外部原文件引用语义。
- 显式 bundle 后处理关闭未声明 provider-native 工件旁路：结构和视觉修复只消费 canonical 声明证据，legacy 文件名扫描仅保留在 `bundle=None` 兼容入口；派生 crop 改写 worker `postprocess/<jobId>` scratch，支持只读 `artifactRoot`。
- OpenAPI 升级到 `1.2.0`；OCR-Flow 新增顶层类型化能力 descriptor，`providerContract` / `postProcessContract` 保持可扩展 Map，TypeScript/Java SDK 新增 `getOcrFlowCapability()`。
- 当前已有结构、工具、golden replay 和确定性工件 parity 证据；`tests/ocrflow-performance/baseline-ref.json` 仍为 `pending-controlled-baseline`，受控性能与真实语料 gate 未完成。
- 更新后端、worker、开发、产品、接口、交付、验收和运维文档；OCR 主流程、工作台、Engine 边界、平台 SDK 和服务器流程图同步 provider-neutral 后处理与 Java durable 全局标准化流程。

## 2026-07-13

- 选择题解析新增受约束弱标签恢复：可从连续 A/B/C 后的 `说明文字 D + 图片块` 恢复 D，同时过滤孤立字母和普通正文变量。
- 新增二维选项单元格与全局一对一题图分配器，消费 MinerU pageIndex、bbox 和页尺寸，支持图片位于标签之前、四宫格乱序和跨页选项；Markdown offset 不再天然获得 0.98/0.99。
- 自动二维结果可纠正错误 offset；人工 `confirmed/overridden` placement 冻结。最优/次优 margin、alternatives、冲突数和保护数量进入审计摘要。
- `imagePlacementValidation` 新增选项完整、题干/选项冲突、几何缺失、资产守恒和一对一阻断机器码，并进入 Java 统一标准化 request；单题与全局流程均按同一守卫返回 `review_required`。
- canonicalization preview 基于保存的 OCR Markdown 与 middle/content 布局重算选项和题图，不重新运行 MinerU；新增 `structureDiffs`，沿用 token、事务快照和 rollback。
- 增加默认关闭的受限多模态兜底协议；只处理中等置信或 offset/二维冲突，非法映射、超时和模型不可用保持人工复核。
- 人工校验页显示题图阻断原因和旧→新归属，有阻断项时禁止入库或直接应用结构整理。

## 2026-07-12

- 题图归属升级为显式 `imagePlacements`：按 Markdown offset 确认题干/选项/小问 owner，以 bbox 几何处理双栏顺序，只在无显式证据时补充，冲突时保留主证据并标记复核。
- 修复 legacy 跨题补图和无效整卷 fallback 覆盖主结构；主候选与 fallback 都不合法时保留证据质量更高的候选并返回 `requiresReview`。
- Java 导入题、题库题、`question-package.v1`、OpenAPI 和 SDK 均保留题图归属；前端支持人工修改 owner，未归属/冲突阻止“已校验”，导出按题干、选项和小问位置渲染。
- OCR 视觉修复改为节点内有界并发：`visual-repair` 仍排在 AI 边界确认和结构构建之后，内部按题目并发执行 crop、横线检测和可选 Pix2Text，结果按原始题目顺序统一合并，避免视觉修复影响题目边界识别。
- 新增视觉修复只读预处理：进入 `llm-boundary-refine` 前异步加载 content_list/middle.json、题号 bbox 索引和有限页图像缓存，真正写回题目仍等待边界确认完成后执行。
- 新增配置 `OCR_VISUAL_REPAIR_MAX_CONCURRENCY`、`OCR_VISUAL_REPAIR_PRELOAD_ENABLED`、`OCR_VISUAL_REPAIR_PRELOAD_MAX_PAGES`；同步更新 README、运维指南、技术设计和 OCR-Flow 流程图。
- 回归测试补充：覆盖视觉修复并发合并顺序、预加载页图缓存、Pix2Text 兜底和横线检测；Python worker 全量测试 97 个用例通过。

## 2026-07-10

- 修复人工校验预览态选择题选项重复渲染：当题干源码已经包含 `tasks` 选项块时，`MarkdownRenderer` 不再额外渲染结构化 `options`，避免标准化保存后预览页出现两组 A-D 题图选项。
- 人工校验单题/小问 `AI 标准化` 改为安全候选自动应用并保存：通过 `applyBlocked`、严重公式风险和渲染校验的结果会直接写回导入题草稿；被安全闸门阻断的候选仍保留候选面板，不自动覆盖。
- 导入校验工作台同步原型“全局标准化”：工具栏新增“全局标准化”按钮，确认后逐题处理题干、答案、解析和复合题小问字段；父题题干复用导入题上下文 AI 标准化接口，小问及答案/解析复用通用 Markdown 标准化接口，成功项自动保存，失败项不中断整批并汇总提示。
- 全局标准化与重新 OCR 扫描、AI 解析全部、批量入库互斥；运行时显示顶部进度条 `标准化中 n/m`、成功/失败计数和百分比。题目状态保持不变；已入库导入卡片可被标准化，但覆盖题库仍需点击“重新入库”。
- OCR 拆题升级为“结构契约优先”：先从卷面抽取总题数、大题声明和题号范围，再对所有数字题号做候选评分；卷头说明区的编号、非大题段内编号、超出当前大题范围的编号不会直接建题，避免把“本试卷共 N 题”等说明误识别为题目。
- 题号候选与真实题目分离：本地边界检测记录 `anchorCandidates` 和 `structureContract`，按段内位置、题号范围、正文区、题干语义和前后连续性打分；低分候选进入复核或回退，不污染最终题目列表。
- 首次 OCR 返回前支持自动 AI 标准化：新增 `OCR_AUTO_STANDARDIZE_MODE=off|risky|all` 和 `OCR_AUTO_STANDARDIZE_MAX_CONCURRENCY`。默认 `risky` 只处理严重 LaTeX、渲染失败、重复 Markdown、图片/选项异常等低置信题；该流程不创建 Java AI job，写入 `autoStandardize` 元数据。
- 自动标准化增加硬校验：候选必须通过渲染、严重风险、选项数量、题图标签、小问结构和未知图片引用校验，才会写回导入题；失败、阻断或 fallback 时保留原题，避免模型修复破坏已经正确识别的题目。
- 布局解析与题目识别彻底解耦：`PaperLayoutCapability` 只生成只读父题定位框，可由 `OCR_PAPER_LAYOUT_ENABLED` 关闭；布局框不参与题目拆分、题图归属写回或人工编辑稿生成，布局不稳定时不影响题目识别稳定性。
- 布局框绑定修复：读取 MinerU `_middle.json` 中嵌套 `blocks[].lines[].spans[].image_path`，跳过 `A/B/C/D` 这类极短选项标签作为 Markdown offset 锚点；当只命中小标签、极小框、缺少题图或 image-only 匹配缺题干时，降级到几何兜底或 warning。
- 布局框重新启用并发布到服务器：当前测试环境 `http://120.211.112.121:5173/` 已重新构建容器，健康检查通过；`OCR_PAPER_LAYOUT_ENABLED=true`、`OCR_AUTO_STANDARDIZE_MODE=risky`、`OCR_AUTO_STANDARDIZE_MAX_CONCURRENCY=2`。
- 回归测试补充：覆盖结构契约过滤卷头、跨页/粘连题号、自动标准化并发与关闭模式、图片选项去重、嵌套 middle 图片 bbox、短选项标签不串到下一题布局框。
- 文档和流程图同步升级到 v15：`ocr-flow`、导入 OCR 工作台和服务器 OCR 流程图补齐结构契约、自动标准化、布局解耦和低置信兜底链路。

## 2026-07-09

- 导入工作台“AI 解析全部”交互增强：确认后立即显示顶部进度条，展示当前处理题号/小问、成功失败计数和百分比；处理完成后短暂停留结果，再恢复按钮。普通题批量解析改为调用与单题按钮一致的导入题专用 AI 解析接口，避免用户点击后长时间无明显反馈。
- 布局解析框封装为 `PaperLayoutCapability`：保留 `attach_paper_layout`、`build_paper_layout`、`render_source_page`、`question_image_refs_by_layout` 兼容入口，内部收敛为能力对象和 private helper；`paperLayout` 增加 capability 元数据，对外仍只暴露 `pages[]`、`regions[]`、`warnings[]`。
- 布局解析框正式题目绑定版落地：优先读取 MinerU `_middle.json` 的 `page_size` 和 bbox，过滤标题、章节说明、页码等多余区域，只输出父题级 region，并绑定平台 `questionId`；点击框后右侧校验题卡滚动并高亮。
- 新增 `docs/architecture/CODE_STRUCTURE_PORTABILITY_REVIEW.md`，评审当前项目可迁移性、模块化、OCR provider 替换边界和后续治理项；同步更新产品规格、OCR 规格、技术设计、接口说明和验收标准。
- 外部大模型配置切换：本地 `.env` 与服务器 `/home/user/AI_GENERATION_DOCKER/.env` 已切到 TokenHub OpenAI 兼容接口 `https://tokenhub.shwfl.edu.cn/v1`，外部模型统一为 `qwen3.7-max`，provider 标记为 `tokenhub`；旧 API Key 已保存到各自 `.run/secret-backups/` 下的 `.env.before-tokenhub-*` 备份文件，文档不记录密钥。
- 导入工作台新增“布局解析框”开关：任务详情返回父题级 `paperLayout`，前端在试卷原文件页图上按原始 OCR bbox 叠加可点击题目范围框；支持多页 PDF，框编号使用平台顺序编号，点击后右侧校验题卡自动滚动并高亮。
- 新增试卷分页预览接口：`GET /api/import-tasks/{taskId}/source/paper/pages/{pageIndex}` 由 Java bridge 接管并从 Python worker 渲染页图，保证 overlay 坐标与 OCR 渲染尺寸一致；答案文件暂不显示布局框。
- 布局解析框精度优化：不再优先用 Markdown offset 猜测题目范围；现在优先使用 MinerU `_middle.json` 中与页图同源的 `page_size` 和 bbox，再按题号锚点顺序切分父题区域，过滤标题、章节说明和页码；缺少 `_middle.json` 时才回退 `content_list`。
- MinerU bbox 坐标优先用于题图归属：当 MinerU `content_list` 中图片在 JSON 顺序上早于所属题目文本、但坐标上落在后一道题区域时，按 `(page_idx, y0, x0)` 几何阅读顺序重新分配题图，避免第 7 题误挂第 8 题图片。
- 布局框 warning 机制：缺少可靠 OCR 坐标、原文件缺失、PDF 渲染不可用或文件类型不支持时，任务详情返回 `paperLayout.warnings`，前端在原文件区域提示人工复核。
- Python worker 正式依赖补齐 `pypdfium2`，确保新容器和 TOGO/服务器环境都能渲染 PDF 页图供布局框叠加使用。
- 题图引用一致性升级：前端为关联图片维护稳定 `图N` 标签，删除图片后不自动重排编号；从「题图（关联图片）」移除图片时，会同步清理题干、答案、解析、小问题干以及小问答案/解析中的对应 Markdown 图片引用。
- OCR 图片标签化升级：Python worker 在结构化题目时把 `![](images/xxx.jpg)`、API URL 和文件名引用规范为 `![](图N)`；有 OCR 位置时原位替换，没有可靠位置时追加到题干末尾并写入人工复核 warning。
- 选择题选项图片标签化补强：OCR 边界检测和 Markdown 规范化现在支持 `![]` 与 `(images/xxx.jpg)` 被换行拆开的图片语法；选项里的题图会保留在 `options` / `tasks` 中并规范为 `![](图N)`，不再被误判为题干缺失图片后追加到题干顶部。
- AI 标准化选择题保护：标准化 prompt 明确禁止删除、合并、重排 A/B/C/D 选项和图片选项；后端新增结构闸门，AI 候选丢失选择题选项时自动恢复原 OCR 结构化选项，图片选项保留 `![](图N)`。
- 回归测试补充：覆盖 OCR 图片路径标签化、尾部图片标签保留、AI 标准化丢失图片选项时恢复原选项结构。

## 2026-07-08

- 导入校验工作台同步 v13 原型能力：工具栏新增“AI 解析全部”和“重新 OCR 扫描”。批量 AI 解析默认只补齐未入库且缺少解析的题目，可勾选覆盖已有解析；普通题按整题生成，复合大题按小问逐个生成，失败项不阻断整批，结束后汇总成功/失败数，校验状态不自动改变。
- 新增 `POST /api/import-tasks/{taskId}/rescan` Java 编排接口：仅重新投递原始试卷/答案 OCR job，保留当前已提取和已编辑题目；处理中重复触发返回 `409`。前端扫描期间显示任务/OCR 为“处理中”、自动轮询，并禁用“重新 OCR 扫描”“AI 解析全部”“批量入库”。
- 修复 `/api/import-tasks/{taskId}/rescan` 生产路由代理：该路径现在明确由 Java domain controller 接管，避免被 Python worker API proxy 误转发为 FastAPI 404。
- OpenAPI 契约升级到 `1.1.0`：TypeScript / Java SDK 新增 `rescanImportTask(jobId)`，SDK 使用说明、接口说明书、契约校验和 TOGO 打包脚本同步更新；`question-package.v1` 保持兼容。
- TOGO 交付脚本新增 `--release-name`，交付包 manifest 写入 `contractVersion`；交付包纳入 `Dockerfile`、`docker-compose.server.yml`、`.dockerignore` 和 `deploy/nginx.conf`，方便开发团队按本地脚本或服务器 Docker 模式接手。
- `docs/architecture` 流程图完成版本治理：新增 `docs/architecture/README.md`，标记 current-primary/current-support/historical-reference 状态，明确重复边界、合并策略和 Mermaid 渲染规则；同步更新 engine boundary、local-platform、导入工作台、服务器算力和历史迁移图。
- 本地小平台 Markdown 预览增强 OCR HTML 表格渲染：`MarkdownRenderer` 现在会受控解析 `<table>/<tr>/<td>/<th>` 片段并保留 `rowspan/colspan`，题目源码仍保留原 OCR HTML，预览不再把表格标签当普通文本显示。
- Python worker 导入任务详情查询会同步 OCR job 最新状态，但仍只在任务没有题目时从 OCR 输出构建题目，保证重扫不会覆盖人工编辑内容。
- 服务器部署进入客户体验状态：当前运行目录固定为 `/home/user/AI_GENERATION_DOCKER`，公网入口为 `http://120.211.112.121:5173/`；旧目录 `/aa/AI_GENERATION_TOGO` 不再作为运行目录。
- MinerU OCR 加速落地：服务器改为常驻 `mineru-api`，应用调用 `MINERU_API_URL=http://127.0.0.1:8002`，并将 `/root/.cache/modelscope` 持久挂载到宿主机，避免容器重建后重复下载或校验模型。
- 服务器 GPU 资源确认：AI_GENERATION / MinerU 固定使用物理 GPU0，vLLM / `aux-qwen3-32b-fp8` 固定使用物理 GPU1；MinerU venv 已安装并验证 `onnxruntime-gpu==1.23.2`，可用 provider 包含 TensorRT / CUDA / CPU。
- AI 边界确认服务器默认走外部满血模型，并启用分片并发：`LLM_BOUNDARY_CHUNK_SIZE=5`、`LLM_BOUNDARY_MAX_CONCURRENCY=4`、`LLM_EXTERNAL_MAX_CONCURRENCY=4`，20 道题可拆成 4 片并发确认边界。
- 修复 OCR 正文最后一题尾部污染：当题干末尾紧跟“参考答案与试题解析”、答案解析标题或重复试卷标题时，结构构建阶段会截断非题干尾部，避免把试卷标题并入最后一题。
- 导入题显示编号改为平台顺序编号：不再用 OCR 扫描题号去重或对齐展示编号；重复 `q_1..q_n` 会保留全部父题，并在内部 `sourceQuestionId` 追加 `__occurrence_2` 等后缀。服务器同类样本已验证可从旧的 28 题恢复为 56 题，当前可见任务 `1` 也保持 56 题。
- 本地小平台人工校验 UI 与原型同步：Markdown + LaTeX 编辑区中只有题干源码/小问题干源码使用蓝色背景，预览、答案、解析、AI 候选源码和其它表单区域保持白底。
- AI 标准化和 AI 解析鲁棒性增强：标准化 LLM 超时/限流/非法 JSON 时返回 `rules-fallback` 本地候选和可重试元数据，不再直接 `409`；AI 解析失败时返回可重试兜底响应，前端只提示、不清空当前题目内容。
- AI 标准化和 AI 解析新增同步请求有界并发：`LLM_STANDARDIZE_MAX_CONCURRENCY`、`LLM_ANALYSIS_MAX_CONCURRENCY`、`LLM_STANDARDIZE_MAX_ATTEMPTS`、`LLM_ANALYSIS_MAX_ATTEMPTS` 已纳入 worker runtime options 和服务器 Compose 默认配置；后续大规模用户上线时预留 Java ai-flow 队列/MQ 异步化路径。
- 补齐服务器部署文档版本管理：新增并维护 `docs/server/README.md`、`docs/server/CHANGELOG.md`、`docs/server/RUNBOOK.md`，服务器相关部署状态、变更和操作命令不再散落在临时对话里。

## 2026-07-07

- 明确本地/服务器 LLM 路由边界：本地开发默认 `LLM_ROUTER_MODE=external`、`LOCAL_LLM_ENABLED=false`，所有 AI 节点稳定走外部 `deepseek-v4-pro`；服务器部署可使用 `LLM_ROUTER_MODE=hybrid`，但 AI 边界确认默认直接走外部满血模型，本地 `aux-qwen3-32b-fp8` 只默认承接小问结构确认、AI 标准化等快速结构类任务，复杂解析和高风险兜底继续走外部模型。
- 服务器 GPU 资源拆分：`docker-compose.server.yml` 默认只给 AI_GENERATION / MinerU 申请物理 GPU0（`NVIDIA_VISIBLE_DEVICES=0`，容器内 `OCR_CUDA_VISIBLE_DEVICES=0`），`vllm-aux` 使用物理 GPU1（`AUX_LLM_GPU_DEVICE=1`），避免 OCR 和 vLLM 抢同一张卡。
- OCR-Flow 接入混合 LLM 路由：`boundary_refine` 默认走外部 `deepseek-v4-pro`；小问结构确认和 AI 标准化先走服务器本地 `aux-qwen3-32b-fp8`，失败、schema 错误、结构校验失败或高风险样本再升级外部模型；本地模型并发和外部模型并发独立配置，外部默认严格限流。
- 本地 Qwen3 路由新增 JSON 稳定性兼容：默认通过 `LOCAL_LLM_DISABLE_THINKING=true` 关闭 thinking 模式，并在响应解析前剥离 `<think>` 段、扫描首个可解析 JSON 对象，减少 reasoning 文本导致的 schema 失败。
- 新增路由层 LLM 短期缓存和脱敏指标：`llmMetrics` 现在记录本地/外部调用次数、耗时和缓存命中数，单次调用只记录 route、provider、model、riskScore、耗时和短错误，不记录 prompt、密钥、OCR 全文或图片 base64。
- 新增离线回归脚本 `scripts/regression_ocr_flow_router.py`，覆盖选择题错拆、小问漏拆、填空题缺失、答案解析串题和题图 path 冲突等路由风险样本。
- 图库引用体验升级：题目编辑器与导入人工校验统一采用图片引用芯片化显示（`![](图N)` / `![](题图N)` / `![](#N)` / `![](N)`），拖拽与双击编辑均保持源码语义不变，复制/剪切会原样保留 Markdown 引用代码；删除为原子单位，避免半截字符串残留。题库中心与导入人工校验的小问题干/答案/解析字段同时接入该编辑器，支持题目字段间跨位置移动题图引用（按需移动，不改接口）。
- PDF 导出改为预览样式 XeLaTeX 主路径：Python worker 在 `format=pdf` 时优先生成专用 XeLaTeX 试卷模板，保留 `$...$` / `$$...$$` 数学公式，由 XeLaTeX 渲染分式、方程组、上下标、角度和科学计数法；若环境缺少 `xelatex` 或 LaTeX 包，再回退 ReportLab 文本版。
- PDF 预览样式继续保留卷头、题型徽标、所选小问徽标、小问卡片、题图和两列选项；解答题会自动预留浅色横线作答区，带小问的解答题会在每个小问卡片内预留作答空间。
- 导出测试补齐 XeLaTeX 路径：覆盖 LaTeX 数学命令不被转义、XeLaTeX PDF 可编译、解答题留白只作用于解答题或继承父题型的小问；本地真实导出已渲染检查 2 页 PDF，公式不再降级为 `a ^ 2` / `\frac` 文本。
- 同步导出相关文档：产品规格、技术设计、接口说明、运维、验收、交付包边界、PRD、开发手册和文档索引均更新为 DOCX Pandoc / PDF XeLaTeX 分支链路。

## 2026-07-06

- AI 标准化可靠候选链路落地：worker 现在按“本地确定性 LaTeX 修复 -> 原始 OCR 兜底 -> LLM 修复”顺序执行；当前编辑稿严重损坏但同题 OCR 题段干净时，会直接返回 `source=ocr-fallback` 候选，不再等待大模型。
- AI 标准化候选新增渲染安全闸门：worker 会规范化 `$$...$$` 展示公式块边界，返回 `renderValidation` 和 `applyBlocked`；前端候选面板区分“本地修复 / 原始 OCR 兜底 / AI 修复”，不可应用候选禁用“应用”并展示原因；耗时超过短阈值时显示 AI job 正在执行；Java 显式写回同样拒绝 `applyBlocked=true` 或 `renderValidation.valid=false` 的候选。
- AI 标准化效率优化：新增 `AI_STANDARDIZE_CACHE_TTL_SECONDS`，按当前编辑稿、可信 OCR 上下文和结构提示缓存成功的 LLM 标准化候选，重复点击同一题不再重复消耗模型。
- Java AI-flow 标准化上下文分离：`rawOcrContext` 不再拼接题目当前 `manualMarkdown`，当前编辑稿只通过 request `markdown` 传递，避免坏稿污染可信 OCR 兜底证据。
- 核验并补齐文档与流程图：`ocr-flow`、导入 OCR 工作台流程图和 local-platform example 图示同步高置信本地边界跳过、低置信分片 AI 边界确认、AI 标准化本地修复/OCR 兜底/缓存或 LLM/渲染闸门链路；技术设计、规格、接口说明和文档索引同步可靠候选与题图引用规则。
- 复验 AI 标准化链路：Python worker 49 条测试、Java 33 条测试、前端 `tsc + vite build`、基础部署 smoke、contract/portability/package 检查均通过；通过 Java 创建 Markdown 导入任务后，用损坏第 20 题样本触发 AI 标准化，14ms 返回 `source=ocr-fallback`、`rawOcrFallbackUsed=true`、`candidateSevereIssues=[]`、`renderValidation.valid=true`。
- 优化 OCR-Flow LLM 调用策略：高置信本地边界跳过 AI 边界确认，低置信边界支持按题段分片并发确认。
- 新增 LLM 调用耗时指标，用于后续性能基准和容量规划。
- 新增 OCR 自动语义修复模式配置，默认不阻塞 OCR 主链路。
- 复验 OCR-Flow LLM 效率优化：高置信 Markdown smoke 样本成功跳过边界模型，`outputs.boundaryConfidence.highConfidence=true`，`outputs.llmMetrics.callCount=0`，`outputs.autoSemanticRepair.mode=skipped`；相关 Python worker 测试、完整 worker 测试和 portability 检查均通过。
- 修复并验证迁移检查脚本的扫描边界：`scripts/check_project_portability.py` 的源码树扫描会剪枝 `.venv`、`node_modules` 等本机依赖目录，避免迁移自检卡住。
- 本地小平台补齐小问级 AI 操作：题库中心编辑题目和题目导入人工校验中，每个可编辑小问都显示独立 `AI 标准化` 与 `AI 解析` 按钮；标准化候选只应用到当前小问，解析会组合大题材料、当前小问题干、答案、知识点和题图，只回填当前小问答案/解析，不污染父题或其它小问。
- 修复新建 OCR 任务后任务记录加载/跳转卡住：`GET /api/import-tasks` 改为直接返回 Java 持久化快照，不再同步等待 Python worker；任务创建和详情继续同步 worker 状态。开发启动的 `uvicorn --reload` 只监听 worker 应用源码，避免 `.venv/site-packages` 文件事件导致 worker 反复重启。
- 通用 AI 解析入口补齐题图上下文转换：无题目 ID 的 ad-hoc 解析也会复用 Java `file-flow` 图片读取和 data URL 转换逻辑，保证小问级 AI 解析在带题图场景下能把有效题图传给多模态模型。
- 本地小平台题目编辑器新增“小问增删”：题库中心编辑题目和题目导入人工校验都可从普通题添加第一个小问、继续追加小问、确认后删除小问；添加第一个小问时自动迁移父题答案/解析，删除最后一个小问后恢复普通题答案/解析输入框；系统生成的 `(1)(2)(3)` 标签会连续重排，用户手动改过的标签保留；已入库只读题不展示增删控件。
- OCR-Flow 拆题流水线改为证据驱动、多阶段、可回滚：新增 `local-boundary-detect`、`llm-boundary-refine`、`question-structure-build`、`sub-question-split`、`structure-validate` 节点；模型只确认边界，题干/小问题干由 OCR 原文切片生成，结构校验失败会回滚旧规则拆题。
- 大模型默认切换为 DeepSeek OpenAI 兼容配置：默认 base URL 为 `https://api.deepseek.com`，默认模型为 `deepseek-v4-pro`，新增 `DEEPSEEK_API_KEY` 优先读取，同时保留 `DASHSCOPE_*` 变量兼容旧部署和平台模型网关。
- 新增边界拆题回归测试，覆盖大题小问拆解、选择题选项不混入题干、未知题图 path 被结构校验拒绝。
- 同步更新 `docs/architecture/ocr-flow.mmd` 源图，并重渲染 `docs/architecture/ocr-flow.svg`。
- 修复 OCR 小问链路逻辑漏洞：小问内题图按证据位置归属到子题；重叠的 LLM 题目/小问边界会被裁剪；长 OCR 文本超过 LLM 窗口时保留截断点后的本地边界；选择题中的 `①②③` 判断项不再被本地规则误拆成小问；小问 AI evidence 字段在 worker、Java 和前端保存链路中保留。
- 修复题图预览和选择题识别：题干源码删除 `![](图N)` 后题目预览不再渲染对应未引用题图；保存和 AI 应用不再无条件补回已删除题图引用；选择题选项提取支持 `()A. ... B. ... C. ... D. ...` 这类 OCR 连写格式。
- 继续增强选择题边界识别：OCR 拆题和前端预览同步支持全角选项字母、冒号选项标记和行首裸 `A/B/C/D` 标记；题干正文中自然出现的 `A/B/C/D` 不会被误切为选项；自动追加在选项后的 `![](图N)` 会回收到题干，避免污染最后一个选项。
- 抽象为空位题结构保护能力：题干包含“填空”“横线”“空缺”“补全”“填写”等提示时会修正为填空题；显式空位符号会归一为 `____`/`(____)`；公式等号和行尾等待填写位置会保守补空位；短字母/数字/标点 OCR 噪声行会转为空位占位；AI 标准化提示词要求保留空位、禁止直接补答案。
- 同步空位题结构保护文档：OCR 规格、技术设计、OCR-Flow Mermaid 源图、接口说明、开发贡献规则和文档索引均补齐选择题/空位题泛化规则与回归要求。
- 新增 OCR 视觉证据修复节点 `visual-repair`：对低置信空位题根据 MinerU bbox 裁出题目 crop，本地检测长横线并补 `____` 占位；支持通过 `PIX2TEXT_COMMAND` 对单题 crop 调用 Pix2Text 二次 OCR，候选通过安全校验后再写回题干，未配置时自动跳过。
- OCR-Flow 小问链路升级：大模型结构化拆题提示词明确输出 `subQuestions`，AI 元数据补全、AI 标准化和 AI 解析都按小问 `id`/`label`/顺序归属答案解析；导入题和题库题 AI 写回会合并到 `childrenJson/subQuestions`，父题答案解析保持为空。
- 本地小平台复合编辑器接通小问 AI 结果：含小问题目的 AI 标准化候选和 AI 解析会更新小问编辑区，前端调用 AI 解析时会把当前小问草稿一起传给 worker。
- AI 解析题图输入增加格式校验：Java 只把可识别为 PNG、JPEG、GIF 或 WebP 的有效题图转为多模态输入，损坏或占位图片会带跳过原因并不再导致解析 409。
- 本地小平台支持大题小问：Java 题库题和导入题同步会同时返回 `children`/`subQuestions`，含小问的大题父题答案解析保持为空，小问独立保存题干、答案、解析、题型、难度、分值、知识点和题图。
- 组卷中心新增按小问选择：试卷新增 `subSelections` 持久化字段；新建选题、试卷编辑和预览都支持只纳入部分小问，缺失/空选择/失效 ID 兼容为全选，取消到最后一个小问会被阻止。
- 同步 `/docs` 文档和 Mermaid 图示：OCR-Flow、导入校验工作台、本地小平台 overview、engine boundary、local-platform 业务流和时序图均补齐 `subQuestions`、复合编辑器和试卷层 `subSelections`。
- 新增服务器 Docker Compose 部署入口：`Dockerfile`、`docker-compose.server.yml`、`deploy/nginx.conf` 和 `scripts/docker-entrypoint.sh`，支持在单个应用容器内运行 nginx、Java backend、Python worker 和 MinerU。
- 前端生产构建默认改为同源 API，服务器访问时通过 nginx 代理 `/api/*` 到 Java backend；本地 Vite 开发模式仍默认请求 `http://localhost:8018`。
- Docker 部署数据默认挂载到 `server-data/`，大模型 API Key 继续通过 `.env` 或环境变量注入，不写入镜像；GPU 服务器可通过 `SERVER_BASE_IMAGE` 使用本机已有 TensorRT 镜像，并通过 `HOST_MINERU_VENV` 挂载服务器 MinerU venv。

## 2026-07-03

- 调整启动文档默认路径：TOGO/交付体验优先使用 `./scripts/deploy_local.sh --with-mineru`，不带参数的 `deploy_local.sh` 明确降级为只验证服务连通的基础部署；`--with-ai` 仍需显式启用，因为它依赖本地模型密钥并会调用真实模型服务。
- TOGO 交付支持携带 MinerU 离线部署大包：新增 `scripts/build_mineru_wheelhouse.sh` 生成 `vendor/mineru-wheelhouse/`，`package_question_engine_delivery.py --include-mineru-wheelhouse` 可将其打入交付包；`install_mineru.sh` 会优先从该 wheelhouse 离线安装，目标机器仍本机重建 `.venv`。
- 修复 TOGO 目录默认部署后上传 PDF 会生成 `OCR failed` 空任务的问题：Java 导入任务创建前会检查 Python worker 的 OCR provider runtime，Python worker 单独 OCR job 创建接口也会在非 Markdown 文件上传前检查 provider；MinerU 未安装或 `MINERU_COMMAND` 不可用时直接返回 503，并提示使用 `./scripts/deploy_local.sh --with-mineru`。
- 同步部署和交付文档，明确 `./scripts/deploy_local.sh` 只代表基础部署成功，PDF、图片和 Office OCR 导入必须使用 `--with-mineru` 或配置可用 OCR provider。

## 2026-07-02

- 增加运行稳定性冗余：Python worker 的 `library_store.json` 和 OCR job JSON 改为原子写入并生成 `.bak` 备份，主文件损坏时会自动回退备份并隔离损坏文件；Java OCR 快照恢复增加任务级并发锁，避免多个详情轮询请求重复恢复同一任务。
- 新增 `scripts/health_watchdog.sh`，可读取 `.run/deploy.env`、PID 和健康接口做一次性或持续 watchdog 检查，失败时输出三端日志尾部，必要时可用 `--restart` 自动转调 `deploy_local.sh` 重新拉起。
- 修复导入任务详情页长期显示 `Not Found` 或卡在 `处理中` 的问题：Java 导入任务详情和列表现在以 Java 持久化快照为返回基准，worker 兼容 store 丢失任务时会先回退 Java 快照；若 OCR job 已成功但任务题目未同步，会通过 worker 内部恢复接口按 OCR job 结果重建题目并写回 Java 表，避免页面永久停留在 running。
- 新增 `scripts/deploy_local.sh` 作为迁移后一键部署入口：自动检查并安装基础依赖、可选安装 MinerU、自动避让被其它项目占用的默认端口、按 Python worker -> Java backend -> 前端顺序启动、等待健康检查，并把实际 URL、PID 和日志写入 `.run/deploy.env`、`.run/pids/`、`.run/logs/`。
- 部署默认关闭 `uvicorn --reload`，仅 `--dev-reload` 或开发兼容入口 `scripts/start_project_with_java_backend.sh` 启用 reload；旧启动入口已改为转调 `deploy_local.sh --dev-reload`。
- 新增分层冒烟脚本：`scripts/smoke_deploy_basic.py` 用于基础部署验证，`scripts/smoke_ocr.py` 用于 MinerU/OCR 验证，`scripts/smoke_ai.py` 用于大模型标准化和解析验证；`deploy_local.sh --with-mineru` 和 `--with-ai` 会分别触发对应检查。
- 交付和运维文档同步升级：README、`DELIVERY_PACKAGE.md`、`OPERATIONS_GUIDE.md`、`ACCEPTANCE.md`、`DEVELOPMENT_GUIDE.md`、`CONTRIBUTING.md` 均改为区分“基础部署成功 / OCR 可用 / AI 全链路可用”三个验收等级。

## 2026-07-01

- 生成可直接迁移交付的项目目录流程：通过 `package_question_engine_delivery.py --include-local-platform` 输出到 `AI_GENERATION_TOGO`，明确排除 `.venv`、`backend/storage`、`backend/target`、`node_modules`、`local-platform/dist` 和真实 `.env`，目标机器必须本地重建依赖后启动。
- 新增 `scripts/test_python_worker.sh` 作为 Python worker 单元测试统一入口，固定 worker import path，纳入交付包必选文件和迁移验证流程。
- 修正交付包自检边界：`backend/python-worker/tests/` 随 `test_python_worker.sh` 一起交付，`check_question_engine_contract.py` 在正式包排除 `protocal/` 时不再误报历史原型 README 缺失。
- 完善迁移部署文档：`DELIVERY_PACKAGE.md`、`OPERATIONS_GUIDE.md`、`DEVELOPMENT_GUIDE.md`、`CONTRIBUTING.md` 和 README 均补充迁移检查、依赖安装、MinerU 检查、前端依赖安装、启动和健康检查顺序。
- 补齐 question-engine 作为平台 OCR 试卷处理插件交付所需材料：新增交付包边界、生产安全契约、部署手册、错误码与状态机、插件级验收套件、运行手册、贡献指南、性能基准、架构决策记录、平台最小接入样例、脱敏样例输入输出，并增强 OpenAPI 安全声明和 SDK 校验脚本。
- 新增 `docs/development/DEVELOPMENT_GUIDE.md` 作为开发手册和文档导航，说明 `question-engine`/SDK 能力边界、推荐阅读顺序、每类文档作用、按任务查文档方式和本地项目逐步搭建流程；同步更新根 README 与 docs 索引。
- 将 `docs/example/` 下的 Mermaid 图渲染为 SVG，并更新 `LOCAL_PLATFORM_AS_EXAMPLE.md`、example README、文档索引和同步检查脚本，使文档优先引用 SVG，`.mmd` 保留为源文件。
- 扩写 `question-engine/sdk/USAGE.md` 为工程师接入手册，补充 SDK 工程形态、接入前提、TypeScript/Java 引入方式、Java multipart 创建任务示例、任务状态机、`question-package.v1` 字段映射、回调异步、错误处理、平台封装建议、排错清单和验收清单。
- 扩写 `docs/product/LOCAL_PLATFORM_AS_EXAMPLE.md`，按题目导入、题库中心、组卷中心、知识点库四个模块说明本地代码、API adapter、SDK/question-engine 能力、平台自研边界和部署配置；新增 `docs/example/`，提供 local-platform 调用 SDK/question-engine 的时序图和业务流程图。
- 补充平台接入文档：新增 `question-engine/sdk/USAGE.md` 说明 TypeScript/Java SDK、任务创建/轮询、`question-package.v1` 消费和接入边界；新增 `docs/product/LOCAL_PLATFORM_AS_EXAMPLE.md` 说明 `local-platform` 如何作为本地工作台 example，而不是正式平台 SDK。
- AI 解析支持题图多模态输入：Java `ai-flow` 在导入题/题库题解析前读取题目已保存 `images`，优先从 Java `file-flow` 生成 `imageDataUrl`，旧 OCR 图片回退 worker 文件接口，再把题图随 `/worker/ai/analysis` 请求发给 Python worker；AI job 查询结果会脱敏内联图片内容。
- Python worker 的 AI 解析请求组装升级为 OpenAI/DashScope 兼容的多模态 `image_url` 消息，同时保留图片元数据，要求模型结合题图推理但不得编造看不清的图片内容。
- OpenAPI 和 generated TypeScript/Java SDK 补齐导入题/题库题 AI 解析写回接口：`analyzeImportQuestion`、`analyzeBankQuestion`；`QuestionImage` 增加 AI 解析相关的图片输入状态字段。
- 补充 Java 回归测试，覆盖题库题上传题图后执行 AI 解析时 worker 请求包含 `data:image/png;base64,...`，并验证 AI job request 中图片内容已脱敏。
- 修复 Java 迭代后 AI 标准化回归：导入题/题库题标准化默认恢复为“候选源码 + 候选预览 + 人工应用保存”，不再自动覆盖 `manualMarkdown`；显式写回必须通过低置信、`candidateSevereIssues` 和 `writeBlocked` 闸门。Java 会按 `paperOcrJobId` 读取同题原始 OCR 片段传给 worker，严重 LaTeX 损坏时支持 `rawOcrFallbackUsed` 候选兜底；worker 提示词也收敛为旧版保守策略，不再主动新增 `tasks`。
- 升级 AI 标准化公式修复能力：worker 新增确定性 LaTeX 分隔符修复层，能修复展示公式内部嵌套单 `$`、行内公式被 `\div`/`\leq` 等运算符切断的问题；如果本地公式标准化会重新引入严重风险，会跳过该轮标准化并保留可渲染候选。

## 2026-06-30

- 选择题选项编辑按原型收敛为同一源码面板：人工校验和题库编辑不会拆出独立选项输入控件；当题目已有结构化 `options` 但题干源码没有选项块时，前端会自动把选项补成标准 `\begin{tasks}(4) ... \task ... \end{tasks}`，用户直接在“题干源码” textarea 中编辑选项，保存时再解析回 `stemMarkdown + options`。
- 选择题 `\task` 标准化继续增强：AI 标准化提示词要求选择题选项输出为标准 `\begin{tasks}(4) ... \task ... \end{tasks}`，禁止 `ttasks`；Python OCR-flow 和前端渲染现在同时容错 `ttasks`、带 `(4)` 参数的 `tasks` 和裸 `\task` 行，能够把选项符号不明显的选择题拆成独立 A/B/C/D 选项。
- AI 标准化答案解析归位继续加强：答案/解析提取仍由大模型语义分析完成，Python worker 新增确定性后处理，在模型返回 `answer` 或 `analysis` 后删除题干中的 `【答案】`、`【解析】`、`【解答】`、`故答案为` 等残留块，并把题干末尾直接拼入的已抽取答案替换为空括号，保证题干只保留题目本身。
- 修复 OCR 选择题选项未独立渲染的问题：Python OCR-flow 现在能把 `- A.`、`A．`、`A、`、`(A)` 和 `tasks` 环境拆成 `options`，前端人工校验、题库列表、查看弹窗、组卷选题和试卷预览统一把题干与选项分离渲染；保存时会根据当前源码实时回传 `stemMarkdown + options`，避免旧空选项覆盖新拆分结果。
- 导入工作台头部操作按原型调整：任务详情页右上角原“刷新”按钮改为“显示原文件 / 隐藏原文件”切换；隐藏原文件后人工校验区域自动扩展为全宽，移动端同步切到校验题目视图。
- 同步 GitHub 私有仓库 `PIPICHANG-QAQ/ai-question-bank` 最新原型到本地 `protocal/`，并迁移当前可落地页面细节：题目导入页拆分为“新建 OCR 任务/任务记录”首页与单任务校验工作台，组卷中心试卷列表筛选区升级为搜索、学科、年级一行式筛选，题图选择改为任务题图库弹窗，Input/Select/Textarea 视觉同步为新版输入控件。
- 保留当前 Java 后端业务逻辑：没有采用原型中会回退为 data URL/mock 题图库的图片同步方案，题图上传和选择仍走 Java `file-flow` 的 `/images` 与 `/images/select`；导入文件类型仍保留 `.md/.markdown/.doc` 等当前后端支持格式。
- question-engine 契约和 SDK 同步升级：`question-engine/openapi/question-engine.v1.yaml` 正式纳入任务题图库、从题图库选择题图、导入题/题库题 AI 标准化写回答案解析等接口；TypeScript/Java 轻量 SDK 补齐对应模型和调用方法，`QUESTION_ENGINE_INTERFACE_GUIDE.md` 补充 file-flow 选图示例和 SDK 方法表。
- 固化新增能力交付闭环：`docs/development/CONTRIBUTING.md` 收敛“新增能力自动同步闭环”，要求以后每次新增能力都同步后端能力边界、OpenAPI、SDK、接口说明、受影响规格文档、变更记录和测试验证；新增 `scripts/check_question_engine_contract.py` 检查 question-engine 契约、SDK 和文档是否同步。
- 导入人工校验题图升级：每个导入任务现在可通过 Java `file-flow` 返回任务级题图库，人工校验题目支持本地上传题图，也支持从当前任务题图库多选并关联到当前题目；新增 `/api/import-tasks/{taskId}/questions/{questionId}/images/select`，并在本地业务冒烟脚本中覆盖上传、题图库和选择链路。
- AI 标准化升级为题干清洗 + 答案解析归位：Python worker 标准化提示词要求识别混入题干的本题答案、解析、参考答案或解答过程，并返回 `answer`、`analysis`；Java AI-flow 在标准化成功后写回 `manualMarkdown`，并在返回答案/解析时自动写回导入题或题库题，前端同步回填输入框。
- 新增 `docs/delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md`，作为 question-engine 封装接口说明书，面向平台开发者说明作用边界、OCR-Flow 调用位置、核心接口出入参、AI/题图/导出/callback-flow 使用方式、SDK 入口和不推荐接入方式。
- 修复本地启动脚本复用旧进程导致小平台业务跑旧编译产物的问题：`scripts/start_project_with_java_backend.sh` 默认重启本项目端口，`AI_GENERATION_REUSE_EXISTING=true` 可显式复用；新增 `scripts/smoke_local_platform_business.py` 覆盖本地小平台基础业务冒烟测试。
- 新增平台静态契约和生成型 SDK 主入口：`question-engine/openapi/question-engine.v1.yaml` 覆盖能力目录、题目加工、运行时和 callback-flow 主路径；`question-engine/sdk/generated` 提供 TypeScript/Java SDK，旧手写 SDK 移入 `question-engine/sdk/examples`。
- `question-package.v1` 稳定字段强类型化：题目选项、子题、公式校验和 source evidence 从泛型 `Object/Map` 收敛为明确 record，`raw` 仅作为扩展字段保留。
- callback-flow 增强本地工程化能力：事件表新增幂等键、最大重试次数和下一次重试时间，支持 `dead_letter` 状态和 `/events/retry-due` 到期重试扫描入口。
- 统一本期文档口径：`PRD.md`、`OCR_PHASE_1_SPEC.md`、`QUESTION_BANK_PHASE_2_SPEC.md` 和 `docs/delivery/ACCEPTANCE.md` 不再按“一期/二期”拆分，改为当前 `question-engine` 能力服务、Java 主后端、Python worker 和 `local-platform` 本地小平台的统一规格与验收标准。
- 架构图拆分：移除混合本地页面、平台集成和 SDK/OpenAPI 的 `system-overview`，新增 `local-platform-overview` 与 `platform-openapi-sdk-overview` 两张图，分别表达本地小平台闭环和公司平台集成契约。
- 项目结构瘦身：`backend-java/` 已合并为唯一 `backend/`，旧 Python 后端核心能力移入 `backend/python-worker/`，前端演示壳从 `frontend/` 迁移为 `local-platform/`，历史 `protocal/` 原型仓库、`artifacts/`、`tmp/`、构建产物和旧依赖目录已清理。
- Python worker 结构重整：原 3121 行 `main.py` 已拆分为 `worker_base.py`、`question_markdown.py`、`ocr_processing.py`、`import_services.py`、`export_service.py`、`ocr_execution.py` 和 `worker_routes.py`；新的 `main.py` 只保留 FastAPI 应用入口和路由注册。
- 补充代码 metadata 和中文注释：新增 `backend/README.md`、`backend/python-worker/README.md`、`local-platform/README.md`、`docs/delivery/DELIVERY_PACKAGE.md`，并为 Java 20 个主要包补充 `package-info.java` 包级职责说明。
- 本地脚本路径更新：`install_backend.sh`、`install_mineru.sh`、`check_mineru.py`、`start_java_backend.sh` 和 `start_project_with_java_backend.sh` 已适配 `backend/python-worker` 与 `local-platform`。
- Java 题图 file-flow 继续升级：导入题和题库题的题图上传、访问和 image-library 已由 Java 接管，上传文件写入 `java_storage_files`，并同步回写导入题或题库题 `images`；历史 Python 图片 URL 保留兼容回退。
- Java AI-flow 编排落地：新增 `java_ai_jobs` 表、AI job 实体/Mapper/Service/Controller，导入题和题库题的 AI 标准化/AI 解析由 Java 创建任务并调用 Python worker；AI 解析返回 `answer` 或 `analysis` 时自动写回对应题目。
- Java export-flow 编排落地：新增 `java_export_jobs` 表和导出任务 Service，`GET /api/papers/{paperId}/export` 由 Java 创建导出 job、调用 Python `/worker/export/render`、保存导出文件到 Java 文件存储并返回下载响应。
- Python worker 新增 `/worker/export/render`，接收 Java 传入的试卷和题目快照后生成 DOCX/PDF 文件；Python 只负责 Pandoc/LaTeX 渲染，不再负责导出任务元数据。
- 导入任务重试入口迁到 Java：新增 `POST /api/import-tasks/{taskId}/retry`，Java 根据 OCR job 失败状态调用 Python `/worker/ocr/{jobId}/retry` 并回写任务状态。
- Python worker 新增 `/worker/ocr/{jobId}/retry`，用于 Java 编排 OCR 失败重试。
- callback-flow 第一版落地：新增 `java_callback_events` 表和 Java callback service，支持 HMAC-SHA256 签名、HTTP 回调发送、失败记录、事件列表和手动重试；MQ 仍以配置摘要和本地表 fallback 方式保留。
- Java 能力目录更新：`ai-flow`、`export-flow`、`file-flow`、`callback-flow` 和 `sdk-openapi` 的描述已从“契约/后续”更新为当前已实现的 Java 编排入口。
- 新增轻量 SDK 草案，覆盖 `/api/capabilities`、`/api/engine`、加工任务创建/查询和 `question-package.v1`；该草案现已迁移到 `question-engine/sdk/examples`，正式入口改为 `question-engine/sdk/generated`。
- 补充 Java 回归测试，覆盖 Java 题图上传访问、AI 解析写回答案、导出 job 存储、导入任务重试和 callback-flow 签名；当前 `cd backend && JAVA_HOME=$(/usr/libexec/java_home -v 17) mvn test` 通过。
- 新增 Java 能力总目录 `/api/capabilities`，在 `ocr-flow` 和 `question-processing` 之外，补充封装 `review-workbench`、`ai-flow`、`export-flow`、`file-flow`、`callback-flow` 和 `sdk-openapi`，明确每项能力的边界、Java API、Python worker、数据契约、平台依赖和扩展点。
- `/api/engine` 新增 `supplementalCapabilities` 字段，并新增 `/api/engine/supplemental-capabilities`，使 `question-engine` 交付包可以直接列出六个补充能力，继续与本地小平台页面隔离。
- 新增 `/api/capabilities/ai-flow/runtime`、`/api/capabilities/export-flow/runtime` 和 `/api/capabilities/file-flow/runtime`，分别暴露大模型运行时、Pandoc/XeLaTeX 导出环境、LOCAL/MINIO 文件存储运行时摘要。
- Python worker 新增 `/api/system/export-flow` 和 `/worker/export-flow`，返回 Markdown + Pandoc 导出策略、Pandoc、XeLaTeX、中文字体、导出格式和 fallback 状态。
- 新增 Java `engine` 包和 `/api/engine` 能力目录，把题目导入、题库、组卷中心、知识点库四个模块封装为可交付能力模块，明确 Java API、Python worker 补充、模块依赖、平台必须提供内容和扩展点。
- 新增 `/api/engine/platform-requirements` 和 `/api/engine/delivery-boundary`，用于说明 question-engine 运行需要的平台能力，以及交付时应包含/排除的代码范围。
- 新增 `docs/architecture/ENGINE_DELIVERY_BOUNDARY.md` 和 `question-engine/README.md`，把能力发动机与本地小平台页面、Replit 原型、截图和演示数据隔离。
- 封装 OCR-Flow provider 边界：新增 `backend/app/ocr_flow.py`，把默认 MinerU 调用收敛为 `MineruOcrProvider`，`main.py` 只负责上传、Markdown 直读、`.doc` 预转换、provider 调用和统一产物收集。
- OCR-Flow 新增配置弹性：支持 `OCR_FLOW_PROVIDER` 选择 provider，支持 `OCR_FLOW_EXTENSIONS` 配置 provider 文件类型，保留 `MINERU_COMMAND`、`MINERU_TIMEOUT_SECONDS` 等 MinerU 默认 provider 配置。
- 新增 Python 状态接口 `GET /api/system/ocr-flow` 和内部 worker 状态接口 `GET /worker/ocr-flow`，返回 provider、文件类型、超时、配置键和流程步骤。
- 新增 Java 能力 API `GET /api/capabilities/ocr-flow` 和 `GET /api/capabilities/ocr-flow/runtime`，让 Java 主后端显式暴露 OCR-Flow 能力边界、provider 合约和运行时状态。
- 新增 `docs/product/OCR_PHASE_1_SPEC.md`，记录替换 MinerU 的最小路径：新增 provider、注册 provider、配置 `OCR_FLOW_PROVIDER`、保持 `collect_outputs` 统一输出结构不变。
- 项目定位调整为“本地小平台 + 题目加工能力服务”：新增 `docs/architecture/ENGINE_DELIVERY_BOUNDARY.md`，明确本项目负责试卷 OCR、题目结构化、AI 标准化/解析、人工校验和标准题目包输出，平台负责用户、权限、最终题库、知识点主数据、审核流和长期文件归档。
- 新增 Java 能力 API：`/api/capabilities/question-processing`，提供能力描述、加工任务列表、创建加工任务、查看加工任务和标准题目包输出。
- 新增标准题目包 `question-package.v1`，从 Java 导入任务、导入题和题图快照生成 `ProcessingJob`、`ProcessedQuestion`、题图、候选知识点、公式校验提示和 source evidence，供公司教育生态平台或本地小平台稳定消费。
- Java 代理规则排除 `/api/capabilities/*`，能力 API 不再落入 Python fallback 代理。
- 新增能力层回归测试，覆盖能力描述、OCR-Flow 能力描述、任务视图和标准题目包输出；当前 Java 测试总数增加到 12 个并通过。
- Java 文件存储迁移启动：新增 `java_storage_files` 表、实体、Mapper、`JavaFileStorageService` 和 `java-storage.local-root` 配置，用于保存上传原文件的业务归属、字段名、原始文件名、大小、内容类型、存储类型、本地路径或 MinIO object key。
- 导入任务创建链路升级：Java bridge 现在会先保存试卷文件和可选答案文件到 Java 管理的文件存储层，再调用 Python worker 创建 OCR job；如果 Python 创建失败，会清理本次 Java 文件副本和元数据。
- Java 文件存储默认写入本地 `backend/storage/java_files`，启用 `enterprise.minio.enabled=true` 后可写入 MinIO；`/api/java/enterprise` 新增当前文件存储类型和本地根目录摘要。
- Java 接管导入任务原文件预览入口：`GET /api/import-tasks/{taskId}/source/{paper|answer}` 现在优先从 `java_storage_files` 读取 Java 本地文件或 MinIO object 并以 `inline` 返回；旧任务没有 Java 文件记录时继续回退 Python worker，前端 URL 不变。
- 修复 Java 代理拦截规则：导入任务 source 预览路径已列为 Java 已接管路由，避免在 Python 代理关闭时误返回 503。
- Java 导入任务状态机落地第一版：同步导入任务时由 Java 根据 `paper_ocr_status`、`answer_ocr_status`、`failure_reason`、`retryable`、`retryCount/maxRetryCount` 和题目状态派生 `处理中`、`待校验`、`部分完成`、`已完成`、`失败`、`可重试`。
- Java 导入任务 bridge 响应现在会回填 Java 派生后的 `status`、`paperOcrStatus`、`answerOcrStatus` 和 `failureReason`，前端能直接看到 `可重试` / `失败` 等状态。
- Java 导入题目数据迁移继续推进：新增 `java_import_questions`、`java_import_question_images` 表、实体、Mapper 和同步 Service，导入任务同步时会保存题干、答案、解析、知识点、题图、选项、子题、公式校验和原始 JSON 快照。
- 修复 Java 导入题同步潜在脏数据：当 Python worker 返回的题目列表变少时，Java 会清理不再存在的导入题和题图；题图同步主键改为稳定 UUID，避免长任务 ID/题目 ID 组合超过字段长度。
- Python worker 新增内部 worker 形态入口：`/worker/ocr`、`/worker/ai/standardize`、`/worker/ai/analysis`、`/worker/export`，旧 `/api/*` 保持兼容，供 Java 后续编排逐步切换。
- Java 工程化配置补齐：新增 Redis Starter、MinIO SDK 和 `enterprise.*` 配置，`GET /api/java/enterprise` 可查看 MySQL、Redis、MinIO、MQ 和 Prometheus 入口状态；默认不强制连接 Redis/MinIO/MQ，保持本地 H2 + Python worker 可直接启动。
- 补充 Java 回归测试，覆盖导入文件 Java 存储元数据、导入题目/题图同步、题目列表缩减后的清理、OCR 失败可重试/最终失败状态派生、bridge 响应状态回填；本轮验证 `cd backend-java && JAVA_HOME=$(/usr/libexec/java_home -v 17) mvn test` 通过，`python -m py_compile backend/app/main.py backend/app/ocr_flow.py` 通过，`cd frontend && npm run build` 通过。
- Java 导入任务元数据继续升级：`java_import_tasks` 新增 `paper_ocr_job_json` 和 `answer_ocr_job_json`，同步导入任务列表/详情时保存 OCR job 状态快照，为 Java 状态机、失败原因和重试编排提供数据基础。
- Java 导入任务新增 OCR 派生状态字段：`paper_ocr_status`、`answer_ocr_status` 和 `failure_reason`，从 Python 返回的 job 快照中提取状态和错误信息，方便后续 Java 状态机和重试判断。
- 新增启动期 schema 兼容迁移器，自动为已有本地 H2/MySQL 表补齐导入任务 OCR job 快照列、状态列和失败原因列，避免老库重启后缺列。
- Java 继续接管导入任务管理入口：`PUT /api/import-tasks/{taskId}`、`DELETE /api/import-tasks/{taskId}`、`POST /api/import-tasks/batch-delete` 现在由 Java bridge 处理，调用 Python worker 保持现有业务语义，并同步更新或清理 `java_import_tasks` 元数据。
- 新增导入任务管理 bridge 回归测试，覆盖重命名同步、单任务删除清理和批量删除清理；当前 Java 测试总数增加到 8 个并通过。
- Java 接管导入任务创建入口：`POST /api/import-tasks` 现在由 Java bridge 处理 multipart 表单，转发试卷/答案文件到 Python worker 创建 OCR job，并把返回的导入任务元数据同步到 `java_import_tasks`。
- 保持前端响应兼容：导入任务创建接口仍返回 Python worker 原始任务结构，现有“创建后进入 OCR 工作台”的业务流不变。
- 新增 Java bridge 回归测试，覆盖 multipart 表单转发、答案文件转发和创建后元数据落库；Java 测试总数增加到 6 个并通过。

## 2026-06-29

- Java 导入任务元数据迁移启动：新增 `java_import_tasks` 表、实体、Mapper 和同步 Service，启动迁移时从 `library_store.json` 导入 import task 元数据。
- Java 接管导入任务 GET bridge：`GET /api/import-tasks` 和 `GET /api/import-tasks/{taskId}` 仍返回 Python worker 原始响应，同时把任务元数据、OCR job id、题目数量和原始 JSON 同步到 Java 表，为 Java 状态机迁移提供数据基础。
- Java 导入入库链路升级：新增 `ImportTaskBankBridgeController/Service`，Java 现在接管 `POST /api/import-tasks/{taskId}/questions/{questionId}/bank` 和 `POST /api/import-tasks/{taskId}/bank`，先调用 Python worker 保持现有校验/查重/状态流转，再把返回的 `bankQuestion` 或 `items` upsert 到 Java 题库表。
- 新增 Java bridge 回归测试，使用本地模拟 Python worker 覆盖单题入库同步和批量入库同步，避免 Java 题库列表与 Python 导入任务入库结果断层。
- 优化 AI 解析回填：导入题和题库题点击 AI 解析后，前端会同时写入解析和模型返回的答案；后端 AI 解析响应增加 `answer` 字段并保留 `suggestedAnswer` 兼容旧调用。
- Java 主后端进入数据层迁移阶段：新增 MyBatis Plus、MySQL Connector 和 H2 本地开发库，默认使用 H2 文件库保证本地无需 MySQL 也能启动，`mysql` profile 可切换到 MySQL。
- 新增 Java 业务表结构 `java_knowledge_points`、`java_bank_questions`、`java_papers`，并在启动时从 `backend/storage/library_store.json` 幂等迁移知识点、题库题目和试卷数据。
- Java 后端接管知识点、题库题目、试卷基础 CRUD 路由：`/api/knowledge-points`、`/api/question-bank/questions`、`/api/papers`；导入任务、OCR、AI 标准化/解析、题图上传和试卷导出继续由 Java 代理到 Python worker。
- 修复数据表字段兼容问题：题目年份数据库列使用 `question_year`，避免 H2/MySQL 模式下 `year` 保留字导致建表或查询失败。
- 新增 Java domain MockMvc 回归测试，覆盖知识点、题库题目、试卷基础 CRUD，并在 JDK 17 下通过 `mvn test`。
- 本地重启 Java backend 验证通过：`/api/java/health` 返回 Java `17.0.11`，知识点/题库题目/试卷列表从 Java 表返回迁移数据，导入任务接口仍可通过 Java 代理访问 Python worker。
- 拉取 Replit 原型最新版本到 `protocal`：`b2ae6ed -> 70fb228`，同步页面头部对齐、新建导入表单间距、知识点选择搜索框、批量删除复选框对齐和组卷中心试卷名称搜索。
- 迁移原型最新前端细节到当前 `frontend/src`，保留本地 Java backend API 兼容层。
- 修复原型前端业务接口未真实对接的问题：导入题卡“AI 标准化”改为调用 `/api/import-tasks/{taskId}/questions/{questionId}/standardize/ai`，题库题编辑改为调用 `/api/question-bank/questions/{questionId}/standardize/ai`，新建题才使用通用 `/api/markdown/standardize/ai`。
- 修复 AI 解析上下文不足：导入题使用导入任务专用解析接口，题库题使用题库题专用解析接口，新建题使用 `/api/ai/analysis`，并传入题型、答案、知识点和题图。
- 修复题图功能：前端渲染 `/api/...` 题图时自动转为 Java backend 绝对地址；已有导入题和题库题上传题图时改为调用后端图片上传接口，不再只保存浏览器 data URL。
- 修复 OCR 原文件预览识别：前端会读取后端返回的 `filename` 字段判断 PDF、图片、Office 和 Markdown/Text 文件类型，避免把可预览文件误判为不支持预览。
- 同步导入文件选择器支持 `.md/.markdown/.doc`，与后端 OCR 导入文件类型保持一致。
- 后端 `GET /api/papers` 新增 `keyword` 参数，支持原型组卷中心按试卷标题、学科、年级和状态模糊搜索。
- 完成关键业务流回归：新建 Markdown 导入任务、答案 OCR 匹配、原文件预览、导入题 AI 标准化、导入题 AI 解析、导入题题图上传与保存、单题入库、题库题 AI 标准化、题库题 AI 解析、题库题题图上传、试卷创建和试卷关键词筛选。
- 新增最新原型界面截图：`docs/renders/replit-prototype-question-bank-desktop-20260629-latest.png`、`docs/renders/replit-prototype-import-desktop-20260629-latest.png`、`docs/renders/replit-prototype-papers-desktop-20260629-latest.png`、`docs/renders/replit-prototype-question-bank-mobile-20260629-latest.png`。
- 配置 GitHub CLI 登录账号 `PIPICHANG-QAQ`，通过 `repo` 权限访问私有仓库，并将 Replit 原型仓库 `PIPICHANG-QAQ/ai-question-bank` 克隆到 `protocal/`。
- 将 `protocal/artifacts/question-bank-admin/src` 迁移为当前 `frontend/src`，前端默认改用 Replit 原型后台界面，包含题目导入、题库中心、组卷中心和知识点库。
- 升级前端依赖和 Vite 配置：接入 Tailwind v4、shadcn/Radix 组件、TanStack Query、Framer Motion、Sonner、KaTeX Markdown 渲染和 `@` 路径别名。
- 适配原型前端与当前 Java backend：`frontend/src/lib/api.ts` 默认访问 `http://localhost:8018`，兼容 `VITE_API_BASE_URL` / `VITE_API_BASE`，导入任务批量删除映射到 `/api/import-tasks/batch-delete`，题库、知识点和试卷批量删除在当前阶段顺序调用单删接口。
- 新增 FastAPI 兼容接口 `POST /api/ai/analysis`，复用现有 DashScope 题目解析能力，为新建题目和无题目 ID 的原型编辑器返回解析草稿，不直接写入业务数据。
- 将 Replit 原型前端的桌面和移动端题库中心截图归档到 `docs/renders/replit-prototype-question-bank-desktop-20260629.png` 和 `docs/renders/replit-prototype-question-bank-mobile-20260629.png`。
- 生成 Java 主后端改造前完整版本快照：`docs/VERSION_SNAPSHOT_20260629_BEFORE_JAVA_BACKEND.md`，记录当前 FastAPI、前端、业务接口、存储、运行方式和回溯要点。
- 新增 `backend-java` Spring Boot 3.3.5 / Java 17 主后端第一阶段并行骨架，提供健康检查、运行时信息、TraceId、CORS 和 Python worker 连通性探测。
- 新增 `scripts/start_java_backend.sh`，默认以 `test` profile 在 `8018` 端口启动 Java 服务。
- 升级 Java 后端为前端默认 API 入口：`/api/java/*` 由 Java 处理，现有 `/api/*` 通过 Java 反向代理到 Python worker。
- 前端默认 `VITE_API_BASE` 从 `http://localhost:8000` 切换为 `http://localhost:8018`，临时直连 Python 时仍可通过环境变量覆盖。
- 新增 `scripts/start_project_with_java_backend.sh`，一键启动或复用 Python worker、Java backend 和前端。
- Java `pom.xml` 增加 SmartRAG 对齐版本属性和公开 BOM：Java 17、Spring Boot 3.3.5、Spring Cloud 2023.0.3、Spring Cloud Alibaba 2023.0.1.2、Spring AI 1.0.0、Spring AI Alibaba 1.0.0.2，并接入 Knife4j、Prometheus、OkHttp、FastJSON2、Hutool、Commons IO 等公开依赖。
- `scripts/start_java_backend.sh` 默认选择本机 JDK 17 运行 Java 后端，避免继承系统默认 Java 20/21 导致运行时与 SmartRAG 不一致。
- 新增 `/api/java/stack`，用于查看当前 Java 后端与 SmartRAG 对齐的技术栈版本清单。
- 修复导入任务原文件预览异常：前端不再把 404/错误 JSON 直接显示进 PDF 预览区，而是先校验源文件响应并以 Blob URL 预览，失败时显示明确错误。
- 修复导入任务轮询潜在状态污染：`fetchImportTask` 现在会检查 HTTP 状态，避免把 `{"detail":"Import task not found"}` 当作任务对象写入当前页面状态。
- 补齐题目删除和试卷删除的失败响应检查，避免后端删除失败时前端误刷新为成功状态。
- 新增 `docker-compose.local.yml`，提供 MySQL、Redis、MinIO 本地企业化依赖入口，便于后续对齐 SmartRAG 技术栈。
- 更新 `.env.example`，补充 Java 后端、Python worker 和本地依赖占位配置。
- 更新 `.gitignore`，忽略 `backend-java/target/` Maven 构建产物。
- 新增 `docs/architecture/java-transition-flow.mmd`，记录 Java 主后端与现有 Python worker 的阶段性过渡关系。
- 更新 README、PRD、技术设计和验收标准，明确当前阶段 Java 不替换现有 `/api/*` 业务接口，Python 仍承载 OCR、题库、组卷和导出能力。

## 2026-06-25

- 新增二期题库业务骨架：左侧导航包含题库中心、组卷中心、知识点库。
- 题库中心新增导入任务流程，创建任务时填写学段、学科、年级、地区、年份和标题。
- 导入任务支持同时上传试卷文件和答案文件，并分别创建 OCR job。
- OCR 初扫继续复用 MinerU、大模型拆题、公式渲染、题图匹配和 AI 语义修复。
- 新增 AI 题目元数据补全：题型、答案、解析、知识点、难度和分值。
- 新增导入任务状态：处理中、待校验、部分完成、已完成。
- 新增导入题目状态：待校验、已校验、已入库。
- 新增单题入库和批量入库 API。
- 新增题库中心题目搜索、筛选、增删改查 API。
- 新增知识点库增删改查 API。
- 新增组卷中心手动选题、试卷保存和 Word/PDF 导出 API。
- 前端将导入任务和 OCR 校验合并为“导入 OCR 工作台”：创建导入任务后直接进入工作台，左侧预览原文件，右侧人工校验并入库。
- 后端新增导入任务原文件预览接口，支持试卷和答案文件在工作台内查看。
- 修复导入题目、题库列表和组卷选题池中题图不随题干展示的问题；题目保存和入库时保留 `images` 数组。
- 新增 `docs/REPLIT_UI_PROTOTYPE_REQUIREMENTS.md`，用于交给 Replit 重做前端 UI 原型，细化页面结构、业务流程、按钮行为、接口映射和状态要求。
- 按外部 UI 设计说明重做前端视觉样式：引入 HSL 语义化 token、深蓝主调、暖橙点缀、玻璃拟态侧栏、现代卡片、状态徽章和响应式工作台布局；不改变现有页面功能和接口。
- 修复视觉重做后的导入 OCR 工作台回归问题：恢复原文件预览区的有效高度和缩放变量，校验编辑模式改为稳定纵向布局，避免 Markdown 编辑器、预览区和题目元数据表单相互重叠。
- 优化宽屏空间利用：题库业务页改为全宽工作台，导入 OCR 工作台在宽屏下加大源文件和校验区比例，人工校验编辑态横向展开源码、预览和元数据，减少内容挤压。
- 调整人工校验编辑区为上下布局：上方展示 Markdown + LaTeX 源码和渲染预览，下方集中展示题型、难度、分值、知识点、答案和解析等题目配置项。
- 完善题库中心筛选能力：前端筛选面板按截图收敛为题型、难度、知识点、学科、年级、地区、年份和清空筛选按钮；后端题库列表接口继续兼容已有查询参数。
- 优化全项目浏览器窗口自适应：导入 OCR 工作台、题目校验编辑器、Markdown/LaTeX 预览和筛选表单支持可收缩布局、内部滚动和长文本换行，避免窄窗口或低高度窗口出现遮挡。
- 新增左侧导航收缩能力：宽屏可手动收起为图标栏，中等窗口默认收窄；人工校验 Markdown 源码和渲染预览改为基于容器宽度动态排布，空间充足时左右布局，空间不足时上下布局，减少右侧内容裁切。
- 优化左侧导航收起态交互：收起后不再显示独立展开按钮，顶部 logo 直接作为展开入口；中等窗口下同步进入真实收起状态，避免出现视觉收起但 logo 不可展开的问题。
- 重做组卷中心：在 `/papers` 内实现试卷列表、新建试卷选题、试卷编辑器三视图；支持跨分页保留选题、清空已选、题目追加、拖拽排序、逐题赋分、试卷头预览、发布校验、编辑、删除和 Word/PDF 导出入口。
- 优化二次编辑试卷流程：追加题目复用新建试卷的完整搜索、筛选、分页和题目预览交互；点击发布时先展示发布前试卷预览，确认后才保存发布。
- 重做知识点库：支持按名称、学科、年级和说明实时筛选，使用弹窗新增/编辑知识点，并保留删除二次确认。
- 完善试卷后端序列化和分页：`GET /api/papers` 返回分页结构，试卷详情和列表自动解析题目、覆盖本卷分值并计算题目数量和满分。
- 新增 `docs/product/QUESTION_BANK_PHASE_2_SPEC.md`，记录组卷中心和知识点库的详细流程、数据关联、接口和缓存刷新机制。
- 新增 `docs/product/QUESTION_BANK_PHASE_2_SPEC.md` 记录二期题库业务规格。
- 迭代导入 OCR 工作台人工校验卡片：题干按截图样式展示 Markdown + LaTeX 源码和预览，答案与解析也支持源码和实时预览。
- 迭代人工校验题图结构：题图从题干 Markdown 中拆出为独立模块，OCR 图片自动进入本卷题图库，单题支持从题图库导入、多图本地上传、移除和预览。
- 新增导入任务题图库与题图上传接口：`GET /api/import-tasks/{taskId}/image-library`、`POST /api/import-tasks/{taskId}/questions/{questionId}/images`。
- 新增导入题目 AI 解析接口 `POST /api/import-tasks/{taskId}/questions/{questionId}/analysis`，将人工校验中的“AI 标准化”调整为“AI 解析”，用于根据题干、答案、题型和知识点生成解析草稿。
- 修复导入 OCR 工作台历史任务和创建任务后弹出系统“保存为”窗口的问题：导入任务原文件预览接口改为 `Content-Disposition: inline`；题库中心移除右上角“新建导入”，任务创建统一在左侧表单完成。
- 按截图回调导入 OCR 工作台布局：顶部使用下划线页签，左侧为新建导入和任务列表，右侧任务工作台内部分为原文件预览与人工校验入库两栏。
- 迭代题库中心题目列表：入库题目支持展开编辑，复用人工校验的 Markdown + LaTeX 源码/预览、元数据和答案解析编辑结构；预览态渲染展示答案和解析。
- 题库中心题目编辑器补齐“AI 解析”：复用大模型解析逻辑，在题干编辑工具栏生成解析草稿，用户复核后再保存。
- 优化试卷 Word/PDF 导出：导出时渲染常见 LaTeX 数学表达式为可读数学符号，并补齐标题、副标题、学校、考试时长、满分、题量、考生信息和考生须知等卷头内容。
- 完善导入任务交互校验：新建导入必填项显示 `*` 并一次性提示缺失项；任务列表支持重命名、单个删除和批量删除；后端新增导入任务标题查重和题目入库查重，重复任务名或重复题目会被拒绝或跳过。
- 优化试卷渲染样式：前端试卷编辑器中答案/解析统一走 Markdown + LaTeX 渲染；导出 DOCX/PDF 去除 Word 默认标题蓝色和 Markdown 加粗残留，统一正文正文字号、字重、行距和 PDF 中文字体。
- 升级试卷导出链路：后端先生成 Markdown + LaTeX 中间文件，再优先通过 Pandoc 转 DOCX/PDF；DOCX 公式转为 Word 原生公式对象，PDF 通过 XeLaTeX 渲染，Pandoc 不可用时回退旧导出。
- 优化带图试题导出：试卷 Word/PDF 导出会解析 OCR 图片和本地上传题图，在题干后、选项前插入图片，并按页面宽高自适应缩放。
- 优化题目编辑交互：人工校验和题库题目编辑的知识点改为联动知识点库的可搜索多选下拉，并在保存时同步写入知识点 id 与名称；题库列表编辑改为大弹窗样式，复用题干、答案、解析的 Markdown + LaTeX 编辑能力。
- 补充导入 OCR 工作台业务 + 技术流程图：在 `TECHNICAL_DESIGN.md` 和 `docs/architecture/import-ocr-workbench-flow.mmd` 中用绿色标注本地算力、黄色标注外部 API 算力、蓝色标注混合链路。
- 修复题库题目编辑弹窗布局挤压问题：题目编辑弹窗改为大尺寸双栏工作台，窄屏自动切换单栏滚动；同时补齐通用弹窗和表单控件的防溢出约束，降低组件重叠风险。
- 更新架构流程图到最新版：同步 `import-ocr-workbench-flow.mmd`、`ocr-flow.mmd`、`system-overview.mmd`，覆盖任务查重、题图库、多图上传、知识点联动、AI 解析、入库查重、题库弹窗编辑和渲染导出，并生成对应 SVG。
- 补齐题库题目编辑弹窗的题图管理能力：复用人工校验页的题图管理组件，支持从源导入任务题图库导入、本地上传、移除并保存到题库题目；新增题库题目题图上传、访问和图片库接口。
- 题库题目编辑弹窗的 AI 解析改为使用当前编辑态题干、答案、知识点和题图列表，解析草稿仍需人工复核后保存。
- 修复导入 OCR 工作台人工校验预览态解析显示：题目解析现在走 Markdown + LaTeX 渲染，不再直接显示原始源码。
- 将导入人工校验和题库题目编辑弹窗中的“本地标准化”改为“AI 标准化”，调用大模型修复题干 Markdown + LaTeX，并展示模型修正或复核提示。
- 优化 AI 标准化交互：AI 结果先作为候选源码和候选预览展示，用户手动应用后才覆盖编辑内容，避免模型输出异常时破坏原稿。
- 升级 AI 标准化为上下文修复：导入人工校验和题库题目编辑会检测严重 LaTeX 损坏，并在题目有来源时参考同题原始 OCR 文本生成候选，同时提示原稿和候选中的严重公式风险。
- 修复应用 AI 标准化候选后的保存回归：人工保存时如果本地公式标准化会引入更严重 LaTeX 风险，后端保留用户提交内容并记录复核提示。
- 修复题库中心筛选面板偶发排版错位：题库页网格行改为按内容高度排列，避免路由切换或空列表状态下 header、页签和筛选区被视口高度拉开。
- 试卷新增学科、年级字段：后端试卷 API 支持保存和序列化这两个字段，组卷中心试卷列表支持按学科、年级筛选，试卷编辑器可填写并在预览中展示。
- 扩展 OCR 导入文件类型：支持 `.md/.markdown` 直接解析，支持 `.doc` 先转换为 `.docx` 后再走 MinerU；前端上传选择器同步放开 `.doc` 和 Markdown 文件。
- 升级导入任务 AI 答案解析匹配：大模型补全会读取试卷 OCR 全文和可选答案 OCR 文本，从同卷“参考答案/答案解析/解答过程”区域按题号和题干语义匹配答案解析；缺少 OCR 证据的模型答案会被清空并提示人工复核。

## 2026-06-24

- 新增一期 FastAPI OCR 后端骨架。
- 新增 MinerU 命令行检测和本地安装脚本。
- 新增 Vite + React OCR 工作台，支持原文件和 OCR 结果左右双栏展示。
- 新增 `/docs` 文档体系和强制开发检查清单。
- 已将 MinerU 安装到项目本地 Python worker venv，并让后端优先检测项目本地 MinerU。
- 将所有 Markdown 项目文档统一改为中文。
- 新增 OCR Markdown 公式渲染能力，支持 `$...$` 和 `$$...$$` 通过 KaTeX 展示。
- 新增 OCR Markdown 题图路径解析，按 MinerU 输出位置显示对应题图。
- 新增 OCR 结果结构化拆题能力，后端输出大题 `sections` 和题目 `questions`。
- 右侧结果区默认改为按大题分组的题目卡片视图，展示题干、题图、选项和题型扩展内容。
- 新增阿里云百炼 / DashScope 大模型拆题链路：配置 `DASHSCOPE_API_KEY` 后优先使用大模型，失败时回退本地规则。
- 新增 `/api/system/llm` 状态接口和前端大模型配置状态展示。
- 新增 `splitter` 元信息，题目区展示拆题来源和兜底原因。
- 新增子题展示块，用于承载大题下的（1）（2）等子问。
- 新增 `.env.example`，并在开发规范中明确密钥禁止入库。
- 新增后端公式标准化与校验层，对题干、选项和子题进行多轮 LaTeX 修复与风险标记。
- 前端新增公式校验汇总和单题公式状态展示，区分正常、已自动修复和需复核。
- 后端新增本地 `.env` 自动加载能力，用于解决大模型密钥未进入进程环境导致的本地规则兜底提示。
- 新增题目人工校验编辑能力：题卡内支持 Markdown + LaTeX 双栏编辑和实时预览。
- 新增本地标准化与 AI 标准化接口，AI 标准化复用阿里云百炼 / DashScope 配置。
- 新增 `manualMarkdown` 保存机制，人工保存后优先渲染整题 Markdown + LaTeX。
- 前端新增 LaTeX `tasks` 选择题环境预览，将 `\task` 渲染为选项网格。
- 优化连续 `$$` 公式边界修复：支持 `=9$$(-12)` 这类同一行公式粘连，避免合法块级公式误报。
- AI 标准化升级为语义标准化：支持结合题目上下文修复 `5"` 误识别为 `$5^n$` 这类高置信 OCR 错误，并返回修正说明。
- 本地公式校验新增疑似指数引号风险提示，引导使用 AI 语义标准化或人工复核。
- OCR 结果返回前新增自动 AI 语义修复层：对本地校验命中的高置信语义 OCR 风险自动调用大模型，成功后写回题干并重新执行公式校验。
- 前端题卡新增“AI 自动修复”标记和修正说明展示，便于人工验收 OCR 质量。
