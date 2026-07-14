# OCR Flow golden corpus

本目录冻结 OCR Flow 的结构兼容基线。比较器只忽略明确的时变值，不改变题目、选项、图片、题图归属、warning、validation 或数组顺序。

## 已提交样例

`manifest.json` 登记脱敏的 Markdown paper/answer、平台接入 expected，以及 Java 兼容测试通过当前 `QuestionProcessingCapabilityService` 生成并冻结的 aggregate replay。

当前仓库没有可离线调用完整 OCR/AI 生产链的 provider-output replay。因而 `replayMode: captured-aggregate` 表示：

- `capture --mode replay` 捕获的是已冻结的当前 Java 聚合产物；
- `compare --manifest` 将该产物与 manifest 的 expected 做严格比较；
- 命令不会调用 OCR/LLM，也不会把 expected 复制成“当前实现”；
- `docs/samples/platform-integration/expected-question-package.v1.json` 原本是结构示例，若与当前聚合契约不同，manifest compare 会如实返回非零和逐路径 diff。

完整生产链 replay 在获得真实 provider-output fixture 后，应把 `providerOutput` 指向该链路的真实重放产物，并保留相同严格比较语义。

## 命令

```bash
python3 scripts/ocrflow_golden.py capture \
  --manifest tests/ocrflow-golden/manifest.json \
  --mode replay \
  --output .artifacts/ocrflow-golden/baseline.json

python3 scripts/ocrflow_golden.py compare \
  --baseline .artifacts/ocrflow-golden/baseline.json \
  --candidate .artifacts/ocrflow-golden/baseline.json

python3 scripts/ocrflow_golden.py compare \
  --manifest tests/ocrflow-golden/manifest.json
```

两种 compare 模式互斥。缺参数、混用模式、无效 manifest、无效 JSON 或发布 corpus 不完整均返回非零。标准输出始终为 JSON；`differences` 的 key 是精确路径，例如 `questions[0].options[0].content`。

归一化字段固定为 `createdAt`、`updatedAt`、`startedAt`、`finishedAt` 和 `traceId`。随机 ID 仅由 manifest 的 `randomIdPaths` 显式配置；路径支持 `[*]` 数组通配，例如 `questions[*].questionId`。未配置的 `jobId`、题目 ID 或图片 ID 不会被忽略。

## 受控真实样卷

敏感或受控样卷不提交到 Git。通过只读的 `OCRFLOW_GOLDEN_ROOT` 提供，每个一级子目录是一份 case：

```text
<case-id>/
  case.json
  paper/                         至少一个文件
  answer/                        可选；存在时至少一个文件
  provider-output/               至少一个真实 replay 文件
  expected/question-package.json
```

`case.json` 格式：

```json
{
  "schemaVersion": "ocrflow-controlled-case.v1",
  "id": "case-id-must-equal-directory-name",
  "features": ["option-images", "formula"],
  "sha256": {
    "paper/paper.pdf": "64 lowercase hexadecimal characters",
    "provider-output/question-package.json": "64 lowercase hexadecimal characters",
    "expected/question-package.json": "64 lowercase hexadecimal characters"
  }
}
```

`sha256` 必须逐一列出除 `case.json` 外的所有文件，不能缺少或多报。验证器重新计算每个文件的 SHA-256，并要求至少 20 个 case。整个 corpus 必须覆盖以下 feature slug：

- `option-images`
- `cross-page-options`
- `composite-questions`
- `child-question-images`
- `answer-duplicate-questions`
- `tables`
- `two-column`
- `formula`
- `header-noise`

本地未设置 `OCRFLOW_GOLDEN_ROOT` 时，受控 corpus 检查明确标记为 skipped；发布验收必须给命令增加 `--release`，此时缺目录、少于 20 份、结构不完整、覆盖不足或哈希不符都会失败，不能跳过：

```bash
OCRFLOW_GOLDEN_ROOT=/read-only/corpus \
  python3 scripts/ocrflow_golden.py compare \
  --manifest tests/ocrflow-golden/manifest.json \
  --release
```

`gates.json` 只冻结 accuracy gate 和 Task 2 将使用的性能指标 schema；本任务不执行性能 benchmark，也不定义性能阈值。
