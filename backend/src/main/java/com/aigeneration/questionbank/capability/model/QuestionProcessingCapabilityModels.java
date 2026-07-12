package com.aigeneration.questionbank.capability.model;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * question-processing 能力对外数据模型集合。
 *
 * <p>该类只作为命名空间承载 record，避免把能力描述、任务视图和标准题目包模型分散到过多小文件。
 * 所有 record 都面向平台集成，应保持字段语义稳定。</p>
 */
public final class QuestionProcessingCapabilityModels {
    /**
     * 禁止实例化模型命名空间类。
     */
    private QuestionProcessingCapabilityModels() {
    }

    /**
     * question-processing 能力描述。
     *
     * @param code 能力编码
     * @param name 能力名称
     * @param boundary 能力边界说明
     * @param packageVersion 标准题目包版本
     * @param inputs 支持输入
     * @param outputs 输出内容
     * @param endpoints Java API 端点映射
     * @param executionWorkers 内部依赖 worker
     * @param platformOwned 平台侧负责的能力
     */
    public record CapabilityDescriptor(
            String code,
            String name,
            String boundary,
            String packageVersion,
            List<String> inputs,
            List<String> outputs,
            Map<String, String> endpoints,
            List<String> executionWorkers,
            List<String> platformOwned
    ) {
    }

    /**
     * 加工任务平台视图。
     *
     * @param jobId 加工任务 ID
     * @param title 任务标题
     * @param stage 学段
     * @param subject 学科
     * @param grade 年级
     * @param region 地区
     * @param year 年份
     * @param status 原始中文状态
     * @param processingStatus 平台归一化状态
     * @param failureReason 失败原因
     * @param questionCount 已同步题目数量
     * @param sourceFiles 原文件预览入口
     * @param paperOcr 试卷 OCR 状态
     * @param answerOcr 答案 OCR 状态
     * @param createdAt 创建时间
     * @param updatedAt 更新时间
     */
    public record ProcessingJobView(
            String jobId,
            String title,
            String stage,
            String subject,
            String grade,
            String region,
            String year,
            String status,
            String processingStatus,
            String failureReason,
            Integer questionCount,
            List<SourceFileView> sourceFiles,
            OcrStatusView paperOcr,
            OcrStatusView answerOcr,
            LocalDateTime createdAt,
            LocalDateTime updatedAt
    ) {
    }

    /**
     * 原文件预览入口。
     *
     * @param kind 文件类型，例如 paper 或 answer
     * @param filename 原文件名
     * @param previewUrl Java 预览 URL
     */
    public record SourceFileView(
            String kind,
            String filename,
            String previewUrl
    ) {
    }

    /**
     * OCR job 状态视图。
     *
     * @param kind OCR 类型，例如 paper 或 answer
     * @param jobId OCR job ID
     * @param status OCR 状态
     * @param raw 原始 OCR job 快照
     */
    public record OcrStatusView(
            String kind,
            String jobId,
            String status,
            Map<String, Object> raw
    ) {
    }

    /**
     * 标准题目包。
     *
     * @param packageVersion 包版本
     * @param capability 来源能力
     * @param job 加工任务快照
     * @param questions 标准化题目列表
     * @param warnings 包级告警
     */
    public record QuestionPackage(
            String packageVersion,
            String capability,
            ProcessingJobView job,
            List<ProcessedQuestion> questions,
            List<ProcessingWarning> warnings
    ) {
    }

