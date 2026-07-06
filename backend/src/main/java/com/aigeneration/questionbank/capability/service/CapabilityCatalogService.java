package com.aigeneration.questionbank.capability.service;

import com.aigeneration.questionbank.config.EnterpriseProperties;
import com.aigeneration.questionbank.config.JavaStorageProperties;
import com.aigeneration.questionbank.config.PythonWorkerProperties;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.file.Path;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.util.UriComponentsBuilder;

/**
 * 能力目录聚合服务。
 *
 * <p>负责把题库加工引擎可交付的主能力、补充能力、运行时状态和平台需承接的边界整理成
 * 稳定目录。该目录面向 SDK、OpenAPI 文档和企业平台集成方，不承载具体业务执行。</p>
 */
@Service
public class CapabilityCatalogService {
    /**
     * worker runtime 响应按通用 Map 读取，允许 Python worker 独立扩展运行时字段。
     */
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {
    };

    /**
     * Python worker 连接配置，用于查询 AI/导出等下游 runtime。
     */
    private final PythonWorkerProperties pythonWorkerProperties;

    /**
     * 企业部署配置，当前主要用于描述 MinIO 文件能力。
     */
    private final EnterpriseProperties enterpriseProperties;

    /**
     * Java 存储配置，用于 file-flow runtime 暴露本地存储根目录。
     */
    private final JavaStorageProperties storageProperties;

    /**
     * JSON 解析器，负责把 worker runtime JSON 解析成 Map。
     */
    private final ObjectMapper objectMapper;

    /**
     * 注入能力目录构建所需的配置与 JSON 支撑组件。
     *
     * @param pythonWorkerProperties Python worker 连接配置
     * @param enterpriseProperties 企业部署配置
     * @param storageProperties Java 文件存储配置
     * @param objectMapper JSON 解析器
     */
    public CapabilityCatalogService(
            PythonWorkerProperties pythonWorkerProperties,
            EnterpriseProperties enterpriseProperties,
            JavaStorageProperties storageProperties,
            ObjectMapper objectMapper
    ) {
        this.pythonWorkerProperties = pythonWorkerProperties;
        this.enterpriseProperties = enterpriseProperties;
        this.storageProperties = storageProperties;
        this.objectMapper = objectMapper;
    }

    /**
     * 返回完整能力目录。
     *
     * <p>目录同时包含 question-processing、ocr-flow 两个主能力，以及人工校验、AI、
     * 导出、文件、回调、SDK/OpenAPI 等补充能力，便于平台一次性发现引擎能力边界。</p>
     *
     * @return 完整能力描述列表
     */
    public List<Map<String, Object>> catalog() {
        return List.of(
                coreCapability(
                        "question-processing",
                        "试卷到标准题目数据包加工能力",
                        "主能力",
                        List.of("/api/capabilities/question-processing", "/api/capabilities/question-processing/jobs"),
                        List.of("review-workbench", "ocr-flow", "ai-flow", "file-flow", "callback-flow")
                ),
                coreCapability(
                        "ocr-flow",
                        "OCR-Flow 试卷识别加工能力",
                        "主能力",
                        List.of("/api/capabilities/ocr-flow", "/api/capabilities/ocr-flow/runtime"),
                        List.of("file-flow", "ai-flow")
                ),
                reviewWorkbench(),
                aiFlow(),
                exportFlow(),
                fileFlow(),
                callbackFlow(),
                sdkOpenapi()
        );
    }

    /**
     * 返回面向企业平台交付的补充能力清单。
     *
     * <p>该清单排除主能力入口，强调平台集成时需要承接或复用的边界能力。</p>
     *
     * @return 交付能力描述列表
     */
    public List<Map<String, Object>> deliveryCapabilities() {
        return List.of(
                reviewWorkbench(),
                aiFlow(),
                exportFlow(),
                fileFlow(),
                callbackFlow(),
                sdkOpenapi()
        );
    }

