package com.aigeneration.questionbank.domain.controller;

import com.aigeneration.questionbank.domain.service.ImportTaskBankBridgeService;
import java.util.Map;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 导入任务入库桥接控制器。
 *
 * <p>该控制器把导入任务中的待校验题同步到 Java 本地题库快照。它保留与旧 Python 入库接口兼容的路径，
 * 但最终状态落在 Java 题库表中。</p>
 */
@RestController
@RequestMapping("/api/import-tasks")
public class ImportTaskBankBridgeController {
    /** 入库桥接服务，负责单题/批量入库和 Java 题库快照同步。 */
    private final ImportTaskBankBridgeService service;

    /**
     * 创建导入题入库桥接控制器。
     *
     * @param service 入库桥接服务
     */
    public ImportTaskBankBridgeController(ImportTaskBankBridgeService service) {
        this.service = service;
    }

    /**
     * 将导入任务中的单道题入库到本地题库快照。
     *
     * @param taskId 导入任务 ID
     * @param questionId 导入题 ID
     * @return 入库结果和题库题快照
     */
    @PostMapping("/{taskId}/questions/{questionId}/bank")
    public Map<String, Object> bankSingle(@PathVariable String taskId, @PathVariable String questionId) {
        return service.bankSingle(taskId, questionId);
    }

    /**
     * 将导入任务中的所有可入库题批量入库。
     *
     * @param taskId 导入任务 ID
     * @return 批量入库数量、重复题和题库题列表
     */
    @PostMapping("/{taskId}/bank")
    public Map<String, Object> bankAll(@PathVariable String taskId) {
        return service.bankAll(taskId);
    }
}
