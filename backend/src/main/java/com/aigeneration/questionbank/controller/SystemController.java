package com.aigeneration.questionbank.controller;

import com.aigeneration.questionbank.common.ApiResponse;
import com.aigeneration.questionbank.common.TraceIdFilter;
import com.aigeneration.questionbank.config.EnterpriseProperties;
import com.aigeneration.questionbank.config.JavaStorageProperties;
import com.aigeneration.questionbank.config.PythonWorkerProperties;
import com.aigeneration.questionbank.config.SmartRagStackProperties;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import org.slf4j.MDC;
import org.springframework.boot.info.BuildProperties;
import org.springframework.core.env.Environment;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.util.UriComponentsBuilder;

/**
 * Java 后端系统诊断接口。
 *
 * <p>该控制器只暴露运行时、企业化配置摘要、Python worker 连通性和技术栈对齐信息，
 * 不承载题目加工、题库、组卷或知识点业务逻辑。所有返回都包在 {@link ApiResponse}
 * 中，并把 {@link TraceIdFilter} 写入 MDC 的 traceId 带回给调用方，便于前端和日志系统关联一次请求。</p>
 */
@Tag(name = "Java 系统诊断", description = "Java 后端健康检查、运行时、企业化配置、Python worker 和技术栈对齐信息")
@RestController
@RequestMapping("/api/java")
public class SystemController {

    /** Python worker 调用配置，用于暴露 worker 开关、代理开关、健康检查路径和请求超时。 */
    private final PythonWorkerProperties pythonWorkerProperties;
    /** SmartRAG 技术栈版本对齐配置，用于说明当前项目和参考工程的公开依赖版本关系。 */
    private final SmartRagStackProperties smartRagStackProperties;
    /** 企业化依赖开关配置，用于汇总 MySQL、Redis、MinIO、MQ 等可选基础设施状态。 */
    private final EnterpriseProperties enterpriseProperties;
    /** Java 侧文件存储配置，用于报告本地存储根目录和企业对象存储切换后的活跃存储类型。 */
    private final JavaStorageProperties javaStorageProperties;
    /** Spring 运行环境，用于读取当前 active profiles 并辅助判断企业 profile 是否启用。 */
    private final Environment environment;
    /** Spring Boot 构建信息；本地开发或未打包时可能不存在，因此构造函数中允许为空。 */
    private final BuildProperties buildProperties;

    /**
     * 创建系统诊断控制器。
     *
     * @param pythonWorkerProperties Python worker 运行和代理配置
     * @param smartRagStackProperties SmartRAG 技术栈对齐配置
     * @param enterpriseProperties 企业化依赖开关与连接摘要配置
     * @param javaStorageProperties Java 文件存储配置
     * @param environment Spring 环境，用于读取 active profiles
     * @param buildProperties 可选构建信息；测试、本地 IDE 启动或未执行 build-info 时为空
     */
    public SystemController(
            PythonWorkerProperties pythonWorkerProperties,
            SmartRagStackProperties smartRagStackProperties,
            EnterpriseProperties enterpriseProperties,
            JavaStorageProperties javaStorageProperties,
            Environment environment,
            java.util.Optional<BuildProperties> buildProperties
    ) {
        this.pythonWorkerProperties = pythonWorkerProperties;
        this.smartRagStackProperties = smartRagStackProperties;
        this.enterpriseProperties = enterpriseProperties;
        this.javaStorageProperties = javaStorageProperties;
        this.environment = environment;
        this.buildProperties = buildProperties.orElse(null);
    }

    /**
     * 查询 Java 主后端基础健康状态。
     *
     * <p>该接口不访问数据库或 Python worker，只返回当前进程可以立即计算出的轻量信息。
     * 适合前端启动探活、网关粗粒度健康检查和人工排查 Java 服务是否正常响应。</p>
     *
     * @return 包含服务状态、active profile、Java 版本、worker 开关和当前时间戳的统一响应
     */
    @Operation(summary = "查询 Java 后端健康状态", description = "轻量健康检查，不访问数据库或 Python worker；用于确认 Java 主后端进程是否可响应。")
    @GetMapping("/health")
    public ApiResponse<Map<String, Object>> health() {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("status", "ok");
        payload.put("service", "ai-question-bank-java");
        payload.put("profile", activeProfiles());
        payload.put("javaVersion", Runtime.version().toString());
        payload.put("workerEnabled", pythonWorkerProperties.isEnabled());
        payload.put("apiProxyEnabled", pythonWorkerProperties.isApiProxyEnabled());
        payload.put("timestamp", Instant.now().toString());
        return ApiResponse.ok(payload, traceId());
    }

