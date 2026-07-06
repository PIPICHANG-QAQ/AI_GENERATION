package com.aigeneration.questionbank.domain.service;

import com.aigeneration.questionbank.domain.entity.ExportJobEntity;
import com.aigeneration.questionbank.domain.entity.StorageFileEntity;
import com.aigeneration.questionbank.domain.mapper.ExportJobMapper;
import com.aigeneration.questionbank.domain.support.Ids;
import com.aigeneration.questionbank.domain.support.JsonSupport;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

/**
 * 试卷导出流程服务。
 *
 * <p>负责创建导出 job、组装试卷导出请求、调用 Python worker 渲染 DOCX/PDF、保存导出文件
 * 并返回可预览响应。</p>
 */
@Service
public class PaperExportFlowService {
    /**
     * 导出 job 表访问对象。
     */
    private final ExportJobMapper mapper;

    /**
     * 试卷服务，用于读取完整试卷和题目快照。
     */
    private final PaperService paperService;

    /**
     * Python worker 客户端，用于调用导出渲染接口。
     */
    private final PythonWorkerClient pythonWorkerClient;

    /**
     * 文件存储服务，用于保存导出产物。
     */
    private final JavaFileStorageService fileStorageService;

    /**
     * JSON 辅助组件，用于保存导出 job 请求和响应。
     */
    private final JsonSupport json;

    /**
     * 注入导出流程所需依赖。
     *
     * @param mapper 导出 job Mapper
     * @param paperService 试卷服务
     * @param pythonWorkerClient Python worker 客户端
     * @param fileStorageService 文件存储服务
     * @param json JSON 辅助组件
     */
    public PaperExportFlowService(
            ExportJobMapper mapper,
            PaperService paperService,
            PythonWorkerClient pythonWorkerClient,
            JavaFileStorageService fileStorageService,
            JsonSupport json
    ) {
        this.mapper = mapper;
        this.paperService = paperService;
        this.pythonWorkerClient = pythonWorkerClient;
        this.fileStorageService = fileStorageService;
        this.json = json;
    }

    /**
     * 导出试卷并返回导出文件响应。
     *
     * @param paperId 试卷 ID
     * @param format 导出格式，支持 docx/pdf
     * @param variant 答案展示版本
     * @return 导出文件响应
     */
    public ResponseEntity<Resource> export(String paperId, String format, String variant) {
        String safeFormat = normalizeFormat(format);
        String safeVariant = normalizeVariant(variant);
        Map<String, Object> paper = paperService.get(paperId);
        ExportJobEntity job = createJob(paperId, safeFormat, safeVariant, paper);
        try {
            Map<String, Object> request = new LinkedHashMap<>();
            request.put("exportJobId", job.getId());
            request.put("paper", paper);
            request.put("questions", paper.get("questions"));
            request.put("format", safeFormat);
            request.put("variant", safeVariant);
            ResponseEntity<byte[]> generated = pythonWorkerClient.postJsonForFile("/worker/export/render", request);
            String contentType = contentType(generated, safeFormat);
            String filename = filename(generated, job.getId() + "." + safeFormat);
            StorageFileEntity file = fileStorageService.storePaperExport(job.getId(), filename, contentType, generated.getBody());
            job.setStatus("success");
            job.setFileId(file.getId());
            job.setResponseJson(json.write(Map.of(
                    "filename", filename,
                    "contentType", contentType,
                    "sizeBytes", file.getSizeBytes(),
                    "storageFileId", file.getId()
            )));
            job.setUpdatedAt(LocalDateTime.now());
            mapper.updateById(job);
            return fileStorageService.inlineResponse(file);
        } catch (RuntimeException ex) {
            job.setStatus("failed");
            job.setFailureReason(ex.getMessage());
            job.setUpdatedAt(LocalDateTime.now());
            mapper.updateById(job);
            throw ex;
        }
    }

