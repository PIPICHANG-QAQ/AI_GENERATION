# 服务器部署 Changelog

本文件只记录服务器部署相关变更。项目通用功能变更继续记录在 `docs/CHANGELOG.md`。

## 2026-07-16

### MinerU OCR 生产恢复与全量运行态验收

本节记录生产运行态恢复，不表示正式生产交付或全部模块化计划已完成。

- 已切换 question-engine 到镜像 sha256:18f2ee29a87ed5c1a4809ce5c49ccae60dfa30df0e569e987778653f8fd700ef；上一镜像保留为 ai-generation-question-engine:pre-edc045d（sha256:761d7e15fd459152a17107ddfa20fefb72c22c9b242a98488439bbc614b39850）。
- active MinerU venv 的 runtime 返回 mineru 3.4.2、runtimeProbeOk=true、apiReady=true；运行解释器为 /home/user/AI_GENERATION_DOCKER/vendor/mineru-venv/bin/python。
- 新镜像包含 LibreOffice 7.3.7.2，.doc 的真实导入、转换、OCR 和题目生成已通过；同轮 13 类声明支持格式均成功产出题目。
- 公开前端返回 200，Java health 成功、Java 到 Python worker 可达；平台业务 smoke 和 AI smoke 全部通过。
- 原失败导入任务 import_task_20260715_065444_e0d1c55f 已复用 OCR job ocr_20260715_065444_6f78252a 成功完成；本次仅发起一次 retry，retryCount=2 为历史累计值，questionCount=37、failureReason 为空。
- 最近容器日志未匹配 Traceback、ERROR、Exception、cannot import 或 CUDA out of memory；GPU0 为 MinerU Python，GPU1 保持 vLLM。
- 本次生产恢复代码归档已更新为 edc045d 对应包；旧 d29674e 归档保留在服务器 release/archive-d29674e。完整 SHA-256、备份和限制见生产恢复验收记录。

## 2026-07-10

### OCR v15 结构契约、自动标准化和布局解耦

- 服务器已重新构建 `ai_generation_docker-question-engine-1`，当前镜像包含结构契约拆题、题号候选评分、首次返回前低置信自动标准化和布局框只读解耦。
- `.env` 当前启用：

```text
OCR_PAPER_LAYOUT_ENABLED=true
OCR_AUTO_STANDARDIZE_MODE=risky
OCR_AUTO_STANDARDIZE_MAX_CONCURRENCY=2
```

- `OCR_AUTO_STANDARDIZE_MODE=risky` 只处理严重 LaTeX、渲染失败、重复 Markdown、图片/选项异常等低置信题；不创建 Java AI job，候选通过渲染、选项、题图、小问和严重风险硬校验后才写回。
- `PaperLayoutCapability` 已确认只做只读定位，不参与题目拆分、题图归属写回或人工编辑稿生成；布局框异常时可把 `OCR_PAPER_LAYOUT_ENABLED=false` 作为快速降级，不影响题目识别能力。
- 布局框绑定已修复 MinerU `_middle.json` 嵌套图片路径识别，并跳过 `A/B/C/D` 短选项标签作为 Markdown offset 锚点；只命中小标签、极小框、缺题图或 image-only 缺题干时会降级到几何兜底或 warning。
- 本地验证：Python worker 全量测试 `87 passed`；截图对应 4 题样本回放后，第 3 题覆盖完整图片选项，第 4 题覆盖题干和题图。
- 服务器验证：容器重建后 `GET /api/java/health` 返回 `success=true`，Docker health 为 `healthy`，客户体验地址仍为 `http://120.211.112.121:5173/`。

## 2026-07-09

### AI 解析全部进度反馈

- 导入工作台“AI 解析全部”新增顶部进度条，启动后立即展示当前处理题号/小问、成功失败计数和百分比，避免长耗时请求期间看起来无响应。
- 普通题批量解析改为调用与单题“AI 解析”一致的导入题专用接口 `/api/import-tasks/{taskId}/questions/{questionId}/analysis`；复合大题仍按小问生成后统一保存父题小问结构。
- 批量解析期间继续禁用“重新 OCR 扫描”“AI 解析全部”“批量入库”，完成后自动刷新任务详情。

### 布局解析框能力封装

- 代码层将布局解析框收敛为 Python worker `PaperLayoutCapability`：
  - 对外继续兼容 `attach_paper_layout`、`build_paper_layout`、`render_source_page`、`question_image_refs_by_layout`。
  - 内部统一管理 `paperLayout` 构建、页图渲染和题图几何辅助。
  - `paperLayout` 增加 `capability` 元数据，前端仍消费 `pages[]`、`regions[]`、`warnings[]`。
