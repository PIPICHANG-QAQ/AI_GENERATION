package com.aigeneration.questionbank.ocrflow.adapter.worker;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.aigeneration.questionbank.config.PythonWorkerProperties;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.Executors;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class PythonWorkerHttpTransportTest {
    private HttpServer server;
    private PythonWorkerHttpTransport transport;

    @BeforeEach
    void setUp() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.setExecutor(Executors.newCachedThreadPool());
        server.createContext("/api/echo", this::echo);
        server.createContext("/api/multipart", this::multipart);
        server.createContext("/api/file", exchange -> respond(exchange, 200, "application/octet-stream", "bin\u0000ary".getBytes(StandardCharsets.ISO_8859_1)));
        server.createContext("/api/client-error", exchange -> respond(exchange, 422, "application/json", "{\"detail\":\"bad\"}".getBytes(StandardCharsets.UTF_8)));
        server.createContext("/api/server-error", exchange -> respond(exchange, 503, "text/plain", "down".getBytes(StandardCharsets.UTF_8)));
        server.createContext("/api/slow", exchange -> {
            try {
                Thread.sleep(500);
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
            }
            respond(exchange, 200, "application/json", "{}".getBytes(StandardCharsets.UTF_8));
        });
        server.start();

        PythonWorkerProperties properties = new PythonWorkerProperties();
        properties.setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
        properties.setConnectTimeoutMs(500);
        properties.setReadTimeoutMs(500);
        transport = new PythonWorkerHttpTransport(properties, new ObjectMapper());
    }

    @AfterEach
    void tearDown() {
        if (server != null) {
            server.stop(0);
        }
    }

    @Test
    void sendsJsonMethodUriAndReusesTransportForRepeatedRequests() {
        PythonWorkerHttpTransport.Response first = transport.postJson("/api/echo?mode=one", Map.of("name", "worker"));
        PythonWorkerHttpTransport.Response second = transport.getJson("/api/echo?mode=two");

        assertEquals(200, first.statusCode());
        assertEquals("/api/echo?mode=one", first.header("X-Seen-Uri"));
        assertEquals("POST", first.header("X-Seen-Method"));
        assertEquals(200, second.statusCode());
        assertEquals("GET", second.header("X-Seen-Method"));
    }

    @Test
    void sendsMultipartFileWithFilenameAndFields() {
        PythonWorkerHttpTransport.Response response = transport.postMultipart(
                "/api/multipart",
                "file",
                "paper.pdf",
                "pdf-bytes".getBytes(StandardCharsets.UTF_8),
                "application/pdf",
                Map.of("jobId", "job-1"));

        assertEquals(200, response.statusCode());
        assertEquals("paper.pdf", response.header("X-Filename"));
        assertEquals("job-1", response.header("X-Job-Id"));
    }

    @Test
    void readsBinaryBodyAndResponseHeaders() {
        PythonWorkerHttpTransport.Response response = transport.get("/api/file");

        assertEquals(200, response.statusCode());
        assertEquals("application/octet-stream", response.header("Content-Type"));
        assertArrayEquals("bin\u0000ary".getBytes(StandardCharsets.ISO_8859_1), response.body());
    }

    @Test
    void mapsClientAndServerErrorsToStructuredException() {
        PythonWorkerHttpTransport.WorkerHttpException client = assertThrows(
                PythonWorkerHttpTransport.WorkerHttpException.class,
                () -> transport.getJson("/api/client-error"));
        PythonWorkerHttpTransport.WorkerHttpException serverError = assertThrows(
                PythonWorkerHttpTransport.WorkerHttpException.class,
                () -> transport.getJson("/api/server-error"));

        assertEquals(422, client.statusCode());
        assertEquals("{\"detail\":\"bad\"}", client.body());
        assertEquals(503, serverError.statusCode());
        assertEquals("down", serverError.body());
    }

    @Test
    void mapsReadTimeoutWithoutChangingHttpStatusSemantics() throws IOException {
        PythonWorkerProperties properties = new PythonWorkerProperties();
        properties.setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
        properties.setConnectTimeoutMs(500);
        properties.setReadTimeoutMs(50);
        PythonWorkerHttpTransport shortTransport = new PythonWorkerHttpTransport(properties, new ObjectMapper());

        PythonWorkerHttpTransport.WorkerHttpException timeout = assertThrows(
                PythonWorkerHttpTransport.WorkerHttpException.class,
                () -> shortTransport.getJson("/api/slow"));

        assertTrue(timeout.timeout());
        assertInstanceOf(java.net.SocketTimeoutException.class, timeout.getCause());
    }

    private void echo(HttpExchange exchange) throws IOException {
        byte[] request = exchange.getRequestBody().readAllBytes();
        exchange.getResponseHeaders().add("X-Seen-Uri", exchange.getRequestURI().toString());
        exchange.getResponseHeaders().add("X-Seen-Method", exchange.getRequestMethod());
        respond(exchange, 200, "application/json", request.length == 0 ? "{}".getBytes(StandardCharsets.UTF_8) : request);
    }

    private void multipart(HttpExchange exchange) throws IOException {
        String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.ISO_8859_1);
        String filename = body.contains("filename=\"paper.pdf\"") ? "paper.pdf" : "";
        String jobId = body.contains("name=\"jobId\"") && body.contains("job-1") ? "job-1" : "";
        exchange.getResponseHeaders().add("X-Filename", filename);
        exchange.getResponseHeaders().add("X-Job-Id", jobId);
        respond(exchange, 200, "application/json", "{}".getBytes(StandardCharsets.UTF_8));
    }

    private void respond(HttpExchange exchange, int status, String contentType, byte[] body) throws IOException {
        exchange.getResponseHeaders().set("Content-Type", contentType);
        exchange.sendResponseHeaders(status, body.length);
        try (var output = exchange.getResponseBody()) {
            output.write(body);
        }
    }
}
