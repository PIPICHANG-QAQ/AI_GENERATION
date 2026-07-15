package com.aigeneration.questionbank.capability.service;

import com.aigeneration.questionbank.config.PythonWorkerProperties;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
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
 * OCR-Flow 能力说明服务。
 *
 * <p>该服务不直接执行 OCR 任务，而是向平台暴露 OCR 能力边界、可替换 provider 策略以及
 * Python worker 当前运行时状态，供能力目录、接口文档和集成方 SDK 使用。</p>
 */
@Service
public class OcrFlowCapabilityService {
    /**
     * 能力目录中用于标识 OCR-Flow 的稳定编码。
     */
    public static final String CAPABILITY_CODE = "ocr-flow";

    /**
     * worker runtime 响应统一按 Map 读取，避免 runtime 字段扩展时需要频繁修改 Java 模型。
     */
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {
    };

    /**
     * Python worker 访问配置，包含开关、baseUrl 和超时时间。
     */
    private final PythonWorkerProperties pythonWorkerProperties;

    /**
     * 负责把 worker 返回的 JSON 字符串转换成通用 Map。
     */
    private final ObjectMapper objectMapper;

    /**
     * 注入 OCR 能力运行时所需的 worker 配置和 JSON 解析器。
     *
     * @param pythonWorkerProperties Python worker 配置
     * @param objectMapper JSON 解析器
     */
    public OcrFlowCapabilityService(PythonWorkerProperties pythonWorkerProperties, ObjectMapper objectMapper) {
        this.pythonWorkerProperties = pythonWorkerProperties;
        this.objectMapper = objectMapper;
    }

    /**
     * 返回 OCR-Flow 的静态能力描述。
     *
     * <p>描述内容覆盖能力边界、provider 合约、预处理器、配置键、Java/worker 端点以及替换
     * OCR provider 时必须保持稳定的输出结构。</p>
     *
     * @return OCR-Flow 能力描述 Map
     */
    public Map<String, Object> descriptor() {
        Map<String, Object> descriptor = new LinkedHashMap<>();
        descriptor.put("code", CAPABILITY_CODE);
        descriptor.put("name", "OCR-Flow 试卷识别加工能力");
        descriptor.put("boundary", "接收原始试卷/答案文件，完成预处理、OCR provider 调用、统一证据适配、后处理、结构化拆题、公式标准化和 AI 补全；不负责平台用户、权限、最终题库主数据和业务审核流。");
        descriptor.put("defaultProvider", "mineru");
        descriptor.put("providerContract", Map.of(
                "status", "返回 provider 是否可用、命令位置、版本和错误原因。",
                "run", "输入 jobId、uploadPath 和 runtime，输出 provider 原生结果并适配为统一 OCR 证据包。",
                "outputSchema", "canonical-ocr-bundle.v1",
                "requiredEvidence", List.of("documentId", "inputSha256", "canonicalMarkdown", "artifactRoot"),
                "optionalEvidence", List.of("assets", "pages", "layoutBlocks", "sourceDocumentRef", "producer", "nativeArtifacts", "capabilities")
        ));
        descriptor.put("postProcessContract", Map.of(
                "inputSchema", "canonical-ocr-bundle.v1",
                "entrypoint", "app.ocr.OcrPostProcessingPipeline.run_bundle",
                "outputCompatibility", "legacy-collect-outputs",
                "responsibilities", List.of("assets", "sections", "questions", "mathValidation", "questionImages")
        ));
        descriptor.put("preprocessors", List.of(
                Map.of("name", "markdown-direct", "extensions", List.of(".md", ".markdown")),
                Map.of("name", "doc-convert", "extensions", List.of(".doc"), "output", ".docx")
        ));
        descriptor.put("configKeys", Map.of(
                "provider", "OCR_FLOW_PROVIDER",
                "extensions", "OCR_FLOW_EXTENSIONS",
                "mineruCommand", "MINERU_COMMAND",
                "timeout", "MINERU_TIMEOUT_SECONDS"
        ));
        descriptor.put("javaEndpoints", Map.of(
                "descriptor", "/api/capabilities/ocr-flow",
                "runtime", "/api/capabilities/ocr-flow/runtime"
        ));
        descriptor.put("workerEndpoints", Map.of(
                "runtime", "/worker/ocr-flow",
                "createJob", "/worker/ocr",
                "getJob", "/worker/ocr/{jobId}",
                "getResult", "/worker/ocr/{jobId}/result"
        ));
        descriptor.put("replaceProviderStrategy", List.of(
                "在 Python worker 增加新的 OcrProvider 实现。",
                "使用 provider adapter 把原生结果转换为 canonical-ocr-bundle.v1。",
                "通过 OCR_FLOW_PROVIDER 切换 provider 名称。",
                "通过 OCR_FLOW_EXTENSIONS 调整 provider 可接收的文件后缀。",
                "保持 CanonicalOcrBundle 输入契约和后处理输出兼容层稳定，避免改动 Java 业务 API 和前端。"
        ));
        return descriptor;
    }

    /**
     * 查询 Python worker 暴露的 OCR-Flow 运行时状态。
     *
     * <p>该方法会校验 worker 开关，按配置拼接 runtime URL，并把 worker 返回值补充
     * {@code runtimeUrl} 后返回。worker 不可用时转换成网关错误，便于调用方区分 Java 服务
     * 正常但下游能力不可达的场景。</p>
     *
     * @return OCR-Flow 运行时状态
     */
    public Map<String, Object> runtime() {
        if (!pythonWorkerProperties.isEnabled()) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Python worker is disabled");
        }

        String runtimeUrl = UriComponentsBuilder
                .fromHttpUrl(pythonWorkerProperties.getBaseUrl())
                .path("/worker/ocr-flow")
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
                        throw new RestClientException("OCR-Flow runtime returned HTTP " + response.getStatusCode());
                    })
                    .body(String.class);
            Map<String, Object> runtime = objectMapper.readValue(body == null ? "{}" : body, MAP_TYPE);
            runtime.put("runtimeUrl", runtimeUrl);
            return runtime;
        } catch (Exception ex) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "OCR-Flow runtime is not reachable: " + ex.getMessage(), ex);
        }
    }
}