- 文档同步：产品规格、OCR 规格、技术设计、接口说明、验收标准、架构图和代码结构可迁移性评审均已更新。

### 布局解析框题目绑定版

- 在 MinerU `_middle.json` 坐标对齐验证通过后，布局解析框从 raw 调试版切回正式题目定位模式。
- 后端 `paperLayout.regions` 现在：
  - 优先读取 `_middle.json` 的精准 bbox 和 `page_size`。
  - 按页面几何阅读顺序识别题号锚点，并切分父题范围。
  - 过滤试卷标题、章节说明、页码等非题目 block。
  - 按平台题目顺序绑定 `questionId` 和显示编号，不使用 OCR 题号重排。
  - 输出 `source=mineru_question`，前端点击后跳转并高亮右侧对应校验题卡。
- 若 OCR 可用 bbox 数量不足，会返回 warning 提示仅匹配到部分题目，避免静默漏框。
- 本地验证：Python worker 全量测试 `80 passed`，local-platform `npm run build` 通过。

### MinerU raw bbox 坐标系修正

- 修正布局解析框 raw 调试层坐标偏移问题：raw bbox 优先读取 MinerU `_middle.json` 的 `pdf_info[].para_blocks` 和 `discarded_blocks`，而不是直接用 `*_content_list.json`。
- 原因：`content_list.json` 的 bbox 与当前原始 PDF 预览 PNG 不是同一个坐标基准，直接用预览图尺寸归一化会把页码等底部元素画到页面中部。
- 新逻辑：
  - 有 `_middle.json` 时使用其中的 `page_size` 作为 bbox 归一化分母。
  - 保留标题、正文、图片/公式块、页码等 raw block，不做题目过滤、不做右侧题目关联。
  - 没有 `_middle.json` 时 fallback 到旧的 `*_content_list.json` raw 读取。
- 本地验证：Python worker 全量测试 `80 passed`，local-platform `npm run build` 通过。

### MinerU 原始 bbox 调试版

- 按最新排查需求，布局解析框暂时切换为 MinerU 原始 bbox 展示模式。
- 后端 `paperLayout.regions` 直接来自 MinerU `*_content_list.json`：
  - 不按题目匹配。
  - 不过滤标题、章节、页码等内容。
  - 不拆分多行 block。
  - 不按 AI 校验题目建立点击关联。
  - 每条 bbox 原样转成前端百分比坐标，附带 `source=mineru_raw`、`type` 和短文本摘要。
- 前端对 `mineru_raw` 框使用 amber 样式展示；点击不跳转右侧题目，只用于观察 MinerU 版面识别效果。
- 目标：先确认 MinerU 返回的 bbox 原始质量，再决定后续如何从 raw bbox 中筛选题目相关框。
- 本地验证：Python worker 全量测试 `79 passed`，local-platform `npm run build` 通过。

### 布局解析框题干锚点模式

- 按产品目标调整布局解析框：从“尽量框住整道题”改为“命中题干锚点即可”，用于用户从原文件快速定位到右侧校验题目。
- 后端 `paperLayout.regions` 现在优先按 MinerU 几何阅读顺序匹配题号开头的题干 block，并只使用该 block 的 bbox 生成可点击框。
- 保留平台顺序编号，不使用 OCR 题号重排。
- 标题、章节说明、页码等非题目内容仍会过滤；匹配不到可靠题干锚点时继续给 warning，不强行画错框。
- 题图归属逻辑仍保留原来的 MinerU 几何整题切组，不受本次“只画题干锚点框”影响。
- 本地验证：Python worker 全量测试 `79 passed`。

### 导入校验保存失败修复

- 修复人工校验题目保存时报 `body.options.*.raw Input should be a valid string` 的问题。
- 原因：前端选项结构已携带 `{label, content, contentMarkdown, raw}`，其中 `raw` 可能是对象；后端 `ImportQuestionPayload.options` 仍按 `dict[str, str]` 校验，导致 Pydantic 返回 `422`。
- 处理：
  - 后端放宽导入题 `options` payload 类型，并在写入父题和小问时统一清洗为 `{label, content, contentMarkdown}`。
  - 前端保存前不再向 API 提交 `raw` 对象。
- 验证：
  - 本地 Python worker 回归测试通过。
  - local-platform `npm run build` 通过。
  - 服务器 API 已用同类 payload 验证返回 `200`，保存后的选项结构已清洗。

