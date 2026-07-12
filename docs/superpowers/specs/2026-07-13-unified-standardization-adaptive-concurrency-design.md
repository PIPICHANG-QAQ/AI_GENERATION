# 统一标准化流水线与自适应并发设计

日期：2026-07-13
状态：已确认，待实施计划
目标分支：`codex/image-placement-upgrade`

## 1. 背景

当前单题标准化和全局标准化最终都会调用 Python worker 的标准化逻辑，但两条路径并不等价：

- 单题标准化由前端把独立存储的选择题选项拼入 Markdown，再以候选方式应用；
- 全局标准化只把数据库中的 `manualMarkdown` 或 `stemMarkdown` 发送给 worker，并直接请求安全写回；
- Java 生成的 `structuredHints` 没有包含 `options`，导致 worker 已有的选择题选项保护无法稳定生效；
- Java 批任务并发和 worker 模型并发默认均为 2，Java 代码还把批任务并发硬性封顶为 2；
- 批任务进度同时统计题干、答案、解析和小问字段，容易把 51 道题显示成 225 个“AI 标准化任务”，但实际执行单位仍应是 canonical 题目；
- 单题页面的 job 提示延迟 1.5 秒显示，因此规则、OCR 回退或缓存快速返回时，用户会误以为没有启动任务。

本设计选择“统一标准化流水线”方案：单题和全局共用同一输入构造、同一决策顺序、同一结构保护与同一模型并发闸门，仅在最终应用方式上保留差异。

## 2. 目标

1. 单题和全局标准化对同一道题生成等价输入，并使用同一 worker 流水线。
2. 固定按“本地规则 → OCR 回退 → 缓存 → 必要时调用模型”的顺序执行。
3. 每道 canonical 题只创建一个标准化任务项；字段数量不再显示成 AI 任务数量。
4. 真实模型并发采用自适应控制：初始 4、最低 2、最高 8。
5. 本地规则、OCR 回退和缓存命中的题不占用模型并发名额。
6. 全局标准化不得丢失、减少、重排选择题选项，不得错误改变题图和小问归属。
7. 只有通过公式、渲染、选项、题图、小问和输入版本校验的结果才能自动写回。
8. 页面和运行指标能区分规则、OCR、缓存、模型、待复核和失败数量。
9. 保留批任务取消、恢复、失败重试、服务器重启恢复和版本回滚能力。

## 3. 非目标

- 本次不更换模型供应商或模型。
- 本次不重新设计 OCR 边界识别和 canonicalization 算法。
- 本次不让 AI 覆盖人工确认的题图归属。
- 本次不把全局批任务迁移为完全由 Python 持久化管理。
- 本次不改变单题标准化“候选预览后保存”的交互原则。
- 本次不合并到 `main`；仍在保留分支完成开发、测试和服务器灰度。

## 4. 核心决策

### 4.1 职责边界

Java 负责：

- 从数据库读取题目并构造唯一的标准化请求；
- 持久化批任务、题目任务项、状态、取消、恢复和结果摘要；
- 根据 worker 的结构校验结果执行题目级原子写回；
- 为单题和全局请求创建 Java AI job 审计记录；
- 对外提供批任务进度和题目级排障信息。

Python worker 负责：

- 本地确定性规则修复；
- 原始 OCR 更优片段回退；
- 标准化结果缓存；
- 判断是否需要调用模型；
- 统一的自适应模型并发、路由和重试；
- 模型结果后处理和结构保护；
- 返回统一的执行路径、结构摘要和写回建议。

前端负责：

- 单题候选预览和人工应用；
- 全局任务进度、执行路径统计、待复核和失败入口；
- 不再自行决定全局任务输入结构或并发。

### 4.2 统一请求构造

Java 新增单一职责的标准化请求构造器。单题、全局、重试和恢复必须调用同一构造器，不允许各自拼装请求。

标准请求包含：

