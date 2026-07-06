package com.aigeneration.questionbank.domain.service;

import com.aigeneration.questionbank.domain.entity.KnowledgePointEntity;
import com.aigeneration.questionbank.domain.mapper.KnowledgePointMapper;
import com.aigeneration.questionbank.domain.support.Ids;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

/**
 * 知识点服务。
 *
 * <p>负责本地知识点快照的 CRUD 和响应序列化。企业平台若已有权威知识点主数据，可将该
 * 服务替换为只读同步或映射缓存。</p>
 */
@Service
public class KnowledgePointService {
    /**
     * 知识点表访问对象。
     */
    private final KnowledgePointMapper mapper;

    /**
     * 注入知识点 Mapper。
     *
     * @param mapper 知识点 Mapper
     */
    public KnowledgePointService(KnowledgePointMapper mapper) {
        this.mapper = mapper;
    }

    /**
     * 查询知识点列表。
     *
     * @return 知识点列表响应
     */
    public Map<String, Object> list() {
        List<Map<String, Object>> items = mapper.selectList(new LambdaQueryWrapper<KnowledgePointEntity>()
                        .orderByDesc(KnowledgePointEntity::getCreatedAt))
                .stream()
                .map(this::toMap)
                .toList();
        return Map.of("items", items);
    }

    /**
     * 创建知识点。
     *
     * @param payload 创建载荷
     * @return 新建知识点响应 Map
     */
    public Map<String, Object> create(Map<String, Object> payload) {
        LocalDateTime now = LocalDateTime.now();
        KnowledgePointEntity entity = new KnowledgePointEntity();
        entity.setId(Ids.next("kp"));
        applyPayload(entity, payload);
        if (entity.getName() == null || entity.getName().isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "知识点名称不能为空");
        }
        entity.setCreatedAt(now);
        entity.setUpdatedAt(now);
        mapper.insert(entity);
        return toMap(entity);
    }

    /**
     * 更新知识点。
     *
     * @param id 知识点 ID
     * @param payload 更新载荷
     * @return 更新后的知识点响应 Map
     */
    public Map<String, Object> update(String id, Map<String, Object> payload) {
        KnowledgePointEntity entity = mapper.selectById(id);
        if (entity == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Knowledge point not found");
        }
        applyPayload(entity, payload);
        if (entity.getName() == null || entity.getName().isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "知识点名称不能为空");
        }
        entity.setUpdatedAt(LocalDateTime.now());
        mapper.updateById(entity);
        return toMap(entity);
    }

    /**
     * 删除知识点。
     *
     * @param id 知识点 ID
     * @return 删除结果
     */
    public Map<String, Object> delete(String id) {
        if (mapper.deleteById(id) == 0) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Knowledge point not found");
        }
        return Map.of("deleted", true);
    }

    /**
     * 插入旧数据迁移得到的知识点。
     *
     * @param entity 迁移实体
     */
    public void insertMigrated(KnowledgePointEntity entity) {
        if (entity.getId() != null && mapper.selectById(entity.getId()) == null) {
            mapper.insert(entity);
        }
    }

    /**
     * 将请求载荷应用到知识点实体。
     *
     * @param entity 知识点实体
     * @param payload 请求载荷
     */
    private void applyPayload(KnowledgePointEntity entity, Map<String, Object> payload) {
        entity.setName(text(payload.get("name")));
        entity.setParentId(text(payload.get("parentId")));
        entity.setSubject(text(payload.get("subject")));
        entity.setGrade(text(payload.get("grade")));
        entity.setDescription(text(payload.get("description")));
    }

    /**
     * 将知识点实体序列化为 API 响应 Map。
     *
     * @param entity 知识点实体
     * @return 响应 Map
     */
    public Map<String, Object> toMap(KnowledgePointEntity entity) {
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("id", entity.getId());
        item.put("name", entity.getName());
        item.put("parentId", entity.getParentId());
        item.put("subject", entity.getSubject());
        item.put("grade", entity.getGrade());
        item.put("description", entity.getDescription());
        item.put("createdAt", entity.getCreatedAt());
        item.put("updatedAt", entity.getUpdatedAt());
        return item;
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
}
