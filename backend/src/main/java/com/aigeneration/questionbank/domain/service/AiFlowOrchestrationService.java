package com.aigeneration.questionbank.domain.service;

import com.aigeneration.questionbank.domain.entity.AiJobEntity;
import com.aigeneration.questionbank.domain.entity.BankQuestionEntity;
import com.aigeneration.questionbank.domain.entity.ImportQuestionEntity;
import com.aigeneration.questionbank.domain.entity.ImportTaskEntity;
import com.aigeneration.questionbank.domain.entity.StorageFileEntity;
import com.aigeneration.questionbank.domain.mapper.AiJobMapper;
import com.aigeneration.questionbank.domain.support.Ids;
import com.aigeneration.questionbank.domain.support.JsonSupport;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

/**
 * AI 能力编排服务。
 *
 * <p>负责导入题和题库题的 AI 标准化、AI 解析、临时 Markdown 处理、AI job 记录、
 * 题图多模态上下文拼装和结果回写。Python worker 只执行模型调用，Java 负责业务状态。</p>
 */
@Service
public class AiFlowOrchestrationService {
    /**
     * 单次 AI 请求最多携带的题图数量，避免多模态上下文过大。
     */
    private static final int MAX_AI_IMAGE_COUNT = 6;

    /**
     * 单张题图允许内联到 AI 请求中的最大字节数。
     */
    private static final long MAX_AI_IMAGE_BYTES = 8L * 1024L * 1024L;

    /**
     * AI job 表访问对象。
     */
    private final AiJobMapper mapper;

    /**
     * Python worker 客户端，用于调用 AI 标准化和解析接口。
     */
    private final PythonWorkerClient pythonWorkerClient;

    /**
     * 导入题服务，用于读取题目上下文并回写 AI 结果。
     */
    private final ImportQuestionSyncService importQuestionService;

    /**
     * 题库题服务，用于读取题库题上下文并回写 AI 结果。
     */
    private final BankQuestionService bankQuestionService;

    /**
     * 导入任务元数据服务，用于回溯 OCR 整稿并构造同题原始上下文。
     */
    private final ImportTaskMetadataService importTaskMetadataService;

    /**
     * 文件存储服务，用于读取已保存题图并生成 data URL。
     */
    private final JavaFileStorageService fileStorageService;

    /**
     * JSON 辅助组件，用于读写 job 请求/响应和题目 JSON 字段。
     */
    private final JsonSupport json;

    /** 单题和全局共享的标准化请求构造器。 */
    private final StandardizationRequestFactory standardizationRequests;

    /**
     * 注入 AI 编排所需的 job、worker、题目、文件和 JSON 依赖。
     *
     * @param mapper AI job Mapper
     * @param pythonWorkerClient Python worker 客户端
     * @param importQuestionService 导入题服务
     * @param bankQuestionService 题库题服务
     * @param fileStorageService 文件存储服务
     * @param json JSON 辅助组件
     */
    public AiFlowOrchestrationService(
            AiJobMapper mapper,
            PythonWorkerClient pythonWorkerClient,
            ImportQuestionSyncService importQuestionService,
            BankQuestionService bankQuestionService,
            ImportTaskMetadataService importTaskMetadataService,
            JavaFileStorageService fileStorageService,
            JsonSupport json,
            StandardizationRequestFactory standardizationRequests
    ) {
        this.mapper = mapper;
        this.pythonWorkerClient = pythonWorkerClient;
        this.importQuestionService = importQuestionService;
        this.bankQuestionService = bankQuestionService;
        this.importTaskMetadataService = importTaskMetadataService;
        this.fileStorageService = fileStorageService;
        this.json = json;
        this.standardizationRequests = standardizationRequests;
    }

