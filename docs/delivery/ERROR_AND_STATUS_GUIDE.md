# 错误码与状态机手册

本文定义 `question-engine` 平台接入时应使用的状态、错误分类、可重试规则和前端展示建议。

## 1. 状态字段

`ProcessingJob` 同时包含：

| 字段 | 面向对象 | 说明 |
| --- | --- | --- |
| `status` | 本地中文状态兼容 | 兼容本地小平台，例如 `处理中`、`待校验` |
| `processingStatus` | 平台稳定状态 | SDK 和平台接入应优先使用 |

平台不得依赖中文 `status` 做长期业务判断，应使用 `processingStatus`。

## 2. 加工任务状态机

| processingStatus | 中文含义 | 终态 | 平台建议 |
| --- | --- | --- | --- |
| `PROCESSING` | 处理中 | 否 | 展示进度或轮询；允许取消入口由平台自研 |
| `WAITING_REVIEW` | 待人工校验 | 否 | 打开复核工作台或允许预览题目包 |
| `PARTIAL_COMPLETED` | 部分完成 | 可作为业务终态 | 展示警告，允许人工补救和部分入库 |
| `COMPLETED` | 完成 | 是 | 获取 `question-package.v1` 并进入平台入库流程 |
| `FAILED` | 失败 | 是 | 展示失败原因，不自动重试 |
| `RETRYABLE` | 可重试 | 否 | 平台可触发重试或提示用户重试 |
| `UNKNOWN` | 未知 | 否 | 展示排障提示，记录 trace id |

状态流：

```text
PROCESSING
  -> WAITING_REVIEW
  -> COMPLETED

PROCESSING
  -> PARTIAL_COMPLETED
  -> COMPLETED

PROCESSING
  -> RETRYABLE
  -> PROCESSING

PROCESSING
  -> FAILED

任意状态
  -> UNKNOWN
```

## 3. 导入题状态

| 状态 | 含义 | 平台动作 |
| --- | --- | --- |
| `待校验` | OCR/AI 生成草稿，等待人工确认 | 打开编辑器 |
| `已校验` | 人工已保存确认 | 可纳入题目包或平台入库 |
| `已入库` | 已同步到本地题库快照 | 平台不应依赖本地入库状态作为正式主数据 |

正式平台应按自己的审核流和发布流维护最终题目状态。

## 4. 错误分类

| errorCode | HTTP | 可重试 | 说明 | 平台展示 |
| --- | --- | --- | --- | --- |
| `INVALID_REQUEST` | 400 | 否 | 参数缺失、字段格式错误 | 提示用户修正输入 |
| `UNSUPPORTED_FILE_TYPE` | 400 | 否 | 文件后缀或 MIME 不支持 | 提示支持的文件类型 |
| `FILE_TOO_LARGE` | 413 | 否 | 文件超过平台限制 | 提示压缩或拆分文件 |
| `OCR_PROVIDER_UNAVAILABLE` | 503 | 是 | MinerU 或 OCR provider 不可用 | 提示稍后重试，通知运维 |
| `OCR_TIMEOUT` | 504 | 是 | OCR 超时 | 提示文件较大，允许重试 |
| `OCR_FAILED` | 500 | 视原因 | OCR 执行失败 | 展示失败摘要，保留 trace id |
| `LLM_UNAVAILABLE` | 503 | 是 | 大模型服务不可用 | 降级或稍后重试 |
| `LLM_TIMEOUT` | 504 | 是 | AI 标准化/解析超时 | 允许跳过 AI 或重试 |
| `QUESTION_SPLIT_FAILED` | 422 | 视原因 | OCR 文本无法拆题 | 允许人工上传更清晰文件 |
| `MATH_NORMALIZE_FAILED` | 422 | 否 | Markdown/LaTeX 标准化失败 | 显示公式风险，进入人工修正 |
| `STORAGE_WRITE_FAILED` | 500 | 是 | 文件写入本地或对象存储失败 | 提示稍后重试，通知运维 |
| `CALLBACK_DELIVERY_FAILED` | 502 | 是 | callback 投递失败 | 进入重试或死信 |
| `WORKER_UNAVAILABLE` | 503 | 是 | Python worker 不可达 | 通知运维 |
| `INTERNAL_ERROR` | 500 | 视原因 | 未分类异常 | 展示通用错误和 trace id |

