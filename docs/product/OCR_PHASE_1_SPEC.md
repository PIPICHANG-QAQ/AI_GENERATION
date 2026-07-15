# OCR-Flow、AI 标准化与人工校验规格

## 文档定位

本文件描述当前本期 OCR-Flow 和题目校验能力。文件名保留 `OCR_PHASE_1_SPEC.md` 仅为兼容旧链接，不表示项目仍按阶段拆分。

OCR-Flow 是 `question-engine` 的核心底层能力：它负责把试卷/答案文件解析成可校验、可修复、可入库的结构化题目草稿。它不是独立页面能力，而是被导入任务、题目加工能力 API、人工校验工作台和平台集成共同复用。

## 能力目标

- 支持试卷文件和答案文件上传。
- 默认使用 MinerU provider 执行 OCR 和版面解析。
- 通过 provider 边界预留替换其它 OCR 引擎的空间。
- 把 OCR 产物整理为 Markdown、JSON、图片资源、题目列表和大题结构。
- 识别题干、选项、小问 / 子题、题图和题型。
- 先抽取试卷结构契约，再拆题：总题数、大题段声明、每段题号范围必须约束后续题号候选。
- 保护选择题和空位题结构：选项、空位占位、小问和题图都必须按 OCR 证据归属，不能靠模型补写。
- 对图片型选择题恢复连续 A–H 选项链，并使用 MinerU `middle/content_list` 的页码、bbox 和页尺寸构造二维选项单元格；四图四选项默认执行全局一对一分配，不再把 Markdown offset 当作唯一高置信事实。
- 明确四选一但选项不完整、题干图与选项图冲突、归属缺少几何证据或资源不守恒时，写入 `imagePlacementValidation.blockingReasons` 并阻止标准化自动覆盖与入库。
- 对低置信空位题执行题目级视觉修复：使用 OCR bbox 裁出 question crop，检测长横线，并可选调用 Pix2Text 做二次 OCR。
- 对 Markdown + LaTeX 做本地标准化和风险检测。
- 在大模型已配置时执行低置信边界确认、人工触发 AI 标准化、AI 解析和答案解析匹配。
- 生成适合人工校验的题目草稿。
- 为 `question-package.v1` 提供题目、图片、答案、解析、候选知识点和 source evidence。

## 支持输入

- PDF：`.pdf`
- 图片：`.png`、`.jpg`、`.jpeg`、`.webp`、`.tif`、`.tiff`
- Markdown：`.md`、`.markdown`
- Word 旧格式：`.doc`
- Office：`.docx`、`.pptx`、`.xlsx`

处理规则：

- `.md/.markdown` 直接进入 Markdown 拆题和公式校验，不调用 MinerU。
- `.doc` 先转换为 `.docx`，再交给当前 OCR provider；转换失败时任务失败并返回明确错误。
- 其它格式由当前 provider 决定是否支持，允许通过 `OCR_FLOW_EXTENSIONS` 扩展或收缩可接收后缀。

## Provider 边界

默认 provider 为 `mineru`。业务层不得直接依赖 MinerU 的内部目录结构或 Python API，只依赖 OCR-Flow 的统一输出。

## 选择题题图归属

- 强标签包括带标点标签和独立行标签；粘在说明文字末尾的弱标签只有在 A 起始连续链、后续图片/布局块共同支持时才采用。
- 证据优先级为：人工 `confirmed/overridden` placement、完整选项链与二维布局一致、二维全局分配、Markdown offset、受限多模态候选、未归属。
- offset-only placement 最高只能进入待复核；二维全局分配的最优/次优 margin 不足时返回 alternatives，不静默覆盖。
- `IMAGE_PLACEMENT_MULTIMODAL_ENABLED=false` 为默认值。启用后仍只允许模型输出 `imageId → stem|A-H|unassigned`；非法 JSON、未知图片、重复选项、超时或模型不可用时继续 `review_required`。
- canonicalization preview 使用已保存 OCR Markdown、middle/content JSON 和图片重新计算，返回 `structureDiffs`；apply 使用现有 token、事务和回滚快照，不重新运行 MinerU，也不覆盖人工 placement。

