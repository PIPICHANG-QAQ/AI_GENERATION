package com.aigeneration.questionbank.domain.entity;

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;

/**
 * 导入题快照实体。
 *
 * <p>对应 {@code java_import_questions} 表，用于保存 OCR/AI 同步后的待校验题目，包括题干、
 * 人工编辑 Markdown、答案、解析、题图、选项、子题、公式校验和原始 JSON。</p>
 */
@TableName("java_import_questions")
public class ImportQuestionEntity {
    @TableId
    private String id;
    private String taskId;
    private String sourceQuestionId;
    private Integer questionNumber;
    private String status;
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
    private String mathValidationJson;
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
     * 获取 taskId 字段值。
     *
     * @return taskId 字段值
     */
    public String getTaskId() { return taskId; }
    /**
     * 设置 taskId 字段值。
     *
     * @param taskId taskId 字段值
     */
    public void setTaskId(String taskId) { this.taskId = taskId; }
    /**
     * 获取 sourceQuestionId 字段值。
     *
     * @return sourceQuestionId 字段值
     */
    public String getSourceQuestionId() { return sourceQuestionId; }
    /**
     * 设置 sourceQuestionId 字段值。
     *
     * @param sourceQuestionId sourceQuestionId 字段值
     */
    public void setSourceQuestionId(String sourceQuestionId) { this.sourceQuestionId = sourceQuestionId; }
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
     * 获取 mathValidationJson 字段值。
     *
     * @return mathValidationJson 字段值
     */
    public String getMathValidationJson() { return mathValidationJson; }
    /**
     * 设置 mathValidationJson 字段值。
     *
     * @param mathValidationJson mathValidationJson 字段值
     */
    public void setMathValidationJson(String mathValidationJson) { this.mathValidationJson = mathValidationJson; }
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
