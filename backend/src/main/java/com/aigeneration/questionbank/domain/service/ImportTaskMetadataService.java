package com.aigeneration.questionbank.domain.service;

import com.aigeneration.questionbank.domain.entity.ImportTaskEntity;
import com.aigeneration.questionbank.domain.mapper.ImportTaskMapper;
import com.aigeneration.questionbank.domain.support.JsonSupport;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.format.DateTimeParseException;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import org.springframework.stereotype.Service;

/**
 * 导入任务元数据同步服务。
 *
 * <p>负责把 Python worker 返回的导入任务快照同步到 Java 侧任务表，并在任务状态或题目数量
 * 发生变化时触发题目表同步。该服务是导入任务状态的 Java 侧可信快照。</p>
 */
@Service
public class ImportTaskMetadataService {
    /**
     * 导入任务表访问对象。
     */
    private final ImportTaskMapper mapper;

    /**
     * JSON 辅助组件，用于持久化 worker 原始文件、OCR job 和任务快照。
     */
    private final JsonSupport json;

    /**
     * 导入题目同步服务，用于在任务变化后刷新题目和题图快照。
     */
    private final ImportQuestionSyncService importQuestionSyncService;

    /**
     * 注入任务表、JSON 工具和题目同步服务。
     *
     * @param mapper 导入任务 Mapper
     * @param json JSON 辅助组件
     * @param importQuestionSyncService 导入题目同步服务
     */
    public ImportTaskMetadataService(
            ImportTaskMapper mapper,
            JsonSupport json,
            ImportQuestionSyncService importQuestionSyncService
    ) {
        this.mapper = mapper;
        this.json = json;
        this.importQuestionSyncService = importQuestionSyncService;
    }

    /**
     * 同步 worker 返回的任务列表。
     *
     * @param value 预期为任务 Map 列表的原始对象
     */
    public void syncList(Object value) {
        if (!(value instanceof List<?> items)) {
            return;
        }
        for (Object item : items) {
            if (item instanceof Map<?, ?> map) {
                syncMap(map);
            }
        }
    }

    /**
     * 同步 worker 返回的单个任务对象。
     *
     * @param value 预期为任务 Map 的原始对象
     */
    public void syncOne(Object value) {
        if (value instanceof Map<?, ?> map) {
            syncMap(map);
        }
    }

    /**
     * 将单个任务快照同步到 Java 任务表。
     *
     * <p>方法会保留已有创建时间，重新计算 Java 侧状态、OCR 状态、失败原因和题目数量。只有
     * 任务字段变化时才写库，只有影响题目展示的字段变化时才同步题目，减少重复写入。</p>
     *
     * @param raw worker 返回的任务 Map
     */
    public void syncMap(Map<?, ?> raw) {
        String id = text(raw.get("id"));
        if (id.isBlank()) {
            return;
        }
        LocalDateTime now = LocalDateTime.now();
        ImportTaskEntity existing = mapper.selectById(id);
        ImportTaskEntity entity = new ImportTaskEntity();
        entity.setId(id);
        LocalDateTime createdAt = existing == null ? null : existing.getCreatedAt();
        String paperOcrStatus = jobStatus(raw.get("paperOcrJob"));
        String answerOcrStatus = jobStatus(raw.get("answerOcrJob"));
        int questionCount = questionCount(raw.get("questions"));
        entity.setStage(text(raw.get("stage")));
        entity.setSubject(text(raw.get("subject")));
        entity.setGrade(text(raw.get("grade")));
        entity.setRegion(text(raw.get("region")));
        entity.setYear(text(raw.get("year")));
        entity.setTitle(text(raw.get("title")));
        entity.setStatus(deriveStatus(raw));
        entity.setPaperFileJson(json.write(raw.get("paperFile")));
        entity.setAnswerFileJson(json.write(raw.get("answerFile")));
        entity.setPaperOcrJobId(text(raw.get("paperOcrJobId")));
        entity.setAnswerOcrJobId(text(raw.get("answerOcrJobId")));
        entity.setPaperOcrJobJson(json.write(raw.get("paperOcrJob")));
        entity.setAnswerOcrJobJson(json.write(raw.get("answerOcrJob")));
        entity.setPaperOcrStatus(paperOcrStatus);
        entity.setAnswerOcrStatus(answerOcrStatus);
        entity.setFailureReason(failureReason(raw));
        entity.setQuestionCount(questionCount);
        entity.setRawJson(json.write(raw));
        entity.setCreatedAt(parseTime(raw.get("createdAt"), createdAt == null ? now : createdAt));
        entity.setUpdatedAt(parseTime(raw.get("updatedAt"), now));
        boolean shouldWriteTask = existing == null || taskChanged(existing, entity);
        boolean shouldSyncQuestions = existing == null
                || !Objects.equals(existing.getUpdatedAt(), entity.getUpdatedAt())
                || !Objects.equals(existing.getStatus(), entity.getStatus())
                || !Objects.equals(existing.getQuestionCount(), entity.getQuestionCount())
                || !Objects.equals(existing.getPaperOcrStatus(), entity.getPaperOcrStatus())
                || !Objects.equals(existing.getAnswerOcrStatus(), entity.getAnswerOcrStatus());
        if (existing == null) {
            mapper.insert(entity);
        } else if (shouldWriteTask) {
            mapper.updateById(entity);
        }
        if (shouldSyncQuestions) {
            importQuestionSyncService.syncQuestions(id, raw.get("questions"));
        }
    }