    /**
     * 查询导出 job 列表。
     *
     * @param paperId 试卷 ID 过滤
     * @return 导出 job 列表
     */
    public List<Map<String, Object>> listJobs(String paperId) {
        QueryWrapper<ExportJobEntity> query = new QueryWrapper<ExportJobEntity>()
                .orderByDesc("created_at");
        if (paperId != null && !paperId.isBlank()) {
            query.eq("paper_id", paperId);
        }
        return mapper.selectList(query).stream().map(this::toMap).toList();
    }

    /**
     * 查询单个导出 job。
     *
     * @param jobId 导出 job ID
     * @return 导出 job 响应 Map
     */
    public Map<String, Object> getJob(String jobId) {
        ExportJobEntity job = mapper.selectById(jobId);
        if (job == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Export job not found");
        }
        return toMap(job);
    }

    /**
     * 创建运行中的导出 job。
     *
     * @param paperId 试卷 ID
     * @param format 导出格式
     * @param variant 导出版本
     * @param paper 试卷快照
     * @return 新建导出 job
     */
    private ExportJobEntity createJob(String paperId, String format, String variant, Map<String, Object> paper) {
        LocalDateTime now = LocalDateTime.now();
        ExportJobEntity job = new ExportJobEntity();
        job.setId(Ids.next("export_job"));
        job.setPaperId(paperId);
        job.setFormat(format);
        job.setVariant(variant);
        job.setStatus("running");
        job.setRequestJson(json.write(Map.of("paperId", paperId, "format", format, "variant", variant, "paperTitle", paper.get("title"))));
        job.setCreatedAt(now);
        job.setUpdatedAt(now);
        mapper.insert(job);
        return job;
    }

    /**
     * 将导出 job 实体序列化为 API 响应 Map。
     *
     * @param job 导出 job 实体
     * @return 响应 Map
     */
    private Map<String, Object> toMap(ExportJobEntity job) {
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("id", job.getId());
        item.put("paperId", job.getPaperId());
        item.put("format", job.getFormat());
        item.put("variant", job.getVariant());
        item.put("status", job.getStatus());
        item.put("fileId", job.getFileId());
        item.put("failureReason", job.getFailureReason());
        item.put("request", json.readMap(job.getRequestJson()));
        item.put("response", json.readMap(job.getResponseJson()));
        item.put("createdAt", job.getCreatedAt());
        item.put("updatedAt", job.getUpdatedAt());
        return item;
    }

    /**
     * 规范化导出格式。
     *
     * @param format 原始格式
     * @return pdf 或 docx
     */
    private String normalizeFormat(String format) {
        return "pdf".equalsIgnoreCase(format) ? "pdf" : "docx";
    }

    /**
     * 规范化导出版本。
     *
     * @param variant 原始版本
     * @return 版本值；缺失时为 teacher
     */
    private String normalizeVariant(String variant) {
        return variant == null || variant.isBlank() ? "teacher" : variant;
    }

    /**
     * 解析导出文件 Content-Type。
     *
     * @param response worker 文件响应
     * @param format 导出格式
     * @return 内容类型
     */
    private String contentType(ResponseEntity<byte[]> response, String format) {
        String header = response.getHeaders().getFirst(HttpHeaders.CONTENT_TYPE);
        if (header != null && !header.isBlank()) {
            return header;
        }
        if ("pdf".equals(format)) {
            return "application/pdf";
        }
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
    }

    /**
     * 从 Content-Disposition 解析文件名。
     *
     * @param response worker 文件响应
     * @param fallback 兜底文件名
     * @return 文件名
     */
    private String filename(ResponseEntity<byte[]> response, String fallback) {
        String disposition = response.getHeaders().getFirst(HttpHeaders.CONTENT_DISPOSITION);
        if (disposition == null || disposition.isBlank()) {
            return fallback;
        }
        for (String part : disposition.split(";")) {
            String trimmed = part.trim();
            if (trimmed.startsWith("filename=")) {
                return trimmed.substring("filename=".length()).replace("\"", "").trim();
            }
        }
        return fallback;
    }
}
