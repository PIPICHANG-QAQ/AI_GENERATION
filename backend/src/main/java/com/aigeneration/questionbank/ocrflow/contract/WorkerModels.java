package com.aigeneration.questionbank.ocrflow.contract;

import com.fasterxml.jackson.annotation.JsonAnyGetter;
import com.fasterxml.jackson.annotation.JsonAnySetter;
import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.databind.JsonNode;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Stable transport models shared by Java callers and the Python worker. */
public final class WorkerModels {
    private WorkerModels() {
    }

    /** Request envelope; unknown fields are preserved for forward compatibility. */
    public record WorkerRequestEnvelope(
            String schemaVersion,
            String requestId,
            String traceId,
            String jobId,
            String attemptId,
            int attemptNo,
            String idempotencyKey,
            String inputSha256,
            String pipelineVersion,
            Map<String, Object> payload,
            @JsonIgnore Map<String, JsonNode> extensions
    ) {
        public WorkerRequestEnvelope {
            schemaVersion = schemaVersion == null || schemaVersion.isBlank() ? "worker-request.v1" : schemaVersion;
            requestId = requestId == null ? "" : requestId;
            traceId = traceId == null ? "" : traceId;
            jobId = jobId == null ? "" : jobId;
            attemptId = attemptId == null ? "" : attemptId;
            idempotencyKey = idempotencyKey == null ? "" : idempotencyKey;
            inputSha256 = inputSha256 == null ? "" : inputSha256;
            pipelineVersion = pipelineVersion == null ? "" : pipelineVersion;
            payload = payload == null ? new LinkedHashMap<>() : new LinkedHashMap<>(payload);
            extensions = extensions == null ? new LinkedHashMap<>() : new LinkedHashMap<>(extensions);
        }

        @JsonAnySetter
        public void addExtension(String name, JsonNode value) {
            extensions.put(name, value);
        }

        @JsonAnyGetter
        public Map<String, JsonNode> extensionProperties() {
            return extensions;
        }
    }

    public record WorkerResponseEnvelope(
            String schemaVersion,
            String requestId,
            String traceId,
            String jobId,
            String attemptId,
            int attemptNo,
            String pipelineVersion,
            Map<String, Object> payload,
            WorkerError error
    ) {
        public WorkerResponseEnvelope {
            schemaVersion = schemaVersion == null || schemaVersion.isBlank() ? "worker-response.v1" : schemaVersion;
            payload = payload == null ? new LinkedHashMap<>() : payload;
        }
    }

    public record OcrCreateRequest(
            String fileName,
            String contentType,
            String inputSha256,
            String pipelineVersion,
            String idempotencyKey,
            String sourcePath,
            Map<String, Object> metadata
    ) {
        public OcrCreateRequest {
            pipelineVersion = pipelineVersion == null || pipelineVersion.isBlank() ? "ocrflow.v1" : pipelineVersion;
            metadata = metadata == null ? new LinkedHashMap<>() : metadata;
        }
    }

    public record OcrJobAccepted(
            String schemaVersion,
            String jobId,
            String status,
            String requestId,
            String traceId,
            String attemptId,
            int attemptNo,
            String pipelineVersion,
            String acceptedAt,
            String pollUrl
    ) {
        public OcrJobAccepted {
            schemaVersion = schemaVersion == null || schemaVersion.isBlank() ? "worker-ocr-accepted.v1" : schemaVersion;
            status = status == null || status.isBlank() ? "pending" : status;
            pipelineVersion = pipelineVersion == null || pipelineVersion.isBlank() ? "ocrflow.v1" : pipelineVersion;
        }
    }

