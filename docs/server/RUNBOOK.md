# 服务器运维 Runbook

本文记录服务器部署的常用检查、重启、验证和排障命令。命令默认在服务器上执行。

## 进入项目目录

```bash
cd /home/user/AI_GENERATION_DOCKER
```

## 查看容器状态

```bash
sudo docker compose -f docker-compose.server.yml ps
sudo docker inspect -f '{{.State.Health.Status}}' ai_generation_docker-question-engine-1
```

期望：

```text
healthy
```

## 重建并启动服务

```bash
cd /home/user/AI_GENERATION_DOCKER
JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-17-openjdk-amd64}" mvn -f backend/pom.xml clean -DskipTests package
npm --prefix local-platform ci && npm --prefix local-platform run build
sudo docker compose -f docker-compose.server.yml build question-engine
sudo docker compose -f docker-compose.server.yml up -d --force-recreate question-engine
sudo docker compose -f docker-compose.server.yml ps
```

重建后需要确认 `mineru-api` 常驻进程仍在。

## 原子重建 MinerU venv

服务器 venv 必须在服务器上联网解析 Linux 制品，不设置 `MINERU_WHEELHOUSE`，也不使用本地 macOS wheelhouse。切换期间必须停止 `question-engine` 容器；只有 active venv 的 readiness 和版本检查都成功后才能重启：

```bash
cd /home/user/AI_GENERATION_DOCKER
set -euo pipefail

sudo docker compose -f docker-compose.server.yml stop question-engine
sudo docker compose -f docker-compose.server.yml ps

python3 scripts/rebuild_mineru_venv.py \
  --target /home/user/AI_GENERATION_DOCKER/vendor/mineru-venv \
  --python /usr/bin/python3 \
  --mineru-version 3.4.2 \
  --check-script /home/user/AI_GENERATION_DOCKER/scripts/check_mineru.py \
  --keep-backups 2 \
  --keep-failed-staging 2

python3 /home/user/AI_GENERATION_DOCKER/scripts/rebuild_mineru_venv.py \
  --verify-only \
  --target /home/user/AI_GENERATION_DOCKER/vendor/mineru-venv \
  --mineru-version 3.4.2 \
  --check-script /home/user/AI_GENERATION_DOCKER/scripts/check_mineru.py

sudo docker compose -f docker-compose.server.yml up -d question-engine
sudo docker compose -f docker-compose.server.yml ps
```

安装、staging 验证、active 复验或严格版本检查失败时，`set -e` 会阻止容器启动。脚本保留本次失败 staging 供诊断；若切换后复验失败，会把新环境移回原 staging 路径并恢复旧 active（如果旧 active 存在）。`--keep-failed-staging` 必须至少为 `1`，默认保留最近 2 个：每次新尝试前先清理旧失败 staging，为本次诊断目录预留一个名额；成功验收后再次收敛到指定数量。

安全查看失败 staging：

```bash
find /home/user/AI_GENERATION_DOCKER/vendor -maxdepth 1 -type d \
  -name 'mineru-venv.new-*' -print
```

显式删除前必须填写并复核一个绝对路径，同时确认它是严格匹配名称的常规目录而不是 symlink：

```bash
failed="/home/user/AI_GENERATION_DOCKER/vendor/mineru-venv.new-REPLACE_WITH_EXACT_SUFFIX"
test "$(dirname -- "$failed")" = "/home/user/AI_GENERATION_DOCKER/vendor"
case "$(basename -- "$failed")" in
  mineru-venv.new-?*) ;;
  *) echo "拒绝删除非 MinerU staging 路径: $failed" >&2; exit 1 ;;
esac
test ! -L "$failed"
test -d "$failed"
rm -rf -- "$failed"
```

## 回滚 MinerU venv

先从本次重建记录中选择经过验收的精确 backup 路径，替换下面示例时间戳；不得用 `find | sort | tail` 猜测最新目录。回滚同样必须先停容器，readiness 成功后才重启：