    /**
     * 对导入题执行 AI 标准化。
     *
     * @param taskId 导入任务 ID
     * @param questionId 导入题 ID
     * @param payload 请求载荷
     * @return AI 响应及题目快照
     */
    public Map<String, Object> standardizeImportQuestion(String taskId, String questionId, Map<String, Object> payload) {
        ImportQuestionEntity question = requireImportQuestion(taskId, questionId);
        String requestSource = "global".equals(text(payload.get("requestSource"))) ? "global" : "single";
        String rawOcrContext = importRawContext(question);
        String persistedInputHash = standardizationRequests.inputHash(
                question,
                firstText(question.getManualMarkdown(), question.getStemMarkdown()),
                rawOcrContext
        );
        Map<String, Object> request = standardizationRequests.build(
                question,
                text(payload.get("markdown")),
                rawOcrContext,
                requestSource
        );
        boolean writeRequested = standardizeWriteRequested(payload);
        Map<String, Object> response = executeAiJob("import-question", questionId, "standardize", "/worker/ai/standardize", request, false);
        String recommendation = value(response.get("applyRecommendation"));
        ImportQuestionEntity latest = requireImportQuestion(taskId, questionId);
        boolean staleInput = writeRequested && !persistedInputHash.equals(standardizationRequests.inputHash(
                latest,
                firstText(latest.getManualMarkdown(), latest.getStemMarkdown()),
                importRawContext(latest)
        ));
        if (staleInput) {
            List<Object> reasons = new ArrayList<>(listValue(response.get("reviewReasons")));
            if (!reasons.contains("stale_input")) reasons.add("stale_input");
            response.put("reviewReasons", reasons);
            markStandardizeWriteSkipped(response);
        } else if (writeRequested && "unchanged".equals(recommendation)) {
            response.put("writeResult", true);
            response.put("writeDecision", "unchanged");
        } else if (writeRequested && standardizeWriteAllowed(response)) {
            importQuestionService.updateStandardizedResult(
                    taskId,
                    questionId,
                    firstText(response.get("markdown"), response.get("standardizedMarkdown")),
                    aiAnswer(response),
                    aiAnalysis(response),
                    response
            );
            response.put("writeResult", true);
            response.put("writeDecision", "applied");
        } else if (writeRequested) {
            markStandardizeWriteSkipped(response);
        } else {
            markStandardizeCandidateOnly(response);
        }
        response.put("question", importQuestionService.toMap(requireImportQuestion(taskId, questionId)));
        return response;
    }

    /**
     * 对导入题执行 AI 解析并回写答案/解析。
     *
     * @param taskId 导入任务 ID
     * @param questionId 导入题 ID
     * @param payload 请求载荷
     * @return AI 响应及更新后的题目快照
     */
    public Map<String, Object> analyzeImportQuestion(String taskId, String questionId, Map<String, Object> payload) {
        ImportQuestionEntity question = requireImportQuestion(taskId, questionId);
        Map<String, Object> request = analysisRequest(payload, importQuestionService.toMap(question));
        Map<String, Object> response = executeAiJob("import-question", questionId, "analysis", "/worker/ai/analysis", request, true);
        importQuestionService.updateAiResult(
                taskId,
                questionId,
                text(response.get("analysis")),
                firstText(response.get("answer"), response.get("suggestedAnswer")),
                response
        );
        response.put("question", importQuestionService.toMap(requireImportQuestion(taskId, questionId)));
        return response;
    }

    /**
     * 对题库题执行 AI 标准化。
     *
     * @param questionId 题库题 ID
     * @param payload 请求载荷
     * @return AI 响应及题库题快照
     */
    public Map<String, Object> standardizeBankQuestion(String questionId, Map<String, Object> payload) {
        BankQuestionEntity question = bankQuestionService.required(questionId);
        Map<String, Object> request = standardizeRequest(payload, bankRawContext(question), bankHints(question));
        boolean writeRequested = standardizeWriteRequested(payload);
        Map<String, Object> response = executeAiJob("bank-question", questionId, "standardize", "/worker/ai/standardize", request, false);
        if (writeRequested && standardizeWriteAllowed(response)) {
            bankQuestionService.updateStandardizedResult(
                    questionId,
                    firstText(response.get("markdown"), response.get("standardizedMarkdown")),
                    aiAnswer(response),
                    aiAnalysis(response),
                    response
            );
            response.put("writeResult", true);
        } else if (writeRequested) {
            markStandardizeWriteSkipped(response);
        } else {
            markStandardizeCandidateOnly(response);
        }
        response.put("question", bankQuestionService.get(questionId));
        return response;
    }

    /**
     * 对题库题执行 AI 解析并回写答案/解析。
     *
     * @param questionId 题库题 ID
     * @param payload 请求载荷
     * @return AI 响应及更新后的题库题快照
     */
    public Map<String, Object> analyzeBankQuestion(String questionId, Map<String, Object> payload) {
        Map<String, Object> question = bankQuestionService.get(questionId);
        Map<String, Object> request = analysisRequest(payload, question);
        Map<String, Object> response = executeAiJob("bank-question", questionId, "analysis", "/worker/ai/analysis", request, true);
        bankQuestionService.updateAiResult(
                questionId,
                text(response.get("analysis")),
                firstText(response.get("answer"), response.get("suggestedAnswer")),
                response
        );
        response.put("question", bankQuestionService.get(questionId));
        return response;
    }

