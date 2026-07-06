package com.aigeneration.questionbank.migration;

import com.aigeneration.questionbank.domain.entity.BankQuestionEntity;
import com.aigeneration.questionbank.domain.entity.KnowledgePointEntity;
import com.aigeneration.questionbank.domain.entity.PaperEntity;
import com.aigeneration.questionbank.domain.service.BankQuestionService;
import com.aigeneration.questionbank.domain.service.ImportTaskMetadataService;
import com.aigeneration.questionbank.domain.service.KnowledgePointService;
import com.aigeneration.questionbank.domain.service.PaperService;
import com.aigeneration.questionbank.domain.support.JsonSupport;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;

/**
 * 历史 library_store.json 数据迁移器。
 *
 * <p>应用启动时按配置读取旧 JSON 存储，把导入任务、知识点、题库题和试卷迁移到 Java 侧
 * 数据表。迁移方法都以“若不存在则插入”为原则，避免重复启动导致重复数据。</p>
 */
@Component
public class LibraryStoreMigrator implements ApplicationRunner {
    /**
     * 迁移日志记录器。
     */
    private static final Logger log = LoggerFactory.getLogger(LibraryStoreMigrator.class);

    /**
     * 旧存储文件根对象类型。
     */
    private static final TypeReference<Map<String, Object>> STORE_TYPE = new TypeReference<>() {};

    /**
     * 是否启用启动迁移。
     */
    private final boolean enabled;

    /**
     * 历史 library_store.json 路径。
     */
    private final Path libraryStorePath;

    /**
     * JSON 读取器，用于读取旧存储文件。
     */
    private final ObjectMapper objectMapper;

    /**
     * JSON 辅助组件，用于写入实体中的 JSON 字段。
     */
    private final JsonSupport json;

    /**
     * 知识点服务，用于插入迁移数据。
     */
    private final KnowledgePointService knowledgePointService;

    /**
     * 题库题服务，用于插入迁移数据。
     */
    private final BankQuestionService bankQuestionService;

    /**
     * 导入任务服务，用于同步迁移任务和题目。
     */
    private final ImportTaskMetadataService importTaskMetadataService;

    /**
     * 试卷服务，用于插入迁移数据。
     */
    private final PaperService paperService;

    /**
     * 注入迁移配置和各领域服务。
     *
     * @param enabled 是否启用迁移
     * @param libraryStorePath 旧 JSON 存储路径
     * @param objectMapper JSON 读取器
     * @param json JSON 辅助组件
     * @param knowledgePointService 知识点服务
     * @param bankQuestionService 题库题服务
     * @param importTaskMetadataService 导入任务服务
     * @param paperService 试卷服务
     */
    public LibraryStoreMigrator(
            @Value("${java-domain.migration.enabled:true}") boolean enabled,
            @Value("${java-domain.migration.library-store-path:storage/library_store.json}") String libraryStorePath,
            ObjectMapper objectMapper,
            JsonSupport json,
            KnowledgePointService knowledgePointService,
            BankQuestionService bankQuestionService,
            ImportTaskMetadataService importTaskMetadataService,
            PaperService paperService
    ) {
        this.enabled = enabled;
        this.libraryStorePath = Path.of(libraryStorePath);
        this.objectMapper = objectMapper;
        this.json = json;
        this.knowledgePointService = knowledgePointService;
        this.bankQuestionService = bankQuestionService;
        this.importTaskMetadataService = importTaskMetadataService;
        this.paperService = paperService;
    }

    /**
     * Spring Boot 启动后执行历史数据迁移。
     *
     * @param args 启动参数
     * @throws Exception 读取或迁移失败时抛出
     */
    @Override
    public void run(ApplicationArguments args) throws Exception {
        if (!enabled) {
            log.info("Java domain migration is disabled");
            return;
        }
        if (!Files.isRegularFile(libraryStorePath)) {
            log.info("Java domain migration skipped, library_store.json not found: {}", libraryStorePath);
            return;
        }

        Map<String, Object> store = readStore();
        int importTasks = migrateImportTasks(list(store.get("importTasks")));
        int knowledgePoints = migrateKnowledgePoints(list(store.get("knowledgePoints")));
        int bankQuestions = migrateBankQuestions(list(store.get("bankQuestions")));
        int papers = migratePapers(list(store.get("papers")));
        log.info(
                "Java domain migration finished from {}: importTasks={}, knowledgePoints={}, bankQuestions={}, papers={}",
                libraryStorePath,
                importTasks,
                knowledgePoints,
                bankQuestions,
                papers
        );
    }

