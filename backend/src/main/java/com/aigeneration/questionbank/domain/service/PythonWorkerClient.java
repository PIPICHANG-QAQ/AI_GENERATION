package com.aigeneration.questionbank.domain.service;

import com.aigeneration.questionbank.config.PythonWorkerProperties;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.net.URI;
import java.time.Duration;
import java.util.Map;
import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import okhttp3.ResponseBody;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.util.UriComponentsBuilder;

/**
 * Python worker HTTP 客户端。
 *
 * <p>统一处理 Java 到 Python worker 的 JSON 请求、文件请求、超时配置、代理开关、错误转换和
 * 响应头复制，避免业务服务重复拼接 OkHttp 调用逻辑。</p>
 */
@Service
public class PythonWorkerClient {
    /**
     * JSON 响应按通用 Map 读取。
     */
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {
    };

    /**
     * Python worker 连接配置。
     */
    private final PythonWorkerProperties properties;

    /**
     * JSON 序列化/反序列化组件。
     */
    private final ObjectMapper objectMapper;

    /**
     * 注入 worker 配置和 JSON 处理器。
     *
     * @param properties Python worker 配置
     * @param objectMapper JSON 处理器
     */
    public PythonWorkerClient(PythonWorkerProperties properties, ObjectMapper objectMapper) {
        this.properties = properties;
        this.objectMapper = objectMapper;
    }

    /**
     * 发起 GET JSON 请求。
     *
     * @param path worker 路径
     * @return JSON Map 响应
     */
    public Map<String, Object> getJson(String path) {
        return jsonRequest("GET", path, null);
    }

    /**
     * 发起 POST JSON 请求。
     *
     * @param path worker 路径
     * @param payload 请求体
     * @return JSON Map 响应
     */
    public Map<String, Object> postJson(String path, Object payload) {
        return jsonRequest("POST", path, payload);
    }

    /**
     * 发起 PUT JSON 请求。
     *
     * @param path worker 路径
     * @param payload 请求体
     * @return JSON Map 响应
     */
    public Map<String, Object> putJson(String path, Object payload) {
        return jsonRequest("PUT", path, payload);
    }

    /**
     * 发起 DELETE JSON 请求。
     *
     * @param path worker 路径
     * @return JSON Map 响应
     */
    public Map<String, Object> deleteJson(String path) {
        return jsonRequest("DELETE", path, null);
    }

    /**
     * 发起 GET 文件请求。
     *
     * @param path worker 路径
     * @return 文件字节响应
     */
    public ResponseEntity<byte[]> getFile(String path) {
        return fileRequest("GET", path, null);
    }

    /**
     * 发起 POST JSON 并读取文件响应。
     *
     * @param path worker 路径
     * @param payload JSON 请求体
     * @return 文件字节响应
     */
    public ResponseEntity<byte[]> postJsonForFile(String path, Object payload) {
        return fileRequest("POST", path, payload);
    }