配置项：

- `OCR_FLOW_PROVIDER`：选择 OCR provider，默认 `mineru`。
- `OCR_FLOW_EXTENSIONS`：声明当前 provider 支持的文件后缀。
- `MINERU_COMMAND`：MinerU 命令路径。
- `MINERU_TIMEOUT_SECONDS`：MinerU 执行超时。

MinerU 命令解析顺序：

1. `MINERU_COMMAND` 环境变量。
2. `backend/python-worker/.venv/bin/mineru`。
3. `PATH` 中的 `mineru`。

默认命令：

```bash
mineru -p <input_path> -o <output_path> -b pipeline
```

未来替换 OCR 引擎时，应优先新增 provider，不修改导入任务、题库中心、组卷中心或平台能力 API 的业务逻辑。

## API 入口

### Java 能力入口

- `GET /api/capabilities/ocr-flow`：返回 OCR-Flow provider 合约、默认 provider、配置键、worker endpoint 和替换策略。
- `GET /api/capabilities/ocr-flow/runtime`：返回当前 provider、可用 provider、允许文件类型和运行时状态。
- `POST /api/capabilities/question-processing/jobs`：能力化题目加工任务创建入口，接收试卷/答案文件并返回 `ProcessingJob`。
- `GET /api/capabilities/question-processing/jobs/{jobId}`：查询加工任务。
- `GET /api/capabilities/question-processing/jobs/{jobId}/question-package`：输出 `question-package.v1`。
- `question-engine/openapi/question-engine.v1.yaml`：平台静态契约源头，覆盖 OCR-Flow、题目加工、运行时和 callback-flow 主路径。

### 本地小平台兼容入口

- `POST /api/import-tasks`：创建导入任务。
- `GET /api/import-tasks`：查看导入任务列表。
- `GET /api/import-tasks/{taskId}`：查看任务详情和待校验题目。
- `GET /api/import-tasks/{taskId}/source/{paper|answer}`：预览试卷或答案原文件。

列表接口必须优先返回 Java 侧持久化快照，不得同步等待 Python worker。任务列表是导入首页的导航和历史记录入口，worker 正在 OCR、AI 调用、开发 reload 或临时不可达时，页面仍应能展示最近快照；任务创建、任务详情、重试和恢复流程负责同步 worker 最新状态。

### Python worker 入口

- `/worker/ocr-flow`：OCR-Flow 运行时探测。
- `/worker/ocr`：执行 OCR job。
- `/worker/ai/standardize`：AI 标准化。
- `/worker/ai/analysis`：AI 解析。
- `/worker/export`、`/worker/export/render`：导出 worker。

旧 `/api/ocr/*` 和其它 Python `/api/*` 路由只作为兼容迁移保留，不作为新增平台对接入口。

## OCR 结果结构

OCR 成功后必须形成以下结构：

- `markdown`：整卷 Markdown。
- `json`：OCR provider 原始或归一化 JSON。
- `assets`：图片资源列表。
- `sections`：大题列表，每个大题包含标题、题型和题目数组。
- `questions`：扁平题目列表。
- `splitter`：拆题来源，说明使用大模型、规则兜底或其它 provider。
- `boundaryConfidence`：本地边界置信度和是否跳过 AI 边界确认的原因。
- `mathValidation`：整卷公式校验汇总。
- `autoSemanticRepair`：自动 AI 语义修复的启用、跳过和应用情况。
- `autoStandardize`：首次返回前自动标准化的模式、候选数、应用数、阻断数和并发上限。
- `llmMetrics`：LLM 调用次数、总耗时和单次调用耗时明细；不得包含 prompt、密钥、完整 OCR 文本或图片 base64。

每道题至少包含：

- `id`
- `number`：OCR 结构内候选题号；导入工作台展示编号必须按平台导入顺序重新生成。
- `type`
- `stemMarkdown`
- `manualMarkdown`
- `answer`
- `analysis`
- `options`
- `subQuestions`
- `children`：兼容旧字段，内容与 `subQuestions` 保持一致。
- `images`
- `imagePlacements`：可选的显式题图归属，目标可为题干、A-H 选项、小问、答案、解析、共享材料、装饰图或未归属。
- `knowledgePoints`
- `difficulty`
- `score`
- `mathValidation`
- `autoSemanticRepair`
- `autoStandardize`
- `aiMetadata`