    /**
     * 构造人工校验工作台能力描述。
     *
     * @return review-workbench 能力描述
     */
    public Map<String, Object> reviewWorkbench() {
        return capability(
                "review-workbench",
                "可嵌入人工校验工作台",
                "把 OCR/AI 产生的待校验题目交给人工编辑，支持题干、选项、答案、解析、题图、原文件预览、公式渲染和保存校验状态；不负责平台菜单、登录、审批和最终发布。",
                "Java 保存任务、题目、题图和校验状态；本地小平台提供 React 页面，企业平台可 iframe/微前端嵌入或重写 UI 调 Java API。",
                List.of(
                        "/api/capabilities/question-processing/jobs/{jobId}",
                        "/api/capabilities/question-processing/jobs/{jobId}/question-package",
                        "/api/import-tasks/{jobId}",
                        "/api/import-tasks/{jobId}/questions/{questionId}",
                        "/api/import-tasks/{jobId}/source/{paper|answer}"
                ),
                List.of(),
                List.of("/import?taskId={jobId}", "未来企业嵌入入口：/embed/review-workbench/jobs/{jobId}"),
                List.of("ProcessingJob", "ImportQuestionSnapshot", "QuestionImage", "SourceFilePreview"),
                List.of("平台容器页或 iframe 容器", "operatorId/tenantId 请求上下文", "保存后是否入库的业务策略"),
                List.of("题目编辑器组件", "公式渲染器", "题图选择器", "原文件预览器", "保存前校验策略"),
                List.of("当前本地页面可用；交付时应只交付能力 API、嵌入入口规范和必要组件，不交付小平台导航壳。")
        );
    }

    /**
     * 构造 AI 标准化和解析能力描述。
     *
     * @return ai-flow 能力描述
     */
    public Map<String, Object> aiFlow() {
        return capability(
                "ai-flow",
                "AI 标准化、AI 解析和答案解析匹配",
                "对 OCR 原始文本、人工编辑 Markdown 和题图做确定性 LaTeX 分隔符修复、语义修复、题目解析生成、答案自动回填、答案解析与题目匹配；不直接决定平台审核和发布。",
                "Java 作为业务入口和状态归属方，负责创建 AI job、读取题图并转成 worker 内部图片输入、调用 worker、记录成功/失败、返回标准化候选并写回答案/解析；Python worker 先执行确定性公式分隔符修复和安全校验，再按需调用大模型做语义修复。",
                List.of(
                        "/api/capabilities/ai-flow",
                        "/api/capabilities/ai-flow/runtime",
                        "/api/capabilities/ai-flow/jobs",
                        "/api/import-tasks/{jobId}/questions/{questionId}/standardize/ai",
                        "/api/import-tasks/{jobId}/questions/{questionId}/analysis",
                        "/api/question-bank/questions/{questionId}/standardize/ai",
                        "/api/question-bank/questions/{questionId}/analysis"
                ),
                List.of("/worker/ai/standardize", "/worker/ai/analysis"),
                List.of(),
                List.of("rawOcrText", "currentMarkdown", "questionImages", "structuredHints", "answerEvidence", "analysisEvidence", "aiMetadata"),
                List.of("大模型 API Key/模型/代理配置", "敏感内容和成本控制策略", "失败降级和人工复核规则"),
                List.of("确定性 LaTeX 分隔符修复器", "LLM provider", "Prompt 模板", "答案解析匹配策略", "LaTeX 校验器", "人工确认阈值"),
                List.of("Java 已接管 AI 标准化/解析编排；AI 标准化默认返回候选并等待人工应用保存，worker 会先修复展示公式内部嵌套 $ 和行内公式被运算符切断等确定性 LaTeX 分隔符问题，AI 解析会把已保存题图送入多模态模型上下文并写回答案/解析；生产环境下一步应接入异步队列、超时扫描和成本限流。")
        );
    }

