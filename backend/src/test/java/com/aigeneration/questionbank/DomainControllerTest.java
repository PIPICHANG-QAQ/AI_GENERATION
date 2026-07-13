package com.aigeneration.questionbank;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.aigeneration.questionbank.config.PythonWorkerProperties;
import com.aigeneration.questionbank.domain.entity.ImportQuestionEntity;
import com.aigeneration.questionbank.domain.entity.ImportTaskEntity;
import com.aigeneration.questionbank.domain.entity.StorageFileEntity;
import com.aigeneration.questionbank.domain.service.BankQuestionService;
import com.aigeneration.questionbank.domain.service.ImportTaskBankBridgeService;
import com.aigeneration.questionbank.domain.service.ImportTaskMetadataBridgeService;
import com.aigeneration.questionbank.domain.service.ImportTaskMetadataService;
import com.aigeneration.questionbank.domain.service.ImportQuestionSyncService;
import com.aigeneration.questionbank.domain.service.JavaFileStorageService;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Map.Entry;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.web.server.ResponseStatusException;

/**
 * Java domain 控制器和桥接服务集成测试。
 *
 * <p>该测试类覆盖知识点、题库题、试卷、导入任务同步、题图文件流、AI 编排、导出编排、
 * OCR 重试和回调签名等核心 Java 接管路径，使用 H2 和内置 HttpServer 模拟 worker。</p>
 */
@SpringBootTest(properties = {
        "java-domain.migration.enabled=false",
        "spring.datasource.url=jdbc:h2:mem:domain-controller-test;MODE=MySQL;DATABASE_TO_LOWER=TRUE;CASE_INSENSITIVE_IDENTIFIERS=TRUE",
        "python-worker.api-proxy-enabled=false",
        "java-storage.local-root=target/test-storage-files"
})
@AutoConfigureMockMvc
class DomainControllerTest {

    /**
     * MockMvc 用于调用 Spring MVC 控制器。
     */
    @Autowired
    private MockMvc mockMvc;

    /**
     * JSON 处理器，用于构造请求和解析响应。
     */
    @Autowired
    private ObjectMapper objectMapper;

    /**
     * 题库题服务，用于直接验证桥接入库后的 Java 表状态。
     */
    @Autowired
    private BankQuestionService bankQuestionService;

    /**
     * 导入任务元数据服务，用于构造和读取 Java 侧任务快照。
     */
    @Autowired
    private ImportTaskMetadataService importTaskMetadataService;

    /**
     * 导入题同步服务，用于验证题目和题图快照。
     */
    @Autowired
    private ImportQuestionSyncService importQuestionSyncService;

    /**
     * Java 文件存储服务，用于验证上传文件元数据和预览内容。
     */
    @Autowired
    private JavaFileStorageService javaFileStorageService;

    /**
     * Python worker 配置对象，用于测试期间临时指向内置 HttpServer。
     */
    @Autowired
    private PythonWorkerProperties pythonWorkerProperties;

    /** Canonicalization endpoints are Java-owned and reject unknown tasks before calling the worker. */
    @Test
    void canonicalizationEndpointsRejectUnknownTask() throws Exception {
        String base = "/api/import-tasks/missing-canonical-task/canonicalization";
        mockMvc.perform(post(base + "/preview"))
                .andExpect(status().isNotFound());
        mockMvc.perform(postJson(base + "/apply", Map.of("applyToken", "stale")))
                .andExpect(status().isNotFound());
        mockMvc.perform(post(base + "/rollback"))
                .andExpect(status().isNotFound());
    }

