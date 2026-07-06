package com.aigeneration.questionengine.sdk;

import java.util.List;
import java.util.Map;

// Generated from ../../../../openapi/question-engine.v1.yaml. Do not edit by hand.
public final class QuestionEngineModels {
    private QuestionEngineModels() {
    }

    public record CapabilitySummary(String code, String name, String boundary, Map<String, Object> raw) {
    }

    public record DeliveryBoundary(List<String> includePaths, List<String> excludePaths, Map<String, Object> raw) {
    }

    public record EngineCatalog(
            String code,
            List<Map<String, Object>> modules,
            List<Map<String, Object>> supplementalCapabilities,
            DeliveryBoundary deliveryBoundary,
            Map<String, Object> raw
    ) {
    }

    public record EngineInterfaceDescriptor(
            String groupCode,
            String groupName,
            String method,
            String path,
            String description,
            String audience,
            String source
    ) {
    }

    public record QuestionProcessingDescriptor(
            String code,
            String name,
            String boundary,
            String packageVersion,
            Map<String, String> endpoints,
            Map<String, Object> raw
    ) {
    }

    public record SourceFile(String kind, String filename, String previewUrl) {
    }

    public record OcrStatus(String kind, String jobId, String status, Map<String, Object> raw) {
    }

    public record ProcessingJob(
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
            List<SourceFile> sourceFiles,
            OcrStatus paperOcr,
            OcrStatus answerOcr,
            String createdAt,
            String updatedAt
    ) {
    }

    public record QuestionOption(String label, String contentMarkdown, Map<String, Object> raw) {
    }

    public record QuestionImage(
            String id,
            String imageId,
            Integer index,
            Integer imageIndex,
            String name,
            String path,
            String url,
            String source,
            String type,
            Long size,
            String storageFileId,
            String questionId,
            String contentType,
            String imageDataUrl,
            Boolean aiImageIncluded,
            String aiImageSkipReason,
            Map<String, Object> raw
    ) {
    }

    public record QuestionImageLibrary(List<QuestionImage> items) {
    }

    public record SelectQuestionImagesRequest(List<String> imageIds, List<QuestionImage> images) {
    }

    public record QuestionImageMutationResult(
            List<QuestionImage> images,
            List<QuestionImage> uploaded,
            List<QuestionImage> selected,
            Map<String, Object> question,
            Map<String, Object> task
    ) {
    }

    public record AiStandardizeRequest(
            String markdown,
            String rawOcrText,
            String rawOcrContext,
            Map<String, Object> structuredHints,
            String questionType,
            String answer,
            String analysis,
            List<QuestionImage> images,
            Boolean writeResult,
            Boolean apply,
            Map<String, Object> raw
    ) {
    }

    public record AiStandardizeResult(
            String aiJobId,
            Boolean writeResult,
            String writeSkippedReason,
            String markdown,
            String standardizedMarkdown,
            String answer,
            String suggestedAnswer,
            String analysis,
            String explanation,
            Map<String, Object> standardizer,
            Map<String, Object> metadata,
            Map<String, Object> question
    ) {
    }

    public record AiAnalysisRequest(
            String manualMarkdown,
            String answer,
            String type,
            List<String> knowledgePoints,
            List<QuestionImage> images,
            Map<String, Object> raw
    ) {
    }

    public record AiAnalysisResult(
            String aiJobId,
            Boolean writeResult,
            String markdown,
            String standardizedMarkdown,
            String answer,
            String suggestedAnswer,
            String analysis,
            String explanation,
            Map<String, Object> standardizer,
            Map<String, Object> metadata,
            Map<String, Object> question
    ) {
    }

    public record QuestionChild(
            String childId,
            String sourceQuestionId,
            Integer number,
            String stemMarkdown,
            String answer,
            String analysis,
            List<QuestionOption> options,
            List<QuestionImage> images,
            Map<String, Object> raw
    ) {
    }

    public record MathValidationIssue(String code, String severity, String message, String field) {
    }

    public record MathValidation(String status, String summary, List<MathValidationIssue> issues, Map<String, Object> raw) {
    }

    public record SourceEvidence(
            String processingJobId,
            String sourceQuestionId,
            Object answerEvidence,
            Object analysisEvidence,
            Boolean rawOcrContextUsed,
            Map<String, Object> raw
    ) {
    }

    public record ProcessingWarning(String code, String message, String targetId) {
    }

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
            List<String> knowledgePointIdCandidates,
            List<String> knowledgePointCandidates,
            String difficultyCandidate,
            Double scoreCandidate,
            MathValidation mathValidation,
            List<ProcessingWarning> warnings,
            SourceEvidence sourceEvidence,
            Map<String, Object> raw
    ) {
    }

    public record QuestionPackage(
            String packageVersion,
            String capability,
            ProcessingJob job,
            List<ProcessedQuestion> questions,
            List<ProcessingWarning> warnings
    ) {
    }

    public record CallbackEvent(
            String id,
            String eventType,
            String aggregateType,
            String aggregateId,
            String status,
            String callbackUrl,
            String idempotencyKey,
            Integer retryCount,
            Integer maxRetryCount,
            String nextRetryAt,
            String failureReason,
            Map<String, Object> payload,
            Map<String, Object> response,
            String createdAt,
            String updatedAt
    ) {
    }

    public record CallbackEventList(List<CallbackEvent> items, Integer total) {
    }
}
