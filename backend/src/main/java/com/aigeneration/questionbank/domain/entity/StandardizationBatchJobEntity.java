package com.aigeneration.questionbank.domain.entity;

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;

/** Persistent lifecycle and progress for one task-wide standardization run. */
@TableName("java_standardization_batch_jobs")
public class StandardizationBatchJobEntity {
    @TableId private String id;
    private String taskId;
    private String status;
    private Integer totalQuestions;
    private Integer totalItems;
    private Integer completedQuestions;
    private Integer completedItems;
    private Integer successItems;
    private Integer failedItems;
    private Integer maxConcurrency;
    private LocalDateTime cancelRequestedAt;
    private LocalDateTime createdAt;
    private LocalDateTime startedAt;
    private LocalDateTime finishedAt;
    private LocalDateTime updatedAt;

    public String getId() { return id; } public void setId(String value) { id = value; }
    public String getTaskId() { return taskId; } public void setTaskId(String value) { taskId = value; }
    public String getStatus() { return status; } public void setStatus(String value) { status = value; }
    public Integer getTotalQuestions() { return totalQuestions; } public void setTotalQuestions(Integer value) { totalQuestions = value; }
    public Integer getTotalItems() { return totalItems; } public void setTotalItems(Integer value) { totalItems = value; }
    public Integer getCompletedQuestions() { return completedQuestions; } public void setCompletedQuestions(Integer value) { completedQuestions = value; }
    public Integer getCompletedItems() { return completedItems; } public void setCompletedItems(Integer value) { completedItems = value; }
    public Integer getSuccessItems() { return successItems; } public void setSuccessItems(Integer value) { successItems = value; }
    public Integer getFailedItems() { return failedItems; } public void setFailedItems(Integer value) { failedItems = value; }
    public Integer getMaxConcurrency() { return maxConcurrency; } public void setMaxConcurrency(Integer value) { maxConcurrency = value; }
    public LocalDateTime getCancelRequestedAt() { return cancelRequestedAt; } public void setCancelRequestedAt(LocalDateTime value) { cancelRequestedAt = value; }
    public LocalDateTime getCreatedAt() { return createdAt; } public void setCreatedAt(LocalDateTime value) { createdAt = value; }
    public LocalDateTime getStartedAt() { return startedAt; } public void setStartedAt(LocalDateTime value) { startedAt = value; }
    public LocalDateTime getFinishedAt() { return finishedAt; } public void setFinishedAt(LocalDateTime value) { finishedAt = value; }
    public LocalDateTime getUpdatedAt() { return updatedAt; } public void setUpdatedAt(LocalDateTime value) { updatedAt = value; }
}
