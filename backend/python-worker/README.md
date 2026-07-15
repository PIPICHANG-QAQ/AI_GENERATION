# Python Worker

本目录只保留 Java 主后端必须调用的 Python 执行能力。

## 本地虚拟环境

`backend/python-worker/.venv` 只属于当前机器，不能随源码或交付包复制到其它电脑。venv 内的 `bin/python` 以及 `mineru`、`uvicorn` 等脚本会记录创建机器上的绝对路径；跨用户或跨目录复用后会报 `no such file or directory`。

新机器上应重新执行：

```bash
./scripts/install_backend.sh
./scripts/install_mineru.sh
python scripts/check_mineru.py
```

安装脚本会检测不可用的 `.venv` 并自动重建。MinerU 不作为源码内置二进制交付，而是安装进目标机器自己的 Python worker venv。

`check_mineru.py` 的 `installed=true` 表示 OCR provider 的可执行入口可用，且已用该入口同一环境的 Python 通过深度运行时导入探测（`runtimeProbeOk=true`）。`--version` 仅提供兼容性信息；即使它超时并显示 `version=null`、`versionProbeOk=false`，只要运行时探测健康，OCR 仍可用。

## 保留能力

- OCR provider 调用、provider adapter 和统一 OCR 证据包。
- Provider-neutral Post Process：拆题、选项/小问恢复、题图归属、公式与结构校验。
- 大模型拆题、AI 标准化和 AI 解析。
- LaTeX/Markdown 公式处理。
- Pandoc/XeLaTeX DOCX/PDF 渲染。
- 短期兼容 Java bridge 仍需调用的导入任务接口。

## 模块说明

- `app/main.py`：极薄 FastAPI 入口，只导入共享 app 并注册路由。
- `app/worker_base.py`：共享配置、路径、模型和轻量 JSON 兼容存储。
- `app/question_markdown.py`：题目 Markdown、题图和选项归一化。
- `app/ocr/contracts.py`：`canonical-ocr-bundle.v1` 输入契约和强校验。
- `app/ocr/mineru_adapter.py`：MinerU 私有工件到统一证据包的唯一适配器。
- `app/ocr/postprocess_pipeline.py`：统一后处理入口，保持现有算法和 outputs 兼容。
- `app/ocr_processing.py`：现有 OCR 后处理算法兼容实现；新 provider 不得直接依赖其内部细节。
- `app/import_services.py`：导入任务兼容桥和入库辅助。
- `app/export_service.py`：试卷 Markdown/DOCX/PDF 渲染。
- `app/ocr_execution.py`：OCR job 执行。
- `app/worker_routes.py`：Java 仍需调用的 worker 和兼容路由。

新增平台业务逻辑不得放入 Python worker。

## OCR Provider 与 Post Process

当前执行链路为：

```text
OcrProvider -> provider adapter -> CanonicalOcrBundle -> OcrPostProcessingPipeline -> outputs
```

新 provider 必须输出 `canonical-ocr-bundle.v1`，并在当前兼容期提供已存在的只读 `artifactRoot`；所有声明的 Markdown、JSON、asset 和 native artifact 路径都必须是 root 内真实存在的相对文件。显式 bundle 只消费声明的 Markdown、assets、layoutBlocks、pages 和 sourceDocumentRef，不扫描 root 中的 provider 私有文件名；视觉 crop 写入 `PYTHON_WORKER_STORAGE_ROOT/postprocess/job-<sha256(documentId)>`，不把 provider 控制的 documentId 用作路径组件，也不写回工件目录。稳定 Python 导入入口是 `app.ocr`；完整字段、示例、能力等级和测试门禁见 [OCR Post Process 使用说明书](../../docs/delivery/POST_PROCESS_USAGE_GUIDE.md)。

当前入口属于同一 worker 进程内的嵌入式能力，不是无状态公网 API。平台远程调用继续使用 Question Engine OpenAPI/SDK。

## Legacy API 边界

`worker_routes.py` 中仍保留一批 `/api/*` 路由，用于本地小平台和 Java bridge 平滑迁移。这些路由属于兼容桥，不是平台正式集成面：

- 新能力必须优先进入 Java `backend/src/main/java`。
- 平台集成必须优先使用 `/api/capabilities/*`、`/api/engine` 和 OpenAPI/SDK。
- Python 新增接口应使用 `/worker/*` 前缀，只表达 OCR、AI、公式处理或导出执行能力。
- 当 Java 已完全接管对应业务状态后，兼容 `/api/*` 路由应逐步删除。
