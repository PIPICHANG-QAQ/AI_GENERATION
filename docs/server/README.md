# 服务器部署状态

本文记录 AIGeneration 项目在服务器上的实际部署状态、资源分配和关键约定。敏感信息不要写入本文，包括 SSH 密码、API Key、Authorization header 和平台密钥。

## 当前结论

- 当前服务器项目目录：`/home/user/AI_GENERATION_DOCKER`
- 当前 Compose 项目：`ai_generation_docker`
- 当前应用容器：`ai_generation_docker-question-engine-1`
- 不再使用旧目录：`/aa/AI_GENERATION_TOGO`
- 客户体验地址：`http://120.211.112.121:5173/`
- 无端口地址：`http://120.211.112.121/` 已在容器层映射，但公网 80 入站从外部访问会超时；服务器本机访问 80 正常，UFW 也已放行，疑似上游安全组或线路策略限制。
- 2026-07-10 已发布 OCR v15：结构契约拆题、首次返回前低置信自动标准化、布局解析框只读解耦和布局框低置信兜底已在容器内生效，健康检查通过。
- 2026-07-15 源码架构已增加 `Provider -> Adapter -> CanonicalOcrBundle -> Post Process` 边界；它不新增服务器端口。是否已部署必须以服务器当前 commit、`/api/capabilities/ocr-flow` 和 `docs/server/CHANGELOG.md` 的实际发布记录为准，不能仅根据源码文档推断。

## 服务器连接

```text
Host: 120.211.112.121
SSH user: user
SSH port: 3322
```

不要在文档、提交或脚本中记录 SSH 密码。

## 端口

| 端口 | 用途 | 说明 |
| --- | --- | --- |
| `5173` | 客户体验入口 | `0.0.0.0:5173 -> container:8080`，公网已验证可访问 |
| `80` | 无端口 HTTP 入口 | `0.0.0.0:80 -> container:8080`，服务器本机正常，公网入站可能被上游拦截 |
| `8018` | Java 后端直连 | `0.0.0.0:8018 -> container:8018`，主要用于调试 |
| `8000` | Python worker | 容器内 `127.0.0.1:8000`，不对公网暴露 |
| `8002` | 常驻 MinerU API | 容器内 `127.0.0.1:8002`，不对公网暴露 |

## GPU 分配

| 物理 GPU | 组件 | 说明 |
| --- | --- | --- |
| GPU0 | AI_GENERATION / MinerU OCR | AIGeneration 容器只暴露物理 GPU0；容器内 `CUDA_VISIBLE_DEVICES=0` |
| GPU1 | vLLM / `aux-qwen3-32b-fp8` | 本地辅助大模型独立运行，避免和 OCR 抢显存 |

关键环境变量：

```text
NVIDIA_VISIBLE_DEVICES=0
OCR_CUDA_VISIBLE_DEVICES=0
CUDA_VISIBLE_DEVICES=0
MINERU_VIRTUAL_VRAM_SIZE=48
MINERU_HYBRID_BATCH_RATIO=16
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,max_split_size_mb:512
```

## MinerU 加速状态

当前 MinerU 已改为常驻 API 模式：

```text
MINERU_COMMAND=/home/user/AI_GENERATION_DOCKER/vendor/mineru-venv/bin/mineru
MINERU_API_ENABLED=true
MINERU_API_COMMAND=/home/user/AI_GENERATION_DOCKER/vendor/mineru-venv/bin/mineru-api
MINERU_API_HOST=127.0.0.1
MINERU_API_PORT=8002
MINERU_API_URL=http://127.0.0.1:8002
MINERU_API_MAX_CONCURRENT_REQUESTS=1
MINERU_API_ENABLE_VLM_PRELOAD=false
```

应用调用 MinerU 时会追加：

```bash
--api-url http://127.0.0.1:8002
```

这样避免每个 OCR 任务都重新启动 MinerU FastAPI 服务和重新初始化模型。

