package com.aigeneration.questionbank.domain.service;

import com.aigeneration.questionbank.domain.entity.BankQuestionEntity;
import com.aigeneration.questionbank.domain.mapper.BankQuestionMapper;
import com.aigeneration.questionbank.domain.support.Ids;
import com.aigeneration.questionbank.domain.support.JsonSupport;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.format.DateTimeParseException;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

/**
 * 题库题目服务。
 *
 * <p>负责题库题目的 CRUD、筛选查询、题图追加、AI 结果回写以及从导入题同步入库。
 * 该服务保存的是 engine 侧题库题目快照，平台可在此基础上接管最终题库主数据。</p>
 */
@Service
public class BankQuestionService {
    /**
     * 题库题目表访问对象。
     */
    private final BankQuestionMapper mapper;

    /**
     * JSON 辅助组件，用于读写题图、选项、子题和知识点数组字段。
     */
    private final JsonSupport json;

    /**
     * 注入题库题 Mapper 和 JSON 辅助组件。
     *
     * @param mapper 题库题 Mapper
     * @param json JSON 辅助组件
     */
    public BankQuestionService(BankQuestionMapper mapper, JsonSupport json) {
        this.mapper = mapper;
        this.json = json;
    }

    /**
     * 按过滤条件查询题库题。
     *
     * @param filters 控制器传入的筛选条件
     * @return 包含 items 和 total 的查询结果
     */
    public Map<String, Object> list(Map<String, String> filters) {
        List<Map<String, Object>> matched = mapper.selectList(new LambdaQueryWrapper<BankQuestionEntity>()
                        .orderByDesc(BankQuestionEntity::getCreatedAt))
                .stream()
                .filter(entity -> matches(entity, filters))
                .map(this::toMap)
                .toList();
        return Map.of("items", matched, "total", matched.size());
    }

    /**
     * 查询单道题库题。
     *
     * @param id 题目 ID
     * @return 题库题响应 Map
     */
    public Map<String, Object> get(String id) {
        return toMap(required(id));
    }

    /**
     * 创建题库题。
     *
     * @param payload 题目载荷
     * @return 新建题目响应 Map
     */
    public Map<String, Object> create(Map<String, Object> payload) {
        LocalDateTime now = LocalDateTime.now();
        BankQuestionEntity entity = new BankQuestionEntity();
        entity.setId(Ids.next("bank_question"));
        entity.setCreatedAt(now);
        entity.setUpdatedAt(now);
        applyPayload(entity, payload);
        mapper.insert(entity);
        return toMap(entity);
    }

    /**
     * 更新题库题。
     *
     * @param id 题目 ID
     * @param payload 更新载荷
     * @return 更新后题目响应 Map
     */
    public Map<String, Object> update(String id, Map<String, Object> payload) {
        BankQuestionEntity entity = required(id);
        LocalDateTime createdAt = entity.getCreatedAt();
        applyPayload(entity, payload);
        entity.setId(id);
        entity.setCreatedAt(createdAt == null ? LocalDateTime.now() : createdAt);
        entity.setUpdatedAt(LocalDateTime.now());
        mapper.updateById(entity);
        return toMap(entity);
    }

