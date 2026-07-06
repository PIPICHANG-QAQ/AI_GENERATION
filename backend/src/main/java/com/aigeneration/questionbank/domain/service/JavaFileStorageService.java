package com.aigeneration.questionbank.domain.service;

import com.aigeneration.questionbank.config.EnterpriseProperties;
import com.aigeneration.questionbank.config.JavaStorageProperties;
import com.aigeneration.questionbank.domain.entity.StorageFileEntity;
import com.aigeneration.questionbank.domain.mapper.StorageFileMapper;
import com.aigeneration.questionbank.domain.support.Ids;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import io.minio.BucketExistsArgs;
import io.minio.GetObjectArgs;
import io.minio.MakeBucketArgs;
import io.minio.MinioClient;
import io.minio.PutObjectArgs;
import io.minio.RemoveObjectArgs;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.Locale;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.InputStreamResource;
import org.springframework.core.io.Resource;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

/**
 * Java 文件存储服务。
 *
 * <p>统一管理导入原文件、导入题图、题库题图和导出文件的元数据与二进制存储。服务支持
 * 本地磁盘和 MinIO 两种后端，并为控制器提供 inline 预览、字节读取和 data URL 生成能力。</p>
 */
@Service
public class JavaFileStorageService {
    /**
     * 导入任务原文件业务类型。
     */
    public static final String BUSINESS_IMPORT_TASK_UPLOAD = "IMPORT_TASK_UPLOAD";

    /**
     * 导入题题图业务类型。
     */
    public static final String BUSINESS_IMPORT_QUESTION_IMAGE = "IMPORT_QUESTION_IMAGE";

    /**
     * 题库题题图业务类型。
     */
    public static final String BUSINESS_BANK_QUESTION_IMAGE = "BANK_QUESTION_IMAGE";

    /**
     * 试卷导出文件业务类型。
     */
    public static final String BUSINESS_PAPER_EXPORT = "PAPER_EXPORT";

    /**
     * 文件元数据表访问对象。
     */
    private final StorageFileMapper mapper;

    /**
     * 企业部署配置，包含 MinIO 开关和连接信息。
     */
    private final EnterpriseProperties enterpriseProperties;

    /**
     * Java 存储配置，包含本地存储根目录。
     */
    private final JavaStorageProperties storageProperties;

    /**
     * 注入文件元数据 Mapper、企业配置和存储配置。
     *
     * @param mapper 文件元数据 Mapper
     * @param enterpriseProperties 企业部署配置
     * @param storageProperties Java 存储配置
     */
    public JavaFileStorageService(
            StorageFileMapper mapper,
            EnterpriseProperties enterpriseProperties,
            JavaStorageProperties storageProperties
    ) {
        this.mapper = mapper;
        this.enterpriseProperties = enterpriseProperties;
        this.storageProperties = storageProperties;
    }

    /**
     * 保存导入任务原文件。
     *
     * @param businessId 任务 ID 或临时业务 ID
     * @param fieldName 文件字段名
     * @param file 上传文件
     * @return 文件元数据实体
     */
    public StorageFileEntity storeImportUpload(String businessId, String fieldName, MultipartFile file) {
        return store(BUSINESS_IMPORT_TASK_UPLOAD, businessId, fieldName, file);
    }

    /**
     * 保存导入题题图。
     *
     * @param questionId 导入题 ID
     * @param file 上传文件
     * @return 文件元数据实体
     */
    public StorageFileEntity storeImportQuestionImage(String questionId, MultipartFile file) {
        return store(BUSINESS_IMPORT_QUESTION_IMAGE, questionId, "image", file);
    }

    /**
     * 保存题库题题图。
     *
     * @param questionId 题库题 ID
     * @param file 上传文件
     * @return 文件元数据实体
     */
    public StorageFileEntity storeBankQuestionImage(String questionId, MultipartFile file) {
        return store(BUSINESS_BANK_QUESTION_IMAGE, questionId, "image", file);
    }

