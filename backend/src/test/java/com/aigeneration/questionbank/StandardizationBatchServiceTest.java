package com.aigeneration.questionbank;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
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
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;

class StandardizationBatchServiceTest {
    private StandardizationBatchJobMapper jobMapper;
    private StandardizationBatchItemMapper itemMapper;
    private ImportQuestionSyncService questionService;
    private ImportTaskCanonicalizationService canonicalization;
    private StandardizationBatchService service;

    @BeforeEach
    void setUp() {
        jobMapper = mock(StandardizationBatchJobMapper.class);
        itemMapper = mock(StandardizationBatchItemMapper.class);
        questionService = mock(ImportQuestionSyncService.class);
        canonicalization = mock(ImportTaskCanonicalizationService.class);
        service = new StandardizationBatchService(
                jobMapper,
                itemMapper,
                questionService,
                canonicalization,
                mock(AiFlowOrchestrationService.class),
                new JsonSupport(new ObjectMapper().findAndRegisterModules())
        );
    }

    @Test
    void createBuildsOneItemPerCanonicalQuestionAndRejectsSecondActiveJob() {
        when(questionService.listByTask("task-1")).thenReturn(List.of(question("q1"), question("q2")));

        Map<String, Object> created = service.create("task-1");

        assertEquals(2, created.get("totalQuestions"));
        verify(jobMapper).insert(any(StandardizationBatchJobEntity.class));
        verify(itemMapper, org.mockito.Mockito.times(2)).insert(any(StandardizationBatchItemEntity.class));

        StandardizationBatchJobEntity active = new StandardizationBatchJobEntity();
        active.setId("active-job");
        active.setTaskId("task-1");
        active.setStatus("running");
        when(jobMapper.selectActiveByTaskId("task-1")).thenReturn(active);
        assertThrows(ResponseStatusException.class, () -> service.create("task-1"));
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
