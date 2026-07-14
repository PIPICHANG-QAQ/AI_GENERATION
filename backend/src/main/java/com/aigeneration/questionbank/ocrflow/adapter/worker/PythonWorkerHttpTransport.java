package com.aigeneration.questionbank.ocrflow.adapter.worker;

import com.aigeneration.questionbank.config.PythonWorkerProperties;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.net.SocketTimeoutException;
import java.net.URI;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;
import okhttp3.MediaType;
import okhttp3.MultipartBody;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.ResponseBody;
import org.springframework.stereotype.Component;
import org.springframework.web.util.UriComponentsBuilder;

/** Single HTTP transport used by future worker ports. It intentionally has no domain knowledge. */
@Component
public final class PythonWorkerHttpTransport {
    private static final MediaType JSON = MediaType.parse("application/json; charset=utf-8");
    private final PythonWorkerProperties properties;
    private final ObjectMapper objectMapper;
    private final OkHttpClient client;

    public PythonWorkerHttpTransport(PythonWorkerProperties properties, ObjectMapper objectMapper) {
        this.properties = properties;
        this.objectMapper = objectMapper;
        this.client = new OkHttpClient.Builder()
                .connectTimeout(Duration.ofMillis(properties.getConnectTimeoutMs()))
                .readTimeout(Duration.ofMillis(properties.getReadTimeoutMs()))
                .writeTimeout(Duration.ofMillis(properties.getReadTimeoutMs()))
                .build();
    }

    public Response getJson(String path) {
        return execute("GET", path, null);
    }

    public Response postJson(String path, Object payload) {
        return execute("POST", path, jsonBody(payload));
    }

    public Response putJson(String path, Object payload) {
        return execute("PUT", path, jsonBody(payload));
    }

    public Response deleteJson(String path) {
        return execute("DELETE", path, null);
    }

    public Response get(String path) {
        return execute("GET", path, null);
    }

    public Response postMultipart(
            String path,
            String fieldName,
            String fileName,
            byte[] file,
            String contentType,
            Map<String, String> fields
    ) {
        MultipartBody.Builder multipart = new MultipartBody.Builder().setType(MultipartBody.FORM);
        if (fields != null) {
            fields.forEach((key, value) -> multipart.addFormDataPart(key, value == null ? "" : value));
        }
        multipart.addFormDataPart(
                fieldName,
                fileName,
                RequestBody.create(file == null ? new byte[0] : file, MediaType.parse(contentType))
        );
        return execute("POST", path, multipart.build());
    }

    private Response execute(String method, String path, RequestBody body) {
        if (!properties.isEnabled() || !properties.isApiProxyEnabled()) {
            throw new WorkerHttpException(503, "Python worker API proxy is disabled", false, null);
        }
        URI target = targetUri(path);
        RequestBody requestBody = body;
        if (requestBody == null && allowsEmptyBody(method)) {
            requestBody = RequestBody.create(new byte[0], null);
        }
        Request request = new Request.Builder().url(target.toString()).method(method, requestBody).build();
        try (okhttp3.Response response = client.newCall(request).execute()) {
            ResponseBody responseBody = response.body();
            byte[] bytes = responseBody == null ? new byte[0] : responseBody.bytes();
            Map<String, String> headers = new LinkedHashMap<>();
            for (String name : response.headers().names()) {
                headers.put(name, response.header(name, ""));
            }
            if (!response.isSuccessful()) {
                throw new WorkerHttpException(
                        response.code(),
                        new String(bytes, java.nio.charset.StandardCharsets.UTF_8),
                        false,
                        null
                );
            }
            return new Response(response.code(), bytes, headers);
        } catch (WorkerHttpException ex) {
            throw ex;
        } catch (SocketTimeoutException ex) {
            throw new WorkerHttpException(-1, "Python worker request timed out", true, ex);
        } catch (IOException ex) {
            throw new WorkerHttpException(-1, "Python worker request failed: " + ex.getMessage(), false, ex);
        }
    }

    private RequestBody jsonBody(Object payload) {
        try {
            return RequestBody.create(objectMapper.writeValueAsBytes(payload), JSON);
        } catch (JsonProcessingException ex) {
            throw new WorkerHttpException(400, "Invalid Python worker payload", false, ex);
        }
    }

    private URI targetUri(String path) {
        String requestPath = path == null || path.isBlank() ? "/" : path;
        int queryIndex = requestPath.indexOf('?');
        UriComponentsBuilder builder = UriComponentsBuilder.fromHttpUrl(properties.getBaseUrl());
        if (queryIndex < 0) {
            builder.path(requestPath);
        } else {
            builder.path(requestPath.substring(0, queryIndex));
            builder.query(requestPath.substring(queryIndex + 1));
        }
        return builder.build(true).toUri();
    }

    private boolean allowsEmptyBody(String method) {
        return "POST".equalsIgnoreCase(method)
                || "PUT".equalsIgnoreCase(method)
                || "PATCH".equalsIgnoreCase(method)
                || "DELETE".equalsIgnoreCase(method);
    }

    public record Response(int statusCode, byte[] body, Map<String, String> headers) {
        public Response {
            body = body == null ? new byte[0] : body.clone();
            headers = headers == null ? Map.of() : Map.copyOf(headers);
        }

        public String header(String name) {
            if (name == null) return null;
            String value = headers.get(name);
            if (value != null) return value;
            return headers.entrySet().stream()
                    .filter(entry -> name.equalsIgnoreCase(entry.getKey()))
                    .map(Map.Entry::getValue)
                    .findFirst()
                    .orElse(null);
        }
    }

    public static final class WorkerHttpException extends RuntimeException {
        private final int statusCode;
        private final String body;
        private final boolean timeout;

        public WorkerHttpException(int statusCode, String body, boolean timeout, Throwable cause) {
            super(body, cause);
            this.statusCode = statusCode;
            this.body = body == null ? "" : body;
            this.timeout = timeout;
        }

        public int statusCode() { return statusCode; }
        public String body() { return body; }
        public boolean timeout() { return timeout; }
    }
}
