package com.aigeneration.questionbank.domain.service;

import com.aigeneration.questionbank.domain.entity.ImportQuestionEntity;
import com.aigeneration.questionbank.domain.entity.StandardizationBatchItemEntity;
import com.aigeneration.questionbank.domain.entity.StandardizationBatchJobEntity;
import com.aigeneration.questionbank.domain.mapper.StandardizationBatchItemMapper;
import com.aigeneration.questionbank.domain.mapper.StandardizationBatchJobMapper;
import com.aigeneration.questionbank.domain.support.JsonSupport;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

/** Persistent lifecycle for task-wide, question-atomic AI standardization batches. */
@Service
public class StandardizationBatchService {
    private final StandardizationBatchJobMapper jobMapper;
    private final StandardizationBatchItemMapper itemMapper;
    private final ImportQuestionSyncService questionService;
    private final ImportTaskCanonicalizationService canonicalization;
    private final AiFlowOrchestrationService ai;
    private final JsonSupport json;

    public StandardizationBatchService(
            StandardizationBatchJobMapper jobMapper,
            StandardizationBatchItemMapper itemMapper,
            ImportQuestionSyncService questionService,
            ImportTaskCanonicalizationService canonicalization,
            AiFlowOrchestrationService ai,
            JsonSupport json
    ) {
        this.jobMapper = jobMapper;
        this.itemMapper = itemMapper;
        this.questionService = questionService;
        this.canonicalization = canonicalization;
        this.ai = ai;
        this.json = json;
    }

