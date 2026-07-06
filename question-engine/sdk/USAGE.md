# Question Engine SDK 使用手册

本文面向要接入 `question-engine` 的工程师。如果团队内部把它称为 `question_engine` 插件，可以按这个理解：它不是一个前端插件，也不是一个完整业务系统，而是一组可被平台调用的能力包。

当前工程形态：

- Java backend 暴露稳定能力 API。
- OpenAPI 描述稳定契约。
- `question-engine/sdk/generated/typescript` 提供 TypeScript client。
- `question-engine/sdk/generated/java` 提供 Java JSON API client。
- Python worker 只负责 OCR、AI、导出等执行任务，由 Java backend 内部编排。

工程师看完本文后，应能完成三件事：

1. 在平台工程里引入 SDK 或 OpenAPI client。
2. 创建试卷加工任务，查询状态，获取 `question-package.v1`。
3. 判断哪些功能能直接用 question-engine，哪些必须由平台自己开发。

## 1. 先看结论

正式平台接入的主路径是：

```text
平台前端或平台服务
  -> QuestionEngineClient / OpenAPI client
  -> question-engine Java backend
  -> Python OCR / AI / export worker
  -> question-package.v1
  -> 平台自己的题库、图片、知识点、审核、权限、审计
```

最小调用链：

1. `listCapabilities()` 或 `getQuestionProcessingCapability()` 检查能力是否可用。
2. `createProcessingJob(...)` 上传试卷和可选答案文件。
3. `getProcessingJob(jobId)` 轮询任务状态，或由平台消费 callback。
4. 可选调用题图、AI 标准化、AI 解析能力完成复核。
5. `getQuestionPackage(jobId)` 获取标准题目包。
6. 平台把标准题目包写入自己的业务库。

不要这样接入：

- 不要直接调用 Python worker。
- 不要把 `local-platform/src/lib/api.ts` 当成正式 SDK。
- 不要把本地 H2、本地文件目录、本地入库接口当成平台主数据。
- 不要让 question-engine 接管平台用户、租户、权限、审核流、题库主表和知识点主数据。

## 2. 目录和文件

| 路径 | 用途 | 接入时是否使用 |
| --- | --- | --- |
| `question-engine/openapi/question-engine.v1.yaml` | 稳定契约源头 | 必看，可用于生成平台自己的 SDK |
| `question-engine/sdk/generated/typescript` | 生成型 TypeScript SDK | 前端、Node BFF、TypeScript 服务可用 |
| `question-engine/sdk/generated/java` | 生成型 Java SDK | Java 平台服务可用，当前主要覆盖 JSON API |
| `question-engine/sdk/examples` | 旧手写示例 | 仅参考，不作为正式 SDK |
| `question-engine/sdk/USAGE.md` | 本文 | 接入入口 |
| `docs/delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md` | 接口说明书 | 评审接口和边界时阅读 |
| `docs/product/LOCAL_PLATFORM_AS_EXAMPLE.md` | 本地小平台 example 说明 | 理解 local-platform 如何演示能力，不作为 SDK |

## 3. 接入前提

### 3.1 服务前提

本地调试时先启动 Java backend、Python worker 和 local-platform：

```bash
./scripts/start_project_with_java_backend.sh
```

至少确认这些地址可用：

```bash
curl http://localhost:8018/api/java/health
curl http://localhost:8018/api/java/worker
curl http://localhost:8018/api/capabilities
curl http://localhost:8018/api/engine/interfaces
curl http://localhost:8018/api/capabilities/question-processing
```

`http://localhost:8018` 是本地 Java backend 默认地址。生产环境应替换成平台内网服务地址或网关地址。

### 3.2 配置前提

| 配置 | 本地默认 | 正式环境建议 |
| --- | --- | --- |
| `QUESTION_ENGINE_BASE_URL` | `http://localhost:8018` | 平台内部 question-engine 服务地址 |
| Python worker | `http://127.0.0.1:8000` | 只允许 Java backend 内部访问 |
| OCR provider | MinerU provider | 按平台算力和文件类型配置 |
| LLM provider | 本地环境变量或配置 | 平台统一密钥、限流、成本、审计 |
| file-flow | 本地文件目录 | 对接平台对象存储或 MinIO |
| callback secret | 本地配置 | 平台统一 HMAC secret、重试、死信 |
| 租户/用户上下文 | 示例 header | 平台认证网关注入或平台服务补充 |

