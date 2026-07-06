package com.aigeneration.questionengine.sdk;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;

public class QuestionEngineClientExample {
    private final String baseUrl;
    private final Map<String, String> headers;
    private final HttpClient client;

    public QuestionEngineClientExample(String baseUrl) {
        this(baseUrl, Map.of());
    }

    public QuestionEngineClientExample(String baseUrl, Map<String, String> headers) {
        this.baseUrl = stripTrailingSlash(baseUrl);
        this.headers = headers;
        this.client = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(5))
                .build();
    }

    public String capabilities() throws IOException, InterruptedException {
        return get("/api/capabilities");
    }

    public String engine() throws IOException, InterruptedException {
        return get("/api/engine");
    }

    public String processingJob(String jobId) throws IOException, InterruptedException {
        return get("/api/capabilities/question-processing/jobs/" + encode(jobId));
    }

    public String questionPackage(String jobId) throws IOException, InterruptedException {
        return get("/api/capabilities/question-processing/jobs/" + encode(jobId) + "/question-package");
    }

    private String get(String path) throws IOException, InterruptedException {
        HttpRequest.Builder builder = HttpRequest.newBuilder()
                .uri(URI.create(baseUrl + path))
                .timeout(Duration.ofSeconds(30))
                .GET();
        headers.forEach(builder::header);
        HttpResponse<String> response = client.send(builder.build(), HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new IOException("Question Engine request failed: HTTP " + response.statusCode() + " " + response.body());
        }
        return response.body();
    }

    private static String stripTrailingSlash(String value) {
        return value == null ? "" : value.replaceAll("/+$", "");
    }

    private static String encode(String value) {
        return java.net.URLEncoder.encode(value, java.nio.charset.StandardCharsets.UTF_8);
    }
}
