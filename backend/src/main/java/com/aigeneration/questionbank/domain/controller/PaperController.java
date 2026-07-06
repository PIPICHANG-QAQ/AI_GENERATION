package com.aigeneration.questionbank.domain.controller;

import com.aigeneration.questionbank.domain.service.PaperService;
import com.aigeneration.questionbank.domain.service.PaperExportFlowService;
import java.util.Map;
import org.springframework.core.io.Resource;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 试卷控制器。
 *
 * <p>该控制器维护 Java 本地组卷定义，支持试卷列表、创建、详情、更新、删除和导出。
 * 导出由 export-flow 编排，最终会调用 Python worker 执行 Pandoc/LaTeX 渲染。</p>
 */
@RestController
@RequestMapping("/api/papers")
public class PaperController {
    /** 试卷业务服务，负责试卷定义和题目引用 CRUD。 */
    private final PaperService service;
    /** 试卷导出服务，负责导出 job、worker 调用和文件响应。 */
    private final PaperExportFlowService exportFlowService;

    /**
     * 创建试卷控制器。
     *
     * @param service 试卷业务服务
     * @param exportFlowService 试卷导出服务
     */
    public PaperController(PaperService service, PaperExportFlowService exportFlowService) {
        this.service = service;
        this.exportFlowService = exportFlowService;
    }

    /**
     * 查询试卷列表。
     *
     * @param page 页码，从 1 开始
     * @param pageSize 每页数量
     * @param subject 可选学科过滤
     * @param grade 可选年级过滤
     * @param keyword 可选关键词过滤
     * @return items/total 结构的试卷列表
     */
    @GetMapping
    public Map<String, Object> list(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "6") int pageSize,
            @RequestParam(defaultValue = "") String subject,
            @RequestParam(defaultValue = "") String grade,
            @RequestParam(defaultValue = "") String keyword
    ) {
        return service.list(page, pageSize, subject, grade, keyword);
    }

    /**
     * 创建试卷。
     *
     * @param payload 试卷标题、学科、年级、题目引用和卷头配置
     * @return 创建后的试卷快照
     */
    @PostMapping
    public Map<String, Object> create(@RequestBody Map<String, Object> payload) {
        return service.create(payload);
    }

    /**
     * 查询试卷详情。
     *
     * @param id 试卷 ID
     * @return 试卷定义、题目引用和统计信息
     */
    @GetMapping("/{id}")
    public Map<String, Object> get(@PathVariable String id) {
        return service.get(id);
    }

    /**
     * 导出试卷文件。
     *
     * @param id 试卷 ID
     * @param format 导出格式，通常为 docx 或 pdf
     * @param variant 导出变体，例如 teacher 或 student
     * @return 导出的文件资源响应
     */
    @GetMapping("/{id}/export")
    public ResponseEntity<Resource> export(
            @PathVariable String id,
            @RequestParam(defaultValue = "docx") String format,
            @RequestParam(defaultValue = "teacher") String variant
    ) {
        return exportFlowService.export(id, format, variant);
    }

    /**
     * 更新试卷。
     *
     * @param id 试卷 ID
     * @param payload 待更新字段
     * @return 更新后的试卷快照
     */
    @PutMapping("/{id}")
    public Map<String, Object> update(@PathVariable String id, @RequestBody Map<String, Object> payload) {
        return service.update(id, payload);
    }

    /**
     * 删除试卷。
     *
     * @param id 试卷 ID
     * @return 删除结果
     */
    @DeleteMapping("/{id}")
    public Map<String, Object> delete(@PathVariable String id) {
        return service.delete(id);
    }
}