题图必须同时保留 `images` 资产池、`imagePlacements` 显式归属和对应 Markdown 图片引用。Markdown offset 是第一证据，MinerU page/bbox 是第二证据；几何证据不得覆盖明确 offset。无法可靠判断时目标必须为 `unassigned`，不得按图片数量或数组顺序自动塞入 A-D。用户修改归属时必须原子更新 placement 与 Markdown 引用。

空位题、补全题、横线题和证明过程填空题必须在 `stemMarkdown` / `manualMarkdown` 中保留可编辑占位，统一使用 `____` 或 `(____)`。占位只是题干结构，不等价于答案；答案仍进入 `answer` 或小问 `answer` 字段。

当一道大题包含多个小问时，答案、解析、题型、难度、分值和知识点应落在 `subQuestions` 的每个元素上，父题自身 `answer` / `analysis` 保持为空。Java 和 Python worker 对外同时返回 `subQuestions` 与历史兼容字段 `children`，平台新接入优先消费 `subQuestions`。

## 拆题与答案解析匹配

拆题以 OCR 原文和本地边界证据为主。OCR 主链路只保证 `markdown/json/assets/sections/questions/mathValidation` 等可人工校验产物；本地边界高置信时直接跳过 AI 边界确认，低置信时才按题段分片调用大模型确认边界。

拆题前必须先形成结构契约：

- 从卷面说明和大题标题抽取总题数，例如“本试卷共 21 题”。
- 从大题标题抽取分段声明，例如“一、填空题，共 12 题”“二、选择题，共 4 题”。
- 推断每段题号范围，例如 `1-12`、`13-16`、`17-21`。
- 大题前的编号、说明区编号、超出当前段范围的编号只能作为低分候选，不能直接生成题目。
- 结构契约不完整时仍允许拆题，但必须在 `structureValidation.warnings` 中提示。

数字题号必须先作为 `anchorCandidates` 评分，不得看到 `数字.` 就直接建题。评分维度包括：

- 是否在大题段内。
- 题号是否落在当前大题合法范围内。
- 是否出现在正文区域而不是卷头、页眉、答题说明或页脚。
- 后文是否像题干，而不是“本试卷、答题纸、考试时间、考生注意”等说明文本。
- 是否和前后题号连续。

输入包括：

- 试卷 OCR Markdown。
- 图片资源列表。
- 本地题号、选项、小问和题图边界参考。
- 可选答案文件 OCR Markdown。
- 试卷自身可能包含的参考答案、答案解析或解答过程。

大模型只负责低置信边界的确认或修正，不生成题干文本、答案或解析。当题干中存在 `(1)`、`（2）`、`①` 等小问边界时，父题保留共用材料/大题题干，小问进入 `subQuestions`，并同步到兼容字段 `children`。本地规则拆题是主链路的证据来源和兜底；模型失败、未配置、返回非法 JSON 或某个分片失败时，系统回退对应本地边界，不让 OCR 任务失败。

大模型输出必须经过本地归一化和校验。模型失败、未配置或返回非法 JSON 时，系统回退本地规则拆题。扁平 `questions` 可用于检索和兼容，但导入工作台生成题目卡片时应优先读取 `sections[].questions` 的父题，避免把小问误生成为独立大题。

结构校验必须检查：

- 题目总数是否满足卷面声明或大题声明的合计；局部页面样本可降级为 warning。
- 大题题号范围是否连续、无重复。
- 第一题不能出现在第一大题标题之前。
- 每道题的 `sourceEvidence` 起始文本必须匹配自身题号。
- 题干不能从公式中间、图片路径中间或无意义碎片开始。
- 题图路径必须能回溯到 OCR assets。

