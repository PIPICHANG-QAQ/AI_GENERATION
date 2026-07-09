package com.aigeneration.questionbank;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.aigeneration.questionbank.domain.entity.ImportTaskEntity;
import com.aigeneration.questionbank.domain.mapper.ImportTaskMapper;
import com.aigeneration.questionbank.domain.service.ImportTaskOrchestrationService;
import com.aigeneration.questionbank.domain.service.PythonWorkerClient;
import com.aigeneration.questionbank.domain.support.JsonSupport;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

/**
 * 导入任务编排服务单元测试。
 *
 * <p>覆盖 v13 新增的重新 OCR 扫描入口，确保重复触发被拒绝，正常触发会重投 OCR job
 * 且只切换任务状态，不重建题目内容。</p>
 */
class ImportTaskOrchestrationServiceTest {

    private final ImportTaskMapper mapper = mock(ImportTaskMapper.class);
    private final PythonWorkerClient pythonWorkerClient = mock(PythonWorkerClient.class);
    private final JsonSupport json = new JsonSupport(new ObjectMapper());
    private final ImportTaskOrchestrationService service =
            new ImportTaskOrchestrationService(mapper, pythonWorkerClient, json);

    @Test
    void rescanRejectsTaskAlreadyProcessing() {
        ImportTaskEntity task = task("task-1", "处理中", "running", "");
        when(mapper.selectById("task-1")).thenReturn(task);

        assertThatThrownBy(() -> service.rescan("task-1"))
                .isInstanceOf(ResponseStatusException.class)
                .extracting(ex -> ((ResponseStatusException) ex).getStatusCode())
                .isEqualTo(HttpStatus.CONFLICT);

        verify(mapper, never()).updateById(any());
        verifyNoInteractions(pythonWorkerClient);
    }

    @Test
    void rescanRetriesExistingOcrJobsAndMarksTaskProcessing() {
        ImportTaskEntity task = task("task-2", "待校验", "success", "success");
        when(mapper.selectById("task-2")).thenReturn(task);
        when(pythonWorkerClient.postJson(eq("/worker/ocr/paper-job/retry"), any()))
                .thenReturn(Map.of("jobId", "paper-job", "status", "pending"));
        when(pythonWorkerClient.postJson(eq("/worker/ocr/answer-job/retry"), any()))
                .thenReturn(Map.of("jobId", "answer-job", "status", "pending"));

        Map<String, Object> result = service.rescan("task-2");

        assertThat(result)
                .containsEntry("status", "处理中")
                .containsEntry("paperOcrStatus", "处理中")
                .containsEntry("answerOcrStatus", "处理中")
                .containsEntry("rescanInProgress", true);
        assertThat(task.getStatus()).isEqualTo("处理中");
        assertThat(task.getPaperOcrStatus()).isEqualTo("处理中");
        assertThat(task.getAnswerOcrStatus()).isEqualTo("处理中");
        assertThat(json.readMap(task.getRawJson()))
                .containsEntry("rescanInProgress", true)
                .containsEntry("rescanPreviousStatus", "待校验");
        verify(mapper).updateById(task);
    }

    private ImportTaskEntity task(String id, String status, String paperOcrStatus, String answerOcrStatus) {
        ImportTaskEntity task = new ImportTaskEntity();
        task.setId(id);
        task.setStatus(status);
        task.setPaperOcrStatus(paperOcrStatus);
        task.setAnswerOcrStatus(answerOcrStatus);
        task.setPaperOcrJobId("paper-job");
        task.setAnswerOcrJobId(answerOcrStatus.isBlank() ? "" : "answer-job");
        task.setRawJson(json.write(Map.of(
                "id", id,
                "status", status,
                "questions", java.util.List.of(Map.of("id", "q1", "status", "待校验"))
        )));
        return task;
    }
}
