# OCR 题图与选择题鲁棒性 OKR

## Objective

提升 OCR 导入后人工校验的结构稳定性，重点解决题图引用不同步、图片标签未规范化、AI 标准化破坏选择题结构的问题。

## Key Results

### KR1：题图引用模型稳定化

状态：完成

- 关联图片使用稳定 `图N` 标签。
- 删除图片后不自动重排剩余编号。
- 从「题图（关联图片）」移除图片时，同步清理题干、答案、解析、小问题干、小问答案和小问解析中的对应引用。

### KR2：OCR 初扫图片标签化

状态：完成

- OCR 结构化阶段把原始图片路径、API URL、文件名规范为 `![](图N)`。
- 有 OCR 位置时原位替换；没有可靠位置时追加到题干末尾并写入 warning。
- OCR 图片语法被换行拆成 `![]` + `(images/xxx.jpg)` 时也能识别为题图。
- 选择题选项图保留在对应 `options` / `tasks` 内容里，不作为题干缺失图片追加到题干顶部。

### KR3：AI 标准化选择题保护

状态：完成

- 标准化 prompt 明确要求保留 A/B/C/D 选项和图片选项。
- 后端结构闸门会在 AI 候选丢失选项时恢复原 OCR 结构化选项。
- 图片选项保留为 `![](图N)`。
- 前端打开历史数据、应用 AI 候选和保存前拆分 `tasks` 时，都会按当前关联图片把选项中的 raw 图片路径规范为 `![](图N)`。

### KR4：验证和文档闭环

状态：完成

- Python worker 全量测试通过：`72 passed`。
- 前端构建通过：`npm run build`。
- 契约检查通过：`python scripts/check_question_engine_contract.py`。
- 已更新 `docs/CHANGELOG.md`、`docs/delivery/ACCEPTANCE.md`、`docs/product/QUESTION_BANK_PHASE_2_SPEC.md` 和 `docs/architecture/ocr-flow.*`。