SDK 只接收 `baseUrl` 和 `headers`，不会替平台管理认证、租户、权限和审计。

## 4. 能力和 SDK 方法总览

| 能力 | TypeScript 方法 | Java 方法 | 说明 |
| --- | --- | --- | --- |
| 能力目录 | `listCapabilities()` | `listCapabilities()` | 查看全部能力 |
| Engine 目录 | `getEngineCatalog()` | `getEngineCatalog()` | 查看模块和交付边界 |
| 接口清单 | `getEngineInterfaces()` | `getEngineInterfaces()` | 对接评审、SDK 覆盖检查 |
| 题目加工能力描述 | `getQuestionProcessingCapability()` | `getQuestionProcessingCapability()` | 查看输入、输出和端点 |
| 创建加工任务 | `createProcessingJob(input)` | 当前 Java SDK 未封装 multipart | TS 可直接用；Java 建议 OpenAPI 生成或手写 multipart |
| 查询加工任务 | `getProcessingJob(jobId)` | `getProcessingJob(jobId)` | 查询状态、失败原因、题数 |
| 获取标准题目包 | `getQuestionPackage(jobId)` | `getQuestionPackage(jobId)` | 平台最终消费入口 |
| 导入任务题图库 | `getImportTaskImageLibrary(jobId)` | `getImportTaskImageLibrary(jobId)` | 复核工作台使用 |
| 选择导入题题图 | `selectImportQuestionImages(jobId, questionId, input)` | `selectImportQuestionImages(...)` | 从任务题图库挂图 |
| 上传导入题题图 | `uploadImportQuestionImages(jobId, questionId, files)` | 当前 Java SDK 未封装 multipart | TS 可直接用；Java 按 OpenAPI 生成 |
| 导入题 AI 标准化 | `standardizeImportQuestion(jobId, questionId, input)` | `standardizeImportQuestion(...)` | Java 编排 AI worker，默认返回修复候选 |
| 导入题 AI 解析 | `analyzeImportQuestion(jobId, questionId, input)` | `analyzeImportQuestion(...)` | 支持题图上下文 |
| 题库题图库 | `getBankQuestionImageLibrary(questionId)` | `getBankQuestionImageLibrary(questionId)` | 已入库题目的图片库 |
| 上传题库题题图 | `uploadBankQuestionImages(questionId, files)` | 当前 Java SDK 未封装 multipart | TS 可直接用；Java 按 OpenAPI 生成 |
| 题库题 AI 标准化 | `standardizeBankQuestion(questionId, input)` | `standardizeBankQuestion(...)` | 对已有题库题生成 AI 修复候选 |
| 题库题 AI 解析 | `analyzeBankQuestion(questionId, input)` | `analyzeBankQuestion(...)` | 对已有题库题生成解析 |
| runtime | `getOcrFlowRuntime()` 等 | `getRuntime(capability)` | 运维诊断 |
| callback | `listCallbackEvents()`、`retryCallbackEvent()` | `listCallbackEvents()`、`retryCallbackEvent()` | 回调排错和重试 |

## 5. TypeScript 接入

### 5.1 引入 SDK

当前 generated SDK 是源码目录，不是已发布 npm 包。平台有三种接入方式：

| 方式 | 做法 | 适用场景 |
| --- | --- | --- |
| 源码 vendoring | 把 `generated/typescript` 放进平台工程的 SDK 目录 | 初期最快 |
| 私有 npm 包 | 将 generated SDK 包装成内部包发布 | 多应用共享 |
| OpenAPI 生成 | 平台 CI 从 `question-engine.v1.yaml` 生成 client | 长期推荐 |

示例导入：

```ts
import { QuestionEngineClient } from "./question-engine-sdk";
import type {
  ProcessingJob,
  QuestionPackage,
  ProcessedQuestion,
} from "./question-engine-sdk";
```

如果直接在当前仓库内调试：

```ts
import { QuestionEngineClient } from "./generated/typescript";
```

### 5.2 创建 client

```ts
import { QuestionEngineClient } from "./question-engine-sdk";

const questionEngine = new QuestionEngineClient({
  baseUrl: process.env.QUESTION_ENGINE_BASE_URL ?? "http://localhost:8018",
  headers: {
    "X-Tenant-Id": "demo-tenant",
    "X-Operator-Id": "teacher-001",
    "X-Source-App": "platform-question-import",
  },
});
```

