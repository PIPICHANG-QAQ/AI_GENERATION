package com.aigeneration.questionbank.proxy;

import com.aigeneration.questionbank.config.PythonWorkerProperties;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.net.URI;
import java.time.Duration;
import java.util.Collections;
import java.util.Locale;
import java.util.Set;
import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.RequestBody;
import okhttp3.Response;
import okhttp3.ResponseBody;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.util.UriComponentsBuilder;

/**
 * Python worker API 代理过滤器。
 *
 * <p>该过滤器只代理仍由 Python worker 承接的 {@code /api/**} 请求；Java 已接管的
 * engine、capability、导入任务、题库、组卷、知识点、题图、AI 和导出路径会跳过过滤器，
 * 交给 Spring MVC 控制器处理。</p>
 */
@Component
@Order(Ordered.LOWEST_PRECEDENCE)
public class PythonWorkerProxyFilter extends OncePerRequestFilter {

    /**
     * 不应透传给下游或客户端的逐跳 HTTP 头。
     */
    private static final Set<String> HOP_BY_HOP_HEADERS = Set.of(
            "connection",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailer",
            "transfer-encoding",
            "upgrade",
            "host",
            "content-length"
    );

    /**
     * Python worker 连接和代理开关配置。
     */
    private final PythonWorkerProperties properties;

    /**
     * 注入 Python worker 配置。
     *
     * @param properties Python worker 配置
     */
    public PythonWorkerProxyFilter(PythonWorkerProperties properties) {
        this.properties = properties;
    }

