package com.aigeneration.questionbank.domain.controller;

import com.aigeneration.questionbank.domain.service.BankQuestionService;
import java.util.Map;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 题库题目控制器。
 *
 * <p>该控制器维护 Java 本地题库题快照，支持查询、创建、更新和删除。平台若自管最终题库，
 * 可以只消费 question-package，不必调用本地题库写入接口。</p>
 */
@RestController
@RequestMapping("/api/question-bank/questions")
public class BankQuestionController {
    /** 题库题业务服务，负责题目快照 CRUD 和查询过滤。 */
    private final BankQuestionService service;

    /**
     * 创建题库题目控制器。
     *
     * @param service 题库题服务
     */
    public BankQuestionController(BankQuestionService service) {
        this.service = service;
    }

    /**
     * 查询题库题列表。
     *
     * @param filters 查询过滤参数，包括学科、年级、关键词等
     * @return items/total 结构的题库题列表
     */
    @GetMapping
    public Map<String, Object> list(@RequestParam Map<String, String> filters) {
        return service.list(filters);
    }

    /**
     * 创建题库题。
     *
     * @param payload 题干、答案、解析、题型、知识点、题图等字段
     * @return 创建后的题库题快照
     */
    @PostMapping
    public Map<String, Object> create(@RequestBody Map<String, Object> payload) {
        return service.create(payload);
    }

    /**
     * 查询单个题库题。
     *
     * @param id 题库题 ID
     * @return 题库题快照
     */
    @GetMapping("/{id}")
    public Map<String, Object> get(@PathVariable String id) {
        return service.get(id);
    }

    /**
     * 更新题库题。
     *
     * @param id 题库题 ID
     * @param payload 待更新字段
     * @return 更新后的题库题快照
     */
    @PutMapping("/{id}")
    public Map<String, Object> update(@PathVariable String id, @RequestBody Map<String, Object> payload) {
        return service.update(id, payload);
    }

    /**
     * 删除题库题。
     *
     * @param id 题库题 ID
     * @return 删除结果
     */
    @DeleteMapping("/{id}")
    public Map<String, Object> delete(@PathVariable String id) {
        return service.delete(id);
    }
}