这些 header 只是示例。正式环境中，租户、用户、应用来源、trace id、认证 token 应按平台网关规范传入。

### 5.3 接入前健康检查

```ts
async function assertQuestionEngineReady(client: QuestionEngineClient) {
  const capabilities = await client.listCapabilities();
  const questionProcessing = await client.getQuestionProcessingCapability();
  const interfaces = await client.getEngineInterfaces();

  const hasQuestionProcessing = capabilities.some((item) => item.code === "question-processing");
  if (!hasQuestionProcessing) {
    throw new Error("question-processing capability is not available");
  }

  if (questionProcessing.packageVersion !== "question-package.v1") {
    throw new Error(`unsupported package version: ${questionProcessing.packageVersion}`);
  }

  return { capabilities, questionProcessing, interfaces };
}
```

### 5.4 从浏览器文件创建加工任务

```ts
const paperInput = document.querySelector<HTMLInputElement>("#paper-file");
const answerInput = document.querySelector<HTMLInputElement>("#answer-file");

if (!paperInput?.files?.[0]) {
  throw new Error("paper file is required");
}

const job = await questionEngine.createProcessingJob({
  paperFile: paperInput.files[0],
  answerFile: answerInput?.files?.[0],
  title: "2026 高一数学期中考试",
  stage: "高中",
  subject: "数学",
  grade: "高一",
  region: "北京",
  year: "2026",
});

console.log(job.jobId, job.processingStatus);
```

浏览器直接调用时需要处理 CORS、认证和文件大小限制。正式平台更推荐：

- 前端上传到平台服务。
- 平台服务鉴权、落任务表、记录审计。
- 平台服务调用 question-engine。
- 前端只访问平台自己的任务接口。

### 5.5 轮询任务状态

```ts
const TERMINAL_STATUSES = new Set([
  "WAITING_REVIEW",
  "PARTIAL_COMPLETED",
  "COMPLETED",
  "FAILED",
  "RETRYABLE",
]);

export async function waitProcessingJob(
  client: QuestionEngineClient,
  jobId: string,
  options: { intervalMs?: number; timeoutMs?: number } = {},
) {
  const intervalMs = options.intervalMs ?? 1500;
  const timeoutMs = options.timeoutMs ?? 120_000;
  const startedAt = Date.now();

  while (true) {
    const job = await client.getProcessingJob(jobId);

    if (TERMINAL_STATUSES.has(job.processingStatus)) {
      return job;
    }

    if (Date.now() - startedAt > timeoutMs) {
      throw new Error(`question processing timeout: ${jobId}`);
    }

    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}
```

状态含义：

| `processingStatus` | 含义 | 平台动作 |
| --- | --- | --- |
| `PROCESSING` | OCR/AI/拆题仍在处理 | 继续轮询或等待 callback |
| `WAITING_REVIEW` | 已生成待复核题目 | 打开复核页或获取题目包做预览 |
| `PARTIAL_COMPLETED` | 部分题目可用，部分失败或待处理 | 展示警告，允许人工处理 |
| `COMPLETED` | 任务完成 | 获取 `question-package.v1` 并入平台库 |
| `FAILED` | 不可继续的失败 | 展示失败原因，允许重新上传 |
| `RETRYABLE` | 可重试失败 | 平台触发重试策略或提示用户 |
| `UNKNOWN` | 状态不可识别 | 记录日志并进入人工排查 |

不要在生产环境用无限轮询。平台应有超时、重试、回调和后台任务编排。

### 5.6 获取标准题目包并写平台库

```ts
const latestJob = await waitProcessingJob(questionEngine, job.jobId);

if (latestJob.processingStatus === "FAILED") {
  throw new Error(latestJob.failureReason || "question processing failed");
}

const questionPackage = await questionEngine.getQuestionPackage(job.jobId);

if (questionPackage.packageVersion !== "question-package.v1") {
  throw new Error(`unsupported package version: ${questionPackage.packageVersion}`);
}

for (const question of questionPackage.questions) {
  await saveToPlatformQuestionBank({
    externalJobId: questionPackage.job.jobId,
    externalQuestionId: question.questionId,
    sourceQuestionId: question.sourceQuestionId,
    type: question.type,
    stemMarkdown: question.stemMarkdown,
    answer: question.answer,
    analysis: question.analysis,
    options: question.options,
    children: question.children,
    images: question.images,
    knowledgePointCandidates: question.knowledgePointCandidates,
    difficultyCandidate: question.difficultyCandidate,
    scoreCandidate: question.scoreCandidate,
    mathValidation: question.mathValidation,
    sourceEvidence: question.sourceEvidence,
    raw: question.raw,
  });
}
```

