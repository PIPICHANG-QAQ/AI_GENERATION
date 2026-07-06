package com.aigeneration.questionbank.domain.entity;

import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;

/**
 * 导入任务持久化实体。
 *
 * <p>对应 {@code java_import_tasks} 表，用于保存一次试卷/答案导入任务的基础信息、原文件、
 * OCR job 状态、失败原因、题目数量和旧 worker 原始响应快照。</p>
 */
@TableName("java_import_tasks")
public class ImportTaskEntity {
    @TableId
    private String id;
    private String stage;
    private String subject;
    private String grade;
    private String region;
    @TableField("task_year")
    private String taskYear;
    private String title;
    private String status;
    private String paperFileJson;
    private String answerFileJson;
    private String paperOcrJobId;
    private String answerOcrJobId;
    private String paperOcrJobJson;
    private String answerOcrJobJson;
    private String paperOcrStatus;
    private String answerOcrStatus;
    private String failureReason;
    private Integer questionCount;
    private String rawJson;
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
     * 获取 stage 字段值。
     *
     * @return stage 字段值
     */
    public String getStage() { return stage; }
    /**
     * 设置 stage 字段值。
     *
     * @param stage stage 字段值
     */
    public void setStage(String stage) { this.stage = stage; }
    /**
     * 获取 subject 字段值。
     *
     * @return subject 字段值
     */
    public String getSubject() { return subject; }
    /**
     * 设置 subject 字段值。
     *
     * @param subject subject 字段值
     */
    public void setSubject(String subject) { this.subject = subject; }
    /**
     * 获取 grade 字段值。
     *
     * @return grade 字段值
     */
    public String getGrade() { return grade; }
    /**
     * 设置 grade 字段值。
     *
     * @param grade grade 字段值
     */
    public void setGrade(String grade) { this.grade = grade; }
    /**
     * 获取 region 字段值。
     *
     * @return region 字段值
     */
    public String getRegion() { return region; }
    /**
     * 设置 region 字段值。
     *
     * @param region region 字段值
     */
    public void setRegion(String region) { this.region = region; }
    /**
     * 获取 taskYear 字段值。
     *
     * @return taskYear 字段值
     */
    public String getTaskYear() { return taskYear; }
    /**
     * 设置 taskYear 字段值。
     *
     * @param taskYear taskYear 字段值
     */
    public void setTaskYear(String taskYear) { this.taskYear = taskYear; }
    /**
     * 获取 taskYear 字段值。
     *
     * @return taskYear 字段值
     */
    public String getYear() { return taskYear; }
    /**
     * 设置 taskYear 字段值。
     *
     * @param year taskYear 字段值
     */
    public void setYear(String year) { this.taskYear = year; }
    /**
     * 获取 title 字段值。
     *
     * @return title 字段值
     */
    public String getTitle() { return title; }
    /**
     * 设置 title 字段值。
     *
     * @param title title 字段值
     */
    public void setTitle(String title) { this.title = title; }
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
     * 获取 paperFileJson 字段值。
     *
     * @return paperFileJson 字段值
     */
    public String getPaperFileJson() { return paperFileJson; }
    /**
     * 设置 paperFileJson 字段值。
     *
     * @param paperFileJson paperFileJson 字段值
     */
    public void setPaperFileJson(String paperFileJson) { this.paperFileJson = paperFileJson; }
    /**
     * 获取 answerFileJson 字段值。
     *
     * @return answerFileJson 字段值
     */
    public String getAnswerFileJson() { return answerFileJson; }
    /**
     * 设置 answerFileJson 字段值。
     *
     * @param answerFileJson answerFileJson 字段值
     */
    public void setAnswerFileJson(String answerFileJson) { this.answerFileJson = answerFileJson; }
    /**
     * 获取 paperOcrJobId 字段值。
     *
     * @return paperOcrJobId 字段值
     */
    public String getPaperOcrJobId() { return paperOcrJobId; }
    /**
     * 设置 paperOcrJobId 字段值。
     *
     * @param paperOcrJobId paperOcrJobId 字段值
     */
    public void setPaperOcrJobId(String paperOcrJobId) { this.paperOcrJobId = paperOcrJobId; }
    /**
     * 获取 answerOcrJobId 字段值。
     *
     * @return answerOcrJobId 字段值
     */
    public String getAnswerOcrJobId() { return answerOcrJobId; }
    /**
     * 设置 answerOcrJobId 字段值。
     *
     * @param answerOcrJobId answerOcrJobId 字段值
     */
    public void setAnswerOcrJobId(String answerOcrJobId) { this.answerOcrJobId = answerOcrJobId; }
    /**
     * 获取 paperOcrJobJson 字段值。
     *
     * @return paperOcrJobJson 字段值
     */
    public String getPaperOcrJobJson() { return paperOcrJobJson; }
    /**
     * 设置 paperOcrJobJson 字段值。
     *
     * @param paperOcrJobJson paperOcrJobJson 字段值
     */
    public void setPaperOcrJobJson(String paperOcrJobJson) { this.paperOcrJobJson = paperOcrJobJson; }
    /**
     * 获取 answerOcrJobJson 字段值。
     *
     * @return answerOcrJobJson 字段值
     */
    public String getAnswerOcrJobJson() { return answerOcrJobJson; }
    /**
     * 设置 answerOcrJobJson 字段值。
     *
     * @param answerOcrJobJson answerOcrJobJson 字段值
     */
    public void setAnswerOcrJobJson(String answerOcrJobJson) { this.answerOcrJobJson = answerOcrJobJson; }
    /**
     * 获取 paperOcrStatus 字段值。
     *
     * @return paperOcrStatus 字段值
     */
    public String getPaperOcrStatus() { return paperOcrStatus; }
    /**
     * 设置 paperOcrStatus 字段值。
     *
     * @param paperOcrStatus paperOcrStatus 字段值
     */
    public void setPaperOcrStatus(String paperOcrStatus) { this.paperOcrStatus = paperOcrStatus; }
    /**
     * 获取 answerOcrStatus 字段值。
     *
     * @return answerOcrStatus 字段值
     */
    public String getAnswerOcrStatus() { return answerOcrStatus; }
    /**
     * 设置 answerOcrStatus 字段值。
     *
     * @param answerOcrStatus answerOcrStatus 字段值
     */
    public void setAnswerOcrStatus(String answerOcrStatus) { this.answerOcrStatus = answerOcrStatus; }
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
     * 获取 questionCount 字段值。
     *
     * @return questionCount 字段值
     */
    public Integer getQuestionCount() { return questionCount; }
    /**
     * 设置 questionCount 字段值。
     *
     * @param questionCount questionCount 字段值
     */
    public void setQuestionCount(Integer questionCount) { this.questionCount = questionCount; }
    /**
     * 获取 rawJson 字段值。
     *
     * @return rawJson 字段值
     */
    public String getRawJson() { return rawJson; }
    /**
     * 设置 rawJson 字段值。
     *
     * @param rawJson rawJson 字段值
     */
    public void setRawJson(String rawJson) { this.rawJson = rawJson; }
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
