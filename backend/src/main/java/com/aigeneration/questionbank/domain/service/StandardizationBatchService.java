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
import java.util.concurrent.CompletionService;
import java.util.concurrent.ExecutorCompletionService;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import jakarta.annotation.PreDestroy;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
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
    private final int maxConcurrency = configuredConcurrency();
    private final ExecutorService coordinator = Executors.newSingleThreadExecutor(runnable -> daemonThread(runnable, "standardization-coordinator"));
    private final ExecutorService workers = Executors.newFixedThreadPool(maxConcurrency, runnable -> daemonThread(runnable, "standardization-worker"));

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
        job.setTotalItems(questions.size());
        job.setCompletedQuestions(0);
        job.setCompletedItems(0);
        job.setSuccessItems(0);
        job.setFailedItems(0);
        job.setMaxConcurrency(maxConcurrency);
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
            item.setTotalItems(1);
            item.setCompletedItems(0);
            item.setSuccessItems(0);
            item.setFailedItems(0);
            item.setCreatedAt(now);
            item.setUpdatedAt(now);
            itemMapper.insert(item);
        }
        Map<String, Object> created = toMap(job, itemMapper.selectByJobId(job.getId()));
        startAfterCommit(job.getId());
        return created;
    }

    public Map<String, Object> get(String taskId, String jobId) {
        StandardizationBatchJobEntity job = requireJob(taskId, jobId);
        return toMap(job, itemMapper.selectByJobId(jobId));
    }

    @Transactional
    public Map<String, Object> cancel(String taskId, String jobId) {
        StandardizationBatchJobEntity job = requireJob(taskId, jobId);
        if (List.of("completed", "cancelled", "failed", "partial_failed", "partial_review").contains(job.getStatus())) {
            return toMap(job, itemMapper.selectByJobId(jobId));
        }
        job.setStatus("cancelling");
        job.setCancelRequestedAt(LocalDateTime.now());
        job.setUpdatedAt(LocalDateTime.now());
        jobMapper.updateById(job);
        Map<String, Object> result = toMap(job, itemMapper.selectByJobId(jobId));
        startAfterCommit(jobId);
        return result;
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
        Map<String, Object> result = toMap(job, itemMapper.selectByJobId(jobId));
        startAfterCommit(jobId);
        return result;
    }

    private void startAfterCommit(String jobId) {
        if (!TransactionSynchronizationManager.isSynchronizationActive()) {
            start(jobId);
            return;
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override public void afterCommit() { start(jobId); }
        });
    }

    /** Start or continue a persisted job without blocking the HTTP request. */
    public void start(String jobId) {
        coordinator.submit(() -> runJob(jobId));
    }

    private void runJob(String jobId) {
        StandardizationBatchJobEntity job = jobMapper.selectById(jobId);
        if (job == null || !List.of("queued", "running").contains(job.getStatus())) return;
        job.setStatus("running");
        if (job.getStartedAt() == null) job.setStartedAt(LocalDateTime.now());
        job.setUpdatedAt(LocalDateTime.now());
        jobMapper.updateById(job);
        List<StandardizationBatchItemEntity> queued = itemMapper.selectByJobId(jobId).stream()
                .filter(item -> "queued".equals(item.getStatus()) || "running".equals(item.getStatus()))
                .toList();
        CompletionService<Void> completion = new ExecutorCompletionService<>(workers);
        int cursor = 0;
        int active = 0;
        try {
            while (cursor < queued.size() || active > 0) {
                while (active < maxConcurrency && cursor < queued.size() && !cancellationRequested(jobId)) {
                    StandardizationBatchItemEntity item = queued.get(cursor++);
                    completion.submit(() -> { processItem(job, item); return null; });
                    active++;
                }
                if (active == 0) break;
                Future<Void> done = completion.take();
                done.get();
                active--;
            }
        } catch (Exception ignored) {
            Thread.currentThread().interrupt();
        }
        finishJob(jobId);
    }

    private void processItem(StandardizationBatchJobEntity job, StandardizationBatchItemEntity item) {
        ImportQuestionEntity question = questionService.getQuestion(item.getQuestionId());
        if (question == null) {
            failItem(item, "Question no longer exists");
            return;
        }
        StandardizationBatchItemEntity reused = itemMapper.selectSuccessfulByInputHash(item.getInputHash());
        if (reused != null && !item.getId().equals(reused.getId())) {
            item.setExecutionPath("cache");
            item.setWriteDecision("unchanged");
            item.setModelInvoked(false);
            item.setCacheHit(true);
            item.setProviderCallAttempts(0);
            succeedItem(item);
            return;
        }
        for (int attempt = number(item.getAttemptCount()) + 1; attempt <= 3; attempt++) {
            item.setStatus("running");
            item.setAttemptCount(attempt);
            if (item.getStartedAt() == null) item.setStartedAt(LocalDateTime.now());
            item.setUpdatedAt(LocalDateTime.now());
            itemMapper.updateById(item);
            try {
                Map<String, Object> response = ai.standardizeImportQuestion(
                        job.getTaskId(),
                        item.getQuestionId(),
                        Map.of(
                                "markdown", editableMarkdown(question),
                                "writeResult", true,
                                "requestSource", attempt == 1 ? "global" : "retry"
                        )
                );
                persistExecutionMetadata(item, response);
                if ("review_required".equals(text(response.get("writeDecision")))) {
                    reviewItem(item);
                    return;
                }
                if (!Boolean.TRUE.equals(response.get("writeResult"))) {
                    throw new IllegalStateException("Standardizer did not save the question");
                }
                succeedItem(item);
                return;
            } catch (RuntimeException ex) {
                if (attempt >= 3 || !retryable(ex)) {
                    failItem(item, ex.getMessage());
                    return;
                }
                sleepRetry(attempt);
            }
        }
    }

    private void succeedItem(StandardizationBatchItemEntity item) {
        item.setStatus("success");
        item.setCompletedItems(number(item.getTotalItems()));
        item.setSuccessItems(number(item.getTotalItems()));
        item.setFailedItems(0);
        item.setErrorMessage(null);
        item.setFinishedAt(LocalDateTime.now());
        item.setUpdatedAt(LocalDateTime.now());
        itemMapper.updateById(item);
    }

    private void reviewItem(StandardizationBatchItemEntity item) {
        item.setStatus("review_required");
        item.setCompletedItems(1);
        item.setSuccessItems(0);
        item.setFailedItems(0);
        item.setErrorMessage(null);
        item.setFinishedAt(LocalDateTime.now());
        item.setUpdatedAt(LocalDateTime.now());
        itemMapper.updateById(item);
    }

    private void persistExecutionMetadata(StandardizationBatchItemEntity item, Map<String, Object> response) {
        item.setExecutionPath(text(response.get("executionPath")));
        item.setWriteDecision(text(response.get("writeDecision")));
        item.setModelInvoked(Boolean.TRUE.equals(response.get("modelInvoked")));
        item.setCacheHit(Boolean.TRUE.equals(response.get("cacheHit")));
        item.setProviderCallAttempts(integer(response.get("providerCallAttempts")));
        item.setReviewReasonsJson(json.write(response.get("reviewReasons")));
        Map<String, Object> standardizer = mapValue(response.get("standardizer"));
        item.setAdaptiveConcurrencyJson(json.write(standardizer.get("adaptiveConcurrency")));
    }

    private void failItem(StandardizationBatchItemEntity item, String message) {
        item.setStatus("failed");
        item.setCompletedItems(number(item.getTotalItems()));
        item.setSuccessItems(0);
        item.setFailedItems(number(item.getTotalItems()));
        item.setErrorMessage(text(message));
        item.setFinishedAt(LocalDateTime.now());
        item.setUpdatedAt(LocalDateTime.now());
        itemMapper.updateById(item);
    }

    private boolean cancellationRequested(String jobId) {
        StandardizationBatchJobEntity latest = jobMapper.selectById(jobId);
        return latest == null || List.of("cancelling", "cancelled").contains(latest.getStatus());
    }

    private void finishJob(String jobId) {
        StandardizationBatchJobEntity job = jobMapper.selectById(jobId);
        if (job == null) return;
        List<StandardizationBatchItemEntity> items = itemMapper.selectByJobId(jobId);
        int succeeded = items.stream().filter(item -> "success".equals(item.getStatus())).mapToInt(item -> number(item.getTotalItems())).sum();
        int review = (int) items.stream().filter(item -> "review_required".equals(item.getStatus())).count();
        int failed = items.stream().filter(item -> "failed".equals(item.getStatus())).mapToInt(item -> number(item.getTotalItems())).sum();
        int completedQuestions = (int) items.stream().filter(item -> List.of("success", "review_required", "failed").contains(item.getStatus())).count();
        job.setCompletedQuestions(completedQuestions);
        job.setCompletedItems(succeeded + review + failed);
        job.setSuccessItems(succeeded);
        job.setFailedItems(failed);
        if ("cancelling".equals(job.getStatus())) job.setStatus("cancelled");
        else if (failed == 0 && review > 0) job.setStatus("partial_review");
        else if (failed == 0) job.setStatus("completed");
        else if (succeeded == 0) job.setStatus("failed");
        else job.setStatus("partial_failed");
        job.setFinishedAt(LocalDateTime.now());
        job.setUpdatedAt(LocalDateTime.now());
        jobMapper.updateById(job);
    }

    private boolean retryable(RuntimeException ex) {
        if (ex instanceof ResponseStatusException response) {
            int status = response.getStatusCode().value();
            return status == 429 || status >= 500;
        }
        String message = text(ex.getMessage()).toLowerCase(java.util.Locale.ROOT);
        return message.contains("timeout") || message.contains("timed out");
    }

    private void sleepRetry(int attempt) {
        long delay = attempt == 1 ? 2000 : 5000;
        String override = System.getProperty("AI_STANDARDIZATION_RETRY_DELAY_MS", System.getenv("AI_STANDARDIZATION_RETRY_DELAY_MS"));
        if (override != null && !override.isBlank()) {
            try { delay = Math.max(0, Long.parseLong(override)); } catch (NumberFormatException ignored) { delay = attempt == 1 ? 2000 : 5000; }
        }
        try {
            Thread.sleep(delay);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
        }
    }

    private String editableMarkdown(ImportQuestionEntity question) {
        return nonBlank(question.getManualMarkdown()) ? question.getManualMarkdown() : text(question.getStemMarkdown());
    }

    /** Requeue interrupted items and resume jobs after a server restart. */
    @EventListener(ApplicationReadyEvent.class)
    public void recoverOnStartup() {
        for (StandardizationBatchJobEntity job : jobMapper.selectRecoverableJobs()) {
            for (StandardizationBatchItemEntity item : itemMapper.selectByJobId(job.getId())) {
                if ("running".equals(item.getStatus())) {
                    item.setStatus("queued");
                    item.setUpdatedAt(LocalDateTime.now());
                    itemMapper.updateById(item);
                }
            }
            job.setStatus("queued");
            job.setUpdatedAt(LocalDateTime.now());
            jobMapper.updateById(job);
            start(job.getId());
        }
    }

    @PreDestroy
    public void shutdown() {
        coordinator.shutdownNow();
        workers.shutdownNow();
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
            item.setExecutionPath(null);
            item.setWriteDecision(null);
            item.setModelInvoked(null);
            item.setCacheHit(null);
            item.setProviderCallAttempts(0);
            item.setReviewReasonsJson(null);
            item.setAdaptiveConcurrencyJson(null);
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

    private String inputHash(ImportQuestionEntity question) {
        String value = String.join("|",
                "standardizer-v1",
                text(question.getId()),
                text(question.getManualMarkdown()),
                text(question.getStemMarkdown()),
                text(question.getAnswer()),
                text(question.getAnalysis()),
                text(question.getChildrenJson()),
                text(question.getOptionsJson()),
                text(question.getImagesJson()),
                text(question.getImagePlacementsJson())
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
        value.put("rulesCount", countPath(items, "rules"));
        value.put("ocrFallbackCount", countPath(items, "ocr-fallback"));
        value.put("cacheHitCount", (int) items.stream().filter(item -> Boolean.TRUE.equals(item.getCacheHit()) || "cache".equals(item.getExecutionPath())).count());
        value.put("llmQuestionCount", (int) items.stream().filter(item -> Boolean.TRUE.equals(item.getModelInvoked())).count());
        value.put("reviewRequiredCount", (int) items.stream().filter(item -> "review_required".equals(item.getStatus())).count());
        value.put("failedCount", (int) items.stream().filter(item -> "failed".equals(item.getStatus())).count());
        value.put("providerCallAttempts", items.stream().mapToInt(item -> number(item.getProviderCallAttempts())).sum());
        Map<String, Object> adaptive = latestAdaptiveConcurrency(items);
        value.put("currentLlmConcurrency", integer(adaptive.get("limit")));
        value.put("maximumLlmConcurrency", integer(adaptive.getOrDefault("maximum", 8)));
        List<Map<String, Object>> mappedItems = new ArrayList<>();
        for (StandardizationBatchItemEntity item : items) {
            Map<String, Object> mapped = new LinkedHashMap<>();
            mapped.put("id", item.getId()); mapped.put("questionId", item.getQuestionId()); mapped.put("status", item.getStatus());
            mapped.put("attemptCount", number(item.getAttemptCount())); mapped.put("totalItems", number(item.getTotalItems()));
            mapped.put("completedItems", number(item.getCompletedItems())); mapped.put("successItems", number(item.getSuccessItems()));
            mapped.put("failedItems", number(item.getFailedItems())); mapped.put("executionPath", text(item.getExecutionPath()));
            mapped.put("writeDecision", text(item.getWriteDecision())); mapped.put("modelInvoked", Boolean.TRUE.equals(item.getModelInvoked()));
            mapped.put("cacheHit", Boolean.TRUE.equals(item.getCacheHit())); mapped.put("providerCallAttempts", number(item.getProviderCallAttempts()));
            mapped.put("reviewReasons", json.readList(item.getReviewReasonsJson()));
            mappedItems.add(mapped);
        }
        value.put("items", mappedItems);
        return value;
    }

    private int number(Integer value) { return value == null ? 0 : value; }
    private int integer(Object value) { try { return value == null ? 0 : Integer.parseInt(String.valueOf(value)); } catch (NumberFormatException ignored) { return 0; } }
    @SuppressWarnings("unchecked") private Map<String, Object> mapValue(Object value) { return value instanceof Map<?, ?> map ? (Map<String, Object>) map : Map.of(); }
    private int countPath(List<StandardizationBatchItemEntity> items, String path) { return (int) items.stream().filter(item -> path.equals(item.getExecutionPath())).count(); }
    private Map<String, Object> latestAdaptiveConcurrency(List<StandardizationBatchItemEntity> items) {
        for (int index = items.size() - 1; index >= 0; index--) {
            Map<String, Object> value = json.readMap(items.get(index).getAdaptiveConcurrencyJson());
            if (!value.isEmpty()) return value;
        }
        return Map.of("limit", 0, "maximum", 8);
    }
    private boolean nonBlank(Object... values) { for (Object value : values) if (!text(value).isBlank()) return true; return false; }
    private String text(Object value) { return value == null ? "" : String.valueOf(value).trim(); }
    private static Thread daemonThread(Runnable runnable, String name) { Thread thread = new Thread(runnable, name); thread.setDaemon(true); return thread; }
    private static int configuredConcurrency() {
        String value = System.getProperty("AI_STANDARDIZATION_MAX_CONCURRENCY", System.getenv("AI_STANDARDIZATION_MAX_CONCURRENCY"));
        try { return Math.max(1, Math.min(12, Integer.parseInt(value == null ? "12" : value))); }
        catch (NumberFormatException ignored) { return 12; }
    }
}
