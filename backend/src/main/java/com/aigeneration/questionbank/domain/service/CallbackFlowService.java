package com.aigeneration.questionbank.domain.service;

import com.aigeneration.questionbank.config.EnterpriseProperties;
import com.aigeneration.questionbank.domain.entity.CallbackEventEntity;
import com.aigeneration.questionbank.domain.mapper.CallbackEventMapper;
import com.aigeneration.questionbank.domain.support.Ids;
import com.aigeneration.questionbank.domain.support.JsonSupport;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

/**
 * Callback-Flow 回调服务。
 *
 * <p>负责创建回调事件、按 HMAC-SHA256 签名发送 HTTP 回调、记录响应、计算重试时间和
 * 死信状态。未接入 MQ 时，本地表承担事件记录和重试扫描职责。</p>
 */
@Service
public class CallbackFlowService {
    /**
     * 回调事件表访问对象。
     */
    private final CallbackEventMapper mapper;

    /**
     * JSON 辅助组件，用于保存事件 payload 和响应快照。
     */
    private final JsonSupport json;

    /**
     * 企业配置，用于 runtime 暴露 MQ 是否启用。
     */
    private final EnterpriseProperties enterpriseProperties;

    /**
     * 注入回调事件 Mapper、JSON 工具和企业配置。
     *
     * @param mapper 回调事件 Mapper
     * @param json JSON 辅助组件
     * @param enterpriseProperties 企业配置
     */
    public CallbackFlowService(CallbackEventMapper mapper, JsonSupport json, EnterpriseProperties enterpriseProperties) {
        this.mapper = mapper;
        this.json = json;
        this.enterpriseProperties = enterpriseProperties;
    }

    /**
     * 返回 Callback-Flow 运行时能力描述。
     *
     * @return runtime 描述 Map
     */
    public Map<String, Object> runtime() {
        return Map.of(
                "capability", "callback-flow",
                "callbackSigner", "HMAC-SHA256",
                "eventTable", "java_callback_events",
                "retryPolicy", Map.of(
                        "localScannerEndpoint", "/api/capabilities/callback-flow/events/retry-due",
                        "deadLetterStatus", "dead_letter",
                        "defaultMaxRetryCount", 3,
                        "idempotencyKeyField", "idempotencyKey"
                ),
                "mq", Map.of(
                        "enabled", enterpriseProperties.getMq().isEnabled(),
                        "provider", enterpriseProperties.getMq().getProvider(),
                        "nameServer", enterpriseProperties.getMq().getNameServer(),
                        "localFallback", !enterpriseProperties.getMq().isEnabled()
                ),
                "eventTypes", List.of("processing.completed", "processing.failed", "processing.retryable", "export.completed", "export.failed")
        );
    }

