package com.aigeneration.questionbank.domain.service;

import com.aigeneration.questionbank.domain.entity.BankQuestionEntity;
import com.aigeneration.questionbank.domain.entity.PaperEntity;
import com.aigeneration.questionbank.domain.mapper.BankQuestionMapper;
import com.aigeneration.questionbank.domain.mapper.PaperMapper;
import com.aigeneration.questionbank.domain.support.Ids;
import com.aigeneration.questionbank.domain.support.JsonSupport;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

/**
 * 试卷组卷服务。
 *
 * <p>负责试卷定义的 CRUD、题目引用解析、规则选题、分值构建和 API 响应序列化。导出流程
 * 使用该服务提供的试卷快照作为输入。</p>
 */
@Service
public class PaperService {
    /**
     * 试卷表访问对象。
     */
    private final PaperMapper mapper;

    /**
     * 题库题 Mapper，用于解析试卷中的题目引用。
     */
    private final BankQuestionMapper questionMapper;

    /**
     * 题库题服务，用于复用题目响应序列化规则。
     */
    private final BankQuestionService questionService;

    /**
     * JSON 辅助组件，用于读写题目 ID、规则、分值和卷头字段。
     */
    private final JsonSupport json;

    /**
     * 注入试卷、题库题和 JSON 依赖。
     *
     * @param mapper 试卷 Mapper
     * @param questionMapper 题库题 Mapper
     * @param questionService 题库题服务
     * @param json JSON 辅助组件
     */
    public PaperService(
            PaperMapper mapper,
            BankQuestionMapper questionMapper,
            BankQuestionService questionService,
            JsonSupport json
    ) {
        this.mapper = mapper;
        this.questionMapper = questionMapper;
        this.questionService = questionService;
        this.json = json;
    }

    /**
     * 分页查询试卷。
     *
     * @param page 页码，从 1 开始
     * @param pageSize 每页数量
     * @param subject 学科过滤
     * @param grade 年级过滤
     * @param keyword 关键词过滤
     * @return 分页试卷列表
     */
    public Map<String, Object> list(int page, int pageSize, String subject, String grade, String keyword) {
        List<Map<String, Object>> filtered = mapper.selectList(new LambdaQueryWrapper<PaperEntity>()
                        .orderByDesc(PaperEntity::getCreatedAt))
                .stream()
                .filter(entity -> contains(entity.getSubject(), subject))
                .filter(entity -> contains(entity.getGrade(), grade))
                .filter(entity -> matchesKeyword(entity, keyword))
                .map(this::serialize)
                .toList();
        int total = filtered.size();
        int safePage = Math.max(1, page);
        int safePageSize = Math.max(1, pageSize);
        int start = Math.min((safePage - 1) * safePageSize, total);
        int end = Math.min(start + safePageSize, total);
        return Map.of(
                "items", filtered.subList(start, end),
                "total", total,
                "page", safePage,
                "pageSize", safePageSize
        );
    }

    /**
     * 查询单张试卷。
     *
     * @param id 试卷 ID
     * @return 试卷响应 Map
     */
    public Map<String, Object> get(String id) {
        return serialize(required(id));
    }

    /**
     * 创建试卷。
     *
     * @param payload 试卷载荷
     * @return 新建试卷响应 Map
     */
    public Map<String, Object> create(Map<String, Object> payload) {
        LocalDateTime now = LocalDateTime.now();
        PaperEntity entity = new PaperEntity();
        entity.setId(Ids.next("paper"));
        entity.setCreatedAt(now);
        entity.setUpdatedAt(now);
        applyPayload(entity, payload, true);
        mapper.insert(entity);
        return serialize(entity);
    }

    /**
     * 更新试卷。
     *
     * @param id 试卷 ID
     * @param payload 更新载荷
     * @return 更新后的试卷响应 Map
     */
    public Map<String, Object> update(String id, Map<String, Object> payload) {
        PaperEntity entity = required(id);
        LocalDateTime createdAt = entity.getCreatedAt();
        applyPayload(entity, payload, false);
        entity.setId(id);
        entity.setCreatedAt(createdAt == null ? LocalDateTime.now() : createdAt);
        entity.setUpdatedAt(LocalDateTime.now());
        mapper.updateById(entity);
        return serialize(entity);
    }

