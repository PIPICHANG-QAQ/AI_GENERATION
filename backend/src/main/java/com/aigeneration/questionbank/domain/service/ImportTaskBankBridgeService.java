package com.aigeneration.questionbank.domain.service;

import com.aigeneration.questionbank.config.PythonWorkerProperties;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.net.URI;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import okhttp3.ResponseBody;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.util.UriComponentsBuilder;

/**
 * 导入题入库桥接服务。
 *
 * <p>该服务调用 Python worker 的入库接口，将导入题转换成题库题 payload，然后同步写入
 * Java 侧题库题表，保证本地题库中心能立即看到入库结果。</p>
 */
@Service
public class ImportTaskBankBridgeService {
    /**
     * worker 入库响应按通用 Map 读取。
     */
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    /**
     * Python worker 连接与代理开关配置。
     */
    private final PythonWorkerProperties properties;

    /**
     * JSON 解析器。
     */
    private final ObjectMapper objectMapper;

    /**
     * 题库题服务，用于 upsert 入库后的题目快照。
     */
    private final BankQuestionService bankQuestionService;

    /**
     * 注入 worker 配置、JSON 解析器和题库题服务。
     *
     * @param properties Python worker 配置
     * @param objectMapper JSON 解析器
     * @param bankQuestionService 题库题服务
     */
    public ImportTaskBankBridgeService(
            PythonWorkerProperties properties,
            ObjectMapper objectMapper,
            BankQuestionService bankQuestionService
    ) {
        this.properties = properties;
        this.objectMapper = objectMapper;
        this.bankQuestionService = bankQuestionService;
    }

    /**
     * 将单道导入题入库。
     *
     * @param taskId 导入任务 ID
     * @param questionId 导入题 ID
     * @return worker 入库响应
     */
    public Map<String, Object> bankSingle(String taskId, String questionId) {
        Map<String, Object> response = postPython("/api/import-tasks/" + taskId + "/questions/" + questionId + "/bank");
        syncBankQuestion(response.get("bankQuestion"));
        return response;
    }

    /**
     * 将导入任务下全部题目批量入库。
     *
     * @param taskId 导入任务 ID
     * @return worker 批量入库响应
     */
    public Map<String, Object> bankAll(String taskId) {
        Map<String, Object> response = postPython("/api/import-tasks/" + taskId + "/bank");
        syncBankQuestions(response.get("items"));
        return response;
    }

    /**
     * 同步批量入库结果到 Java 题库题表。
     *
     * @param value worker 返回的题库题列表
     */
    @SuppressWarnings("unchecked")
    private void syncBankQuestions(Object value) {
        if (!(value instanceof List<?> items)) {
            return;
        }
        for (Object item : items) {
            if (item instanceof Map<?, ?> map) {
                syncBankQuestion((Map<String, Object>) map);
            }
        }
    }

    /**
     * 同步单个入库题目到 Java 题库题表。
     *
     * @param value worker 返回的题库题对象
     */
    @SuppressWarnings("unchecked")
    private void syncBankQuestion(Object value) {
        if (value instanceof Map<?, ?> map) {
            bankQuestionService.upsertFromPayload((Map<String, Object>) map);
        }
    }

    /**
     * 向 Python worker 发起空请求体 POST。
     *
     * @param path worker API 路径
     * @return JSON Map 响应
     */
    private Map<String, Object> postPython(String path) {
        if (!properties.isEnabled() || !properties.isApiProxyEnabled()) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Python worker API proxy is disabled");
        }
        URI targetUri = UriComponentsBuilder.fromHttpUrl(properties.getBaseUrl())
                .path(path)
                .build(true)
                .toUri();
        OkHttpClient client = new OkHttpClient.Builder()
                .connectTimeout(Duration.ofMillis(properties.getConnectTimeoutMs()))
                .readTimeout(Duration.ofMillis(properties.getReadTimeoutMs()))
                .writeTimeout(Duration.ofMillis(properties.getReadTimeoutMs()))
                .build();
        Request request = new Request.Builder()
                .url(targetUri.toString())
                .post(RequestBody.create(new byte[0], null))
                .build();
        try (Response response = client.newCall(request).execute()) {
            String body = readBody(response);
            if (!response.isSuccessful()) {
                throw new ResponseStatusException(HttpStatus.valueOf(response.code()), body);
            }
            return readMap(body);
        } catch (ResponseStatusException ex) {
            throw ex;
        } catch (IOException ex) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Python worker bank bridge failed: " + ex.getMessage());
        }
    }

    /**
     * 读取 worker 响应体文本。
     *
     * @param response worker 响应
     * @return 响应文本；空响应体返回空 JSON
     * @throws IOException 读取失败时抛出
     */
    private String readBody(Response response) throws IOException {
        ResponseBody body = response.body();
        return body == null ? "{}" : body.string();
    }

    /**
     * 将 worker JSON 响应解析为 Map。
     *
     * @param body JSON 文本
     * @return 解析后的 Map
     */
    private Map<String, Object> readMap(String body) {
        try {
            return objectMapper.readValue(body, MAP_TYPE);
        } catch (JsonProcessingException ex) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Python worker returned invalid JSON");
        }
    }
}