```bash
cd /home/user/AI_GENERATION_DOCKER
set -euo pipefail

backup="/home/user/AI_GENERATION_DOCKER/vendor/mineru-venv.bak-20260715T120000.000000Z-xxxxxxxx"
test -d "$backup"
test ! -L "$backup"

sudo docker compose -f docker-compose.server.yml stop question-engine
sudo docker compose -f docker-compose.server.yml ps

if /home/user/AI_GENERATION_DOCKER/scripts/rollback_mineru_venv.sh \
  --target /home/user/AI_GENERATION_DOCKER/vendor/mineru-venv \
  --backup "$backup" \
  --check-script /home/user/AI_GENERATION_DOCKER/scripts/check_mineru.py \
  --rebuild-script /home/user/AI_GENERATION_DOCKER/scripts/rebuild_mineru_venv.py \
  --mineru-version 3.4.2; then
  sudo docker compose -f docker-compose.server.yml up -d question-engine
  sudo docker compose -f docker-compose.server.yml ps
else
  echo "回滚失败；保持 question-engine 停止，并按 helper 输出的 prior/rejected 路径人工检查。" >&2
  exit 1
fi
```

helper 内部调用 `rebuild_mineru_venv.py --verify-only`，同时执行 readiness 和严格的 MinerU `3.4.2` 版本校验。只有 helper 返回 `0` 才启动容器；候选校验失败时，helper 会将坏候选移到唯一的 rejected 路径并恢复 prior active。任何失败都保持容器停止，并按输出的 prior/rejected 路径处理，不得启动未验证候选。

## 健康检查

服务器本机：

```bash
curl -fsS http://127.0.0.1:5173/api/java/health
curl -fsS http://127.0.0.1/api/java/health
```

公网：

```bash
curl --noproxy '*' -fsS http://120.211.112.121:5173/api/java/health
```

检查 provider/Post Process 契约是否随当前版本发布：

```bash
curl -fsS http://127.0.0.1:5173/api/capabilities/ocr-flow \
  | python3 -m json.tool \
  | grep -E 'outputSchema|inputSchema|outputCompatibility'
```

期望包含 `canonical-ocr-bundle.v1` 和 `legacy-collect-outputs`。若缺失，表示服务器仍运行旧能力描述；这不等同于 OCR 失败，但需要按发布流程重建镜像后再做 provider 替换验收。

## 验证导入工作台 v15

选择一个已存在导入任务 ID 后执行：

```bash
TASK_ID="<import_task_id>"
curl -fsS "http://127.0.0.1:5173/api/import-tasks/${TASK_ID}" \
  | python3 -m json.tool | grep -E '"status"|"paperOcrStatus"|"answerOcrStatus"' | head -20
curl -i -X POST "http://127.0.0.1:5173/api/import-tasks/${TASK_ID}/rescan"
curl -fsS "http://127.0.0.1:5173/api/import-tasks/${TASK_ID}" \
  | python3 -m json.tool | grep -E '"status"|"paperOcrStatus"|"answerOcrStatus"' | head -20
```

期望：

- 首次重扫返回 `200`，任务和 OCR 状态进入 `处理中`。
- 处理中重复调用 `/rescan` 返回 `409`。
- 页面工具栏中“重新 OCR 扫描”“AI 解析全部”“批量入库”禁用，并随详情轮询自动恢复。
- 当前题目列表和人工编辑内容不因重扫被清空或覆盖。
- 任务详情中的 `paperLayout.capability.mode` 为 `question-region-binding`；若 `OCR_PAPER_LAYOUT_ENABLED=false`，`paperLayout.regions=[]` 且 warning 为“布局解析框已关闭”。
- 首次 OCR 生成题目后，任务或题目可见 `autoStandardize` 元数据；低置信题若被阻断，应保留原题并记录 `blockReason`，不应清空题干或选项。

检查当前 OCR v15 开关：

```bash
sudo docker exec ai_generation_docker-question-engine-1 sh -lc '
env | grep -E "^(OCR_PAPER_LAYOUT_ENABLED|OCR_AUTO_STANDARDIZE_MODE|OCR_AUTO_STANDARDIZE_MAX_CONCURRENCY)=" | sort
'
```

期望客户体验环境为：

