# 生产接入安全契约

本文定义公司平台接入 `question-engine` 时的安全边界、请求上下文、回调签名、文件访问、限流和审计责任。当前工程默认本地模式不启用登录鉴权，生产环境必须由平台网关或平台服务补齐安全控制。

## 1. 安全边界结论

`question-engine` 不做：

- 用户登录。
- 租户、学校、机构、角色和菜单权限判定。
- 最终题库数据访问授权。
- 平台文件中心长期访问授权。
- 平台级限流、风控、审计和告警。

`question-engine` 只做：

- 接收平台已鉴权请求。
- 读取平台注入的上下文 header。
- 按上下文记录任务、日志和 callback payload。
- 对 callback 请求做 HMAC-SHA256 签名。
- 暴露健康检查、能力目录、任务状态和运行时诊断。

生产接入推荐路径：

```text
平台前端
  -> 平台 API / BFF / 网关鉴权
  -> 平台服务补齐 tenant/operator/trace 上下文
  -> question-engine Java backend
  -> Python worker 内网执行 OCR/AI/export
```

平台前端不应直接绕过平台鉴权调用 `question-engine`。

## 2. 必传和建议请求头

| Header | 必填 | 示例 | 说明 |
| --- | --- | --- | --- |
| `Authorization` | 生产必填 | `Bearer <token>` | 平台网关或平台服务使用；本地调试可省略 |
| `X-Tenant-Id` | 生产必填 | `tenant-001` | 租户或机构隔离标识 |
| `X-Operator-Id` | 生产必填 | `teacher-1001` | 发起加工任务的用户或服务账号 |
| `X-Source-App` | 建议 | `question-bank-admin` | 调用方应用 |
| `X-Trace-Id` | 建议 | `trace-20260701-001` | 平台链路追踪；未提供时 Java 会生成 trace id |
| `X-School-Id` | 视平台需要 | `school-001` | 学校维度上下文 |
| `X-Request-Id` | 建议 | `req-...` | 幂等或排障关联 |

上下文 header 应由平台网关或平台后端注入，不应信任浏览器直接传入的用户身份。

## 3. OpenAPI 安全声明

`question-engine/openapi/question-engine.v1.yaml` 使用以下安全模型描述生产接入：

- `PlatformBearerAuth`：平台认证 token。
- `TenantHeader`：`X-Tenant-Id`。
- `OperatorHeader`：`X-Operator-Id`。

本地开发可以不启用网关鉴权，但生产 SDK、网关路由和服务间调用必须按平台安全规范补齐这些 header。

Java backend 提供一层可选的生产兜底校验，不替代平台鉴权。生产建议开启：

```text
PLATFORM_SECURITY_CONTEXT_VALIDATION_ENABLED=true
PLATFORM_SECURITY_AUTHORIZATION_REQUIRED=true
PLATFORM_SECURITY_REQUIRED_HEADERS=X-Tenant-Id,X-Operator-Id
```

开启后，除健康检查、Actuator 和接口文档等排除路径外，业务 API 缺少必填上下文 header 会返回 `400`，避免平台网关漏配时创建无租户或无操作人的 OCR 长任务。默认排除路径由 `PLATFORM_SECURITY_EXCLUDED_PATH_PREFIXES` 控制。

## 4. Callback 签名

callback-flow 使用 HMAC-SHA256：

```text
X-Question-Engine-Signature: sha256=<hex>
```

签名输入：

```text
signature = HMAC_SHA256(callbackSecret, rawRequestBody)
```

平台接收 callback 时必须：

1. 读取原始请求体字节，不要用重新序列化后的 JSON。
2. 使用双方约定的 callback secret 计算签名。
3. 常量时间比较签名值。
4. 校验 `idempotencyKey`，避免重复消费。
5. 对未知事件类型返回 2xx 或 4xx 的策略由平台统一定义，但重复事件必须幂等。

callback secret 不应通过前端传递；应由平台配置中心、密钥管理服务或部署环境注入。

## 5. 文件访问安全

`file-flow` 当前支持本地文件和 MinIO。生产环境必须做到：

- 上传文件由平台侧先完成鉴权、大小限制、类型校验和病毒扫描。
- 试卷原文件、题图、OCR 产物和导出文件的最终归档由平台文件中心或对象存储负责。
- Java 本地文件目录只允许作为临时目录或本地 fallback。
- 预览和下载 URL 不应长期裸露；应使用平台签名 URL、短期 token 或网关受控下载。
- Python worker 不应直接暴露公网；只允许 Java backend 内网调用。
- AI 标准化为修复严重 LaTeX 损坏，会由 Java backend 按 `paperOcrJobId` 内网读取 `/api/ocr/jobs/{jobId}/result`，只截取同题原始 OCR 片段传给 worker；该 OCR result 路径不应暴露给平台前端或公网。

## 6. 限流和配额

OCR、AI 和导出都是高成本能力。生产环境建议平台侧至少按以下维度限流：

| 维度 | 建议控制 |
| --- | --- |
| 租户 | 每分钟创建任务数、每日页数或文件大小总量 |
| 用户 | 并发任务数、AI 调用次数 |
| 文件 | 单文件大小、页数、格式白名单 |
| Worker | OCR 并发、AI 并发、导出并发 |
| Callback | 单事件最大重试次数、死信队列 |

`question-engine` 可以暴露 runtime 和 job 状态，但生产级配额、扣费、告警和封禁策略应归平台统一管理。

## 7. 网络隔离

推荐生产网络：

```text
公网 / 办公网
  -> 平台网关
  -> 平台服务
  -> question-engine Java backend
  -> Python worker
  -> OCR provider / LLM provider / 对象存储
```

要求：

- Java backend 不直接暴露给未鉴权公网。
- Python worker 不暴露给平台外部调用方。
- MinIO、MySQL、Redis、MQ 不暴露公网。
- DeepSeek / OpenAI 兼容大模型密钥只放在后端服务环境。

## 8. 审计字段

平台侧任务表或审计日志建议记录：

- `tenantId`
- `operatorId`
- `sourceApp`
- `traceId`
- `jobId`
- `paperFilename`
- `answerFilename`
- `fileSize`
- `questionCount`
- `processingStatus`
- `failureReason`
- `callbackEventId`
- `createdAt`
- `updatedAt`

如果平台不落任务表，至少要在网关日志和服务日志中保留 `traceId` 与 `jobId` 的关联。

## 9. 生产禁用项

生产环境默认应关闭或限制：

| 项 | 建议 |
| --- | --- |
| `PYTHON_WORKER_API_PROXY_ENABLED` | 关闭，除非仍有明确兼容路由需要迁移 |
| Swagger UI / Knife4j | 内网可用，公网关闭 |
| 本地 H2 数据库 | 仅本地开发使用 |
| 本地文件存储 | 仅作为临时目录或 fallback |
| 测试 callback 接口 | 内网或管理权限控制 |
| `/api/*` Python 兼容桥 | 不作为平台正式接入面 |

## 10. 平台接入验收

平台接入安全验收至少覆盖：

- 未带 `Authorization` 时平台网关拒绝。
- 未带 `X-Tenant-Id` 或 `X-Operator-Id` 时平台服务拒绝或补齐。
- `PLATFORM_SECURITY_CONTEXT_VALIDATION_ENABLED=true` 时，Java backend 对缺少生产上下文的业务 API 返回 `400`。
- 不同租户任务不可互查。
- callback 签名错误时平台拒绝消费。
- 重复 callback 事件幂等。
- 文件下载 URL 过期后不可访问。
- Python worker 不能被平台前端或公网直接访问。
