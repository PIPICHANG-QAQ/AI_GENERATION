package com.aigeneration.questionbank.domain.controller;

import com.aigeneration.questionbank.domain.service.ImportTaskMetadataBridgeService;
import java.util.Map;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.bind.annotation.RestController;

/**
 * 导入任务元数据桥接控制器。
 *
 * <p>该控制器承载导入任务列表、创建、详情、原文件预览、更新和删除接口。Java 负责保存任务元数据、
 * 原文件记录和题目快照，必要时兼容旧 Python worker 任务结构。</p>
 */
@RestController
@RequestMapping("/api/import-tasks")
public class ImportTaskMetadataBridgeController {
    /** 导入任务元数据桥接服务，负责 Java 本地状态和旧 worker 响应同步。 */
    private final ImportTaskMetadataBridgeService service;

    /**
     * 创建导入任务元数据控制器。
     *
     * @param service 导入任务元数据桥接服务
     */
    public ImportTaskMetadataBridgeController(ImportTaskMetadataBridgeService service) {
        this.service = service;
    }

    /**
     * 查询导入任务列表。
     *
     * @return items/total 结构的导入任务列表
     */
    @GetMapping
    public Map<String, Object> list() {
        return service.list();
    }

    /**
     * 创建导入任务。
     *
     * @param stage 学段
     * @param subject 学科
     * @param grade 年级
     * @param region 地区
     * @param year 年份
     * @param title 任务标题
     * @param paperFile 必填试卷文件
     * @param answerFile 可选答案文件
     * @return 创建并同步后的导入任务详情
     */
    @PostMapping(consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public Map<String, Object> create(
            @RequestParam(defaultValue = "") String stage,
            @RequestParam(defaultValue = "") String subject,
            @RequestParam(defaultValue = "") String grade,
            @RequestParam(defaultValue = "") String region,
            @RequestParam(defaultValue = "") String year,
            @RequestParam(defaultValue = "") String title,
            @RequestParam("paperFile") MultipartFile paperFile,
            @RequestParam(value = "answerFile", required = false) MultipartFile answerFile
    ) {
        return service.create(stage, subject, grade, region, year, title, paperFile, answerFile);
    }

    /**
     * 批量删除导入任务。
     *
     * @param payload 包含任务 ID 列表的请求体
     * @return 删除数量和删除结果
     */
    @PostMapping("/batch-delete")
    public Map<String, Object> batchDelete(@RequestBody Map<String, Object> payload) {
        return service.batchDelete(payload);
    }

    /**
     * 查询导入任务详情。
     *
     * @param taskId 导入任务 ID
     * @return 导入任务详情、OCR 状态、题目和题图快照
     */
    @GetMapping("/{taskId}")
    public Map<String, Object> get(@PathVariable String taskId) {
        return service.get(taskId);
    }

    /**
     * 预览导入任务原文件。
     *
     * @param taskId 导入任务 ID
     * @param kind 文件类型，通常为 paper 或 answer
     * @return 原文件响应；Java 文件缺失时可 fallback 到旧 Python worker
     */
    @GetMapping("/{taskId}/source/{kind}")
    public ResponseEntity<?> source(@PathVariable String taskId, @PathVariable String kind) {
        return service.source(taskId, kind);
    }

    /**
     * 预览导入任务试卷的单页渲染图。
     *
     * @param taskId 导入任务 ID
     * @param pageIndex 从 0 开始的页码
     * @return 试卷页图响应，用于前端叠加布局解析框
     */
    @GetMapping("/{taskId}/source/paper/pages/{pageIndex}")
    public ResponseEntity<?> sourcePaperPage(@PathVariable String taskId, @PathVariable int pageIndex) {
        return service.sourcePaperPage(taskId, pageIndex);
    }

    /**
     * 更新导入任务元数据。
     *
     * @param taskId 导入任务 ID
     * @param payload 待更新字段
     * @return 更新后的导入任务详情
     */
    @PutMapping("/{taskId}")
    public Map<String, Object> update(@PathVariable String taskId, @RequestBody Map<String, Object> payload) {
        return service.update(taskId, payload);
    }

    /**
     * 删除导入任务。
     *
     * @param taskId 导入任务 ID
     * @return 删除结果
     */
    @DeleteMapping("/{taskId}")
    public Map<String, Object> delete(@PathVariable String taskId) {
        return service.delete(taskId);
    }
}
