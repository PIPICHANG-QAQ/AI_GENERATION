package com.aigeneration.questionbank.domain.controller;

import com.aigeneration.questionbank.domain.service.KnowledgePointService;
import java.util.Map;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 知识点库控制器。
 *
 * <p>该控制器维护 Java 本地知识点快照，支持本地闭环；企业平台若已有权威知识点主数据，
 * 可把该模块作为读取和映射缓存，而不是最终主数据源。</p>
 */
@RestController
@RequestMapping("/api/knowledge-points")
public class KnowledgePointController {
    /** 知识点业务服务，负责知识点 CRUD 和列表输出。 */
    private final KnowledgePointService service;

    /**
     * 创建知识点控制器。
     *
     * @param service 知识点服务
     */
    public KnowledgePointController(KnowledgePointService service) {
        this.service = service;
    }

    /**
     * 查询知识点列表。
     *
     * @return 知识点 items/total 结构
     */
    @GetMapping
    public Map<String, Object> list() {
        return service.list();
    }

    /**
     * 创建知识点。
     *
     * @param payload 知识点名称、学科、年级、父级和描述等字段
     * @return 创建后的知识点快照
     */
    @PostMapping
    public Map<String, Object> create(@RequestBody Map<String, Object> payload) {
        return service.create(payload);
    }

    /**
     * 更新知识点。
     *
     * @param id 知识点 ID
     * @param payload 待更新字段
     * @return 更新后的知识点快照
     */
    @PutMapping("/{id}")
    public Map<String, Object> update(@PathVariable String id, @RequestBody Map<String, Object> payload) {
        return service.update(id, payload);
    }

    /**
     * 删除知识点。
     *
     * @param id 知识点 ID
     * @return 删除结果
     */
    @DeleteMapping("/{id}")
    public Map<String, Object> delete(@PathVariable String id) {
        return service.delete(id);
    }
}