    /**
     * 查询企业化依赖配置摘要。
     *
     * <p>该接口只报告配置状态和连接目标，不主动连接 Redis、MinIO 或 MQ。这样可以在本地 H2 +
     * Python worker 模式下保持启动稳定，同时让部署平台确认生产 profile 应配置哪些外部依赖。</p>
     *
     * @return MySQL、Redis、MinIO、Java 文件存储、MQ、Prometheus/Actuator 入口等配置摘要
     */
    @Operation(summary = "查询企业化配置摘要", description = "返回 MySQL、Redis、MinIO、MQ、文件存储和监控入口配置摘要；不会主动连接外部依赖。")
    @GetMapping("/enterprise")
    public ApiResponse<Map<String, Object>> enterprise() {
        Map<String, Object> payload = new LinkedHashMap<>();
        // 数据库摘要：当前只暴露是否启用和 mysql profile 是否处于 active profiles 中。
        payload.put("mysql", Map.of(
                "enabled", enterpriseProperties.getMysql().isEnabled(),
                "activeProfile", activeProfiles().contains("mysql")
        ));
        // Redis、MinIO、MQ 都只报告配置值，不在诊断接口里做真实连接，避免影响本地启动。
        payload.put("redis", Map.of(
                "enabled", enterpriseProperties.getRedis().isEnabled(),
                "host", enterpriseProperties.getRedis().getHost(),
                "port", enterpriseProperties.getRedis().getPort()
        ));
        payload.put("minio", Map.of(
                "enabled", enterpriseProperties.getMinio().isEnabled(),
                "endpoint", enterpriseProperties.getMinio().getEndpoint(),
                "bucket", enterpriseProperties.getMinio().getBucket()
        ));
        payload.put("storage", Map.of(
                "activeType", enterpriseProperties.getMinio().isEnabled() ? "MINIO" : "LOCAL",
                "localRoot", javaStorageProperties.getLocalRoot(),
                "metadataTable", "java_storage_files"
        ));
        payload.put("mq", Map.of(
                "enabled", enterpriseProperties.getMq().isEnabled(),
                "provider", enterpriseProperties.getMq().getProvider(),
                "nameServer", enterpriseProperties.getMq().getNameServer()
        ));
        payload.put("metrics", Map.of(
                "prometheus", "/actuator/prometheus",
                "health", "/actuator/health"
        ));
        payload.put("note", "认证权限未启用；Redis/MinIO/MQ 默认不强制连接，避免破坏本地 H2 + Python worker 启动。");
        return ApiResponse.ok(payload, traceId());
    }

    /**
     * 查询 Java 进程运行时信息。
     *
     * <p>该接口面向运维和本地调试，返回进程资源、构建版本和 Python worker 配置。
     * 内存字段使用 MB，便于前端直接展示，不再让调用方自行换算字节。</p>
     *
     * @return 服务版本、CPU 数、JVM 内存摘要和 Python worker 配置
     */
    @Operation(summary = "查询 Java 运行时信息", description = "返回服务版本、JVM 内存、CPU 数和 Python worker 配置摘要。")
    @GetMapping("/system")
    public ApiResponse<Map<String, Object>> system() {
        Runtime runtime = Runtime.getRuntime();
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("service", "ai-question-bank-java");
        payload.put("version", buildProperties == null ? "0.1.0-SNAPSHOT" : buildProperties.getVersion());
        payload.put("availableProcessors", runtime.availableProcessors());
        payload.put("maxMemoryMb", bytesToMb(runtime.maxMemory()));
        payload.put("totalMemoryMb", bytesToMb(runtime.totalMemory()));
        payload.put("freeMemoryMb", bytesToMb(runtime.freeMemory()));
        payload.put("pythonWorker", Map.of(
                "enabled", pythonWorkerProperties.isEnabled(),
                "apiProxyEnabled", pythonWorkerProperties.isApiProxyEnabled(),
                "baseUrl", pythonWorkerProperties.getBaseUrl(),
                "healthPath", pythonWorkerProperties.getHealthPath()
        ));
        return ApiResponse.ok(payload, traceId());
    }

