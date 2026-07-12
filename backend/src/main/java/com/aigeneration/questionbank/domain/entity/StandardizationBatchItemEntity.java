package com.aigeneration.questionbank.domain.entity;

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;

/** One atomic question unit within a standardization batch. */
@TableName("java_standardization_batch_items")
public class StandardizationBatchItemEntity {
    @TableId private String id;
    private String jobId;
    private String questionId;
    private String status;
    private String inputHash;
    private Integer attemptCount;
    private Integer totalItems;
    private Integer completedItems;
    private Integer successItems;
    private Integer failedItems;
    private String errorMessage;
    private LocalDateTime createdAt;
    private LocalDateTime startedAt;
    private LocalDateTime finishedAt;
    private LocalDateTime updatedAt;

    public String getId() { return id; } public void setId(String value) { id = value; }
    public String getJobId() { return jobId; } public void setJobId(String value) { jobId = value; }
    public String getQuestionId() { return questionId; } public void setQuestionId(String value) { questionId = value; }
    public String getStatus() { return status; } public void setStatus(String value) { status = value; }
    public String getInputHash() { return inputHash; } public void setInputHash(String value) { inputHash = value; }
    public Integer getAttemptCount() { return attemptCount; } public void setAttemptCount(Integer value) { attemptCount = value; }
    public Integer getTotalItems() { return totalItems; } public void setTotalItems(Integer value) { totalItems = value; }
    public Integer getCompletedItems() { return completedItems; } public void setCompletedItems(Integer value) { completedItems = value; }
    public Integer getSuccessItems() { return successItems; } public void setSuccessItems(Integer value) { successItems = value; }
    public Integer getFailedItems() { return failedItems; } public void setFailedItems(Integer value) { failedItems = value; }
    public String getErrorMessage() { return errorMessage; } public void setErrorMessage(String value) { errorMessage = value; }
    public LocalDateTime getCreatedAt() { return createdAt; } public void setCreatedAt(LocalDateTime value) { createdAt = value; }
    public LocalDateTime getStartedAt() { return startedAt; } public void setStartedAt(LocalDateTime value) { startedAt = value; }
    public LocalDateTime getFinishedAt() { return finishedAt; } public void setFinishedAt(LocalDateTime value) { finishedAt = value; }
    public LocalDateTime getUpdatedAt() { return updatedAt; } public void setUpdatedAt(LocalDateTime value) { updatedAt = value; }
}