```json
{
  "pipelineVersion": "standardization.v2",
  "questionId": "q_2",
  "questionNumber": 2,
  "questionType": "choice",
  "editableMarkdown": "题干与规范化 tasks 选项块",
  "rawOcrContext": "同题原始 OCR 片段",
  "structuredHints": {
    "answer": "",
    "analysis": "",
    "options": [],
    "images": [],
    "imagePlacements": [],
    "subQuestions": []
  },
  "inputHash": "sha256"
}
```

构造规则：

- `editableMarkdown` 优先使用非空 `manualMarkdown`，否则使用 `stemMarkdown`；
- 如果题目为选择题且 Markdown 中没有完整选项块，则根据结构化 `options` 追加规范 `tasks` 块；
- 结构化选项是稳定基线，Markdown 选项是发送给模型的可读表达；
- `structuredHints` 必须包含完整的选项、题图、题图归属和小问；
- `inputHash` 必须包含流水线版本、题干、选项、题图、题图归属、小问和原始 OCR 上下文；
- 任一结构字段变化都必须导致哈希变化，禁止复用旧结果覆盖新编辑。

### 4.3 统一返回契约

worker 返回：

```json
{
  "pipelineVersion": "standardization.v2",
  "executionPath": "rules",
  "modelInvoked": false,
  "cacheHit": false,
  "applyRecommendation": "safe_to_apply",
  "markdown": "标准化后的题干",
  "options": [],
  "images": [],
  "imagePlacements": [],
  "subQuestions": [],
  "answer": "",
  "analysis": "",
  "originalStructure": {
    "optionCount": 4,
    "imageCount": 4,
    "subQuestionCount": 0
  },
  "resultStructure": {
    "optionCount": 4,
    "imageCount": 4,
    "subQuestionCount": 0
  },
  "reviewReasons": [],
  "providerCallAttempts": 0,
  "cachedExecutionPath": null,
  "standardizer": {}
}
```

枚举约束：

- `executionPath`: `rules | ocr-fallback | cache | llm`
- `applyRecommendation`: `safe_to_apply | unchanged | review_required | failed`
- `reviewReasons`: 使用稳定机器码，例如 `option_count_changed`、`image_ownership_conflict`、`stale_input`

`executionPath=cache` 时，`cachedExecutionPath` 记录被缓存结果最初来自 `rules`、`ocr-fallback` 或 `llm`。`modelInvoked` 只表示当前请求是否实际调用模型。

Java 在 worker 结果外增加最终 `writeDecision`：`candidate | applied | unchanged | review_required | failed`。单题安全结果为 `candidate`，全局安全写回成功后为 `applied`；worker 只提供写回建议，最终写回决定属于 Java。

旧版 `standardizer` 元数据暂时保留，供现有前端和接口兼容；新代码优先使用顶层稳定字段。

## 5. 标准化流水线

固定执行顺序如下：

1. 校验请求字段、题型和结构基线。
2. 执行本地公式分隔符、LaTeX 空格、括号配对、重复 Markdown 和 tasks 拼写修复。
3. 如果本地修复已消除严重问题且渲染校验通过，返回 `executionPath=rules`。
4. 如果当前题干严重损坏且同题原始 OCR 更完整，返回 `executionPath=ocr-fallback`。
5. 计算标准缓存键并查询缓存；命中时返回 `executionPath=cache`。
6. 前述路径都不能产生可靠候选时，进入模型优先级队列。
7. 获得自适应 LLM 闸门许可后调用模型，执行受限重试。
8. 对模型结果执行答案/解析抽取、公式修复、重复折叠和小问合并。
9. 对候选执行选择题、题图、小问、公式和渲染不变量校验。
10. 返回写回建议；Java 根据执行模式和最新 `inputHash` 决定候选展示或原子写回。

单题和全局的唯一区别：

- 单题：返回候选，由前端预览并保存；
- 全局：通过所有安全条件时自动写回，否则保存候选并标记 `review_required`。

## 6. 自适应并发

### 6.1 两层并发