    /**
     * 读取旧 JSON 存储文件。
     *
     * @return 旧存储根 Map
     * @throws IOException 文件读取失败时抛出
     */
    private Map<String, Object> readStore() throws IOException {
        return objectMapper.readValue(libraryStorePath.toFile(), STORE_TYPE);
    }

    /**
     * 迁移导入任务。
     *
     * @param items 旧导入任务列表
     * @return 已处理条数
     */
    private int migrateImportTasks(List<Map<String, Object>> items) {
        int count = 0;
        for (Map<String, Object> item : items) {
            importTaskMetadataService.syncMap(item);
            count++;
        }
        return count;
    }

    /**
     * 迁移知识点。
     *
     * @param items 旧知识点列表
     * @return 已处理条数
     */
    private int migrateKnowledgePoints(List<Map<String, Object>> items) {
        int count = 0;
        for (Map<String, Object> item : items) {
            String id = text(item.get("id"));
            String name = text(item.get("name"));
            if (id.isBlank() || name.isBlank()) {
                continue;
            }
            KnowledgePointEntity entity = new KnowledgePointEntity();
            entity.setId(id);
            entity.setName(name);
            entity.setParentId(text(item.get("parentId")));
            entity.setSubject(text(item.get("subject")));
            entity.setGrade(text(item.get("grade")));
            entity.setDescription(text(item.get("description")));
            entity.setCreatedAt(time(item.get("createdAt")));
            entity.setUpdatedAt(time(item.get("updatedAt")));
            knowledgePointService.insertMigrated(entity);
            count++;
        }
        return count;
    }

    /**
     * 迁移题库题。
     *
     * @param items 旧题库题列表
     * @return 已处理条数
     */
    private int migrateBankQuestions(List<Map<String, Object>> items) {
        int count = 0;
        for (Map<String, Object> item : items) {
            String id = text(item.get("id"));
            if (id.isBlank()) {
                continue;
            }
            BankQuestionEntity entity = new BankQuestionEntity();
            entity.setId(id);
            entity.setSourceImportTaskId(text(item.get("sourceImportTaskId")));
            entity.setSourceImportQuestionId(text(item.get("sourceImportQuestionId")));
            entity.setSource(text(item.get("source")));
            entity.setStage(text(item.get("stage")));
            entity.setSubject(text(item.get("subject")));
            entity.setGrade(text(item.get("grade")));
            entity.setRegion(text(item.get("region")));
            entity.setYear(text(item.get("year")));
            entity.setTitle(text(item.get("title")));
            entity.setQuestionNumber(integer(item.get("number")));
            entity.setType(text(item.get("type")));
            entity.setStemMarkdown(text(item.get("stemMarkdown")));
            entity.setManualMarkdown(text(item.get("manualMarkdown")));
            entity.setAnswer(text(item.get("answer")));
            entity.setAnalysis(text(item.get("analysis")));
            entity.setKnowledgePointIdsJson(json.write(item.get("knowledgePointIds")));
            entity.setKnowledgePointsJson(json.write(item.get("knowledgePoints")));
            entity.setDifficulty(text(item.get("difficulty")));
            entity.setScore(decimal(item.get("score")));
            entity.setImagesJson(json.write(item.get("images")));
            entity.setOptionsJson(json.write(item.get("options")));
            entity.setChildrenJson(json.write(item.get("children")));
            entity.setCreatedAt(time(item.get("createdAt")));
            entity.setUpdatedAt(time(item.get("updatedAt")));
            bankQuestionService.insertMigrated(entity);
            count++;
        }
        return count;
    }