### 原型 v15/v16 全选能力同步

- 根据原型仓库 v15/v16 需求，把“全选”交互移植到当前运行项目。
- 导入工作台“任务记录”：
  - 任务列表非空且未全部选中时显示描边“全选”按钮。
  - 点击后选中当前任务列表全部实际存在项；全部选中后“全选”自动隐藏。
  - “删除所选 (n)”和批量删除提交 id 均按当前任务列表与选中集合的交集计算，避免刷新后过期选中项虚增数量或误删。
- 题库中心题目列表：
  - 列表头部新增描边“全选”按钮。
  - 分页语义为“选中当前页全部题目，并叠加到已有跨页选择上”；当前页已全选时按钮隐藏，翻到未全选页后重新显示。
  - “全部取消”仍清空所有页选择。
- 本次为纯前端选择状态更新，不涉及 API、后端数据模型或数据库变更。
- 验证：
  - local-platform `npm run build` 通过。
  - 服务器已发布新前端资源 `index-BfTfx69F.js`。
  - 当前容器 `ai_generation_docker-question-engine-1` 健康检查通过。

### 外部大模型 TokenHub 切换

- 服务器运行目录 `/home/user/AI_GENERATION_DOCKER/.env` 已切换外部 OpenAI 兼容模型网关：
  - `DEEPSEEK_BASE_URL=https://tokenhub.shwfl.edu.cn/v1`
  - `DEEPSEEK_MODEL=qwen3.7-max`
  - `LLM_MODEL=qwen3.7-max`
  - `LLM_PROVIDER=tokenhub`
- 旧 `.env` 已保存到 `/home/user/AI_GENERATION_DOCKER/.run/secret-backups/.env.before-tokenhub-*`，不在文档中记录任何 API Key。
- 已通过 `docker compose -f docker-compose.server.yml up -d --force-recreate question-engine` 让新环境变量进入容器。
- 运行时验证：`GET /api/system/llm` 返回 `provider=tokenhub`、`model=qwen3.7-max`、`baseUrl=https://tokenhub.shwfl.edu.cn/v1`、`routerMode=external`。

### 布局解析框发布

- 发布导入工作台“布局解析框”开关：试卷原文件预览可叠加父题级 bbox 范围框，点击后定位并高亮右侧校验题卡。
- 新增试卷单页页图接口 `GET /api/import-tasks/{taskId}/source/paper/pages/{pageIndex}`，支持多页 PDF；答案文件暂不显示布局框。
- Python worker 容器依赖补齐 `pypdfium2`，用于渲染 PDF 页图并与 OCR bbox 坐标对齐。
- 布局框范围生成改为优先按 MinerU 原始页面顺序和题号锚点切分：多行 text block 会近似拆成行级 bbox，试卷标题、章节说明和页码会被过滤，只有锚点不足时才回退旧的 Markdown evidence 匹配。
- OCR 题图归属改为 MinerU bbox 几何优先：按 `(page_idx, y0, x0)` 阅读顺序切题并重新分配图片，修复图片在 `content_list` JSON 顺序上排在下一题文本前导致误挂到上一题的问题。
- 服务器抽查任务 `import_task_20260708_095949_4eaef9b9`：返回 `paperLayout.pages=28`、`regions=70`、`warnings=0`；第一页页图接口返回 `200 image/png`，尺寸 `1191 x 1684`。

### OCR 题图与选择题鲁棒性发布

- 发布 OCR 题图引用稳定化：关联图片使用稳定 `图N` 标签，删除图片不重排编号，并同步清理题干、答案、解析、小问题干、小问答案和小问解析中的对应引用。
- 发布 OCR 初扫图片标签化：原始图片路径、API URL、文件名统一规范为 `![](图N)`；无法原位定位时追加到题干末尾并写入人工复核 warning。
- 发布选择题选项图片标签化补强：支持 OCR 把图片语法识别成 `![]` 换行 `(images/xxx.jpg)` 的情况；选项图保留在对应 `\task` 中并规范为 `![](图N)`，不再重复追加到题干顶部。
- 发布 AI 标准化选择题保护：AI 候选丢失选项时恢复原 OCR 结构化选项，图片选项保留 `![](图N)`。
- 本地验证通过：Python worker `72 passed`、local-platform `npm run build`、契约检查通过。

## 2026-07-08

### OCR HTML 表格预览发布

