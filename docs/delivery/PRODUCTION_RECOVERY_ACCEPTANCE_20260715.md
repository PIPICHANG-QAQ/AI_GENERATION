# 2026-07-15 生产恢复验收记录

> 取证日期：2026-07-16（Asia/Shanghai）
> 结论范围：生产运行态恢复与 OCR 可用性验收完成；不等同于全部模块化计划或正式生产交付完成。
> 状态标签：运行态恢复：已验收；provider 计划：13/18；模块化计划：3/215；正式生产交付：未完成。

## 1. 发布身份与可回滚资产

| 项目 | 实际值 |
| --- | --- |
| Git 分支 | codex/production-recovery-20260715 |
| 当前部署提交 | edc045d（Linux .doc smoke 支持） |
| 前序证据提交 | d29674e（immutable OCR evidence） |
| 服务器镜像 | sha256:18f2ee29a87ed5c1a4809ce5c49ccae60dfa30df0e569e987778653f8fd700ef |
| 应用镜像回滚标签 | ai-generation-question-engine:pre-edc045d → sha256:761d7e15fd459152a17107ddfa20fefb72c22c9b242a98488439bbc614b39850 |
| 本次生产恢复服务器代码包（已部署） | 服务器 release 目录中的 `AI_GENERATION_TOGO_20260715_PRODUCTION_RECOVERY/AI_GENERATION_TOGO_20260715_PRODUCTION_RECOVERY.tar.gz` |
| 已部署代码包 SHA-256 / 文件数 | 9ff128f83f5f4267cf75433ed699db180eeadb9313e89e6d78cde0c85197bf50 / 447 |
| manifest SHA-256 | a39d2b7906b02670882e7257d67b59ee0cf36cd7e63ab3aedcc38ce1f2f1287a |
| 上一交付包归档 | release/archive-d29674e，tar SHA-256 为 85bdb6e576daa323cb3c960f713f0ebaec9f4c6de5fc9015e691084fd3f552f2 |
| 应用备份 | 服务器 backups 目录中的 `AI_GENERATION_DOCKER_20260715T222812Z`，tar SHA-256 为 47f7e2481c206c000a154dbab4ba3957cb2a639414bc6739d8a8169fae9cd01f |
| MinerU venv 备份 | 服务器项目 `vendor/` 目录中的 `mineru-venv.bak-20260715T234343.716530Z-f9debe27` |

持久数据、.env、上传、任务状态和模型缓存没有进入覆盖同步。禁止把已知曾失败 runtime 的 venv 直接当作 OCR 健康回滚；应用代码回滚可使用上一镜像，OCR 回滚必须先重新通过 runtime readiness。

## 2. 根因与修复范围

- 历史故障表明 MinerU 命令存在或 version probe 成功并不足以证明 OCR 可用；恢复流程已增加同解释器深度 import runtime probe 和 API OpenAPI readiness。
- MinerU 原生产工件可能有空 Markdown 而 content-list 仍含内容。canonical adapter 现在生成内容寻址、不可变的 Markdown/JSON 证据快照，并校验 native 和派生路径，避免不受信任 symlink 或工件覆盖改变已保存结果。
- 初次 Linux 全格式 smoke 暴露 Docker 镜像缺少 .doc 转换器。镜像增加 LibreOffice Writer；这不是简单放宽错误，而是在真实 .doc 上传链路中完成转换、OCR 和题目生成验证。

## 3. 本地验证证据

本地正式运行态验收使用端口 8001/8019/5174，严格启动后 worker health、Java health、OCR runtime 和前端根路径均通过。13 类文件类型、basic deploy、平台业务、OCR 与 AI smoke 已在单实例条件下跑通；测试结束后端口均释放。

本轮最终自动化回归：