```text
OCR_AUTO_STANDARDIZE_MAX_CONCURRENCY=2
OCR_AUTO_STANDARDIZE_MODE=risky
OCR_PAPER_LAYOUT_ENABLED=true
```

布局框排障优先级：

1. 如果题目识别正确但左侧框错误，先确认这是布局绑定问题，不要回滚拆题链路。
2. 临时保障用户测试时，可在 `.env` 设置 `OCR_PAPER_LAYOUT_ENABLED=false` 后重建容器，只关闭定位框。
3. 排查 `_middle.json` 是否包含嵌套 `image_path`，以及是否只命中 `A/B/C/D` 短选项标签或极小 bbox。
4. 修复后必须重新验证图片选择题和含公式字母 `A/B/C/D` 的下一题，防止布局框串题。

## 检查端口

```bash
ss -ltnp | grep -E ':(80|5173|8018) '
```

期望：

```text
0.0.0.0:80
0.0.0.0:5173
0.0.0.0:8018
```

如果公网 `80` 端口不通但服务器本机 `127.0.0.1:80` 正常，优先检查云控制台安全组、机房防火墙或线路策略。

## 检查 GPU 分配

宿主机：

```bash
nvidia-smi --query-gpu=index,name,memory.total,memory.used,utilization.gpu --format=csv,noheader
nvidia-smi pmon -c 1 -s um
```

容器内：

```bash
sudo docker exec ai_generation_docker-question-engine-1 nvidia-smi --query-gpu=index,name,memory.total,memory.used,utilization.gpu --format=csv,noheader
sudo docker exec ai_generation_docker-question-engine-1 sh -lc 'env | grep -E "^(NVIDIA_VISIBLE_DEVICES|CUDA_VISIBLE_DEVICES|OCR_CUDA_VISIBLE_DEVICES|MINERU_)" | sort'
```

期望：

- 容器只看到一张 RTX 4090。
- 容器内 `NVIDIA_VISIBLE_DEVICES=0`。
- 宿主机 GPU0 出现 MinerU/Python 进程。
- 宿主机 GPU1 出现 vLLM 进程。

## 检查常驻 MinerU API

```bash
sudo docker exec ai_generation_docker-question-engine-1 sh -lc '
ps -ef | grep -E "mineru-api|fast_api" | grep -v grep || true
ss -ltnp | grep :8002 || true
curl -fsS http://127.0.0.1:8002/docs >/dev/null && echo mineru_api_docs_ok
'
```

期望：

```text
mineru-api ... --host 127.0.0.1 --port 8002
127.0.0.1:8002
mineru_api_docs_ok
```

## 检查 ONNX GPU provider

```bash
sudo docker exec ai_generation_docker-question-engine-1 sh -lc '
/home/user/AI_GENERATION_DOCKER/vendor/mineru-venv/bin/python - <<'"'"'PY'"'"'
import onnxruntime as ort
print(ort.__version__)
print(ort.get_available_providers())
PY
'
```

期望至少包含：

```text
CUDAExecutionProvider
```

如果只剩 `CPUExecutionProvider`，需要重新检查服务器 venv 中的 `onnxruntime-gpu` 安装。

## 检查模型缓存挂载

```bash
du -sh /home/user/AI_GENERATION_DOCKER/server-data/modelscope-cache
sudo docker exec ai_generation_docker-question-engine-1 du -sh /root/.cache/modelscope
```

两边大小应接近。若宿主机目录为空，容器重建后可能再次下载模型。

## MinerU 预热

容器重启后，第一次 OCR 可能触发模型加载。可手动预热：

```bash
sudo docker exec ai_generation_docker-question-engine-1 sh -lc '
rm -rf /tmp/mineru-warmup
time /home/user/AI_GENERATION_DOCKER/vendor/mineru-venv/bin/mineru \
  -p "/data/import_uploads/ocr_20260708_023144_2ad6e4db/Weixin Image_20260708103053_2147_3860.png" \
  -o /tmp/mineru-warmup \
  -b pipeline \
  --api-url http://127.0.0.1:8002
'
```