导入工作台从 OCR 输出生成待校验题时，不按 OCR 题号或 OCR `id` 做去重。平台展示编号按实际导入顺序递增；OCR `id` 只进入 `sourceQuestionId`。如果 OCR 在正文和答案解析区重复输出 `q_1..q_n`，后续重复项必须保留，并给 `sourceQuestionId` 增加 `__occurrence_2` 等后缀，避免覆盖前一轮题目。

答案和解析匹配规则：

- 如果 OCR 文本中包含参考答案、答案解析或解答过程，系统应按题号和题干语义匹配到对应题。
- 如果题目包含 `subQuestions`，答案、解析、知识点、难度和分值必须按小问 `id`、`label` 或原顺序匹配到对应小问；父题 `answer` / `analysis` 保持为空。
- 不是每道题都有答案或解析时，缺失题保持空值。
- 模型必须提供 `answerEvidence` 或 `analysisEvidence` 等 OCR 原文证据。
- 缺少 OCR 原文证据的答案/解析不得自动写入题目，避免把模型自行求解结果误当作教师原答案。
- 证据不足、跨题混淆或置信度低时，应写入 warning 并提示人工复核。

## 选择题和空位题结构保护

选择题和空位题是 OCR 拆题中最容易被误改写的结构。系统必须把它们作为证据驱动的结构保护能力，而不是针对某张截图的特例修补。

选择题保护规则：

- 本地规则负责优先识别稳定的 A/B/C/D 边界，支持 `A.`、`A．`、`A、`、`(A)`、全角字母、冒号标记、行首裸 `A/B/C/D`、标准 `tasks`、误识别 `ttasks` 和裸 `\task`。
- 题干正文中自然出现的 `A/B/C/D` 不应被误切为选项。
- 自动追加在选项后的题图引用必须回收到题干，不得污染最后一个选项。
- AI 只做边界纠错和低置信复核；对外稳定结果应收敛为 `options` 或标准 `tasks`，不能把选项正文混入题干。

空位题保护规则：

- 题型判断不能只看大题标题。只要题干或小问题干包含“填空”“横线”“空格”“空白”“空缺”“补全”“填写”“填入”“填上”“写在”“填在”等空位提示，或出现明确下划线/空位符号，就应按空位题保护处理。
- 显式空位符号统一归一为 `____`；括号内空位统一归一为 `(____)`。
- OCR 丢掉横线时，系统只在高置信结构位置保守恢复占位，例如公式行以 `=` 结束、文本以“值为/值是/取值范围是/是/为”等等待填写语义结束。
- 短数字、字母、标点组成的低信息 OCR 噪声行，只能在题目已经被判定为空位题后转成占位；普通题、选择题选项、题号和含中文/LaTeX/运算符的正文不得按噪声处理。
- 空位题中的 `(1)(2)`、`①②③` 等可能只是填空序号或证明步骤，不能直接拆成小问；只有后续文本构成独立题干时才进入 `subQuestions`。
- AI 标准化必须保留空位，占位缺失时只能返回 `____` / `(____)` 候选和 warning，不得直接求解并把答案填进题干。
- 答案/解析抽取仍必须带 OCR evidence；没有证据时不自动写入，只提示人工复核。

## 视觉证据修复与二次 OCR

视觉修复只处理主 OCR 已经低置信的题目，当前优先覆盖空位题、补全题、横线题和证明过程填空题。处理顺序：

1. 在 AI 边界确认阶段并行执行只读预处理，从 MinerU `content_list` / `middle` 读取题目 `bbox`、`page_idx`、页面尺寸、题号索引和有限页图像缓存。
2. 等边界确认、结构构建和小问拆解完成后，按最终题目结构进入 `visual-repair` 节点；该节点内部可按题目并发裁出 question crop。
3. 在 crop 内用本地像素扫描检测长横线，识别 OCR 丢失的空位视觉证据。
4. 如果当前题干缺少足够占位，保守追加 `____` 占位，并写入 `visualRepair` 元数据。
5. 如果配置了 `PIX2TEXT_COMMAND`，只对该题 crop 调用 Pix2Text 二次 OCR；候选必须比主 OCR 更完整，且题号不冲突，才允许写回题干。

