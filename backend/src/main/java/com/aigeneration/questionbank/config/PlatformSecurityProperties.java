package com.aigeneration.questionbank.config;

import java.util.List;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 平台接入安全上下文校验配置。
 *
 * <p>本地开发默认不强制校验，由平台网关或 BFF 负责鉴权。生产环境可开启
 * {@code platform.security.context-validation-enabled}，让 Java backend 在能力 API
 * 边界上兜底校验租户、操作人和授权头，避免网关漏配时静默创建跨租户任务。</p>
 */
@ConfigurationProperties(prefix = "platform.security")
public record PlatformSecurityProperties(
        boolean contextValidationEnabled,
        boolean authorizationRequired,
        List<String> requiredHeaders,
        List<String> excludedPathPrefixes
) {
    /**
     * 补齐默认值，保持本地环境无侵入。
     *
     * @param contextValidationEnabled 是否启用上下文 header 校验
     * @param authorizationRequired 是否要求 Authorization header
     * @param requiredHeaders 必填上下文 header
     * @param excludedPathPrefixes 不需要校验的路径前缀
     */
    public PlatformSecurityProperties {
        if (requiredHeaders == null || requiredHeaders.isEmpty()) {
            requiredHeaders = List.of("X-Tenant-Id", "X-Operator-Id");
        }
        if (excludedPathPrefixes == null || excludedPathPrefixes.isEmpty()) {
            excludedPathPrefixes = List.of(
                    "/actuator",
                    "/v3/api-docs",
                    "/swagger-ui",
                    "/doc.html",
                    "/webjars",
                    "/favicon.ico",
                    "/api/java/health",
                    "/api/java/worker",
                    "/api/java/stack",
                    "/api/java/enterprise"
            );
        }
    }
}
