package com.aigeneration.questionbank.capability.service;

import com.aigeneration.questionbank.capability.model.QuestionProcessingCapabilityModels.CapabilityDescriptor;
import com.aigeneration.questionbank.capability.model.QuestionProcessingCapabilityModels.MathValidationIssue;
import com.aigeneration.questionbank.capability.model.QuestionProcessingCapabilityModels.MathValidationView;
import com.aigeneration.questionbank.capability.model.QuestionProcessingCapabilityModels.OcrStatusView;
import com.aigeneration.questionbank.capability.model.QuestionProcessingCapabilityModels.QuestionChild;
import com.aigeneration.questionbank.capability.model.QuestionProcessingCapabilityModels.QuestionOption;
import com.aigeneration.questionbank.capability.model.QuestionProcessingCapabilityModels.ProcessedQuestion;
import com.aigeneration.questionbank.capability.model.QuestionProcessingCapabilityModels.ProcessingJobView;
import com.aigeneration.questionbank.capability.model.QuestionProcessingCapabilityModels.ProcessingWarning;
import com.aigeneration.questionbank.capability.model.QuestionProcessingCapabilityModels.QuestionImage;
import com.aigeneration.questionbank.capability.model.QuestionProcessingCapabilityModels.QuestionPackage;
import com.aigeneration.questionbank.capability.model.QuestionProcessingCapabilityModels.SourceEvidence;
import com.aigeneration.questionbank.capability.model.QuestionProcessingCapabilityModels.SourceFileView;
import com.aigeneration.questionbank.domain.entity.ImportQuestionEntity;
import com.aigeneration.questionbank.domain.entity.ImportQuestionImageEntity;
import com.aigeneration.questionbank.domain.entity.ImportTaskEntity;
import com.aigeneration.questionbank.domain.service.ImportQuestionSyncService;
import com.aigeneration.questionbank.domain.service.ImportTaskMetadataBridgeService;
import com.aigeneration.questionbank.domain.service.ImportTaskMetadataService;
import com.aigeneration.questionbank.domain.support.JsonSupport;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

/**
 * Question Processing 主能力服务。
 *
 * <p>该服务把导入任务、OCR 结果、题目同步表和题图表组合成平台可消费的标准题目包，
 * 同时提供创建加工任务、查询任务状态和输出数据包的能力入口。</p>
 */
@Service
public class QuestionProcessingCapabilityService {
    /**
     * 主能力稳定编码，供能力目录、SDK 和下游平台识别。
     */
    public static final String CAPABILITY_CODE = "question-processing";

    /**
     * 标准题目包协议版本。
     */
    public static final String PACKAGE_VERSION = "question-package.v1";

    /**
     * 导入任务元数据服务，提供任务状态、OCR job 信息和文件元数据。
     */
    private final ImportTaskMetadataService taskService;

    /**
     * 题目同步服务，提供导入任务下的题目、题图和结构化内容。
     */
    private final ImportQuestionSyncService questionService;

    /**
     * 兼容旧导入接口的桥接服务，用于创建真实加工任务。
     */
    private final ImportTaskMetadataBridgeService bridgeService;

    /**
     * JSON 辅助组件，用于读取实体中的 JSON 字符串字段。
     */
    private final JsonSupport json;

    /**
     * 注入主能力需要聚合的任务、题目、桥接和 JSON 服务。
     *
     * @param taskService 导入任务元数据服务
     * @param questionService 导入题目同步服务
     * @param bridgeService 导入任务桥接服务
     * @param json JSON 辅助组件
     */
    public QuestionProcessingCapabilityService(
            ImportTaskMetadataService taskService,
            ImportQuestionSyncService questionService,
            ImportTaskMetadataBridgeService bridgeService,
            JsonSupport json
    ) {
        this.taskService = taskService;
        this.questionService = questionService;
        this.bridgeService = bridgeService;
        this.json = json;
    }