视觉修复约束：

- 未配置 Pix2Text 时不影响 OCR 任务成功，只跳过二次 OCR。
- Pix2Text 输出只作为 OCR 证据补偿，不作为大模型推理结果；不得用它求解答案。
- 含小问的大题暂不自动覆盖父题题干，避免把多个小问合并回单题；后续可按小问 bbox 扩展。
- 每道题的修复证据写入 `visualRepair`，包括 crop 路径、bbox、横线数量、Pix2Text 输出和是否应用。
- 二次 OCR 只在低置信题目局部 crop 上运行，不整卷调用，避免拖慢导入速度。
- 视觉修复不能与边界确认共享可变题目结构；线程内只产出单题结果，主线程按原始题目顺序合并，保证视觉修复不影响题目识别稳定性。

## 布局解析框能力

- 布局解析框不属于视觉修复写回链路，而是独立的 `PaperLayoutCapability`。
- `PaperLayoutCapability` 只生成只读定位数据：`paperLayout.pages[]`、`paperLayout.regions[]`、`paperLayout.warnings[]`，不会修改 OCR 题目、题图或人工编辑稿。
- 布局解析框必须和题目识别解耦。题目结构由 OCR Markdown、结构契约和 source evidence 生成；布局框只在题目已经生成后绑定平台 `questionId`。布局解析失败、低置信或关闭时，不得影响题目数量、题干、选项或题图归属。
- `OCR_PAPER_LAYOUT_ENABLED=false` 时，任务详情返回空 `paperLayout` 和“布局解析框已关闭” warning，导入题目仍正常生成。
- 坐标源优先使用 MinerU `_middle.json` 的 `pdf_info[].para_blocks`、`discarded_blocks` 和 `page_size`，因为该坐标系与当前试卷页图预览同源；只有缺失 `_middle.json` 时才回退 `content_list`。
- 能力只输出父题级范围并绑定平台 `questionId`，过滤标题、章节说明、页码等非题目 block；前端点击后仅用于滚动定位右侧校验题卡。
- middle 图片路径可能嵌套在 `blocks[].lines[].spans[].image_path`，布局能力必须递归提取，避免图片题只框住文字标签。
- Markdown offset 回贴不得使用 `A/B/C/D` 这类极短选项标签作为可靠锚点，避免下一题公式中的字母把布局框串到错误题目。
- 当布局匹配只命中小标签、极小框、缺少预期题图或只有图片但缺少题干时，必须降级为不可靠，优先走几何题号锚点兜底；仍不可靠时只返回 warning 或不显示该题框。

## 公式标准化与 AI 修复

本地公式标准化负责处理高置信格式问题：

- 连续 `$` 或错误的公式边界。
- 行内公式与块级公式混用导致的渲染失败。
- `\frac { 5 } { 1 9 }` 这类 OCR 空格问题。
- `\left/\right` 不匹配。
- 花括号、方括号或环境 begin/end 不闭合。
- `tasks` 环境在预览和导出中的兼容转换。

AI 标准化负责处理需要上下文判断的语义修复：

- 指数被识别为引号。
- 公式变量、上下标或分式结构被 OCR 破坏。
- 题干中存在严重 LaTeX 风险但本地规则无法安全修复。
- 展示公式 `$$...$$` 内部嵌套单个 `$`，或行内公式被 `\div`、`\leq` 等数学运算符切断时，应先执行确定性分隔符修复，修成可渲染候选后再决定是否调用大模型。

AI 标准化约束：