## 模型缓存

模型缓存已持久化：

```text
Host:      /home/user/AI_GENERATION_DOCKER/server-data/modelscope-cache
Container: /root/.cache/modelscope
```

当前验证过的缓存大小约 `782MB`。容器重建后不应重新下载/校验全部 ModelScope 模型文件。

## ONNX GPU 状态

服务器 MinerU venv 已安装：

```text
onnxruntime-gpu==1.23.2
```

容器内验证 provider：

```text
TensorrtExecutionProvider
CUDAExecutionProvider
CPUExecutionProvider
```

日志中可能仍出现 `device_discovery` warning；只要 `CUDAExecutionProvider` 存在，就不等于 CPU-only。

## 性能验证

优化前，最近 OCR provider 阶段耗时：

| 样本 | 优化前 |
| --- | --- |
| 单页图片 | 约 `147s` |
| 4 页 PDF | 约 `157s` |

常驻 MinerU API + ONNX GPU provider 后验证：

| 样本 | 优化后 |
| --- | --- |
| 单页图片 | 约 `9s` |
| 4 页 PDF | 约 `12.4s` |

第一次启动常驻 `mineru-api` 后仍会有一次模型初始化，日志中曾记录 `model init cost` 约 `137s`。预热完成后，后续 OCR 任务复用常驻服务，不再为每个任务重复初始化。

## AI 边界确认并发

服务器 AI 边界确认仍默认走外部满血模型：

```text
LLM_ROUTER_MODE=hybrid
LOCAL_LLM_ENABLED=true
LOCAL_LLM_MODEL=aux-qwen3-32b-fp8
DASHSCOPE_MODEL=deepseek-v4-pro
```

边界确认分片并发配置：

```text
LLM_BOUNDARY_CHUNK_SIZE=5
LLM_BOUNDARY_MAX_CONCURRENCY=4
LLM_EXTERNAL_MAX_CONCURRENCY=4
```

设计约定：

- 先用本地规则生成题目候选边界和全文绝对 offset。
- 每个 chunk 按题目候选边界切分，不按裸字符硬切。
- 默认 20 道题拆为 4 个 chunk，每个 chunk 约 5 道题。
- chunk 内发送局部 Markdown 和局部候选边界，模型只确认边界，不生成题干正文。
- 模型返回后恢复到全文绝对 offset，再按 offset 合并。
- 单个 chunk 失败时，只回退该 chunk 的本地边界，不回退整份试卷。
- 合并后仍执行结构校验、图片引用校验和证据回溯。

## OCR 自动标准化与布局解析框

当前服务器启用：

```text
OCR_AUTO_STANDARDIZE_MODE=risky
OCR_AUTO_STANDARDIZE_MAX_CONCURRENCY=2
OCR_PAPER_LAYOUT_ENABLED=true
```

约定：

- 自动标准化只在首次 OCR 生成导入题目时处理低置信题，不创建 Java AI job。
- 候选必须通过渲染、严重风险、选项、题图和小问结构硬校验后才写回；失败时保留原题并写入 `autoStandardize` 元数据。
- 布局解析框只用于左侧原文件定位，不参与题目拆分、题图归属或人工编辑稿生成。
- 如果布局框不稳定，可先把 `.env` 中 `OCR_PAPER_LAYOUT_ENABLED=false` 后重建容器；题目识别能力仍应稳定运行。
- 当前布局框绑定已支持 MinerU `_middle.json` 嵌套图片路径，并跳过 `A/B/C/D` 短选项标签作为 offset 锚点，避免图片选择题串框到下一题。

## 相关文件

- `docker-compose.server.yml`
- `.env.example`
- `scripts/docker-entrypoint.sh`
- `backend/python-worker/app/ocr_flow.py`
- `docs/architecture/ocr-flow.mmd`
- `docs/architecture/server-ocr-flow.mmd`
- `docs/delivery/OPERATIONS_GUIDE.md`
