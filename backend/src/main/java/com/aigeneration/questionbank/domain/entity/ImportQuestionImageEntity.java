package com.aigeneration.questionbank.domain.entity;

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;

/**
 * 导入题题图实体。
 *
 * <p>对应 {@code java_import_question_images} 表，用于记录导入任务下每道题关联的题图元数据，
 * 包括 OCR 图片、人工上传图片和从任务题图库选择的图片。</p>
 */
@TableName("java_import_question_images")
public class ImportQuestionImageEntity {
    @TableId
    private String id;
    private String taskId;
    private String questionId;
    private Integer imageIndex;
    private String name;
    private String path;
    private String url;
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
     * 获取 questionId 字段值。
     *
     * @return questionId 字段值
     */
    public String getQuestionId() { return questionId; }
    /**
     * 设置 questionId 字段值。
     *
     * @param questionId questionId 字段值
     */
    public void setQuestionId(String questionId) { this.questionId = questionId; }
    /**
     * 获取 imageIndex 字段值。
     *
     * @return imageIndex 字段值
     */
    public Integer getImageIndex() { return imageIndex; }
    /**
     * 设置 imageIndex 字段值。
     *
     * @param imageIndex imageIndex 字段值
     */
    public void setImageIndex(Integer imageIndex) { this.imageIndex = imageIndex; }
    /**
     * 获取 name 字段值。
     *
     * @return name 字段值
     */
    public String getName() { return name; }
    /**
     * 设置 name 字段值。
     *
     * @param name name 字段值
     */
    public void setName(String name) { this.name = name; }
    /**
     * 获取 path 字段值。
     *
     * @return path 字段值
     */
    public String getPath() { return path; }
    /**
     * 设置 path 字段值。
     *
     * @param path path 字段值
     */
    public void setPath(String path) { this.path = path; }
    /**
     * 获取 url 字段值。
     *
     * @return url 字段值
     */
    public String getUrl() { return url; }
    /**
     * 设置 url 字段值。
     *
     * @param url url 字段值
     */
    public void setUrl(String url) { this.url = url; }
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