平台写库建议：

- 以 `jobId + questionId` 做幂等键。
- 先写平台导入任务表，再写题库草稿表。
- 保留 `sourceQuestionId`，方便追溯 OCR 原始题。
- 图片不要只保存 URL 字符串，应映射到平台对象存储或文件表。
- `knowledgePointCandidates` 是候选，不是最终知识点主数据。
- `raw` 只用于排错和兼容，不作为平台强依赖字段。

### 5.7 复核工作台能力

如果平台要实现自己的复核页，可以使用这些 helper。

获取任务题图库：

```ts
const library = await questionEngine.getImportTaskImageLibrary(job.jobId);
```

从题图库选择图片挂到题目：

```ts
await questionEngine.selectImportQuestionImages(job.jobId, "question-001", {
  imageIds: ["image-001", "image-002"],
});
```

上传本地题图：

```ts
const files = Array.from(fileInput.files ?? []);
const result = await questionEngine.uploadImportQuestionImages(
  job.jobId,
  "question-001",
  files,
);
```

AI 标准化：

```ts
const standardized = await questionEngine.standardizeImportQuestion(
  job.jobId,
  "question-001",
  {
    markdown: "题干 Markdown + LaTeX",
    questionType: "choice",
    answer: "A",
    analysis: "已有解析，可为空",
  },
);

console.log(standardized.markdown, standardized.answer, standardized.analysis);
// writeResult 默认是 false。调用方应展示候选源码/预览，用户确认后再保存题目。
// 只有确需服务端直接写回时，才显式传入 writeResult: true；低置信或严重 LaTeX 风险会被阻断。
if (!standardized.writeResult) {
  console.log(standardized.writeSkippedReason);
}
const standardizer = standardized.standardizer ?? {};
console.log({
  severeIssues: standardizer.severeIssues,
  candidateSevereIssues: standardizer.candidateSevereIssues,
  latexDelimiterRepaired: standardizer.latexDelimiterRepaired,
});
```

AI 解析：

```ts
const analysis = await questionEngine.analyzeImportQuestion(
  job.jobId,
  "question-001",
  {
    manualMarkdown: standardized.markdown,
    answer: standardized.answer,
    type: "choice",
    knowledgePoints: ["二次函数"],
  },
);
```

AI 解析接口会由 Java 读取当前题目已保存题图，并把可用图片转为模型可消费输入。平台通常不需要自己传 `imageDataUrl`。

### 5.8 已入库题目的 AI 和题图能力

如果平台已经有自己的题库题 ID，并希望复用 question-engine 的 AI 和题图能力，可以使用题库题 helper：

```ts
const imageLibrary = await questionEngine.getBankQuestionImageLibrary("bank-question-001");

const uploaded = await questionEngine.uploadBankQuestionImages(
  "bank-question-001",
  Array.from(fileInput.files ?? []),
);

const normalized = await questionEngine.standardizeBankQuestion("bank-question-001", {
  markdown: "题干 Markdown",
  questionType: "solution",
});

const generated = await questionEngine.analyzeBankQuestion("bank-question-001", {
  manualMarkdown: normalized.markdown,
  answer: normalized.answer,
  type: "solution",
});
```

注意：题库题 CRUD、版本、审核、发布仍是平台职责。question-engine 只提供 AI/file-flow 辅助能力。

## 6. Java 接入

### 6.1 引入 Java SDK

当前 Java SDK 是 generated source，不是已发布 Maven artifact。平台有三种使用方式：

| 方式 | 做法 | 适用场景 |
| --- | --- | --- |
| 源码 vendoring | 把 `generated/java/src/main/java/com/aigeneration/questionengine/sdk` 放入平台工程 | 初期最快 |
| 内部 Maven 模块 | 把 generated Java SDK 包成内部 jar | 多服务复用 |
| OpenAPI 生成 | 平台 CI 从 OpenAPI 生成 Java client | 长期推荐 |

依赖：

- JDK 17 或兼容 `java.net.http.HttpClient` 的版本。
- Jackson `ObjectMapper`。

### 6.2 创建 Java client