- 批任务预处理窗口：最多同时推进 12 道题，处理规则、OCR、缓存和结果校验。
- 真实 LLM 并发：由 Python worker 的共享自适应闸门控制，范围为 2–8，初始为 4。

预处理窗口不是模型并发。规则、OCR 和缓存快速路径不消耗 LLM 许可。

### 6.2 并发所有权

Python worker 是真实模型并发的唯一所有者。Java 不再用硬编码上限 2 充当模型限流器，只控制批任务预处理窗口和待处理题目数量。

单题、全局、批任务重试和 OCR 自动增强共享同一个模型闸门，防止不同入口合计突破供应商容量。

优先级从高到低：

1. 人工触发的单题标准化；
2. 全局任务失败重试；
3. 全局任务普通题目；
4. OCR 自动增强。

同一优先级内使用 FIFO；低优先级连续等待达到阈值后允许一次老化提升，避免永久饥饿。

### 6.3 AIMD 调整

参数：

```text
initial = 4
minimum = 2
maximum = 8
successWindow = 20
cooldown = 30s
```

增加条件：

- 最近连续 20 次供应商调用成功；
- 没有 429、503 或超时；
- 窗口错误率低于 5%；
- 窗口延迟未超过基线的 1.5 倍。

满足后并发上限增加 1，最大为 8。

降低条件：

- 收到 429；
- 连续两次超时；
- 收到 503 或明确的服务繁忙响应；
- 最近窗口错误率超过 20%。

触发后使用：

```text
newLimit = max(2, floor(currentLimit / 2))
```

随后进入 30 秒冷却期。冷却期间继续完成已获得许可的调用，但不提升并发。

worker 重启后从初始值 4 恢复，不持久化短期拥塞状态。

### 6.4 重试

允许重试：429、502、503、504、网络超时和无法解析的模型 JSON。

不重试：结构不变量失败、题图归属冲突、输入缺失、低置信候选和 stale input。

最多尝试 3 次，退避为 2 秒、5 秒，并增加 ±20% 抖动。结构问题进入待复核，不重复消耗模型费用。

## 7. 状态模型

题目任务项状态：

```text
queued
preprocessing
rules_completed
ocr_fallback_completed
cache_completed
waiting_for_llm
llm_running
validating
applied
unchanged
review_required
failed
cancelled
```

批任务状态：

```text
queued
running
completed
partial_review
partial_failed
failed
cancelling
cancelled
```

终态规则：

- 所有题为 `applied` 或 `unchanged`：`completed`；
- 存在 `review_required` 且无技术失败：`partial_review`；
- 部分题技术失败：`partial_failed`；
- 全部题技术失败：`failed`。

取消时不再调度新题。已发送给模型的调用可以完成，但取消后完成的结果不自动写回，标记为可复用候选。恢复时只重排未完成题，并按最新 `inputHash` 判断候选能否复用。

服务器重启后，`preprocessing`、`waiting_for_llm`、`llm_running` 和 `validating` 重置为 `queued`；终态题目不重复执行。

## 8. 结构保护

### 8.1 不可变基线

流水线开始前保存：题型、选项标签与内容、题图 ID、题图归属、小问 ID 与标签、答案和解析摘要。候选必须与基线进行差异校验。

### 8.2 选择题

原题存在至少两个结构化选项时：

- 候选不得减少选项数量；
- 标签不得缺失、重复或重排；
- AI 未返回选项时恢复原结构化选项；
- AI 只返回部分选项或改变标签时进入 `review_required`；
- 题干中的 tasks 块与数据库 `optionsJson` 必须由同一候选生成；
- 图片选项不得被替换成自然语言描述；
- 图片引用数量不得减少。

### 8.3 题图归属

证据优先级：

```text
人工确认的 imagePlacements
> canonicalization 证据
> Markdown 明确引用
> OCR 空间位置
> AI 建议
```

AI 只能为未确定图片提供建议，不能覆盖更高优先级证据。题干和选项归属冲突进入 `review_required`，原因记录为 `image_ownership_conflict`，原题保持不变。

### 8.4 小问

