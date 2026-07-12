package com.aigeneration.questionbank.domain.service;

import com.aigeneration.questionbank.domain.entity.ImportQuestionEntity;
import com.aigeneration.questionbank.domain.entity.ImportQuestionImageEntity;
import com.aigeneration.questionbank.domain.mapper.ImportQuestionImageMapper;
import com.aigeneration.questionbank.domain.mapper.ImportQuestionMapper;
import com.aigeneration.questionbank.domain.support.JsonSupport;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.format.DateTimeParseException;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashSet;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 导入题目同步服务。
 *
 * <p>负责把导入任务中的题目数组同步为 Java 侧题目表和题图表，并提供 AI 结果回写、
 * 人工追加题图、题目快照序列化等能力。</p>
 */
@Service
public class ImportQuestionSyncService {
    /**
     * 导入题目表访问对象。
     */
    private final ImportQuestionMapper questionMapper;

    /**
     * 导入题图表访问对象。
     */
    private final ImportQuestionImageMapper imageMapper;

    /**
     * JSON 辅助组件，用于读写题目中的数组和原始快照字段。
     */
    private final JsonSupport json;

    /**
     * 注入题目、题图 Mapper 和 JSON 工具。
     *
     * @param questionMapper 导入题目 Mapper
     * @param imageMapper 导入题图 Mapper
     * @param json JSON 辅助组件
     */
    public ImportQuestionSyncService(
            ImportQuestionMapper questionMapper,
            ImportQuestionImageMapper imageMapper,
            JsonSupport json
    ) {
        this.questionMapper = questionMapper;
        this.imageMapper = imageMapper;
        this.json = json;
    }

    /**
     * 同步指定任务下的题目列表。
     *
     * <p>同步完成后会删除 Java 表中已经不在 worker 返回列表内的题目，保证任务快照与
     * worker 最新结果一致。</p>
     *
     * @param taskId 导入任务 ID
     * @param value 预期为题目 Map 列表
     */
    public void syncQuestions(String taskId, Object value) {
        if (taskId == null || taskId.isBlank() || !(value instanceof List<?> questions)) {
            return;
        }
        Set<String> seenIds = new LinkedHashSet<>();
        for (Object item : questions) {
            if (item instanceof Map<?, ?> raw) {
                String id = text(raw.get("id"));
                if (!id.isBlank()) {
                    seenIds.add(id);
                }
                syncQuestion(taskId, raw);
            }
        }
        deleteMissingQuestions(taskId, seenIds);
    }

    /**
     * 根据题目 ID 查询导入题目实体。
     *
     * @param id 题目 ID
     * @return 导入题目实体；不存在时返回 null
     */
    public ImportQuestionEntity getQuestion(String id) {
        return questionMapper.selectById(id);
    }

    /**
     * 查询任务下的题目并按题号排序。
     *
     * @param taskId 任务 ID
     * @return 导入题目列表
     */
    public List<ImportQuestionEntity> listByTask(String taskId) {
        return questionMapper.selectList(new QueryWrapper<ImportQuestionEntity>()
                .eq("task_id", taskId)
                .orderByAsc("question_number"));
    }

    /**
     * 查询题目下的题图并按图片顺序排序。
     *
     * @param questionId 题目 ID
     * @return 题图实体列表
     */
    public List<ImportQuestionImageEntity> listImages(String questionId) {
        return imageMapper.selectList(new QueryWrapper<ImportQuestionImageEntity>()
                .eq("question_id", questionId)
                .orderByAsc("image_index"));
    }

    /**
     * 查询任务下全部题图。
     *
     * @param taskId 任务 ID
     * @return 题图实体列表
     */
    public List<ImportQuestionImageEntity> listImagesByTask(String taskId) {
        return imageMapper.selectList(new QueryWrapper<ImportQuestionImageEntity>()
                .eq("task_id", taskId)
                .orderByAsc("question_id")
                .orderByAsc("image_index"));
    }

    /**
     * 为导入题目追加题图。
     *
     * <p>方法会合并已有题图和新上传题图，并按 storageFileId/url/path/name 去重后重建题图表。</p>
     *
     * @param taskId 任务 ID
     * @param questionId 题目 ID
     * @param uploaded 新上传题图元数据
     * @return 合并后的题图列表；题目不存在或任务不匹配时返回空列表
     */
    public List<Object> appendImages(String taskId, String questionId, List<Map<String, Object>> uploaded) {
        ImportQuestionEntity question = questionMapper.selectById(questionId);
        if (question == null || !taskId.equals(question.getTaskId())) {
            return List.of();
        }
        List<Object> images = mergeImages(json.readList(question.getImagesJson()), uploaded);
        replaceImages(question, images);
        return images;
    }

