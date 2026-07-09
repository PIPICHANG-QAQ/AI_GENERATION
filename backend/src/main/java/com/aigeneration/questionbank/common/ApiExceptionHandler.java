package com.aigeneration.questionbank.common;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.server.ResponseStatusException;

/**
 * 统一输出 API 业务异常，避免 Spring 默认错误页丢失 ResponseStatusException 的 reason。
 */
@RestControllerAdvice
public class ApiExceptionHandler {
    private final ObjectMapper objectMapper;

    public ApiExceptionHandler(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    @ExceptionHandler(ResponseStatusException.class)
    public ResponseEntity<Map<String, Object>> handleResponseStatus(
            ResponseStatusException exception,
            HttpServletRequest request
    ) {
        HttpStatusCode status = exception.getStatusCode();
        String detail = extractDetail(exception.getReason());
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("timestamp", OffsetDateTime.now().toString());
        body.put("status", status.value());
        body.put("error", status.toString());
        body.put("detail", detail);
        body.put("message", detail);
        body.put("path", request.getRequestURI());
        return ResponseEntity.status(status).body(body);
    }

    private String extractDetail(String reason) {
        if (reason == null || reason.isBlank()) {
            return "请求处理失败";
        }
        String text = reason.trim();
        if (!text.startsWith("{")) {
            return text;
        }
        try {
            Map<String, Object> payload = objectMapper.readValue(text, new TypeReference<>() {});
            for (String key : new String[] {"detail", "message", "error"}) {
                Object value = payload.get(key);
                if (value instanceof String stringValue && !stringValue.isBlank()) {
                    return stringValue;
                }
            }
        } catch (Exception ignored) {
            return text;
        }
        return text;
    }
}