- 导入题必须调用导入题专用接口，并参考同题原始 OCR 文本。
- 题库题必须调用题库题专用接口；如果题目来自导入任务，应回溯源 OCR 上下文。
- 新建题且没有题目 ID 时才允许调用通用标准化接口。
- `currentMarkdown` / `manualMarkdown` 只代表当前编辑稿，可能已经被人工或模型破坏；可信 OCR 证据必须通过 `rawOcrContext`、同题 OCR 题段、`stemMarkdown` 或来源题段单独传递，不得把当前编辑稿拼进 trusted raw OCR context。
- AI 标准化候选链路必须按“本地确定性修复 -> 可信 OCR 兜底 -> LLM 修复”执行；本地修复或 OCR 兜底已经消除严重风险时不得再调用 LLM。
- 标准化后必须整理展示公式块边界，避免 `$$...$$(2)` 这类块公式与正文粘连。
- 所有候选必须返回严重 LaTeX 校验和 Markdown/KaTeX 渲染级校验；不可渲染候选只能作为安全 fallback 说明，不得展示为可直接应用候选。
- AI 标准化成功后，Java 应记录 AI job，并默认把标准化后的 Markdown 作为候选返回；前端展示候选源码和候选预览，用户应用后再通过保存接口写入 `manualMarkdown`。
- 只有显式传入 `writeResult=true` 或 `apply=true` 时，Java 才尝试直接写回 AI 标准化结果；低置信、`candidateSevereIssues` 非空、`writeBlocked=true`、`applyBlocked=true` 或 `renderValidation.valid=false` 时必须保留原题干，并返回 `writeResult=false` 与 `writeSkippedReason`。
- 只有进入 LLM 修复阶段且成功返回的候选才可进入短期缓存；缓存 key 必须包含当前编辑稿、可信 OCR 上下文和结构化提示，TTL 由 `AI_STANDARDIZE_CACHE_TTL_SECONDS` 控制。
- 如果 currentMarkdown 或同题 OCR 上下文中混入本题答案、解析、参考答案或解答过程，AI 标准化应将其从题干中移除，并分别返回 `answer`、`analysis`；前端应用候选时可同步回填输入框，AI 解析接口仍负责答案/解析自动写回。
- 如果题目已有小问，或 currentMarkdown / 原始 OCR 上下文显示题目由多个小问组成，AI 标准化必须返回 `subQuestions[].answer` / `subQuestions[].analysis`，父题 `answer` / `analysis` 返回空字符串；Java 写回和前端应用候选时都只更新小问答案解析。
- 如果题目是空位题、补全题或横线题，AI 标准化必须保留 `____` / `(____)` 占位，不得把模型自行求解结果写回题干；缺失占位只能作为候选修复，并带出 warning。
- 答案/解析识别以大模型语义分析为主，程序脚本只做保守后处理：当模型已经返回 `answer` 或 `analysis` 时，必须删除题干中带 `【答案】`、`【解析】`、`【解答】`、`故答案为` 等明确标记的答案解析块；如果题干末尾以“长为/值为/结果为/等于”等形式直接拼入已抽取答案，应替换为空括号，答案只保留在 `answer` 字段。
- 修复后仍存在严重风险时不得覆盖原题干。
- 本地公式标准化如果会重新引入严重 LaTeX 风险，必须跳过该轮本地标准化并保留已修好的 AI 候选原文。
- OCR 主链路默认 `OCR_AUTO_SEMANTIC_REPAIR_MODE=skip`，只记录语义修复候选数量并交给人工校验；如需压测可配置为 `inline` 或 `inline-concurrent`，但低置信、仍有同类风险或缺少证据的修复不得自动写回。

### 首次返回前自动标准化

首次 OCR 导入题目支持在返回给用户前执行一次轻量自动标准化。该流程用于减少明显可修复的低置信问题，但不得替代人工校验，也不得创建 Java AI job。

配置项：

- `OCR_AUTO_STANDARDIZE_MODE=off|risky|all`，默认 `risky`。
- `OCR_AUTO_STANDARDIZE_MAX_CONCURRENCY`，默认 `2`，取值范围 `1..8`。

`risky` 模式只处理命中以下风险的题目：

- 严重 LaTeX 风险或渲染失败。
- 重复 Markdown、重复题图引用或图片选项同时出现在题干和选项中。
- 选择题选项数量异常、选项粘连或题图标签异常。
- `mathValidation.warningCount > 0`。

自动标准化写回前必须经过硬校验：

- 候选不能增加严重 LaTeX 风险。
- 候选必须通过渲染校验。
- 选择题不能丢失原有选项。
- 候选不能丢失原有题图标签，也不能引用未知题图。
- 含小问题目不能被候选降级为普通题。

