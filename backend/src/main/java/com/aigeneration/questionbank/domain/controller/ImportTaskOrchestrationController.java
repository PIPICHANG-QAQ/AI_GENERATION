package com.aigeneration.questionbank.domain.controller;

import com.aigeneration.questionbank.domain.service.ImportTaskOrchestrationService;
import java.util.Map;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 导入任务编排控制器。
 *
 * <p>当前只暴露重试入口，用于把失败或可重试的导入任务重新交给 Java/Python 编排链路处理。</p>
 */
@RestController
public class ImportTaskOrchestrationController {
    /** 导入任务编排服务，负责重试策略和任务状态切换。 */
    private final ImportTaskOrchestrationService service;

    /**
     * 创建导入任务编排控制器。
     *
     * @param service 导入任务编排服务
     */
    public ImportTaskOrchestrationController(ImportTaskOrchestrationService service) {
        this.service = service;
    }

    /**
     * 重试导入任务。
     *
     * @param taskId 导入任务 ID
     * @return 重试后的任务状态和同步结果
     */
    @PostMapping("/api/import-tasks/{taskId}/retry")
    public Map<String, Object> retry(@PathVariable String taskId) {
        return service.retry(taskId);
    }

    /**
     * 重新扫描导入任务原始 OCR 文件。
     *
     * @param taskId 导入任务 ID
     * @return 重扫启动后的任务状态
     */
    @PostMapping("/api/import-tasks/{taskId}/rescan")
    public Map<String, Object> rescan(@PathVariable String taskId) {
        return service.rescan(taskId);
    }
}