- 已将本地最新代码同步到服务器运行目录 `/home/user/AI_GENERATION_DOCKER`，保留服务器 `.env`、`server-data`、`vendor`、MinerU venv 和模型缓存。
- 服务器前端重新安装依赖并完成 `npm run build`；修复 npm optional dependency 导致 Rollup Linux native 包缺失的问题。
- 已重建并重启 `ai_generation_docker-question-engine-1`，当前容器健康检查通过。
- 本次发布包含 `MarkdownRenderer` 的受控 OCR HTML 表格渲染增强：题目预览会把 `<table>/<tr>/<td>/<th>` 渲染成表格，并保留 `rowspan` / `colspan`。
- 验证地址：`http://120.211.112.121:5173/`；`http://120.211.112.121:8018/api/java/health` 返回正常。

### 导入工作台 v13 批量操作

- 本地项目已同步原型 v13：导入工作台工具栏新增“AI 解析全部”和“重新 OCR 扫描”。
- “AI 解析全部”由前端顺序调用现有 AI 解析接口和题目保存接口：默认只补缺失解析，可勾选覆盖已有解析；已入库题跳过，复合大题按小问生成，失败项不阻断整批。
- “重新 OCR 扫描”新增 Java 接口 `POST /api/import-tasks/{taskId}/rescan`，会重新投递当前任务的试卷/答案 OCR job，并把任务状态切到 `处理中`；当前已提取和已编辑题目不重建、不覆盖。
- 重扫期间前端自动轮询任务详情，并禁用“重新 OCR 扫描”“AI 解析全部”“批量入库”；重复触发重扫返回 `409`。
- 已补齐 Java/Python 代理白名单：`/api/import-tasks/{taskId}/rescan` 由 Java 编排控制器处理，不会被 Python worker API 代理截获。
- 服务器发布后需重点验证：任务详情可从 `处理中` 自动恢复到 `待校验/部分完成`，题目编辑内容不因重扫丢失。

### AI 标准化 / AI 解析同步并发与兜底

- 服务器 Compose 新增默认配置：

```text
LLM_STANDARDIZE_MAX_CONCURRENCY=4
LLM_ANALYSIS_MAX_CONCURRENCY=4
LLM_STANDARDIZE_MAX_ATTEMPTS=2
LLM_ANALYSIS_MAX_ATTEMPTS=2
```

- AI 标准化 LLM 超时、限流或返回非法 JSON 时，不再直接返回 `409 标准化失败`；worker 返回 `source=rules-fallback`、`fallbackUsed=true`、`retryable=true` 的本地兜底候选，并保留 `llmCalls` 失败明细。
- AI 解析 LLM 失败时返回可重试兜底元数据，前端只提示“稍后重试或人工填写”，不清空当前答案/解析编辑内容。
- 当前阶段保持单题人工按钮的同步请求语义；大量用户上线或批量 AI 加工时，后续应升级为 Java `ai-flow` 队列/MQ 后台任务，配合租户级、用户级和模型 endpoint 限流。

### 导入题号改为平台顺序编号

- 导入任务不再按 OCR 扫描到的题号去重或对齐展示编号。
- 平台展示题号改为按导入顺序自动编号：`1, 2, 3...`。
- 当 OCR 结果中出现重复 `q_1..q_n`（例如试卷正文和答案解析区各出现一轮题号）时，会保留全部父题，并给内部 `sourceQuestionId` 追加 `__occurrence_2` 后缀，避免被 Java 题目表覆盖。
- 已在服务器将任务 `import_task_20260708_052629_3d1b2b05`（标题 `4123`）从旧的 `28` 题重建为 `56` 题。
- 重新部署前端后，当前服务器可见任务 `import_task_20260708_060119_79dfcc32`（标题 `1`）同样验证为 `56` 题，编号 `1..56`，第 `29` 题起对应重复 OCR 来源 `q_1__occurrence_2`。

### 人工校验原型样式同步

- local-platform 人工校验编辑器按原型图调整背景规则。
- 只有题干源码 / 小问题干源码输入区保留蓝色背景。
- 题目预览、小问预览、答案、解析、AI 候选源码、AI 候选预览和元数据表单保持白底。

### OCR 最后一题尾部标题污染修复

- 修复试卷正文最后一道题或最后一个小问后紧跟“试卷标题 / 参考答案与试题解析”时，标题被并入题干的问题。
- 题目结构构建阶段现在会在尾部遇到 `参考答案与试题解析`、`答案解析`、`【解答】`、重复试卷标题等非题干区块时截断题干证据范围。
- 保留截断点之前属于本题的小问题图，不影响正常题号去重。

### AI 边界确认分片并发

