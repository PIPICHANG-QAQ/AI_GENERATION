package com.aigeneration.questionbank.domain.service;

import com.aigeneration.questionbank.config.PythonWorkerProperties;
import com.aigeneration.questionbank.ocrflow.adapter.worker.PythonWorkerHttpTransport;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.Map;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

/**
 * Python worker HTTP 客户端。
 *
 * <p>统一处理 Java 到 Python worker 的 JSON 请求、文件请求、错误转换和响应头复制，
 * 底层连接、超时和代理开关由 {@link PythonWorkerHttpTransport} 负责。</p>
 */
@Service
public class PythonWorkerClient {
    /**
     * JSON 响应按通用 Map 读取。
     */
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {
    };

    /**
     * JSON 序列化/反序列化组件。
     */
    private final ObjectMapper objectMapper;

    /**
     * Worker HTTP 传输层。客户端只负责把领域请求映射为兼容的响应，底层连接由该组件复用。
     */
    private final PythonWorkerHttpTransport transport;

    /**
     * 注入 worker 配置和 JSON 处理器。
     *
     * @param properties Python worker 配置
     * @param objectMapper JSON 处理器
     * @param transport Worker HTTP 传输层
     */
    @Autowired
    public PythonWorkerClient(
            PythonWorkerProperties properties,
            ObjectMapper objectMapper,
            PythonWorkerHttpTransport transport
    ) {
        this.objectMapper = objectMapper;
        this.transport = transport;
    }

    /**
     * 保留原有构造函数，供非 Spring 调用方和旧测试继续使用。
     *
     * @param properties Python worker 配置
     * @param objectMapper JSON 处理器
     */
    public PythonWorkerClient(PythonWorkerProperties properties, ObjectMapper objectMapper) {
        this(properties, objectMapper, new PythonWorkerHttpTransport(properties, objectMapper));
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
        try {
            PythonWorkerHttpTransport.Response response = executeJson(method, path, payload);
            String body = readBody(response);
            return readMap(body);
        } catch (PythonWorkerHttpTransport.WorkerHttpException ex) {
            throw translate(ex, "request");
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
        try {
            PythonWorkerHttpTransport.Response response = executeJson(method, path, payload);
            byte[] bytes = response.body();
            ResponseEntity.BodyBuilder builder = ResponseEntity.status(response.statusCode());
            copyHeader(response, builder, HttpHeaders.CONTENT_TYPE);
            copyHeader(response, builder, HttpHeaders.CONTENT_DISPOSITION);
            copyHeader(response, builder, HttpHeaders.CONTENT_LENGTH);
            return builder.body(bytes);
        } catch (PythonWorkerHttpTransport.WorkerHttpException ex) {
            throw translate(ex, "file request");
        }
    }

    /**
     * 通过统一传输层执行 JSON 请求。
     *
     * @param method HTTP 方法
     * @param path worker 路径
     * @param payload 请求体
     * @return 已读取并封装的 worker 响应
     */
    private PythonWorkerHttpTransport.Response executeJson(String method, String path, Object payload) {
        return switch (method.toUpperCase()) {
            case "GET" -> transport.getJson(path);
            case "POST" -> transport.postJson(path, payload);
            case "PUT" -> transport.putJson(path, payload);
            case "DELETE" -> transport.deleteJson(path);
            default -> throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Unsupported Python worker method");
        };
    }

    /**
     * 读取响应体文本。
     *
     * @param response worker 传输响应
     * @return 响应文本；空响应体返回空 JSON
     */
    private String readBody(PythonWorkerHttpTransport.Response response) {
        return response.body().length == 0
                ? "{}"
                : new String(response.body(), java.nio.charset.StandardCharsets.UTF_8);
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
    private void copyHeader(PythonWorkerHttpTransport.Response response, ResponseEntity.BodyBuilder builder, String name) {
        String value = response.header(name);
        if (value != null && !value.isBlank()) {
            builder.header(name, value);
        }
    }

    private ResponseStatusException translate(PythonWorkerHttpTransport.WorkerHttpException exception, String operation) {
        HttpStatus status = HttpStatus.resolve(exception.statusCode());
        if (status != null) {
            return new ResponseStatusException(status, exception.body());
        }
        String message = exception.getMessage();
        if (message == null || message.isBlank()) {
            message = "unknown worker error";
        }
        return new ResponseStatusException(
                HttpStatus.BAD_GATEWAY,
                "Python worker " + operation + " failed: " + message,
                exception.getCause());
    }
}