    /**
     * 对临时 Markdown 执行 AI 标准化，不回写任何题目。
     *
     * @param payload 请求载荷
     * @return AI 标准化响应
     */
    public Map<String, Object> standardizeAdHoc(Map<String, Object> payload) {
        return executeAiJob("ad-hoc", "markdown", "standardize", "/worker/ai/standardize", standardizeRequest(payload, "", Map.of()), false);
    }

    /**
     * 对临时题目内容执行 AI 解析，不回写任何题目。
     *
     * @param payload 请求载荷
     * @return AI 解析响应
     */
    public Map<String, Object> analyzeAdHoc(Map<String, Object> payload) {
        return executeAiJob("ad-hoc", "analysis", "analysis", "/worker/ai/analysis", analysisRequest(payload, Map.of()), true);
    }

    /**
     * 查询 AI job 列表。
     *
     * @param targetType 目标类型过滤
     * @param targetId 目标 ID 过滤
     * @return AI job 列表响应
     */
    public Map<String, Object> listJobs(String targetType, String targetId) {
        QueryWrapper<AiJobEntity> query = new QueryWrapper<AiJobEntity>().orderByDesc("created_at");
        if (targetType != null && !targetType.isBlank()) {
            query.eq("target_type", targetType);
        }
        if (targetId != null && !targetId.isBlank()) {
            query.eq("target_id", targetId);
        }
        List<Map<String, Object>> items = mapper.selectList(query).stream().map(this::toMap).toList();
        return Map.of("items", items, "total", items.size());
    }