    /**
     * 删除题库题。
     *
     * @param id 题目 ID
     * @return 删除结果
     */
    public Map<String, Object> delete(String id) {
        if (mapper.deleteById(id) == 0) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Question not found");
        }
        return Map.of("deleted", true);
    }

    /**
     * 为题库题追加题图。
     *
     * @param id 题目 ID
     * @param uploaded 新上传题图元数据
     * @return 更新后的题目响应 Map
     */
    public Map<String, Object> appendImages(String id, List<Map<String, Object>> uploaded) {
        BankQuestionEntity entity = required(id);
        List<Object> images = mergeImages(json.readList(entity.getImagesJson()), uploaded);
        entity.setImagesJson(json.write(images));
        entity.setUpdatedAt(LocalDateTime.now());
        mapper.updateById(entity);
        return toMap(entity);
    }

    /**
     * 回写 AI 标准化结果。
     *
     * @param id 题目 ID
     * @param markdown 标准化 Markdown
     * @param answer AI 答案
     * @param analysis AI 解析
     * @return 更新后的题目响应 Map
     */
    public Map<String, Object> updateStandardizedResult(String id, String markdown, String answer, String analysis, Map<String, Object> aiResponse) {
        BankQuestionEntity entity = required(id);
        List<Object> children = mergeAiSubQuestions(json.readList(entity.getChildrenJson()), aiResponse);
        boolean hasSubQuestions = !children.isEmpty();
        if (hasSubQuestions) {
            entity.setChildrenJson(json.write(children));
        }
        if (markdown != null && !markdown.isBlank()) {
            entity.setManualMarkdown(markdown);
        }
        if (hasSubQuestions) {
            entity.setAnalysis("");
            entity.setAnswer("");
        } else if (analysis != null && !analysis.isBlank()) {
            entity.setAnalysis(analysis);
        }
        if (!hasSubQuestions && answer != null && !answer.isBlank()) {
            entity.setAnswer(answer);
        }
        entity.setUpdatedAt(LocalDateTime.now());
        mapper.updateById(entity);
        return toMap(entity);
    }

    /**
     * 回写 AI 解析结果。
     *
     * @param id 题目 ID
     * @param analysis AI 解析
     * @param answer AI 答案
     * @return 更新后的题目响应 Map
     */
    public Map<String, Object> updateAiResult(String id, String analysis, String answer, Map<String, Object> aiResponse) {
        BankQuestionEntity entity = required(id);
        List<Object> children = mergeAiSubQuestions(json.readList(entity.getChildrenJson()), aiResponse);
        boolean hasSubQuestions = !children.isEmpty();
        if (hasSubQuestions) {
            entity.setChildrenJson(json.write(children));
            entity.setAnalysis("");
            entity.setAnswer("");
        } else if (analysis != null && !analysis.isBlank()) {
            entity.setAnalysis(analysis);
        }
        if (!hasSubQuestions && answer != null && !answer.isBlank()) {
            entity.setAnswer(answer);
        }
        entity.setUpdatedAt(LocalDateTime.now());
        mapper.updateById(entity);
        return toMap(entity);
    }

    /**
     * 查询必需存在的题库题实体。
     *
     * @param id 题目 ID
     * @return 题库题实体
     */
    public BankQuestionEntity required(String id) {
        BankQuestionEntity entity = mapper.selectById(id);
        if (entity == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Question not found");
        }
        return entity;
    }

    /**
     * 将题库题实体序列化为 API 响应 Map。
     *
     * @param entity 题库题实体
     * @return 响应 Map
     */
    public Map<String, Object> toMap(BankQuestionEntity entity) {
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("id", entity.getId());
        item.put("sourceImportTaskId", entity.getSourceImportTaskId());
        item.put("sourceImportQuestionId", entity.getSourceImportQuestionId());
        item.put("source", value(entity.getSource()));
        item.put("stage", value(entity.getStage()));
        item.put("subject", value(entity.getSubject()));
        item.put("grade", value(entity.getGrade()));
        item.put("region", value(entity.getRegion()));
        item.put("year", value(entity.getYear()));
        item.put("title", value(entity.getTitle()));
        item.put("number", entity.getQuestionNumber());
        item.put("type", value(entity.getType(), "unknown"));
        item.put("stemMarkdown", value(entity.getStemMarkdown()));
        item.put("manualMarkdown", value(entity.getManualMarkdown()));
        item.put("answer", value(entity.getAnswer()));
        item.put("analysis", value(entity.getAnalysis()));
        item.put("knowledgePointIds", json.readList(entity.getKnowledgePointIdsJson()));
        item.put("knowledgePoints", json.readList(entity.getKnowledgePointsJson()));
        item.put("difficulty", value(entity.getDifficulty(), "medium"));
        item.put("score", entity.getScore() == null ? 0 : entity.getScore());
        item.put("images", json.readList(entity.getImagesJson()));
        item.put("options", json.readList(entity.getOptionsJson()));
        List<Object> children = json.readList(entity.getChildrenJson());
        item.put("children", children);
        item.put("subQuestions", children);
        item.put("createdAt", entity.getCreatedAt());
        item.put("updatedAt", entity.getUpdatedAt());
        return item;
    }

    /**
     * 插入旧数据迁移得到的题库题。
     *
     * @param entity 迁移实体
     */
    public void insertMigrated(BankQuestionEntity entity) {
        if (entity.getId() != null && mapper.selectById(entity.getId()) == null) {
            mapper.insert(entity);
        }
    }

    /**
     * 从导入题入库载荷创建或更新题库题。
     *
     * @param payload 导入题转换后的题库题载荷
     * @return 题库题响应 Map
     */
    public Map<String, Object> upsertFromPayload(Map<String, Object> payload) {
        String id = text(payload.get("id"));
        LocalDateTime now = LocalDateTime.now();
        BankQuestionEntity entity = id.isBlank() ? null : mapper.selectById(id);
        LocalDateTime createdAt = entity == null ? null : entity.getCreatedAt();
        if (entity == null) {
            entity = new BankQuestionEntity();
            entity.setId(id.isBlank() ? Ids.next("bank_question") : id);
        }
        applyPayload(entity, payload);
        entity.setCreatedAt(parseTime(payload.get("createdAt"), createdAt == null ? now : createdAt));
        entity.setUpdatedAt(parseTime(payload.get("updatedAt"), now));
        if (mapper.selectById(entity.getId()) == null) {
            mapper.insert(entity);
        } else {
            mapper.updateById(entity);
        }
        return toMap(entity);
    }

    /**
     * 将 API 载荷应用到题库题实体。
     *
     * @param entity 题库题实体
     * @param payload 请求载荷
     */
    private void applyPayload(BankQuestionEntity entity, Map<String, Object> payload) {
        entity.setSourceImportTaskId(text(payload.get("sourceImportTaskId")));
        entity.setSourceImportQuestionId(text(payload.get("sourceImportQuestionId")));
        entity.setSource(text(payload.get("source")));
        entity.setStage(text(payload.get("stage")));
        entity.setSubject(text(payload.get("subject")));
        entity.setGrade(text(payload.get("grade")));
        entity.setRegion(text(payload.get("region")));
        entity.setYear(text(payload.get("year")));
        entity.setTitle(text(payload.getOrDefault("title", payload.get("source"))));
        entity.setQuestionNumber(intValue(payload.get("number")));
        entity.setType(value(text(payload.get("type")), "unknown"));
        entity.setStemMarkdown(text(payload.get("stemMarkdown")));
        entity.setManualMarkdown(text(payload.getOrDefault("manualMarkdown", payload.get("stemMarkdown"))));
        List<Object> subQuestions = listValue(payload.containsKey("subQuestions") ? payload.get("subQuestions") : payload.get("children"));
        entity.setAnswer(subQuestions.isEmpty() ? text(payload.get("answer")) : "");
        entity.setAnalysis(subQuestions.isEmpty() ? text(payload.get("analysis")) : "");
        entity.setKnowledgePointIdsJson(json.write(payload.get("knowledgePointIds")));
        entity.setKnowledgePointsJson(json.write(payload.get("knowledgePoints")));
        entity.setDifficulty(value(text(payload.get("difficulty")), "medium"));
        entity.setScore(doubleValue(payload.get("score")));
        entity.setImagesJson(json.write(payload.get("images")));
        entity.setOptionsJson(json.write(payload.get("options")));
        entity.setChildrenJson(json.write(subQuestions));
    }

    /**
     * 将 AI 返回的小问答案/解析合并进当前小问列表。
     *
     * @param current 当前 childrenJson 小问
     * @param aiResponse AI 响应
     * @return 合并后的小问列表
     */
    private List<Object> mergeAiSubQuestions(List<Object> current, Map<String, Object> aiResponse) {
        List<Object> incomingRaw = listValue(aiSubQuestions(aiResponse));
        if (incomingRaw.isEmpty()) {
            return current;
        }
        List<Map<String, Object>> incoming = new ArrayList<>();
        for (Object item : incomingRaw) {
            Map<String, Object> mapped = mapValue(item);
            if (!mapped.isEmpty()) {
                incoming.add(mapped);
            }
        }
        if (incoming.isEmpty()) {
            return current;
        }
        if (current.isEmpty()) {
            return new ArrayList<>(incoming);
        }

        List<Object> merged = new ArrayList<>();
        Set<Integer> used = new LinkedHashSet<>();
        for (int index = 0; index < current.size(); index++) {
            Object item = current.get(index);
            Map<String, Object> child = mapValue(item);
            if (child.isEmpty()) {
                merged.add(item);
                continue;
            }
            int matchIndex = findSubQuestionMatch(child, incoming, used, index);
            if (matchIndex >= 0) {
                mergeSubQuestionFields(child, incoming.get(matchIndex));
                used.add(matchIndex);
            }
            merged.add(child);
        }
        for (int index = 0; index < incoming.size(); index++) {
            if (!used.contains(index)) {
                merged.add(incoming.get(index));
            }
        }
        return merged;
    }

    /**
     * 提取 AI 响应里的小问数组。
     *
     * @param aiResponse AI 响应
     * @return subQuestions 或 metadata.subQuestions
     */
    private Object aiSubQuestions(Map<String, Object> aiResponse) {
        if (aiResponse == null) {
            return List.of();
        }
        Object direct = aiResponse.get("subQuestions");
        if (direct instanceof List<?>) {
            return direct;
        }
        Object metadata = aiResponse.get("metadata");
        if (metadata instanceof Map<?, ?> raw) {
            return raw.get("subQuestions");
        }
        return List.of();
    }

    /**
     * 查找当前小问对应的 AI 小问。
     *
     * @param child 当前小问
     * @param incoming AI 小问列表
     * @param used 已匹配下标
     * @param fallbackIndex 兜底顺序下标
     * @return 匹配下标；未匹配返回 -1
     */
    private int findSubQuestionMatch(Map<String, Object> child, List<Map<String, Object>> incoming, Set<Integer> used, int fallbackIndex) {
        String id = text(child.get("id"));
        if (!id.isBlank()) {
            for (int i = 0; i < incoming.size(); i++) {
                if (!used.contains(i) && id.equals(text(incoming.get(i).get("id")))) {
                    return i;
                }
            }
        }
        String label = text(child.get("label"));
        if (!label.isBlank()) {
            for (int i = 0; i < incoming.size(); i++) {
                if (!used.contains(i) && label.equals(text(incoming.get(i).get("label")))) {
                    return i;
                }
            }
        }
        return fallbackIndex < incoming.size() && !used.contains(fallbackIndex) ? fallbackIndex : -1;
    }

    /**
     * 合并小问字段。
     *
     * @param target 当前小问
     * @param source AI 小问
     */
    private void mergeSubQuestionFields(Map<String, Object> target, Map<String, Object> source) {
        for (String field : List.of(
                "stem", "stemMarkdown", "manualMarkdown", "answer", "analysis",
                "type", "difficulty", "score", "knowledgePointIds", "knowledgePoints", "options", "images",
                "contextMatched", "answerEvidence", "analysisEvidence", "warnings", "aiMetadata")) {
            Object value = source.get(field);
            if (hasValue(value)) {
                target.put(field, value);
            }
        }
    }

    /**
     * 将对象转换为字符串键 Map。
     *
     * @param value 原始对象
     * @return Map；非 Map 返回空 Map
     */
    private Map<String, Object> mapValue(Object value) {
        if (!(value instanceof Map<?, ?> raw)) {
            return new LinkedHashMap<>();
        }
        Map<String, Object> mapped = new LinkedHashMap<>();
        for (Map.Entry<?, ?> entry : raw.entrySet()) {
            if (entry.getKey() != null) {
                mapped.put(String.valueOf(entry.getKey()), entry.getValue());
            }
        }
        return mapped;
    }

    /**
     * 判断 AI 字段是否可以写回。
     *
     * @param value 字段值
     * @return true 表示非空
     */
    private boolean hasValue(Object value) {
        if (value == null) {
            return false;
        }
        if (value instanceof String text) {
            return !text.isBlank();
        }
        if (value instanceof List<?> list) {
            return !list.isEmpty();
        }
        return true;
    }

    /**
     * 判断题目是否满足筛选条件。
     *
     * @param entity 题库题实体
     * @param filters 筛选条件
     * @return true 表示命中
     */
    private boolean matches(BankQuestionEntity entity, Map<String, String> filters) {
        if (!contains(searchText(entity), filters.get("keyword"))) return false;
        if (!equalsFilter(entity.getType(), filters.get("type"))) return false;
        if (!equalsFilter(entity.getDifficulty(), filters.get("difficulty"))) return false;
        if (!contains(entity.getSubject(), filters.get("subject"))) return false;
        if (!contains(entity.getGrade(), filters.get("grade"))) return false;
        if (!contains(entity.getRegion(), filters.get("region"))) return false;
        if (!contains(entity.getYear(), filters.get("year"))) return false;
        if (!contains(entity.getSource(), filters.get("source"))) return false;
        if (!contains(entity.getKnowledgePointIdsJson(), filters.get("knowledgePointId"))) return false;
        String score = filters.get("score");
        return score == null || score.isBlank() || String.valueOf(entity.getScore()).equals(score);
    }

    /**
     * 构建关键词搜索文本。
     *
     * @param entity 题库题实体
     * @return 可搜索文本
     */
    private String searchText(BankQuestionEntity entity) {
        return String.join("\n",
                value(entity.getManualMarkdown()),
                value(entity.getStemMarkdown()),
                value(entity.getAnswer()),
                value(entity.getAnalysis()),
                value(entity.getKnowledgePointsJson()),
                value(entity.getChildrenJson()));
    }

    /**
     * 将对象安全转换为列表。
     *
     * @param value 原始值
     * @return 列表；非列表返回空列表
     */
    private List<Object> listValue(Object value) {
        if (value instanceof List<?> list) {
            return new ArrayList<>(list);
        }
        return List.of();
    }

    /**
     * 判断字段是否精确匹配过滤值。
     *
     * @param source 字段值
     * @param filter 过滤值
     * @return true 表示匹配或过滤值为空
     */
    private boolean equalsFilter(String source, String filter) {
        return filter == null || filter.isBlank() || value(source).equals(filter);
    }

    /**
     * 判断字段是否包含过滤值。
     *
     * @param source 字段值
     * @param filter 过滤值
     * @return true 表示包含或过滤值为空
     */
    private boolean contains(String source, String filter) {
        return filter == null || filter.isBlank() || value(source).toLowerCase().contains(filter.toLowerCase());
    }

    /**
     * 合并并去重题图列表。
     *
     * @param existing 已有题图
     * @param appended 新追加题图
     * @return 合并后的题图列表
     */
    private List<Object> mergeImages(List<Object> existing, List<Map<String, Object>> appended) {
        List<Object> images = new ArrayList<>();
        java.util.Set<String> seen = new java.util.LinkedHashSet<>();
        for (Object image : existing) {
            if (imageKey(image, seen)) {
                images.add(image);
            }
        }
        for (Map<String, Object> image : appended) {
            if (imageKey(image, seen)) {
                images.add(image);
            }
        }
        return images;
    }

    /**
     * 提取题图去重键。
     *
     * @param image 题图对象
     * @param seen 已出现键集合
     * @return true 表示题图有效且未重复
     */
    private boolean imageKey(Object image, java.util.Set<String> seen) {
        if (!(image instanceof Map<?, ?> raw)) {
            return false;
        }
        String key = firstText(raw.get("storageFileId"), raw.get("url"), raw.get("path"), raw.get("name"));
        return !key.isBlank() && seen.add(key);
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
     * 将对象转换为去首尾空白文本。
     *
     * @param value 原始值
     * @return 文本；null 返回空字符串
     */
    private String text(Object value) {
        return value == null ? "" : String.valueOf(value).trim();
    }

    /**
     * 返回非空字符串或空字符串。
     *
     * @param value 原始字符串
     * @return 非空字符串；空值返回空字符串
     */
    private String value(String value) {
        return value(value, "");
    }

    /**
     * 返回非空字符串或兜底值。
     *
     * @param value 原始字符串
     * @param fallback 兜底值
     * @return 非空字符串或兜底值
     */
    private String value(String value, String fallback) {
        return value == null || value.isBlank() ? fallback : value;
    }

    /**
     * 将对象转换为整数。
     *
     * @param value 原始值
     * @return 整数；无法解析时返回 null
     */
    private Integer intValue(Object value) {
        if (value instanceof Number number) return number.intValue();
        if (value == null || String.valueOf(value).isBlank()) return null;
        try {
            return Integer.parseInt(String.valueOf(value));
        } catch (NumberFormatException ex) {
            return null;
        }
    }

    /**
     * 将对象转换为分值小数。
     *
     * @param value 原始值
     * @return 小数；无法解析时返回 0.0
     */
    private Double doubleValue(Object value) {
        if (value instanceof Number number) return number.doubleValue();
        if (value == null || String.valueOf(value).isBlank()) return 0.0;
        try {
            return Double.parseDouble(String.valueOf(value));
        } catch (NumberFormatException ex) {
            return 0.0;
        }
    }

    /**
     * 解析题库题时间字段。
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
