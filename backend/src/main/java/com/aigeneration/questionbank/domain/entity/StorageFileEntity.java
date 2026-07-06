package com.aigeneration.questionbank.domain.entity;

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;

/**
 * Java 文件存储元数据实体。
 *
 * <p>对应 {@code java_storage_files} 表，用于统一记录导入原文件、题图、OCR 产物和导出文件在
 * LOCAL 或 MINIO 中的存储位置、业务归属和访问 URL。</p>
 */
@TableName("java_storage_files")
public class StorageFileEntity {
    @TableId
    private String id;
    private String businessType;
    private String businessId;
    private String fieldName;
    private String originalFilename;
    private String contentType;
    private Long sizeBytes;
    private String storageType;
    private String bucket;
    private String objectKey;
    private String localPath;
    private String url;
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
     * 获取 businessType 字段值。
     *
     * @return businessType 字段值
     */
    public String getBusinessType() { return businessType; }
    /**
     * 设置 businessType 字段值。
     *
     * @param businessType businessType 字段值
     */
    public void setBusinessType(String businessType) { this.businessType = businessType; }
    /**
     * 获取 businessId 字段值。
     *
     * @return businessId 字段值
     */
    public String getBusinessId() { return businessId; }
    /**
     * 设置 businessId 字段值。
     *
     * @param businessId businessId 字段值
     */
    public void setBusinessId(String businessId) { this.businessId = businessId; }
    /**
     * 获取 fieldName 字段值。
     *
     * @return fieldName 字段值
     */
    public String getFieldName() { return fieldName; }
    /**
     * 设置 fieldName 字段值。
     *
     * @param fieldName fieldName 字段值
     */
    public void setFieldName(String fieldName) { this.fieldName = fieldName; }
    /**
     * 获取 originalFilename 字段值。
     *
     * @return originalFilename 字段值
     */
    public String getOriginalFilename() { return originalFilename; }
    /**
     * 设置 originalFilename 字段值。
     *
     * @param originalFilename originalFilename 字段值
     */
    public void setOriginalFilename(String originalFilename) { this.originalFilename = originalFilename; }
    /**
     * 获取 contentType 字段值。
     *
     * @return contentType 字段值
     */
    public String getContentType() { return contentType; }
    /**
     * 设置 contentType 字段值。
     *
     * @param contentType contentType 字段值
     */
    public void setContentType(String contentType) { this.contentType = contentType; }
    /**
     * 获取 sizeBytes 字段值。
     *
     * @return sizeBytes 字段值
     */
    public Long getSizeBytes() { return sizeBytes; }
    /**
     * 设置 sizeBytes 字段值。
     *
     * @param sizeBytes sizeBytes 字段值
     */
    public void setSizeBytes(Long sizeBytes) { this.sizeBytes = sizeBytes; }
    /**
     * 获取 storageType 字段值。
     *
     * @return storageType 字段值
     */
    public String getStorageType() { return storageType; }
    /**
     * 设置 storageType 字段值。
     *
     * @param storageType storageType 字段值
     */
    public void setStorageType(String storageType) { this.storageType = storageType; }
    /**
     * 获取 bucket 字段值。
     *
     * @return bucket 字段值
     */
    public String getBucket() { return bucket; }
    /**
     * 设置 bucket 字段值。
     *
     * @param bucket bucket 字段值
     */
    public void setBucket(String bucket) { this.bucket = bucket; }
    /**
     * 获取 objectKey 字段值。
     *
     * @return objectKey 字段值
     */
    public String getObjectKey() { return objectKey; }
    /**
     * 设置 objectKey 字段值。
     *
     * @param objectKey objectKey 字段值
     */
    public void setObjectKey(String objectKey) { this.objectKey = objectKey; }
    /**
     * 获取 localPath 字段值。
     *
     * @return localPath 字段值
     */
    public String getLocalPath() { return localPath; }
    /**
     * 设置 localPath 字段值。
     *
     * @param localPath localPath 字段值
     */
    public void setLocalPath(String localPath) { this.localPath = localPath; }
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