校验失败、模型 fallback、`applyBlocked=true`、空候选或异常时，系统必须保留原题，只在题目和任务摘要中写入 `autoStandardize.status`、`reasons`、`blockReason` 或 `error`。

## 人工校验工作台

人工校验工作台用于把 OCR 草稿变成可入库题目。要求：

- 左侧预览试卷原文件，可切换答案原文件。
- 右侧展示 OCR 状态、拆题来源、公式校验汇总、题目列表、JSON 和图片资源。
- 每道题独立卡片展示题干、题图、选项、答案、解析和校验状态；含小问的大题展示“含 N 小问”标识。
- 含小问的大题使用复合编辑器：大题题干/材料编辑区 + 每个小问题干、答案、解析、题型、难度、分值和知识点编辑区。
- 题干、答案和解析都支持 Markdown + LaTeX 源码编辑与实时预览。
- 保存导入题、入库到题库、题库题创建和题库题更新都必须持久化 `subQuestions`；`children` 仅作为兼容别名同步返回。
- 选择题预览必须把选项从题干中独立渲染；OCR 或人工源码中的 `- A.`、`A．`、`A、`、`(A)`、标准 `\begin{tasks}...\task...\end{tasks}`、误识别 `\begin{ttasks}` 以及裸 `\task` 行都应解析为 `options`，保存时不得用旧空选项覆盖新解析结果。
- AI 标准化应保留原有换行、题号、选项和已有 `tasks` 环境；没有 `tasks` 时不要主动新增，除非题型明确为选择题且原文已有高置信 A/B/C/D 选项边界；不得输出 `ttasks` 等拼写错误环境。
- 人工校验和题库编辑的 LaTeX 源码面板必须包含选择题选项；如果题目已有结构化 `options` 但源码中没有选项块，前端应自动补成标准 `tasks` 块，用户直接在同一源码面板中编辑 `\task` 内容。
- 空位题源码和预览必须保留 `____` / `(____)` 占位；用户手动删除占位时按用户输入保存，AI 标准化候选不能绕过人工确认直接补回。
- 预览态必须渲染 Markdown + LaTeX，不能展示原始源码。
- 支持 AI 标准化、AI 解析、保存、单题入库和批量入库。
- AI 标准化返回候选源码和候选预览；用户应用候选时，若响应包含 `answer` 或 `analysis`，前端可回填对应字段，未返回时保留用户当前内容。
- AI 标准化候选面板必须区分来源：本地修复、原始 OCR 兜底、AI 修复；不可应用候选必须禁用“应用”按钮并展示具体原因。
- AI 解析返回 `answer` 时自动回填答案；未返回答案时保留用户当前答案。含小问题目会把当前 `subQuestions` 一并传给 worker，并要求模型返回每个小问的答案与解析；前端把结果合并到小问编辑区，父题答案解析保持为空。
- 含小问题目的每个可编辑小问必须保留独立 `AI 标准化` 和 `AI 解析` 操作。小问级标准化通过安全闸门后自动应用并保存到当前小问；被安全闸门阻断时只返回当前小问候选等待人工复核。小问级解析以大题材料、当前小问、答案、知识点和题图作为上下文，只回填当前小问 `answer` / `analysis`，不得修改父题或其它小问。
- 保存后题目优先展示人工编辑内容。
- 窄屏和桌面宽度都不能出现源码、预览、表单或按钮互相遮挡。

## 文件和题图

- Java `file-flow` 管理试卷原文件、答案原文件、题图、OCR 产物和导出文件元数据。
- 本地默认写入 `backend/storage/java_files`。
- 企业模式可切换到 MinIO 或平台文件中心。
- 原文件预览优先由 Java 返回；历史任务没有 Java 文件记录时可回退 Python worker。
- 每个导入任务必须形成任务级题图库，来源包括 OCR 题图和用户在该任务内上传的题图。
- 人工校验时，题图支持本地上传，也支持从当前任务题图库选择后关联到当前题目。
- 题图上传、任务题图库、图片选择关联和图片访问由 Java 接管。
- AI 解析只会把可读取且能识别为 PNG、JPEG、GIF 或 WebP 的题图转为多模态输入；损坏图片、占位字节、空文件或超限文件应标记 `aiImageIncluded=false` 和 `aiImageSkipReason`，并跳过该图但不中断解析。
- 通用 ad-hoc AI 解析入口也必须经过 Java 题图转换逻辑。当前用于新建题和小问级 AI 解析，避免有图小问在没有题目 ID 的草稿态看不到题图。
- 前端渲染 `/api/...` 相对地址时必须指向 Java backend。