    /**
     * 插入从旧存储迁移来的导入任务。
     *
     * @param entity 待迁移的导入任务实体
     */
    public void insertMigrated(ImportTaskEntity entity) {
        if (entity.getId() != null && mapper.selectById(entity.getId()) == null) {
            mapper.insert(entity);
        }
    }

    /**
     * 根据任务 ID 读取导入任务实体。
     *
     * @param id 任务 ID
     * @return 导入任务实体；不存在时返回 null
     */
    public ImportTaskEntity getEntity(String id) {
        return mapper.selectById(id);
    }

    /**
     * 按更新时间倒序查询所有任务实体。
     *
     * @return 任务实体列表
     */
    public List<ImportTaskEntity> listEntities() {
        return mapper.selectList(new QueryWrapper<ImportTaskEntity>()
                .orderByDesc("updated_at")
                .orderByDesc("created_at"));
    }

    /**
     * 删除任务及其同步题目快照。
     *
     * @param id 任务 ID
     */
    public void delete(String id) {
        if (id != null && !id.isBlank()) {
            mapper.deleteById(id);
            importQuestionSyncService.deleteByTask(id);
        }
    }

    /**
     * 批量删除任务及题目快照。
     *
     * @param value 预期为任务 ID 列表
     */
    public void deleteMany(Object value) {
        if (!(value instanceof List<?> ids)) {
            return;
        }
        for (Object id : ids) {
            delete(text(id));
        }
    }

    /**
     * 统计原始题目列表数量。
     *
     * @param value 原始题目列表
     * @return 题目数量
     */
    private int questionCount(Object value) {
        return value instanceof List<?> list ? list.size() : 0;
    }

    /**
     * 判断任务实体中需要持久化的字段是否发生变化。
     *
     * @param existing 已存在实体
     * @param next 新同步实体
     * @return true 表示需要更新数据库
     */
    private boolean taskChanged(ImportTaskEntity existing, ImportTaskEntity next) {
        return !Objects.equals(existing.getStage(), next.getStage())
                || !Objects.equals(existing.getSubject(), next.getSubject())
                || !Objects.equals(existing.getGrade(), next.getGrade())
                || !Objects.equals(existing.getRegion(), next.getRegion())
                || !Objects.equals(existing.getYear(), next.getYear())
                || !Objects.equals(existing.getTitle(), next.getTitle())
                || !Objects.equals(existing.getStatus(), next.getStatus())
                || !Objects.equals(existing.getPaperFileJson(), next.getPaperFileJson())
                || !Objects.equals(existing.getAnswerFileJson(), next.getAnswerFileJson())
                || !Objects.equals(existing.getPaperOcrJobId(), next.getPaperOcrJobId())
                || !Objects.equals(existing.getAnswerOcrJobId(), next.getAnswerOcrJobId())
                || !Objects.equals(existing.getPaperOcrJobJson(), next.getPaperOcrJobJson())
                || !Objects.equals(existing.getAnswerOcrJobJson(), next.getAnswerOcrJobJson())
                || !Objects.equals(existing.getPaperOcrStatus(), next.getPaperOcrStatus())
                || !Objects.equals(existing.getAnswerOcrStatus(), next.getAnswerOcrStatus())
                || !Objects.equals(existing.getFailureReason(), next.getFailureReason())
                || !Objects.equals(existing.getQuestionCount(), next.getQuestionCount())
                || !Objects.equals(existing.getUpdatedAt(), next.getUpdatedAt())
                || !Objects.equals(existing.getRawJson(), next.getRawJson());
    }