    /**
     * 返回主能力描述。
     *
     * <p>描述包含输入要求、输出类型、Java/worker 端点以及平台侧必须承接的用户、租户、
     * 权限和最终入库边界。</p>
     *
     * @return question-processing 能力描述
     */
    public CapabilityDescriptor descriptor() {
        return new CapabilityDescriptor(
                CAPABILITY_CODE,
                "试卷到标准题目数据包加工能力",
                "接收试卷/答案文件，执行 OCR、拆题、AI 标准化/解析、人工校验，并输出平台可消费的标准题目包；不承载用户、权限、最终题库入库和审核流。",
                PACKAGE_VERSION,
                List.of("paperFile", "answerFile?", "stage", "subject", "grade", "region", "year", "title"),
                List.of("processingJob", "questionPackage", "sourceFilePreview", "markdown/docx/pdf export"),
	                Map.of(
	                        "createJob", "/api/capabilities/question-processing/jobs",
	                        "listJobs", "/api/capabilities/question-processing/jobs",
	                        "getJob", "/api/capabilities/question-processing/jobs/{jobId}",
	                        "questionPackage", "/api/capabilities/question-processing/jobs/{jobId}/question-package",
	                        "ocrFlowCapability", "/api/capabilities/ocr-flow",
	                        "legacyWorkbench", "/api/import-tasks/{jobId}"
	                ),
	                List.of("/worker/ocr-flow", "/worker/ocr", "/worker/ai/standardize", "/worker/ai/analysis", "/worker/export"),
	                List.of("user", "tenant", "permission", "knowledge-master-data", "final-question-bank", "review-flow")
	        );
	    }

    /**
     * 查询所有已同步的加工任务并转换成能力层任务视图。
     *
     * @return 加工任务视图列表
     */
    public List<ProcessingJobView> listJobs() {
        return taskService.listEntities().stream()
                .map(this::jobView)
                .toList();
    }

    /**
     * 创建新的题目加工任务。
     *
     * <p>创建逻辑复用导入任务桥接服务，确保上传文件、OCR 触发和 Java 表同步流程保持一致。</p>
     *
     * @param stage 学段
     * @param subject 学科
     * @param grade 年级
     * @param region 地区
     * @param year 年份
     * @param title 任务标题
     * @param paperFile 试卷文件
     * @param answerFile 答案文件，可为空
     * @return 创建后的加工任务视图
     */
    public ProcessingJobView createJob(
            String stage,
            String subject,
            String grade,
            String region,
            String year,
            String title,
            MultipartFile paperFile,
            MultipartFile answerFile
    ) {
        Map<String, Object> response = bridgeService.create(stage, subject, grade, region, year, title, paperFile, answerFile);
        return getJob(text(response.get("id")));
    }

    /**
     * 根据任务 ID 查询加工任务视图。
     *
     * @param jobId 加工任务 ID
     * @return 加工任务视图
     */
    public ProcessingJobView getJob(String jobId) {
        return jobView(synchronizedTask(jobId));
    }

    /**
     * 生成标准题目包。
     *
     * <p>题目包包含任务视图、已处理题目、题图、公式校验信息、来源证据和加工告警。任务失败
     * 或尚未产生题目时会在 warnings 中体现，避免调用方只能通过异常判断业务状态。</p>
     *
     * @param jobId 加工任务 ID
     * @return 标准题目包
     */
    public QuestionPackage questionPackage(String jobId) {
        ImportTaskEntity task = synchronizedTask(jobId);
        List<ProcessedQuestion> questions = questionService.listByTask(jobId).stream()
                .map(this::processedQuestion)
                .toList();
        List<ProcessingWarning> warnings = new ArrayList<>();
        if (!text(task.getFailureReason()).isBlank()) {
            warnings.add(new ProcessingWarning("JOB_FAILURE_REASON", task.getFailureReason(), task.getId()));
        }
        if (questions.isEmpty()) {
            warnings.add(new ProcessingWarning("EMPTY_QUESTION_PACKAGE", "当前加工任务尚未形成可输出题目。", task.getId()));
        }
        return new QuestionPackage(PACKAGE_VERSION, CAPABILITY_CODE, jobView(task), questions, warnings);
    }

    /**
     * 校验并读取加工任务实体。
     *
     * @param jobId 加工任务 ID
     * @return 导入任务实体
     */
    private ImportTaskEntity requiredTask(String jobId) {
        if (jobId == null || jobId.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Processing job id is required");
        }
        ImportTaskEntity task = taskService.getEntity(jobId);
        if (task == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Processing job not found");
        }
        return task;
    }

    /**
     * 查询 worker 最新任务状态并同步 Java 表。
     *
     * <p>question-processing 是平台轮询入口，不能只读取创建时的 Java 快照。这里复用导入
     * 任务 bridge 的 GET，同步 OCR job、题目列表和任务状态后，再读取 Java 侧标准视图。</p>
     *
     * @param jobId 加工任务 ID
     * @return 已同步后的导入任务实体
     */
    private ImportTaskEntity synchronizedTask(String jobId) {
        requiredTask(jobId);
        try {
            bridgeService.get(jobId);
        } catch (ResponseStatusException ex) {
            if (HttpStatus.NOT_FOUND.equals(ex.getStatusCode())) {
                throw ex;
            }
            // 允许平台在 worker 暂不可达时读取 Java 已同步快照；轮询场景下一次查询会再次尝试同步。
        }
        return requiredTask(jobId);
    }