| 验证项 | 结果 |
| --- | --- |
| Python 全量 pytest | 332 passed，1 条第三方 Starlette/httpx 弃用警告，40 subtests passed |
| Python worker 包装套件 | 217 tests OK |
| Java Maven | 87 tests，0 failures，0 errors，BUILD SUCCESS |
| local-platform Vitest | 22 tests，4 files passed |
| local-platform production build | 2445 modules transformed，build success |
| 可移植性检查测试 | 10 tests OK |
| OCR golden 工具测试 | 32 tests OK；不是受控真实语料 compare |
| OCR benchmark 工具测试 | 8 tests OK；不是正式 performance baseline compare |
| OCR 边界检查 | 46 tests OK |
| MinerU venv 重建检查 | 78 tests OK |
| Question Engine 契约检查 | contract、SDK 与文档同步 |
| 文档更新后的本地包边界检查 | valid，448 files（含本验收记录）；这是本地边界检查，不替换已部署的 447 文件代码包 |

本地历史运行态记录还确认 .xlsx 的 HTML table Markdown 边界处理已修复，最终 13 类格式各自产出至少 1 题。

## 4. 服务器运行态验收

### 4.1 基础健康与 MinerU

- Docker health：healthy；前端根路径 HTTP 200。
- Java health：success=true，worker bridge reachable=true。
- OCR runtime：selectedProvider=mineru，installed=true，versionProbeOk=true，runtimeProbeOk=true，apiEnabled=true，apiReady=true。
- active venv 包元数据：mineru 3.4.2、MarkupSafe 3.0.3、Jinja2 3.1.6、transformers 4.57.6。
- LibreOffice：/usr/bin/soffice，版本 7.3.7.2。

### 4.2 OCR 与业务 smoke

| 验收项 | 实际结果 |
| --- | --- |
| 小样 OCR | import_task_20260716_025940_15ce0f3b / ocr_20260716_025940_48c660bf 成功，任务进入待校验，1 题 |
| 原失败任务 retry | import_task_20260715_065444_e0d1c55f 继续使用 ocr_20260715_065444_6f78252a；本次根因修复后仅发起一次 retry，retryCount=2 为历史累计值；status=待校验，paperOcrStatus=success，questionCount=37，failureReason 为空，source/paper HTTP 200 |
| 全文件类型 smoke | .md、.markdown、.pdf、.png、.jpg、.jpeg、.webp、.tif、.tiff、.doc、.docx、.pptx、.xlsx 全部通过；每项 OCR success 且 questionCount=1 |
| 平台业务 smoke | 题目导入、预览、保存、题图、知识点、题库、试卷、导出和题目包均通过 |
| AI smoke | 创建、题目读取、canonicalization、单题标准化/解析、全局标准化均通过 |

修复前由 smoke 产生的 .doc 失败测试任务 import_task_20260716_032400_41864fb9 已经核验为测试数据并删除，随后 GET 返回 404。用户原始 37 题任务没有删除或重复 retry。

### 4.3 日志与 GPU

- 发布后日志扫描没有匹配 Traceback、ERROR、Exception、cannot import 或 CUDA out of memory。
- GPU0：MinerU Python，约 1141 MiB；GPU1：VLLM::EngineCore，约 39601 MiB。OCR 与 vLLM 的既有 GPU 分配未被破坏。

## 5. 仍未完成的范围

以下项目不因本次 recovery 或 smoke 被视为完成：

- provider 替换的 20 份受控真实样卷零差异、正式 benchmark baseline、性能和预发观察周期；
- 用户/租户权限、题目版本、企业审核流；
- 真实 MQ、超时扫描器和 durable task/fencing 体系；
- Java 作为唯一事实源、灰度迁移、正式 Java/TypeScript SDK 发布包；
- OCR Flow 模块化总计划中除 Task 7 已有代码证据外的阶段门禁。

因此当前状态应表述为“核心重构已验证、生产运行态恢复并验收完成”，不能表述为“全部 215 项模块化计划完成”或“正式生产交付全部完成”。
