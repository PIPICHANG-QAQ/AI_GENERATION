package com.aigeneration.questionbank.domain.entity;

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;

/**
 * 平台回调事件实体。
 *
 * <p>对应 {@code java_callback_events} 表，用于记录 callback-flow 事件的目标 URL、payload、
 * 响应、幂等键、状态、重试次数和下一次重试时间。</p>
 */
@TableName("java_callback_events")
public class CallbackEventEntity {
    @TableId
    private String id;
    private String eventType;
    private String aggregateType;
    private String aggregateId;
    private String status;
    private String callbackUrl;
    private String idempotencyKey;
    private String payloadJson;
    private String responseJson;
    private String failureReason;
    private Integer retryCount;
    private Integer maxRetryCount;
    private LocalDateTime nextRetryAt;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;

    /**
     * 获取 id 字段值。
     *
     * @return id 字段值
     */
    public String getId() { return id; }
    /**
     * 设置 id 字段值。
     *
     * @param id id 字段值
     */
    public void setId(String id) { this.id = id; }
    /**
     * 获取 eventType 字段值。
     *
     * @return eventType 字段值
     */
    public String getEventType() { return eventType; }
    /**
     * 设置 eventType 字段值。
     *
     * @param eventType eventType 字段值
     */
    public void setEventType(String eventType) { this.eventType = eventType; }
    /**
     * 获取 aggregateType 字段值。
     *
     * @return aggregateType 字段值
     */
    public String getAggregateType() { return aggregateType; }
    /**
     * 设置 aggregateType 字段值。
     *
     * @param aggregateType aggregateType 字段值
     */
    public void setAggregateType(String aggregateType) { this.aggregateType = aggregateType; }
    /**
     * 获取 aggregateId 字段值。
     *
     * @return aggregateId 字段值
     */
    public String getAggregateId() { return aggregateId; }
    /**
     * 设置 aggregateId 字段值。
     *
     * @param aggregateId aggregateId 字段值
     */
    public void setAggregateId(String aggregateId) { this.aggregateId = aggregateId; }
    /**
     * 获取 status 字段值。
     *
     * @return status 字段值
     */
    public String getStatus() { return status; }
    /**
     * 设置 status 字段值。
     *
     * @param status status 字段值
     */
    public void setStatus(String status) { this.status = status; }
    /**
     * 获取 callbackUrl 字段值。
     *
     * @return callbackUrl 字段值
     */
    public String getCallbackUrl() { return callbackUrl; }
    /**
     * 设置 callbackUrl 字段值。
     *
     * @param callbackUrl callbackUrl 字段值
     */
    public void setCallbackUrl(String callbackUrl) { this.callbackUrl = callbackUrl; }
    /**
     * 获取 idempotencyKey 字段值。
     *
     * @return idempotencyKey 字段值
     */
    public String getIdempotencyKey() { return idempotencyKey; }
    /**
     * 设置 idempotencyKey 字段值。
     *
     * @param idempotencyKey idempotencyKey 字段值
     */
    public void setIdempotencyKey(String idempotencyKey) { this.idempotencyKey = idempotencyKey; }
    /**
     * 获取 payloadJson 字段值。
     *
     * @return payloadJson 字段值
     */
    public String getPayloadJson() { return payloadJson; }
    /**
     * 设置 payloadJson 字段值。
     *
     * @param payloadJson payloadJson 字段值
     */
    public void setPayloadJson(String payloadJson) { this.payloadJson = payloadJson; }
    /**
     * 获取 responseJson 字段值。
     *
     * @return responseJson 字段值
     */
    public String getResponseJson() { return responseJson; }
    /**
     * 设置 responseJson 字段值。
     *
     * @param responseJson responseJson 字段值
     */
    public void setResponseJson(String responseJson) { this.responseJson = responseJson; }
    /**
     * 获取 failureReason 字段值。
     *
     * @return failureReason 字段值
     */
    public String getFailureReason() { return failureReason; }
    /**
     * 设置 failureReason 字段值。
     *
     * @param failureReason failureReason 字段值
     */
    public void setFailureReason(String failureReason) { this.failureReason = failureReason; }
    /**
     * 获取 retryCount 字段值。
     *
     * @return retryCount 字段值
     */
    public Integer getRetryCount() { return retryCount; }
    /**
     * 设置 retryCount 字段值。
     *
     * @param retryCount retryCount 字段值
     */
    public void setRetryCount(Integer retryCount) { this.retryCount = retryCount; }
    /**
     * 获取 maxRetryCount 字段值。
     *
     * @return maxRetryCount 字段值
     */
    public Integer getMaxRetryCount() { return maxRetryCount; }
    /**
     * 设置 maxRetryCount 字段值。
     *
     * @param maxRetryCount maxRetryCount 字段值
     */
    public void setMaxRetryCount(Integer maxRetryCount) { this.maxRetryCount = maxRetryCount; }
    /**
     * 获取 nextRetryAt 字段值。
     *
     * @return nextRetryAt 字段值
     */
    public LocalDateTime getNextRetryAt() { return nextRetryAt; }
    /**
     * 设置 nextRetryAt 字段值。
     *
     * @param nextRetryAt nextRetryAt 字段值
     */
    public void setNextRetryAt(LocalDateTime nextRetryAt) { this.nextRetryAt = nextRetryAt; }
    /**
     * 获取 createdAt 字段值。
     *
     * @return createdAt 字段值
     */
    public LocalDateTime getCreatedAt() { return createdAt; }
    /**
     * 设置 createdAt 字段值。
     *
     * @param createdAt createdAt 字段值
     */
    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
    /**
     * 获取 updatedAt 字段值。
     *
     * @return updatedAt 字段值
     */
    public LocalDateTime getUpdatedAt() { return updatedAt; }
    /**
     * 设置 updatedAt 字段值。
     *
     * @param updatedAt updatedAt 字段值
     */
    public void setUpdatedAt(LocalDateTime updatedAt) { this.updatedAt = updatedAt; }
}
