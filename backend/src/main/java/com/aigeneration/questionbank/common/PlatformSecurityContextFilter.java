package com.aigeneration.questionbank.common;

import com.aigeneration.questionbank.config.PlatformSecurityProperties;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import org.slf4j.MDC;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * 生产平台接入上下文兜底校验过滤器。
 *
 * <p>该过滤器默认关闭，不替代平台网关鉴权。生产环境开启后，Java backend 会拒绝缺少
 * 租户、操作人或授权头的业务 API 请求，避免 OCR 长任务在无上下文情况下落库或触发回调。</p>
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 10)
public class PlatformSecurityContextFilter extends OncePerRequestFilter {

    private final PlatformSecurityProperties properties;
    private final ObjectMapper objectMapper;

    public PlatformSecurityContextFilter(
            PlatformSecurityProperties properties,
            ObjectMapper objectMapper
    ) {
        this.properties = properties;
        this.objectMapper = objectMapper;
    }

    /**
     * 根据配置决定是否跳过当前请求。
     *
     * @param request 当前 HTTP 请求
     * @return true 表示跳过安全上下文校验
     */
    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        if (!properties.contextValidationEnabled()) {
            return true;
        }
        String path = request.getRequestURI();
        return properties.excludedPathPrefixes().stream().anyMatch(path::startsWith);
    }

    /**
     * 校验生产接入必需的上下文 header。
     *
     * @param request 当前 HTTP 请求
     * @param response 当前 HTTP 响应
     * @param filterChain 后续过滤器链
     * @throws ServletException Servlet 处理异常
     * @throws IOException 请求或响应 I/O 异常
     */
    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain
    ) throws ServletException, IOException {
        List<String> missing = new ArrayList<>();
        for (String header : properties.requiredHeaders()) {
            if (isBlank(request.getHeader(header))) {
                missing.add(header);
            }
        }
        if (properties.authorizationRequired() && isBlank(request.getHeader("Authorization"))) {
            missing.add("Authorization");
        }
        if (!missing.isEmpty()) {
            response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
            response.setContentType(MediaType.APPLICATION_JSON_VALUE);
            response.setCharacterEncoding("UTF-8");
            String traceId = MDC.get(TraceIdFilter.MDC_KEY);
            objectMapper.writeValue(
                    response.getWriter(),
                    ApiResponse.failed("Missing required platform security headers: " + String.join(", ", missing), traceId)
            );
            return;
        }
        filterChain.doFilter(request, response);
    }

    private static boolean isBlank(String value) {
        return value == null || value.isBlank();
    }
}