    /**
     * 构造试卷导出能力描述。
     *
     * @return export-flow 能力描述
     */
    public Map<String, Object> exportFlow() {
        return capability(
                "export-flow",
                "Markdown/DOCX/PDF 试卷导出能力",
                "先生成中间 Markdown，再通过 Pandoc/XeLaTeX 导出 DOCX/PDF；支持题目、答案、解析、题图和公式；不负责平台发布流和文件长期归档。",
                "Java 管试卷定义、导出 job、失败原因和导出文件存储；Python worker 只执行 Pandoc/LaTeX 渲染。",
                List.of(
                        "/api/capabilities/export-flow",
                        "/api/capabilities/export-flow/runtime",
                        "/api/capabilities/export-flow/jobs",
                        "/api/papers/{paperId}/export"
                ),
                List.of("/worker/export/render", "/worker/export-flow"),
                List.of(),
                List.of("PaperExportRequest", "paper.md", "paper.docx", "paper.pdf", "ExportFile"),
                List.of("Pandoc/XeLaTeX 或企业导出服务", "中文字体配置", "导出文件存储策略"),
                List.of("导出模板", "字体配置", "DOCX reference 模板", "PDF engine", "对象存储归档"),
                List.of("Java 已接管导出任务元数据、worker 调用和文件存储；运行时状态由 /runtime 暴露，生产环境下一步接入异步队列和下载权限。")
        );
    }

    /**
     * 构造文件存储、题图和产物访问能力描述。
     *
     * @return file-flow 能力描述
     */
    public Map<String, Object> fileFlow() {
        return capability(
                "file-flow",
                "原文件、题图、OCR 产物和导出文件存储协议",
                "统一描述文件上传、预览、下载、对象存储、题图引用、OCR 产物和导出文件；不负责平台最终文件中心的权限模型。",
                "Java 管业务文件元数据和本地/MinIO 存储；Python worker 只读取临时文件、临时 URL 或写入 worker 产物。",
                List.of(
                        "/api/capabilities/file-flow",
                        "/api/capabilities/file-flow/runtime",
                        "/api/import-tasks/{jobId}/source/{paper|answer}",
                        "/api/import-tasks/{jobId}/image-library",
                        "/api/import-tasks/{jobId}/questions/{questionId}/images",
                        "/api/question-bank/questions/{questionId}/image-library",
                        "/api/question-bank/questions/{questionId}/images",
                        "/api/ocr/jobs/{ocrJobId}/files/{relativePath}"
                ),
                List.of(),
                List.of(),
                List.of("StorageFile", "SourceFilePreview", "QuestionImage", "OcrOutputFile", "ExportFile"),
                List.of("对象存储或平台文件中心", "访问签名/下载权限", "临时 URL 或本地临时路径策略"),
                List.of("StorageProvider", "SignedUrlProvider", "FileAccessPolicy", "VirusScanHook", "RetentionPolicy"),
                List.of("Java 已支持 LOCAL/MINIO 两种存储，并接管导入原文件、导入题图、题库题图和导出文件；下一步可抽象平台文件中心适配器和临时 URL。")
        );
    }

    /**
     * 构造任务事件回调能力描述。
     *
     * @return callback-flow 能力描述
     */
    public Map<String, Object> callbackFlow() {
        return capability(
                "callback-flow",
                "任务完成、失败和可重试平台回调能力",
                "把导入、OCR、AI、导出任务的完成、失败、可重试和超时事件通知给平台；不承载平台消息中心和业务审批。",
                "Java 计算任务状态并发出回调；Python worker 只返回执行结果和失败原因。",
                List.of(
                        "/api/capabilities/callback-flow",
                        "/api/capabilities/callback-flow/runtime",
                        "POST /api/capabilities/callback-flow/test",
                        "GET /api/capabilities/callback-flow/events",
                        "POST /api/capabilities/callback-flow/events/{eventId}/retry"
                ),
                List.of(),
                List.of(),
                List.of("CallbackEvent", "ProcessingJobStatus", "FailureReason", "RetryPolicy"),
                List.of("回调 URL", "签名密钥", "幂等键处理", "平台侧重试/死信策略"),
                List.of("CallbackSigner", "RetryPolicy", "DeadLetterPublisher", "EventMapper"),
                List.of("已提供 HTTP 回调发送、HMAC-SHA256 签名、事件记录和失败重试；MQ 开关通过 runtime 暴露，未启用时使用本地表记录。")
        );
    }