```java
import com.aigeneration.questionengine.sdk.QuestionEngineClient;
import com.aigeneration.questionengine.sdk.QuestionEngineModels.QuestionPackage;
import com.aigeneration.questionengine.sdk.QuestionEngineModels.ProcessingJob;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.Map;

QuestionEngineClient client = new QuestionEngineClient(
    System.getenv().getOrDefault("QUESTION_ENGINE_BASE_URL", "http://localhost:8018"),
    Map.of(
        "X-Tenant-Id", "demo-tenant",
        "X-Operator-Id", "teacher-001",
        "X-Source-App", "platform-question-import"
    ),
    new ObjectMapper()
);

var capabilities = client.listCapabilities();
var interfaces = client.getEngineInterfaces();
```

### 6.3 Java 创建加工任务

当前 generated Java SDK 没有封装 multipart 创建任务。Java 平台服务有两个选择：

1. 用平台的 OpenAPI 生成器生成 multipart client。
2. 临时用 `HttpClient` 手写 multipart 调用 `/api/capabilities/question-processing/jobs`。

下面是手写 multipart 的最小示例。生产环境应补齐文件大小限制、重试、日志、trace id、异常分类和测试。

```java
import com.aigeneration.questionengine.sdk.QuestionEngineModels.ProcessingJob;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Map;
import java.util.UUID;

public final class QuestionEngineMultipart {
    private final String baseUrl;
    private final Map<String, String> headers;
    private final HttpClient httpClient = HttpClient.newHttpClient();
    private final ObjectMapper objectMapper = new ObjectMapper();

    public QuestionEngineMultipart(String baseUrl, Map<String, String> headers) {
        this.baseUrl = baseUrl.replaceAll("/+$", "");
        this.headers = headers;
    }

    public ProcessingJob createProcessingJob(
            Path paperFile,
            Path answerFile,
            Map<String, String> fields
    ) throws IOException, InterruptedException {
        String boundary = "----qe-" + UUID.randomUUID();
        byte[] body = multipartBody(boundary, paperFile, answerFile, fields);

        HttpRequest.Builder builder = HttpRequest.newBuilder()
                .uri(URI.create(baseUrl + "/api/capabilities/question-processing/jobs"))
                .timeout(Duration.ofSeconds(60))
                .header("Content-Type", "multipart/form-data; boundary=" + boundary)
                .POST(HttpRequest.BodyPublishers.ofByteArray(body));
        headers.forEach(builder::header);

        HttpResponse<String> response = httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new IOException("create processing job failed: HTTP " + response.statusCode() + " " + response.body());
        }
        return objectMapper.readValue(response.body(), ProcessingJob.class);
    }

    private static byte[] multipartBody(
            String boundary,
            Path paperFile,
            Path answerFile,
            Map<String, String> fields
    ) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        for (Map.Entry<String, String> entry : fields.entrySet()) {
            writeTextPart(out, boundary, entry.getKey(), entry.getValue());
        }
        writeFilePart(out, boundary, "paperFile", paperFile);
        if (answerFile != null) {
            writeFilePart(out, boundary, "answerFile", answerFile);
        }
        out.write(("--" + boundary + "--\r\n").getBytes(StandardCharsets.UTF_8));
        return out.toByteArray();
    }

    private static void writeTextPart(ByteArrayOutputStream out, String boundary, String name, String value) throws IOException {
        out.write(("--" + boundary + "\r\n").getBytes(StandardCharsets.UTF_8));
        out.write(("Content-Disposition: form-data; name=\"" + name + "\"\r\n\r\n").getBytes(StandardCharsets.UTF_8));
        out.write((value == null ? "" : value).getBytes(StandardCharsets.UTF_8));
        out.write("\r\n".getBytes(StandardCharsets.UTF_8));
    }

    private static void writeFilePart(ByteArrayOutputStream out, String boundary, String name, Path file) throws IOException {
        String filename = file.getFileName().toString();
        String contentType = Files.probeContentType(file);
        if (contentType == null) contentType = "application/octet-stream";
        out.write(("--" + boundary + "\r\n").getBytes(StandardCharsets.UTF_8));
        out.write(("Content-Disposition: form-data; name=\"" + name + "\"; filename=\"" + filename + "\"\r\n").getBytes(StandardCharsets.UTF_8));
        out.write(("Content-Type: " + contentType + "\r\n\r\n").getBytes(StandardCharsets.UTF_8));
        out.write(Files.readAllBytes(file));
        out.write("\r\n".getBytes(StandardCharsets.UTF_8));
    }
}
```