    /**
     * 根据 OCR job、失败原因和题目校验进度推导 Java 侧任务状态。
     *
     * @param raw worker 原始任务 Map
     * @return 中文业务状态
     */
    private String deriveStatus(Map<?, ?> raw) {
        String rawStatus = text(raw.get("status"));
        String paperStatus = jobStatus(raw.get("paperOcrJob"));
        String answerStatus = jobStatus(raw.get("answerOcrJob"));
        if (isFailed(paperStatus) || isFailed(answerStatus) || !failureReason(raw).isBlank()) {
            return retryable(raw) ? "可重试" : "失败";
        }
        if (isRunning(paperStatus) || isRunning(answerStatus)) {
            return "处理中";
        }
        if (!(raw.get("questions") instanceof List<?> questions) || questions.isEmpty()) {
            return rawStatus.isBlank() ? "处理中" : rawStatus;
        }
        int banked = 0;
        int reviewed = 0;
        for (Object item : questions) {
            if (!(item instanceof Map<?, ?> question)) {
                continue;
            }
            String status = text(question.get("status"));
            if ("已入库".equals(status)) {
                banked++;
            }
            if ("已校验".equals(status) || "已入库".equals(status)) {
                reviewed++;
            }
        }
        if (banked == questions.size()) {
            return "已完成";
        }
        if (banked > 0 || reviewed > 0) {
            return "部分完成";
        }
        return "待校验";
    }

    /**
     * 判断 OCR job 状态是否表示仍在执行。
     *
     * @param status 原始状态
     * @return true 表示任务仍在运行
     */
    private boolean isRunning(String status) {
        return "queued".equalsIgnoreCase(status)
                || "pending".equalsIgnoreCase(status)
                || "running".equalsIgnoreCase(status)
                || "processing".equalsIgnoreCase(status)
                || "处理中".equals(status);
    }

    /**
     * 判断 OCR job 状态是否表示失败。
     *
     * @param status 原始状态
     * @return true 表示失败
     */
    private boolean isFailed(String status) {
        return "failed".equalsIgnoreCase(status)
                || "error".equalsIgnoreCase(status)
                || "失败".equals(status);
    }

    /**
     * 根据 worker 的重试标记或重试次数判断任务是否可重试。
     *
     * @param raw worker 原始任务 Map
     * @return true 表示可重试
     */
    private boolean retryable(Map<?, ?> raw) {
        Object retryable = raw.get("retryable");
        if (retryable instanceof Boolean value) {
            return value;
        }
        Integer retryCount = integer(raw.get("retryCount"));
        Integer maxRetryCount = integer(raw.get("maxRetryCount"));
        if (retryCount != null && maxRetryCount != null) {
            return retryCount < maxRetryCount;
        }
        return true;
    }

    /**
     * 提取 OCR job 状态。
     *
     * @param value OCR job 原始对象
     * @return 状态字符串
     */
    private String jobStatus(Object value) {
        if (value instanceof Map<?, ?> map) {
            return text(map.get("status"));
        }
        return "";
    }

    /**
     * 汇总试卷和答案 OCR 的失败原因。
     *
     * @param raw worker 原始任务 Map
     * @return 面向用户展示的失败原因
     */
    private String failureReason(Map<?, ?> raw) {
        String paperError = jobError(raw.get("paperOcrJob"));
        String answerError = jobError(raw.get("answerOcrJob"));
        if (!paperError.isBlank() && !answerError.isBlank()) {
            return "试卷 OCR: " + paperError + "\n答案 OCR: " + answerError;
        }
        if (!paperError.isBlank()) {
            return "试卷 OCR: " + paperError;
        }
        if (!answerError.isBlank()) {
            return "答案 OCR: " + answerError;
        }
        return "";
    }

    /**
     * 提取单个 OCR job 的错误文本。
     *
     * @param value OCR job 原始对象
     * @return 错误文本
     */
    private String jobError(Object value) {
        if (value instanceof Map<?, ?> map) {
            return text(map.get("error"));
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
        } catch (NumberFormatException ignored) {
            return null;
        }
    }

    /**
     * 解析 worker 时间字段。
     *
     * <p>优先按带时区的 ISO 时间解析，失败后按本地时间解析，再失败使用 fallback，兼容
     * Python worker 和历史数据的两种时间格式。</p>
     *
     * @param value 原始时间值
     * @param fallback 解析失败时的兜底时间
     * @return 本地时间
     */
    private LocalDateTime parseTime(Object value, LocalDateTime fallback) {
        String text = text(value);
        if (text.isBlank()) {
            return fallback;
        }
        try {
            return OffsetDateTime.parse(text).toLocalDateTime();
        } catch (DateTimeParseException ignored) {
            try {
                return LocalDateTime.parse(text);
            } catch (DateTimeParseException ignoredAgain) {
                return fallback;
            }
        }
    }
}
