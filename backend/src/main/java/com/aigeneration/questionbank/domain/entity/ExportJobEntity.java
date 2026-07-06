package com.aigeneration.questionbank.domain.entity;

import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;

/**
 * 试卷导出任务实体。
 *
 * <p>对应 {@code java_export_jobs} 表，用于记录试卷导出格式、变体、状态、导出文件引用、
 * worker 请求响应和失败原因。</p>
 */
@TableName("java_export_jobs")
public class ExportJobEntity {
    @TableId
    private String id;
    private String paperId;
    @TableField("export_format")
    private String format;
    private String variant;
    private String status;
    private String fileId;
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
     * 获取 paperId 字段值。
     *
     * @return paperId 字段值
     */
    public String getPaperId() { return paperId; }
    /**
     * 设置 paperId 字段值。
     *
     * @param paperId paperId 字段值
     */
    public void setPaperId(String paperId) { this.paperId = paperId; }
    /**
     * 获取 format 字段值。
     *
     * @return format 字段值
     */
    public String getFormat() { return format; }
    /**
     * 设置 format 字段值。
     *
     * @param format format 字段值
     */
    public void setFormat(String format) { this.format = format; }
    /**
     * 获取 variant 字段值。
     *
     * @return variant 字段值
     */
    public String getVariant() { return variant; }
    /**
     * 设置 variant 字段值。
     *
     * @param variant variant 字段值
     */
    public void setVariant(String variant) { this.variant = variant; }
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
     * 获取 fileId 字段值。
     *
     * @return fileId 字段值
     */
    public String getFileId() { return fileId; }
    /**
     * 设置 fileId 字段值。
     *
     * @param fileId fileId 字段值
     */
    public void setFileId(String fileId) { this.fileId = fileId; }
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