    /**
     * 标准化题目视图。
     *
     * @param questionId Java 内部题目 ID
     * @param sourceQuestionId OCR/worker 原始题目 ID
     * @param number 题号
     * @param status 校验状态
     * @param type 题型
     * @param stemMarkdown 推荐题干 Markdown
     * @param originalStemMarkdown OCR 初始题干 Markdown
     * @param answer 答案
     * @param analysis 解析
     * @param options 选择题选项
     * @param children 子题
     * @param images 题图
     * @param imagePlacements 题图显式归属
     * @param knowledgePointIdCandidates 知识点 ID 候选
     * @param knowledgePointCandidates 知识点名称候选
     * @param difficultyCandidate 难度候选
     * @param scoreCandidate 分值候选
     * @param mathValidation 公式校验结果
     * @param warnings 题目级告警
     * @param sourceEvidence 来源证据
     * @param raw 原始扩展字段
     */
    public record ProcessedQuestion(
            String questionId,
            String sourceQuestionId,
            Integer number,
            String status,
            String type,
            String stemMarkdown,
            String originalStemMarkdown,
            String answer,
            String analysis,
            List<QuestionOption> options,
            List<QuestionChild> children,
            List<QuestionImage> images,
            List<Map<String, Object>> imagePlacements,
            List<String> knowledgePointIdCandidates,
            List<String> knowledgePointCandidates,
            String difficultyCandidate,
            Double scoreCandidate,
            MathValidationView mathValidation,
            List<ProcessingWarning> warnings,
            SourceEvidence sourceEvidence,
            Map<String, Object> raw
    ) {
    }

    /**
     * 选择题选项。
     *
     * @param label 选项标签
     * @param contentMarkdown 选项 Markdown 内容
     * @param raw 原始扩展字段
     */
    public record QuestionOption(
            String label,
            String contentMarkdown,
            Map<String, Object> raw
    ) {
    }

    /**
     * 子题视图。
     *
     * @param childId 子题 ID
     * @param sourceQuestionId 子题来源 ID
     * @param number 子题题号
     * @param stemMarkdown 子题题干
     * @param answer 子题答案
     * @param analysis 子题解析
     * @param options 子题选项
     * @param images 子题题图
     * @param imagePlacements 子题题图显式归属
     * @param raw 原始扩展字段
     */
    public record QuestionChild(
            String childId,
            String sourceQuestionId,
            Integer number,
            String stemMarkdown,
            String answer,
            String analysis,
            List<QuestionOption> options,
            List<QuestionImage> images,
            List<Map<String, Object>> imagePlacements,
            Map<String, Object> raw
    ) {
    }

    /**
     * 题图视图。
     *
     * @param id 题图 ID
     * @param index 题图顺序
     * @param name 文件名
     * @param path worker 或本地路径
     * @param url 前端可访问 URL
     * @param raw 原始扩展字段
     */
    public record QuestionImage(
            String id,
            Integer index,
            String name,
            String path,
            String url,
            Map<String, Object> raw
    ) {
    }

    /**
     * 加工告警。
     *
     * @param code 告警编码
     * @param message 告警说明
     * @param targetId 告警关联目标 ID
     */
    public record ProcessingWarning(
            String code,
            String message,
            String targetId
    ) {
    }

    /**
     * 公式校验视图。
     *
     * @param status 校验状态
     * @param summary 校验摘要
     * @param issues 具体问题列表
     * @param raw 原始公式校验字段
     */
    public record MathValidationView(
            String status,
            String summary,
            List<MathValidationIssue> issues,
            Map<String, Object> raw
    ) {
    }

    /**
     * 公式校验问题。
     *
     * @param code 问题编码
     * @param severity 严重程度
     * @param message 问题说明
     * @param field 关联字段
     */
    public record MathValidationIssue(
            String code,
            String severity,
            String message,
            String field
    ) {
    }

    /**
     * 题目来源证据。
     *
     * @param processingJobId 加工任务 ID
     * @param sourceQuestionId 来源题目 ID
     * @param answerEvidence 答案证据
     * @param analysisEvidence 解析证据
     * @param rawOcrContextUsed 是否使用 OCR 原文上下文
     * @param raw 原始扩展字段
     */
    public record SourceEvidence(
            String processingJobId,
            String sourceQuestionId,
            Object answerEvidence,
            Object analysisEvidence,
            Boolean rawOcrContextUsed,
            Map<String, Object> raw
    ) {
    }
}
