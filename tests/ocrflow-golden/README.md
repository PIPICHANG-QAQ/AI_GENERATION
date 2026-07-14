# OCR Flow golden corpus

本目录冻结 OCR Flow 的结构兼容基线。比较器只忽略明确的时变值，不改变题目、选项、图片、题图归属、warning、validation 或数组顺序。

## 已提交样例

`manifest.json` 登记同一份脱敏 Markdown paper/answer、raw `processing-job.json` replay input 和冻结 expected。`runner` 必须显式为 `java-question-processing`。

runner 是测试范围 Java harness `OcrFlowReplayRunnerTest`。Python 为所有 case 生成一次批量请求，Maven harness 读取 raw Java 持久化快照、构造现有仓储边界，并现场调用生产 `QuestionProcessingCapabilityService` 生成 candidate。Python 不实现题目转换算法，也不把 expected 当 candidate。runner 未配置、Maven 失败、candidate 缺失或非法时均非零退出。

这是“当前 Java 聚合实现的确定性 replay”，不调用外部 OCR/LLM provider。完整生产链 fixture 可用后，必须新增调用真实无状态入口的 runner 类型，不能退回静态 candidate 文件。

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

两种 compare 模式互斥。`--release` 只允许用于 manifest/capture 受控模式，不能用于 baseline/candidate pair。缺参数、混用模式、无效 manifest、无效 JSON、runner 失败或发布 corpus 不完整均返回非零。标准输出始终为 JSON；`differences` 的 key 是精确路径，例如 `questions[0].options[0].content`。

归一化字段固定为 `createdAt`、`updatedAt`、`startedAt`、`finishedAt` 和 `traceId`。随机 ID 仅由 manifest 或受控 case 的 `randomIdPaths` 显式配置；路径支持中间层 `[*]` 数组通配，例如 `questions[*].questionId`。空路径、根路径、语法错误、未命中路径，以及解析到 dict/list 容器的路径均 fail-closed。未配置的 `jobId`、题目 ID 或图片 ID 不会被忽略。

## 受控真实样卷

敏感或受控样卷不提交到 Git。通过只读的 `OCRFLOW_GOLDEN_ROOT` 提供，每个一级子目录是一份 case：

```text
<case-id>/
  case.json
  paper/                         至少一个文件
  answer/                        可选；存在时至少一个文件
  provider-output/               至少一个 raw replay input
  expected/question-package.json
```

`case.json` 格式：

```json
{
  "schemaVersion": "ocrflow-controlled-case.v1",
  "id": "case-id-must-equal-directory-name",
  "runner": "java-question-processing",
  "replayInput": "provider-output/processing-job.json",
  "randomIdPaths": ["job.jobId"],
  "features": ["option-images", "formula"],
  "sha256": {
    "paper/paper.pdf": "64 lowercase hexadecimal characters",
    "provider-output/processing-job.json": "64 lowercase hexadecimal characters",
    "expected/question-package.json": "64 lowercase hexadecimal characters"
  }
}
```

`replayInput` 必须位于 `provider-output/` 下，且不能与 expected 是同一路径或相同 SHA-256。`sha256` 必须逐一列出除 `case.json` 外的所有文件，不能缺少或多报。验证器重新计算每个文件的 SHA-256，并要求至少 20 个 case。整个 corpus 必须覆盖以下 feature slug：

- `option-images`
- `cross-page-options`
- `composite-questions`
- `child-question-images`
- `answer-duplicate-questions`
- `tables`
- `two-column`
- `formula`
- `header-noise`

本地未设置 `OCRFLOW_GOLDEN_ROOT` 时，受控 corpus 检查明确标记为 skipped；若设置根目录，每个 case 都与仓库 case 走同一 runner。发布验收必须给命令增加 `--release`，此时缺目录、少于 20 份、结构不完整、覆盖不足、哈希不符、runner 失败或 candidate/expected 任意逐路径差异都会失败，不能跳过：

```bash
OCRFLOW_GOLDEN_ROOT=/read-only/corpus \
  python3 scripts/ocrflow_golden.py compare \
  --manifest tests/ocrflow-golden/manifest.json \
  --release
```

`gates.json` 只冻结 accuracy gate 和 Task 2 将使用的性能指标 schema；本任务不执行性能 benchmark，也不定义性能阈值。
