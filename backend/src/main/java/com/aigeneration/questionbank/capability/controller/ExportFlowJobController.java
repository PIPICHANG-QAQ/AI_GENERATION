package com.aigeneration.questionbank.capability.controller;

import com.aigeneration.questionbank.domain.service.PaperExportFlowService;
import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * Export-Flow 导出任务查询控制器。
 *
 * <p>试卷导出由 {@code /api/papers/{paperId}/export} 创建，该控制器只负责按导出能力查询
 * 已创建的导出 job，便于平台或前端追踪导出状态和失败原因。</p>
 */
@RestController
@RequestMapping("/api/capabilities/export-flow/jobs")
public class ExportFlowJobController {
    /** 试卷导出编排服务，保存导出任务状态并调用 Python 渲染 worker。 */
    private final PaperExportFlowService service;

    /**
     * 创建导出任务查询控制器。
     *
     * @param service 试卷导出服务
     */
    public ExportFlowJobController(PaperExportFlowService service) {
        this.service = service;
    }

    /**
     * 查询导出任务列表。
     *
     * @param paperId 可选试卷 ID；为空时返回全部导出任务
     * @return items/total 结构的导出任务列表
     */
    @GetMapping
    public Map<String, Object> list(@RequestParam(defaultValue = "") String paperId) {
        List<Map<String, Object>> items = service.listJobs(paperId);
        return Map.of("items", items, "total", items.size());
    }

    /**
     * 查询单个导出任务。
     *
     * @param jobId 导出任务 ID
     * @return 导出任务详情
     */
    @GetMapping("/{jobId}")
    public Map<String, Object> get(@PathVariable String jobId) {
        return service.getJob(jobId);
    }
}