    /**
     * 回写 AI 标准化结果。
     *
     * @param taskId 任务 ID
     * @param questionId 题目 ID
     * @param markdown 标准化后的 Markdown
     * @param answer AI 回填答案
     * @param analysis AI 回填解析
     * @param aiResponse AI 原始响应
     * @return 更新后的题目实体；题目不存在或任务不匹配时返回 null
     */
    @Transactional
    public ImportQuestionEntity updateStandardizedResult(String taskId, String questionId, String markdown, String answer, String analysis, Map<String, Object> aiResponse) {
        ImportQuestionEntity question = questionMapper.selectById(questionId);
        if (question == null || !taskId.equals(question.getTaskId())) {
            return null;
        }
        List<Object> children = mergeAiSubQuestions(json.readList(question.getChildrenJson()), aiResponse);
        boolean hasSubQuestions = !children.isEmpty();
        if (hasSubQuestions) {
            question.setChildrenJson(json.write(children));
        }
        if (markdown != null && !markdown.isBlank()) {
            question.setManualMarkdown(markdown);
        }
        if (hasSubQuestions) {
            question.setAnalysis("");
            question.setAnswer("");
        } else if (analysis != null && !analysis.isBlank()) {
            question.setAnalysis(analysis);
        }
        if (!hasSubQuestions && answer != null && !answer.isBlank()) {
            question.setAnswer(answer);
        }
        List<Object> responseOptions = listValue(aiResponse.get("options"));
        List<Object> responseImages = listValue(aiResponse.get("images"));
        List<Object> responsePlacements = listValue(aiResponse.get("imagePlacements"));
        if (!responseOptions.isEmpty()) {
            question.setOptionsJson(json.write(responseOptions));
        }
        if (!responseImages.isEmpty()) {
            question.setImagesJson(json.write(responseImages));
        }
        if (!responsePlacements.isEmpty()) {
            question.setImagePlacementsJson(json.write(responsePlacements));
        }
        Map<String, Object> raw = json.readMap(question.getRawJson());
        raw.put("aiLastStandardizeResponse", aiResponse);
        raw.put("manualMarkdown", question.getManualMarkdown());
        raw.put("analysis", question.getAnalysis());
        raw.put("answer", question.getAnswer());
        raw.put("children", children);
        raw.put("subQuestions", children);
        raw.put("options", json.readList(question.getOptionsJson()));
        raw.put("images", json.readList(question.getImagesJson()));
        raw.put("imagePlacements", json.readList(question.getImagePlacementsJson()));
        question.setRawJson(json.write(raw));
        question.setUpdatedAt(LocalDateTime.now());
        questionMapper.updateById(question);
        if (!responseImages.isEmpty()) {
            syncImages(taskId, questionId, responseImages, question.getUpdatedAt());
        }
        return question;
    }

    /**
     * 回写 AI 解析/答案匹配结果。
     *
     * @param taskId 任务 ID
     * @param questionId 题目 ID
     * @param analysis AI 解析
     * @param answer AI 答案
     * @param aiResponse AI 原始响应
     * @return 更新后的题目实体；题目不存在或任务不匹配时返回 null
     */
    public ImportQuestionEntity updateAiResult(String taskId, String questionId, String analysis, String answer, Map<String, Object> aiResponse) {
        ImportQuestionEntity question = questionMapper.selectById(questionId);
        if (question == null || !taskId.equals(question.getTaskId())) {
            return null;
        }
        List<Object> children = mergeAiSubQuestions(json.readList(question.getChildrenJson()), aiResponse);
        boolean hasSubQuestions = !children.isEmpty();
        if (hasSubQuestions) {
            question.setChildrenJson(json.write(children));
            question.setAnalysis("");
            question.setAnswer("");
        } else if (analysis != null && !analysis.isBlank()) {
            question.setAnalysis(analysis);
        }
        if (!hasSubQuestions && answer != null && !answer.isBlank()) {
            question.setAnswer(answer);
        }
        Map<String, Object> raw = json.readMap(question.getRawJson());
        raw.put("aiLastResponse", aiResponse);
        raw.put("analysis", question.getAnalysis());
        raw.put("answer", question.getAnswer());
        raw.put("children", children);
        raw.put("subQuestions", children);
        question.setRawJson(json.write(raw));
        question.setUpdatedAt(LocalDateTime.now());
        questionMapper.updateById(question);
        return question;
    }

