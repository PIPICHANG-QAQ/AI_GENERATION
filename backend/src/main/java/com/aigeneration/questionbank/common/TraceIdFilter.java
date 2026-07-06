package com.aigeneration.questionbank.common;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.Optional;
import java.util.UUID;
import org.slf4j.MDC;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * 为每个 HTTP 请求注入 TraceId 的 Servlet 过滤器。
 *
 * <p>如果调用方已经通过 {@value #TRACE_ID_HEADER} 传入链路 ID，则沿用该值；否则生成 UUID。
 * TraceId 会同时写入响应头和 SLF4J MDC，后续 controller、service 和日志输出都可以复用同一个值。</p>
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class TraceIdFilter extends OncePerRequestFilter {

    /** 前端、网关或调用方传递/接收 traceId 的 HTTP header 名称。 */
    public static final String TRACE_ID_HEADER = "X-Trace-Id";
    /** 写入 SLF4J MDC 的 key，控制器可用它把 traceId 放入响应体。 */
    public static final String MDC_KEY = "traceId";

    /**
     * 为当前请求准备 traceId 并在请求结束后清理 MDC。
     *
     * @param request 当前 HTTP 请求
     * @param response 当前 HTTP 响应
     * @param filterChain 后续过滤器链和 DispatcherServlet
     * @throws ServletException Servlet 处理异常
     * @throws IOException 请求或响应 I/O 异常
     */
    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain
    ) throws ServletException, IOException {
        String traceId = Optional.ofNullable(request.getHeader(TRACE_ID_HEADER))
                .filter(value -> !value.isBlank())
                .orElseGet(() -> UUID.randomUUID().toString());
        MDC.put(MDC_KEY, traceId);
        response.setHeader(TRACE_ID_HEADER, traceId);
        try {
            filterChain.doFilter(request, response);
        } finally {
            // 清理线程本地 MDC，避免 Tomcat 工作线程复用时串到下一次请求。
            MDC.remove(MDC_KEY);
        }
    }
}
