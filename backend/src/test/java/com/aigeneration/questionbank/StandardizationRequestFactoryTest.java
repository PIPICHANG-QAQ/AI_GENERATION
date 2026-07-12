package com.aigeneration.questionbank;

import static org.assertj.core.api.Assertions.assertThat;

import com.aigeneration.questionbank.domain.entity.ImportQuestionEntity;
import com.aigeneration.questionbank.domain.service.StandardizationRequestFactory;
import com.aigeneration.questionbank.domain.support.JsonSupport;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class StandardizationRequestFactoryTest {
    private StandardizationRequestFactory factory;

    @BeforeEach
    void setUp() {
        factory = new StandardizationRequestFactory(new JsonSupport(new ObjectMapper().findAndRegisterModules()));
    }

    @Test
    void choiceOptionsArePresentInMarkdownAndStructuredHints() {
        ImportQuestionEntity question = choiceQuestion();

        Map<String, Object> request = factory.build(question, "题干", "原始 OCR", "single");

        assertThat(request.get("markdown").toString())
                .contains("\\begin{tasks}(4)", "\\task 食品夹", "\\task 船桨", "\\end{tasks}");
        Map<?, ?> hints = (Map<?, ?>) request.get("structuredHints");
        assertThat((List<?>) hints.get("options")).hasSize(4);
        assertThat((List<?>) hints.get("images")).hasSize(1);
        assertThat((List<?>) hints.get("imagePlacements")).hasSize(1);
        assertThat(hints.get("requestPriority")).isEqualTo("interactive");
        assertThat(request).containsKeys("pipelineVersion", "inputHash", "requestSource");
    }

    @Test
    void existingChoiceBlockIsNotDuplicated() {
        ImportQuestionEntity question = choiceQuestion();
        String markdown = "题干\n\n\\begin{tasks}(4)\n\\task 甲\n\\task 乙\n\\task 丙\n\\task 丁\n\\end{tasks}";

        Map<String, Object> request = factory.build(question, markdown, "", "global");

        assertThat(request.get("markdown").toString().split("begin\\{tasks}", -1)).hasSize(2);
        assertThat(((Map<?, ?>) request.get("structuredHints")).get("requestPriority")).isEqualTo("batch");
    }

    @Test
    void inputHashChangesWhenPlacementChanges() {
        ImportQuestionEntity question = choiceQuestion();
        String before = factory.inputHash(question, "题干", "原始 OCR");
        question.setImagePlacementsJson("[{\"imageId\":\"img-1\",\"target\":{\"kind\":\"option\",\"optionLabel\":\"B\"}}]");

        assertThat(factory.inputHash(question, "题干", "原始 OCR")).isNotEqualTo(before);
    }

    private ImportQuestionEntity choiceQuestion() {
        ImportQuestionEntity question = new ImportQuestionEntity();
        question.setId("q-2");
        question.setQuestionNumber(2);
        question.setType("choice");
        question.setStemMarkdown("题干");
        question.setOptionsJson("""
                [{"label":"A","content":"食品夹"},{"label":"B","content":"船桨"},
                 {"label":"C","content":"修枝剪刀"},{"label":"D","content":"托盘天平"}]
                """);
        question.setImagesJson("[{\"imageId\":\"img-1\",\"label\":\"图1\"}]");
        question.setImagePlacementsJson("[{\"imageId\":\"img-1\",\"target\":{\"kind\":\"option\",\"optionLabel\":\"A\"}}]");
        question.setChildrenJson("[]");
        question.setKnowledgePointsJson("[]");
        return question;
    }
}
