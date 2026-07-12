package com.aigeneration.questionengine.sdk;

import com.aigeneration.questionengine.sdk.QuestionEngineModels.CallbackEvent;
import com.aigeneration.questionengine.sdk.QuestionEngineModels.CallbackEventList;
import com.aigeneration.questionengine.sdk.QuestionEngineModels.CapabilitySummary;
import com.aigeneration.questionengine.sdk.QuestionEngineModels.DeliveryBoundary;
import com.aigeneration.questionengine.sdk.QuestionEngineModels.EngineCatalog;
import com.aigeneration.questionengine.sdk.QuestionEngineModels.EngineInterfaceDescriptor;
import com.aigeneration.questionengine.sdk.QuestionEngineModels.ImportTaskRescanResult;
import com.aigeneration.questionengine.sdk.QuestionEngineModels.AiAnalysisRequest;
import com.aigeneration.questionengine.sdk.QuestionEngineModels.AiAnalysisResult;
import com.aigeneration.questionengine.sdk.QuestionEngineModels.AiStandardizeRequest;
import com.aigeneration.questionengine.sdk.QuestionEngineModels.AiStandardizeResult;
import com.aigeneration.questionengine.sdk.QuestionEngineModels.ProcessingJob;
import com.aigeneration.questionengine.sdk.QuestionEngineModels.QuestionImageLibrary;
import com.aigeneration.questionengine.sdk.QuestionEngineModels.QuestionImageMutationResult;
import com.aigeneration.questionengine.sdk.QuestionEngineModels.QuestionPackage;
import com.aigeneration.questionengine.sdk.QuestionEngineModels.QuestionProcessingDescriptor;
import com.aigeneration.questionengine.sdk.QuestionEngineModels.SelectQuestionImagesRequest;
import com.aigeneration.questionengine.sdk.QuestionEngineModels.CanonicalizationPreview;
import com.aigeneration.questionengine.sdk.QuestionEngineModels.StandardizationBatchJob;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.Map;

// Generated from ../../../../openapi/question-engine.v1.yaml. Do not edit by hand.
public class QuestionEngineClient {
    private static final TypeReference<List<CapabilitySummary>> CAPABILITIES_TYPE = new TypeReference<>() {};
    private static final TypeReference<List<EngineInterfaceDescriptor>> ENGINE_INTERFACES_TYPE = new TypeReference<>() {};
    private final String baseUrl;
    private final Map<String, String> headers;
    private final HttpClient client;
    private final ObjectMapper objectMapper;

    public QuestionEngineClient(String baseUrl) {
        this(baseUrl, Map.of(), new ObjectMapper());
    }