    /**
     * 构造 SDK 与 OpenAPI 能力描述。
     *
     * @return sdk-openapi 能力描述
     */
    public Map<String, Object> sdkOpenapi() {
        return capability(
                "sdk-openapi",
                "面向平台应用的 SDK / OpenAPI",
                "提供稳定 OpenAPI、Knife4j 文档、能力目录和 SDK 生成边界，供公司教育生态平台的不同应用调用题库加工能力。",
                "Java 暴露 OpenAPI 和能力接口；平台按网关、认证和租户上下文封装自己的 SDK。",
                List.of(
                        "/api/capabilities",
                        "/api/engine",
                        "/v3/api-docs",
                        "/swagger-ui/index.html",
                        "/doc.html"
                ),
                List.of(),
                List.of(),
                List.of("openapi.json", "capability-catalog.v1", "question-package.v1"),
                List.of("API 网关", "鉴权头注入", "租户上下文", "版本兼容策略"),
                List.of("Java SDK", "TypeScript SDK", "Webhook SDK", "OpenAPI Generator 配置"),
                List.of("OpenAPI/Knife4j 已可用；当前新增能力目录作为 SDK 的稳定入口。")
        );
    }

    /**
     * 查询 AI-Flow 的下游运行时，并补充能力编码和 worker 端点。
     *
     * @return AI-Flow runtime
     */
    public Map<String, Object> aiFlowRuntime() {
        Map<String, Object> runtime = workerRuntime("/api/system/llm", "AI-Flow runtime");
        runtime.put("capability", "ai-flow");
        runtime.put("workerEndpoints", List.of("/worker/ai/standardize", "/worker/ai/analysis"));
        return runtime;
    }

    /**
     * 查询 Export-Flow 的下游运行时，并补充能力编码。
     *
     * @return Export-Flow runtime
     */
    public Map<String, Object> exportFlowRuntime() {
        Map<String, Object> runtime = workerRuntime("/worker/export-flow", "Export-Flow runtime");
        runtime.put("capability", "export-flow");
        return runtime;
    }

    /**
     * 返回 Java 侧文件能力 runtime。
     *
     * <p>文件能力 runtime 由 Java 配置直接计算，不依赖 Python worker，用于说明当前使用本地
     * 存储还是 MinIO，以及支持哪些业务文件类型和访问模式。</p>
     *
     * @return File-Flow runtime
     */
    public Map<String, Object> fileFlowRuntime() {
        EnterpriseProperties.Minio minio = enterpriseProperties.getMinio();
        Map<String, Object> runtime = new LinkedHashMap<>();
        runtime.put("capability", "file-flow");
        runtime.put("storageType", minio.isEnabled() ? "MINIO" : "LOCAL");
        runtime.put("localRoot", Path.of(storageProperties.getLocalRoot()).toAbsolutePath().normalize().toString());
        runtime.put("minio", Map.of(
                "enabled", minio.isEnabled(),
                "endpoint", minio.getEndpoint(),
                "bucket", minio.getBucket(),
                "accessKeyConfigured", minio.getAccessKey() != null && !minio.getAccessKey().isBlank()
        ));
        runtime.put("businessTypes", List.of(
                "IMPORT_TASK_UPLOAD",
                "OCR_OUTPUT",
                "QUESTION_IMAGE",
                "BANK_QUESTION_IMAGE",
                "PAPER_EXPORT"
        ));
        runtime.put("accessModes", List.of("inline-preview", "download", "worker-temp-path", "future-signed-url"));
        return runtime;
    }