    /**
     * 将人工编辑载荷写入 Java 侧导入题快照。
     *
     * <p>正常路径下编辑请求会先写 worker 再同步 Java；该方法用于 worker 临时不可用时的
     * 本地兜底，也保证历史记录和入库读取的是最新人工编辑内容。</p>
     *
     * @param taskId 任务 ID
     * @param questionId 导入题 ID
     * @param payload 前端编辑载荷
     * @return 更新后的题目实体；题目不存在或任务不匹配时返回 null
     */
    public ImportQuestionEntity updateQuestionFromPayload(String taskId, String questionId, Map<String, Object> payload) {
        ImportQuestionEntity question = questionMapper.selectById(questionId);
        if (question == null || !taskId.equals(question.getTaskId())) {
            return null;
        }
        Map<String, Object> raw = json.readMap(question.getRawJson());
        LocalDateTime now = LocalDateTime.now();
        boolean imagesChanged = false;

        if (payload.containsKey("type")) {
            question.setType(text(payload.get("type")));
        }
        if (payload.containsKey("status")) {
            question.setStatus(text(payload.get("status")));
        }
        if (payload.containsKey("stemMarkdown")) {
            question.setStemMarkdown(text(payload.get("stemMarkdown")));
        }
        if (payload.containsKey("manualMarkdown")) {
            question.setManualMarkdown(text(payload.get("manualMarkdown")));
            raw.put("manualEditedAt", now.toString());
        }
        if (payload.containsKey("answer")) {
            question.setAnswer(text(payload.get("answer")));
        }
        if (payload.containsKey("analysis")) {
            question.setAnalysis(text(payload.get("analysis")));
        }
        if (payload.containsKey("knowledgePointIds")) {
            question.setKnowledgePointIdsJson(json.write(payload.get("knowledgePointIds")));
        }
        if (payload.containsKey("knowledgePoints")) {
            question.setKnowledgePointsJson(json.write(payload.get("knowledgePoints")));
        }
        if (payload.containsKey("difficulty")) {
            question.setDifficulty(text(payload.get("difficulty")));
        }
        if (payload.containsKey("score")) {
            question.setScore(decimal(payload.get("score")));
        }
        if (payload.containsKey("images")) {
            question.setImagesJson(json.write(payload.get("images")));
            imagesChanged = true;
        }
        if (payload.containsKey("imagePlacements")) {
            question.setImagePlacementsJson(json.write(payload.get("imagePlacements")));
        }
        if (payload.containsKey("options")) {
            question.setOptionsJson(json.write(payload.get("options")));
        }
        if (payload.containsKey("mathValidation")) {
            question.setMathValidationJson(json.write(payload.get("mathValidation")));
        }
        if (payload.containsKey("subQuestions") || payload.containsKey("children")) {
            Object children = payload.containsKey("subQuestions") ? payload.get("subQuestions") : payload.get("children");
            question.setChildrenJson(json.write(children));
            if (!listValue(children).isEmpty()) {
                question.setAnswer("");
                question.setAnalysis("");
            }
        } else if (!json.readList(question.getChildrenJson()).isEmpty()) {
            question.setAnswer("");
            question.setAnalysis("");
        }

        question.setUpdatedAt(now);
        mergeRawQuestionFields(raw, question);
        question.setRawJson(json.write(raw));
        questionMapper.updateById(question);
        if (imagesChanged) {
            syncImages(taskId, questionId, payload.get("images"), now);
        }
        return question;
    }

    /**
     * 删除任务下所有导入题目和题图快照。
     *
     * @param taskId 任务 ID
     */
    public void deleteByTask(String taskId) {
        if (taskId == null || taskId.isBlank()) {
            return;
        }
        questionMapper.delete(new QueryWrapper<ImportQuestionEntity>().eq("task_id", taskId));
        imageMapper.delete(new QueryWrapper<ImportQuestionImageEntity>().eq("task_id", taskId));
    }