    /**
     * 迁移试卷。
     *
     * @param items 旧试卷列表
     * @return 已处理条数
     */
    private int migratePapers(List<Map<String, Object>> items) {
        int count = 0;
        for (Map<String, Object> item : items) {
            String id = text(item.get("id"));
            String title = text(item.get("title"));
            if (id.isBlank() || title.isBlank()) {
                continue;
            }
            Map<String, Object> header = map(item.get("header"));
            PaperEntity entity = new PaperEntity();
            entity.setId(id);
            entity.setTitle(title);
            entity.setSubject(firstText(item.get("subject"), header.get("subject")));
            entity.setGrade(firstText(item.get("grade"), header.get("grade")));
            entity.setQuestionIdsJson(json.write(item.get("questionIds")));
            entity.setRulesJson(json.write(mapOrEmpty(item.get("rules"))));
            entity.setAnswerDisplay(text(item.get("answerDisplay")));
            entity.setScoresJson(json.write(mapOrEmpty(item.get("scores"))));
            entity.setSubSelectionsJson(json.write(mapOrEmpty(item.get("subSelections"))));
            entity.setHeaderJson(json.write(header));
            entity.setStatus(text(item.get("status")));
            entity.setCreatedAt(time(item.get("createdAt")));
            entity.setUpdatedAt(time(item.get("updatedAt")));
            paperService.insertMigrated(entity);
            count++;
        }
        return count;
    }

    /**
     * 将对象安全转换为 Map 列表。
     *
     * @param value 原始值
     * @return Map 列表；非列表返回空列表
     */
    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> list(Object value) {
        if (value instanceof List<?> list) {
            return list.stream()
                    .filter(Map.class::isInstance)
                    .map(item -> (Map<String, Object>) item)
                    .toList();
        }
        return List.of();
    }

    /**
     * 将对象安全转换为 Map。
     *
     * @param value 原始值
     * @return Map；非 Map 返回空 Map
     */
    @SuppressWarnings("unchecked")
    private Map<String, Object> map(Object value) {
        if (value instanceof Map<?, ?> map) {
            return (Map<String, Object>) map;
        }
        return Map.of();
    }

    /**
     * 将对象转换为 Map 或空 Map。
     *
     * @param value 原始值
     * @return Map 或空 Map
     */
    private Object mapOrEmpty(Object value) {
        return value instanceof Map<?, ?> ? value : Map.of();
    }

    /**
     * 返回两个候选值中的首个非空文本。
     *
     * @param first 第一候选
     * @param second 第二候选
     * @return 首个非空文本；都为空返回空字符串
     */
    private String firstText(Object first, Object second) {
        String value = text(first);
        return value.isBlank() ? text(second) : value;
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
     * 将对象转换为整数。
     *
     * @param value 原始值
     * @return 整数；无法解析时返回 null
     */
    private Integer integer(Object value) {
        if (value instanceof Number number) {
            return number.intValue();
        }
        String text = text(value);
        if (text.isBlank()) {
            return null;
        }
        try {
            return Integer.parseInt(text);
        } catch (NumberFormatException ex) {
            return null;
        }
    }

    /**
     * 将对象转换为小数。
     *
     * @param value 原始值
     * @return 小数；无法解析时返回 0.0
     */
    private Double decimal(Object value) {
        if (value instanceof Number number) {
            return number.doubleValue();
        }
        String text = text(value);
        if (text.isBlank()) {
            return 0.0;
        }
        try {
            return Double.parseDouble(text);
        } catch (NumberFormatException ex) {
            return 0.0;
        }
    }

    /**
     * 解析旧数据中的时间字段。
     *
     * @param value 原始时间值
     * @return 本地时间；解析失败时返回当前时间
     */
    private LocalDateTime time(Object value) {
        String text = text(value);
        if (text.isBlank()) {
            return LocalDateTime.now();
        }
        try {
            return OffsetDateTime.parse(text).toLocalDateTime();
        } catch (DateTimeParseException ignored) {
            try {
                return LocalDateTime.parse(text, DateTimeFormatter.ISO_LOCAL_DATE_TIME);
            } catch (DateTimeParseException ignoredAgain) {
                return LocalDateTime.now();
            }
        }
    }
}