    /**
     * 把导入任务实体转换成能力层任务视图。
     *
     * @param task 导入任务实体
     * @return 加工任务视图
     */
    private ProcessingJobView jobView(ImportTaskEntity task) {
        return new ProcessingJobView(
                task.getId(),
                text(task.getTitle()),
                text(task.getStage()),
                text(task.getSubject()),
                text(task.getGrade()),
                text(task.getRegion()),
                text(task.getYear()),
                text(task.getStatus()),
                processingStatus(task.getStatus()),
                text(task.getFailureReason()),
                task.getQuestionCount(),
                sourceFiles(task),
                new OcrStatusView("paper", text(task.getPaperOcrJobId()), text(task.getPaperOcrStatus()), json.readMap(task.getPaperOcrJobJson())),
                new OcrStatusView("answer", text(task.getAnswerOcrJobId()), text(task.getAnswerOcrStatus()), json.readMap(task.getAnswerOcrJobJson())),
                task.getCreatedAt(),
                task.getUpdatedAt()
        );
    }

    /**
     * 从任务元数据和 OCR job JSON 中提取原始文件预览入口。
     *
     * @param task 导入任务实体
     * @return 原始文件视图列表
     */
    private List<SourceFileView> sourceFiles(ImportTaskEntity task) {
        List<SourceFileView> files = new ArrayList<>();
        Map<String, Object> paperFile = json.readMap(task.getPaperFileJson());
        Map<String, Object> answerFile = json.readMap(task.getAnswerFileJson());
        String paperFilename = firstText(paperFile.get("filename"), json.readMap(task.getPaperOcrJobJson()).get("filename"));
        String answerFilename = firstText(answerFile.get("filename"), json.readMap(task.getAnswerOcrJobJson()).get("filename"));
        if (!paperFilename.isBlank() || !text(task.getPaperOcrJobId()).isBlank()) {
            files.add(new SourceFileView("paper", paperFilename, "/api/import-tasks/" + task.getId() + "/source/paper"));
        }
        if (!answerFilename.isBlank() || !text(task.getAnswerOcrJobId()).isBlank()) {
            files.add(new SourceFileView("answer", answerFilename, "/api/import-tasks/" + task.getId() + "/source/answer"));
        }
        return files;
    }

    /**
     * 把同步题目实体转换成标准题目包中的题目视图。
     *
     * @param question 导入题目实体
     * @return 标准处理题目
     */
    private ProcessedQuestion processedQuestion(ImportQuestionEntity question) {
        Map<String, Object> raw = json.readMap(question.getRawJson());
        Map<String, Object> mathValidationRaw = json.readMap(question.getMathValidationJson());
        MathValidationView mathValidation = mathValidation(mathValidationRaw);
        List<ProcessingWarning> warnings = questionWarnings(question, mathValidation);
        return new ProcessedQuestion(
                question.getId(),
                text(question.getSourceQuestionId()),
                question.getQuestionNumber(),
                text(question.getStatus()),
                text(question.getType()),
                preferredStem(question),
                text(question.getStemMarkdown()),
                text(question.getAnswer()),
                text(question.getAnalysis()),
                questionOptions(json.readList(question.getOptionsJson())),
                questionChildren(json.readList(question.getChildrenJson())),
                questionImages(question.getId()),
                mapList(json.readList(question.getImagePlacementsJson())),
                json.stringList(json.readList(question.getKnowledgePointIdsJson())),
                json.stringList(json.readList(question.getKnowledgePointsJson())),
                text(question.getDifficulty()),
                question.getScore(),
                mathValidation,
                warnings,
                sourceEvidence(question, raw),
                raw
        );
    }

    /**
     * 规范化题目选项结构。
     *
     * @param rawOptions 原始选项列表
     * @return 标准选项列表
     */
    private List<QuestionOption> questionOptions(List<Object> rawOptions) {
        List<QuestionOption> options = new ArrayList<>();
        for (Object rawOption : rawOptions) {
            Map<String, Object> raw = mapValue(rawOption);
            options.add(new QuestionOption(
                    firstText(raw.get("label"), raw.get("key"), raw.get("name"), raw.get("option")),
                    firstText(raw.get("contentMarkdown"), raw.get("markdown"), raw.get("text"), raw.get("content"), raw.get("value"), rawOption),
                    raw
            ));
        }
        return options;
    }

