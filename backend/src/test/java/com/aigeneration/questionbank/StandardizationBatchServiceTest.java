package com.aigeneration.questionbank;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.aigeneration.questionbank.domain.entity.ImportQuestionEntity;
import com.aigeneration.questionbank.domain.entity.StandardizationBatchItemEntity;
import com.aigeneration.questionbank.domain.entity.StandardizationBatchJobEntity;
import com.aigeneration.questionbank.domain.mapper.StandardizationBatchItemMapper;
import com.aigeneration.questionbank.domain.mapper.StandardizationBatchJobMapper;
import com.aigeneration.questionbank.domain.service.AiFlowOrchestrationService;
import com.aigeneration.questionbank.domain.service.ImportQuestionSyncService;
import com.aigeneration.questionbank.domain.service.ImportTaskCanonicalizationService;
import com.aigeneration.questionbank.domain.service.StandardizationBatchService;
import com.aigeneration.questionbank.domain.support.JsonSupport;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;

class StandardizationBatchServiceTest {
    private StandardizationBatchJobMapper jobMapper;
    private StandardizationBatchItemMapper itemMapper;
    private ImportQuestionSyncService questionService;
    private ImportTaskCanonicalizationService canonicalization;
    private AiFlowOrchestrationService ai;
    private StandardizationBatchService service;

    @BeforeEach
    void setUp() {
        jobMapper = mock(StandardizationBatchJobMapper.class);
        itemMapper = mock(StandardizationBatchItemMapper.class);
        questionService = mock(ImportQuestionSyncService.class);
        canonicalization = mock(ImportTaskCanonicalizationService.class);
        ai = mock(AiFlowOrchestrationService.class);
        service = new StandardizationBatchService(
                jobMapper,
                itemMapper,
                questionService,
                canonicalization,
                ai,
                new JsonSupport(new ObjectMapper().findAndRegisterModules())
        );
    }

    @AfterEach
    void tearDown() {
        System.clearProperty("AI_STANDARDIZATION_RETRY_DELAY_MS");
        service.shutdown();
    }

    @Test
    void retryableFailureStopsAfterThreeTotalAttempts() throws Exception {
        System.setProperty("AI_STANDARDIZATION_RETRY_DELAY_MS", "0");
        StandardizationBatchJobEntity job = job("job-1", "queued");
        StandardizationBatchItemEntity item = item("item-1", "queued"); item.setTotalItems(1);
        when(jobMapper.selectById("job-1")).thenReturn(job);
        when(itemMapper.selectByJobId("job-1")).thenReturn(List.of(item));
        when(questionService.getQuestion("q1")).thenReturn(question("q1"));
        List<String> requestSources = new java.util.concurrent.CopyOnWriteArrayList<>();
        when(ai.standardizeImportQuestion(any(), any(), any())).thenAnswer(invocation -> {
            Map<String, Object> payload = invocation.getArgument(2);
            requestSources.add(String.valueOf(payload.get("requestSource")));
            throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.BAD_GATEWAY);
        });

        service.start("job-1");
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(2);
        while (!"failed".equals(item.getStatus()) && System.nanoTime() < deadline) Thread.sleep(10);

