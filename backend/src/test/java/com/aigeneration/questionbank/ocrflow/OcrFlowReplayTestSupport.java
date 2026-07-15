package com.aigeneration.questionbank.ocrflow;

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
import java.nio.file.Path;
import java.util.List;
import java.util.Map;

final class OcrFlowReplayTestSupport {
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper()
            .findAndRegisterModules()
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

    private OcrFlowReplayTestSupport() {
    }

    static ObjectMapper objectMapper() {
        return OBJECT_MAPPER;
    }

    static JsonNode readResource(String resource) throws IOException {
        try (InputStream input = OcrFlowReplayTestSupport.class
                .getClassLoader()
                .getResourceAsStream(resource)) {
            if (input == null) {
                throw new IOException("Missing classpath fixture: " + resource);
            }
            return OBJECT_MAPPER.readTree(input);
        }
    }

    static JsonNode render(Path input) throws IOException {
        return render(OBJECT_MAPPER.readTree(input.toFile()));
    }

    static JsonNode render(JsonNode input) throws IOException {
        ImportTaskEntity task = OBJECT_MAPPER.treeToValue(input.required("task"), ImportTaskEntity.class);
        List<ImportQuestionEntity> questions = OBJECT_MAPPER.convertValue(
                input.required("questions"),
                new TypeReference<>() {}
        );
        List<ImportQuestionImageEntity> images = OBJECT_MAPPER.convertValue(
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
                new JsonSupport(OBJECT_MAPPER)
        );
        return OBJECT_MAPPER.valueToTree(service.questionPackage(task.getId()));
    }
}
