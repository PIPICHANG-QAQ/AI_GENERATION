package com.aigeneration.questionbank.domain.controller;

import com.aigeneration.questionbank.domain.service.AiFlowOrchestrationService;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * AI-Flow 编排控制器。
 *
 * <p>该控制器暴露导入题、题库题和临时文本的 AI 标准化/解析入口。Java 创建 AI job、
 * 读取题图上下文并写回答案解析，Python worker 只执行模型调用和 Markdown/LaTeX 修复。</p>
 */
@RestController
public class AiFlowController {
    /** AI 编排服务，负责 job 状态、worker 调用、题图上下文和结果写回。 */
    private final AiFlowOrchestrationService service;

    /**
     * 创建 AI-Flow 控制器。
     *
     * @param service AI 编排服务
     */
    public AiFlowController(AiFlowOrchestrationService service) {
        this.service = service;
    }

    /**
     * 对导入题执行 AI 标准化并返回修复候选。
     *
     * @param taskId 导入任务 ID
     * @param questionId 导入题 ID
     * @param payload 当前 Markdown、答案、解析、OCR 原文和可选提示
     * @return AI job 结果和题目快照；默认不写回，显式传入 writeResult/apply 才允许写库
     */
    @PostMapping("/api/import-tasks/{taskId}/questions/{questionId}/standardize/ai")
    public Map<String, Object> standardizeImportQuestion(
            @PathVariable String taskId,
            @PathVariable String questionId,
            @RequestBody Map<String, Object> payload
    ) {
        return service.standardizeImportQuestion(taskId, questionId, payload);
    }

    /**
     * 对导入题执行 AI 解析并写回答案解析。
     *
     * @param taskId 导入任务 ID
     * @param questionId 导入题 ID
     * @param payload 当前题干、题型、答案、知识点和可选提示
     * @return AI 解析结果和写回后的题目快照
     */
    @PostMapping("/api/import-tasks/{taskId}/questions/{questionId}/analysis")
    public Map<String, Object> analyzeImportQuestion(
            @PathVariable String taskId,
            @PathVariable String questionId,
            @RequestBody Map<String, Object> payload
    ) {
        return service.analyzeImportQuestion(taskId, questionId, payload);
    }

    /**
     * 对题库题执行 AI 标准化并返回修复候选。
     *
     * @param questionId 题库题 ID
     * @param payload 当前 Markdown、答案、解析和可选提示
     * @return AI job 结果和题库题快照；默认不写回，显式传入 writeResult/apply 才允许写库
     */
    @PostMapping("/api/question-bank/questions/{questionId}/standardize/ai")
    public Map<String, Object> standardizeBankQuestion(
            @PathVariable String questionId,
            @RequestBody Map<String, Object> payload
    ) {
        return service.standardizeBankQuestion(questionId, payload);
    }

    /**
     * 对题库题执行 AI 解析并写回答案解析。
     *
     * @param questionId 题库题 ID
     * @param payload 当前题干、题型、答案、知识点和可选提示
     * @return AI 解析结果和写回后的题库题快照
     */
    @PostMapping("/api/question-bank/questions/{questionId}/analysis")
    public Map<String, Object> analyzeBankQuestion(
            @PathVariable String questionId,
            @RequestBody Map<String, Object> payload
    ) {
        return service.analyzeBankQuestion(questionId, payload);
    }

    /**
     * 对临时 Markdown 执行 AI 标准化。
     *
     * @param payload 临时 Markdown、OCR 原文和结构化提示
     * @return 标准化后的 Markdown 和可选答案解析建议
     */
    @PostMapping("/api/markdown/standardize/ai")
    public Map<String, Object> standardizeAdHoc(@RequestBody Map<String, Object> payload) {
        return service.standardizeAdHoc(payload);
    }

    /**
     * 对临时题目内容执行 AI 解析。
     *
     * @param payload 临时题干、题型、答案和知识点上下文
     * @return AI 解析结果，不写回任何题目
     */
    @PostMapping("/api/ai/analysis")
    public Map<String, Object> analyzeAdHoc(@RequestBody Map<String, Object> payload) {
        return service.analyzeAdHoc(payload);
    }

    /**
     * 查询 AI job 列表。
     *
     * @param targetType 可选目标类型，例如 import-question 或 bank-question
     * @param targetId 可选目标 ID
     * @return AI job 列表和总数
     */
    @GetMapping("/api/capabilities/ai-flow/jobs")
    public Map<String, Object> listJobs(
            @RequestParam(defaultValue = "") String targetType,
            @RequestParam(defaultValue = "") String targetId
    ) {
        return service.listJobs(targetType, targetId);
    }

    /**
     * 查询单个 AI job。
     *
     * @param jobId AI job ID
     * @return AI job 详情
     */
    @GetMapping("/api/capabilities/ai-flow/jobs/{jobId}")
    public Map<String, Object> getJob(@PathVariable String jobId) {
        return service.getJob(jobId);
    }
}