调用示例：

```java
QuestionEngineMultipart multipart = new QuestionEngineMultipart(
    "http://localhost:8018",
    Map.of("X-Tenant-Id", "demo-tenant", "X-Operator-Id", "teacher-001")
);

ProcessingJob created = multipart.createProcessingJob(
    Path.of("/path/to/paper.pdf"),
    Path.of("/path/to/answer.pdf"),
    Map.of(
        "title", "2026 高一数学期中考试",
        "stage", "高中",
        "subject", "数学",
        "grade", "高一",
        "year", "2026"
    )
);
```

### 6.4 Java 轮询并获取标准题目包

```java
import java.time.Duration;
import java.time.Instant;
import java.util.Set;

static final Set<String> TERMINAL = Set.of(
    "WAITING_REVIEW",
    "PARTIAL_COMPLETED",
    "COMPLETED",
    "FAILED",
    "RETRYABLE"
);

ProcessingJob waitJob(QuestionEngineClient client, String jobId) throws Exception {
    Instant deadline = Instant.now().plus(Duration.ofMinutes(2));
    while (Instant.now().isBefore(deadline)) {
        ProcessingJob job = client.getProcessingJob(jobId);
        if (TERMINAL.contains(job.processingStatus())) {
            return job;
        }
        Thread.sleep(1500);
    }
    throw new IllegalStateException("question processing timeout: " + jobId);
}

ProcessingJob latest = waitJob(client, created.jobId());
if ("FAILED".equals(latest.processingStatus())) {
    throw new IllegalStateException(latest.failureReason());
}

QuestionPackage questionPackage = client.getQuestionPackage(created.jobId());
questionPackage.questions().forEach(question -> {
    System.out.println(question.questionId() + " " + question.type());
    System.out.println(question.stemMarkdown());
});
```

### 6.5 Java 调用 AI 和题图能力

选择导入题题图：

```java
import com.aigeneration.questionengine.sdk.QuestionEngineModels.SelectQuestionImagesRequest;

client.selectImportQuestionImages(
    created.jobId(),
    "question-001",
    new SelectQuestionImagesRequest(List.of("image-001", "image-002"), null)
);
```

AI 标准化导入题：

```java
import com.aigeneration.questionengine.sdk.QuestionEngineModels.AiStandardizeRequest;

var result = client.standardizeImportQuestion(
    created.jobId(),
    "question-001",
    new AiStandardizeRequest(
        "题干 Markdown",
        null,
        null,
        Map.of(),
        "choice",
        "A",
        "",
        List.of(),
        false,
        false,
        Map.of()
    )
);
```

AI 解析导入题：

```java
import com.aigeneration.questionengine.sdk.QuestionEngineModels.AiAnalysisRequest;

var analysis = client.analyzeImportQuestion(
    created.jobId(),
    "question-001",
    new AiAnalysisRequest(
        result.markdown(),
        result.answer(),
        "choice",
        List.of("二次函数"),
        List.of(),
        Map.of()
    )
);
```

## 7. `question-package.v1` 怎么用

`question-package.v1` 是平台最应该稳定消费的数据结构。

顶层结构：

| 字段 | 含义 | 平台建议 |
| --- | --- | --- |
| `packageVersion` | 当前为 `question-package.v1` | 做版本判断 |
| `capability` | 当前为 `question-processing` | 做来源识别 |
| `job` | 加工任务摘要 | 写平台导入任务表 |
| `questions` | 标准化后的题目列表 | 写平台题库草稿或审核表 |
| `warnings` | 任务级警告 | 展示给审核人员或写日志 |

`ProcessedQuestion` 核心字段：