    /**
     * 规范化子题结构。
     *
     * @param rawChildren 原始子题列表
     * @return 标准子题列表
     */
    private List<QuestionChild> questionChildren(List<Object> rawChildren) {
        List<QuestionChild> children = new ArrayList<>();
        for (Object rawChild : rawChildren) {
            Map<String, Object> raw = mapValue(rawChild);
            children.add(new QuestionChild(
                    firstText(raw.get("childId"), raw.get("id")),
                    firstText(raw.get("sourceQuestionId"), raw.get("sourceId")),
                    integerValue(firstText(raw.get("number"), raw.get("index"))),
                    firstText(raw.get("stemMarkdown"), raw.get("markdown"), raw.get("stem"), raw.get("text")),
                    text(raw.get("answer")),
                    text(raw.get("analysis")),
                    questionOptions(listValue(raw.get("options"))),
                    rawImages(listValue(raw.get("images"))),
                    mapList(listValue(raw.get("imagePlacements"))),
                    raw
            ));
        }
        return children;
    }

    /**
     * 将通用 JSON 数组转换为 Map 列表，保留题图归属扩展字段。
     *
     * @param values 通用 JSON 数组
     * @return Map 列表
     */
    private List<Map<String, Object>> mapList(List<Object> values) {
        List<Map<String, Object>> result = new ArrayList<>();
        for (Object value : values) {
            Map<String, Object> mapped = mapValue(value);
            if (!mapped.isEmpty()) {
                result.add(mapped);
            }
        }
        return result;
    }

    /**
     * 查询题目的已保存题图并转换成标准题图视图。
     *
     * @param questionId 题目 ID
     * @return 标准题图列表
     */
    private List<QuestionImage> questionImages(String questionId) {
        return questionService.listImages(questionId).stream()
                .map(this::questionImage)
                .toList();
    }

    /**
     * 把原始 JSON 内嵌题图列表转换成标准题图视图。
     *
     * @param rawImages 原始题图列表
     * @return 标准题图列表
     */
    private List<QuestionImage> rawImages(List<Object> rawImages) {
        List<QuestionImage> images = new ArrayList<>();
        int index = 0;
        for (Object rawImage : rawImages) {
            Map<String, Object> raw = mapValue(rawImage);
            images.add(new QuestionImage(
                    firstText(raw.get("id"), raw.get("imageId")),
                    integerValue(firstText(raw.get("index"), raw.get("imageIndex"), index)),
                    firstText(raw.get("name"), raw.get("filename")),
                    text(raw.get("path")),
                    text(raw.get("url")),
                    raw
            ));
            index++;
        }
        return images;
    }

    /**
     * 把题图实体转换成题目包题图结构。
     *
     * @param image 题图实体
     * @return 标准题图视图
     */
    private QuestionImage questionImage(ImportQuestionImageEntity image) {
        return new QuestionImage(
                image.getId(),
                image.getImageIndex(),
                text(image.getName()),
                text(image.getPath()),
                text(image.getUrl()),
                json.readMap(image.getRawJson())
        );
    }

    /**
     * 汇总题目的来源证据信息。
     *
     * @param question 题目实体
     * @param raw 原始题目 JSON
     * @return 来源证据视图
     */
    private SourceEvidence sourceEvidence(ImportQuestionEntity question, Map<String, Object> raw) {
        Map<String, Object> evidence = new LinkedHashMap<>();
        evidence.put("processingJobId", question.getTaskId());
        evidence.put("sourceQuestionId", firstText(question.getSourceQuestionId(), raw.get("sourceQuestionId"), raw.get("id")));
        if (raw.containsKey("answerEvidence")) {
            evidence.put("answerEvidence", raw.get("answerEvidence"));
        }
        if (raw.containsKey("analysisEvidence")) {
            evidence.put("analysisEvidence", raw.get("analysisEvidence"));
        }
        if (raw.containsKey("rawOcrContextUsed")) {
            evidence.put("rawOcrContextUsed", raw.get("rawOcrContextUsed"));
        }
        return new SourceEvidence(
                question.getTaskId(),
                firstText(question.getSourceQuestionId(), raw.get("sourceQuestionId"), raw.get("id")),
                raw.get("answerEvidence"),
                raw.get("analysisEvidence"),
                booleanValue(raw.get("rawOcrContextUsed")),
                evidence
        );
    }

