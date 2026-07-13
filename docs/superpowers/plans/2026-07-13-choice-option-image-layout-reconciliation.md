# 选择题选项完整性与题图二维归属 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从已保存的 OCR Markdown 与 MinerU 布局产物中恢复完整选择题选项，并用二维全局约束把题图稳定归入 A–H 选项；不确定结果必须阻断自动写回。

**Architecture:** 保留现有 OCR、canonicalization 和标准化入口，在 Python worker 内新增一个纯函数二维分配模块。题目解析先恢复单调选项链，再按题目布局范围构造标签、文本、图片节点并求全局最优分配；校验摘要随题持久化并通过 Java request factory 进入统一标准化守卫。人工确认结果具有最高优先级，canonicalization 只基于已保存 OCR 产物重算，不重新调用 MinerU。

**Tech Stack:** Python 3 / pytest、FastAPI worker、Java 17 / Spring Boot / JUnit、TypeScript / React / Vitest、Docker Compose。

---

## Task 1: 恢复粘连和跨块的选项标签序列

**Files:**
- Modify: `backend/python-worker/app/question_markdown.py`
- Modify: `backend/python-worker/app/question_boundary.py`
- Test: `backend/python-worker/tests/test_question_boundary.py`
- Test: `backend/python-worker/tests/test_question_markdown.py`

- [x] 添加失败测试：输入 `A/B/C` 后出现 `运动鞋底的鞋钉 D\n\n![](images/d.png)` 时，`split_choice_options()` 应恢复 A–D，且 D 的内容包含图片。
- [x] 添加失败测试：英文正文中的普通大写 `D`、公式变量 `D` 和缺少 A–C 前序链的孤立 `D` 不得成为选项。
- [x] 添加失败测试：跨页序列化 Markdown 中 A/B 在前页、C/D 在后页时仍生成一个单调 A–D 链，且不越过下一题题号。
- [x] 运行 `cd backend/python-worker && python -m pytest tests/test_question_markdown.py tests/test_question_boundary.py -q`，确认新测试因弱标签候选尚未实现而失败。
- [x] 在 `detect_choice_option_markers()` 中增加仅针对“当前期望标签”的弱候选：要求前序链存在，候选后紧邻换行/图片/短文本块，并记录 `strength` 与 `reasons`，不把弱候选直接当作独立强标签。
- [x] 调整 `split_choice_options()` 的候选链选择：优先连续 A–D、拒绝重复/倒序/跨下一题；仅在弱候选获得图片或完整链补强时采用。
- [x] 在边界置信度中把明确选择题但只有 2/3 个选项标记为 `unstable-choice-options`，四项完整链才可视为稳定。
- [x] 重跑目标测试，确认通过；再运行 `cd backend/python-worker && python -m pytest tests/test_question_boundary.py tests/test_import_services.py -q` 防止导入链回归。
- [x] 提交：`git add backend/python-worker/app/question_markdown.py backend/python-worker/app/question_boundary.py backend/python-worker/tests/test_question_markdown.py backend/python-worker/tests/test_question_boundary.py && git commit -m "fix: recover embedded choice option labels"`

## Task 2: 新增二维选项单元格与全局一对一分配器

**Files:**
- Create: `backend/python-worker/app/choice_layout_assignment.py`
- Create: `backend/python-worker/tests/test_choice_layout_assignment.py`

- [x] 添加失败测试：四宫格图片输入顺序为 D/A/C/B 时，结果仍为 `a→A, b→B, c→C, d→D`。
- [x] 添加失败测试：图片位于标签上方时，轮胎图应归 A、骆驼图应归 B，而不是题干和 A。
- [x] 添加失败测试：A/B 与 C/D 分处连续两页时，分配器输出同一 A–D 序列；不同题目页区间的节点不得混入。
- [x] 添加失败测试：最优和次优总代价差小于阈值时返回 `needs_review` 与 alternatives，不伪造高置信结果。
- [x] 运行 `cd backend/python-worker && python -m pytest tests/test_choice_layout_assignment.py -q`，确认模块缺失导致 RED。
- [x] 实现纯函数节点归一化：校验 `pageIndex`、bbox、页宽/页高、稳定 `imageRef`，并构造 `option-label`、`text`、`image` 节点。
- [x] 实现选项单元格构造，支持“标签→图片”“图片→标签”和同行/同列；跨页只允许题目布局范围内的连续页面。
- [x] 实现代价函数：同页、行列重叠、归一化距离、阅读顺序、offset 一致性和交叉惩罚。
- [x] 用 `itertools.permutations` 对最多 A–H 的小规模集合求全局最低成本，并计算次优 margin；无多图聚类证据时强制一对一。
- [x] 输出确定性审计字段：`totalCost`、`secondBestCost`、`margin`、`blockingReasons`、逐图 alternatives 和 confidence。
- [x] 运行目标测试确认 GREEN，并运行 `python -m compileall -q app`。
- [x] 提交：`git add backend/python-worker/app/choice_layout_assignment.py backend/python-worker/tests/test_choice_layout_assignment.py && git commit -m "feat: assign choice images with layout constraints"`