| 字段 | 含义 | 平台建议 |
| --- | --- | --- |
| `questionId` | 标准题目 ID | 和 `jobId` 组成幂等键 |
| `sourceQuestionId` | OCR/导入题来源 ID | 保留追溯 |
| `type` | 题型候选 | 平台可二次校验 |
| `stemMarkdown` | 题干 Markdown + LaTeX | 写题干字段 |
| `originalStemMarkdown` | 原始题干 | 用于对比和审计 |
| `answer` | 答案 | 写答案字段 |
| `analysis` | 解析 | 写解析字段 |
| `options` | 选择题选项 | 写结构化选项 |
| `children` | 子题 | 写复合题结构 |
| `images` | 题图 | 映射到平台文件系统 |
| `knowledgePointCandidates` | 知识点名称候选 | 映射平台知识点主数据 |
| `knowledgePointIdCandidates` | 知识点 ID 候选 | 只在 ID 体系一致时使用 |
| `difficultyCandidate` | 难度候选 | 平台可人工确认 |
| `scoreCandidate` | 分值候选 | 平台可人工确认 |
| `mathValidation` | 公式校验摘要 | 作为审核提示 |
| `sourceEvidence` | 来源证据 | 审计和回溯 |
| `warnings` | 题目级警告 | 展示给审核人员 |
| `raw` | 兼容扩展 | 只用于排错 |

平台入库时不要把 `raw` 作为主结构。应显式映射字段，缺字段时走人工审核。

## 8. 回调和异步

当前 SDK 暴露 callback-flow 查询和重试能力：

```ts
const failed = await questionEngine.listCallbackEvents("failed");

for (const event of failed.items) {
  await questionEngine.retryCallbackEvent(event.id!, process.env.CALLBACK_RETRY_SECRET);
}

await questionEngine.retryDueCallbackEvents(process.env.CALLBACK_RETRY_SECRET);
```

Java：

```java
var failed = client.listCallbackEvents("failed");
for (var event : failed.items()) {
    client.retryCallbackEvent(event.id(), System.getenv("CALLBACK_RETRY_SECRET"));
}
```

正式平台建议：

- 任务创建后写平台任务表。
- question-engine 完成关键状态后回调平台。
- 平台用 `idempotencyKey` 做幂等消费。
- 回调失败进入重试，超过次数进入 dead letter。
- 前端不直接依赖 callback，前端查询平台自己的任务状态。

## 9. 错误处理

TypeScript SDK 行为：

- 读取响应文本。
- 如果非 2xx，优先取 `detail` 或 `error` 字段。
- 抛出 `Error`。

Java SDK 行为：

- 如果非 2xx，抛出 `IOException`。
- 异常消息包含 HTTP status 和响应体。

常见 HTTP 状态：

| 状态码 | 含义 | 平台动作 |
| --- | --- | --- |
| `400` | 请求参数错误，例如缺少 `paperFile` | 前端校验或平台服务参数校验 |
| `404` | 任务、题目、图片不存在 | 检查 `jobId`、`questionId`、权限和任务归属 |
| `409` | 状态冲突，可能不允许当前操作 | 刷新任务状态后重试或提示用户 |
| `413` | 文件过大 | 平台限制上传大小 |
| `422` | 结构化校验失败 | 展示字段错误 |
| `500` | 服务端异常 | 记录 trace id，进入排查 |
| `502` | Java 调 Python worker 失败 | 检查 worker、OCR、AI、导出依赖 |
| `503` | worker 禁用或不可达 | 检查部署和配置 |

建议平台日志记录：

- `jobId`
- 平台导入任务 ID
- `questionId`
- 租户、用户、应用来源
- SDK 方法名和 HTTP path
- HTTP status
- 错误响应体
- trace id 或 request id

## 10. 平台封装建议

不要让业务代码散落调用 SDK。建议平台封装一个自己的 service：

```ts
export class PlatformQuestionImportService {
  constructor(private readonly qe: QuestionEngineClient) {}

  async createImportTask(input: {
    tenantId: string;
    operatorId: string;
    paperFile: File | Blob;
    answerFile?: File | Blob;
    title: string;
    subject: string;
    grade: string;
  }) {
    const job = await this.qe.createProcessingJob({
      paperFile: input.paperFile,
      answerFile: input.answerFile,
      title: input.title,
      subject: input.subject,
      grade: input.grade,
    });

    await savePlatformImportTask({
      tenantId: input.tenantId,
      operatorId: input.operatorId,
      questionEngineJobId: job.jobId,
      status: job.processingStatus,
      title: input.title,
    });

    return job;
  }

  async syncQuestionPackage(jobId: string) {
    const pkg = await this.qe.getQuestionPackage(jobId);
    await upsertPlatformQuestionsFromPackage(pkg);
    return pkg;
  }
}
```

平台 service 应负责：

- 认证和授权。
- 租户隔离。
- 平台任务 ID 和 question-engine `jobId` 映射。
- 幂等键。
- 审核流。
- 最终题库写库。
- 图片迁移或引用。
- 失败重试。
- 审计日志。