    /**
     * 构造主能力的轻量目录项。
     *
     * @param code 能力编码
     * @param name 能力名称
     * @param type 能力类型
     * @param javaEndpoints Java 暴露的入口
     * @param relatedCapabilities 相关补充能力编码
     * @return 主能力目录项
     */
    private Map<String, Object> coreCapability(
            String code,
            String name,
            String type,
            List<String> javaEndpoints,
            List<String> relatedCapabilities
    ) {
        Map<String, Object> descriptor = new LinkedHashMap<>();
        descriptor.put("code", code);
        descriptor.put("name", name);
        descriptor.put("type", type);
        descriptor.put("javaEndpoints", javaEndpoints);
        descriptor.put("relatedCapabilities", relatedCapabilities);
        descriptor.put("delivery", "core");
        return descriptor;
    }

    /**
     * 构造补充能力的统一描述结构。
     *
     * @param code 能力编码
     * @param name 能力名称
     * @param boundary 能力边界说明
     * @param stateOwner 状态归属说明
     * @param javaEndpoints Java 侧接口
     * @param workerEndpoints worker 侧接口
     * @param localPlatformEndpoints 本地平台或嵌入入口
     * @param dataContracts 数据契约
     * @param platformMustProvide 平台必须提供的外部能力
     * @param extensionPoints 可替换或扩展点
     * @param migrationStatus 当前迁移状态
     * @return 补充能力描述
     */
    private Map<String, Object> capability(
            String code,
            String name,
            String boundary,
            String stateOwner,
            List<String> javaEndpoints,
            List<String> workerEndpoints,
            List<String> localPlatformEndpoints,
            List<String> dataContracts,
            List<String> platformMustProvide,
            List<String> extensionPoints,
            List<String> migrationStatus
    ) {
        Map<String, Object> descriptor = new LinkedHashMap<>();
        descriptor.put("code", code);
        descriptor.put("name", name);
        descriptor.put("type", "supplemental-capability");
        descriptor.put("boundary", boundary);
        descriptor.put("stateOwner", stateOwner);
        descriptor.put("javaEndpoints", javaEndpoints);
        descriptor.put("workerEndpoints", workerEndpoints);
        descriptor.put("localPlatformEndpoints", localPlatformEndpoints);
        descriptor.put("dataContracts", dataContracts);
        descriptor.put("platformMustProvide", platformMustProvide);
        descriptor.put("extensionPoints", extensionPoints);
        descriptor.put("migrationStatus", migrationStatus);
        descriptor.put("delivery", "engine");
        return descriptor;
    }

    /**
     * 访问 Python worker 的 runtime 接口并转换成通用 Map。
     *
     * <p>该方法统一处理 worker 开关、URL 拼接、超时配置、HTTP 错误转换和 runtimeUrl
     * 回填，供多个能力 runtime 复用。</p>
     *
     * @param workerPath worker runtime 路径
     * @param label 错误信息中的能力标签
     * @return worker runtime 响应
     */
    private Map<String, Object> workerRuntime(String workerPath, String label) {
        if (!pythonWorkerProperties.isEnabled()) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Python worker is disabled");
        }
        String runtimeUrl = UriComponentsBuilder
                .fromHttpUrl(pythonWorkerProperties.getBaseUrl())
                .path(workerPath)
                .toUriString();
        try {
            SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
            requestFactory.setConnectTimeout(Duration.ofMillis(pythonWorkerProperties.getConnectTimeoutMs()));
            requestFactory.setReadTimeout(Duration.ofMillis(pythonWorkerProperties.getReadTimeoutMs()));
            RestClient restClient = RestClient.builder()
                    .requestFactory(requestFactory)
                    .build();
            String body = restClient.get()
                    .uri(runtimeUrl)
                    .retrieve()
                    .onStatus(HttpStatusCode::isError, (request, response) -> {
                        throw new RestClientException(label + " returned HTTP " + response.getStatusCode());
                    })
                    .body(String.class);
            Map<String, Object> runtime = objectMapper.readValue(body == null ? "{}" : body, MAP_TYPE);
            runtime.put("runtimeUrl", runtimeUrl);
            return runtime;
        } catch (Exception ex) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, label + " is not reachable: " + ex.getMessage(), ex);
        }
    }
}