    /**
     * 判断当前请求是否跳过代理。
     *
     * @param request HTTP 请求
     * @return true 表示不进入 Python worker 代理
     */
    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String path = request.getRequestURI();
        return !path.startsWith("/api/")
                || path.startsWith("/api/java/")
                || path.startsWith("/api/engine")
                || path.startsWith("/api/capabilities/")
                || path.equals("/api/capabilities")
                || isJavaDomainPath(path, request.getMethod())
                || "OPTIONS".equalsIgnoreCase(request.getMethod());
    }

    /**
     * 判断路径是否已经由 Java domain/controller 接管。
     *
     * @param path 请求路径
     * @param method HTTP 方法
     * @return true 表示该路径由 Java 处理
     */
    private boolean isJavaDomainPath(String path, String method) {
        if (path.startsWith("/api/knowledge-points")) {
            return true;
        }
        if ("POST".equalsIgnoreCase(method)
                && (path.equals("/api/import-tasks") || path.equals("/api/import-tasks/batch-delete"))) {
            return true;
        }
        if (("PUT".equalsIgnoreCase(method) || "DELETE".equalsIgnoreCase(method))
                && path.matches("^/api/import-tasks/[^/]+$")) {
            return true;
        }
        if ("POST".equalsIgnoreCase(method) && path.matches("^/api/import-tasks/[^/]+/retry$")) {
            return true;
        }
        if ("GET".equalsIgnoreCase(method)
                && (path.equals("/api/import-tasks")
                || path.matches("^/api/import-tasks/[^/]+$")
                || path.matches("^/api/import-tasks/[^/]+/source/(paper|answer)$"))) {
            return true;
        }
        if (path.matches("^/api/import-tasks/[^/]+/questions/[^/]+/bank$") || path.matches("^/api/import-tasks/[^/]+/bank$")) {
            return true;
        }
        if (path.matches("^/api/import-tasks/[^/]+/image-library$")
                || path.matches("^/api/import-tasks/[^/]+/questions/[^/]+/images(/.*)?$")) {
            return true;
        }
        if (path.matches("^/api/import-tasks/[^/]+/questions/[^/]+/(analysis|standardize/ai)$")) {
            return true;
        }
        if (path.matches("^/api/question-bank/questions/?[^/]*/(image-library|images.*)$")) {
            return true;
        }
        if (path.matches("^/api/question-bank/questions/?[^/]*/(analysis|standardize/ai)$")) {
            return true;
        }
        if (path.equals("/api/markdown/standardize/ai") || path.equals("/api/ai/analysis")) {
            return true;
        }
        if (path.equals("/api/question-bank/questions") || path.matches("^/api/question-bank/questions/[^/]+$")) {
            return true;
        }
        if (path.matches("^/api/papers/[^/]+/export$")) {
            return true;
        }
        return path.equals("/api/papers") || path.matches("^/api/papers/[^/]+$");
    }

    /**
     * 执行代理请求。
     *
     * @param request 原始请求
     * @param response 原始响应
     * @param filterChain 过滤器链
     * @throws ServletException Servlet 异常
     * @throws IOException IO 异常
     */
    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain
    ) throws ServletException, IOException {
        if (!properties.isEnabled() || !properties.isApiProxyEnabled()) {
            response.sendError(HttpServletResponse.SC_SERVICE_UNAVAILABLE, "Python worker API proxy is disabled");
            return;
        }

        URI targetUri = buildTargetUri(request);
        try {
            OkHttpClient client = new OkHttpClient.Builder()
                    .connectTimeout(Duration.ofMillis(properties.getConnectTimeoutMs()))
                    .readTimeout(Duration.ofMillis(properties.getReadTimeoutMs()))
                    .writeTimeout(Duration.ofMillis(properties.getReadTimeoutMs()))
                    .followRedirects(false)
                    .build();
            okhttp3.Request proxyRequest = buildProxyRequest(request, targetUri);
            try (Response proxyResponse = client.newCall(proxyRequest).execute()) {
                writeProxyResponse(response, proxyResponse);
            }
        } catch (Exception ex) {
            response.sendError(HttpServletResponse.SC_BAD_GATEWAY, "Python worker proxy failed: " + ex.getMessage());
        }
    }

    /**
     * 根据原始请求构造 worker 目标 URI。
     *
     * @param request 原始请求
     * @return worker 目标 URI
     */
    private URI buildTargetUri(HttpServletRequest request) {
        UriComponentsBuilder builder = UriComponentsBuilder
                .fromHttpUrl(properties.getBaseUrl())
                .path(request.getRequestURI());
        if (request.getQueryString() != null && !request.getQueryString().isBlank()) {
            builder.query(request.getQueryString());
        }
        return builder.build(true).toUri();
    }

    /**
     * 构造发送给 worker 的 OkHttp 请求。
     *
     * @param request 原始请求
     * @param targetUri worker 目标 URI
     * @return OkHttp 请求
     * @throws IOException 读取请求体失败时抛出
     */
    private okhttp3.Request buildProxyRequest(HttpServletRequest request, URI targetUri) throws IOException {
        byte[] body = request.getInputStream().readAllBytes();
        RequestBody requestBody = buildRequestBody(request, body);
        okhttp3.Request.Builder builder = new okhttp3.Request.Builder()
                .url(targetUri.toString())
                .method(request.getMethod(), requestBody);

        Collections.list(request.getHeaderNames()).forEach(headerName -> {
            if (shouldForwardRequestHeader(headerName, requestBody != null)) {
                Collections.list(request.getHeaders(headerName)).forEach(value -> builder.header(headerName, value));
            }
        });
        return builder.build();
    }

    /**
     * 根据原请求体构造代理请求体。
     *
     * @param request 原始请求
     * @param body 请求体字节
     * @return OkHttp 请求体；无请求体时返回 null
     */
    private RequestBody buildRequestBody(HttpServletRequest request, byte[] body) {
        if (body.length == 0 && allowsEmptyRequestBody(request.getMethod())) {
            return RequestBody.create(new byte[0], null);
        }
        if (body.length == 0) {
            return null;
        }
        MediaType mediaType = request.getContentType() == null ? null : MediaType.parse(request.getContentType());
        return RequestBody.create(body, mediaType);
    }

    /**
     * 判断 HTTP 方法是否允许空请求体。
     *
     * @param method HTTP 方法
     * @return true 表示允许空请求体
     */
    private boolean allowsEmptyRequestBody(String method) {
        return "POST".equalsIgnoreCase(method)
                || "PUT".equalsIgnoreCase(method)
                || "PATCH".equalsIgnoreCase(method)
                || "DELETE".equalsIgnoreCase(method);
    }

    /**
     * 将 worker 响应写回客户端。
     *
     * @param response 原始响应
     * @param proxyResponse worker 响应
     * @throws IOException 写响应失败时抛出
     */
    private void writeProxyResponse(HttpServletResponse response, Response proxyResponse) throws IOException {
        response.setStatus(proxyResponse.code());
        proxyResponse.headers().toMultimap().forEach((name, values) -> {
            if (shouldForwardHeader(name)) {
                values.forEach(value -> response.addHeader(name, value));
            }
        });
        ResponseBody responseBody = proxyResponse.body();
        if (responseBody != null) {
            response.getOutputStream().write(responseBody.bytes());
        }
    }

    /**
     * 判断请求头是否可以转发给 worker。
     *
     * @param headerName 请求头名称
     * @param hasBody 代理请求是否包含请求体
     * @return true 表示可转发
     */
    private boolean shouldForwardRequestHeader(String headerName, boolean hasBody) {
        if (hasBody && HttpHeaders.CONTENT_TYPE.equalsIgnoreCase(headerName)) {
            return false;
        }
        return shouldForwardHeader(headerName);
    }

    /**
     * 判断响应头或请求头是否可转发。
     *
     * @param headerName 头名称
     * @return true 表示可转发
     */
    private boolean shouldForwardHeader(String headerName) {
        String normalized = headerName.toLowerCase(Locale.ROOT);
        return !HOP_BY_HOP_HEADERS.contains(normalized)
                && !HttpHeaders.CONTENT_ENCODING.equalsIgnoreCase(headerName);
    }
}