    public QuestionEngineClient(String baseUrl, Map<String, String> headers, ObjectMapper objectMapper) {
        this.baseUrl = stripTrailingSlash(baseUrl);
        this.headers = headers;
        this.objectMapper = objectMapper.copy()
                .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);
        this.client = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(5))
                .build();
    }

    public List<CapabilitySummary> listCapabilities() throws IOException, InterruptedException {
        return objectMapper.readValue(get("/api/capabilities"), CAPABILITIES_TYPE);
    }

    public EngineCatalog getEngineCatalog() throws IOException, InterruptedException {
        return objectMapper.readValue(get("/api/engine"), EngineCatalog.class);
    }

    public List<EngineInterfaceDescriptor> getEngineInterfaces() throws IOException, InterruptedException {
        return objectMapper.readValue(get("/api/engine/interfaces"), ENGINE_INTERFACES_TYPE);
    }

    public DeliveryBoundary getDeliveryBoundary() throws IOException, InterruptedException {
        return objectMapper.readValue(get("/api/engine/delivery-boundary"), DeliveryBoundary.class);
    }

    public QuestionProcessingDescriptor getQuestionProcessingCapability() throws IOException, InterruptedException {
        return objectMapper.readValue(get("/api/capabilities/question-processing"), QuestionProcessingDescriptor.class);
    }

    public ProcessingJob getProcessingJob(String jobId) throws IOException, InterruptedException {
        return objectMapper.readValue(get("/api/capabilities/question-processing/jobs/" + encode(jobId)), ProcessingJob.class);
    }

    public QuestionPackage getQuestionPackage(String jobId) throws IOException, InterruptedException {
        return objectMapper.readValue(get("/api/capabilities/question-processing/jobs/" + encode(jobId) + "/question-package"), QuestionPackage.class);
    }

    public ImportTaskRescanResult rescanImportTask(String jobId) throws IOException, InterruptedException {
        return objectMapper.readValue(postJson(
                "/api/import-tasks/" + encode(jobId) + "/rescan",
                Map.of()
        ), ImportTaskRescanResult.class);
    }

    public CanonicalizationPreview previewImportTaskCanonicalization(String jobId) throws IOException, InterruptedException {
        return objectMapper.readValue(postJson("/api/import-tasks/" + encode(jobId) + "/canonicalization/preview", Map.of()), CanonicalizationPreview.class);
    }

    public CanonicalizationPreview applyImportTaskCanonicalization(String jobId, String applyToken) throws IOException, InterruptedException {
        return objectMapper.readValue(postJson("/api/import-tasks/" + encode(jobId) + "/canonicalization/apply", Map.of("applyToken", applyToken)), CanonicalizationPreview.class);
    }

    public String rollbackImportTaskCanonicalization(String jobId) throws IOException, InterruptedException {
        return postJson("/api/import-tasks/" + encode(jobId) + "/canonicalization/rollback", Map.of());
    }

    public StandardizationBatchJob createStandardizationBatchJob(String jobId) throws IOException, InterruptedException {
        return objectMapper.readValue(postJson("/api/import-tasks/" + encode(jobId) + "/standardization-jobs", Map.of()), StandardizationBatchJob.class);
    }

    public StandardizationBatchJob getStandardizationBatchJob(String jobId, String batchJobId) throws IOException, InterruptedException {
        return objectMapper.readValue(get("/api/import-tasks/" + encode(jobId) + "/standardization-jobs/" + encode(batchJobId)), StandardizationBatchJob.class);
    }

    public StandardizationBatchJob cancelStandardizationBatchJob(String jobId, String batchJobId) throws IOException, InterruptedException {
        return batchAction(jobId, batchJobId, "cancel");
    }

    public StandardizationBatchJob resumeStandardizationBatchJob(String jobId, String batchJobId) throws IOException, InterruptedException {
        return batchAction(jobId, batchJobId, "resume");
    }

    public StandardizationBatchJob retryFailedStandardizationBatchItems(String jobId, String batchJobId) throws IOException, InterruptedException {
        return batchAction(jobId, batchJobId, "retry-failed");
    }

    private StandardizationBatchJob batchAction(String jobId, String batchJobId, String action) throws IOException, InterruptedException {
        return objectMapper.readValue(postJson("/api/import-tasks/" + encode(jobId) + "/standardization-jobs/" + encode(batchJobId) + "/" + action, Map.of()), StandardizationBatchJob.class);
    }

    public QuestionImageLibrary getImportTaskImageLibrary(String jobId) throws IOException, InterruptedException {
        return objectMapper.readValue(get("/api/import-tasks/" + encode(jobId) + "/image-library"), QuestionImageLibrary.class);
    }

    public QuestionImageMutationResult selectImportQuestionImages(
            String jobId,
            String questionId,
            SelectQuestionImagesRequest request
    ) throws IOException, InterruptedException {
        return objectMapper.readValue(postJson(
                "/api/import-tasks/" + encode(jobId) + "/questions/" + encode(questionId) + "/images/select",
                request
        ), QuestionImageMutationResult.class);
    }

    public AiStandardizeResult standardizeImportQuestion(
            String jobId,
            String questionId,
            AiStandardizeRequest request
    ) throws IOException, InterruptedException {
        return objectMapper.readValue(postJson(
                "/api/import-tasks/" + encode(jobId) + "/questions/" + encode(questionId) + "/standardize/ai",
                request
        ), AiStandardizeResult.class);
    }

    public AiAnalysisResult analyzeImportQuestion(
            String jobId,
            String questionId,
            AiAnalysisRequest request
    ) throws IOException, InterruptedException {
        return objectMapper.readValue(postJson(
                "/api/import-tasks/" + encode(jobId) + "/questions/" + encode(questionId) + "/analysis",
                request
        ), AiAnalysisResult.class);
    }

    public QuestionImageLibrary getBankQuestionImageLibrary(String questionId) throws IOException, InterruptedException {
        return objectMapper.readValue(get("/api/question-bank/questions/" + encode(questionId) + "/image-library"), QuestionImageLibrary.class);
    }

    public AiStandardizeResult standardizeBankQuestion(
            String questionId,
            AiStandardizeRequest request
    ) throws IOException, InterruptedException {
        return objectMapper.readValue(postJson(
                "/api/question-bank/questions/" + encode(questionId) + "/standardize/ai",
                request
        ), AiStandardizeResult.class);
    }

    public AiAnalysisResult analyzeBankQuestion(
            String questionId,
            AiAnalysisRequest request
    ) throws IOException, InterruptedException {
        return objectMapper.readValue(postJson(
                "/api/question-bank/questions/" + encode(questionId) + "/analysis",
                request
        ), AiAnalysisResult.class);
    }

    public CallbackEventList listCallbackEvents(String status) throws IOException, InterruptedException {
        String query = status == null || status.isBlank() ? "" : "?status=" + encode(status);
        return objectMapper.readValue(get("/api/capabilities/callback-flow/events" + query), CallbackEventList.class);
    }

    public CallbackEvent retryCallbackEvent(String eventId, String secret) throws IOException, InterruptedException {
        return objectMapper.readValue(postJson(
                "/api/capabilities/callback-flow/events/" + encode(eventId) + "/retry",
                Map.of("secret", secret == null ? "" : secret)
        ), CallbackEvent.class);
    }

    public String getRuntime(String capability) throws IOException, InterruptedException {
        return get("/api/capabilities/" + encode(capability) + "/runtime");
    }

    private String get(String path) throws IOException, InterruptedException {
        HttpRequest.Builder builder = request(path).GET();
        return send(builder.build());
    }

    private String postJson(String path, Object body) throws IOException, InterruptedException {
        HttpRequest.Builder builder = request(path)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(body)));
        return send(builder.build());
    }

    private HttpRequest.Builder request(String path) {
        HttpRequest.Builder builder = HttpRequest.newBuilder()
                .uri(URI.create(baseUrl + path))
                .timeout(Duration.ofSeconds(30));
        headers.forEach(builder::header);
        return builder;
    }

    private String send(HttpRequest request) throws IOException, InterruptedException {
        HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new IOException("Question Engine request failed: HTTP " + response.statusCode() + " " + response.body());
        }
        return response.body();
    }

    private static String stripTrailingSlash(String value) {
        return value == null ? "" : value.replaceAll("/+$", "");
    }

    private static String encode(String value) {
        return URLEncoder.encode(value == null ? "" : value, StandardCharsets.UTF_8);
    }
}