    /**
     * 验证知识点、题库题和试卷 CRUD 在不依赖 Python worker 时可用。
     *
     * @throws Exception 测试请求失败时抛出
     */
    @Test
    void javaDomainCrudWorksWithoutPythonWorker() throws Exception {
        String knowledgePointId = createKnowledgePoint();
        String questionId = createQuestion(knowledgePointId, "二次函数唯一CRUD");
        String paperId = createPaper(questionId, "九年级数学唯一CRUD测试卷");

        MvcResult questionList = mockMvc.perform(get("/api/question-bank/questions").param("keyword", "二次函数唯一CRUD"))
                .andExpect(status().isOk())
                .andReturn();
        org.assertj.core.api.Assertions.assertThat(objectMapper.readTree(questionList.getResponse().getContentAsString())
                        .path("items")
                        .findValuesAsText("id"))
                .contains(questionId);

        mockMvc.perform(get("/api/papers")
                        .param("subject", "数学")
                        .param("grade", "九年级")
                        .param("keyword", "九年级数学唯一CRUD测试卷"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total").value(1))
                .andExpect(jsonPath("$.items[0].id").value(paperId))
                .andExpect(jsonPath("$.items[0].questionCount").value(1));

        mockMvc.perform(putJson("/api/knowledge-points/" + knowledgePointId, Map.of(
                        "name", "二次函数综合",
                        "subject", "数学",
                        "grade", "九年级"
                )))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.name").value("二次函数综合"));

        mockMvc.perform(delete("/api/papers/" + paperId))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.deleted").value(true));
    }

    /**
     * 验证大题小问和试卷小问选择能完整持久化，且小问题目的父题答案解析置空。
     *
     * @throws Exception MockMvc 调用或 JSON 解析失败时抛出
     */
    @Test
    void subQuestionsAndPaperSubSelectionsRoundTrip() throws Exception {
        String knowledgePointId = createKnowledgePoint();
        MvcResult questionResult = mockMvc.perform(postJson("/api/question-bank/questions", Map.ofEntries(
                        entry("title", "含小问大题"),
                        entry("subject", "数学"),
                        entry("grade", "九年级"),
                        entry("type", "composite"),
                        entry("difficulty", "medium"),
                        entry("score", 12),
                        entry("manualMarkdown", "阅读材料并回答下列问题。"),
                        entry("answer", "父题答案不应保存"),
                        entry("analysis", "父题解析不应保存"),
                        entry("knowledgePointIds", List.of(knowledgePointId)),
                        entry("knowledgePoints", List.of("二次函数")),
                        entry("subQuestions", List.of(
                                Map.ofEntries(
                                        entry("id", "sub-1"),
                                        entry("label", "(1)"),
                                        entry("type", "short"),
                                        entry("difficulty", "easy"),
                                        entry("score", 4),
                                        entry("stemMarkdown", "求顶点坐标。"),
                                        entry("answer", "原点"),
                                        entry("analysis", "标准式可直接读出。"),
                                        entry("knowledgePointIds", List.of(knowledgePointId)),
                                        entry("knowledgePoints", List.of("二次函数"))
                                ),
                                Map.ofEntries(
                                        entry("id", "sub-2"),
                                        entry("label", "(2)"),
                                        entry("type", "solution"),
                                        entry("difficulty", "medium"),
                                        entry("score", 8),
                                        entry("stemMarkdown", "说明开口方向。"),
                                        entry("answer", "向上"),
                                        entry("analysis", "二次项系数大于 0。"),
                                        entry("knowledgePointIds", List.of(knowledgePointId)),
                                        entry("knowledgePoints", List.of("二次函数"))
                                )
                        ))
                )))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.answer").value(""))
                .andExpect(jsonPath("$.analysis").value(""))
                .andExpect(jsonPath("$.subQuestions[0].answer").value("原点"))
                .andExpect(jsonPath("$.children[1].analysis").value("二次项系数大于 0。"))
                .andReturn();
        String questionId = readId(questionResult);

        mockMvc.perform(putJson("/api/question-bank/questions/" + questionId, Map.ofEntries(
                        entry("title", "含小问大题更新"),
                        entry("subject", "数学"),
                        entry("grade", "九年级"),
                        entry("type", "composite"),
                        entry("difficulty", "medium"),
                        entry("score", 12),
                        entry("manualMarkdown", "更新后的公共材料。"),
                        entry("answer", "仍不应保存"),
                        entry("analysis", "仍不应保存"),
                        entry("knowledgePointIds", List.of(knowledgePointId)),
                        entry("knowledgePoints", List.of("二次函数")),
                        entry("subQuestions", List.of(
                                Map.ofEntries(
                                        entry("id", "sub-1"),
                                        entry("label", "(1)"),
                                        entry("type", "short"),
                                        entry("difficulty", "easy"),
                                        entry("score", 4),
                                        entry("stemMarkdown", "更新第 1 小问。"),
                                        entry("answer", "A1"),
                                        entry("analysis", "解析 A1")
                                ),
                                Map.ofEntries(
                                        entry("id", "sub-2"),
                                        entry("label", "(2)"),
                                        entry("type", "solution"),
                                        entry("difficulty", "medium"),
                                        entry("score", 8),
                                        entry("stemMarkdown", "更新第 2 小问。"),
                                        entry("answer", "A2"),
                                        entry("analysis", "解析 A2")
                                )
                        ))
                )))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.answer").value(""))
                .andExpect(jsonPath("$.subQuestions[1].answer").value("A2"));

        MvcResult paperResult = mockMvc.perform(postJson("/api/papers", Map.of(
                        "title", "小问组卷测试卷",
                        "subject", "数学",
                        "grade", "九年级",
                        "questionIds", List.of(questionId),
                        "scores", Map.of(questionId, 12),
                        "subSelections", Map.of(questionId, List.of("sub-2")),
                        "header", Map.of("subject", "数学", "grade", "九年级"),
                        "answerDisplay", "teacher"
                )))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.subSelections." + questionId + "[0]").value("sub-2"))
                .andExpect(jsonPath("$.questions[0].subQuestions[1].answer").value("A2"))
                .andReturn();
        String paperId = readId(paperResult);

        mockMvc.perform(putJson("/api/papers/" + paperId, Map.of(
                        "title", "小问组卷测试卷",
                        "subject", "数学",
                        "grade", "九年级",
                        "questionIds", List.of(questionId),
                        "scores", Map.of(questionId, 12),
                        "subSelections", Map.of(questionId, List.of("sub-1")),
                        "header", Map.of("subject", "数学", "grade", "九年级"),
                        "answerDisplay", "teacher"
                )))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.subSelections." + questionId + "[0]").value("sub-1"));
    }

    /**
     * 验证单题入库桥接会把 worker 返回的题库题同步进 Java 题库表。
     *
     * @throws Exception 测试请求或内置 HTTP 服务失败时抛出
     */
    @Test
    void importTaskBankBridgeSyncsPythonBankResultIntoJavaQuestionTable() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        Map<String, Object> bankQuestion = bankQuestionPayload("bank_question_bridge_single", 1);
        server.createContext("/api/import-tasks/task-1/questions/question-1/bank", exchange ->
                writeJson(exchange, Map.of("bankQuestion", bankQuestion, "question", Map.of("id", "question-1")))
        );
        server.start();
        try {
            ImportTaskBankBridgeService bridge = bridgeService(server);
            bridge.bankSingle("task-1", "question-1");

            mockMvc.perform(get("/api/question-bank/questions/bank_question_bridge_single"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.id").value("bank_question_bridge_single"))
                    .andExpect(jsonPath("$.answer").value("A"))
                    .andExpect(jsonPath("$.analysis").value("桥接同步解析"));
        } finally {
            server.stop(0);
        }
    }

    /**
     * 验证批量入库桥接会同步多道 worker 返回题目。
     *
     * @throws Exception 测试请求或内置 HTTP 服务失败时抛出
     */
    @Test
    void importTaskBankBridgeSyncsBulkPythonBankResultsIntoJavaQuestionTable() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        Map<String, Object> first = bankQuestionPayload("bank_question_bridge_bulk_1", 1);
        Map<String, Object> second = bankQuestionPayload("bank_question_bridge_bulk_2", 2);
        server.createContext("/api/import-tasks/task-2/bank", exchange ->
                writeJson(exchange, Map.of("createdCount", 2, "items", List.of(first, second), "duplicates", List.of()))
        );
        server.start();
        try {
            ImportTaskBankBridgeService bridge = bridgeService(server);
            bridge.bankAll("task-2");

            mockMvc.perform(get("/api/question-bank/questions/bank_question_bridge_bulk_1"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.id").value("bank_question_bridge_bulk_1"));
            mockMvc.perform(get("/api/question-bank/questions/bank_question_bridge_bulk_2"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.id").value("bank_question_bridge_bulk_2"));
        } finally {
            server.stop(0);
        }
    }

    /**
     * 验证导入任务列表直接读取 Java 快照，详情桥接会同步任务、OCR job、题目和题图快照。
     *
     * @throws Exception 测试请求或内置 HTTP 服务失败时抛出
     */
    @Test
    void importTaskMetadataBridgeListsJavaSnapshotAndSyncsDetailIntoJavaTable() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        Map<String, Object> task = importTaskPayload("import_task_bridge_1", "待校验", 2);
        Map<String, Object> detail = importTaskPayload("import_task_bridge_1", "部分完成", 3);
        server.createContext("/api/import-tasks/import_task_bridge_1", exchange ->
                writeJson(exchange, detail)
        );
        server.start();
        try {
            ImportTaskMetadataBridgeService bridge = metadataBridgeService(server);
            importTaskMetadataService.syncMap(task);
            Map<String, Object> list = bridge.list();
            org.assertj.core.api.Assertions.assertThat((List<?>) list.get("items"))
                    .anySatisfy(item -> org.assertj.core.api.Assertions.assertThat((Map<?, ?>) item)
                            .extracting(map -> map.get("id"))
                            .isEqualTo("import_task_bridge_1"));
            ImportTaskEntity syncedFromList = importTaskMetadataService.getEntity("import_task_bridge_1");
            org.assertj.core.api.Assertions.assertThat(syncedFromList).isNotNull();
            org.assertj.core.api.Assertions.assertThat(syncedFromList.getStatus()).isEqualTo("待校验");
            org.assertj.core.api.Assertions.assertThat(syncedFromList.getQuestionCount()).isEqualTo(2);
            org.assertj.core.api.Assertions.assertThat(syncedFromList.getPaperOcrJobJson()).contains("\"status\":\"success\"");
            org.assertj.core.api.Assertions.assertThat(syncedFromList.getAnswerOcrJobJson()).contains("\"status\":\"success\"");
            org.assertj.core.api.Assertions.assertThat(syncedFromList.getPaperOcrStatus()).isEqualTo("success");
            org.assertj.core.api.Assertions.assertThat(syncedFromList.getAnswerOcrStatus()).isEqualTo("success");
            org.assertj.core.api.Assertions.assertThat(importQuestionSyncService.listByTask("import_task_bridge_1")).hasSize(2);
            org.assertj.core.api.Assertions.assertThat(importQuestionSyncService.listImages("import_task_bridge_1_question_1")).hasSize(1);

            bridge.get("import_task_bridge_1");
            ImportTaskEntity syncedFromDetail = importTaskMetadataService.getEntity("import_task_bridge_1");
            org.assertj.core.api.Assertions.assertThat(syncedFromDetail.getStatus()).isEqualTo("部分完成");
            org.assertj.core.api.Assertions.assertThat(syncedFromDetail.getQuestionCount()).isEqualTo(3);
            org.assertj.core.api.Assertions.assertThat(importQuestionSyncService.listByTask("import_task_bridge_1")).hasSize(3);

            importTaskMetadataService.syncMap(importTaskPayload("import_task_bridge_1", "待校验", 1));
            org.assertj.core.api.Assertions.assertThat(importQuestionSyncService.listByTask("import_task_bridge_1")).hasSize(1);
            org.assertj.core.api.Assertions.assertThat(importQuestionSyncService.listImages("import_task_bridge_1_question_2")).isEmpty();
        } finally {
            server.stop(0);
        }
    }

    /**
     * 验证 worker 临时任务丢失时，导入任务详情仍能从 Java 快照恢复。
     *
     * @throws Exception 测试请求或内置 HTTP 服务失败时抛出
     */
    @Test
    void importTaskDetailFallsBackToJavaSnapshotWhenWorkerTaskMissing() throws Exception {
        importTaskMetadataService.syncMap(importTaskPayload("import_task_snapshot_fallback", "待校验", 2));
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/import-tasks/import_task_snapshot_fallback", exchange ->
                writeJson(exchange, 404, Map.of("detail", "Import task not found"))
        );
        server.start();
        try {
            ImportTaskMetadataBridgeService bridge = metadataBridgeService(server);
            Map<String, Object> detail = bridge.get("import_task_snapshot_fallback");
            org.assertj.core.api.Assertions.assertThat(detail.get("id")).isEqualTo("import_task_snapshot_fallback");
            org.assertj.core.api.Assertions.assertThat(detail.get("status")).isEqualTo("待校验");
            org.assertj.core.api.Assertions.assertThat(detail.get("snapshotSource")).isEqualTo("java");
            org.assertj.core.api.Assertions.assertThat((List<?>) detail.get("questions")).hasSize(2);
            org.assertj.core.api.Assertions.assertThat(detail.get("paperFile")).isInstanceOf(Map.class);
            org.assertj.core.api.Assertions.assertThat(detail.get("answerFile")).isInstanceOf(Map.class);
        } finally {
            server.stop(0);
        }
    }

    /**
     * 验证导入题保存会先写 worker，并同步到 Java 题目快照，避免历史记录重新进入后回退到旧内容。
     *
     * @throws Exception 测试请求或内置 HTTP 服务失败时抛出
     */
    @Test
    void importQuestionUpdateSyncsWorkerResultIntoJavaSnapshot() throws Exception {
        String taskId = "import_task_question_update";
        String questionId = taskId + "_question_1";
        importTaskMetadataService.syncMap(importTaskPayload(taskId, "待校验", 1));

        Map<String, Object> updatedTask = new LinkedHashMap<>(importTaskPayload(taskId, "部分完成", 1));
        Map<String, Object> updatedQuestion = new LinkedHashMap<>(((List<Map<String, Object>>) updatedTask.get("questions")).get(0));
        updatedQuestion.put("status", "已校验");
        updatedQuestion.put("type", "choice");
        updatedQuestion.put("stemMarkdown", "编辑后的题干");
        updatedQuestion.put("manualMarkdown", "编辑后的题干");
        updatedQuestion.put("answer", "C");
        updatedQuestion.put("analysis", "编辑后的解析");
        updatedQuestion.put("options", List.of(
                Map.of("label", "A", "content", "甲"),
                Map.of("label", "B", "content", "乙"),
                Map.of("label", "C", "content", "丙")
        ));
        updatedTask.put("questions", List.of(updatedQuestion));
        updatedTask.put("updatedAt", "2026-06-29T10:05:00Z");

        AtomicReference<String> requestBody = new AtomicReference<>("");
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/import-tasks/" + taskId + "/questions/" + questionId, exchange -> {
            org.assertj.core.api.Assertions.assertThat(exchange.getRequestMethod()).isEqualTo("PUT");
            requestBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            writeJson(exchange, Map.of("question", updatedQuestion, "task", updatedTask));
        });
        server.start();
        try {
            ImportTaskMetadataBridgeService bridge = metadataBridgeService(server);
            Map<String, Object> response = bridge.updateQuestion(taskId, questionId, Map.of(
                    "manualMarkdown", "编辑后的题干",
                    "status", "已校验",
                    "answer", "C",
                    "analysis", "编辑后的解析"
            ));

            org.assertj.core.api.Assertions.assertThat(requestBody.get()).contains("编辑后的题干");
            Map<?, ?> responseQuestion = (Map<?, ?>) response.get("question");
            org.assertj.core.api.Assertions.assertThat(responseQuestion.get("manualMarkdown")).isEqualTo("编辑后的题干");
            org.assertj.core.api.Assertions.assertThat(responseQuestion.get("status")).isEqualTo("已校验");
            org.assertj.core.api.Assertions.assertThat(importQuestionSyncService.getQuestion(questionId).getManualMarkdown())
                    .isEqualTo("编辑后的题干");
            org.assertj.core.api.Assertions.assertThat(importQuestionSyncService.getQuestion(questionId).getStatus())
                    .isEqualTo("已校验");
            org.assertj.core.api.Assertions.assertThat(importQuestionSyncService.listByTask(taskId)).hasSize(1);
        } finally {
            server.stop(0);
        }
    }

    /**
     * 验证 worker 任务缺失但 OCR job 可恢复时，会优先返回恢复后的任务并同步 Java 表。
     *
     * @throws Exception 测试请求或内置 HTTP 服务失败时抛出
     */
    @Test
    void importTaskDetailRecoversFromOcrSnapshotWhenWorkerTaskMissing() throws Exception {
        importTaskMetadataService.syncMap(importTaskPayload("import_task_ocr_recover", "处理中", 0));
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/import-tasks/import_task_ocr_recover", exchange ->
                writeJson(exchange, 404, Map.of("detail", "Import task not found"))
        );
        server.createContext("/worker/import-tasks/recover", exchange ->
                writeJson(exchange, importTaskPayload("import_task_ocr_recover", "待校验", 3))
        );
        server.start();
        try {
            ImportTaskMetadataBridgeService bridge = metadataBridgeService(server);
            Map<String, Object> detail = bridge.get("import_task_ocr_recover");
            org.assertj.core.api.Assertions.assertThat(detail.get("id")).isEqualTo("import_task_ocr_recover");
            org.assertj.core.api.Assertions.assertThat(detail.get("snapshotSource")).isEqualTo("worker-recovered");
            org.assertj.core.api.Assertions.assertThat((List<?>) detail.get("questions")).hasSize(3);
            ImportTaskEntity recovered = importTaskMetadataService.getEntity("import_task_ocr_recover");
            org.assertj.core.api.Assertions.assertThat(recovered.getStatus()).isEqualTo("待校验");
            org.assertj.core.api.Assertions.assertThat(recovered.getQuestionCount()).isEqualTo(3);
            org.assertj.core.api.Assertions.assertThat(importQuestionSyncService.listByTask("import_task_ocr_recover")).hasSize(3);
        } finally {
            server.stop(0);
        }
    }

    /**
     * 验证创建导入任务时 multipart 会转发给 worker，并且上传原文件会写入 Java 存储。
     *
     * @throws Exception 测试请求或内置 HTTP 服务失败时抛出
     */
    @Test
    void importTaskCreateBridgeForwardsMultipartAndSyncsMetadata() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        AtomicReference<String> requestBody = new AtomicReference<>("");
        Map<String, Object> created = importTaskPayload("import_task_create_bridge_1", "处理中", 0);
        server.createContext("/api/import-tasks", exchange -> {
            org.assertj.core.api.Assertions.assertThat(exchange.getRequestMethod()).isEqualTo("POST");
            requestBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            writeJson(exchange, created);
        });
        server.start();
        try {
            ImportTaskMetadataBridgeService bridge = metadataBridgeService(server);
            bridge.create(
                    "高中",
                    "数学",
                    "高一",
                    "本地",
                    "2026",
                    "Java 创建导入任务",
                    new MockMultipartFile("paperFile", "paper.md", "text/markdown", "# 试卷".getBytes(StandardCharsets.UTF_8)),
                    new MockMultipartFile("answerFile", "answer.md", "text/markdown", "# 答案".getBytes(StandardCharsets.UTF_8))
            );

            org.assertj.core.api.Assertions.assertThat(requestBody.get())
                    .contains("name=\"stage\"")
                    .contains("高中")
                    .contains("name=\"paperFile\"")
                    .contains("filename=\"paper.md\"")
                    .contains("name=\"answerFile\"")
                    .contains("filename=\"answer.md\"");
            ImportTaskEntity synced = importTaskMetadataService.getEntity("import_task_create_bridge_1");
            org.assertj.core.api.Assertions.assertThat(synced).isNotNull();
            org.assertj.core.api.Assertions.assertThat(synced.getStatus()).isEqualTo("处理中");
            org.assertj.core.api.Assertions.assertThat(synced.getPaperOcrJobId()).isEqualTo("ocr_paper_bridge");
            org.assertj.core.api.Assertions.assertThat(synced.getPaperOcrJobJson()).contains("\"jobId\":\"ocr_paper_bridge\"");
            org.assertj.core.api.Assertions.assertThat(synced.getPaperOcrStatus()).isEqualTo("success");
            List<StorageFileEntity> storedFiles = javaFileStorageService.listByBusiness(
                    JavaFileStorageService.BUSINESS_IMPORT_TASK_UPLOAD,
                    "import_task_create_bridge_1"
            );
            org.assertj.core.api.Assertions.assertThat(storedFiles).hasSize(2);
            org.assertj.core.api.Assertions.assertThat(storedFiles)
                    .extracting(StorageFileEntity::getFieldName)
                    .containsExactly("answerFile", "paperFile");
            org.assertj.core.api.Assertions.assertThat(storedFiles)
                    .allSatisfy(file -> org.assertj.core.api.Assertions.assertThat(file.getStorageType()).isEqualTo("LOCAL"));

            MvcResult source = mockMvc.perform(get("/api/import-tasks/import_task_create_bridge_1/source/paper"))
                    .andExpect(status().isOk())
                    .andReturn();
            org.assertj.core.api.Assertions.assertThat(source.getResponse().getContentAsByteArray())
                    .isEqualTo("# 试卷".getBytes(StandardCharsets.UTF_8));
            org.assertj.core.api.Assertions.assertThat(source.getResponse().getHeader(HttpHeaders.CONTENT_DISPOSITION))
                    .contains("inline")
                    .contains("paper.md");
        } finally {
            server.stop(0);
        }
    }

