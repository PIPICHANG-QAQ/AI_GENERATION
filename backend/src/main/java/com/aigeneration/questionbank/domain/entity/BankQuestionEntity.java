package com.aigeneration.questionbank.domain.entity;

import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;

/**
 * 题库题持久化实体。
 *
 * <p>对应 {@code java_bank_questions} 表，用于保存 Java 本地题库题快照，包括题干、答案、
 * 解析、题图、选项、子题、知识点候选和来源导入任务信息。</p>
 */
@TableName("java_bank_questions")
public class BankQuestionEntity {
    @TableId
    private String id;
    private String sourceImportTaskId;
    private String sourceImportQuestionId;
    private String source;
    private String stage;
    private String subject;
    private String grade;
    private String region;
    @TableField("question_year")
    private String questionYear;
    private String title;
    private Integer questionNumber;
    private String type;
    private String stemMarkdown;
    private String manualMarkdown;
    private String answer;
    private String analysis;
    private String knowledgePointIdsJson;
    private String knowledgePointsJson;
    private String difficulty;
    private Double score;
    private String imagesJson;
    private String optionsJson;
    private String childrenJson;
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
     * 获取 sourceImportTaskId 字段值。
     *
     * @return sourceImportTaskId 字段值
     */
    public String getSourceImportTaskId() { return sourceImportTaskId; }
    /**
     * 设置 sourceImportTaskId 字段值。
     *
     * @param sourceImportTaskId sourceImportTaskId 字段值
     */
    public void setSourceImportTaskId(String sourceImportTaskId) { this.sourceImportTaskId = sourceImportTaskId; }
    /**
     * 获取 sourceImportQuestionId 字段值。
     *
     * @return sourceImportQuestionId 字段值
     */
    public String getSourceImportQuestionId() { return sourceImportQuestionId; }
    /**
     * 设置 sourceImportQuestionId 字段值。
     *
     * @param sourceImportQuestionId sourceImportQuestionId 字段值
     */
    public void setSourceImportQuestionId(String sourceImportQuestionId) { this.sourceImportQuestionId = sourceImportQuestionId; }
    /**
     * 获取 source 字段值。
     *
     * @return source 字段值
     */
    public String getSource() { return source; }
    /**
     * 设置 source 字段值。
     *
     * @param source source 字段值
     */
    public void setSource(String source) { this.source = source; }
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
     * 获取 questionYear 字段值。
     *
     * @return questionYear 字段值
     */
    public String getQuestionYear() { return questionYear; }
    /**
     * 设置 questionYear 字段值。
     *
     * @param questionYear questionYear 字段值
     */
    public void setQuestionYear(String questionYear) { this.questionYear = questionYear; }
    /**
     * 获取 questionYear 字段值。
     *
     * @return questionYear 字段值
     */
    public String getYear() { return questionYear; }
    /**
     * 设置 questionYear 字段值。
     *
     * @param year questionYear 字段值
     */
    public void setYear(String year) { this.questionYear = year; }
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
     * 获取 questionNumber 字段值。
     *
     * @return questionNumber 字段值
     */
    public Integer getQuestionNumber() { return questionNumber; }
    /**
     * 设置 questionNumber 字段值。
     *
     * @param questionNumber questionNumber 字段值
     */
    public void setQuestionNumber(Integer questionNumber) { this.questionNumber = questionNumber; }
    /**
     * 获取 type 字段值。
     *
     * @return type 字段值
     */
    public String getType() { return type; }
    /**
     * 设置 type 字段值。
     *
     * @param type type 字段值
     */
    public void setType(String type) { this.type = type; }
    /**
     * 获取 stemMarkdown 字段值。
     *
     * @return stemMarkdown 字段值
     */
    public String getStemMarkdown() { return stemMarkdown; }
    /**
     * 设置 stemMarkdown 字段值。
     *
     * @param stemMarkdown stemMarkdown 字段值
     */
    public void setStemMarkdown(String stemMarkdown) { this.stemMarkdown = stemMarkdown; }
    /**
     * 获取 manualMarkdown 字段值。
     *
     * @return manualMarkdown 字段值
     */
    public String getManualMarkdown() { return manualMarkdown; }
    /**
     * 设置 manualMarkdown 字段值。
     *
     * @param manualMarkdown manualMarkdown 字段值
     */
    public void setManualMarkdown(String manualMarkdown) { this.manualMarkdown = manualMarkdown; }
    /**
     * 获取 answer 字段值。
     *
     * @return answer 字段值
     */
    public String getAnswer() { return answer; }
    /**
     * 设置 answer 字段值。
     *
     * @param answer answer 字段值
     */
    public void setAnswer(String answer) { this.answer = answer; }
    /**
     * 获取 analysis 字段值。
     *
     * @return analysis 字段值
     */
    public String getAnalysis() { return analysis; }
    /**
     * 设置 analysis 字段值。
     *
     * @param analysis analysis 字段值
     */
    public void setAnalysis(String analysis) { this.analysis = analysis; }
    /**
     * 获取 knowledgePointIdsJson 字段值。
     *
     * @return knowledgePointIdsJson 字段值
     */
    public String getKnowledgePointIdsJson() { return knowledgePointIdsJson; }
    /**
     * 设置 knowledgePointIdsJson 字段值。
     *
     * @param knowledgePointIdsJson knowledgePointIdsJson 字段值
     */
    public void setKnowledgePointIdsJson(String knowledgePointIdsJson) { this.knowledgePointIdsJson = knowledgePointIdsJson; }
    /**
     * 获取 knowledgePointsJson 字段值。
     *
     * @return knowledgePointsJson 字段值
     */
    public String getKnowledgePointsJson() { return knowledgePointsJson; }
    /**
     * 设置 knowledgePointsJson 字段值。
     *
     * @param knowledgePointsJson knowledgePointsJson 字段值
     */
    public void setKnowledgePointsJson(String knowledgePointsJson) { this.knowledgePointsJson = knowledgePointsJson; }
    /**
     * 获取 difficulty 字段值。
     *
     * @return difficulty 字段值
     */
    public String getDifficulty() { return difficulty; }
    /**
     * 设置 difficulty 字段值。
     *
     * @param difficulty difficulty 字段值
     */
    public void setDifficulty(String difficulty) { this.difficulty = difficulty; }
    /**
     * 获取 score 字段值。
     *
     * @return score 字段值
     */
    public Double getScore() { return score; }
    /**
     * 设置 score 字段值。
     *
     * @param score score 字段值
     */
    public void setScore(Double score) { this.score = score; }
    /**
     * 获取 imagesJson 字段值。
     *
     * @return imagesJson 字段值
     */
    public String getImagesJson() { return imagesJson; }
    /**
     * 设置 imagesJson 字段值。
     *
     * @param imagesJson imagesJson 字段值
     */
    public void setImagesJson(String imagesJson) { this.imagesJson = imagesJson; }
    /**
     * 获取 optionsJson 字段值。
     *
     * @return optionsJson 字段值
     */
    public String getOptionsJson() { return optionsJson; }
    /**
     * 设置 optionsJson 字段值。
     *
     * @param optionsJson optionsJson 字段值
     */
    public void setOptionsJson(String optionsJson) { this.optionsJson = optionsJson; }
    /**
     * 获取 childrenJson 字段值。
     *
     * @return childrenJson 字段值
     */
    public String getChildrenJson() { return childrenJson; }
    /**
     * 设置 childrenJson 字段值。
     *
     * @param childrenJson childrenJson 字段值
     */
    public void setChildrenJson(String childrenJson) { this.childrenJson = childrenJson; }
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
