package com.aigeneration.questionbank.ocrflow;

import static org.junit.jupiter.api.Assertions.assertEquals;

import com.fasterxml.jackson.databind.JsonNode;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;

class OcrFlowReplayRunnerTest {
    private static final String REQUEST_PROPERTY = "ocrflow.replay.request";
    private static final String INPUT_FIXTURE = "golden/ocrflow/processing-job.json";
    private static final String EXPECTED_FIXTURE = "golden/ocrflow/question-package.json";

    @Test
    void rawProcessingJobIsExecutedThroughCurrentQuestionProcessingService() throws Exception {
        String request = System.getProperty(REQUEST_PROPERTY);
        if (request != null && !request.isBlank()) {
            executeRequest(Path.of(request));
            return;
        }

        JsonNode actual = OcrFlowReplayTestSupport.render(
                OcrFlowReplayTestSupport.readResource(INPUT_FIXTURE)
        );
        JsonNode expected = OcrFlowReplayTestSupport.readResource(EXPECTED_FIXTURE);
        assertEquals(expected, actual, "raw processing-job replay changed current service output");
    }

    private void executeRequest(Path requestPath) throws Exception {
        JsonNode request = OcrFlowReplayTestSupport.objectMapper().readTree(requestPath.toFile());
        assertEquals("ocrflow-replay-request.v1", request.required("schemaVersion").asText());
        for (JsonNode replayCase : request.required("cases")) {
            Path input = Path.of(replayCase.required("input").asText());
            Path output = Path.of(replayCase.required("output").asText());
            JsonNode candidate = OcrFlowReplayTestSupport.render(input);
            Files.createDirectories(output.toAbsolutePath().getParent());
            OcrFlowReplayTestSupport.objectMapper()
                    .writerWithDefaultPrettyPrinter()
                    .writeValue(output.toFile(), candidate);
        }
    }
}
