# 平台接入样例输入输出

本目录保存脱敏样卷、答案文件和预期 `question-package.v1` 输出，用于平台接入开发、SDK 示例和验收说明。

文件：

- `paper.md`：脱敏试卷。
- `answer.md`：脱敏答案。
- `expected-question-package.v1.json`：预期结构示例，不要求字段值与实际 OCR 完全一致，但字段形状必须一致。

使用：

```bash
python scripts/acceptance_question_engine_plugin.py \
  --base-url http://localhost:8018 \
  --paper-file docs/samples/platform-integration/paper.md \
  --answer-file docs/samples/platform-integration/answer.md
```