    public record OcrJobSnapshot(
            String schemaVersion,
            String jobId,
            String status,
            String requestId,
            String traceId,
            String attemptId,
            int attemptNo,
            String pipelineVersion,
            String resultUrl,
            WorkerError error
    ) {
        public OcrJobSnapshot {
            schemaVersion = schemaVersion == null || schemaVersion.isBlank() ? "worker-ocr-job.v1" : schemaVersion;
            pipelineVersion = pipelineVersion == null || pipelineVersion.isBlank() ? "ocrflow.v1" : pipelineVersion;
        }
    }

    public record OcrResult(
            String schemaVersion,
            String jobId,
            String status,
            String pipelineVersion,
            Map<String, Object> outputs,
            List<ArtifactManifest> artifacts
    ) {
        public OcrResult {
            schemaVersion = schemaVersion == null || schemaVersion.isBlank() ? "worker-ocr-result.v1" : schemaVersion;
            status = status == null || status.isBlank() ? "success" : status;
            pipelineVersion = pipelineVersion == null || pipelineVersion.isBlank() ? "ocrflow.v1" : pipelineVersion;
            outputs = outputs == null ? new LinkedHashMap<>() : outputs;
            artifacts = artifacts == null ? new ArrayList<>() : artifacts;
        }
    }

    public record RetryRequest(String reason, String idempotencyKey, int attemptNo) {
    }

    public record QuestionAssemblyRequest(String jobId, Map<String, Object> source, String pipelineVersion) {
    }

    public record QuestionAssemblyResponse(String jobId, List<Map<String, Object>> questions, String pipelineVersion) {
    }

    public record StandardizationRequest(String markdown, String rawOcrContext, Map<String, Object> structuredHints,
                                         String pipelineVersion, String inputSha256, String requestSource) {
    }

    public record StandardizationResponse(String markdown, Map<String, Object> standardizer, String answer, String analysis) {
    }

    public record AnalysisRequest(String manualMarkdown, String type, String answer, List<String> knowledgePoints,
                                  List<Map<String, Object>> images, List<Map<String, Object>> subQuestions) {
    }

    public record AnalysisResponse(String analysis, String answer, String suggestedAnswer,
                                   List<Map<String, Object>> subQuestions, Map<String, Object> metadata) {
    }

    public record CanonicalizationRequest(Map<String, Object> task, String pipelineVersion) {
    }

    public record CanonicalizationResponse(List<Map<String, Object>> questions,
                                           Map<String, Object> canonicalization,
                                           Map<String, Object> paperLayout) {
    }

    public record SourceRenderRequest(Map<String, Object> payload) {
        public SourceRenderRequest {
            payload = payload == null ? new LinkedHashMap<>() : payload;
        }
    }

    public record BinaryResponse(byte[] body, String contentType, String contentDisposition, long contentLength) {
        public BinaryResponse {
            body = body == null ? new byte[0] : body.clone();
            contentType = contentType == null ? "application/octet-stream" : contentType;
            contentDisposition = contentDisposition == null ? "" : contentDisposition;
            contentLength = contentLength < 0 ? body.length : contentLength;
        }
    }

    public record WorkerCapabilities(String schemaVersion, String workerVersion,
                                     List<String> capabilities, Map<String, Object> metadata) {
        public WorkerCapabilities {
            schemaVersion = schemaVersion == null || schemaVersion.isBlank() ? "worker-capabilities.v1" : schemaVersion;
            capabilities = capabilities == null ? new ArrayList<>() : capabilities;
            metadata = metadata == null ? new LinkedHashMap<>() : metadata;
        }
    }

    public record WorkerError(String code, String message, String stage, boolean retryable,
                              String requestId, String jobId, String attemptId, String provider,
                              Map<String, Object> details) {
        public WorkerError {
            details = details == null ? new LinkedHashMap<>() : details;
        }
    }

    public record ArtifactManifest(String artifactId, String kind, String sha256, String uri,
                                   long sizeBytes, String contentType, Map<String, Object> metadata) {
        public ArtifactManifest {
            metadata = metadata == null ? new LinkedHashMap<>() : metadata;
        }
    }
}