预热后，同类单页图片样本应在约 `9s` 完成，4 页 PDF 样本约 `12s` 完成。

## 查看 OCR/MinerU 日志

```bash
sudo docker logs --since 30m ai_generation_docker-question-engine-1 2>&1 \
  | grep -Ei 'mineru|api-url|model init|Start MinerU|CUDAExecutionProvider|Completed batch|ocr-provider' \
  | tail -n 160
```

判断标准：

- 容器启动时出现 `Start MinerU FastAPI Service: http://127.0.0.1:8002` 是正常的。
- OCR 任务不应再出现每个任务启动临时随机端口 MinerU API。
- 如果每个任务仍然出现 `Start MinerU FastAPI Service: http://127.0.0.1:<random>`，说明应用没有带 `--api-url` 或 `MINERU_API_URL` 未生效。

## 检查 AI 边界确认并发

```bash
sudo docker exec ai_generation_docker-question-engine-1 sh -lc '
env | grep -E "^(LLM_BOUNDARY_CHUNK_SIZE|LLM_BOUNDARY_MAX_CONCURRENCY|LLM_EXTERNAL_MAX_CONCURRENCY)=" | sort
'
```

期望服务器客户体验环境为：

```text
LLM_BOUNDARY_CHUNK_SIZE=5
LLM_BOUNDARY_MAX_CONCURRENCY=4
LLM_EXTERNAL_MAX_CONCURRENCY=4
```

查看最近 OCR job 的边界确认调用：

```bash
python3 - <<'PY'
import json, pathlib, itertools
jobs = sorted(pathlib.Path("server-data/jobs").glob("ocr_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
for p in itertools.islice(jobs, 5):
    d = json.loads(p.read_text())
    splitter = (d.get("outputs") or {}).get("splitter") or {}
    calls = splitter.get("llmCalls") or []
    if calls:
        print(p.name, "chunkCount=", splitter.get("chunkCount"), "maxConcurrency=", splitter.get("maxConcurrency"))
        for call in calls:
            print(" ", call.get("chunkIndex"), call.get("route"), call.get("provider"), call.get("model"), call.get("status"), call.get("durationMs"))
PY
```

如果 `maxConcurrency` 仍为 `1`，优先检查 `.env` 和容器环境变量是否被旧配置覆盖。如果 `maxConcurrency=4` 但调用仍串行，检查 `LLM_EXTERNAL_MAX_CONCURRENCY` 是否仍为 `1`。

## 配置备份

## 检查全局标准化并发

```bash
sudo docker exec ai_generation_docker-question-engine-1 sh -lc '
env | grep -E "^(AI_STANDARDIZATION_MAX_CONCURRENCY|LLM_STANDARDIZE_(INITIAL|MIN|MAX)_CONCURRENCY|LLM_EXTERNAL_MAX_CONCURRENCY)=" | sort
'
```

默认值：

```text
AI_STANDARDIZATION_MAX_CONCURRENCY=12
LLM_EXTERNAL_MAX_CONCURRENCY=8
LLM_STANDARDIZE_INITIAL_CONCURRENCY=4
LLM_STANDARDIZE_MIN_CONCURRENCY=2
LLM_STANDARDIZE_MAX_CONCURRENCY=8
```

Java 的12表示可并行推进的题目预处理窗口，不是模型并发。真实标准化模型并发由 worker 在2到8之间自适应控制。

模型网关持续出现429、503或超时时，可临时固定为2并重建容器：

```text
LLM_STANDARDIZE_INITIAL_CONCURRENCY=2
LLM_STANDARDIZE_MIN_CONCURRENCY=2
LLM_STANDARDIZE_MAX_CONCURRENCY=2
LLM_EXTERNAL_MAX_CONCURRENCY=2
```

任务详情中的 `rulesCount + ocrFallbackCount + cacheHitCount + llmQuestionCount` 用于核对执行路径；`providerCallAttempts` 包含重试，不能当作题目数。

每次修改 `.env` 前先备份：

```bash
cp .env .env.bak_$(date +%Y%m%d_%H%M%S)
```

不要把真实 `.env`、SSH 密码或 API Key 写入文档或提交。