    /**
     * 保存试卷导出文件。
     *
     * @param exportJobId 导出 job ID
     * @param filename 文件名
     * @param contentType 内容类型
     * @param bytes 文件字节
     * @return 文件元数据实体
     */
    public StorageFileEntity storePaperExport(String exportJobId, String filename, String contentType, byte[] bytes) {
        return storeBytes(BUSINESS_PAPER_EXPORT, exportJobId, "export", filename, contentType, bytes);
    }

    /**
     * 保存 MultipartFile 到当前配置的存储后端。
     *
     * @param businessType 业务类型
     * @param businessId 业务 ID
     * @param fieldName 字段名
     * @param file 上传文件
     * @return 文件元数据实体
     */
    public StorageFileEntity store(String businessType, String businessId, String fieldName, MultipartFile file) {
        if (file == null || file.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Uploaded file is empty");
        }
        StorageFileEntity entity = baseEntity(businessType, businessId, fieldName, file);
        if (enterpriseProperties.getMinio().isEnabled()) {
            storeToMinio(entity, file);
        } else {
            storeToLocal(entity, file);
        }
        mapper.insert(entity);
        return entity;
    }

    /**
     * 保存字节数组到当前配置的存储后端。
     *
     * @param businessType 业务类型
     * @param businessId 业务 ID
     * @param fieldName 字段名
     * @param filename 文件名
     * @param contentType 内容类型
     * @param bytes 文件字节
     * @return 文件元数据实体
     */
    public StorageFileEntity storeBytes(
            String businessType,
            String businessId,
            String fieldName,
            String filename,
            String contentType,
            byte[] bytes
    ) {
        if (bytes == null || bytes.length == 0) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "File content is empty");
        }
        StorageFileEntity entity = baseEntity(businessType, businessId, fieldName, filename, contentType, bytes.length);
        if (enterpriseProperties.getMinio().isEnabled()) {
            storeBytesToMinio(entity, bytes);
        } else {
            storeBytesToLocal(entity, bytes);
        }
        mapper.insert(entity);
        return entity;
    }

    /**
     * 批量把文件业务 ID 从临时 ID 改为真实业务 ID。
     *
     * @param files 文件实体列表
     * @param businessId 新业务 ID
     */
    public void reassignBusinessId(List<StorageFileEntity> files, String businessId) {
        if (businessId == null || businessId.isBlank()) {
            return;
        }
        for (StorageFileEntity file : files) {
            file.setBusinessId(businessId);
            file.setUpdatedAt(LocalDateTime.now());
            mapper.updateById(file);
        }
    }

    /**
     * 批量删除文件和元数据。
     *
     * @param files 文件实体列表
     */
    public void deleteAll(List<StorageFileEntity> files) {
        for (StorageFileEntity file : new ArrayList<>(files)) {
            delete(file);
        }
    }

    /**
     * 删除单个文件及其元数据。
     *
     * @param file 文件实体
     */
    public void delete(StorageFileEntity file) {
        if (file == null || file.getId() == null) {
            return;
        }
        try {
            if ("LOCAL".equals(file.getStorageType()) && file.getLocalPath() != null && !file.getLocalPath().isBlank()) {
                Files.deleteIfExists(Path.of(file.getLocalPath()));
            }
            if ("MINIO".equals(file.getStorageType()) && file.getBucket() != null && file.getObjectKey() != null) {
                minioClient().removeObject(RemoveObjectArgs.builder()
                        .bucket(file.getBucket())
                        .object(file.getObjectKey())
                        .build());
            }
        } catch (Exception ignored) {
            // Metadata cleanup should still proceed so failed import attempts do not leave active rows.
        }
        mapper.deleteById(file.getId());
    }

    /**
     * 按业务类型和业务 ID 查询文件列表。
     *
     * @param businessType 业务类型
     * @param businessId 业务 ID
     * @return 文件实体列表
     */
    public List<StorageFileEntity> listByBusiness(String businessType, String businessId) {
        return mapper.selectList(new QueryWrapper<StorageFileEntity>()
                .eq("business_type", businessType)
                .eq("business_id", businessId)
                .orderByAsc("field_name")
                .orderByAsc("created_at"));
    }

    /**
     * 查询导入任务指定字段的最新上传文件。
     *
     * @param taskId 任务 ID
     * @param fieldName 字段名
     * @return 文件实体；不存在时返回 null
     */
    public StorageFileEntity findImportUpload(String taskId, String fieldName) {
        return mapper.selectOne(new QueryWrapper<StorageFileEntity>()
                .eq("business_type", BUSINESS_IMPORT_TASK_UPLOAD)
                .eq("business_id", taskId)
                .eq("field_name", fieldName)
                .orderByDesc("created_at")
                .last("LIMIT 1"));
    }

    /**
     * 根据文件 ID 查询文件元数据。
     *
     * @param fileId 文件 ID
     * @return 文件实体；不存在时返回 null
     */
    public StorageFileEntity findById(String fileId) {
        if (fileId == null || fileId.isBlank()) {
            return null;
        }
        return mapper.selectById(fileId);
    }

    /**
     * 查询某业务下指定字段的最新文件。
     *
     * @param businessType 业务类型
     * @param businessId 业务 ID
     * @param fieldName 字段名，可为空
     * @return 最新文件实体；不存在时返回 null
     */
    public StorageFileEntity findLatestByBusiness(String businessType, String businessId, String fieldName) {
        return mapper.selectOne(new QueryWrapper<StorageFileEntity>()
                .eq("business_type", businessType)
                .eq("business_id", businessId)
                .eq(fieldName != null && !fieldName.isBlank(), "field_name", fieldName)
                .orderByDesc("created_at")
                .last("LIMIT 1"));
    }

    /**
     * 构造文件 inline 预览响应。
     *
     * @param file 文件实体
     * @return 资源响应
     */
    public ResponseEntity<Resource> inlineResponse(StorageFileEntity file) {
        if (file == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Storage file not found");
        }
        if ("LOCAL".equals(file.getStorageType())) {
            return localInlineResponse(file);
        }
        if ("MINIO".equals(file.getStorageType())) {
            return minioInlineResponse(file);
        }
        throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Storage file is not readable");
    }

    /**
     * 读取文件字节。
     *
     * @param file 文件实体
     * @return 文件字节
     */
    public byte[] readBytes(StorageFileEntity file) {
        if (file == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Storage file not found");
        }
        if ("LOCAL".equals(file.getStorageType())) {
            return readLocalBytes(file);
        }
        if ("MINIO".equals(file.getStorageType())) {
            return readMinioBytes(file);
        }
        throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Storage file is not readable");
    }

    /**
     * 将文件内容转为 data URL。
     *
     * @param file 文件实体
     * @return data URL 字符串
     */
    public String dataUrl(StorageFileEntity file) {
        String contentType = file.getContentType() == null || file.getContentType().isBlank()
                ? MediaType.APPLICATION_OCTET_STREAM_VALUE
                : file.getContentType();
        return "data:" + contentType + ";base64," + Base64.getEncoder().encodeToString(readBytes(file));
    }

    /**
     * 基于 MultipartFile 构造文件元数据。
     *
     * @param businessType 业务类型
     * @param businessId 业务 ID
     * @param fieldName 字段名
     * @param file 上传文件
     * @return 文件元数据实体
     */
    private StorageFileEntity baseEntity(String businessType, String businessId, String fieldName, MultipartFile file) {
        return baseEntity(businessType, businessId, fieldName, safeFilename(file), safeText(file.getContentType()), file.getSize());
    }

    /**
     * 构造文件元数据基础字段。
     *
     * @param businessType 业务类型
     * @param businessId 业务 ID
     * @param fieldName 字段名
     * @param filename 文件名
     * @param contentType 内容类型
     * @param sizeBytes 文件大小
     * @return 文件元数据实体
     */
    private StorageFileEntity baseEntity(
            String businessType,
            String businessId,
            String fieldName,
            String filename,
            String contentType,
            long sizeBytes
    ) {
        LocalDateTime now = LocalDateTime.now();
        StorageFileEntity entity = new StorageFileEntity();
        entity.setId(Ids.next("file"));
        entity.setBusinessType(safeText(businessType));
        entity.setBusinessId(safeText(businessId));
        entity.setFieldName(safeText(fieldName));
        entity.setOriginalFilename(safeFilename(filename));
        entity.setContentType(safeText(contentType));
        entity.setSizeBytes(sizeBytes);
        entity.setCreatedAt(now);
        entity.setUpdatedAt(now);
        return entity;
    }

    /**
     * 将上传文件保存到本地磁盘。
     *
     * @param entity 文件元数据实体
     * @param file 上传文件
     */
    private void storeToLocal(StorageFileEntity entity, MultipartFile file) {
        Path root = Path.of(storageProperties.getLocalRoot()).toAbsolutePath().normalize();
        Path target = root
                .resolve(entity.getBusinessType().toLowerCase(Locale.ROOT))
                .resolve(entity.getBusinessId())
                .resolve(entity.getFieldName())
                .resolve(storageObjectName(entity))
                .normalize();
        if (!target.startsWith(root)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid storage path");
        }
        try {
            Files.createDirectories(target.getParent());
            try (InputStream input = file.getInputStream()) {
                Files.copy(input, target, StandardCopyOption.REPLACE_EXISTING);
            }
        } catch (IOException ex) {
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, "Cannot store upload file: " + ex.getMessage());
        }
        entity.setStorageType("LOCAL");
        entity.setLocalPath(target.toString());
        entity.setObjectKey("");
        entity.setBucket("");
    }

    /**
     * 构造本地文件 inline 预览响应。
     *
     * @param file 文件实体
     * @return 本地资源响应
     */
    private ResponseEntity<Resource> localInlineResponse(StorageFileEntity file) {
        if (file.getLocalPath() == null || file.getLocalPath().isBlank()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Local file path is empty");
        }
        Path target = readableLocalPath(file);
        FileSystemResource resource = new FileSystemResource(target);
        ResponseEntity.BodyBuilder builder = baseInlineHeaders(file);
        try {
            builder.contentLength(resource.contentLength());
        } catch (IOException ignored) {
            // Content-Length is optional for preview.
        }
        return builder.body(resource);
    }

    /**
     * 构造 MinIO 文件 inline 预览响应。
     *
     * @param file 文件实体
     * @return MinIO 流响应
     */
    private ResponseEntity<Resource> minioInlineResponse(StorageFileEntity file) {
        if (file.getBucket() == null || file.getBucket().isBlank() || file.getObjectKey() == null || file.getObjectKey().isBlank()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "MinIO object is empty");
        }
        try {
            InputStream input = minioClient().getObject(GetObjectArgs.builder()
                    .bucket(file.getBucket())
                    .object(file.getObjectKey())
                    .build());
            ResponseEntity.BodyBuilder builder = baseInlineHeaders(file);
            if (file.getSizeBytes() != null && file.getSizeBytes() >= 0) {
                builder.contentLength(file.getSizeBytes());
            }
            return builder.body(new InputStreamResource(input));
        } catch (Exception ex) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "MinIO file not found: " + ex.getMessage());
        }
    }

    /**
     * 读取本地文件字节。
     *
     * @param file 文件实体
     * @return 文件字节
     */
    private byte[] readLocalBytes(StorageFileEntity file) {
        try {
            return Files.readAllBytes(readableLocalPath(file));
        } catch (IOException ex) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Local file not readable: " + ex.getMessage());
        }
    }

    /**
     * 读取 MinIO 文件字节。
     *
     * @param file 文件实体
     * @return 文件字节
     */
    private byte[] readMinioBytes(StorageFileEntity file) {
        if (file.getBucket() == null || file.getBucket().isBlank() || file.getObjectKey() == null || file.getObjectKey().isBlank()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "MinIO object is empty");
        }
        try (InputStream input = minioClient().getObject(GetObjectArgs.builder()
                .bucket(file.getBucket())
                .object(file.getObjectKey())
                .build())) {
            return input.readAllBytes();
        } catch (Exception ex) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "MinIO file not readable: " + ex.getMessage());
        }
    }

    /**
     * 校验并返回可读本地文件路径。
     *
     * @param file 文件实体
     * @return 本地路径
     */
    private Path readableLocalPath(StorageFileEntity file) {
        Path target = Path.of(file.getLocalPath()).toAbsolutePath().normalize();
        if (!Files.exists(target) || !Files.isRegularFile(target)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Local file not found");
        }
        return target;
    }

    /**
     * 构造 inline 预览响应的通用响应头。
     *
     * @param file 文件实体
     * @return 响应构造器
     */
    private ResponseEntity.BodyBuilder baseInlineHeaders(StorageFileEntity file) {
        String contentType = file.getContentType() == null || file.getContentType().isBlank()
                ? MediaType.APPLICATION_OCTET_STREAM_VALUE
                : file.getContentType();
        return ResponseEntity.ok()
                .contentType(MediaType.parseMediaType(contentType))
                .header(HttpHeaders.CONTENT_DISPOSITION, ContentDisposition.inline()
                        .filename(file.getOriginalFilename() == null || file.getOriginalFilename().isBlank() ? "download" : file.getOriginalFilename(), java.nio.charset.StandardCharsets.UTF_8)
                        .build()
                        .toString());
    }

    /**
     * 将上传文件保存到 MinIO。
     *
     * @param entity 文件元数据实体
     * @param file 上传文件
     */
    private void storeToMinio(StorageFileEntity entity, MultipartFile file) {
        EnterpriseProperties.Minio minio = enterpriseProperties.getMinio();
        String bucket = safeText(minio.getBucket());
        if (bucket.isBlank()) {
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, "MinIO bucket is not configured");
        }
        String objectKey = entity.getBusinessType().toLowerCase(Locale.ROOT)
                + "/" + entity.getBusinessId()
                + "/" + entity.getFieldName()
                + "/" + storageObjectName(entity);
        try {
            ensureBucket(bucket);
            try (InputStream input = file.getInputStream()) {
                minioClient().putObject(PutObjectArgs.builder()
                        .bucket(bucket)
                        .object(objectKey)
                        .contentType(entity.getContentType().isBlank() ? "application/octet-stream" : entity.getContentType())
                        .stream(input, file.getSize(), -1)
                        .build());
            }
        } catch (Exception ex) {
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, "Cannot store upload file to MinIO: " + ex.getMessage());
        }
        entity.setStorageType("MINIO");
        entity.setBucket(bucket);
        entity.setObjectKey(objectKey);
        entity.setLocalPath("");
        entity.setUrl("minio://" + bucket + "/" + objectKey);
    }

    /**
     * 将字节数组保存到本地磁盘。
     *
     * @param entity 文件元数据实体
     * @param bytes 文件字节
     */
    private void storeBytesToLocal(StorageFileEntity entity, byte[] bytes) {
        Path root = Path.of(storageProperties.getLocalRoot()).toAbsolutePath().normalize();
        Path target = root
                .resolve(entity.getBusinessType().toLowerCase(Locale.ROOT))
                .resolve(entity.getBusinessId())
                .resolve(entity.getFieldName())
                .resolve(storageObjectName(entity))
                .normalize();
        if (!target.startsWith(root)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid storage path");
        }
        try {
            Files.createDirectories(target.getParent());
            Files.write(target, bytes);
        } catch (IOException ex) {
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, "Cannot store file: " + ex.getMessage());
        }
        entity.setStorageType("LOCAL");
        entity.setLocalPath(target.toString());
        entity.setObjectKey("");
        entity.setBucket("");
    }

    /**
     * 将字节数组保存到 MinIO。
     *
     * @param entity 文件元数据实体
     * @param bytes 文件字节
     */
    private void storeBytesToMinio(StorageFileEntity entity, byte[] bytes) {
        EnterpriseProperties.Minio minio = enterpriseProperties.getMinio();
        String bucket = safeText(minio.getBucket());
        if (bucket.isBlank()) {
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, "MinIO bucket is not configured");
        }
        String objectKey = entity.getBusinessType().toLowerCase(Locale.ROOT)
                + "/" + entity.getBusinessId()
                + "/" + entity.getFieldName()
                + "/" + storageObjectName(entity);
        try {
            ensureBucket(bucket);
            try (InputStream input = new java.io.ByteArrayInputStream(bytes)) {
                minioClient().putObject(PutObjectArgs.builder()
                        .bucket(bucket)
                        .object(objectKey)
                        .contentType(entity.getContentType().isBlank() ? "application/octet-stream" : entity.getContentType())
                        .stream(input, bytes.length, -1)
                        .build());
            }
        } catch (Exception ex) {
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, "Cannot store file to MinIO: " + ex.getMessage());
        }
        entity.setStorageType("MINIO");
        entity.setBucket(bucket);
        entity.setObjectKey(objectKey);
        entity.setLocalPath("");
        entity.setUrl("minio://" + bucket + "/" + objectKey);
    }

    /**
     * 确保 MinIO bucket 存在。
     *
     * @param bucket bucket 名称
     * @throws Exception MinIO 调用失败时抛出
     */
    private void ensureBucket(String bucket) throws Exception {
        MinioClient client = minioClient();
        boolean exists = client.bucketExists(BucketExistsArgs.builder().bucket(bucket).build());
        if (!exists) {
            client.makeBucket(MakeBucketArgs.builder().bucket(bucket).build());
        }
    }

    /**
     * 根据配置构造 MinIO 客户端。
     *
     * @return MinIO 客户端
     */
    private MinioClient minioClient() {
        EnterpriseProperties.Minio minio = enterpriseProperties.getMinio();
        return MinioClient.builder()
                .endpoint(minio.getEndpoint())
                .credentials(minio.getAccessKey(), minio.getSecretKey())
                .build();
    }

    /**
     * 从 MultipartFile 中获取安全文件名。
     *
     * @param file 上传文件
     * @return 安全文件名
     */
    private String safeFilename(MultipartFile file) {
        String filename = file.getOriginalFilename();
        return safeFilename(filename);
    }

    /**
     * 清理文件名中的路径分隔符。
     *
     * @param filename 原始文件名
     * @return 安全文件名
     */
    private String safeFilename(String filename) {
        if (filename == null || filename.isBlank()) {
            return "upload";
        }
        return filename.replace("\\", "_").replace("/", "_").trim();
    }

    /**
     * 生成仅用于存储后端的 ASCII 对象名。
     *
     * <p>原始文件名仍保存在 {@code originalFilename} 并通过下载/预览响应返回。存储路径不直接使用
     * 原始文件名，避免容器 locale 不是 UTF-8 时中文文件名触发 {@link java.nio.file.InvalidPathException}。</p>
     *
     * @param entity 文件元数据
     * @return 稳定存储对象名
     */
    private String storageObjectName(StorageFileEntity entity) {
        return entity.getId() + safeExtension(entity.getOriginalFilename());
    }

    /**
     * 提取适合存储路径使用的 ASCII 扩展名。
     *
     * @param filename 原始文件名
     * @return 包含点号的扩展名，无法识别时返回空字符串
     */
    private String safeExtension(String filename) {
        String safe = safeFilename(filename);
        int dot = safe.lastIndexOf('.');
        if (dot < 0 || dot == safe.length() - 1) {
            return "";
        }
        String extension = safe.substring(dot + 1).toLowerCase(Locale.ROOT);
        if (!extension.matches("[a-z0-9]{1,16}")) {
            return "";
        }
        return "." + extension;
    }

    /**
     * 将字符串安全转换为去首尾空白文本。
     *
     * @param value 原始字符串
     * @return 文本；null 返回空字符串
     */
    private String safeText(String value) {
        return value == null ? "" : value.trim();
    }
}