    /**
     * 规范化公式和 LaTeX 校验结果。
     *
     * @param raw 原始校验 JSON
     * @return 公式校验视图
     */
    private MathValidationView mathValidation(Map<String, Object> raw) {
        List<MathValidationIssue> issues = new ArrayList<>();
        for (Object item : listValue(firstPresent(raw, "issues", "warnings", "errors", "severeIssues", "candidateSevereIssues"))) {
            Map<String, Object> issue = mapValue(item);
            issues.add(new MathValidationIssue(
                    firstText(issue.get("code"), issue.get("type")),
                    firstText(issue.get("severity"), issue.get("level"), issue.get("status")),
                    firstText(issue.get("message"), issue.get("text"), item),
                    firstText(issue.get("field"), issue.get("target"), issue.get("path"))
            ));
        }
        String status = firstText(raw.get("status"), raw.get("level"), raw.get("severity"));
        if (status.isBlank()) {
            status = issues.isEmpty() ? "OK" : "REVIEW_REQUIRED";
        }
        return new MathValidationView(
                status,
                firstText(raw.get("summary"), raw.get("message")),
                issues,
                raw
        );
    }

    /**
     * 根据题目和公式校验状态生成题目级告警。
     *
     * @param question 题目实体
     * @param mathValidation 公式校验视图
     * @return 告警列表
     */
    private List<ProcessingWarning> questionWarnings(ImportQuestionEntity question, MathValidationView mathValidation) {
        List<ProcessingWarning> warnings = new ArrayList<>();
        String serialized = mathValidation.raw().toString();
        if (serialized.contains("warning")
                || serialized.contains("error")
                || serialized.contains("severe")
                || serialized.contains("风险")
                || serialized.contains("复核")) {
            warnings.add(new ProcessingWarning("MATH_VALIDATION_REVIEW", "公式或 LaTeX 校验提示需要平台或人工复核。", question.getId()));
        }
        return warnings;
    }

    /**
     * 选择题干展示文本，人工编辑内容优先于 OCR 原始题干。
     *
     * @param question 题目实体
     * @return 题干 Markdown
     */
    private String preferredStem(ImportQuestionEntity question) {
        String manual = text(question.getManualMarkdown());
        return manual.isBlank() ? text(question.getStemMarkdown()) : manual;
    }

    /**
     * 把中文任务状态映射成能力层稳定状态码。
     *
     * @param status 原始任务状态
     * @return 能力层状态码
     */
    private String processingStatus(String status) {
        return switch (text(status)) {
            case "处理中" -> "PROCESSING";
            case "待校验" -> "WAITING_REVIEW";
            case "部分完成" -> "PARTIAL_COMPLETED";
            case "已完成" -> "COMPLETED";
            case "失败" -> "FAILED";
            case "可重试" -> "RETRYABLE";
            default -> "UNKNOWN";
        };
    }

    /**
     * 返回第一个非空文本值。
     *
     * @param values 候选值
     * @return 首个非空文本，未命中时返回空字符串
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
     * 从 Map 中按优先级取第一个存在的键值。
     *
     * @param raw 原始 Map
     * @param keys 候选键
     * @return 命中的值，未命中时返回空列表
     */
    private Object firstPresent(Map<String, Object> raw, String... keys) {
        for (String key : keys) {
            if (raw.containsKey(key)) {
                return raw.get(key);
            }
        }
        return List.of();
    }

    /**
     * 将字符串解析为整数。
     *
     * @param value 字符串值
     * @return 整数值，空值或非法数字返回 null
     */
    private Integer integerValue(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return Integer.parseInt(value);
        } catch (NumberFormatException ignored) {
            return null;
        }
    }

    /**
     * 将任意对象转换为布尔值。
     *
     * @param value 原始值
     * @return 布尔值；空文本返回 null
     */
    private Boolean booleanValue(Object value) {
        if (value instanceof Boolean bool) {
            return bool;
        }
        String text = text(value);
        return text.isBlank() ? null : Boolean.parseBoolean(text);
    }

    /**
     * 将对象安全转换为可变列表。
     *
     * @param value 原始值
     * @return 列表副本；非列表返回空列表
     */
    private List<Object> listValue(Object value) {
        if (value instanceof List<?> list) {
            return new ArrayList<>(list);
        }
        return new ArrayList<>();
    }

    /**
     * 将对象安全转换为字符串键 Map。
     *
     * @param value 原始值
     * @return Map 副本；非 Map 返回空 Map
     */
    private Map<String, Object> mapValue(Object value) {
        Map<String, Object> result = new LinkedHashMap<>();
        if (value instanceof Map<?, ?> map) {
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                result.put(String.valueOf(entry.getKey()), entry.getValue());
            }
        }
        return result;
    }

    /**
     * 将对象转换为去首尾空白的字符串。
     *
     * @param value 原始值
     * @return 文本值；null 返回空字符串
     */
    private String text(Object value) {
        return value == null ? "" : String.valueOf(value).trim();
    }
}
