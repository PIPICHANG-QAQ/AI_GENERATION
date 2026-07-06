package com.aigeneration.questionbank.domain.entity;

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;

/**
 * AI job 持久化实体。
 *
 * <p>对应 {@code java_ai_jobs} 表，用于记录导入题、题库题或临时文本的 AI 标准化/解析请求、
 * worker 响应、状态、失败原因和重试次数。</p>
 */
@TableName("java_ai_jobs")
public class AiJobEntity {
    @TableId
    private String id;
    private String targetType;
    private String targetId;
    private String operation;
    private String status;
    private Integer retryCount;
    private String failureReason;
    private String requestJson;
    private String responseJson;
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
     * 获取 targetType 字段值。
     *
     * @return targetType 字段值
     */
    public String getTargetType() { return targetType; }
    /**
     * 设置 targetType 字段值。
     *
     * @param targetType targetType 字段值
     */
    public void setTargetType(String targetType) { this.targetType = targetType; }
    /**
     * 获取 targetId 字段值。
     *
     * @return targetId 字段值
     */
    public String getTargetId() { return targetId; }
    /**
     * 设置 targetId 字段值。
     *
     * @param targetId targetId 字段值
     */
    public void setTargetId(String targetId) { this.targetId = targetId; }
    /**
     * 获取 operation 字段值。
     *
     * @return operation 字段值
     */
    public String getOperation() { return operation; }
    /**
     * 设置 operation 字段值。
     *
     * @param operation operation 字段值
     */
    public void setOperation(String operation) { this.operation = operation; }
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
     * 获取 requestJson 字段值。
     *
     * @return requestJson 字段值
     */
    public String getRequestJson() { return requestJson; }
    /**
     * 设置 requestJson 字段值。
     *
     * @param requestJson requestJson 字段值
     */
    public void setRequestJson(String requestJson) { this.requestJson = requestJson; }
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