    @Transactional
    public Map<String, Object> create(String taskId) {
        canonicalization.requireReadyForStandardization(taskId);
        if (jobMapper.selectActiveByTaskId(taskId) != null) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "An active standardization job already exists");
        }
        List<ImportQuestionEntity> questions = questionService.listByTask(taskId);
        if (questions.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "No canonical questions are ready for standardization");
        }
        LocalDateTime now = LocalDateTime.now();
        StandardizationBatchJobEntity job = new StandardizationBatchJobEntity();
        job.setId("standardization_job_" + UUID.randomUUID());
        job.setTaskId(taskId);
        job.setStatus("queued");
        job.setTotalQuestions(questions.size());
        job.setTotalItems(questions.stream().mapToInt(this::editableItemCount).sum());
        job.setCompletedQuestions(0);
        job.setCompletedItems(0);
        job.setSuccessItems(0);
        job.setFailedItems(0);
        job.setMaxConcurrency(2);
        job.setCreatedAt(now);
        job.setUpdatedAt(now);
        jobMapper.insert(job);
        for (ImportQuestionEntity question : questions) {
            StandardizationBatchItemEntity item = new StandardizationBatchItemEntity();
            item.setId("standardization_item_" + UUID.randomUUID());
            item.setJobId(job.getId());
            item.setQuestionId(question.getId());
            item.setStatus("queued");
            item.setInputHash(inputHash(question));
            item.setAttemptCount(0);
            item.setTotalItems(editableItemCount(question));
            item.setCompletedItems(0);
            item.setSuccessItems(0);
            item.setFailedItems(0);
            item.setCreatedAt(now);
            item.setUpdatedAt(now);
            itemMapper.insert(item);
        }
        return toMap(job, itemMapper.selectByJobId(job.getId()));
    }

    public Map<String, Object> get(String taskId, String jobId) {
        StandardizationBatchJobEntity job = requireJob(taskId, jobId);
        return toMap(job, itemMapper.selectByJobId(jobId));
    }

    @Transactional
    public Map<String, Object> cancel(String taskId, String jobId) {
        StandardizationBatchJobEntity job = requireJob(taskId, jobId);
        if (List.of("completed", "cancelled", "failed", "partial_failed").contains(job.getStatus())) {
            return toMap(job, itemMapper.selectByJobId(jobId));
        }
        job.setStatus("cancelling");
        job.setCancelRequestedAt(LocalDateTime.now());
        job.setUpdatedAt(LocalDateTime.now());
        jobMapper.updateById(job);
        return toMap(job, itemMapper.selectByJobId(jobId));
    }

    @Transactional
    public Map<String, Object> resume(String taskId, String jobId) {
        StandardizationBatchJobEntity job = requireJob(taskId, jobId);
        resetItems(itemMapper.selectByJobId(jobId), false);
        job.setStatus("queued");
        job.setCancelRequestedAt(null);
        job.setFinishedAt(null);
        job.setUpdatedAt(LocalDateTime.now());
        jobMapper.updateById(job);
        return toMap(job, itemMapper.selectByJobId(jobId));
    }

    @Transactional
    public Map<String, Object> retryFailed(String taskId, String jobId) {
        StandardizationBatchJobEntity job = requireJob(taskId, jobId);
        resetItems(itemMapper.selectByJobId(jobId), true);
        job.setStatus("queued");
        job.setFinishedAt(null);
        job.setUpdatedAt(LocalDateTime.now());
        jobMapper.updateById(job);
        return toMap(job, itemMapper.selectByJobId(jobId));
    }

    private void resetItems(List<StandardizationBatchItemEntity> items, boolean failedOnly) {
        for (StandardizationBatchItemEntity item : items) {
            if ("success".equals(item.getStatus()) || (failedOnly && !"failed".equals(item.getStatus()))) continue;
            item.setStatus("queued");
            item.setAttemptCount(0);
            item.setCompletedItems(0);
            item.setSuccessItems(0);
            item.setFailedItems(0);
            item.setErrorMessage(null);
            item.setStartedAt(null);
            item.setFinishedAt(null);
            item.setUpdatedAt(LocalDateTime.now());
            itemMapper.updateById(item);
        }
    }

    private StandardizationBatchJobEntity requireJob(String taskId, String jobId) {
        StandardizationBatchJobEntity job = jobMapper.selectByTaskAndId(taskId, jobId);
        if (job == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Standardization job not found");
        return job;
    }

    private int editableItemCount(ImportQuestionEntity question) {
        int count = nonBlank(question.getManualMarkdown(), question.getStemMarkdown()) ? 1 : 0;
        if (nonBlank(question.getAnswer())) count++;
        if (nonBlank(question.getAnalysis())) count++;
        for (Object raw : json.readList(question.getChildrenJson())) {
            if (!(raw instanceof Map<?, ?> child)) continue;
            if (nonBlank(child.get("manualMarkdown"), child.get("stemMarkdown"), child.get("stem"))) count++;
            if (nonBlank(child.get("answer"))) count++;
            if (nonBlank(child.get("analysis"))) count++;
        }
        return Math.max(1, count);
    }

    private String inputHash(ImportQuestionEntity question) {
        String value = String.join("|",
                "standardizer-v1",
                text(question.getId()),
                text(question.getManualMarkdown()),
                text(question.getStemMarkdown()),
                text(question.getAnswer()),
                text(question.getAnalysis()),
                text(question.getChildrenJson())
        );
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));
            return java.util.HexFormat.of().formatHex(digest);
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException(ex);
        }
    }

    private Map<String, Object> toMap(StandardizationBatchJobEntity job, List<StandardizationBatchItemEntity> items) {
        Map<String, Object> value = new LinkedHashMap<>();
        value.put("id", job.getId()); value.put("taskId", job.getTaskId()); value.put("status", job.getStatus());
        value.put("totalQuestions", job.getTotalQuestions()); value.put("totalItems", job.getTotalItems());
        value.put("completedQuestions", job.getCompletedQuestions()); value.put("completedItems", job.getCompletedItems());
        value.put("successItems", job.getSuccessItems()); value.put("failedItems", job.getFailedItems());
        value.put("maxConcurrency", job.getMaxConcurrency()); value.put("createdAt", job.getCreatedAt());
        List<Map<String, Object>> mappedItems = new ArrayList<>();
        for (StandardizationBatchItemEntity item : items) {
            mappedItems.add(Map.ofEntries(
                    Map.entry("id", item.getId()), Map.entry("questionId", item.getQuestionId()),
                    Map.entry("status", item.getStatus()), Map.entry("attemptCount", number(item.getAttemptCount())),
                    Map.entry("totalItems", number(item.getTotalItems())), Map.entry("completedItems", number(item.getCompletedItems())),
                    Map.entry("successItems", number(item.getSuccessItems())), Map.entry("failedItems", number(item.getFailedItems()))
            ));
        }
        value.put("items", mappedItems);
        return value;
    }

    private int number(Integer value) { return value == null ? 0 : value; }
    private boolean nonBlank(Object... values) { for (Object value : values) if (!text(value).isBlank()) return true; return false; }
    private String text(Object value) { return value == null ? "" : String.valueOf(value).trim(); }
}
