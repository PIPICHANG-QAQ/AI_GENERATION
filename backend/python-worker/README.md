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

`check_mineru.py` 的 `installed=true` 表示 OCR provider 已发现可执行入口。部分 MinerU 版本的 `--version` 启动较慢，可能显示 `version=null`、`versionProbeOk=false`；这只表示版本探测超时，不表示 OCR 入口不可用。

## 保留能力

- OCR provider 调用和 OCR 产物收集。
- 大模型拆题、AI 标准化和 AI 解析。
- LaTeX/Markdown 公式处理。
- Pandoc/XeLaTeX DOCX/PDF 渲染。
- 短期兼容 Java bridge 仍需调用的导入任务接口。

## 模块说明

- `app/main.py`：极薄 FastAPI 入口，只导入共享 app 并注册路由。
- `app/worker_base.py`：共享配置、路径、模型和轻量 JSON 兼容存储。
- `app/question_markdown.py`：题目 Markdown、题图和选项归一化。
- `app/ocr_processing.py`：OCR 输出整理、拆题和公式校验。
- `app/import_services.py`：导入任务兼容桥和入库辅助。
- `app/export_service.py`：试卷 Markdown/DOCX/PDF 渲染。
- `app/ocr_execution.py`：OCR job 执行。
- `app/worker_routes.py`：Java 仍需调用的 worker 和兼容路由。

新增平台业务逻辑不得放入 Python worker。

## Legacy API 边界

`worker_routes.py` 中仍保留一批 `/api/*` 路由，用于本地小平台和 Java bridge 平滑迁移。这些路由属于兼容桥，不是平台正式集成面：

- 新能力必须优先进入 Java `backend/src/main/java`。
- 平台集成必须优先使用 `/api/capabilities/*`、`/api/engine` 和 OpenAPI/SDK。
- Python 新增接口应使用 `/worker/*` 前缀，只表达 OCR、AI、公式处理或导出执行能力。
- 当 Java 已完全接管对应业务状态后，兼容 `/api/*` 路由应逐步删除。