    /**
     * 创建并立即发送一条回调事件。
     *
     * @param payload 回调请求载荷
     * @return 回调事件状态
     */
    public Map<String, Object> send(Map<String, Object> payload) {
        String callbackUrl = text(payload.get("callbackUrl"));
        if (callbackUrl.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "callbackUrl is required");
        }
        String eventType = value(text(payload.get("eventType")), "callback.test");
        String secret = text(payload.get("secret"));
        Object eventPayload = payload.getOrDefault("payload", Map.of("message", "callback-flow test"));
        CallbackEventEntity event = createEvent(
                eventType,
                text(payload.get("aggregateType")),
                text(payload.get("aggregateId")),
                callbackUrl,
                eventPayload,
                text(payload.get("idempotencyKey")),
                intValue(payload.get("maxRetryCount"), 3)
        );
        if (!"pending".equals(event.getStatus())) {
            return toMap(event);
        }
        deliver(event, secret);
        return toMap(mapper.selectById(event.getId()));
    }

    /**
     * 手动重试指定回调事件。
     *
     * @param eventId 回调事件 ID
     * @param payload 可包含 secret 的重试载荷
     * @return 重试后的事件状态
     */
    public Map<String, Object> retry(String eventId, Map<String, Object> payload) {
        CallbackEventEntity event = mapper.selectById(eventId);
        if (event == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Callback event not found");
        }
        deliver(event, text(payload.get("secret")));
        return toMap(mapper.selectById(eventId));
    }

    /**
     * 重试所有已到期的失败事件。
     *
     * @param payload 可包含 secret 的扫描载荷
     * @return 重试统计
     */
    public Map<String, Object> retryDue(Map<String, Object> payload) {
        LocalDateTime now = LocalDateTime.now();
        QueryWrapper<CallbackEventEntity> query = new QueryWrapper<CallbackEventEntity>()
                .eq("status", "failed")
                .le("next_retry_at", now)
                .orderByAsc("next_retry_at");
        List<CallbackEventEntity> dueEvents = mapper.selectList(query);
        int retried = 0;
        int deadLettered = 0;
        String secret = text(payload.get("secret"));
        for (CallbackEventEntity event : dueEvents) {
            if (event.getRetryCount() != null && event.getMaxRetryCount() != null
                    && event.getRetryCount() >= event.getMaxRetryCount()) {
                event.setStatus("dead_letter");
                event.setNextRetryAt(null);
                event.setUpdatedAt(now);
                mapper.updateById(event);
                deadLettered++;
                continue;
            }
            deliver(event, secret);
            CallbackEventEntity updated = mapper.selectById(event.getId());
            if ("dead_letter".equals(updated.getStatus())) {
                deadLettered++;
            } else {
                retried++;
            }
        }
        return Map.of("retried", retried, "deadLettered", deadLettered, "total", dueEvents.size());
    }

    /**
     * 查询回调事件列表。
     *
     * @param status 状态过滤
     * @return 回调事件列表响应
     */
    public Map<String, Object> list(String status) {
        QueryWrapper<CallbackEventEntity> query = new QueryWrapper<CallbackEventEntity>().orderByDesc("created_at");
        if (status != null && !status.isBlank()) {
            query.eq("status", status);
        }
        List<Map<String, Object>> items = mapper.selectList(query).stream().map(this::toMap).toList();
        return Map.of("items", items, "total", items.size());
    }

    /**
     * 创建回调事件。
     *
     * <p>如果提供 idempotencyKey 且已有事件，则直接返回已有事件，避免重复发送相同业务事件。</p>
     *
     * @param eventType 事件类型
     * @param aggregateType 聚合类型
     * @param aggregateId 聚合 ID
     * @param callbackUrl 回调 URL
     * @param payload 回调载荷
     * @param idempotencyKey 幂等键
     * @param maxRetryCount 最大重试次数
     * @return 回调事件实体
     */
    private CallbackEventEntity createEvent(
            String eventType,
            String aggregateType,
            String aggregateId,
            String callbackUrl,
            Object payload,
            String idempotencyKey,
            int maxRetryCount
    ) {
        if (!idempotencyKey.isBlank()) {
            CallbackEventEntity existing = mapper.selectOne(new QueryWrapper<CallbackEventEntity>()
                    .eq("idempotency_key", idempotencyKey)
                    .last("LIMIT 1"));
            if (existing != null) {
                return existing;
            }
        }
        LocalDateTime now = LocalDateTime.now();
        CallbackEventEntity event = new CallbackEventEntity();
        event.setId(Ids.next("callback_event"));
        event.setEventType(eventType);
        event.setAggregateType(aggregateType);
        event.setAggregateId(aggregateId);
        event.setStatus("pending");
        event.setCallbackUrl(callbackUrl);
        event.setIdempotencyKey(idempotencyKey);
        event.setPayloadJson(json.write(payload));
        event.setRetryCount(0);
        event.setMaxRetryCount(Math.max(1, maxRetryCount));
        event.setNextRetryAt(null);
        event.setCreatedAt(now);
        event.setUpdatedAt(now);
        mapper.insert(event);
        return event;
    }

    /**
     * 投递回调事件并更新事件状态。
     *
     * @param event 回调事件实体
     * @param secret 签名密钥，可为空
     */
    private void deliver(CallbackEventEntity event, String secret) {
        try {
            String body = event.getPayloadJson();
            RequestBody requestBody = RequestBody.create(body.getBytes(StandardCharsets.UTF_8), MediaType.parse("application/json; charset=utf-8"));
            Request.Builder builder = new Request.Builder()
                    .url(event.getCallbackUrl())
                    .post(requestBody)
                    .header("X-Question-Engine-Event", event.getEventType())
                    .header("X-Question-Engine-Event-Id", event.getId());
            if (!secret.isBlank()) {
                builder.header("X-Question-Engine-Signature", signature(secret, body));
            }
            try (Response response = client().newCall(builder.build()).execute()) {
                updateDeliveryState(event, response.isSuccessful(), response.isSuccessful() ? "" : "HTTP " + response.code());
                event.setResponseJson(json.write(Map.of("statusCode", response.code(), "message", response.message())));
            }
        } catch (Exception ex) {
            updateDeliveryState(event, false, ex.getMessage());
            event.setResponseJson(json.write(Map.of("error", ex.getMessage())));
        }
        event.setUpdatedAt(LocalDateTime.now());
        mapper.updateById(event);
    }

    /**
     * 根据投递结果更新状态、失败原因和下次重试时间。
     *
     * @param event 回调事件实体
     * @param success 是否投递成功
     * @param failureReason 失败原因
     */
    private void updateDeliveryState(CallbackEventEntity event, boolean success, String failureReason) {
        int attempt = (event.getRetryCount() == null ? 0 : event.getRetryCount()) + 1;
        int maxRetryCount = event.getMaxRetryCount() == null ? 3 : event.getMaxRetryCount();
        event.setRetryCount(attempt);
        if (success) {
            event.setStatus("sent");
            event.setFailureReason("");
            event.setNextRetryAt(null);
            return;
        }
        event.setFailureReason(failureReason);
        if (attempt >= maxRetryCount) {
            event.setStatus("dead_letter");
            event.setNextRetryAt(null);
        } else {
            event.setStatus("failed");
            long delaySeconds = Math.min(60L, 5L * attempt);
            event.setNextRetryAt(LocalDateTime.now().plusSeconds(delaySeconds));
        }
    }

    /**
     * 构造回调用 HTTP 客户端。
     *
     * @return OkHttp 客户端
     */
    private OkHttpClient client() {
        return new OkHttpClient.Builder()
                .connectTimeout(Duration.ofSeconds(3))
                .readTimeout(Duration.ofSeconds(10))
                .writeTimeout(Duration.ofSeconds(10))
                .build();
    }

    /**
     * 生成 HMAC-SHA256 回调签名。
     *
     * @param secret 签名密钥
     * @param body 请求体
     * @return sha256= 前缀的十六进制签名
     * @throws Exception 签名算法初始化失败时抛出
     */
    private String signature(String secret, String body) throws Exception {
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
        return "sha256=" + HexFormat.of().formatHex(mac.doFinal(body.getBytes(StandardCharsets.UTF_8)));
    }

    /**
     * 将回调事件实体序列化为 API 响应 Map。
     *
     * @param event 回调事件实体
     * @return 响应 Map
     */
    private Map<String, Object> toMap(CallbackEventEntity event) {
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("id", event.getId());
        item.put("eventType", event.getEventType());
        item.put("aggregateType", event.getAggregateType());
        item.put("aggregateId", event.getAggregateId());
        item.put("status", event.getStatus());
        item.put("callbackUrl", event.getCallbackUrl());
        item.put("idempotencyKey", event.getIdempotencyKey());
        item.put("payload", json.readMap(event.getPayloadJson()));
        item.put("response", json.readMap(event.getResponseJson()));
        item.put("failureReason", event.getFailureReason());
        item.put("retryCount", event.getRetryCount());
        item.put("maxRetryCount", event.getMaxRetryCount());
        item.put("nextRetryAt", event.getNextRetryAt());
        item.put("createdAt", event.getCreatedAt());
        item.put("updatedAt", event.getUpdatedAt());
        return item;
    }

    /**
     * 将对象转换为去首尾空白文本。
     *
     * @param value 原始值
     * @return 文本；null 返回空字符串
     */
    private String text(Object value) {
        return value == null ? "" : String.valueOf(value).trim();
    }

    /**
     * 返回非空字符串或兜底值。
     *
     * @param value 原始字符串
     * @param fallback 兜底值
     * @return 非空字符串或兜底值
     */
    private String value(String value, String fallback) {
        return value == null || value.isBlank() ? fallback : value;
    }

    /**
     * 将对象转换为整数。
     *
     * @param value 原始值
     * @param fallback 解析失败时的兜底值
     * @return 整数
     */
    private int intValue(Object value, int fallback) {
        if (value instanceof Number number) {
            return number.intValue();
        }
        try {
            return Integer.parseInt(text(value));
        } catch (NumberFormatException ignored) {
            return fallback;
        }
    }
}