- 小问 ID 和标签顺序稳定；
- 父题公共材料不复制到每个小问；
- 小问答案和解析不写入父题；
- AI 新识别出小问时默认作为候选；只有本地边界证据充分时，全局任务才允许自动应用结构变化。

## 9. 安全写回

全局自动写回必须同时满足：

- 模型置信度不是 `low`；
- 无严重 LaTeX 问题；
- 渲染校验通过；
- 选择题结构不变量通过；
- 题图归属校验通过；
- 小问结构校验通过；
- 写回前重新计算的 `inputHash` 与执行输入一致。

不满足时保存候选、结构差异和原因，标记 `review_required`，不修改原题。

题干、选项、题图、题图归属、小问、答案、解析和标准化元数据必须在同一个题目级事务中写回。禁止出现题干已更新而选项或题图仍是旧版本的中间状态。

## 10. 缓存

缓存键包含：

- `pipelineVersion`
- 题干 Markdown
- 原始 OCR 上下文
- 选项
- 题图
- 题图归属
- 小问

保留现有 worker 内存缓存，默认 TTL 为 300 秒。批任务持久化项继续使用输入哈希避免服务器重启后重复处理已成功且输入未变化的题目。

缓存结果重新使用前必须再次执行结构和渲染校验。命中缓存不等于允许自动写回。

## 11. 任务计数与接口兼容

主进度只按 canonical 题目统计：

```text
completedQuestions / totalQuestions
```

一题只对应一个标准化任务项。题干、答案、解析和小问字段处理量仅作为内部 `processedFieldCount`，不展示为 AI 任务数。

批任务摘要新增：

```json
{
  "totalQuestions": 51,
  "completedQuestions": 38,
  "rulesCount": 12,
  "ocrFallbackCount": 3,
  "cacheHitCount": 8,
  "llmQuestionCount": 15,
  "reviewRequiredCount": 2,
  "failedCount": 0,
  "providerCallAttempts": 17,
  "currentLlmConcurrency": 5,
  "maximumLlmConcurrency": 8
}
```

`llmQuestionCount` 是实际进入过模型的题数；`providerCallAttempts` 包含重试，两者不得混用。

为兼容旧客户端，现有 `totalItems/completedItems/successItems/failedItems` 暂时保留一个版本，但前端不再把它们标为 AI 任务数，并在接口文档中标记弃用。

## 12. 前端交互

全局进度显示：

```text
38 / 51 题完成
本地规则 12 · OCR 回退 3 · 缓存命中 8 · AI 处理 15
待复核 2 · 失败 0 · 当前模型并发 5/8
```

提供取消、恢复、重试失败题、查看待复核题、查看实际调用 AI 的题和单题执行详情。

单题结果显示稳定来源标签：本地修复、OCR 回退、缓存结果、AI 修复、待人工复核。即使请求不足 1.5 秒而未显示运行中提示，完成后仍必须显示最终执行来源。

题目详情可查看修改前后差异、模型是否调用、缓存命中、模型名称、耗时、重试次数、降并发原因和结构保护记录。

## 13. 可观测性

指标：

```text
standardization_questions_total{path,status}
standardization_duration_seconds{path}
standardization_llm_requests_total{provider,status}
standardization_llm_active
standardization_llm_concurrency_limit
standardization_cache_hits_total
standardization_review_required_total{reason}
standardization_structure_guard_total{type}
```

日志统一携带：`taskId`、`batchJobId`、`batchItemId`、`questionId`、`aiJobId`、`executionPath` 和 `inputHash`。

日志不得记录完整试题、图片二进制、Data URL、密钥和完整原始 OCR 文本。

## 14. 数据持久化

批任务项需要持久化以下结果摘要：

- `executionPath`
- `applyRecommendation` 和 Java 最终 `writeDecision`
- `modelInvoked`
- `cacheHit`
- `providerCallAttempts`
- `reviewReasons`
- `candidate/result metadata`
- `inputHash`
- 各阶段耗时