- 新增 `LLM_BOUNDARY_MAX_CONCURRENCY`，专门控制 `llm-boundary-refine` 的分片并发，不再完全复用通用 `LLM_MAX_CONCURRENCY` 或本地模型并发。
- 服务器配置为：

```text
LLM_BOUNDARY_CHUNK_SIZE=5
LLM_BOUNDARY_MAX_CONCURRENCY=4
LLM_EXTERNAL_MAX_CONCURRENCY=4
```

- 目标：20 道题按每 5 题拆成 4 片，并发调用外部 `deepseek-v4-pro`。
- 分片原则：按本地候选题目边界和绝对 offset 切分；chunk 失败只回退该 chunk 的本地边界，避免整卷回退。

### 常驻 MinerU API 与 OCR 加速

- 将 OCR 调用路径从每次临时启动 MinerU FastAPI 服务，改为容器内常驻 `mineru-api`。
- 新增并启用：
  - `MINERU_API_ENABLED=true`
  - `MINERU_API_URL=http://127.0.0.1:8002`
  - `MINERU_API_MAX_CONCURRENT_REQUESTS=1`
- `backend/python-worker/app/ocr_flow.py` 支持读取 `MINERU_API_URL`，并在执行 MinerU CLI 时追加 `--api-url`。
- `scripts/docker-entrypoint.sh` 支持启动常驻 `mineru-api`。
- 预热后性能验证：
  - 单页图片 OCR：约 `9s`
  - 4 页 PDF OCR：约 `12.4s`
- 优化前同类任务 OCR provider 阶段约 `147s - 157s`。

### ModelScope 缓存持久化

- 新增 Docker 挂载：

```text
./server-data/modelscope-cache:/root/.cache/modelscope
```

- 目的：容器重建后保留 MinerU / PDF-Extract-Kit 模型缓存，减少重复下载和校验。
- 验证时宿主机和容器内缓存大小均约 `782MB`。

### ONNX GPU provider

- 在服务器 MinerU venv 安装 `onnxruntime-gpu==1.23.2`。
- 容器内验证 `onnxruntime.get_available_providers()` 返回：

```text
TensorrtExecutionProvider
CUDAExecutionProvider
CPUExecutionProvider
```

- 说明：部分 ONNX OCR 子模型可使用 CUDA provider，不再只有 CPU provider。

### GPU 资源拆分

- AI_GENERATION / MinerU 固定使用物理 GPU0。
- vLLM / `aux-qwen3-32b-fp8` 固定使用物理 GPU1。
- AIGeneration 容器环境：

```text
NVIDIA_VISIBLE_DEVICES=0
CUDA_VISIBLE_DEVICES=0
OCR_CUDA_VISIBLE_DEVICES=0
MINERU_VIRTUAL_VRAM_SIZE=48
```

- 验证结果：
  - GPU0 有常驻 MinerU Python 进程，占用约 `1.2GB` 显存。
  - GPU1 上仍为 vLLM 进程，占用约 `39GB` 显存。

### 公网访问入口

- 保留客户体验地址：`http://120.211.112.121:5173/`
- 增加 80 端口映射：`0.0.0.0:80 -> container:8080`
- 验证情况：
  - `:5173` 公网可访问。
  - 服务器本机访问 `http://127.0.0.1/` 正常。
  - 外部访问 `http://120.211.112.121/` 超时，疑似上游安全组或线路策略限制。

### 部署目录与旧目录清理

- 当前运行目录固定为 `/home/user/AI_GENERATION_DOCKER`。
- 旧目录 `/aa/AI_GENERATION_TOGO` 不再作为运行目录；此前已确认不应继续运行旧项目。

### 错误反馈与任务创建修复

- 新增 Java API 异常处理，使 `ResponseStatusException` 的业务 detail 能传到前端。
- 前端 API 错误解析优先使用 `detail`，其次 `message`，再其次 `error`。
- 任务标题重复时能够返回明确提示：`导入任务标题已存在，请更换标题`。

### OCR 流程图与命名整理

- 新增/更新 OCR-Flow 架构图，标注本地算力和外部大模型边界。
- 区分 `ocr-flow.*` 与 `server-ocr-flow.*`：
  - `ocr-flow.mmd/svg`：主 OCR-Flow 业务链路。
  - `server-ocr-flow.mmd/svg`：服务器部署视角的算力边界。

### 大模型路由

- AI 边界确认默认走外部满血模型，避免低置信边界确认被本地模型拖慢。
- 服务器本地 `aux-qwen3-32b-fp8` 保留用于小问结构、标准化等低风险结构任务。