    /**
     * 查询单个 AI job。
     *
     * @param jobId AI job ID
     * @return AI job 响应 Map
     */
    public Map<String, Object> getJob(String jobId) {
        AiJobEntity job = mapper.selectById(jobId);
        if (job == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "AI job not found");
        }
        return toMap(job);
    }

    /**
     * 创建、执行并更新 AI job。
     *
     * @param targetType 目标类型
     * @param targetId 目标 ID
     * @param operation AI 操作
     * @param workerPath worker 接口路径
     * @param request worker 请求体
     * @param writeResult 是否会写回业务实体
     * @return worker 响应
     */
    private Map<String, Object> executeAiJob(
            String targetType,
            String targetId,
            String operation,
            String workerPath,
            Object request,
            boolean writeResult
    ) {
        AiJobEntity job = createJob(targetType, targetId, operation, request);
        try {
            Map<String, Object> response = pythonWorkerClient.postJson(workerPath, request);
            job.setStatus("success");
            job.setResponseJson(json.write(response));
            job.setUpdatedAt(LocalDateTime.now());
            mapper.updateById(job);
            response.put("aiJobId", job.getId());
            response.put("writeResult", writeResult);
            return response;
        } catch (RuntimeException ex) {
            job.setStatus("failed");
            job.setFailureReason(ex.getMessage());
            job.setUpdatedAt(LocalDateTime.now());
            mapper.updateById(job);
            throw ex;
        }
    }

    /**
     * 创建运行中的 AI job 记录。
     *
     * @param targetType 目标类型
     * @param targetId 目标 ID
     * @param operation AI 操作
     * @param request 原始请求体
     * @return 新建 job 实体
     */
    private AiJobEntity createJob(String targetType, String targetId, String operation, Object request) {
        LocalDateTime now = LocalDateTime.now();
        AiJobEntity job = new AiJobEntity();
        job.setId(Ids.next("ai_job"));
        job.setTargetType(targetType);
        job.setTargetId(targetId);
        job.setOperation(operation);
        job.setStatus("running");
        job.setRetryCount(0);
        job.setRequestJson(json.write(redactInlineImageData(request)));
        job.setCreatedAt(now);
        job.setUpdatedAt(now);
        mapper.insert(job);
        return job;
    }

    /**
     * 校验并读取导入题实体。
     *
     * @param taskId 导入任务 ID
     * @param questionId 导入题 ID
     * @return 导入题实体
     */
    private ImportQuestionEntity requireImportQuestion(String taskId, String questionId) {
        ImportQuestionEntity question = importQuestionService.getQuestion(questionId);
        if (question == null || !taskId.equals(question.getTaskId())) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Import question not found");
        }
        return question;
    }

    /**
     * 构造 AI 标准化请求。
     *
     * @param payload 原始请求载荷
     * @param rawOcrContext OCR 原始上下文
     * @param hints 结构化提示信息
     * @return worker 请求 Map
     */
    private Map<String, Object> standardizeRequest(Map<String, Object> payload, String rawOcrContext, Map<String, Object> hints) {
        Map<String, Object> request = new LinkedHashMap<>();
        request.put("markdown", text(payload.get("markdown")));
        request.put("rawOcrContext", rawOcrContext);
        request.put("structuredHints", hints);
        return request;
    }

    /**
     * 构造 AI 解析请求。
     *
     * @param payload 原始请求载荷
     * @param fallbackQuestion 题目快照兜底字段
     * @return worker 请求 Map
     */
    private Map<String, Object> analysisRequest(Map<String, Object> payload, Map<String, Object> fallbackQuestion) {
        Map<String, Object> request = new LinkedHashMap<>();
        request.put("manualMarkdown", firstText(payload.get("manualMarkdown"), fallbackQuestion.get("manualMarkdown"), fallbackQuestion.get("stemMarkdown")));
        request.put("answer", firstText(payload.get("answer"), fallbackQuestion.get("answer")));
        request.put("type", firstText(payload.get("type"), fallbackQuestion.get("type"), "unknown"));
        request.put("knowledgePoints", payload.get("knowledgePoints") == null ? fallbackQuestion.getOrDefault("knowledgePoints", List.of()) : payload.get("knowledgePoints"));
        request.put("images", aiImages(payload.get("images") == null ? fallbackQuestion.getOrDefault("images", List.of()) : payload.get("images")));
        request.put("subQuestions", payload.get("subQuestions") == null ? fallbackSubQuestions(fallbackQuestion) : payload.get("subQuestions"));
        return request;
    }

    /**
     * 从题目快照中读取小问数组。
     *
     * @param question 题目快照
     * @return subQuestions 或 children
     */
    private Object fallbackSubQuestions(Map<String, Object> question) {
        Object subQuestions = question.get("subQuestions");
        if (subQuestions instanceof List<?> list && !list.isEmpty()) {
            return subQuestions;
        }
        Object children = question.get("children");
        return children == null ? List.of() : children;
    }

    /**
     * 将题图列表转换为 AI worker 可消费的图片上下文。
     *
     * @param value 原始题图列表
     * @return 已附加 data URL 或跳过原因的题图列表
     */
    private List<Map<String, Object>> aiImages(Object value) {
        if (!(value instanceof List<?> images)) {
            return List.of();
        }
        List<Map<String, Object>> result = new ArrayList<>();
        for (Object item : images) {
            if (result.size() >= MAX_AI_IMAGE_COUNT) {
                break;
            }
            if (!(item instanceof Map<?, ?> raw)) {
                continue;
            }
            Map<String, Object> image = new LinkedHashMap<>();
            raw.forEach((key, imageValue) -> image.put(String.valueOf(key), imageValue));
            attachImageDataUrl(image);
            result.add(image);
        }
        return result;
    }

    /**
     * 为单张题图附加 data URL。
     *
     * <p>优先使用 Java 文件存储记录；如果是历史 worker 路径，则尝试通过 worker 取回图片。
     * 无法读取或超过大小限制时只标记跳过原因，不中断整个 AI 请求。</p>
     *
     * @param image 题图 Map
     */
    private void attachImageDataUrl(Map<String, Object> image) {
        if (!text(image.get("imageDataUrl")).isBlank() || !text(image.get("dataUrl")).isBlank()) {
            return;
        }
        StorageFileEntity file = fileStorageService.findById(imageStorageFileId(image));
        if (file == null) {
            if (attachWorkerImageDataUrl(image)) {
                return;
            }
            image.put("aiImageIncluded", false);
            image.put("aiImageSkipReason", "storage file not found");
            return;
        }
        if (!isQuestionImage(file)) {
            image.put("aiImageIncluded", false);
            image.put("aiImageSkipReason", "storage file is not a question image");
            return;
        }
        if (file.getSizeBytes() != null && file.getSizeBytes() > MAX_AI_IMAGE_BYTES) {
            image.put("aiImageIncluded", false);
            image.put("aiImageSkipReason", "image is larger than " + MAX_AI_IMAGE_BYTES + " bytes");
            return;
        }
        byte[] bytes;
        try {
            bytes = fileStorageService.readBytes(file);
        } catch (RuntimeException ex) {
            image.put("aiImageIncluded", false);
            image.put("aiImageSkipReason", "storage image not readable: " + ex.getMessage());
            return;
        }
        String contentType = detectedImageContentType(bytes);
        if (contentType.isBlank()) {
            image.put("aiImageIncluded", false);
            image.put("aiImageSkipReason", "image bytes are not a supported image format");
            return;
        }
        image.put("imageDataUrl", "data:" + contentType + ";base64," + Base64.getEncoder().encodeToString(bytes));
        image.put("contentType", contentType);
        image.put("aiImageIncluded", true);
    }

    /**
     * 从 worker 历史图片路径读取图片并附加 data URL。
     *
     * @param image 题图 Map
     * @return true 表示成功附加图片数据
     */
    private boolean attachWorkerImageDataUrl(Map<String, Object> image) {
        String path = firstText(image.get("url"), image.get("path"));
        if (!isWorkerImagePath(path)) {
            return false;
        }
        try {
            ResponseEntity<byte[]> response = pythonWorkerClient.getFile(path);
            byte[] bytes = response.getBody() == null ? new byte[0] : response.getBody();
            if (bytes.length == 0 || bytes.length > MAX_AI_IMAGE_BYTES) {
                image.put("aiImageSkipReason", "worker image is empty or too large");
                return false;
            }
            MediaType contentType = response.getHeaders().getContentType();
            String mediaType = detectedImageContentType(bytes);
            if (mediaType.isBlank()) {
                image.put("aiImageSkipReason", "worker image bytes are not a supported image format");
                return false;
            }
            if (contentType != null && contentType.toString().startsWith("image/")) {
                mediaType = contentType.toString();
            }
            image.put("imageDataUrl", "data:" + mediaType + ";base64," + Base64.getEncoder().encodeToString(bytes));
            image.put("contentType", mediaType);
            image.put("aiImageIncluded", true);
            return true;
        } catch (RuntimeException ex) {
            image.put("aiImageSkipReason", "worker image not readable: " + ex.getMessage());
            return false;
        }
    }

    /**
     * 判断路径是否属于允许 worker 回读的图片接口。
     *
     * @param path 图片路径
     * @return true 表示可通过 worker/client 回读
     */
    private boolean isWorkerImagePath(String path) {
        return path.startsWith("/api/ocr/jobs/")
                || path.startsWith("/api/import-tasks/")
                || path.startsWith("/api/question-bank/questions/");
    }

    /**
     * 根据图片魔数识别 AI 可消费的图片类型。
     *
     * @param bytes 图片字节
     * @return MIME 类型；无法识别时返回空字符串
     */
    private String detectedImageContentType(byte[] bytes) {
        if (startsWith(bytes, 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A)) {
            return "image/png";
        }
        if (startsWith(bytes, 0xFF, 0xD8, 0xFF)) {
            return "image/jpeg";
        }
        if (startsWith(bytes, 0x47, 0x49, 0x46, 0x38, 0x37, 0x61)
                || startsWith(bytes, 0x47, 0x49, 0x46, 0x38, 0x39, 0x61)) {
            return "image/gif";
        }
        if (bytes != null
                && bytes.length >= 12
                && bytes[0] == 0x52
                && bytes[1] == 0x49
                && bytes[2] == 0x46
                && bytes[3] == 0x46
                && bytes[8] == 0x57
                && bytes[9] == 0x45
                && bytes[10] == 0x42
                && bytes[11] == 0x50) {
            return "image/webp";
        }
        return "";
    }

    /**
     * 判断字节数组是否以指定无符号字节序列开头。
     *
     * @param bytes 字节数组
     * @param prefix 前缀
     * @return true 表示匹配
     */
    private boolean startsWith(byte[] bytes, int... prefix) {
        if (bytes == null || bytes.length < prefix.length) {
            return false;
        }
        for (int i = 0; i < prefix.length; i++) {
            if ((bytes[i] & 0xFF) != prefix[i]) {
                return false;
            }
        }
        return true;
    }

    /**
     * 从题图 Map 中解析 Java 存储文件 ID。
     *
     * @param image 题图 Map
     * @return 存储文件 ID；不存在时返回空字符串
     */
    private String imageStorageFileId(Map<String, Object> image) {
        String explicit = firstText(image.get("storageFileId"), image.get("fileId"), image.get("id"), image.get("imageId"));
        if (!explicit.isBlank()) {
            return explicit;
        }
        String path = text(image.get("path"));
        if (path.startsWith("java-storage/")) {
            return path.substring("java-storage/".length()).trim();
        }
        return "";
    }

    /**
     * 判断存储文件是否属于题图业务类型。
     *
     * @param file 存储文件实体
     * @return true 表示可作为 AI 题图上下文
     */
    private boolean isQuestionImage(StorageFileEntity file) {
        return JavaFileStorageService.BUSINESS_IMPORT_QUESTION_IMAGE.equals(file.getBusinessType())
                || JavaFileStorageService.BUSINESS_BANK_QUESTION_IMAGE.equals(file.getBusinessType());
    }

    /**
     * 递归脱敏 AI job 请求中的内联图片数据。
     *
     * @param value 原始请求值
     * @return 脱敏后的值
     */
    @SuppressWarnings("unchecked")
    private Object redactInlineImageData(Object value) {
        if (value instanceof Map<?, ?> raw) {
            Map<String, Object> redacted = new LinkedHashMap<>();
            raw.forEach((key, item) -> {
                String name = String.valueOf(key);
                redacted.put(name, isInlineImageDataKey(name) ? "[redacted inline image data]" : redactInlineImageData(item));
            });
            return redacted;
        }
        if (value instanceof List<?> list) {
            return list.stream().map(this::redactInlineImageData).toList();
        }
        return value;
    }

    /**
     * 判断字段名是否表示内联图片数据。
     *
     * @param key 字段名
     * @return true 表示需要脱敏
     */
    private boolean isInlineImageDataKey(String key) {
        return "imageDataUrl".equals(key) || "dataUrl".equals(key);
    }

    /**
     * 构造导入题标准化提示信息。
     *
     * @param question 导入题实体
     * @return 结构化提示 Map
     */
    private Map<String, Object> importHints(ImportQuestionEntity question) {
        return Map.of(
                "questionId", question.getId(),
                "type", value(question.getType()),
                "answer", value(question.getAnswer()),
                "knowledgePoints", json.readList(question.getKnowledgePointsJson()),
                "images", json.readList(question.getImagesJson()),
                "subQuestions", json.readList(question.getChildrenJson())
        );
    }

    /**
     * 构造题库题标准化提示信息。
     *
     * @param question 题库题实体
     * @return 结构化提示 Map
     */
    private Map<String, Object> bankHints(BankQuestionEntity question) {
        return Map.of(
                "questionId", question.getId(),
                "type", value(question.getType()),
                "answer", value(question.getAnswer()),
                "knowledgePoints", json.readList(question.getKnowledgePointsJson()),
                "images", json.readList(question.getImagesJson()),
                "subQuestions", json.readList(question.getChildrenJson())
        );
    }

    /**
     * 构造导入题 OCR 原始上下文。
     *
     * @param question 导入题实体
     * @return 多段上下文拼接文本
     */
    private String importRawContext(ImportQuestionEntity question) {
        Map<String, Object> raw = json.readMap(question.getRawJson());
        return joinContext(
                value(raw.get("rawOcrContext")),
                sameQuestionRawOcrContext(question),
                value(raw.get("stemMarkdown")),
                value(question.getStemMarkdown()));
    }

    /**
     * 构造题库题原始上下文。
     *
     * @param question 题库题实体
     * @return 多段上下文拼接文本
     */
    private String bankRawContext(BankQuestionEntity question) {
        String sourceRawContext = "";
        if (!value(question.getSourceImportTaskId()).isBlank()) {
            ImportQuestionEntity sourceQuestion = importQuestionService.getQuestion(question.getSourceImportQuestionId());
            if (sourceQuestion != null) {
                sourceRawContext = sameQuestionRawOcrContext(sourceQuestion);
            } else {
                sourceRawContext = sameQuestionRawOcrContext(
                        question.getSourceImportTaskId(),
                        question.getQuestionNumber());
            }
        }
        return joinContext(
                sourceRawContext,
                value(question.getSource()),
                value(question.getStemMarkdown()));
    }

    /**
     * 判断请求是否显式要求把 AI 标准化结果写回题目。
     *
     * <p>旧版 AI 标准化的默认行为是候选预览，避免模型输出在人工复核前污染编辑内容。
     * 因此只有请求显式传入 {@code writeResult=true} 或 {@code apply=true} 才进入写回流程。</p>
     *
     * @param payload 请求载荷
     * @return true 表示调用方要求写回
     */
    private boolean standardizeWriteRequested(Map<String, Object> payload) {
        return booleanValue(payload.get("writeResult")) || booleanValue(payload.get("apply"));
    }

    /**
     * 判断 AI 标准化响应是否允许写回题干。
     *
     * <p>worker 会在 standardizer 内返回修复后残留的严重 LaTeX 风险和模型置信度。只要修复后
     * 仍有严重风险，或模型明确低置信，就保留原题干，仅记录 AI job 和响应。</p>
     *
     * @param response worker 标准化响应
     * @return true 表示可以写回
     */
    private boolean standardizeWriteAllowed(Map<String, Object> response) {
        Map<String, Object> standardizer = mapValue(response.get("standardizer"));
        String recommendation = value(response.get("applyRecommendation"));
        String confidence = value(standardizer.get("confidence")).toLowerCase(java.util.Locale.ROOT);
        Map<String, Object> renderValidation = mapValue(standardizer.get("renderValidation"));
        boolean renderInvalid = renderValidation.containsKey("valid") && !booleanValue(renderValidation.get("valid"));
        return (recommendation.isBlank() || "safe_to_apply".equals(recommendation))
                && !"low".equals(confidence)
                && listValue(standardizer.get("candidateSevereIssues")).isEmpty()
                && !Boolean.TRUE.equals(standardizer.get("writeBlocked"))
                && !Boolean.TRUE.equals(standardizer.get("applyBlocked"))
                && !renderInvalid;
    }

    /**
     * 在响应中标记标准化结果仅作为候选返回。
     *
     * @param response worker 标准化响应
     */
    private void markStandardizeCandidateOnly(Map<String, Object> response) {
        response.put("writeResult", false);
        response.put("writeDecision", "candidate");
        response.put("writeSkippedReason", "AI 标准化结果已作为候选返回，等待人工预览后应用保存");
    }

    /**
     * 在响应中标记标准化结果未写回。
     *
     * @param response worker 标准化响应
     */
    private void markStandardizeWriteSkipped(Map<String, Object> response) {
        response.put("writeResult", false);
        response.put("writeDecision", "review_required");
        response.put("writeSkippedReason", "AI 标准化结果低置信、仍存在严重 LaTeX 风险或渲染安全校验失败，已保留原题干");
    }

    /**
     * 构造导入题同题原始 OCR 上下文。
     *
     * @param question 导入题
     * @return 同题 OCR 片段；无法读取时为空
     */
    private String sameQuestionRawOcrContext(ImportQuestionEntity question) {
        return sameQuestionRawOcrContext(question.getTaskId(), question.getQuestionNumber());
    }

    /**
     * 构造指定任务和题号的原始 OCR 上下文。
     *
     * @param taskId 导入任务 ID
     * @param questionNumber 题号
     * @return 同题 OCR 片段；无法读取时为空
     */
    private String sameQuestionRawOcrContext(String taskId, Integer questionNumber) {
        if (taskId == null || taskId.isBlank()) {
            return "";
        }
        ImportTaskEntity task = importTaskMetadataService.getEntity(taskId);
        if (task == null || value(task.getPaperOcrJobId()).isBlank()) {
            return "";
        }
        try {
            Map<String, Object> outputs = pythonWorkerClient.getJson("/api/ocr/jobs/" + task.getPaperOcrJobId() + "/result");
            return extractRawOcrContext(value(outputs.get("markdown")), questionNumber);
        } catch (RuntimeException ex) {
            return "";
        }
    }

    /**
     * 从 OCR 整稿中按题号截取同题上下文。
     *
     * @param rawMarkdown OCR 整稿 Markdown
     * @param questionNumber 题号
     * @return 同题片段；找不到时返回空
     */
    private String extractRawOcrContext(String rawMarkdown, Integer questionNumber) {
        if (rawMarkdown.isBlank() || questionNumber == null || questionNumber <= 0) {
            return "";
        }
        Matcher matcher = Pattern.compile("(?m)(?:^|\\n)\\s*(\\d{1,3})\\s*[\\.．、)]").matcher(rawMarkdown);
        List<MatcherSnapshot> starts = new ArrayList<>();
        while (matcher.find()) {
            starts.add(new MatcherSnapshot(matcher.start(), Integer.parseInt(matcher.group(1))));
        }
        for (int index = 0; index < starts.size(); index++) {
            MatcherSnapshot current = starts.get(index);
            if (current.number() != questionNumber) {
                continue;
            }
            int end = rawMarkdown.length();
            for (int nextIndex = index + 1; nextIndex < starts.size(); nextIndex++) {
                MatcherSnapshot next = starts.get(nextIndex);
                if (next.number() > questionNumber) {
                    end = next.start();
                    break;
                }
            }
            String context = rawMarkdown.substring(current.start(), end).trim();
            return context.length() > 6000 ? context.substring(0, 6000) : context;
        }
        return "";
    }

    /**
     * 合并上下文片段并去重。
     *
     * @param parts 上下文片段
     * @return 合并后的文本
     */
    private String joinContext(String... parts) {
        Set<String> seen = new LinkedHashSet<>();
        for (String part : parts) {
            if (part != null && !part.isBlank()) {
                seen.add(part.strip());
            }
        }
        return String.join("\n\n", seen);
    }

    /**
     * 将 AI job 实体序列化为 API 响应 Map。
     *
     * @param job AI job 实体
     * @return 响应 Map
     */
    private Map<String, Object> toMap(AiJobEntity job) {
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("id", job.getId());
        item.put("targetType", job.getTargetType());
        item.put("targetId", job.getTargetId());
        item.put("operation", job.getOperation());
        item.put("status", job.getStatus());
        item.put("retryCount", job.getRetryCount());
        item.put("failureReason", job.getFailureReason());
        item.put("request", json.readMap(job.getRequestJson()));
        item.put("response", json.readMap(job.getResponseJson()));
        item.put("createdAt", job.getCreatedAt());
        item.put("updatedAt", job.getUpdatedAt());
        return item;
    }

    /**
     * 返回首个非空文本。
     *
     * @param values 候选值
     * @return 首个非空文本；不存在时返回空字符串
     */
    private String firstText(Object... values) {
        for (Object value : values) {
            String text = text(value);
            if (!text.isBlank()) {
                return text;
            }
        }
        return "";
    }

    /**
     * 从 AI 响应中提取答案。
     *
     * @param response AI 响应
     * @return 答案文本
     */
    private String aiAnswer(Map<String, Object> response) {
        return firstText(
                response.get("answer"),
                response.get("suggestedAnswer"),
                nestedText(response.get("metadata"), "answer"),
                nestedText(response.get("standardizer"), "answer")
        );
    }

    /**
     * 从 AI 响应中提取解析。
     *
     * @param response AI 响应
     * @return 解析文本
     */
    private String aiAnalysis(Map<String, Object> response) {
        return firstText(
                response.get("analysis"),
                response.get("explanation"),
                nestedText(response.get("metadata"), "analysis"),
                nestedText(response.get("metadata"), "explanation"),
                nestedText(response.get("standardizer"), "analysis"),
                nestedText(response.get("standardizer"), "explanation")
        );
    }

    /**
     * 从嵌套 Map 中提取文本字段。
     *
     * @param value 嵌套对象
     * @param key 字段名
     * @return 文本值；不存在时返回空字符串
     */
    private String nestedText(Object value, String key) {
        if (value instanceof Map<?, ?> map) {
            return text(map.get(key));
        }
        return "";
    }

    /**
     * 将对象转换为去首尾空白文本。
     *
     * @param value 原始值
     * @return 文本；null 返回空字符串
     */
    private String text(Object value) {
        return value == null ? "" : String.valueOf(value).trim();
    }

    /**
     * 兼容 Map.of 中需要 Object 输入的文本转换。
     *
     * @param value 原始值
     * @return 文本；null 返回空字符串
     */
    private String value(Object value) {
        return text(value);
    }

    /**
     * 将对象转换为布尔开关。
     *
     * @param value 原始值
     * @return true 表示显式开启
     */
    private boolean booleanValue(Object value) {
        if (value instanceof Boolean bool) {
            return bool;
        }
        String text = text(value);
        return "true".equalsIgnoreCase(text) || "1".equals(text) || "yes".equalsIgnoreCase(text);
    }

    /**
     * 将对象按 Map 读取。
     *
     * @param value 原始值
     * @return Map；类型不匹配时为空 Map
     */
    private Map<String, Object> mapValue(Object value) {
        Map<String, Object> result = new LinkedHashMap<>();
        if (value instanceof Map<?, ?> map) {
            map.forEach((key, item) -> result.put(String.valueOf(key), item));
        }
        return result;
    }

    /**
     * 将对象按列表读取。
     *
     * @param value 原始值
     * @return 列表；类型不匹配时为空列表
     */
    private List<?> listValue(Object value) {
        return value instanceof List<?> list ? list : List.of();
    }

    /**
     * OCR 整稿中题号位置快照。
     *
     * @param start 题号起始位置
     * @param number 题号
     */
    private record MatcherSnapshot(int start, int number) {
    }
}