    /**
     * 同步单道题目快照。
     *
     * @param taskId 任务 ID
     * @param raw worker 返回的题目 Map
     */
    private void syncQuestion(String taskId, Map<?, ?> raw) {
        String id = text(raw.get("id"));
        if (id.isBlank()) {
            return;
        }
        LocalDateTime now = LocalDateTime.now();
        ImportQuestionEntity entity = questionMapper.selectById(id);
        LocalDateTime createdAt = entity == null ? null : entity.getCreatedAt();
        if (entity == null) {
            entity = new ImportQuestionEntity();
            entity.setId(id);
        }
        entity.setTaskId(taskId);
        entity.setSourceQuestionId(text(raw.get("sourceQuestionId")));
        entity.setQuestionNumber(integer(raw.get("number")));
        entity.setStatus(text(raw.get("status")));
        entity.setType(text(raw.get("type")));
        entity.setStemMarkdown(text(raw.get("stemMarkdown")));
        entity.setManualMarkdown(text(raw.get("manualMarkdown")));
        List<Object> children = listValue(raw.containsKey("subQuestions") ? raw.get("subQuestions") : raw.get("children"));
        entity.setAnswer(children.isEmpty() ? text(raw.get("answer")) : "");
        entity.setAnalysis(children.isEmpty() ? text(raw.get("analysis")) : "");
        entity.setKnowledgePointIdsJson(json.write(raw.get("knowledgePointIds")));
        entity.setKnowledgePointsJson(json.write(raw.get("knowledgePoints")));
        entity.setDifficulty(text(raw.get("difficulty")));
        entity.setScore(decimal(raw.get("score")));
        entity.setImagesJson(json.write(raw.get("images")));
        entity.setImagePlacementsJson(json.write(raw.get("imagePlacements")));
        entity.setOptionsJson(json.write(raw.get("options")));
        entity.setChildrenJson(json.write(children));
        entity.setMathValidationJson(json.write(raw.get("mathValidation")));
        entity.setRawJson(json.write(raw));
        entity.setCreatedAt(parseTime(raw.get("createdAt"), createdAt == null ? now : createdAt));
        entity.setUpdatedAt(parseTime(raw.get("updatedAt"), now));
        if (questionMapper.selectById(id) == null) {
            questionMapper.insert(entity);
        } else {
            questionMapper.updateById(entity);
        }
        syncImages(taskId, id, raw.get("images"), entity.getUpdatedAt());
    }

    /**
     * 重建题目对应的题图快照。
     *
     * @param taskId 任务 ID
     * @param questionId 题目 ID
     * @param value 原始题图列表
     * @param updatedAt 题目更新时间
     */
    private void syncImages(String taskId, String questionId, Object value, LocalDateTime updatedAt) {
        imageMapper.delete(new QueryWrapper<ImportQuestionImageEntity>().eq("question_id", questionId));
        if (!(value instanceof List<?> images)) {
            return;
        }
        LocalDateTime now = updatedAt == null ? LocalDateTime.now() : updatedAt;
        for (int index = 0; index < images.size(); index++) {
            Object item = images.get(index);
            if (!(item instanceof Map<?, ?> raw)) {
                continue;
            }
            ImportQuestionImageEntity image = new ImportQuestionImageEntity();
            image.setId(imageId(taskId, questionId, index));
            image.setTaskId(taskId);
            image.setQuestionId(questionId);
            image.setImageIndex(index);
            image.setName(text(raw.get("name")));
            image.setPath(text(raw.get("path")));
            image.setUrl(text(raw.get("url")));
            image.setRawJson(json.write(raw));
            image.setCreatedAt(now);
            image.setUpdatedAt(now);
            imageMapper.insert(image);
        }
    }

    /**
     * 替换题目内嵌题图 JSON 并同步题图表。
     *
     * @param question 题目实体
     * @param images 新题图列表
     */
    private void replaceImages(ImportQuestionEntity question, List<Object> images) {
        LocalDateTime now = LocalDateTime.now();
        question.setImagesJson(json.write(images));
        Map<String, Object> raw = json.readMap(question.getRawJson());
        raw.put("images", images);
        question.setRawJson(json.write(raw));
        question.setUpdatedAt(now);
        questionMapper.updateById(question);
        syncImages(question.getTaskId(), question.getId(), images, now);
    }

    /**
     * 将实体字段回写到原始题目快照，保持旧 worker 兼容字段一致。
     *
     * @param raw 原始题目 Map
     * @param question 已更新的题目实体
     */
    private void mergeRawQuestionFields(Map<String, Object> raw, ImportQuestionEntity question) {
        raw.put("id", question.getId());
        raw.put("taskId", question.getTaskId());
        raw.put("sourceQuestionId", question.getSourceQuestionId());
        raw.put("number", question.getQuestionNumber());
        raw.put("status", question.getStatus());
        raw.put("type", question.getType());
        raw.put("stemMarkdown", question.getStemMarkdown());
        raw.put("manualMarkdown", question.getManualMarkdown());
        raw.put("answer", question.getAnswer());
        raw.put("analysis", question.getAnalysis());
        raw.put("knowledgePointIds", json.readList(question.getKnowledgePointIdsJson()));
        raw.put("knowledgePoints", json.readList(question.getKnowledgePointsJson()));
        raw.put("difficulty", question.getDifficulty());
        raw.put("score", question.getScore());
        raw.put("images", json.readList(question.getImagesJson()));
        raw.put("imagePlacements", json.readList(question.getImagePlacementsJson()));
        raw.put("options", json.readList(question.getOptionsJson()));
        List<Object> children = json.readList(question.getChildrenJson());
        raw.put("children", children);
        raw.put("subQuestions", children);
        raw.put("mathValidation", json.readMap(question.getMathValidationJson()));
        raw.put("updatedAt", question.getUpdatedAt());
    }

