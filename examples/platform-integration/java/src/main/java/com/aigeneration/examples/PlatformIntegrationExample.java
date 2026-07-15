package com.aigeneration.examples;

import com.aigeneration.questionengine.sdk.QuestionEngineClient;
import com.aigeneration.questionengine.sdk.QuestionEngineModels.CapabilitySummary;
import com.aigeneration.questionengine.sdk.QuestionEngineModels.ProcessingJob;
import com.aigeneration.questionengine.sdk.QuestionEngineModels.QuestionPackage;
import com.aigeneration.questionengine.sdk.QuestionEngineModels.OcrFlowDescriptor;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.List;
import java.util.Map;

public class PlatformIntegrationExample {
    public static void main(String[] args) throws Exception {
        String baseUrl = getenv("QUESTION_ENGINE_BASE_URL", "http://localhost:8018");
        String token = System.getenv("QUESTION_ENGINE_TOKEN");
        Map<String, String> headers = token == null || token.isBlank()
                ? Map.of(
                "X-Tenant-Id", getenv("QUESTION_ENGINE_TENANT_ID", "demo-tenant"),
                "X-Operator-Id", getenv("QUESTION_ENGINE_OPERATOR_ID", "demo-operator"),
                "X-Source-App", "platform-integration-example"
        )
                : Map.of(
                "Authorization", "Bearer " + token,
                "X-Tenant-Id", getenv("QUESTION_ENGINE_TENANT_ID", "demo-tenant"),
                "X-Operator-Id", getenv("QUESTION_ENGINE_OPERATOR_ID", "demo-operator"),
                "X-Source-App", "platform-integration-example"
        );

        QuestionEngineClient client = new QuestionEngineClient(baseUrl, headers, new ObjectMapper());
        List<CapabilitySummary> capabilities = client.listCapabilities();
        boolean available = capabilities.stream().anyMatch(item -> "question-processing".equals(item.code()));
        if (!available) {
            throw new IllegalStateException("question-processing capability is not available");
        }
        System.out.println("capabilities=" + capabilities.size());
        System.out.println("interfaces=" + client.getEngineInterfaces().size());
        OcrFlowDescriptor ocrFlow = client.getOcrFlowCapability();
        System.out.println("ocrProvider=" + ocrFlow.defaultProvider());
        System.out.println("postProcessInput=" + ocrFlow.postProcessContract().get("inputSchema"));

        String jobId = System.getenv("QUESTION_ENGINE_JOB_ID");
        if (jobId == null || jobId.isBlank()) {
            System.out.println("Set QUESTION_ENGINE_JOB_ID to fetch a question package.");
            return;
        }

        ProcessingJob job = client.getProcessingJob(jobId);
        System.out.println("job=" + job.jobId() + " status=" + job.processingStatus());
        QuestionPackage questionPackage = client.getQuestionPackage(jobId);
        System.out.println("package=" + questionPackage.packageVersion());
        System.out.println("questions=" + questionPackage.questions().size());
    }

    private static String getenv(String name, String fallback) {
        String value = System.getenv(name);
        return value == null || value.isBlank() ? fallback : value;
    }
}
