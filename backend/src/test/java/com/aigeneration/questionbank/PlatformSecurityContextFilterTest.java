package com.aigeneration.questionbank;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;

/**
 * 平台生产接入上下文校验过滤器测试。
 *
 * <p>本地开发默认关闭该过滤器；本测试显式开启，确保生产开关打开后，业务 API
 * 会拒绝缺少租户、操作人或 Authorization 的请求，同时保留健康检查给网关探活使用。</p>
 */
@SpringBootTest(properties = {
        "java-domain.migration.enabled=false",
        "spring.datasource.url=jdbc:h2:mem:platform-security-test;MODE=MySQL;DATABASE_TO_LOWER=TRUE;CASE_INSENSITIVE_IDENTIFIERS=TRUE",
        "python-worker.api-proxy-enabled=false",
        "platform.security.context-validation-enabled=true",
        "platform.security.authorization-required=true"
})
@AutoConfigureMockMvc
class PlatformSecurityContextFilterTest {

    @Autowired
    private MockMvc mockMvc;

    /**
     * 缺少生产上下文 header 时，能力 API 必须被拒绝。
     *
     * @throws Exception MockMvc 调用失败时抛出
     */
    @Test
    void rejectsCapabilityRequestWithoutPlatformHeaders() throws Exception {
        mockMvc.perform(get("/api/capabilities"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.message").value("Missing required platform security headers: X-Tenant-Id, X-Operator-Id, Authorization"))
                .andExpect(header().exists("X-Trace-Id"));
    }

    /**
     * 带齐平台上下文 header 后，能力 API 应正常放行。
     *
     * @throws Exception MockMvc 调用失败时抛出
     */
    @Test
    void allowsCapabilityRequestWithPlatformHeaders() throws Exception {
        mockMvc.perform(get("/api/capabilities")
                        .header("Authorization", "Bearer test-token")
                        .header("X-Tenant-Id", "tenant-001")
                        .header("X-Operator-Id", "teacher-001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(8));
    }

    /**
     * 健康检查必须保留给平台网关和 Kubernetes 探活使用，不强制业务上下文。
     *
     * @throws Exception MockMvc 调用失败时抛出
     */
    @Test
    void healthCheckIsExcludedFromPlatformHeaderValidation() throws Exception {
        mockMvc.perform(get("/api/java/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));
    }
}