    /**
     * 合并并去重新旧题图列表。
     *
     * @param existing 已有题图
     * @param appended 新追加题图
     * @return 合并后的题图列表
     */
    private List<Object> mergeImages(List<Object> existing, List<Map<String, Object>> appended) {
        List<Object> images = new ArrayList<>();
        Set<String> seen = new LinkedHashSet<>();
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
     * 提取题图去重键并记录是否首次出现。
     *
     * @param image 题图 Map
     * @param seen 已出现去重键集合
     * @return true 表示该题图有效且未重复
     */
    private boolean imageKey(Object image, Set<String> seen) {
        if (!(image instanceof Map<?, ?> raw)) {
            return false;
        }
        String key = firstText(raw.get("storageFileId"), raw.get("url"), raw.get("path"), raw.get("name"));
        return !key.isBlank() && seen.add(key);
    }

    /**
     * 将导入题目实体序列化为控制器返回 Map。
     *
     * @param question 题目实体
     * @return 题目响应 Map
     */
    public Map<String, Object> toMap(ImportQuestionEntity question) {
        Map<String, Object> item = json.readMap(question.getRawJson());
        item.put("id", question.getId());
        item.put("taskId", question.getTaskId());
        item.put("sourceQuestionId", question.getSourceQuestionId());
        item.put("number", question.getQuestionNumber());
        item.put("status", question.getStatus());
        item.put("type", question.getType());
        item.put("stemMarkdown", question.getStemMarkdown());
        item.put("manualMarkdown", question.getManualMarkdown());
        item.put("answer", question.getAnswer());
        item.put("analysis", question.getAnalysis());
        item.put("knowledgePointIds", json.readList(question.getKnowledgePointIdsJson()));
        item.put("knowledgePoints", json.readList(question.getKnowledgePointsJson()));
        item.put("difficulty", question.getDifficulty());
        item.put("score", question.getScore());
        item.put("images", json.readList(question.getImagesJson()));
        item.put("imagePlacements", json.readList(question.getImagePlacementsJson()));
        item.put("options", json.readList(question.getOptionsJson()));
        List<Object> children = json.readList(question.getChildrenJson());
        item.put("children", children);
        item.put("subQuestions", children);
        item.put("mathValidation", json.readMap(question.getMathValidationJson()));
        item.put("createdAt", question.getCreatedAt());
        item.put("updatedAt", question.getUpdatedAt());
        return item;
    }

    /**
     * 删除 worker 最新结果中已经不存在的题目。
     *
     * @param taskId 任务 ID
     * @param seenIds 本轮同步出现过的题目 ID 集合
     */
    private void deleteMissingQuestions(String taskId, Set<String> seenIds) {
        List<ImportQuestionEntity> existing = questionMapper.selectList(new QueryWrapper<ImportQuestionEntity>().eq("task_id", taskId));
        for (ImportQuestionEntity entity : existing) {
            String id = entity.getId();
            if (id != null && !seenIds.contains(id)) {
                imageMapper.delete(new QueryWrapper<ImportQuestionImageEntity>().eq("question_id", id));
                questionMapper.deleteById(id);
            }
        }
    }

    /**
     * 为题图快照生成稳定 ID。
     *
     * @param taskId 任务 ID
     * @param questionId 题目 ID
     * @param index 题图序号
     * @return 题图 ID
     */
    private String imageId(String taskId, String questionId, int index) {
        String raw = taskId + "|" + questionId + "|" + index;
        return "iqi_" + UUID.nameUUIDFromBytes(raw.getBytes(StandardCharsets.UTF_8));
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
     * 将对象转换为去首尾空白文本。
     *
     * @param value 原始值
     * @return 文本；null 返回空字符串
     */
    private String text(Object value) {
        return value == null ? "" : String.valueOf(value).trim();
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
     * 将对象转换为小数。
     *
     * @param value 原始值
     * @return 小数；无法解析时返回 null
     */
    private Double decimal(Object value) {
        if (value instanceof Number number) {
            return number.doubleValue();
        }
        String text = text(value);
        if (text.isBlank()) {
            return null;
        }
        try {
            return Double.parseDouble(text);
        } catch (NumberFormatException ignored) {
            return null;
        }
    }

    /**
     * 解析题目时间字段。
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
