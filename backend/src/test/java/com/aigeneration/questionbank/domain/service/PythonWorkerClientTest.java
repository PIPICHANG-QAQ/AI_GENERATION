package com.aigeneration.questionbank.domain.service;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.aigeneration.questionbank.config.PythonWorkerProperties;
import com.aigeneration.questionbank.ocrflow.adapter.worker.PythonWorkerHttpTransport;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.web.server.ResponseStatusException;

class PythonWorkerClientTest {
    private HttpServer server;
    private PythonWorkerProperties properties;
    private PythonWorkerClient client;

    @BeforeEach
    void setUp() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/json", this::json);
        server.createContext("/api/file", exchange -> {
            exchange.getResponseHeaders().set("Content-Type", "application/pdf");
            exchange.getResponseHeaders().set("Content-Disposition", "attachment; filename=worker.pdf");
            respond(exchange, 200, "application/pdf", "pdf\u0000bytes".getBytes(StandardCharsets.ISO_8859_1));
        });
        server.createContext("/api/client-error", exchange -> respond(exchange, 422, "application/json", "bad".getBytes(StandardCharsets.UTF_8)));
        server.createContext("/api/server-error", exchange -> respond(exchange, 503, "text/plain", "down".getBytes(StandardCharsets.UTF_8)));
        server.start();

        properties = new PythonWorkerProperties();
        properties.setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
        properties.setConnectTimeoutMs(500);
        properties.setReadTimeoutMs(500);
        ObjectMapper mapper = new ObjectMapper();
        client = new PythonWorkerClient(properties, mapper, new PythonWorkerHttpTransport(properties, mapper));
    }

    @AfterEach
    void tearDown() {
        if (server != null) {
            server.stop(0);
        }
    }

    @Test
    void preservesJsonMethodsAndPayloadSemanticsThroughTransport() {
        assertEquals("GET", client.getJson("/api/json?method=get").get("method"));
        assertEquals("POST", client.postJson("/api/json?method=post", Map.of("value", 1)).get("method"));
        assertEquals("PUT", client.putJson("/api/json?method=put", Map.of("value", 2)).get("method"));
        assertEquals("DELETE", client.deleteJson("/api/json?method=delete").get("method"));
        assertEquals("/api/json?method=post", client.postJson("/api/json?method=post", Map.of("value", 1)).get("uri"));
        assertEquals(Map.of(), client.postJson("/api/json?method=post-empty", null).get("payload"));
    }

    @Test
    void preservesFileBytesAndSelectedHeaders() {
        var response = client.getFile("/api/file");

        assertEquals(200, response.getStatusCode().value());
        assertArrayEquals("pdf\u0000bytes".getBytes(StandardCharsets.ISO_8859_1), response.getBody());
        assertEquals("application/pdf", response.getHeaders().getFirst(HttpHeaders.CONTENT_TYPE));
        assertEquals("attachment; filename=worker.pdf", response.getHeaders().getFirst(HttpHeaders.CONTENT_DISPOSITION));
        assertEquals("9", response.getHeaders().getFirst(HttpHeaders.CONTENT_LENGTH));
    }

    @Test
    void preservesWorkerHttpStatusAndBodyOnClientAndServerErrors() {
        ResponseStatusException clientError = assertThrows(
                ResponseStatusException.class,
                () -> client.getJson("/api/client-error"));
        ResponseStatusException serverError = assertThrows(
                ResponseStatusException.class,
                () -> client.getFile("/api/server-error"));

        assertEquals(422, clientError.getStatusCode().value());
        assertEquals("bad", clientError.getReason());
        assertEquals(503, serverError.getStatusCode().value());
        assertEquals("down", serverError.getReason());
    }

    @Test
    void disabledWorkerAndProxyBothRemainServiceUnavailable() {
        properties.setEnabled(false);
        ResponseStatusException disabled = assertThrows(
                ResponseStatusException.class,
                () -> client.getJson("/api/json"));
        assertEquals(503, disabled.getStatusCode().value());
        assertEquals("Python worker API proxy is disabled", disabled.getReason());

        properties.setEnabled(true);
        properties.setApiProxyEnabled(false);
        ResponseStatusException proxyDisabled = assertThrows(
                ResponseStatusException.class,
                () -> client.getJson("/api/json"));
        assertEquals(503, proxyDisabled.getStatusCode().value());
        assertEquals("Python worker API proxy is disabled", proxyDisabled.getReason());
    }

    @Test
    void keepsTwoArgumentConstructorCompatible() {
        PythonWorkerClient compatible = new PythonWorkerClient(properties, new ObjectMapper());

        assertEquals("GET", compatible.getJson("/api/json?method=get").get("method"));
    }

    private void json(HttpExchange exchange) throws IOException {
        byte[] body = exchange.getRequestBody().readAllBytes();
        String payload = body.length == 0 ? "{}" : new String(body, StandardCharsets.UTF_8);
        String response = "{\"method\":\"" + exchange.getRequestMethod()
                + "\",\"uri\":\"" + exchange.getRequestURI() + "\",\"payload\":" + payload + "}";
        respond(exchange, 200, "application/json", response.getBytes(StandardCharsets.UTF_8));
    }

    private void respond(HttpExchange exchange, int status, String contentType, byte[] body) throws IOException {
        exchange.getResponseHeaders().set("Content-Type", contentType);
        exchange.sendResponseHeaders(status, body.length);
        try (var output = exchange.getResponseBody()) {
            output.write(body);
        }
    }
}
