package com.aigeneration.questionbank.domain.entity;

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;

/**
 * 知识点持久化实体。
 *
 * <p>对应 {@code java_knowledge_points} 表，用于保存本地知识点树节点、学科、年级和描述。
 * 企业平台已有权威知识点时，该表可作为映射缓存。</p>
 */
@TableName("java_knowledge_points")
public class KnowledgePointEntity {
    @TableId
    private String id;
    private String name;
    private String parentId;
    private String subject;
    private String grade;
    private String description;
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
     * 获取 parentId 字段值。
     *
     * @return parentId 字段值
     */
    public String getParentId() { return parentId; }
    /**
     * 设置 parentId 字段值。
     *
     * @param parentId parentId 字段值
     */
    public void setParentId(String parentId) { this.parentId = parentId; }
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
     * 获取 description 字段值。
     *
     * @return description 字段值
     */
    public String getDescription() { return description; }
    /**
     * 设置 description 字段值。
     *
     * @param description description 字段值
     */
    public void setDescription(String description) { this.description = description; }
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