## 运行限制

- OCR 质量仍受原文件清晰度、排版复杂度和 provider 能力影响。
- 跨页大题、复杂表格和几何图形空间归属仍需要人工复核。
- 空位题横线如果在 OCR 和图片证据中都严重缺失，系统只做保守占位恢复，不会猜测空位数量或填入模型求解答案。
- `.doc` 转换依赖本机文档转换器，推荐优先上传 `.docx`。
- 未配置大模型时，系统仍可生成待校验题目，但答案、解析和知识点补全质量会下降。
- MinerU 首次运行可能需要下载模型或初始化缓存，耗时较长。

## OCR-Flow Provider 替换边界

`ocr-flow` 是本项目最核心的能力边界。OCR provider 先把原始试卷/答案转成原生结果，provider adapter 再输出 `canonical-ocr-bundle.v1`，统一 Post Process 才执行拆题、公式标准化、AI 补全和人工校验。当前默认 provider 是 MinerU，但业务层和 Post Process 都不直接依赖 MinerU 私有结构。

Python worker 侧由 `backend/python-worker/app/ocr_flow.py` 定义 provider 抽象和默认 `MineruOcrProvider`；`app/ocr/contracts.py` 定义统一证据，`app/ocr/mineru_adapter.py` 是 MinerU 私有适配器，`app/ocr/postprocess_pipeline.py` 提供统一后处理入口。`ocr_execution.py` 负责编排上传、预处理、provider、bundle manifest 和 Post Process。Java 主后端通过 `/api/capabilities/ocr-flow` 返回能力描述，通过 `/api/capabilities/ocr-flow/runtime` 代理运行时状态，外部平台不应直接对接 MinerU。

主要配置项：

```text
OCR_FLOW_PROVIDER=mineru
OCR_FLOW_EXTENSIONS=.pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.docx,.pptx,.xlsx
MINERU_COMMAND=/absolute/path/to/mineru
MINERU_TIMEOUT_SECONDS=1800
MINERU_VERSION_TIMEOUT_SECONDS=3
```

新的 OCR provider 应实现四个稳定点：

- `name`：provider 名称，对应 `OCR_FLOW_PROVIDER`。
- `status()`：返回可用性、版本、命令路径或错误原因。
- `run(OcrProviderRequest)`：执行 OCR 并返回 `OcrProviderResult`。
- provider adapter：把原生结果转换为 `CanonicalOcrBundle`。

Provider 不应负责后处理、导入任务业务状态、题库入库、用户权限租户、题目审核流或平台知识点主数据。Provider 只做 OCR 引擎调用，其 adapter 只做原生证据归一化。

替换 MinerU 的最小路径：

1. 在 `backend/python-worker/app/ocr_flow.py` 中新增一个 `OcrProvider` 实现。
2. 新增 `<provider>_adapter.py`，输出 `canonical-ocr-bundle.v1`。
3. 在 provider 注册表中注册，并设置 `OCR_FLOW_PROVIDER` / `OCR_FLOW_EXTENSIONS`。
4. 调用 `/api/capabilities/ocr-flow` 和 runtime 接口验证契约与可用性。
5. 运行契约测试和相同黄金样本，对比题数、选项、小问、题图、公式、调用数和性能。

只要 `CanonicalOcrBundle` 输入契约和统一 outputs 不变，Java 能力层、前端人工校验页、题库中心、组卷中心都不需要跟着 OCR provider 替换而大改。完整使用说明见 `docs/delivery/POST_PROCESS_USAGE_GUIDE.md`。