## 11. 决策表

| 你要做什么 | 应该使用 |
| --- | --- |
| 让平台上传试卷并得到标准题目 | `createProcessingJob` + `getQuestionPackage` |
| 做一个人工复核页面 | `getProcessingJob`、题图库、题图选择、AI 标准化、AI 解析 |
| 把题目写入公司题库 | 平台自研写库，数据来源用 `question-package.v1` |
| 管理知识点树 | 平台自研 |
| 做组卷、试卷发布、考试绑定 | 平台自研 |
| 导出 DOCX/PDF | 可复用 export-flow，但文件权限和下载由平台自管 |
| 查询 OCR/AI/文件运行时 | runtime 方法或 `/api/capabilities/*/runtime` |
| 排查回调失败 | callback-flow SDK 方法 |
| 替换 OCR provider | 改 Python worker provider，保持 Java API 和输出不变 |

## 12. 本地调试脚本

启动：

```bash
./scripts/start_project_with_java_backend.sh
```

契约和文档同步检查：

```bash
python scripts/check_question_engine_contract.py
```

本地小平台业务冒烟：

```bash
python scripts/smoke_local_platform_business.py
```

SDK 重新生成：

```bash
python question-engine/sdk/generate-sdk.py
python scripts/check_question_engine_contract.py
```

修改以下内容后必须重新生成 SDK：

- `question-engine/openapi/question-engine.v1.yaml`
- API path、operationId、请求体、响应体、枚举。
- `question-package.v1` 字段。
- 题图、AI、callback、runtime 能力。

## 13. 排错清单

| 现象 | 可能原因 | 检查 |
| --- | --- | --- |
| `listCapabilities` 失败 | Java backend 未启动或 baseUrl 错误 | `curl http://localhost:8018/api/capabilities` |
| 创建任务返回 `400` | 没有传 `paperFile` 或字段名错误 | multipart 字段必须叫 `paperFile`、`answerFile` |
| 任务一直 `PROCESSING` | OCR 慢、worker 阻塞或任务状态未同步 | 查 `/api/java/worker`、Java 日志、Python worker 日志 |
| 返回 `502` | Java 调 worker 失败 | 检查 Python worker 是否启动 |
| AI 标准化失败 | LLM key、模型配置或网络问题 | 查 `/api/capabilities/ai-flow/runtime` |
| AI 解析没用到图片 | 题图未保存、文件不可读、图片过大 | 看 `aiImageIncluded`、`aiImageSkipReason` |
| 题目包为空 | OCR 没拆出题或任务未到可消费状态 | 查 `getProcessingJob(jobId)` 的状态和 `questionCount` |
| Java 创建任务困难 | Java SDK 未封装 multipart | 用 OpenAPI 生成器或本文 `HttpClient` multipart 示例 |
| 平台题库字段对不上 | 直接依赖 `raw` 或未做字段映射 | 按 `ProcessedQuestion` 显式映射 |

## 14. 接入验收清单

工程师完成接入后，至少应验证：

- 能通过 SDK 调到 `listCapabilities()`。
- 能识别 `question-processing` 能力。
- 能创建包含试卷文件的加工任务。
- 能查询 `getProcessingJob(jobId)` 并处理 `PROCESSING`、`WAITING_REVIEW`、`COMPLETED`、`FAILED`、`RETRYABLE`。
- 能获取 `question-package.v1`。
- 能把 `questions` 显式映射到平台题库草稿或审核表。
- 能处理空题目、题图缺失、AI 失败、OCR 失败。
- 能记录 `jobId`、平台任务 ID、操作者、租户、错误响应和 trace id。
- 没有直接依赖 `local-platform/src/lib/api.ts`。
- 没有直接调用 Python worker。

## 15. 和 local-platform 的关系

`local-platform` 是 example，不是 SDK。它展示了四个模块如何跑通本地闭环：

- 题目导入。
- 题库中心。
- 组卷中心。
- 知识点库。

正式平台接入时：

- 题目加工、题图、AI、标准题目包优先使用 SDK。
- 题库主表、知识点主数据、组卷、权限、审核、审计由平台自研。
- 想理解本地页面和 SDK/question-engine 的对应关系，阅读 `docs/product/LOCAL_PLATFORM_AS_EXAMPLE.md` 和 `docs/example/`。
