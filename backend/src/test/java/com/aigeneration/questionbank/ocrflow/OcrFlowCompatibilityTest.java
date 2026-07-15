package com.aigeneration.questionbank.ocrflow;

import static org.junit.jupiter.api.Assertions.assertEquals;

import com.fasterxml.jackson.databind.JsonNode;
import org.junit.jupiter.api.Test;

class OcrFlowCompatibilityTest {
    private static final String INPUT_FIXTURE = "golden/ocrflow/processing-job.json";
    private static final String EXPECTED_FIXTURE = "golden/ocrflow/question-package.json";

    @Test
    void questionProcessingServiceMatchesFrozenQuestionPackageRecursively() throws Exception {
        JsonNode input = OcrFlowReplayTestSupport.readResource(INPUT_FIXTURE);
        JsonNode actual = OcrFlowReplayTestSupport.render(input);
        JsonNode expected = OcrFlowReplayTestSupport.readResource(EXPECTED_FIXTURE);

        assertEquals(expected, actual, "question-package.v1 changed from the frozen compatibility baseline");
    }
}
