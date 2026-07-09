package com.aigeneration.questionbank.domain.service;

import com.aigeneration.questionbank.domain.entity.ImportTaskEntity;
import com.aigeneration.questionbank.domain.mapper.ImportTaskMapper;
import com.aigeneration.questionbank.domain.support.JsonSupport;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

/**
 * 导入任务编排服务。
 *
 * <p>当前主要负责失败 OCR job 的重试编排：判断试卷/答案 OCR 状态、调用 worker 重试接口、
 * 并更新 Java 侧任务状态和重试元数据。</p>
 */
@Service
public class ImportTaskOrchestrationService {
    /**
     * 导入任务表访问对象。
     */
    private final ImportTaskMapper mapper;

    /**
     * Python worker 客户端，用于调用 OCR 重试接口。
     */
    private final PythonWorkerClient pythonWorkerClient;

    /**
     * JSON 辅助组件，用于更新任务原始快照中的重试信息。
     */
    private final JsonSupport json;

    /**
     * 注入导入任务 Mapper、worker 客户端和 JSON 工具。
     *
     * @param mapper 导入任务 Mapper
     * @param pythonWorkerClient Python worker 客户端
     * @param json JSON 辅助组件
     */
    public ImportTaskOrchestrationService(ImportTaskMapper mapper, PythonWorkerClient pythonWorkerClient, JsonSupport json) {
        this.mapper = mapper;
        this.pythonWorkerClient = pythonWorkerClient;
        this.json = json;
    }

    /**
     * 重试导入任务中失败的 OCR job。
     *
     * @param taskId 导入任务 ID
     * @return 重试结果，包含重试次数和被重试的 job
     */
    public Map<String, Object> retry(String taskId) {
        ImportTaskEntity task = mapper.selectById(taskId);
        if (task == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Import task not found");
        }
        Map<String, Object> retried = new LinkedHashMap<>();
        if (shouldRetry(task.getPaperOcrStatus()) && notBlank(task.getPaperOcrJobId())) {
            retried.put("paper", pythonWorkerClient.postJson("/worker/ocr/" + task.getPaperOcrJobId() + "/retry", Map.of()));
        }
        if (shouldRetry(task.getAnswerOcrStatus()) && notBlank(task.getAnswerOcrJobId())) {
            retried.put("answer", pythonWorkerClient.postJson("/worker/ocr/" + task.getAnswerOcrJobId() + "/retry", Map.of()));
        }
        if (retried.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "No failed OCR job can be retried");
        }
        Map<String, Object> raw = json.readMap(task.getRawJson());
        raw.put("retryable", true);
        raw.put("lastRetryAt", LocalDateTime.now().toString());
        raw.put("retriedJobs", retried);
        int retryCount = intValue(raw.get("retryCount")) + 1;
        raw.put("retryCount", retryCount);
        raw.putIfAbsent("maxRetryCount", 3);
        task.setStatus("处理中");
        task.setFailureReason("");
        task.setRawJson(json.write(raw));
        task.setUpdatedAt(LocalDateTime.now());
        mapper.updateById(task);
        return Map.of(
                "taskId", taskId,
                "status", task.getStatus(),
                "retryCount", retryCount,
                "retriedJobs", retried
        );
    }

    /**
     * 重新扫描导入任务的原始 OCR 文件，保留当前已提取和已编辑题目。
     *
     * @param taskId 导入任务 ID
     * @return 重扫启动后的任务状态
     */
    public Map<String, Object> rescan(String taskId) {
        ImportTaskEntity task = mapper.selectById(taskId);
        if (task == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Import task not found");
        }
        if (isProcessing(task.getStatus()) || isProcessing(task.getPaperOcrStatus()) || isProcessing(task.getAnswerOcrStatus())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "任务正在处理中，请等待当前处理完成后再重新扫描");
        }
        Map<String, Object> rescanned = new LinkedHashMap<>();
        if (notBlank(task.getPaperOcrJobId())) {
            rescanned.put("paper", pythonWorkerClient.postJson("/worker/ocr/" + task.getPaperOcrJobId() + "/retry", Map.of()));
        }
        if (notBlank(task.getAnswerOcrJobId())) {
            rescanned.put("answer", pythonWorkerClient.postJson("/worker/ocr/" + task.getAnswerOcrJobId() + "/retry", Map.of()));
        }
        if (rescanned.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "No OCR job can be rescanned");
        }

        Map<String, Object> raw = json.readMap(task.getRawJson());
        raw.put("rescanInProgress", true);
        raw.put("rescanStartedAt", LocalDateTime.now().toString());
        raw.put("rescanPreviousStatus", task.getStatus());
        raw.put("rescannedJobs", rescanned);
        task.setStatus("处理中");
        task.setPaperOcrStatus("处理中");
        if (notBlank(task.getAnswerOcrJobId())) {
            task.setAnswerOcrStatus("处理中");
        }
        if (rescanned.get("paper") != null) {
            task.setPaperOcrJobJson(json.write(rescanned.get("paper")));
            raw.put("paperOcrJob", rescanned.get("paper"));
        }
        if (rescanned.get("answer") != null) {
            task.setAnswerOcrJobJson(json.write(rescanned.get("answer")));
            raw.put("answerOcrJob", rescanned.get("answer"));
        }
        raw.put("status", task.getStatus());
        raw.put("paperOcrStatus", task.getPaperOcrStatus());
        raw.put("answerOcrStatus", task.getAnswerOcrStatus());
        task.setFailureReason("");
        task.setRawJson(json.write(raw));
        task.setUpdatedAt(LocalDateTime.now());
        mapper.updateById(task);
        return Map.of(
                "id", taskId,
                "taskId", taskId,
                "status", task.getStatus(),
                "paperOcrStatus", task.getPaperOcrStatus(),
                "answerOcrStatus", task.getAnswerOcrStatus(),
                "rescanInProgress", true,
                "rescannedJobs", rescanned
        );
    }

    /**
     * 判断 OCR 状态是否允许重试。
     *
     * @param status OCR 状态
     * @return true 表示失败且可重试
     */
    private boolean shouldRetry(String status) {
        return "failed".equalsIgnoreCase(status)
                || "error".equalsIgnoreCase(status)
                || "失败".equals(status);
    }

    /**
     * 判断状态是否表示任务仍在处理。
     *
     * @param status 原始状态
     * @return true 表示处理中
     */
    private boolean isProcessing(String status) {
        return "处理中".equals(status)
                || "pending".equalsIgnoreCase(status)
                || "queued".equalsIgnoreCase(status)
                || "running".equalsIgnoreCase(status)
                || "processing".equalsIgnoreCase(status);
    }

    /**
     * 判断字符串是否非空。
     *
     * @param value 原始字符串
     * @return true 表示非空
     */
    private boolean notBlank(String value) {
        return value != null && !value.isBlank();
    }

    /**
     * 将对象转换为整数。
     *
     * @param value 原始值
     * @return 整数；无法解析时返回 0
     */
    private int intValue(Object value) {
        if (value instanceof Number number) {
            return number.intValue();
        }
        if (value == null || String.valueOf(value).isBlank()) {
            return 0;
        }
        try {
            return Integer.parseInt(String.valueOf(value));
        } catch (NumberFormatException ex) {
            return 0;
        }
    }
}