当前接口仍可能返回 `failureReason` 文本。平台适配层应优先识别未来标准 `errorCode`，当前可用关键字映射到上表。
对于 PDF、图片、DOCX、PPTX、XLSX 和 `.doc` 等必须进入 OCR provider 的导入任务，服务会在创建任务前检查 provider runtime；命中 `OCR_PROVIDER_UNAVAILABLE` 时不会创建加工任务，平台应提示运维执行 `./scripts/deploy_local.sh --with-mineru` 或配置 `MINERU_COMMAND` 后再重试。

## 5. 可重试规则

推荐可重试：

- `OCR_PROVIDER_UNAVAILABLE`
- `OCR_TIMEOUT`
- `LLM_UNAVAILABLE`
- `LLM_TIMEOUT`
- `STORAGE_WRITE_FAILED`
- `CALLBACK_DELIVERY_FAILED`
- `WORKER_UNAVAILABLE`
- 网络 502/503/504

不建议自动重试：

- `INVALID_REQUEST`
- `UNSUPPORTED_FILE_TYPE`
- `FILE_TOO_LARGE`
- 明确的权限失败
- 明确的文件损坏或无法解析

需要人工判断：

- `OCR_FAILED`
- `QUESTION_SPLIT_FAILED`
- `MATH_NORMALIZE_FAILED`
- `INTERNAL_ERROR`

## 6. 轮询策略

平台轮询 `GET /api/capabilities/question-processing/jobs/{jobId}` 时建议：

| 场景 | 建议 |
| --- | --- |
| 前 1 分钟 | 每 2 秒轮询 |
| 1 到 5 分钟 | 每 5 秒轮询 |
| 5 分钟后 | 每 10 到 30 秒轮询 |
| 超过平台 SLA | 停止前端轮询，转后台任务或 callback |

轮询必须带 `traceId` 或能关联 `jobId`，避免排障时无法串联日志。

## 7. Callback 状态

| callback status | 含义 | 平台动作 |
| --- | --- | --- |
| `pending` | 等待投递 | 无需人工处理 |
| `sent` | 投递成功 | 幂等消费完成 |
| `failed` | 投递失败，可重试 | 触发重试或等待扫描 |
| `dead_letter` | 超过最大重试 | 人工排障 |

callback 重试必须带同一个 `idempotencyKey`。

## 8. 前端展示建议

| processingStatus | 用户文案 | 操作 |
| --- | --- | --- |
| `PROCESSING` | 正在识别试卷，请稍候 | 查看详情、后台处理 |
| `WAITING_REVIEW` | 已生成待校验题目 | 进入校验 |
| `PARTIAL_COMPLETED` | 部分题目识别成功 | 查看成功题目、处理失败项 |
| `COMPLETED` | 题目加工完成 | 导入平台题库 |
| `FAILED` | 加工失败 | 查看原因、重新上传 |
| `RETRYABLE` | 当前任务可重试 | 重试 |
| `UNKNOWN` | 状态异常 | 复制 trace id 联系运维 |

用户文案不要暴露堆栈、密钥、对象存储路径和内网地址。

## 9. 日志字段

错误日志至少包含：

- `traceId`
- `tenantId`
- `operatorId`
- `jobId`
- `capability`
- `processingStatus`
- `errorCode`
- `failureReason`
- `workerJobId`
- `durationMs`

日志不得包含：

- API Key。
- callback secret。
- 原始试卷全文。
- 内联图片 base64。
- 用户敏感信息。