    /**
     * 检查 Python worker 健康状态。
     *
     * <p>当 worker 被配置为关闭时，接口会直接返回 {@code reachable=false} 和 {@code reason=disabled}。
     * 当 worker 开启时，Java 会按配置的连接/读取超时请求 worker 健康检查路径，并把成功响应或失败原因写入返回体。
     * 该接口用于定位 OCR、AI、导出 worker 是否可达，不替代具体能力运行时接口。</p>
     *
     * @return Python worker 开关、目标健康检查 URL、可达性、响应内容或错误信息
     */
    @Operation(summary = "检查 Python worker 健康状态", description = "按配置请求 Python worker 健康检查路径，返回 worker 是否启用、目标 URL、可达性和响应/错误信息。")
    @GetMapping("/worker")
    public ApiResponse<Map<String, Object>> worker() {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("enabled", pythonWorkerProperties.isEnabled());
        payload.put("baseUrl", pythonWorkerProperties.getBaseUrl());
        payload.put("healthPath", pythonWorkerProperties.getHealthPath());

        // worker 关闭是合法部署形态，直接返回 disabled，而不是抛 503 影响系统诊断页。
        if (!pythonWorkerProperties.isEnabled()) {
            payload.put("reachable", false);
            payload.put("reason", "disabled");
            return ApiResponse.ok(payload, traceId());
        }

        String healthUrl = UriComponentsBuilder
                .fromHttpUrl(pythonWorkerProperties.getBaseUrl())
                .path(pythonWorkerProperties.getHealthPath())
                .toUriString();
        payload.put("healthUrl", healthUrl);

        try {
            // 每次检查都按配置构造带超时的轻量 RestClient，避免健康检查被 worker 长时间阻塞。
            SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
            requestFactory.setConnectTimeout(Duration.ofMillis(pythonWorkerProperties.getConnectTimeoutMs()));
            requestFactory.setReadTimeout(Duration.ofMillis(pythonWorkerProperties.getReadTimeoutMs()));
            RestClient restClient = RestClient.builder()
                    .requestFactory(requestFactory)
                    .build();
            String body = restClient.get()
                    .uri(healthUrl)
                    .retrieve()
                    .onStatus(HttpStatusCode::isError, (request, response) -> {
                        throw new RestClientException("Python worker health returned HTTP " + response.getStatusCode());
                    })
                    .body(String.class);
            payload.put("reachable", true);
            payload.put("response", body);
        } catch (RestClientException ex) {
            // 健康检查失败应返回诊断信息，而不是让系统页整体失败。
            payload.put("reachable", false);
            payload.put("error", ex.getMessage());
        }

        return ApiResponse.ok(payload, traceId());
    }

    /**
     * 查询 SmartRAG 技术栈对齐状态。
     *
     * <p>该接口说明当前项目参考 SmartRAG smc-knowledge 技术栈时只接入公开 BOM 和框架版本，
     * 没有硬依赖私有父 POM、RuoYi 私有模块或 common-core，避免本地 Maven 构建失败。</p>
     *
     * @return SmartRAG 对齐来源、是否已对齐、版本映射和私有依赖排除说明
     */
    @Operation(summary = "查询技术栈对齐状态", description = "返回 SmartRAG 公开依赖版本对齐信息，并说明未硬接入私有父 POM 或私有模块。")
    @GetMapping("/stack")
    public ApiResponse<Map<String, Object>> stack() {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("source", "SmartRAG smc-knowledge 技术栈文档");
        payload.put("aligned", true);
        payload.put("versions", smartRagStackProperties.getVersions());
        payload.put("privateDependenciesExcluded", true);
        payload.put("note", "SmartRAG 的私有父 POM、RuoYi 私有模块和 common-core 未硬接入，避免本项目本地 Maven 构建失败。公开 BOM 与已接入框架版本按 SmartRAG 对齐。");
        return ApiResponse.ok(payload, traceId());
    }

    /**
     * 读取当前请求的 traceId。
     *
     * <p>{@link TraceIdFilter} 会在请求进入时把 traceId 放入 MDC，并在响应头中返回同一个值。
     * 控制器返回体也带上该值，方便不读取响应头的前端或调用脚本定位日志。</p>
     *
     * @return 当前请求的 traceId；如果请求未经过 TraceIdFilter，可能为空
     */
    private String traceId() {
        return MDC.get(TraceIdFilter.MDC_KEY);
    }

    /**
     * 将字节数换算为 MB。
     *
     * @param value 字节数
     * @return 使用 1024 进制换算后的 MB 整数值
     */
    private long bytesToMb(long value) {
        return value / 1024 / 1024;
    }

    /**
     * 获取当前 Spring active profiles。
     *
     * <p>Spring 未显式激活 profile 时返回 {@code default}，多个 profile 使用英文逗号拼接，
     * 与系统诊断接口中的字符串展示保持一致。</p>
     *
     * @return 当前 active profiles 字符串
     */
    private String activeProfiles() {
        String[] profiles = environment.getActiveProfiles();
        return profiles.length == 0 ? "default" : String.join(",", profiles);
    }
}