## Task 3: 将二维分配接入 OCR placement，并保护人工结果

**Files:**
- Modify: `backend/python-worker/app/question_layout.py`
- Modify: `backend/python-worker/app/image_placement.py`
- Modify: `backend/python-worker/app/ocr_processing.py`
- Test: `backend/python-worker/tests/test_question_layout.py`
- Test: `backend/python-worker/tests/test_image_placement.py`
- Test: `backend/python-worker/tests/test_ocr_processing.py`

- [ ] 添加失败测试：`load_image_placement_evidence()` 必须保留 `pageWidth/pageHeight`，并唯一匹配完整路径或唯一后缀；歧义 basename 不得选中任一节点。
- [ ] 把现有 `test_geometry_conflict_does_not_override_explicit_offset` 改为目标行为：完整二维 A–D 证据应纠正错误 offset，并在 alternatives 中保留旧归属。
- [ ] 添加失败测试：`reviewStatus=confirmed` 或 `overridden` 的 placement 不被自动分配器覆盖，冲突只进入阻断原因。
- [ ] 添加失败测试：缺少 bbox 的 offset-only placement 最高置信度低于 `0.95`；几何与 offset 一致才可达到自动采用阈值。
- [ ] 运行 `cd backend/python-worker && python -m pytest tests/test_question_layout.py tests/test_image_placement.py tests/test_ocr_processing.py -q`，确认预期失败。
- [ ] 让 `question_layout.py` 暴露题目范围内的完整布局节点及页尺寸，不再依赖纯 Markdown 窗口过滤掉未索引标签。
- [ ] 在 `reconcile_image_placements()` 中调用全局分配器：高置信二维结果可纠正自动 offset；人工 placement 冻结；冲突保留 alternatives。
- [ ] 重新校准 `build_image_placements()`：offset-only 只作为候选证据，不再固定给 `0.98/0.99`。
- [ ] 在 `reconcile_structure_image_placements()` 汇总 assignment 成本、跨页数、冲突数和保护的人工结果数。
- [ ] 重跑目标测试和 `cd backend/python-worker && python -m pytest tests/test_image_placement.py tests/test_question_layout.py tests/test_question_boundary.py -q`。
- [ ] 提交：`git add backend/python-worker/app/question_layout.py backend/python-worker/app/image_placement.py backend/python-worker/app/ocr_processing.py backend/python-worker/tests/test_question_layout.py backend/python-worker/tests/test_image_placement.py backend/python-worker/tests/test_ocr_processing.py && git commit -m "fix: reconcile image placements from layout evidence"`

## Task 4: 增加强制结构不变量并阻断错误标准化写回

