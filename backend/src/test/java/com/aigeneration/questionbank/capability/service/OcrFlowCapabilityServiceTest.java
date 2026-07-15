package com.aigeneration.questionbank.capability.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.aigeneration.questionbank.config.PythonWorkerProperties;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class OcrFlowCapabilityServiceTest {

    @Test
    void descriptorExposesProviderNeutralPostProcessContract() {
        OcrFlowCapabilityService service = new OcrFlowCapabilityService(
                new PythonWorkerProperties(),
                new ObjectMapper()
        );

        Map<String, Object> descriptor = service.descriptor();
        Map<String, Object> providerContract = mapValue(descriptor, "providerContract");
        Map<String, Object> postProcessContract = mapValue(descriptor, "postProcessContract");

        assertEquals("ocr-flow", descriptor.get("code"));
        assertEquals("canonical-ocr-bundle.v1", providerContract.get("outputSchema"));
        assertEquals(
                List.of("documentId", "inputSha256", "canonicalMarkdown", "artifactRoot"),
                providerContract.get("requiredEvidence")
        );
        assertEquals("canonical-ocr-bundle.v1", postProcessContract.get("inputSchema"));
        assertEquals("app.ocr.OcrPostProcessingPipeline.run_bundle", postProcessContract.get("entrypoint"));
        assertEquals("legacy-collect-outputs", postProcessContract.get("outputCompatibility"));
        assertTrue(((List<?>) descriptor.get("replaceProviderStrategy")).stream()
                .map(Object::toString)
                .anyMatch(value -> value.contains("CanonicalOcrBundle")));
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> mapValue(Map<String, Object> source, String key) {
        return (Map<String, Object>) source.get(key);
    }
}
