package com.aigeneration.questionbank.domain.entity;

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;

/**
 * 试卷定义实体。
 *
 * <p>对应 {@code java_papers} 表，用于保存本地组卷定义、题目引用、组卷规则、答案显示方式、
 * 分值配置、卷头配置和试卷状态。</p>
 */
@TableName("java_papers")
public class PaperEntity {
    @TableId
    private String id;
    private String title;
    private String subject;
    private String grade;
    private String questionIdsJson;
    private String rulesJson;
    private String answerDisplay;
    private String scoresJson;
    private String subSelectionsJson;
    private String headerJson;
    private String status;
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
     * 获取 questionIdsJson 字段值。
     *
     * @return questionIdsJson 字段值
     */
    public String getQuestionIdsJson() { return questionIdsJson; }
    /**
     * 设置 questionIdsJson 字段值。
     *
     * @param questionIdsJson questionIdsJson 字段值
     */
    public void setQuestionIdsJson(String questionIdsJson) { this.questionIdsJson = questionIdsJson; }
    /**
     * 获取 rulesJson 字段值。
     *
     * @return rulesJson 字段值
     */
    public String getRulesJson() { return rulesJson; }
    /**
     * 设置 rulesJson 字段值。
     *
     * @param rulesJson rulesJson 字段值
     */
    public void setRulesJson(String rulesJson) { this.rulesJson = rulesJson; }
    /**
     * 获取 answerDisplay 字段值。
     *
     * @return answerDisplay 字段值
     */
    public String getAnswerDisplay() { return answerDisplay; }
    /**
     * 设置 answerDisplay 字段值。
     *
     * @param answerDisplay answerDisplay 字段值
     */
    public void setAnswerDisplay(String answerDisplay) { this.answerDisplay = answerDisplay; }
    /**
     * 获取 scoresJson 字段值。
     *
     * @return scoresJson 字段值
     */
    public String getScoresJson() { return scoresJson; }
    /**
     * 设置 scoresJson 字段值。
     *
     * @param scoresJson scoresJson 字段值
     */
    public void setScoresJson(String scoresJson) { this.scoresJson = scoresJson; }
    /**
     * 获取 subSelectionsJson 字段值。
     *
     * @return subSelectionsJson 字段值
     */
    public String getSubSelectionsJson() { return subSelectionsJson; }
    /**
     * 设置 subSelectionsJson 字段值。
     *
     * @param subSelectionsJson subSelectionsJson 字段值
     */
    public void setSubSelectionsJson(String subSelectionsJson) { this.subSelectionsJson = subSelectionsJson; }
    /**
     * 获取 headerJson 字段值。
     *
     * @return headerJson 字段值
     */
    public String getHeaderJson() { return headerJson; }
    /**
     * 设置 headerJson 字段值。
     *
     * @param headerJson headerJson 字段值
     */
    public void setHeaderJson(String headerJson) { this.headerJson = headerJson; }
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