    /**
     * 验证中文原始文件名不会直接进入本地存储路径，避免非 UTF-8 容器环境下路径编码失败。
     *
     * @throws Exception 测试请求或内置 HTTP 服务失败时抛出
     */
    @Test
    void importTaskCreateStoresChineseFilenameWithAsciiStoragePath() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        Map<String, Object> created = importTaskPayload("import_task_chinese_filename", "处理中", 0);
        server.createContext("/api/import-tasks", exchange -> writeJson(exchange, created));
        server.start();
        try {
            ImportTaskMetadataBridgeService bridge = metadataBridgeService(server);
            bridge.create(
                    "高中",
                    "数学",
                    "高一",
                    "本地",
                    "2026",
                    "中文文件名导入任务",
                    new MockMultipartFile("paperFile", "安徽省马鞍山市试卷(1).md", "text/markdown", "# 试卷".getBytes(StandardCharsets.UTF_8)),
                    null
            );

            StorageFileEntity storedFile = javaFileStorageService.findImportUpload("import_task_chinese_filename", "paperFile");
            org.assertj.core.api.Assertions.assertThat(storedFile).isNotNull();
            org.assertj.core.api.Assertions.assertThat(storedFile.getOriginalFilename()).isEqualTo("安徽省马鞍山市试卷(1).md");
            org.assertj.core.api.Assertions.assertThat(storedFile.getLocalPath())
                    .endsWith(storedFile.getId() + ".md")
                    .doesNotContain("安徽省马鞍山市");

            MvcResult source = mockMvc.perform(get("/api/import-tasks/import_task_chinese_filename/source/paper"))
                    .andExpect(status().isOk())
                    .andReturn();
            org.assertj.core.api.Assertions.assertThat(source.getResponse().getContentAsByteArray())
                    .isEqualTo("# 试卷".getBytes(StandardCharsets.UTF_8));
        } finally {
            server.stop(0);
        }
    }

    /**
     * 验证 OCR provider 不可用时，Java 会在保存文件和创建 worker 任务前失败。
     *
     * @throws Exception 测试请求或内置 HTTP 服务失败时抛出
     */
    @Test
    void importTaskCreateFailsFastWhenOcrProviderUnavailable() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        AtomicReference<Boolean> createCalled = new AtomicReference<>(false);
        server.createContext("/worker/ocr-flow", exchange -> writeJson(exchange, Map.of(
                "providerStatus", Map.of(
                        "installed", false,
                        "error", "No valid MinerU command found."
                )
        )));
        server.createContext("/api/import-tasks", exchange -> {
            createCalled.set(true);
            writeJson(exchange, importTaskPayload("import_task_should_not_be_created", "处理中", 0));
        });
        server.start();
        try {
            ImportTaskMetadataBridgeService bridge = metadataBridgeService(server);

            org.assertj.core.api.Assertions.assertThatThrownBy(() -> bridge.create(
                            "高中",
                            "数学",
                            "高一",
                            "本地",
                            "2026",
                            "缺少 MinerU 的导入任务",
                            new MockMultipartFile("paperFile", "paper.pdf", "application/pdf", "%PDF".getBytes(StandardCharsets.UTF_8)),
                            null
                    ))
                    .isInstanceOf(ResponseStatusException.class)
                    .satisfies(error -> {
                        ResponseStatusException ex = (ResponseStatusException) error;
                        org.assertj.core.api.Assertions.assertThat(ex.getStatusCode().value()).isEqualTo(503);
                        org.assertj.core.api.Assertions.assertThat(ex.getReason())
                                .contains("OCR provider is unavailable")
                                .contains("--with-mineru");
                    });

            org.assertj.core.api.Assertions.assertThat(createCalled.get()).isFalse();
            org.assertj.core.api.Assertions.assertThat(importTaskMetadataService.getEntity("import_task_should_not_be_created")).isNull();
        } finally {
            server.stop(0);
        }
    }

    /**
     * 验证历史任务缺少 Java 文件记录时会回退到 Python worker source 接口。
     *
     * @throws Exception 测试请求或内置 HTTP 服务失败时抛出
     */
    @Test
    void importTaskSourceFallsBackToPythonWhenJavaFileMissing() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/import-tasks/legacy_task/source/paper", exchange -> {
            byte[] body = "legacy source".getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add(HttpHeaders.CONTENT_TYPE, "text/plain");
            exchange.getResponseHeaders().add(HttpHeaders.CONTENT_DISPOSITION, "inline; filename=\"legacy.txt\"");
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();
        try {
            ImportTaskMetadataBridgeService bridge = metadataBridgeService(server);
            ResponseEntity<?> response = bridge.source("legacy_task", "paper");
            org.assertj.core.api.Assertions.assertThat(response.getStatusCode().value()).isEqualTo(200);
            org.assertj.core.api.Assertions.assertThat((byte[]) response.getBody())
                    .isEqualTo("legacy source".getBytes(StandardCharsets.UTF_8));
            org.assertj.core.api.Assertions.assertThat(response.getHeaders().getFirst(HttpHeaders.CONTENT_DISPOSITION))
                    .isEqualTo("inline; filename=\"legacy.txt\"");
        } finally {
            server.stop(0);
        }
    }

    /**
     * 验证 question-processing 能力可以从 Java 快照导出标准题目包。
     *
     * @throws Exception 测试请求失败时抛出
     */
    @Test
    void questionProcessingCapabilityExportsStandardPackageFromJavaSnapshot() throws Exception {
        importTaskMetadataService.syncMap(importTaskPayload("capability_job_1", "待校验", 2, "能力服务任务"));

        mockMvc.perform(get("/api/capabilities/question-processing"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value("question-processing"))
                .andExpect(jsonPath("$.packageVersion").value("question-package.v1"));

        mockMvc.perform(get("/api/capabilities/question-processing/jobs/capability_job_1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.jobId").value("capability_job_1"))
                .andExpect(jsonPath("$.title").value("能力服务任务"))
                .andExpect(jsonPath("$.processingStatus").value("WAITING_REVIEW"))
                .andExpect(jsonPath("$.sourceFiles[0].kind").value("paper"))
                .andExpect(jsonPath("$.sourceFiles[0].previewUrl").value("/api/import-tasks/capability_job_1/source/paper"));

        mockMvc.perform(get("/api/capabilities/question-processing/jobs/capability_job_1/question-package"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.capability").value("question-processing"))
                .andExpect(jsonPath("$.job.jobId").value("capability_job_1"))
                .andExpect(jsonPath("$.questions[0].questionId").value("capability_job_1_question_1"))
                .andExpect(jsonPath("$.questions[0].stemMarkdown").value("导入题 1"))
                .andExpect(jsonPath("$.questions[0].options.length()").value(0))
                .andExpect(jsonPath("$.questions[0].children.length()").value(0))
                .andExpect(jsonPath("$.questions[0].mathValidation.status").value("OK"))
                .andExpect(jsonPath("$.questions[0].images[0].url").value("/api/image-1.png"))
                .andExpect(jsonPath("$.questions[0].sourceEvidence.processingJobId").value("capability_job_1"));
    }

    /**
     * 验证题图归属经过导入快照、题库快照和标准题目包后保持不变。
     *
     * @throws Exception 测试请求失败时抛出
     */
    @Test
    void imagePlacementsRoundTripThroughImportBankAndQuestionPackage() throws Exception {
        List<Map<String, Object>> placements = List.of(Map.ofEntries(
                entry("placementId", "placement-a"),
                entry("imageId", "images/a.png"),
                entry("target", Map.of("kind", "option", "optionLabel", "A")),
                entry("order", 0),
                entry("sourceEvidence", Map.of("markdownStart", 42, "markdownEnd", 58, "pageIndex", 0)),
                entry("inference", Map.of("method", "explicit-offset", "confidence", 0.99, "reasons", List.of("inside-option-span"))),
                entry("reviewStatus", "auto")
        ));
        Map<String, Object> payload = new LinkedHashMap<>(importTaskPayload("placement_job_1", "待校验", 1, "题图归属任务"));
        List<Map<String, Object>> questions = new ArrayList<>((List<Map<String, Object>>) payload.get("questions"));
        questions.set(0, new LinkedHashMap<>(questions.get(0)));
        questions.get(0).put("imagePlacements", placements);
        payload.put("questions", questions);
        importTaskMetadataService.syncMap(payload);

        Map<String, Object> imported = importQuestionSyncService.listByTask("placement_job_1").stream()
                .map(importQuestionSyncService::toMap)
                .findFirst()
                .orElseThrow();
        org.assertj.core.api.Assertions.assertThat(imported.get("imagePlacements")).isEqualTo(placements);

        Map<String, Object> bankPayload = new LinkedHashMap<>(questions.get(0));
        bankPayload.put("id", "placement_bank_1");
        Map<String, Object> banked = bankQuestionService.upsertFromPayload(bankPayload);
        org.assertj.core.api.Assertions.assertThat(banked.get("imagePlacements")).isEqualTo(placements);

        mockMvc.perform(get("/api/capabilities/question-processing/jobs/placement_job_1/question-package"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.questions[0].imagePlacements[0].placementId").value("placement-a"))
                .andExpect(jsonPath("$.questions[0].imagePlacements[0].target.optionLabel").value("A"));
    }

    /**
     * 验证导入任务同步会提取 OCR 失败原因，并区分可重试和最终失败状态。
     */
    @Test
    void importTaskMetadataSyncExtractsOcrFailureReason() {
        Map<String, Object> retryablePayload = new LinkedHashMap<>(importTaskPayload(
                "import_task_failed_ocr",
                "处理中",
                0,
                "失败 OCR 任务",
                ocrJobPayload("ocr_paper_failed", "paper.md", "failed", "MinerU 解析失败"),
                ocrJobPayload("ocr_answer_failed", "answer.md", "failed", "答案文件损坏")
        ));
        retryablePayload.put("retryable", true);
        importTaskMetadataService.syncMap(retryablePayload);

        ImportTaskEntity failed = importTaskMetadataService.getEntity("import_task_failed_ocr");
        org.assertj.core.api.Assertions.assertThat(failed.getStatus()).isEqualTo("可重试");
        org.assertj.core.api.Assertions.assertThat(failed.getPaperOcrStatus()).isEqualTo("failed");
        org.assertj.core.api.Assertions.assertThat(failed.getAnswerOcrStatus()).isEqualTo("failed");
        org.assertj.core.api.Assertions.assertThat(failed.getFailureReason())
                .contains("试卷 OCR: MinerU 解析失败")
                .contains("答案 OCR: 答案文件损坏");

        Map<String, Object> exhaustedPayload = new LinkedHashMap<>(retryablePayload);
        exhaustedPayload.put("id", "import_task_failed_final");
        exhaustedPayload.put("retryable", false);
        importTaskMetadataService.syncMap(exhaustedPayload);
        org.assertj.core.api.Assertions.assertThat(importTaskMetadataService.getEntity("import_task_failed_final").getStatus())
                .isEqualTo("失败");
    }

    /**
     * 验证导入任务详情桥接返回 Java 推导状态，而不是直接暴露 worker 原始状态。
     *
     * @throws Exception 测试请求或内置 HTTP 服务失败时抛出
     */
    @Test
    void importTaskBridgeReturnsJavaDerivedStatus() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        Map<String, Object> failed = new LinkedHashMap<>(importTaskPayload(
                "import_task_bridge_failed",
                "处理中",
                0,
                "桥接失败任务",
                ocrJobPayload("ocr_paper_failed_bridge", "paper.md", "failed", "MinerU 解析失败"),
                ocrJobPayload("ocr_answer_ok_bridge", "answer.md", "success", "")
        ));
        failed.put("retryable", true);
        server.createContext("/api/import-tasks/import_task_bridge_failed", exchange -> writeJson(exchange, failed));
        server.start();
        try {
            ImportTaskMetadataBridgeService bridge = metadataBridgeService(server);
            Map<String, Object> response = bridge.get("import_task_bridge_failed");
            org.assertj.core.api.Assertions.assertThat(response.get("status")).isEqualTo("可重试");
            org.assertj.core.api.Assertions.assertThat(response.get("paperOcrStatus")).isEqualTo("failed");
            org.assertj.core.api.Assertions.assertThat(response.get("failureReason")).asString().contains("试卷 OCR: MinerU 解析失败");
        } finally {
            server.stop(0);
        }
    }

    /**
     * 验证导入任务更新、删除和批量删除会同步清理 Java 元数据。
     *
     * @throws Exception 测试请求或内置 HTTP 服务失败时抛出
     */
    @Test
    void importTaskManageBridgeUpdatesAndDeletesJavaMetadata() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        AtomicReference<String> updateBody = new AtomicReference<>("");
        AtomicReference<String> batchDeleteBody = new AtomicReference<>("");
        server.createContext("/api/import-tasks/import_task_manage_1", exchange -> {
            if ("PUT".equals(exchange.getRequestMethod())) {
                updateBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
                writeJson(exchange, importTaskPayload("import_task_manage_1", "待校验", 1, "重命名任务"));
                return;
            }
            if ("DELETE".equals(exchange.getRequestMethod())) {
                writeJson(exchange, Map.of("deleted", true));
                return;
            }
            writeJson(exchange, Map.of("error", "unsupported"));
        });
        server.createContext("/api/import-tasks/batch-delete", exchange -> {
            org.assertj.core.api.Assertions.assertThat(exchange.getRequestMethod()).isEqualTo("POST");
            batchDeleteBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            writeJson(exchange, Map.of(
                    "deleted", true,
                    "deletedCount", 2,
                    "deletedIds", List.of("import_task_manage_2", "import_task_manage_3")
            ));
        });
        server.start();
        try {
            ImportTaskMetadataBridgeService bridge = metadataBridgeService(server);
            importTaskMetadataService.syncMap(importTaskPayload("import_task_manage_1", "处理中", 1, "原任务名"));
            importTaskMetadataService.syncMap(importTaskPayload("import_task_manage_2", "待校验", 0, "批量删除任务 2"));
            importTaskMetadataService.syncMap(importTaskPayload("import_task_manage_3", "待校验", 0, "批量删除任务 3"));

            bridge.update("import_task_manage_1", Map.of("title", "重命名任务"));
            org.assertj.core.api.Assertions.assertThat(updateBody.get()).contains("\"title\":\"重命名任务\"");
            ImportTaskEntity updated = importTaskMetadataService.getEntity("import_task_manage_1");
            org.assertj.core.api.Assertions.assertThat(updated.getTitle()).isEqualTo("重命名任务");

            bridge.delete("import_task_manage_1");
            org.assertj.core.api.Assertions.assertThat(importTaskMetadataService.getEntity("import_task_manage_1")).isNull();

            bridge.batchDelete(Map.of("taskIds", List.of("import_task_manage_2", "import_task_manage_3")));
            org.assertj.core.api.Assertions.assertThat(batchDeleteBody.get())
                    .contains("import_task_manage_2")
                    .contains("import_task_manage_3");
            org.assertj.core.api.Assertions.assertThat(importTaskMetadataService.getEntity("import_task_manage_2")).isNull();
            org.assertj.core.api.Assertions.assertThat(importTaskMetadataService.getEntity("import_task_manage_3")).isNull();
        } finally {
            server.stop(0);
        }
    }

    /**
     * 验证题图上传会写入 Java 文件存储，并且可以从 Java 文件流预览。
     *
     * @throws Exception 测试请求失败时抛出
     */
    @Test
    void questionImagesAreStoredAndServedByJavaFileFlow() throws Exception {
        importTaskMetadataService.syncMap(importTaskPayload("image_task_1", "待校验", 1, "题图任务"));
        MockMultipartFile image = new MockMultipartFile("files", "figure.png", "image/png", "png-bytes".getBytes(StandardCharsets.UTF_8));

        MvcResult upload = mockMvc.perform(multipart("/api/import-tasks/image_task_1/questions/image_task_1_question_1/images").file(image))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.uploaded[0].storageFileId").exists())
                .andExpect(jsonPath("$.images[1].source").value("Java 文件存储"))
                .andReturn();
        String fileId = objectMapper.readTree(upload.getResponse().getContentAsString()).get("uploaded").get(0).get("storageFileId").asText();

        mockMvc.perform(get("/api/import-tasks/image_task_1/image-library"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items.length()").value(2));

        MvcResult imageResponse = mockMvc.perform(get("/api/import-tasks/image_task_1/questions/image_task_1_question_1/images/" + fileId))
                .andExpect(status().isOk())
                .andReturn();
        org.assertj.core.api.Assertions.assertThat(imageResponse.getResponse().getContentAsByteArray())
                .isEqualTo("png-bytes".getBytes(StandardCharsets.UTF_8));
    }

    /**
     * 验证导入题可以从任务题图库选择已有题图。
     *
     * @throws Exception 测试请求失败时抛出
     */
    @Test
    void importQuestionCanSelectImagesFromTaskImageLibrary() throws Exception {
        importTaskMetadataService.syncMap(importTaskPayload("image_select_task_1", "待校验", 2, "题图库选择任务"));

        MvcResult library = mockMvc.perform(get("/api/import-tasks/image_select_task_1/image-library"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items.length()").value(2))
                .andReturn();
        String sourceImageId = objectMapper.readTree(library.getResponse().getContentAsString())
                .get("items")
                .get(0)
                .get("imageId")
                .asText();

        mockMvc.perform(postJson(
                        "/api/import-tasks/image_select_task_1/questions/image_select_task_1_question_2/images/select",
                        Map.of("imageIds", List.of(sourceImageId))
                ))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.images.length()").value(2))
                .andExpect(jsonPath("$.images[1].source").value("任务题图库"));
    }

    /**
     * 验证小问题图会进入任务题图库索引，但不会被提升成父题图片。
     *
     * @throws Exception 测试请求失败时抛出
     */
    @Test
    void nestedSubQuestionImagesAreIndexedWithoutBecomingParentImages() throws Exception {
        String taskId = "nested_image_task_1";
        String questionId = taskId + "_question_37";
        Map<String, Object> child = new LinkedHashMap<>();
        child.put("id", questionId + "_sub_3");
        child.put("label", "(3)");
        child.put("stemMarkdown", "A 和 B 的重力。\n\n![](图1)\n\n![](图2)");
        child.put("manualMarkdown", "A 和 B 的重力。\n\n![](图1)\n\n![](图2)");
        child.put("images", List.of(
                Map.of("name", "q37-a.png", "path", "images/q37-a.png", "url", "/q37-a.png", "label", "图1"),
                Map.of("name", "q37-b.png", "path", "images/q37-b.png", "url", "/q37-b.png", "label", "图2")
        ));

        Map<String, Object> question = new LinkedHashMap<>();
        question.put("id", questionId);
        question.put("number", 37);
        question.put("status", "待校验");
        question.put("type", "solution");
        question.put("stemMarkdown", "某物理兴趣小组设计了如图所示的装置。求：");
        question.put("images", List.of());
        question.put("subQuestions", List.of(child));

        Map<String, Object> task = new LinkedHashMap<>(importTaskPayload(taskId, "待校验", 1, "嵌套小问题图任务"));
        task.put("questions", List.of(question));
        importTaskMetadataService.syncMap(task);

        mockMvc.perform(get("/api/import-tasks/" + taskId + "/image-library"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items.length()").value(2))
                .andExpect(jsonPath("$.items[0].questionId").value(questionId))
                .andExpect(jsonPath("$.items[0].ownerKind").value("subQuestion"))
                .andExpect(jsonPath("$.items[0].ownerId").value(questionId + "_sub_3"))
                .andExpect(jsonPath("$.items[0].ownerLabel").value("(3)"));

        org.assertj.core.api.Assertions.assertThat(importQuestionSyncService.listImages(questionId)).isEmpty();
    }

    /**
     * 验证 AI 回写不能覆盖已有小问题图及其归属。
     */
    @Test
    void aiStandardizePreservesExistingSubQuestionImages() throws Exception {
        String taskId = "nested_image_ai_task_1";
        String questionId = taskId + "_question_37";
        String childId = questionId + "_sub_3";
        Map<String, Object> child = new LinkedHashMap<>();
        child.put("id", childId);
        child.put("label", "(3)");
        child.put("stemMarkdown", "A 和 B 的重力。\n\n![](图1)\n\n![](图2)");
        child.put("manualMarkdown", "A 和 B 的重力。\n\n![](图1)\n\n![](图2)");
        child.put("images", List.of(
                Map.of("name", "q37-a.png", "path", "images/q37-a.png", "url", "/q37-a.png", "label", "图1"),
                Map.of("name", "q37-b.png", "path", "images/q37-b.png", "url", "/q37-b.png", "label", "图2")
        ));
        child.put("imagePlacements", List.of(
                Map.of("imageKey", "images/q37-a.png", "target", "stem"),
                Map.of("imageKey", "images/q37-b.png", "target", "stem")
        ));

        Map<String, Object> question = new LinkedHashMap<>();
        question.put("id", questionId);
        question.put("number", 37);
        question.put("status", "待校验");
        question.put("type", "solution");
        question.put("stemMarkdown", "某物理兴趣小组设计了装置。求：");
        question.put("images", List.of());
        question.put("subQuestions", List.of(child));
        Map<String, Object> task = new LinkedHashMap<>(importTaskPayload(taskId, "待校验", 1, "AI 小问题图守恒任务"));
        task.put("questions", List.of(question));
        importTaskMetadataService.syncMap(task);

        ImportQuestionEntity updated = importQuestionSyncService.updateStandardizedResult(
                taskId,
                questionId,
                "某物理兴趣小组设计了装置，求：",
                "",
                "",
                Map.of("subQuestions", List.of(Map.of(
                        "id", childId,
                        "label", "(3)",
                        "stemMarkdown", "A 和 B 的重力。",
                        "images", List.of(Map.of("name", "wrong.png", "path", "images/wrong.png", "url", "/wrong.png"))
                )))
        );

        JsonNode updatedJson = objectMapper.valueToTree(importQuestionSyncService.toMap(updated));
        JsonNode updatedChild = updatedJson.path("subQuestions").get(0);
        org.assertj.core.api.Assertions.assertThat(updatedChild.path("images").findValuesAsText("path"))
                .containsExactly("images/q37-a.png", "images/q37-b.png");
        org.assertj.core.api.Assertions.assertThat(updatedChild.path("imagePlacements").size()).isEqualTo(2);

        mockMvc.perform(get("/api/import-tasks/" + taskId + "/image-library"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items.length()").value(2))
                .andExpect(jsonPath("$.items[0].ownerKind").value("subQuestion"));
    }

    /**
     * 验证 AI 解析由 Java 编排并回写答案，同时题图会以 data URL 传给 worker 且 job 记录脱敏。
     *
     * @throws Exception 测试请求或内置 HTTP 服务失败时抛出
     */
    @Test
    void aiAnalysisIsOrchestratedByJavaAndWritesAnswerBack() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        AtomicReference<String> requestBody = new AtomicReference<>("");
        server.createContext("/worker/ai/analysis", exchange -> {
            requestBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            writeJson(exchange, Map.of("analysis", "AI 解析草稿", "answer", "B", "suggestedAnswer", "B", "metadata", Map.of("source", "test")));
        });
        server.start();
        String oldBaseUrl = pythonWorkerProperties.getBaseUrl();
        boolean oldProxyEnabled = pythonWorkerProperties.isApiProxyEnabled();
        try {
            pythonWorkerProperties.setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
            pythonWorkerProperties.setApiProxyEnabled(true);
            String questionId = createQuestion(createKnowledgePoint());
            byte[] figureBytes = java.util.Base64.getDecoder().decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
            );
            mockMvc.perform(multipart("/api/question-bank/questions/" + questionId + "/images")
                            .file(new MockMultipartFile("files", "analysis-figure.png", "image/png", figureBytes)))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.uploaded[0].storageFileId").exists());

            mockMvc.perform(postJson("/api/question-bank/questions/" + questionId + "/analysis", Map.of(
                            "manualMarkdown", "题干",
                            "answer", "",
                            "type", "choice",
                            "knowledgePoints", List.of("二次函数")
                    )))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.answer").value("B"))
                    .andExpect(jsonPath("$.question.answer").value("B"))
                    .andExpect(jsonPath("$.question.analysis").value("AI 解析草稿"));
            JsonNode workerRequest = objectMapper.readTree(requestBody.get());
            org.assertj.core.api.Assertions.assertThat(workerRequest.path("images").get(0).path("imageDataUrl").asText())
                    .startsWith("data:image/png;base64,")
                    .endsWith(java.util.Base64.getEncoder().encodeToString(figureBytes));
            org.assertj.core.api.Assertions.assertThat(workerRequest.path("images").get(0).path("aiImageIncluded").asBoolean())
                    .isTrue();

            mockMvc.perform(get("/api/capabilities/ai-flow/jobs").param("targetId", questionId))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.total").value(1))
                    .andExpect(jsonPath("$.items[0].status").value("success"))
                    .andExpect(jsonPath("$.items[0].request.images[0].imageDataUrl").value("[redacted inline image data]"));
        } finally {
            pythonWorkerProperties.setBaseUrl(oldBaseUrl);
            pythonWorkerProperties.setApiProxyEnabled(oldProxyEnabled);
            server.stop(0);
        }
    }

    /**
     * 验证 AI 标准化在显式请求写回时会回写 Markdown、答案和解析到导入题。
     *
     * @throws Exception 测试请求或内置 HTTP 服务失败时抛出
     */
    @Test
    void aiStandardizeWritesMarkdownAnswerAndAnalysisBack() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/worker/ai/standardize", exchange ->
                writeJson(exchange, Map.of(
                        "markdown", "清理后的题干",
                        "answer", "C",
                        "analysis", "从题干中提取的解析",
                        "standardizer", Map.of("source", "test")
                ))
        );
        server.start();
        String oldBaseUrl = pythonWorkerProperties.getBaseUrl();
        boolean oldProxyEnabled = pythonWorkerProperties.isApiProxyEnabled();
        try {
            pythonWorkerProperties.setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
            pythonWorkerProperties.setApiProxyEnabled(true);
            importTaskMetadataService.syncMap(importTaskPayload("ai_standardize_task_1", "待校验", 1, "AI 标准化任务"));

            mockMvc.perform(postJson(
                            "/api/import-tasks/ai_standardize_task_1/questions/ai_standardize_task_1_question_1/standardize/ai",
                            Map.of("markdown", "含答案解析的题干", "writeResult", true)
                    ))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.writeResult").value(true))
                    .andExpect(jsonPath("$.markdown").value("清理后的题干"))
                    .andExpect(jsonPath("$.answer").value("C"))
                    .andExpect(jsonPath("$.analysis").value("从题干中提取的解析"))
                    .andExpect(jsonPath("$.question.manualMarkdown").value("清理后的题干"))
                    .andExpect(jsonPath("$.question.answer").value("C"))
                    .andExpect(jsonPath("$.question.analysis").value("从题干中提取的解析"));
        } finally {
            pythonWorkerProperties.setBaseUrl(oldBaseUrl);
            pythonWorkerProperties.setApiProxyEnabled(oldProxyEnabled);
            server.stop(0);
        }
    }

    @Test
    void aiStandardizeDoesNotWriteWorkerReviewCandidate() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/worker/ai/standardize", exchange ->
                writeJson(exchange, Map.of(
                        "markdown", "不安全候选",
                        "applyRecommendation", "review_required",
                        "reviewReasons", List.of("option_image_reference_removed"),
                        "standardizer", Map.of("source", "ai")
                ))
        );
        server.start();
        String oldBaseUrl = pythonWorkerProperties.getBaseUrl();
        boolean oldProxyEnabled = pythonWorkerProperties.isApiProxyEnabled();
        try {
            pythonWorkerProperties.setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
            pythonWorkerProperties.setApiProxyEnabled(true);
            importTaskMetadataService.syncMap(importTaskPayload("ai_standardize_review_1", "待校验", 1, "待复核标准化任务"));

            mockMvc.perform(postJson(
                            "/api/import-tasks/ai_standardize_review_1/questions/ai_standardize_review_1_question_1/standardize/ai",
                            Map.of("markdown", "原始题干", "writeResult", true)
                    ))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.writeResult").value(false))
                    .andExpect(jsonPath("$.writeDecision").value("review_required"))
                    .andExpect(jsonPath("$.question.manualMarkdown").value(""));
        } finally {
            pythonWorkerProperties.setBaseUrl(oldBaseUrl);
            pythonWorkerProperties.setApiProxyEnabled(oldProxyEnabled);
            server.stop(0);
        }
    }

    @Test
    void aiStandardizeDoesNotOverwriteConcurrentManualEdit() throws Exception {
        String taskId = "ai_standardize_stale_1";
        String questionId = taskId + "_question_1";
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/worker/ai/standardize", exchange -> {
            importQuestionSyncService.updateQuestionFromPayload(
                    taskId,
                    questionId,
                    Map.of("manualMarkdown", "人工并发修改")
            );
            writeJson(exchange, Map.of(
                    "markdown", "模型候选",
                    "applyRecommendation", "safe_to_apply",
                    "standardizer", Map.of("source", "ai")
            ));
        });
        server.start();
        String oldBaseUrl = pythonWorkerProperties.getBaseUrl();
        boolean oldProxyEnabled = pythonWorkerProperties.isApiProxyEnabled();
        try {
            pythonWorkerProperties.setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
            pythonWorkerProperties.setApiProxyEnabled(true);
            importTaskMetadataService.syncMap(importTaskPayload(taskId, "待校验", 1, "并发编辑保护任务"));

            mockMvc.perform(postJson(
                            "/api/import-tasks/" + taskId + "/questions/" + questionId + "/standardize/ai",
                            Map.of("markdown", "原始题干", "writeResult", true)
                    ))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.writeResult").value(false))
                    .andExpect(jsonPath("$.writeDecision").value("review_required"))
                    .andExpect(jsonPath("$.reviewReasons[0]").value("stale_input"))
                    .andExpect(jsonPath("$.question.manualMarkdown").value("人工并发修改"));
        } finally {
            pythonWorkerProperties.setBaseUrl(oldBaseUrl);
            pythonWorkerProperties.setApiProxyEnabled(oldProxyEnabled);
            server.stop(0);
        }
    }

    /** Text-only standardization must not erase structured option image references. */
    @Test
    void aiStandardizePreservesOptionImagesWhenResponseHasNoVisualFields() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        AtomicReference<String> standardizeRequest = new AtomicReference<>("");
        server.createContext("/worker/ai/standardize", exchange -> {
            standardizeRequest.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            writeJson(exchange, Map.of(
                    "markdown", "清理后的题干",
                    "standardizer", Map.of("source", "test")
            ));
        });
        server.start();
        String oldBaseUrl = pythonWorkerProperties.getBaseUrl();
        boolean oldProxyEnabled = pythonWorkerProperties.isApiProxyEnabled();
        try {
            pythonWorkerProperties.setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
            pythonWorkerProperties.setApiProxyEnabled(true);
            Map<String, Object> payload = new LinkedHashMap<>(
                    importTaskPayload("ai_visual_task_1", "待校验", 1, "AI 题图保护任务")
            );
            @SuppressWarnings("unchecked")
            Map<String, Object> question = new LinkedHashMap<>(((List<Map<String, Object>>) payload.get("questions")).get(0));
            question.put("images", List.of(Map.of("imageId", "img-1", "label", "图1", "url", "/api/a.jpg")));
            question.put("options", List.of(
                    Map.of("label", "A", "content", "![](图1) 食品夹", "contentMarkdown", "![](图1) 食品夹"),
                    Map.of("label", "B", "content", "船桨", "contentMarkdown", "船桨")
            ));
            question.put("imagePlacements", List.of(Map.of(
                    "imageId", "img-1",
                    "target", Map.of("kind", "option", "optionLabel", "A")
            )));
            payload.put("questions", List.of(question));
            importTaskMetadataService.syncMap(payload);

            mockMvc.perform(postJson(
                            "/api/import-tasks/ai_visual_task_1/questions/ai_visual_task_1_question_1/standardize/ai",
                            Map.of("markdown", "含图片选项的题干", "writeResult", true)
                    ))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.question.options[0].contentMarkdown").value("![](图1) 食品夹"));

            JsonNode workerRequest = objectMapper.readTree(standardizeRequest.get());
            org.assertj.core.api.Assertions.assertThat(workerRequest.path("markdown").asText())
                    .contains("\\begin{tasks}(2)", "\\task ![](图1) 食品夹", "\\task 船桨");
            org.assertj.core.api.Assertions.assertThat(workerRequest.path("structuredHints").path("options").size())
                    .isEqualTo(2);
            org.assertj.core.api.Assertions.assertThat(workerRequest.path("structuredHints").path("imagePlacements").size())
                    .isEqualTo(1);
            org.assertj.core.api.Assertions.assertThat(workerRequest.path("pipelineVersion").asText())
                    .isEqualTo("standardization.v2");

            var saved = importQuestionSyncService.getQuestion("ai_visual_task_1_question_1");
            org.assertj.core.api.Assertions.assertThat(saved.getOptionsJson()).contains("图1");
            org.assertj.core.api.Assertions.assertThat(saved.getImagesJson()).contains("img-1");
            org.assertj.core.api.Assertions.assertThat(saved.getImagePlacementsJson()).contains("optionLabel");
        } finally {
            pythonWorkerProperties.setBaseUrl(oldBaseUrl);
            pythonWorkerProperties.setApiProxyEnabled(oldProxyEnabled);
            server.stop(0);
        }
    }

    /**
     * 验证 AI 标准化默认只返回候选，不直接覆盖导入题编辑内容。
     *
     * @throws Exception 测试请求或内置 HTTP 服务失败时抛出
     */
    @Test
    void aiStandardizeReturnsCandidateWithoutWritingByDefault() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/worker/ai/standardize", exchange ->
                writeJson(exchange, Map.of(
                        "markdown", "候选修复题干",
                        "standardizer", Map.of("source", "test", "confidence", "high", "candidateSevereIssues", List.of())
                ))
        );
        server.start();
        String oldBaseUrl = pythonWorkerProperties.getBaseUrl();
        boolean oldProxyEnabled = pythonWorkerProperties.isApiProxyEnabled();
        try {
            pythonWorkerProperties.setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
            pythonWorkerProperties.setApiProxyEnabled(true);
            importTaskMetadataService.syncMap(importTaskPayload("ai_candidate_task_1", "待校验", 1, "AI 候选任务"));

            mockMvc.perform(postJson(
                            "/api/import-tasks/ai_candidate_task_1/questions/ai_candidate_task_1_question_1/standardize/ai",
                            Map.of("markdown", "当前编辑题干")
                    ))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.writeResult").value(false))
                    .andExpect(jsonPath("$.writeSkippedReason").value("AI 标准化结果已作为候选返回，等待人工预览后应用保存"))
                    .andExpect(jsonPath("$.markdown").value("候选修复题干"))
                    .andExpect(jsonPath("$.question.manualMarkdown").isEmpty())
                    .andExpect(jsonPath("$.question.stemMarkdown").value("导入题 1"));
        } finally {
            pythonWorkerProperties.setBaseUrl(oldBaseUrl);
            pythonWorkerProperties.setApiProxyEnabled(oldProxyEnabled);
            server.stop(0);
        }
    }

    /**
     * 验证 Java 接管 AI 标准化后仍会把同题原始 OCR 片段传给 worker，供严重 LaTeX 损坏时兜底。
     *
     * @throws Exception 测试请求或内置 HTTP 服务失败时抛出
     */
    @Test
    void aiStandardizePassesSameQuestionRawOcrContext() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        AtomicReference<String> requestBody = new AtomicReference<>("");
        server.createContext("/api/ocr/jobs/ocr_paper_bridge/result", exchange ->
                writeJson(exchange, Map.of(
                        "markdown", "19. 前一题\n20. （8分）（1）解下面一元一次不等式组，并写出它的所有非负整数解。\n$\\left\\{\\begin{array}{l}\\frac{5x-1}{6}+2 \\geq \\frac{x+5}{4} \\\\ 2x+5 \\leq 3(5-x)\\end{array}\\right.$\n（2）化简：$\\left(\\frac{a^2}{a-2}-\\frac{2a}{a+2}\\right)\\div\\frac{a}{a^2-4}$\n21. 后一题"
                ))
        );
        server.createContext("/worker/ai/standardize", exchange -> {
            requestBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            writeJson(exchange, Map.of(
                    "markdown", "清理后的第 20 题",
                    "standardizer", Map.of("source", "test", "confidence", "high", "candidateSevereIssues", List.of())
            ));
        });
        server.start();
        String oldBaseUrl = pythonWorkerProperties.getBaseUrl();
        boolean oldProxyEnabled = pythonWorkerProperties.isApiProxyEnabled();
        try {
            pythonWorkerProperties.setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
            pythonWorkerProperties.setApiProxyEnabled(true);
            Map<String, Object> rawContextTask = new LinkedHashMap<>(importTaskPayload("ai_raw_context_task_1", "待校验", 20, "AI 原文上下文任务"));
            List<Map<String, Object>> rawContextQuestions = new ArrayList<>();
            for (Object item : (List<?>) rawContextTask.get("questions")) {
                rawContextQuestions.add(new LinkedHashMap<>((Map<String, Object>) item));
            }
            rawContextQuestions.get(19).put("manualMarkdown", "BROKEN_MANUAL_CONTEXT_SHOULD_NOT_BE_TRUSTED");
            rawContextTask.put("questions", rawContextQuestions);
            importTaskMetadataService.syncMap(rawContextTask);

            mockMvc.perform(postJson(
                            "/api/import-tasks/ai_raw_context_task_1/questions/ai_raw_context_task_1_question_20/standardize/ai",
                            Map.of("markdown", "$$\\left\\{\\begin{array}{l l}\\displaystyle$\\frac{5x - 1}{6}$ + 2$\\geq$\\displaystyle$\\frac{x + 5}{4}$$")
                    ))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.markdown").value("清理后的第 20 题"))
                    .andExpect(jsonPath("$.writeResult").value(false))
                    .andExpect(jsonPath("$.question.manualMarkdown").value("BROKEN_MANUAL_CONTEXT_SHOULD_NOT_BE_TRUSTED"));

            JsonNode sent = objectMapper.readTree(requestBody.get());
            org.assertj.core.api.Assertions.assertThat(sent.path("rawOcrContext").asText())
                    .contains("20. （8分）（1）解下面一元一次不等式组")
                    .contains("\\frac{5x-1}{6}")
                    .doesNotContain("21. 后一题")
                    .doesNotContain("BROKEN_MANUAL_CONTEXT_SHOULD_NOT_BE_TRUSTED");
        } finally {
            pythonWorkerProperties.setBaseUrl(oldBaseUrl);
            pythonWorkerProperties.setApiProxyEnabled(oldProxyEnabled);
            server.stop(0);
        }
    }

    /**
     * 验证 AI 标准化结果仍有严重 LaTeX 风险时，Java 只记录响应但不覆盖原题干。
     *
     * @throws Exception 测试请求或内置 HTTP 服务失败时抛出
     */
    @Test
    void aiStandardizeDoesNotOverwriteWhenCandidateStillHasSevereLatexRisk() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/ocr/jobs/ocr_paper_bridge/result", exchange ->
                writeJson(exchange, Map.of("markdown", "1. 原始 OCR 题干"))
        );
        server.createContext("/worker/ai/standardize", exchange ->
                writeJson(exchange, Map.of(
                        "markdown", "$$\\left\\{\\begin{array}{l l}\\displaystyle$\\frac{x}{2}$",
                        "standardizer", Map.of(
                                "source", "test",
                                "confidence", "medium",
                                "candidateSevereIssues", List.of("展示公式内部嵌套了单个 $ 分隔符")
                        )
                ))
        );
        server.start();
        String oldBaseUrl = pythonWorkerProperties.getBaseUrl();
        boolean oldProxyEnabled = pythonWorkerProperties.isApiProxyEnabled();
        try {
            pythonWorkerProperties.setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
            pythonWorkerProperties.setApiProxyEnabled(true);
            importTaskMetadataService.syncMap(importTaskPayload("ai_severe_guard_task_1", "待校验", 1, "AI 严重风险闸门任务"));

            mockMvc.perform(postJson(
                            "/api/import-tasks/ai_severe_guard_task_1/questions/ai_severe_guard_task_1_question_1/standardize/ai",
                            Map.of("markdown", "原始安全题干", "writeResult", true)
                    ))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.writeResult").value(false))
                    .andExpect(jsonPath("$.writeSkippedReason").exists())
                    .andExpect(jsonPath("$.question.manualMarkdown").isEmpty())
                    .andExpect(jsonPath("$.question.stemMarkdown").value("导入题 1"));
        } finally {
            pythonWorkerProperties.setBaseUrl(oldBaseUrl);
            pythonWorkerProperties.setApiProxyEnabled(oldProxyEnabled);
            server.stop(0);
        }
    }

    /**
     * 验证 worker 标记候选不可应用时，Java 显式写回也必须保留原题干。
     *
     * @throws Exception 测试请求或内置 HTTP 服务失败时抛出
     */
    @Test
    void aiStandardizeDoesNotOverwriteWhenCandidateApplyBlocked() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/ocr/jobs/ocr_paper_bridge/result", exchange ->
                writeJson(exchange, Map.of("markdown", "1. 原始 OCR 题干"))
        );
        server.createContext("/worker/ai/standardize", exchange ->
                writeJson(exchange, Map.of(
                        "markdown", "不可渲染候选",
                        "standardizer", Map.of(
                                "source", "test",
                                "confidence", "high",
                                "candidateSevereIssues", List.of(),
                                "applyBlocked", true,
                                "renderValidation", Map.of(
                                        "valid", false,
                                        "issues", List.of("候选未通过渲染安全校验")
                                )
                        )
                ))
        );
        server.start();
        String oldBaseUrl = pythonWorkerProperties.getBaseUrl();
        boolean oldProxyEnabled = pythonWorkerProperties.isApiProxyEnabled();
        try {
            pythonWorkerProperties.setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
            pythonWorkerProperties.setApiProxyEnabled(true);
            importTaskMetadataService.syncMap(importTaskPayload("ai_apply_blocked_task_1", "待校验", 1, "AI 应用闸门任务"));

            mockMvc.perform(postJson(
                            "/api/import-tasks/ai_apply_blocked_task_1/questions/ai_apply_blocked_task_1_question_1/standardize/ai",
                            Map.of("markdown", "原始安全题干", "writeResult", true)
                    ))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.writeResult").value(false))
                    .andExpect(jsonPath("$.writeSkippedReason").exists())
                    .andExpect(jsonPath("$.question.manualMarkdown").isEmpty())
                    .andExpect(jsonPath("$.question.stemMarkdown").value("导入题 1"));
        } finally {
            pythonWorkerProperties.setBaseUrl(oldBaseUrl);
            pythonWorkerProperties.setApiProxyEnabled(oldProxyEnabled);
            server.stop(0);
        }
    }

    /**
     * 验证试卷导出由 Java 创建导出 job、调用 worker、保存文件并记录导出结果。
     *
     * @throws Exception 测试请求或内置 HTTP 服务失败时抛出
     */
    @Test
    void paperExportIsOrchestratedByJavaAndStoredAsExportJob() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/worker/export/render", exchange -> {
            byte[] body = "export-bytes".getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add(HttpHeaders.CONTENT_TYPE, "application/pdf");
            exchange.getResponseHeaders().add(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"paper.pdf\"");
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();
        String oldBaseUrl = pythonWorkerProperties.getBaseUrl();
        boolean oldProxyEnabled = pythonWorkerProperties.isApiProxyEnabled();
        try {
            pythonWorkerProperties.setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
            pythonWorkerProperties.setApiProxyEnabled(true);
            String paperId = createPaper(createQuestion(createKnowledgePoint()));

            MvcResult export = mockMvc.perform(get("/api/papers/" + paperId + "/export").param("format", "pdf"))
                    .andExpect(status().isOk())
                    .andReturn();
            org.assertj.core.api.Assertions.assertThat(export.getResponse().getContentAsByteArray())
                    .isEqualTo("export-bytes".getBytes(StandardCharsets.UTF_8));

            mockMvc.perform(get("/api/capabilities/export-flow/jobs").param("paperId", paperId))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.total").value(1))
                    .andExpect(jsonPath("$.items[0].status").value("success"))
                    .andExpect(jsonPath("$.items[0].response.storageFileId").exists());
        } finally {
            pythonWorkerProperties.setBaseUrl(oldBaseUrl);
            pythonWorkerProperties.setApiProxyEnabled(oldProxyEnabled);
            server.stop(0);
        }
    }

    /**
     * 验证 OCR 重试会调用 worker retry 接口，并且 callback-flow 会签名、幂等和死信。
     *
     * @throws Exception 测试请求或内置 HTTP 服务失败时抛出
     */
    @Test
    void importTaskRetryCallsWorkerRetryAndCallbackFlowSignsEvents() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        AtomicReference<String> signature = new AtomicReference<>("");
        server.createContext("/worker/ocr/ocr_retry_failed/retry", exchange ->
                writeJson(exchange, Map.of("jobId", "ocr_retry_failed", "status", "pending", "retryCount", 1))
        );
        server.createContext("/callback", exchange -> {
            signature.set(exchange.getRequestHeaders().getFirst("X-Question-Engine-Signature"));
            byte[] body = "ok".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.createContext("/callback-fail", exchange -> {
            byte[] body = "failed".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(500, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();
        String oldBaseUrl = pythonWorkerProperties.getBaseUrl();
        boolean oldProxyEnabled = pythonWorkerProperties.isApiProxyEnabled();
        try {
            pythonWorkerProperties.setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
            pythonWorkerProperties.setApiProxyEnabled(true);
            Map<String, Object> failed = new LinkedHashMap<>(importTaskPayload(
                    "retry_task_1",
                    "处理中",
                    0,
                    "重试任务",
                    ocrJobPayload("ocr_retry_failed", "paper.md", "failed", "OCR failed"),
                    ocrJobPayload("ocr_retry_answer", "answer.md", "success", "")
            ));
            failed.put("retryable", true);
            importTaskMetadataService.syncMap(failed);

            mockMvc.perform(post("/api/import-tasks/retry_task_1/retry"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.status").value("处理中"))
                    .andExpect(jsonPath("$.retriedJobs.paper.status").value("pending"));

            mockMvc.perform(postJson("/api/capabilities/callback-flow/test", Map.of(
                            "callbackUrl", "http://127.0.0.1:" + server.getAddress().getPort() + "/callback",
                            "eventType", "processing.completed",
                            "secret", "secret",
                            "payload", Map.of("taskId", "retry_task_1")
                    )))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.status").value("sent"));
            org.assertj.core.api.Assertions.assertThat(signature.get()).startsWith("sha256=");

            mockMvc.perform(postJson("/api/capabilities/callback-flow/test", Map.of(
                            "callbackUrl", "http://127.0.0.1:" + server.getAddress().getPort() + "/callback-fail",
                            "eventType", "processing.failed",
                            "idempotencyKey", "callback-idem-1",
                            "maxRetryCount", 1,
                            "payload", Map.of("taskId", "retry_task_1")
                    )))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.status").value("dead_letter"))
                    .andExpect(jsonPath("$.idempotencyKey").value("callback-idem-1"))
                    .andExpect(jsonPath("$.maxRetryCount").value(1))
                    .andExpect(jsonPath("$.retryCount").value(1));

            mockMvc.perform(postJson("/api/capabilities/callback-flow/test", Map.of(
                            "callbackUrl", "http://127.0.0.1:" + server.getAddress().getPort() + "/callback-fail",
                            "eventType", "processing.failed",
                            "idempotencyKey", "callback-idem-1",
                            "maxRetryCount", 1,
                            "payload", Map.of("taskId", "retry_task_1")
                    )))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.status").value("dead_letter"))
                    .andExpect(jsonPath("$.retryCount").value(1));

            mockMvc.perform(postJson("/api/capabilities/callback-flow/events/retry-due", Map.of()))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.total").value(0));
        } finally {
            pythonWorkerProperties.setBaseUrl(oldBaseUrl);
            pythonWorkerProperties.setApiProxyEnabled(oldProxyEnabled);
            server.stop(0);
        }
    }

    /**
     * 创建测试用知识点并返回 ID。
     *
     * @return 新建知识点 ID
     * @throws Exception MockMvc 调用或 JSON 解析失败时抛出
     */
    private String createKnowledgePoint() throws Exception {
        MvcResult result = mockMvc.perform(postJson("/api/knowledge-points", Map.of(
                        "name", "二次函数",
                        "subject", "数学",
                        "grade", "九年级",
                        "description", "函数图像与性质"
                )))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.name").value("二次函数"))
                .andReturn();
        return readId(result);
    }

    /**
     * 使用默认关键词创建测试题目。
     *
     * @param knowledgePointId 知识点 ID
     * @return 新建题目 ID
     * @throws Exception MockMvc 调用或 JSON 解析失败时抛出
     */
    private String createQuestion(String knowledgePointId) throws Exception {
        return createQuestion(knowledgePointId, "二次函数");
    }

    /**
     * 创建带指定关键词的测试题目。
     *
     * @param knowledgePointId 知识点 ID
     * @param keyword 题干和知识点关键词
     * @return 新建题目 ID
     * @throws Exception MockMvc 调用或 JSON 解析失败时抛出
     */
    private String createQuestion(String knowledgePointId, String keyword) throws Exception {
        MvcResult result = mockMvc.perform(postJson("/api/question-bank/questions", Map.ofEntries(
                        entry("title", keyword + "选择题"),
                        entry("subject", "数学"),
                        entry("grade", "九年级"),
                        entry("type", "single"),
                        entry("difficulty", "medium"),
                        entry("score", 5),
                        entry("manualMarkdown", "若 $y=x^2$，求图像顶点。" + keyword),
                        entry("answer", "原点"),
                        entry("analysis", "标准形式可直接读出顶点。"),
                        entry("knowledgePointIds", List.of(knowledgePointId)),
                        entry("knowledgePoints", List.of(keyword))
                )))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.subject").value("数学"))
                .andReturn();
        return readId(result);
    }

    /**
     * 使用默认标题创建测试试卷。
     *
     * @param questionId 题目 ID
     * @return 新建试卷 ID
     * @throws Exception MockMvc 调用或 JSON 解析失败时抛出
     */
    private String createPaper(String questionId) throws Exception {
        return createPaper(questionId, "九年级数学测试卷");
    }

    /**
     * 创建包含指定题目的测试试卷。
     *
     * @param questionId 题目 ID
     * @param title 试卷标题
     * @return 新建试卷 ID
     * @throws Exception MockMvc 调用或 JSON 解析失败时抛出
     */
    private String createPaper(String questionId, String title) throws Exception {
        MvcResult result = mockMvc.perform(postJson("/api/papers", Map.of(
                        "title", title,
                        "subject", "数学",
                        "grade", "九年级",
                        "questionIds", List.of(questionId),
                        "scores", Map.of(questionId, 5),
                        "header", Map.of("subject", "数学", "grade", "九年级"),
                        "answerDisplay", "teacher"
                )))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.title").value(title))
                .andReturn();
        return readId(result);
    }

    /**
     * 构造 JSON POST 请求。
     *
     * @param path 请求路径
     * @param payload 请求体对象
     * @return MockMvc 请求构造器
     * @throws Exception JSON 序列化失败时抛出
     */
    private org.springframework.test.web.servlet.RequestBuilder postJson(String path, Object payload)
            throws Exception {
        return post(path)
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(payload));
    }

    /**
     * 构造 JSON PUT 请求。
     *
     * @param path 请求路径
     * @param payload 请求体对象
     * @return MockMvc 请求构造器
     * @throws Exception JSON 序列化失败时抛出
     */
    private org.springframework.test.web.servlet.RequestBuilder putJson(String path, Object payload)
            throws Exception {
        return put(path)
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(payload));
    }

    /**
     * 从响应 JSON 根对象中读取 id 字段。
     *
     * @param result MockMvc 响应
     * @return id 字符串
     * @throws Exception JSON 解析失败时抛出
     */
    private String readId(MvcResult result) throws Exception {
        JsonNode node = objectMapper.readTree(result.getResponse().getContentAsString());
        return node.get("id").asText();
    }

    /**
     * 创建 Map.ofEntries 所需的键值项。
     *
     * @param key 键
     * @param value 值
     * @return Map entry
     */
    private static Entry<String, Object> entry(String key, Object value) {
        return Map.entry(key, value);
    }

    /**
     * 构造指向内置 HttpServer 的导入入库桥接服务。
     *
     * @param server 内置 HTTP 服务
     * @return 桥接服务实例
     */
    private ImportTaskBankBridgeService bridgeService(HttpServer server) {
        PythonWorkerProperties properties = new PythonWorkerProperties();
        properties.setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
        properties.setConnectTimeoutMs(1000);
        properties.setReadTimeoutMs(1000);
        return new ImportTaskBankBridgeService(properties, objectMapper, bankQuestionService);
    }

    /**
     * 构造指向内置 HttpServer 的导入任务元数据桥接服务。
     *
     * @param server 内置 HTTP 服务
     * @return 桥接服务实例
     */
    private ImportTaskMetadataBridgeService metadataBridgeService(HttpServer server) {
        PythonWorkerProperties properties = new PythonWorkerProperties();
        properties.setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
        properties.setConnectTimeoutMs(1000);
        properties.setReadTimeoutMs(1000);
        return new ImportTaskMetadataBridgeService(
                properties,
                objectMapper,
                importTaskMetadataService,
                importQuestionSyncService,
                javaFileStorageService
        );
    }

    /**
     * 构造 worker 入库接口返回的题库题 payload。
     *
     * @param id 题库题 ID
     * @param number 题号
     * @return 题库题 Map
     */
    private Map<String, Object> bankQuestionPayload(String id, int number) {
        return Map.ofEntries(
                entry("id", id),
                entry("sourceImportTaskId", "task-bridge"),
                entry("sourceImportQuestionId", "question-" + number),
                entry("source", "桥接同步题"),
                entry("stage", "高中"),
                entry("subject", "数学"),
                entry("grade", "高一"),
                entry("region", "本地"),
                entry("year", "2026"),
                entry("title", "桥接同步题"),
                entry("number", number),
                entry("type", "choice"),
                entry("stemMarkdown", "桥接同步题 " + number),
                entry("manualMarkdown", "桥接同步题 " + number),
                entry("answer", "A"),
                entry("analysis", "桥接同步解析"),
                entry("knowledgePointIds", List.of()),
                entry("knowledgePoints", List.of()),
                entry("difficulty", "medium"),
                entry("score", 2),
                entry("images", List.of()),
                entry("options", List.of()),
                entry("children", List.of()),
                entry("createdAt", "2026-06-29T10:00:00Z"),
                entry("updatedAt", "2026-06-29T10:00:00Z")
        );
    }

    /**
     * 构造默认标题的导入任务 payload。
     *
     * @param id 任务 ID
     * @param status 任务状态
     * @param questionCount 题目数量
     * @return 导入任务 Map
     */
    private Map<String, Object> importTaskPayload(String id, String status, int questionCount) {
        return importTaskPayload(id, status, questionCount, "桥接导入任务");
    }

    /**
     * 构造默认 OCR 成功的导入任务 payload。
     *
     * @param id 任务 ID
     * @param status 任务状态
     * @param questionCount 题目数量
     * @param title 任务标题
     * @return 导入任务 Map
     */
    private Map<String, Object> importTaskPayload(String id, String status, int questionCount, String title) {
        return importTaskPayload(
                id,
                status,
                questionCount,
                title,
                ocrJobPayload("ocr_paper_bridge", "paper.md", "success"),
                ocrJobPayload("ocr_answer_bridge", "answer.md", "success")
        );
    }

    /**
     * 构造可指定 OCR job 的导入任务 payload。
     *
     * @param id 任务 ID
     * @param status 任务状态
     * @param questionCount 题目数量
     * @param title 任务标题
     * @param paperOcrJob 试卷 OCR job
     * @param answerOcrJob 答案 OCR job
     * @return 导入任务 Map
     */
    private Map<String, Object> importTaskPayload(
            String id,
            String status,
            int questionCount,
            String title,
            Map<String, Object> paperOcrJob,
            Map<String, Object> answerOcrJob
    ) {
        return Map.ofEntries(
                entry("id", id),
                entry("stage", "高中"),
                entry("subject", "数学"),
                entry("grade", "高一"),
                entry("region", "本地"),
                entry("year", "2026"),
                entry("title", title),
                entry("status", status),
                entry("paperFile", Map.of("filename", "paper.md")),
                entry("answerFile", Map.of("filename", "answer.md")),
                entry("paperOcrJobId", paperOcrJob.get("jobId")),
                entry("answerOcrJobId", answerOcrJob.get("jobId")),
                entry("paperOcrJob", paperOcrJob),
                entry("answerOcrJob", answerOcrJob),
                entry("questions", makeImportQuestions(id, questionCount, status)),
                entry("createdAt", "2026-06-29T10:00:00Z"),
                entry("updatedAt", "2026-06-29T10:00:00Z")
        );
    }

    /**
     * 构造默认无错误的 OCR job payload。
     *
     * @param jobId OCR job ID
     * @param filename 文件名
     * @param status OCR 状态
     * @return OCR job Map
     */
    private Map<String, Object> ocrJobPayload(String jobId, String filename, String status) {
        return ocrJobPayload(jobId, filename, status, "");
    }

    /**
     * 构造 OCR job payload。
     *
     * @param jobId OCR job ID
     * @param filename 文件名
     * @param status OCR 状态
     * @param error 错误信息
     * @return OCR job Map
     */
    private Map<String, Object> ocrJobPayload(String jobId, String filename, String status, String error) {
        return Map.ofEntries(
                entry("jobId", jobId),
                entry("filename", filename),
                entry("status", status),
                entry("createdAt", "2026-06-29T10:00:00Z"),
                entry("startedAt", "2026-06-29T10:00:01Z"),
                entry("finishedAt", "2026-06-29T10:00:02Z"),
                entry("error", error)
        );
    }

    /**
     * 构造导入任务下的题目列表。
     *
     * @param taskId 任务 ID
     * @param count 题目数量
     * @param taskStatus 任务状态
     * @return 题目 Map 列表
     */
    private List<Map<String, Object>> makeImportQuestions(String taskId, int count, String taskStatus) {
        return java.util.stream.IntStream.rangeClosed(1, count)
                .mapToObj(index -> Map.<String, Object>of(
                        "id", taskId + "_question_" + index,
                        "number", index,
                        "status", questionStatus(taskStatus, index),
                        "stemMarkdown", "导入题 " + index,
                        "images", List.of(Map.of("name", "figure-" + index + ".png", "url", "/api/image-" + index + ".png"))
                ))
                .toList();
    }

    /**
     * 根据任务状态推导测试题目的状态。
     *
     * @param taskStatus 任务状态
     * @param index 题目序号
     * @return 题目状态
     */
    private String questionStatus(String taskStatus, int index) {
        if ("已完成".equals(taskStatus)) {
            return "已入库";
        }
        if ("部分完成".equals(taskStatus) && index == 1) {
            return "已校验";
        }
        return "待校验";
    }

    /**
     * 向内置 HttpServer 写 JSON 响应。
     *
     * @param exchange HTTP 交换对象
     * @param payload 响应载荷
     * @throws IOException 写响应失败时抛出
     */
    private void writeJson(HttpExchange exchange, Object payload) throws IOException {
        writeJson(exchange, 200, payload);
    }

    /**
     * 向内置 HttpServer 写指定状态码的 JSON 响应。
     *
     * @param exchange HTTP 交换对象
     * @param statusCode HTTP 状态码
     * @param payload 响应载荷
     * @throws IOException 写响应失败时抛出
     */
    private void writeJson(HttpExchange exchange, int statusCode, Object payload) throws IOException {
        byte[] body = objectMapper.writeValueAsBytes(payload);
        exchange.getResponseHeaders().add("Content-Type", "application/json");
        exchange.sendResponseHeaders(statusCode, body.length);
        exchange.getResponseBody().write(body);
        exchange.close();
    }
}