**Files:**
- Modify: `backend/python-worker/app/image_placement.py`
- Modify: `backend/python-worker/app/question_boundary.py`
- Modify: `backend/python-worker/app/import_services.py`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/StandardizationRequestFactory.java`
- Test: `backend/python-worker/tests/test_image_placement.py`
- Test: `backend/python-worker/tests/test_import_services.py`
- Test: `backend/src/test/java/com/aigeneration/questionbank/StandardizationRequestFactoryTest.java`
- Test: `backend/src/test/java/com/aigeneration/questionbank/StandardizationBatchServiceTest.java`

- [ ] 添加失败测试：明确四选一但只有三项时返回 `choice_option_sequence_incomplete`；图片型选择题出现 stem 图且某选项无图时返回 `stem_option_geometry_conflict`。
- [ ] 添加失败测试：高置信 placement 缺少 page/bbox、同图多个排他归属、一个选项多图但另一个空缺时分别产生机器码并设置 `blocking=true`。
- [ ] 添加失败测试：`build_import_questions()` 将 `imagePlacementValidation` 复制到导入题，canonicalization preview 也保留该字段。
- [ ] 添加 Java 失败测试：`StandardizationRequestFactory` 从题目 `rawJson` 读取 `imagePlacementValidation` 放入 `structuredHints`，并纳入 `inputHash`。
- [ ] 添加 worker 失败测试：存在 blockingReasons 时，规则快速路径不得返回 `safe_to_apply`，模型结果也必须为 `review_required`。
- [ ] 运行 Python 与 Java 目标测试，确认 RED：`cd backend/python-worker && python -m pytest tests/test_image_placement.py tests/test_import_services.py -q`；`cd backend && mvn -Dtest=StandardizationRequestFactoryTest,StandardizationBatchServiceTest test`。
- [ ] 扩展 `validate_image_placements()` 返回 `blocking`、`blockingReasons`、`expectedOptionCount`、`optionImageCounts` 和缺失几何统计。
- [ ] 在 `question_boundary.py` 和 `import_services.py` 持久化校验摘要；不新增数据库列，沿用现有 `rawJson` 以保持兼容。
- [ ] 在 Java request factory 读取并传递校验摘要；在 Python `finalize_standardize_response()` 合并阻断原因，设置 `applyRecommendation=review_required`。
- [ ] 确保全局批处理继续按现有 `applyRecommendation` 跳过写回，单题接口返回相同守卫结果。
- [ ] 重跑目标测试，再运行 `cd backend && mvn test`。
- [ ] 提交：`git add backend/python-worker/app/image_placement.py backend/python-worker/app/question_boundary.py backend/python-worker/app/import_services.py backend/src/main/java/com/aigeneration/questionbank/domain/service/StandardizationRequestFactory.java backend/python-worker/tests/test_image_placement.py backend/python-worker/tests/test_import_services.py backend/src/test/java/com/aigeneration/questionbank/StandardizationRequestFactoryTest.java backend/src/test/java/com/aigeneration/questionbank/StandardizationBatchServiceTest.java && git commit -m "fix: block unsafe choice image standardization"`

## Task 5: 让 canonicalization 基于已保存 OCR 产物重算并展示差异

**Files:**
- Modify: `backend/python-worker/app/import_services.py`
- Modify: `backend/python-worker/app/worker_routes.py`
- Modify: `backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportTaskCanonicalizationService.java`
- Test: `backend/python-worker/tests/test_worker_canonicalization_route.py`
- Test: `backend/python-worker/tests/test_import_services.py`
- Test: `backend/src/test/java/com/aigeneration/questionbank/ImportTaskCanonicalizationServiceTest.java`

- [ ] 添加失败测试：preview 读取保存的 OCR output 及 middle/content 布局，返回每题 `optionCountBefore/After`、placement old/new target、confidence 和 blockingReasons，且不修改任务。
- [ ] 添加失败测试：apply 使用 preview token 原子写入并保留 rollback snapshot；已人工确认 placement 保持原值。
- [ ] 添加失败测试：缺少布局文件时返回待复核差异，不触发 OCR/MinerU 执行函数。
- [ ] 运行 worker 与 Java canonicalization 目标测试，确认 RED。
- [ ] 在 `canonicalize_import_outputs()` 中复用 Task 1–4 的确定性重算，不建立第二套解析逻辑。
- [ ] 扩展 preview 响应的结构差异摘要；保持现有 token、stale preview 检查和回滚协议。
- [ ] 在 Java apply 中继续使用现有快照事务，只写 preview 已确认的题目结构与校验摘要。
- [ ] 重跑目标测试和 `cd backend/python-worker && python -m pytest tests/test_question_canonicalization.py tests/test_worker_canonicalization_route.py tests/test_import_services.py -q`。
- [ ] 提交：`git add backend/python-worker/app/import_services.py backend/python-worker/app/worker_routes.py backend/src/main/java/com/aigeneration/questionbank/domain/service/ImportTaskCanonicalizationService.java backend/python-worker/tests/test_worker_canonicalization_route.py backend/python-worker/tests/test_import_services.py backend/src/test/java/com/aigeneration/questionbank/ImportTaskCanonicalizationServiceTest.java && git commit -m "feat: preview layout-aware question canonicalization"`

## Task 6: 增加受限的低置信多模态兜底协议

**Files:**
- Create: `backend/python-worker/app/image_placement_multimodal.py`
- Create: `backend/python-worker/tests/test_image_placement_multimodal.py`
- Modify: `backend/python-worker/app/image_placement.py`
- Modify: `.env.example`

- [ ] 添加失败测试：只有 confidence 位于 `[0.80, 0.95)` 或存在 geometry/offset 冲突时才调用 resolver；高置信、低于 0.80 和人工 placement 均不调用。
- [ ] 添加失败测试：resolver 只能返回 `imageId → stem|A-H|unassigned`；修改题干/答案、未知 imageId、重复排他归属或非法标签时拒绝输出并保持 `review_required`。
- [ ] 添加失败测试：超时、模型不可用或非法 JSON 时不降级成 stem 图。
- [ ] 运行 `cd backend/python-worker && python -m pytest tests/test_image_placement_multimodal.py -q`，确认 RED。
- [ ] 实现小接口 `resolve_ambiguous_assignments(crop_evidence, candidates, resolver)`，将外部调用隔离为可注入 resolver；默认由 `IMAGE_PLACEMENT_MULTIMODAL_ENABLED=false` 关闭。
- [ ] 仅发送局部页图、标签框、图片框、稳定 imageId 和选项短文本；返回后再次执行 Task 4 的结构不变量。
- [ ] 在 `image_placement.py` 只对满足阈值的候选调用该接口；未配置视觉模型时保留人工复核状态。
- [ ] 重跑目标测试与全部 image placement 测试。
- [ ] 提交：`git add backend/python-worker/app/image_placement_multimodal.py backend/python-worker/app/image_placement.py backend/python-worker/tests/test_image_placement_multimodal.py .env.example && git commit -m "feat: add constrained image placement fallback"`

## Task 7: 在人工校验页显示阻断原因和归属差异

**Files:**
- Modify: `local-platform/src/pages/ImportWorkbenchTask.tsx`
- Modify: `local-platform/src/pages/ImportWorkbenchTask.test.tsx`
- Modify: `local-platform/src/services/domainApi.ts`

- [ ] 添加失败测试：存在 `blockingReasons` 时题卡显示“题图归属待复核”和机器码对应中文说明，入库按钮保持不可用。
- [ ] 添加失败测试：canonicalization preview 显示旧归属→新归属、置信度和 alternatives；无图片题不渲染空面板。
- [ ] 运行 `cd local-platform && npm test -- --run src/pages/ImportWorkbenchTask.test.tsx`，确认 RED。
- [ ] 扩展前端类型和已有题卡展示；只消费后端结果，不在前端重算标签或图片归属。
- [ ] 重跑目标测试，随后运行 `cd local-platform && npm test -- --run && npm run build`。
- [ ] 提交：`git add local-platform/src/pages/ImportWorkbenchTask.tsx local-platform/src/pages/ImportWorkbenchTask.test.tsx local-platform/src/services/domainApi.ts && git commit -m "feat: surface image placement review blockers"`

## Task 8: 文档、全量回归、服务器真实样本验收与发布

**Files:**
- Modify: `docs/product/OCR_PHASE_1_SPEC.md`
- Modify: `docs/architecture/TECHNICAL_DESIGN.md`
- Modify: `docs/architecture/ocr-flow.mmd`
- Modify: `docs/delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md`
- Modify: `docs/delivery/ACCEPTANCE.md`
- Modify: `docs/CHANGELOG.md`

- [ ] 更新 OCR、技术设计、接口、验收与变更记录，写明置信阈值、阻断机器码、人工 placement 保护和 canonicalization preview/apply 行为；若接口 schema 未变化，明确记录未修改 OpenAPI 的理由。
- [ ] 运行 Python 全量测试：`cd backend/python-worker && python -m pytest -q && python -m compileall -q app`。
- [ ] 运行 Java 全量测试：`cd backend && mvn test`。
- [ ] 运行前端全量测试和构建：`cd local-platform && npm test -- --run && npm run build`。
- [ ] 运行仓库契约与可移植性检查：`bash scripts/check-question-engine-contract.sh && bash scripts/check-portability.sh`。
- [ ] 用服务器任务 `import_task_20260713_011241_577801d8` 执行只读 canonicalization preview，验收第 4 题恢复 A–D 且四图分别归 A–D；第 6 题轮胎/骆驼/菜刀/图钉分别归 A/B/C/D；原任务在 apply 前不被修改。
- [ ] 对普通纯文字选择题、单题标准化和全局标准化各跑一组回归，确认结果逻辑一致；阻断题不得自动写回，稳定题仍走规则/缓存快速路径。
- [ ] 若任一真实样本失败，保存 preview 证据，按系统化调试流程新增失败测试后修复，并重复本任务全部验证命令。
- [ ] 提交文档和必要修复：`git add docs backend local-platform .env.example && git commit -m "docs: document layout-aware image placement"`（仅在有未提交文件时执行）。
- [ ] 将当前分支部署到 `$DEPLOY_DIR`，同步时排除 `.env`、`server-data`、构建缓存和本地依赖；使用现有服务器环境变量重建并启动 Docker Compose。
- [ ] 发布后检查容器健康、`/api/health`、前端页面、canonicalization preview 和上述第 4/6 题结果；记录镜像/提交版本和验证输出。
- [ ] 保留 `codex/image-placement-upgrade` 分支，不合并 `main`，不自动 apply 用户原任务数据。

## 完成标准

- 第 4 题和第 6 题的服务器只读 preview 均达到预期 A–D 映射。
- 明确四选一但选项不完整、几何缺失或一对一约束冲突时一律 `review_required`。
- 单题与全局标准化使用同一 request、快速路径和结构守卫。
- Python、Java、前端、契约与可移植性检查均以最新代码完整通过。
- 服务器运行当前分支版本，原任务数据未被自动覆盖，`main` 未合并。