    /**
     * 发起 JSON 请求并解析 Map 响应。
     *
     * @param method HTTP 方法
     * @param path worker 路径
     * @param payload 请求体
     * @return JSON Map 响应
     */
    private Map<String, Object> jsonRequest(String method, String path, Object payload) {
        try (Response response = execute(method, path, payload)) {
            String body = readBody(response);
            if (!response.isSuccessful()) {
                throw new ResponseStatusException(HttpStatus.valueOf(response.code()), body);
            }
            return readMap(body);
        } catch (ResponseStatusException ex) {
            throw ex;
        } catch (IOException ex) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Python worker request failed: " + ex.getMessage());
        }
    }

    /**
     * 发起文件请求并复制关键响应头。
     *
     * @param method HTTP 方法
     * @param path worker 路径
     * @param payload 请求体
     * @return 文件字节响应
     */
    private ResponseEntity<byte[]> fileRequest(String method, String path, Object payload) {
        try (Response response = execute(method, path, payload)) {
            if (!response.isSuccessful()) {
                throw new ResponseStatusException(HttpStatus.valueOf(response.code()), readBody(response));
            }
            ResponseBody body = response.body();
            byte[] bytes = body == null ? new byte[0] : body.bytes();
            ResponseEntity.BodyBuilder builder = ResponseEntity.status(response.code());
            copyHeader(response, builder, HttpHeaders.CONTENT_TYPE);
            copyHeader(response, builder, HttpHeaders.CONTENT_DISPOSITION);
            copyHeader(response, builder, HttpHeaders.CONTENT_LENGTH);
            return builder.body(bytes);
        } catch (ResponseStatusException ex) {
            throw ex;
        } catch (IOException ex) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Python worker file request failed: " + ex.getMessage());
        }
    }

    /**
     * 构造并执行底层 OkHttp 请求。
     *
     * @param method HTTP 方法
     * @param path worker 路径
     * @param payload 请求体
     * @return OkHttp 响应，调用方负责关闭
     * @throws IOException 网络调用失败时抛出
     */
    private Response execute(String method, String path, Object payload) throws IOException {
        if (!properties.isEnabled() || !properties.isApiProxyEnabled()) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Python worker API proxy is disabled");
        }
        URI targetUri = UriComponentsBuilder.fromHttpUrl(properties.getBaseUrl())
                .path(path)
                .build(true)
                .toUri();
        RequestBody requestBody = payload == null ? null : jsonBody(payload);
        if (requestBody == null && allowsEmptyRequestBody(method)) {
            requestBody = RequestBody.create(new byte[0], null);
        }
        Request request = new Request.Builder()
                .url(targetUri.toString())
                .method(method, requestBody)
                .build();
        return client().newCall(request).execute();
    }

    /**
     * 按配置构造 OkHttp 客户端。
     *
     * @return OkHttp 客户端
     */
    private OkHttpClient client() {
        return new OkHttpClient.Builder()
                .connectTimeout(Duration.ofMillis(properties.getConnectTimeoutMs()))
                .readTimeout(Duration.ofMillis(properties.getReadTimeoutMs()))
                .writeTimeout(Duration.ofMillis(properties.getReadTimeoutMs()))
                .build();
    }

    /**
     * 将 Java 对象序列化为 JSON 请求体。
     *
     * @param payload 请求载荷
     * @return JSON 请求体
     */
    private RequestBody jsonBody(Object payload) {
        try {
            return RequestBody.create(
                    objectMapper.writeValueAsBytes(payload),
                    MediaType.parse("application/json; charset=utf-8")
            );
        } catch (JsonProcessingException ex) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid Python worker payload");
        }
    }

    /**
     * 判断 HTTP 方法是否允许空请求体。
     *
     * @param method HTTP 方法
     * @return true 表示需要发送空请求体
     */
    private boolean allowsEmptyRequestBody(String method) {
        return "POST".equalsIgnoreCase(method)
                || "PUT".equalsIgnoreCase(method)
                || "PATCH".equalsIgnoreCase(method)
                || "DELETE".equalsIgnoreCase(method);
    }

    /**
     * 读取响应体文本。
     *
     * @param response OkHttp 响应
     * @return 响应文本；空响应体返回空 JSON
     * @throws IOException 读取失败时抛出
     */
    private String readBody(Response response) throws IOException {
        ResponseBody body = response.body();
        return body == null ? "{}" : body.string();
    }

    /**
     * 将 JSON 文本解析为 Map。
     *
     * @param body JSON 文本
     * @return 解析后的 Map
     */
    private Map<String, Object> readMap(String body) {
        try {
            return objectMapper.readValue(body == null || body.isBlank() ? "{}" : body, MAP_TYPE);
        } catch (JsonProcessingException ex) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Python worker returned invalid JSON");
        }
    }

    /**
     * 从 worker 响应复制指定响应头。
     *
     * @param response worker 响应
     * @param builder Java 响应构造器
     * @param name 响应头名称
     */
    private void copyHeader(Response response, ResponseEntity.BodyBuilder builder, String name) {
        String value = response.header(name);
        if (value != null && !value.isBlank()) {
            builder.header(name, value);
        }
    }
}
