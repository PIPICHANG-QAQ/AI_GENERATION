package com.aigeneration.questionbank.ocrflow.contract;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.aigeneration.questionbank.ocrflow.contract.WorkerModels.WorkerRequestEnvelope;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.LinkedHashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;

class WorkerModelsTest {
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void requestEnvelopeRoundTripsUnknownExtensionFields() throws Exception {
        String json = """
                {
                  "schemaVersion": "worker-request.v1",
                  "requestId": "request-1",
                  "traceId": "trace-1",
                  "pipelineVersion": "ocrflow.v1",
                  "payload": {"fileName": "paper.pdf"},
                  "futureFlag": true,
                  "futureObject": {"version": 2}
                }
                """;

        WorkerRequestEnvelope envelope = objectMapper.readValue(json, WorkerRequestEnvelope.class);
        JsonNode encoded = objectMapper.readTree(objectMapper.writeValueAsString(envelope));

        assertEquals("worker-request.v1", envelope.schemaVersion());
        assertTrue(envelope.extensions().containsKey("futureFlag"));
        assertEquals(true, encoded.get("futureFlag").asBoolean());
        assertEquals(2, encoded.get("futureObject").get("version").asInt());
    }

    @Test
    void requestEnvelopeUsesStableDefaults() throws Exception {
        WorkerRequestEnvelope envelope = new WorkerRequestEnvelope(
                "worker-request.v1", "request-1", "", "", "", 0, "", "", "ocrflow.v1",
                Map.of("fileName", "paper.pdf"), new LinkedHashMap<>());

        assertEquals("worker-request.v1", envelope.schemaVersion());
        assertEquals(0, envelope.attemptNo());
        assertEquals("paper.pdf", envelope.payload().get("fileName"));
    }
}