    /**
     * 删除试卷。
     *
     * @param id 试卷 ID
     * @return 删除结果
     */
    public Map<String, Object> delete(String id) {
        if (mapper.deleteById(id) == 0) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Paper not found");
        }
        return Map.of("deleted", true);
    }

    /**
     * 查询必需存在的试卷实体。
     *
     * @param id 试卷 ID
     * @return 试卷实体
     */
    public PaperEntity required(String id) {
        PaperEntity entity = mapper.selectById(id);
        if (entity == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Paper not found");
        }
        return entity;
    }

    /**
     * 将试卷实体序列化为 API 响应。
     *
     * <p>序列化时会展开 questionIds 对应的题库题，并用试卷分值覆盖题目默认分值，同时计算
     * 题目数量和总分。</p>
     *
     * @param entity 试卷实体
     * @return 试卷响应 Map
     */
    public Map<String, Object> serialize(PaperEntity entity) {
        List<String> questionIds = json.stringList(json.readList(entity.getQuestionIdsJson()));
        Map<String, Double> scores = json.doubleMap(json.readMap(entity.getScoresJson()));
        List<Map<String, Object>> questions = new ArrayList<>();
        for (String questionId : questionIds) {
            BankQuestionEntity question = questionMapper.selectById(questionId);
            if (question == null) {
                continue;
            }
            Map<String, Object> item = new LinkedHashMap<>(questionService.toMap(question));
            item.put("score", scores.getOrDefault(questionId, number(item.get("score"))));
            questions.add(item);
        }
        double totalScore = questions.stream().mapToDouble(item -> number(item.get("score"))).sum();
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("id", entity.getId());
        item.put("title", entity.getTitle());
        item.put("subject", value(entity.getSubject()));
        item.put("grade", value(entity.getGrade()));
        item.put("questionIds", questionIds);
        item.put("rules", json.readMap(entity.getRulesJson()));
        item.put("answerDisplay", value(entity.getAnswerDisplay(), "teacher"));
        item.put("scores", scores);
        item.put("subSelections", json.readMap(entity.getSubSelectionsJson()));
        item.put("header", json.readMap(entity.getHeaderJson()));
        item.put("status", value(entity.getStatus(), "已发布"));
        item.put("createdAt", entity.getCreatedAt());
        item.put("updatedAt", entity.getUpdatedAt());
        item.put("questions", questions);
        item.put("questionCount", questions.size());
        item.put("totalScore", totalScore);
        return item;
    }

    /**
     * 插入旧数据迁移得到的试卷。
     *
     * @param entity 迁移实体
     */
    public void insertMigrated(PaperEntity entity) {
        if (entity.getId() != null && mapper.selectById(entity.getId()) == null) {
            mapper.insert(entity);
        }
    }

    /**
     * 将请求载荷应用到试卷实体。
     *
     * @param entity 试卷实体
     * @param payload 请求载荷
     */
    private void applyPayload(PaperEntity entity, Map<String, Object> payload, boolean create) {
        String title = text(payload.get("title"));
        if (title.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "试卷标题不能为空");
        }
        Map<String, Object> header = payload.get("header") instanceof Map<?, ?> map
                ? new LinkedHashMap<>((Map<String, Object>) map)
                : new LinkedHashMap<>();
        entity.setTitle(title);
        entity.setSubject(value(text(payload.get("subject")), text(header.get("subject"))));
        entity.setGrade(value(text(payload.get("grade")), text(header.get("grade"))));
        List<String> questionIds = json.stringList(payload.get("questionIds"));
        if (questionIds.isEmpty()) {
            questionIds = selectQuestionsByRules(payload.get("rules"));
        }
        entity.setQuestionIdsJson(json.write(questionIds));
        entity.setRulesJson(json.write(payload.get("rules") == null ? Map.of() : payload.get("rules")));
        entity.setAnswerDisplay(value(text(payload.get("answerDisplay")), "teacher"));
        entity.setScoresJson(json.write(buildScores(questionIds, payload.get("scores"))));
        if (create || payload.containsKey("subSelections")) {
            entity.setSubSelectionsJson(json.write(payload.get("subSelections") == null ? Map.of() : payload.get("subSelections")));
        }
        entity.setHeaderJson(json.write(header));
        entity.setStatus(value(text(payload.get("status")), "已发布"));
    }

    /**
     * 根据规则选择题目。
     *
     * <p>当前规则实现为按创建时间倒序取指定数量题目，后续可在此替换为按题型、难度、
     * 知识点和分值约束的组卷策略。</p>
     *
     * @param rawRules 原始规则对象
     * @return 选中的题目 ID 列表
     */
    private List<String> selectQuestionsByRules(Object rawRules) {
        Map<String, Object> rules = rawRules instanceof Map<?, ?> map
                ? new LinkedHashMap<>((Map<String, Object>) map)
                : Map.of();
        int count = (int) number(rules.getOrDefault("count", 10));
        return questionMapper.selectList(new LambdaQueryWrapper<BankQuestionEntity>()
                        .orderByDesc(BankQuestionEntity::getCreatedAt))
                .stream()
                .limit(Math.max(1, count))
                .map(BankQuestionEntity::getId)
                .toList();
    }

    /**
     * 构建试卷题目分值表。
     *
     * @param questionIds 试卷题目 ID 列表
     * @param rawScores 请求中提供的分值 Map
     * @return 题目 ID 到分值的映射
     */
    private Map<String, Double> buildScores(List<String> questionIds, Object rawScores) {
        Map<String, Double> provided = json.doubleMap(rawScores);
        Map<String, Double> scores = new LinkedHashMap<>();
        for (String questionId : questionIds) {
            BankQuestionEntity question = questionMapper.selectById(questionId);
            double defaultScore = question == null || question.getScore() == null ? 0 : question.getScore();
            scores.put(questionId, provided.getOrDefault(questionId, defaultScore));
        }
        return scores;
    }

    /**
     * 判断试卷是否命中关键词。
     *
     * @param entity 试卷实体
     * @param keyword 关键词
     * @return true 表示命中或关键词为空
     */
    private boolean matchesKeyword(PaperEntity entity, String keyword) {
        if (keyword == null || keyword.isBlank()) {
            return true;
        }
        return contains(entity.getTitle(), keyword)
                || contains(entity.getSubject(), keyword)
                || contains(entity.getGrade(), keyword)
                || contains(entity.getStatus(), keyword);
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
     * 将对象转换为数字。
     *
     * @param value 原始值
     * @return 数字；无法解析时返回 0
     */
    private double number(Object value) {
        if (value instanceof Number number) return number.doubleValue();
        if (value == null || String.valueOf(value).isBlank()) return 0;
        try {
            return Double.parseDouble(String.valueOf(value));
        } catch (NumberFormatException ex) {
            return 0;
        }
    }
}