批任务摘要可以从题目项聚合并回写现有 job 计数字段。候选正文只保存在受控结果 JSON 中，列表接口默认不返回完整内容。

## 15. 测试设计

### 15.1 Java 单元测试

- 单题和全局对同一道题生成相同请求；
- 请求包含选项、题图、归属和小问；
- 任一结构字段变化后 `inputHash` 改变；
- 每道 canonical 题只创建一个任务项；
- stale input 拒绝写回；
- 单题请求优先于全局普通任务；
- 题目级写回保持原子性。

### 15.2 Python 单元测试

- 规则、OCR 和缓存路径不调用模型；
- 缓存未命中才进入 LLM 闸门；
- AI 删除、减少或重排选项时恢复或阻止写回；
- 图片选项引用和人工题图归属不会丢失；
- 缓存结果仍执行结构校验；
- 429、503、超时触发并发下降；
- 连续成功触发并发逐级恢复；
- 不可重试结构问题直接进入待复核。

### 15.3 前端测试

- 51 道题显示为 51 道标准化题目；
- 正确显示四条执行路径、待复核和失败数量；
- 待复核不显示为技术失败；
- 快速完成后仍显示最终来源；
- 当前模型并发正确轮询和展示。

### 15.4 集成测试集

固定覆盖纯文本选择题、四图片选项题、题干图题、题干与选项混合图题、填空题、多小问题、公式损坏题、答案区重复题和人工编辑后的题。

每题分别执行单题和全局标准化，要求 `type/options/images/imagePlacements/subQuestions` 一致。允许差异仅为单题先返回候选、全局在安全时自动写回。

### 15.5 并发与故障测试

使用 100 道题模拟 60 道规则命中、20 道缓存命中、20 道调用模型，并注入随机 429、连续 503、超时、服务重启、用户取消和并行单题请求。

要求模型并发始终处于 2–8，429 后立即下降，稳定后逐步恢复；单题不被全局长期阻塞；重启后已完成题不重复调用；不发生重复或部分写回。

## 16. 灰度发布

阶段一：影子模式。新流水线运行但不自动写回，对比旧结构和执行路径。

阶段二：小流量自动写回。只允许规则、OCR 回退和缓存路径中的安全结果自动写回，模型结果仍进入待复核。

阶段三：完整启用。结构校验全部通过的模型结果允许自动写回，保留快速切回候选模式的开关。

开关：

```text
STANDARDIZATION_PIPELINE_V2_ENABLED
STANDARDIZATION_PIPELINE_V2_SHADOW_MODE
STANDARDIZATION_AI_AUTO_APPLY_ENABLED
STANDARDIZATION_ADAPTIVE_CONCURRENCY_ENABLED
```

服务器发布前创建备份，只更新保留分支版本，不合并 `main`。

## 17. 验收标准

- 单题和全局使用相同请求构造器与 worker 流水线；
- 51 道 canonical 题只创建 51 个题目任务项；
- 规则、OCR 和缓存命中时不调用模型；
- 全局标准化不丢失文本或图片选项；
- 人工题图归属不会被 AI 覆盖；
- `review_required` 不修改原题；
- 真实模型并发在 2–8 之间自适应；
- 单题请求可优先获得模型许可；
- 容器保持 healthy，公网前端和健康接口正常；
- 固定测试集和服务器真实试卷测试通过；
- 发布前备份和回滚路径验证通过；
- 分支保留，不合并 `main`。

## 18. 回滚

出现数据或模型稳定性问题时，按以下顺序降级：

1. 关闭 `STANDARDIZATION_AI_AUTO_APPLY_ENABLED`，所有模型结果改为待复核；
2. 关闭 `STANDARDIZATION_ADAPTIVE_CONCURRENCY_ENABLED`，模型并发固定为 2；
3. 关闭 `STANDARDIZATION_PIPELINE_V2_ENABLED`，恢复旧流水线；
4. 如已发生错误写回，使用题目级标准化前快照或服务器发布备份恢复。

回滚不得删除批任务审计记录，便于定位触发原因和受影响题目。
