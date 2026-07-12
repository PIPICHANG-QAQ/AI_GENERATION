# OCR 题图归属与选项匹配升级设计

## 目标

在不恢复旧版“按布局顺序直接覆盖题图”的前提下，提高题图与题目的匹配正确度，并显式表达图片属于父题题干、具体选项、小问或未归属状态。所有自动写回都必须可解释、可回退、可人工复核。

## 已确认的问题

1. 主 Markdown 区间结果可能被 legacy `pending_images` 错误补图。
2. 整卷结构校验失败时，即使 legacy fallback 仍无效，也会覆盖主结构。
3. 图片 offset、page、bbox 在题目构造后丢失。
4. 图片选项依赖提示词、数量相等和数组顺序，无法稳定处理双栏、缺图、混合题干图。
5. 结构校验只检查图片路径，不检查图片 owner、跨题重复或选项归属。
6. 前端图片标签可能在增删图片时重编号；导出会把选项图扁平化到题干后。

## 设计原则

- Markdown offset 是第一证据，MinerU bbox/page 是第二证据。
- 提示词和图片数量只作为弱特征，不能单独决定 owner。
- layout 继续与题目边界解耦，只向独立 reconciliation 阶段提供候选证据。
- 无法高置信判断时保留 `unassigned`，不得静默删除或默认写入题干。
- 自动结果、人工结果和渲染引用必须能互相校验。
- 先做确定性规则；多模态模型只处理低置信冲突样本。

## 数据模型

题目继续保留兼容字段 `images[]`，新增 `imagePlacements[]`：

```json
{
  "placementId": "placement-image-id-0",
  "imageId": "image-id",
  "target": {
    "kind": "stem | option | subquestion | shared | answer | analysis | unassigned | decoration",
    "optionLabel": "A",
    "subQuestionId": null
  },
  "order": 0,
  "sourceEvidence": {
    "markdownStart": 120,
    "markdownEnd": 145,
    "pageIndex": 0,
    "bbox": [100, 200, 300, 400]
  },
  "inference": {
    "method": "explicit-offset | geometry | rule | multimodal | human",
    "confidence": 0.96,
    "reasons": ["inside-option-span"],
    "alternatives": []
  },
  "reviewStatus": "auto | needs_review | confirmed | overridden"
}
```

图片资产和放置位置分离，以支持共享材料、一图多处引用和人工调整。现有 Markdown 图片引用继续作为编辑、预览和导出的兼容格式。

## 后端数据流

1. MinerU 产物收集时只读取 provider 原始输出目录，排除 `visual_repair/` 和 `paper_preview_pages/`。
2. 本地/LLM 边界继续生成题目、选项、小问和图片 offset。
3. 题目构造优先消费显式 option span；图片落在 option span 内时直接生成高置信 placement。
4. `image-reconcile` 使用 sourceEvidence、page/bbox、题号范围和选项标签布局补充候选。
5. Markdown 与 geometry 一致时自动接受；冲突时保留主证据并写 warning，不直接覆盖。
6. 结构校验增加 owner、引用和资产守恒检查。
7. fallback 按章节或题目比较质量，仅在 fallback 自身有效且更优时替换。
8. 视觉修复在最终结构选定后执行，并按 sourceEvidence/occurrence 定位。

## 前端交互

- 每张图片展示稳定 `图N`、归属、置信度和复核状态。
- 可将图片切换为题干、A-H 选项、小问或未归属。
- 修改 placement 时同步更新对应 Markdown 引用；修改失败不得只更新一边。
- 新上传图片默认 `unassigned`。
- 存在未归属、重复归属或悬挂引用时，“已校验”和导出显示阻断提示。
- 保留当前工作区删除前端自动 zip 的意图，前端不再自行猜测选项图。

## 导出

- 题干图片按题干 Markdown/placement 顺序渲染。
- 选项图片在对应选项内部渲染。
- 小问图片在对应小问内部渲染。
- 未归属图片不静默进入正式导出，并产生 warning。

## 错误处理与降级

- `structureValidation.valid=false` 且 fallback 也无效：返回“需人工复核”结果，不伪装为正常高质量结果。
- 缺少 bbox：继续使用显式 offset；没有 offset 时为 `unassigned`。
- bbox 与 offset 冲突：保留 offset，降低 confidence 并记录 alternatives。
- 图片路径不唯一：禁止 basename 随机取第一项。
- 多模态不可用：不影响确定性结果，低置信 placement 保持待复核。

## 测试策略

- 固化两份真实回归：四题截图、48 页 B_B 试卷。
- 覆盖 q1 图片不再复制给 q2、q24/q25 各保留一图。
- 覆盖双栏四宫格 A/B/C/D、D 图片位于 label 前、题干图与选项图混合。
- 覆盖零选项选择题、重复题号、跨页、共享图、装饰图、派生图污染。
- 覆盖前端打开—增删图—保存—重开 round-trip。
- 覆盖 DOCX/PDF/Markdown 导出中选项图位置。

## 发布门槛

- 高置信自动归属 precision 不低于 99.5%。
- 图片选项 exact mapping 不低于 98%。
- dangling/orphan 各不高于 0.5%。
- 独立审计 600 道带图题时严重跨题误配为 0。
- 先 shadow，再按 5% → 25% → 100% 放量。

