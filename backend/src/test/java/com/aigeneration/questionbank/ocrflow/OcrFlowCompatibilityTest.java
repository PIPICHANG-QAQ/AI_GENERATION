package com.aigeneration.questionbank.ocrflow;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.aigeneration.questionbank.capability.service.QuestionProcessingCapabilityService;
import com.aigeneration.questionbank.domain.entity.ImportQuestionEntity;
import com.aigeneration.questionbank.domain.entity.ImportQuestionImageEntity;
import com.aigeneration.questionbank.domain.entity.ImportTaskEntity;
import com.aigeneration.questionbank.domain.service.ImportQuestionSyncService;
import com.aigeneration.questionbank.domain.service.ImportTaskMetadataBridgeService;
import com.aigeneration.questionbank.domain.service.ImportTaskMetadataService;
import com.aigeneration.questionbank.domain.support.JsonSupport;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import java.io.IOException;
import java.io.InputStream;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class OcrFlowCompatibilityTest {
    private static final String INPUT_FIXTURE = "golden/ocrflow/processing-job.json";
    private static final String EXPECTED_FIXTURE = "golden/ocrflow/question-package.json";

    private final ObjectMapper objectMapper = new ObjectMapper()
            .findAndRegisterModules()
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

    @Test
    void questionProcessingServiceMatchesFrozenQuestionPackageRecursively() throws Exception {
        JsonNode input = readFixture(INPUT_FIXTURE);
        ImportTaskEntity task = objectMapper.treeToValue(input.required("task"), ImportTaskEntity.class);
        List<ImportQuestionEntity> questions = objectMapper.convertValue(
                input.required("questions"),
                new TypeReference<>() {}
        );
        List<ImportQuestionImageEntity> images = objectMapper.convertValue(
                input.required("images"),
                new TypeReference<>() {}
        );

        ImportTaskMetadataService taskService = mock(ImportTaskMetadataService.class);
        ImportQuestionSyncService questionService = mock(ImportQuestionSyncService.class);
        ImportTaskMetadataBridgeService bridgeService = mock(ImportTaskMetadataBridgeService.class);
        when(taskService.getEntity(task.getId())).thenReturn(task);
        when(questionService.listByTask(task.getId())).thenReturn(questions);
        when(questionService.listImages(anyString())).thenAnswer(invocation -> {
            String questionId = invocation.getArgument(0);
            return images.stream().filter(image -> questionId.equals(image.getQuestionId())).toList();
        });
        when(bridgeService.get(task.getId())).thenReturn(Map.of("id", task.getId()));
        QuestionProcessingCapabilityService service = new QuestionProcessingCapabilityService(
                taskService,
                questionService,
                bridgeService,
                new JsonSupport(objectMapper)
        );

        JsonNode actual = objectMapper.valueToTree(service.questionPackage(task.getId()));
        JsonNode expected = readFixture(EXPECTED_FIXTURE);

        assertEquals(expected, actual, "question-package.v1 changed from the frozen compatibility baseline");
    }

    private JsonNode readFixture(String resource) throws IOException {
        try (InputStream input = getClass().getClassLoader().getResourceAsStream(resource)) {
            if (input == null) {
                throw new IOException("Missing classpath fixture: " + resource);
            }
            return objectMapper.readTree(input);
        }
    }
}
