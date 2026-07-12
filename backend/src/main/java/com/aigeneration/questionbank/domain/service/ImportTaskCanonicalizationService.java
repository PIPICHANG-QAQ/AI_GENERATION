package com.aigeneration.questionbank.domain.service;

import com.aigeneration.questionbank.domain.entity.ImportQuestionEntity;
import com.aigeneration.questionbank.domain.entity.ImportTaskEntity;
import com.aigeneration.questionbank.domain.entity.ImportTaskSnapshotEntity;
import com.aigeneration.questionbank.domain.mapper.ImportTaskMapper;
import com.aigeneration.questionbank.domain.mapper.ImportTaskSnapshotMapper;
import com.aigeneration.questionbank.domain.support.JsonSupport;
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

/** Coordinates read-only canonicalization previews, guarded apply, and rollback. */
@Service
public class ImportTaskCanonicalizationService {
    private static final String WORKER_PREVIEW_PATH = "/worker/import-tasks/canonicalization/preview";

    private final ImportTaskMapper taskMapper;
    private final ImportTaskSnapshotMapper snapshotMapper;
    private final ImportQuestionSyncService questionSyncService;
    private final PythonWorkerClient worker;
    private final JsonSupport json;

    public ImportTaskCanonicalizationService(
            ImportTaskMapper taskMapper,
            ImportTaskSnapshotMapper snapshotMapper,
            ImportQuestionSyncService questionSyncService,
            PythonWorkerClient worker,
            JsonSupport json
    ) {
        this.taskMapper = taskMapper;
        this.snapshotMapper = snapshotMapper;
        this.questionSyncService = questionSyncService;
        this.worker = worker;
        this.json = json;
    }

    /** Ask the worker to rebuild structure without writing task or question tables. */
    public Map<String, Object> preview(String taskId) {
        ImportTaskEntity task = requireTask(taskId);
        return worker.postJson(WORKER_PREVIEW_PATH, Map.of("task", currentTaskPayload(task)));
    }

    /** Apply a fresh preview only when its content token matches the user's preview token. */
    @Transactional
    public Map<String, Object> apply(String taskId, Map<String, Object> payload) {
        ImportTaskEntity task = requireTask(taskId);
        Map<String, Object> fresh = new LinkedHashMap<>(
                worker.postJson(WORKER_PREVIEW_PATH, Map.of("task", currentTaskPayload(task)))
        );
        String submittedToken = text(payload == null ? null : payload.get("applyToken"));
        String freshToken = text(fresh.get("applyToken"));
        if (submittedToken.isBlank() || !submittedToken.equals(freshToken)) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Canonicalization preview is stale; preview again");
        }
        if (fresh.get("blockingIssues") instanceof List<?> issues && !issues.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Canonicalization has unresolved review items");
        }

        List<Object> questions = listValue(fresh.get("questions"));
        insertSnapshot(task);
        questionSyncService.syncQuestions(taskId, questions);

        Map<String, Object> raw = json.readMap(task.getRawJson());
        raw.put("questions", questions);
        raw.put("canonicalization", fresh.get("canonicalization"));
        raw.put("paperLayout", fresh.get("paperLayout"));
        task.setRawJson(json.write(raw));
        task.setQuestionCount(questions.size());
        task.setUpdatedAt(LocalDateTime.now());
        taskMapper.updateById(task);

        fresh.put("applied", true);
        fresh.put("taskId", taskId);
        return fresh;
    }

    /** Restore the most recent pre-apply task and question snapshot. */
    @Transactional
    public Map<String, Object> rollbackLatest(String taskId) {
        ImportTaskEntity task = requireTask(taskId);
        ImportTaskSnapshotEntity snapshot = snapshotMapper.selectLatestByTaskId(taskId);
        if (snapshot == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Canonicalization snapshot not found");
        }
        Map<String, Object> saved = json.readMap(snapshot.getSnapshotJson());
        List<Object> questions = listValue(saved.get("questions"));
        Map<String, Object> taskRaw = mapValue(saved.get("taskRaw"));
        questionSyncService.syncQuestions(taskId, questions);
        task.setRawJson(json.write(taskRaw));
        task.setStatus(text(saved.get("taskStatus")));
        task.setQuestionCount(integer(saved.get("questionCount"), questions.size()));
        task.setUpdatedAt(LocalDateTime.now());
        taskMapper.updateById(task);
        return Map.of(
                "rolledBack", true,
                "taskId", taskId,
                "snapshotId", snapshot.getId(),
                "questionCount", questions.size()
        );
    }

    private ImportTaskEntity requireTask(String taskId) {
        ImportTaskEntity task = taskId == null || taskId.isBlank() ? null : taskMapper.selectById(taskId);
        if (task == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Import task not found");
        }
        return task;
    }

    private Map<String, Object> currentTaskPayload(ImportTaskEntity task) {
        Map<String, Object> raw = json.readMap(task.getRawJson());
        raw.put("id", task.getId());
        if (text(raw.get("paperOcrJobId")).isBlank() && task.getPaperOcrJobId() != null) {
            raw.put("paperOcrJobId", task.getPaperOcrJobId());
        }
        if (text(raw.get("answerOcrJobId")).isBlank() && task.getAnswerOcrJobId() != null) {
            raw.put("answerOcrJobId", task.getAnswerOcrJobId());
        }
        List<Object> questions = new ArrayList<>();
        for (ImportQuestionEntity question : questionSyncService.listByTask(task.getId())) {
            questions.add(questionSyncService.toMap(question));
        }
        raw.put("questions", questions);
        return raw;
    }

    private void insertSnapshot(ImportTaskEntity task) {
        List<Object> questions = new ArrayList<>();
        for (ImportQuestionEntity question : questionSyncService.listByTask(task.getId())) {
            questions.add(questionSyncService.toMap(question));
        }
        Map<String, Object> snapshotPayload = new LinkedHashMap<>();
        snapshotPayload.put("taskRaw", json.readMap(task.getRawJson()));
        snapshotPayload.put("taskStatus", task.getStatus());
        snapshotPayload.put("questionCount", task.getQuestionCount());
        snapshotPayload.put("questions", questions);

        ImportTaskSnapshotEntity snapshot = new ImportTaskSnapshotEntity();
        snapshot.setId("import_task_snapshot_" + UUID.randomUUID());
        snapshot.setTaskId(task.getId());
        snapshot.setSnapshotType("canonicalization");
        snapshot.setVersion(System.currentTimeMillis());
        snapshot.setSnapshotJson(json.write(snapshotPayload));
        snapshot.setCreatedAt(LocalDateTime.now());
        snapshotMapper.insert(snapshot);
    }

    private List<Object> listValue(Object value) {
        return value instanceof List<?> list ? new ArrayList<>(list) : new ArrayList<>();
    }

    private Map<String, Object> mapValue(Object value) {
        Map<String, Object> result = new LinkedHashMap<>();
        if (value instanceof Map<?, ?> map) {
            map.forEach((key, item) -> result.put(String.valueOf(key), item));
        }
        return result;
    }

    private int integer(Object value, int fallback) {
        if (value instanceof Number number) {
            return number.intValue();
        }
        try {
            return Integer.parseInt(text(value));
        } catch (NumberFormatException ignored) {
            return fallback;
        }
    }

    private String text(Object value) {
        return value == null ? "" : String.valueOf(value).trim();
    }
}
