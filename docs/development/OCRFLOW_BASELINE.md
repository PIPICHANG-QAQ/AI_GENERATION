# OCR Flow 基线、调用次数与门禁

`scripts/benchmark_ocrflow.py` 只负责采集和比较指标，不改变 OCR、标准化、解析或路由实现。默认 `baseline` 使用 Task 1 的 Java replay runner，因此结构比较不受模型波动影响；真实 live 基线必须由 CI/运维提供固定 provider、模型版本和进程采样来源，不能在发布现场临时录制。

## 工作流

```bash
ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"
python3 scripts/benchmark_ocrflow.py baseline \
  --manifest tests/ocrflow-golden/manifest.json \
  --runs 5 \
  --output .artifacts/ocrflow-baseline/current.json

python3 scripts/benchmark_ocrflow.py archive \
  --input .artifacts/ocrflow-baseline/current.json \
  --store-root "$OCRFLOW_BASELINE_PUBLISH_ROOT" \
  --ref tests/ocrflow-performance/baseline-ref.json \
  --golden-manifest-sha "$(shasum -a 256 tests/ocrflow-golden/manifest.json | awk '{print $1}')"

python3 scripts/benchmark_ocrflow.py restore \
  --ref tests/ocrflow-performance/baseline-ref.json \
  --store-root "$OCRFLOW_BASELINE_READ_ROOT" \
  --output .artifacts/ocrflow-baseline/restored.json

python3 scripts/benchmark_ocrflow.py compare \
  --baseline .artifacts/ocrflow-baseline/restored.json \
  --candidate .artifacts/ocrflow-baseline/current.json \
  --gates tests/ocrflow-golden/gates.json
```

`OCRFLOW_BASELINE_PUBLISH_ROOT` 必须是只追加制品目录，`OCRFLOW_BASELINE_READ_ROOT` 必须是只读挂载；缺少任一目录、引用 SHA 不匹配、manifest 指纹不匹配或基线仍为 pending 均失败。不能根据时间猜测“最近一次”基线。

## 指标语义

- `p50Ms`、`p95Ms`：每个 case 的端到端 replay wall time。
- `throughputPerMinute`：该批次运行数除以总 wall time。
- `peakRssMb`：replay 子进程的系统资源峰值；live 服务必须改用显式 PID/容器采样，不可把 CLI 自身内存当服务内存。
- `ocrProviderCalls`、`llmProviderCalls`、`cacheHits`：来自 replay 输出的明确计数；无法确定时为 0 仅适用于 replay，live 采集必须 fail-closed。
- `normalizedContentDiff`：与黄金包的归一化结构差异数，必须为 0。

门禁阈值冻结在 `tests/ocrflow-golden/gates.json`：性能 warning 不阻断，failure 或 provider 调用增加会阻断；结构差异始终阻断。

## Router 回归说明

当前生产代码、单元测试和离线执行均表明 `boundary-refine` 的 hybrid 路由为 external-only；仓库旧回归脚本中期待 `local → external` 的断言是过期预期。是否恢复 local-first 必须由线上提交、环境和准确率证据决定，不能为通过旧脚本修改生产路由。
