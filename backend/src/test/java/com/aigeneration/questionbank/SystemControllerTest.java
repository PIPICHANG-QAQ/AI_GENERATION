package com.aigeneration.questionbank;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.options;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;

/**
 * 系统和能力目录控制器测试。
 *
 * <p>该测试类覆盖 Java 后端健康检查、OCR-Flow 能力描述、补充能力目录和 question-engine
 * 目录接口，确保这些面向平台集成的稳定接口不被后续改动破坏。</p>
 */
@SpringBootTest(properties = {
        "java-domain.migration.enabled=false",
        "spring.datasource.url=jdbc:h2:mem:system-controller-test;MODE=MySQL;DATABASE_TO_LOWER=TRUE;CASE_INSENSITIVE_IDENTIFIERS=TRUE",
        "python-worker.api-proxy-enabled=false",
        "app.cors.allowed-origin-patterns=http://localhost:*,http://127.0.0.1:*,https://*.pinggy-free.link"
})
@AutoConfigureMockMvc
class SystemControllerTest {

    /**
     * MockMvc 用于在不启动真实 HTTP 服务的情况下调用 Spring MVC 接口。
     */
    @Autowired
    private MockMvc mockMvc;

    /**
     * 验证 Java 后端健康检查返回统一成功结构和服务标识。
     *
     * @throws Exception MockMvc 调用失败时抛出
     */
    @Test
    void healthReturnsJavaBackendStatus() throws Exception {
        mockMvc.perform(get("/api/java/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.status").value("ok"))
                .andExpect(jsonPath("$.data.service").value("ai-question-bank-java"));
    }

    /**
     * 验证部署隧道域名可通过 CORS 预检，避免浏览器 POST 被 Spring CORS 过滤器拒绝。
     *
     * @throws Exception MockMvc 调用失败时抛出
     */
    @Test
    void corsPreflightAllowsConfiguredPublicTunnelOrigin() throws Exception {
        mockMvc.perform(options("/api/import-tasks")
                        .header("Origin", "https://demo-120-211-112-121.run.pinggy-free.link")
                        .header("Access-Control-Request-Method", "POST"))
                .andExpect(status().isOk())
                .andExpect(result -> org.assertj.core.api.Assertions.assertThat(
                                result.getResponse().getHeader("Access-Control-Allow-Origin"))
                        .isEqualTo("https://demo-120-211-112-121.run.pinggy-free.link"));
    }

    /**
     * 验证重新 OCR 扫描入口由 Java 编排控制器处理，而不是被 Python worker 代理截获。
     *
     * @throws Exception MockMvc 调用失败时抛出
     */
    @Test
    void rescanRouteIsHandledByJavaDomainController() throws Exception {
        mockMvc.perform(post("/api/import-tasks/__missing_task__/rescan"))
                .andExpect(status().isNotFound());
    }

    /**
     * 验证 OCR-Flow 能力描述暴露 provider 边界和 worker 端点。
     *
     * @throws Exception MockMvc 调用失败时抛出
     */
    @Test
    void ocrFlowCapabilityDescriptorExposesProviderBoundary() throws Exception {
        mockMvc.perform(get("/api/capabilities/ocr-flow"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("ocr-flow"))
                .andExpect(jsonPath("$.defaultProvider").value("mineru"))
                .andExpect(jsonPath("$.configKeys.provider").value("OCR_FLOW_PROVIDER"))
                .andExpect(jsonPath("$.workerEndpoints.runtime").value("/worker/ocr-flow"));
    }

    /**
     * 验证能力目录包含所有补充能力，并且 file-flow runtime 暴露 Java 存储状态。
     *
     * @throws Exception MockMvc 调用失败时抛出
     */
    @Test
    void capabilityCatalogExposesSupplementalEngineCapabilities() throws Exception {
        mockMvc.perform(get("/api/capabilities"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(8))
                .andExpect(jsonPath("$[2].code").value("review-workbench"))
                .andExpect(jsonPath("$[3].code").value("ai-flow"))
                .andExpect(jsonPath("$[4].code").value("export-flow"))
                .andExpect(jsonPath("$[5].code").value("file-flow"))
                .andExpect(jsonPath("$[6].code").value("callback-flow"))
                .andExpect(jsonPath("$[7].code").value("sdk-openapi"));

        mockMvc.perform(get("/api/capabilities/file-flow/runtime"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.capability").value("file-flow"))
                .andExpect(jsonPath("$.storageType").value("LOCAL"))
                .andExpect(jsonPath("$.businessTypes[0]").value("IMPORT_TASK_UPLOAD"));
    }

    /**
     * 验证 question-engine 总目录、模块目录、补充能力和接口清单的基本契约。
     *
     * @throws Exception MockMvc 调用失败时抛出
     */
    @Test
    void engineCatalogExposesFourDeliverableModules() throws Exception {
        mockMvc.perform(get("/api/engine"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("question-engine"))
                .andExpect(jsonPath("$.modules.length()").value(4))
                .andExpect(jsonPath("$.supplementalCapabilities.length()").value(6))
                .andExpect(jsonPath("$.modules[0].code").value("question-import"))
                .andExpect(jsonPath("$.deliveryBoundary.excludePaths[0]").value("local-platform"));

        mockMvc.perform(get("/api/engine/modules/paper-assembly"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("paper-assembly"))
                .andExpect(jsonPath("$.dependsOn[0]").value("question-bank"));

        mockMvc.perform(get("/api/engine/supplemental-capabilities"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(6))
                .andExpect(jsonPath("$[0].code").value("review-workbench"));

        mockMvc.perform(get("/api/engine/interfaces"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].groupCode").value("engine-catalog"))
                .andExpect(jsonPath("$[0].method").value("GET"))
                .andExpect(jsonPath("$[0].path").value("/api/engine"));
    }
}
