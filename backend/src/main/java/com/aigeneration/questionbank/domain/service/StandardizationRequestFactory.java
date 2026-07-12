package com.aigeneration.questionbank.domain.service;

import com.aigeneration.questionbank.domain.entity.ImportQuestionEntity;
import com.aigeneration.questionbank.domain.support.JsonSupport;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;
import org.springframework.stereotype.Component;

/** Builds one canonical standardization request for both interactive and batch calls. */
@Component
public class StandardizationRequestFactory {
    public static final String PIPELINE_VERSION = "standardization.v2";
    private static final Pattern TASKS_BLOCK = Pattern.compile("\\\\begin\\{tasks}(?:\\([^)]+\\)|\\[[^]]+])?.*?\\\\end\\{tasks}", Pattern.DOTALL);

    private final JsonSupport json;

    public StandardizationRequestFactory(JsonSupport json) {
        this.json = json;
    }

    public Map<String, Object> build(
            ImportQuestionEntity question,
            String requestedMarkdown,
            String rawOcrContext,
            String requestSource
    ) {
        List<Object> options = json.readList(question.getOptionsJson());
        List<Object> images = json.readList(question.getImagesJson());
        List<Object> placements = json.readList(question.getImagePlacementsJson());
        List<Object> subQuestions = json.readList(question.getChildrenJson());
        String markdown = withChoiceOptions(
                firstText(requestedMarkdown, question.getManualMarkdown(), question.getStemMarkdown()),
                question.getType(),
                options
        );
        String source = "global".equals(text(requestSource)) ? "global" : "single";

        Map<String, Object> hints = new LinkedHashMap<>();
        hints.put("questionId", text(question.getId()));
        hints.put("number", question.getQuestionNumber());
        hints.put("type", text(question.getType()));
        hints.put("answer", text(question.getAnswer()));
        hints.put("analysis", text(question.getAnalysis()));
        hints.put("knowledgePoints", json.readList(question.getKnowledgePointsJson()));
        hints.put("options", options);
        hints.put("images", images);
        hints.put("imagePlacements", placements);
        hints.put("subQuestions", subQuestions);
        hints.put("requestPriority", "single".equals(source) ? "interactive" : "batch");

        Map<String, Object> request = new LinkedHashMap<>();
        request.put("pipelineVersion", PIPELINE_VERSION);
        request.put("markdown", markdown);
        request.put("rawOcrContext", text(rawOcrContext));
        request.put("structuredHints", hints);
        request.put("requestSource", source);
        request.put("inputHash", inputHash(question, markdown, rawOcrContext));
        return request;
    }

    public String inputHash(ImportQuestionEntity question, String markdown, String rawOcrContext) {
        Map<String, Object> content = new LinkedHashMap<>();
        content.put("pipelineVersion", PIPELINE_VERSION);
        content.put("questionId", text(question.getId()));
        content.put("markdown", text(markdown));
        content.put("rawOcrContext", text(rawOcrContext));
        content.put("type", text(question.getType()));
        content.put("answer", text(question.getAnswer()));
        content.put("analysis", text(question.getAnalysis()));
        content.put("options", json.readList(question.getOptionsJson()));
        content.put("images", json.readList(question.getImagesJson()));
        content.put("imagePlacements", json.readList(question.getImagePlacementsJson()));
        content.put("subQuestions", json.readList(question.getChildrenJson()));
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(json.write(content).getBytes(StandardCharsets.UTF_8));
            return java.util.HexFormat.of().formatHex(digest);
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException(ex);
        }
    }

    private String withChoiceOptions(String markdown, String questionType, List<Object> options) {
        String current = text(markdown);
        if (options.size() < 2 || TASKS_BLOCK.matcher(current).find()) {
            return current;
        }
        int columns = options.size() >= 4 ? 4 : 2;
        StringBuilder block = new StringBuilder("\\begin{tasks}(").append(columns).append(")");
        for (Object value : options) {
            String content = optionContent(value);
            if (!content.isBlank()) block.append("\n\\task ").append(content);
        }
        block.append("\n\\end{tasks}");
        return current.isBlank() ? block.toString() : current + "\n\n" + block;
    }

    private String optionContent(Object value) {
        if (value instanceof Map<?, ?> option) {
            return firstText(
                    option.get("contentMarkdown"), option.get("markdown"), option.get("content"),
                    option.get("text"), option.get("value")
            );
        }
        return text(value);
    }

    private String firstText(Object... values) {
        for (Object value : values) {
            String current = text(value);
            if (!current.isBlank()) return current;
        }
        return "";
    }

    private String text(Object value) {
        return value == null ? "" : String.valueOf(value).trim();
    }
}