        assertEquals("failed", item.getStatus());
        assertEquals(3, item.getAttemptCount());
        assertEquals(List.of("global", "retry", "retry"), requestSources);
        verify(ai, org.mockito.Mockito.times(3)).standardizeImportQuestion(any(), any(), any());
    }

    @Test
    void successfulInputHashIsReused() throws Exception {
        StandardizationBatchJobEntity job = job("job-1", "queued");
        StandardizationBatchItemEntity item = item("item-1", "queued"); item.setTotalItems(1); item.setInputHash("same");
        StandardizationBatchItemEntity previous = item("old", "success"); previous.setInputHash("same");
        when(jobMapper.selectById("job-1")).thenReturn(job);
        when(itemMapper.selectByJobId("job-1")).thenReturn(List.of(item));
        when(itemMapper.selectSuccessfulByInputHash("same")).thenReturn(previous);
        when(questionService.getQuestion("q1")).thenReturn(question("q1"));

        service.start("job-1");
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(2);
        while (!"success".equals(item.getStatus()) && System.nanoTime() < deadline) Thread.sleep(10);

        assertEquals("success", item.getStatus());
        verify(ai, never()).standardizeImportQuestion(any(), any(), any());
    }

    @Test
    void startupRecoveryRequeuesRunningItems() {
        StandardizationBatchJobEntity job = job("job-1", "running");
        StandardizationBatchItemEntity item = item("item-1", "running");
        when(jobMapper.selectRecoverableJobs()).thenReturn(List.of(job));
        when(itemMapper.selectByJobId("job-1")).thenReturn(List.of(item));

        service.recoverOnStartup();

        assertEquals("queued", item.getStatus());
        verify(itemMapper).updateById(item);
    }

    @Test
    void dispatchesIndependentQuestionsConcurrentlyAndSavesEachOnce() throws Exception {
        StandardizationBatchJobEntity job = job("job-1", "queued");
        job.setTotalQuestions(3);
        job.setTotalItems(3);
        StandardizationBatchItemEntity first = item("first", "queued"); first.setQuestionId("q1"); first.setTotalItems(1);
        StandardizationBatchItemEntity second = item("second", "queued"); second.setQuestionId("q2"); second.setTotalItems(1);
        StandardizationBatchItemEntity third = item("third", "queued"); third.setQuestionId("q3"); third.setTotalItems(1);
        List<StandardizationBatchItemEntity> items = List.of(first, second, third);
        when(jobMapper.selectById("job-1")).thenReturn(job);
        when(itemMapper.selectByJobId("job-1")).thenReturn(items);
        when(questionService.getQuestion(org.mockito.ArgumentMatchers.anyString())).thenAnswer(invocation -> question(invocation.getArgument(0)));
        CountDownLatch started = new CountDownLatch(3);
        CountDownLatch release = new CountDownLatch(1);
        AtomicInteger active = new AtomicInteger();
        AtomicInteger peak = new AtomicInteger();
        AtomicReference<Map<String, Object>> requestPayload = new AtomicReference<>();
        when(ai.standardizeImportQuestion(any(), any(), any())).thenAnswer(invocation -> {
            requestPayload.set(invocation.getArgument(2));
            int current = active.incrementAndGet();
            peak.accumulateAndGet(current, Math::max);
            started.countDown();
            release.await(2, TimeUnit.SECONDS);
            active.decrementAndGet();
            return Map.of("writeResult", true, "writeDecision", "applied", "executionPath", "rules");
        });

        service.start("job-1");
        org.junit.jupiter.api.Assertions.assertTrue(started.await(2, TimeUnit.SECONDS));
        assertEquals(3, peak.get());
        assertEquals("global", requestPayload.get().get("requestSource"));
        release.countDown();
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(2);
        while (!"completed".equals(job.getStatus()) && System.nanoTime() < deadline) Thread.sleep(10);

        assertEquals("completed", job.getStatus());
        verify(ai, org.mockito.Mockito.times(3)).standardizeImportQuestion(any(), any(), any());
        assertEquals(List.of("success", "success", "success"), items.stream().map(StandardizationBatchItemEntity::getStatus).toList());
        assertEquals(List.of("rules", "rules", "rules"), items.stream().map(StandardizationBatchItemEntity::getExecutionPath).toList());
    }

    @Test
    void createBuildsOneItemPerCanonicalQuestionAndRejectsSecondActiveJob() {
        when(questionService.listByTask("task-1")).thenReturn(List.of(question("q1"), question("q2")));

        Map<String, Object> created = service.create("task-1");

        assertEquals(2, created.get("totalQuestions"));
        assertEquals(2, created.get("totalItems"));
        verify(jobMapper).insert(any(StandardizationBatchJobEntity.class));
        verify(itemMapper, org.mockito.Mockito.times(2)).insert(org.mockito.ArgumentMatchers.argThat(item -> item.getTotalItems() == 1));

        StandardizationBatchJobEntity active = new StandardizationBatchJobEntity();
        active.setId("active-job");
        active.setTaskId("task-1");
        active.setStatus("running");
        when(jobMapper.selectActiveByTaskId("task-1")).thenReturn(active);
        assertThrows(ResponseStatusException.class, () -> service.create("task-1"));
    }

    @Test
    void reviewRequiredIsCompletedWithoutTechnicalFailure() throws Exception {
        StandardizationBatchJobEntity job = job("job-1", "queued");
        job.setTotalQuestions(1);
        job.setTotalItems(1);
        StandardizationBatchItemEntity item = item("item-1", "queued");
        item.setTotalItems(1);
        when(jobMapper.selectById("job-1")).thenReturn(job);
        when(itemMapper.selectByJobId("job-1")).thenReturn(List.of(item));
        when(questionService.getQuestion("q1")).thenReturn(question("q1"));
        when(ai.standardizeImportQuestion(any(), any(), any())).thenReturn(Map.of(
                "writeResult", false,
                "writeDecision", "review_required",
                "executionPath", "llm",
                "modelInvoked", true,
                "reviewReasons", List.of("option_image_reference_removed"),
                "providerCallAttempts", 1
        ));

        service.start("job-1");
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(2);
        while (!"partial_review".equals(job.getStatus()) && System.nanoTime() < deadline) Thread.sleep(10);

        assertEquals("partial_review", job.getStatus());
        assertEquals("review_required", item.getStatus());
        assertEquals("llm", item.getExecutionPath());
        assertEquals(0, job.getFailedItems());
    }

    @Test
    void cancelMarksRequestAndResumeRequeuesNonSuccessfulItems() {
        StandardizationBatchJobEntity job = job("job-1", "running");
        when(jobMapper.selectByTaskAndId("task-1", "job-1")).thenReturn(job);
        StandardizationBatchItemEntity failed = item("item-1", "failed");
        when(itemMapper.selectByJobId("job-1")).thenReturn(List.of(failed));

        assertEquals("cancelling", service.cancel("task-1", "job-1").get("status"));
        assertEquals("queued", service.resume("task-1", "job-1").get("status"));
        assertEquals("queued", failed.getStatus());
    }

    @Test
    void retryFailedResetsOnlyFailedItems() {
        StandardizationBatchJobEntity job = job("job-1", "partial_failed");
        StandardizationBatchItemEntity failed = item("failed", "failed");
        failed.setAttemptCount(3);
        StandardizationBatchItemEntity success = item("success", "success");
        when(jobMapper.selectByTaskAndId("task-1", "job-1")).thenReturn(job);
        when(itemMapper.selectByJobId("job-1")).thenReturn(List.of(failed, success));

        service.retryFailed("task-1", "job-1");

        assertEquals("queued", failed.getStatus());
        assertEquals(0, failed.getAttemptCount());
        assertEquals("success", success.getStatus());
    }

    private ImportQuestionEntity question(String id) {
        ImportQuestionEntity question = new ImportQuestionEntity();
        question.setId(id);
        question.setTaskId("task-1");
        question.setManualMarkdown("题干 " + id);
        return question;
    }

    private StandardizationBatchJobEntity job(String id, String status) {
        StandardizationBatchJobEntity job = new StandardizationBatchJobEntity();
        job.setId(id);
        job.setTaskId("task-1");
        job.setStatus(status);
        return job;
    }

    private StandardizationBatchItemEntity item(String id, String status) {
        StandardizationBatchItemEntity item = new StandardizationBatchItemEntity();
        item.setId(id);
        item.setJobId("job-1");
        item.setQuestionId("q1");
        item.setStatus(status);
        return item;
    }
}
