package com.aigeneration.questionbank;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.aigeneration.questionbank.domain.entity.ImportTaskEntity;
import com.aigeneration.questionbank.domain.entity.ImportTaskSnapshotEntity;
import com.aigeneration.questionbank.domain.mapper.ImportTaskMapper;
import com.aigeneration.questionbank.domain.mapper.ImportTaskSnapshotMapper;
import com.aigeneration.questionbank.domain.service.ImportQuestionSyncService;
import com.aigeneration.questionbank.domain.service.ImportTaskCanonicalizationService;
import com.aigeneration.questionbank.domain.service.PythonWorkerClient;
import com.aigeneration.questionbank.domain.support.JsonSupport;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.InOrder;
import org.springframework.web.server.ResponseStatusException;

class ImportTaskCanonicalizationServiceTest {
    private ImportTaskMapper taskMapper;
    private ImportTaskSnapshotMapper snapshotMapper;
    private ImportQuestionSyncService questionSyncService;
    private PythonWorkerClient worker;
    private JsonSupport json;
    private ImportTaskCanonicalizationService service;
    private ImportTaskEntity task;

    @BeforeEach
    void setUp() {
        taskMapper = mock(ImportTaskMapper.class);
        snapshotMapper = mock(ImportTaskSnapshotMapper.class);
        questionSyncService = mock(ImportQuestionSyncService.class);
        worker = mock(PythonWorkerClient.class);
        json = new JsonSupport(new ObjectMapper().findAndRegisterModules());
        service = new ImportTaskCanonicalizationService(
                taskMapper, snapshotMapper, questionSyncService, worker, json
        );
        task = new ImportTaskEntity();
        task.setId("task-1");
        task.setStatus("待校验");
        task.setQuestionCount(2);
        task.setRawJson(json.write(Map.of(
                "id", "task-1",
                "paperOcrJobId", "ocr-1",
                "questions", List.of()
        )));
        when(taskMapper.selectById("task-1")).thenReturn(task);
        when(questionSyncService.listByTask("task-1")).thenReturn(List.of());
    }

    @Test
    void previewDoesNotWrite() {
        when(worker.postJson(anyString(), any())).thenReturn(Map.of(
                "applyToken", "fresh",
                "questions", List.of()
        ));

        Map<String, Object> result = service.preview("task-1");

        assertEquals("fresh", result.get("applyToken"));
        verifyNoInteractions(snapshotMapper);
        verify(taskMapper, never()).updateById(any());
        verify(questionSyncService, never()).syncQuestions(anyString(), any());
    }

    @Test
    void applyRejectsStalePreviewToken() {
        when(worker.postJson(anyString(), any())).thenReturn(Map.of("applyToken", "fresh", "questions", List.of()));
        assertThrows(ResponseStatusException.class, () -> service.apply("task-1", Map.of("applyToken", "stale")));
        verifyNoInteractions(snapshotMapper);
    }

    @Test
    void applySnapshotsBeforeSync() {
        List<Map<String, Object>> questions = List.of(Map.of("id", "q-1", "number", 1));
        when(worker.postJson(anyString(), any())).thenReturn(Map.of(
                "applyToken", "fresh",
                "questions", questions,
                "canonicalization", Map.of("version", "question-canonicalization.v1"),
                "paperLayout", Map.of("regions", List.of())
        ));

        Map<String, Object> result = service.apply("task-1", Map.of("applyToken", "fresh"));

        InOrder order = inOrder(snapshotMapper, questionSyncService, taskMapper);
        order.verify(snapshotMapper).insert(any(ImportTaskSnapshotEntity.class));
        order.verify(questionSyncService).syncQuestions("task-1", questions);
        order.verify(taskMapper).updateById(task);
        assertEquals(true, result.get("applied"));
        assertEquals(1, task.getQuestionCount());
    }

    @Test
    void applyAllowsPlacementReviewWhenStructureHasNoApplyBlockers() {
        List<Map<String, Object>> questions = List.of(Map.of("id", "q-1", "number", 1));
        when(worker.postJson(anyString(), any())).thenReturn(Map.of(
                "applyToken", "fresh",
                "questions", questions,
                "canonicalization", Map.of("version", "question-canonicalization.v1"),
                "paperLayout", Map.of("regions", List.of()),
                "applyBlockingIssues", List.of(),
                "blockingIssues", List.of(Map.of("type", "image-placement-validation"))
        ));

        Map<String, Object> result = service.apply("task-1", Map.of("applyToken", "fresh"));

        verify(snapshotMapper).insert(any(ImportTaskSnapshotEntity.class));
        verify(questionSyncService).syncQuestions("task-1", questions);
        assertEquals(true, result.get("applied"));
    }

    @Test
    void applyRejectsExplicitStructureApplyBlockers() {
        when(worker.postJson(anyString(), any())).thenReturn(Map.of(
                "applyToken", "fresh",
                "questions", List.of(),
                "applyBlockingIssues", List.of("ambiguous-duplicate-question"),
                "blockingIssues", List.of()
        ));

        assertThrows(
                ResponseStatusException.class,
                () -> service.apply("task-1", Map.of("applyToken", "fresh"))
        );

        verifyNoInteractions(snapshotMapper);
        verify(questionSyncService, never()).syncQuestions(anyString(), any());
    }

    @Test
    void applyFallsBackToLegacyBlockingIssuesWhenApplyFieldIsMissing() {
        when(worker.postJson(anyString(), any())).thenReturn(Map.of(
                "applyToken", "fresh",
                "questions", List.of(),
                "blockingIssues", List.of(Map.of("type", "image-placement-validation"))
        ));

        assertThrows(
                ResponseStatusException.class,
                () -> service.apply("task-1", Map.of("applyToken", "fresh"))
        );

        verifyNoInteractions(snapshotMapper);
        verify(questionSyncService, never()).syncQuestions(anyString(), any());
    }

    @Test
    void rollbackRestoresLatestSnapshot() {
        ImportTaskSnapshotEntity snapshot = new ImportTaskSnapshotEntity();
        snapshot.setId("snapshot-1");
        snapshot.setTaskId("task-1");
        snapshot.setSnapshotJson(json.write(Map.of(
                "taskRaw", Map.of("id", "task-1", "questions", List.of(Map.of("id", "old-q"))),
                "taskStatus", "待校验",
                "questionCount", 1,
                "questions", List.of(Map.of("id", "old-q", "number", 1))
        )));
        when(snapshotMapper.selectLatestByTaskId("task-1")).thenReturn(snapshot);

        Map<String, Object> result = service.rollbackLatest("task-1");

        verify(questionSyncService).syncQuestions(
                "task-1", List.of(Map.of("id", "old-q", "number", 1))
        );
        verify(taskMapper).updateById(task);
        assertEquals(1, task.getQuestionCount());
        assertEquals(true, result.get("rolledBack"));
    }
}
