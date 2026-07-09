package com.aigeneration.questionbank.domain.service;

import com.aigeneration.questionbank.config.PythonWorkerProperties;
import com.aigeneration.questionbank.domain.entity.ImportTaskEntity;
import com.aigeneration.questionbank.domain.entity.StorageFileEntity;
import com.aigeneration.questionbank.domain.support.Ids;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.net.URI;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import okhttp3.OkHttpClient;
import okhttp3.MediaType;
import okhttp3.MultipartBody;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import okhttp3.ResponseBody;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.util.UriComponentsBuilder;

/**
 * 导入任务 Python worker 桥接服务。
 *
 * <p>该服务对外保持 Java API 入口，对内调用 Python worker 的导入任务接口，并在关键路径上
 * 同步 Java 侧任务/题目快照、保存上传原文件、优先用 Java 存储提供源文件预览。</p>
 */
@Service
public class ImportTaskMetadataBridgeService {
    /**
     * worker JSON 响应统一按通用 Map 读取。
     */
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    /**
     * Jackson 反序列化任意 JSON 值的类型引用。
     */
    private static final TypeReference<Object> OBJECT_TYPE = new TypeReference<>() {};

    /**
     * Python worker 连接与代理开关配置。
     */
    private final PythonWorkerProperties properties;

    /**
     * JSON 序列化/反序列化组件。
     */
    private final ObjectMapper objectMapper;

    /**
     * Java 侧任务元数据同步服务。
     */
    private final ImportTaskMetadataService metadataService;

    /**
     * Java 侧题目同步服务，用于 worker 状态缺失时从持久化题目表重建任务详情。
     */
    private final ImportQuestionSyncService importQuestionSyncService;

    /**
     * Java 文件存储服务，用于保存上传原文件并提供预览回退。
     */
    private final JavaFileStorageService fileStorageService;

    /**
     * 任务级恢复锁，避免多个详情轮询请求同时重建同一个 OCR 任务。
     */
    private final Map<String, Object> recoveryLocks = new ConcurrentHashMap<>();

    /**
     * 注入 worker 配置、JSON、任务同步和文件存储服务。
     *
     * @param properties Python worker 配置
     * @param objectMapper JSON 处理器
     * @param metadataService 任务元数据同步服务
     * @param fileStorageService Java 文件存储服务
     */
    public ImportTaskMetadataBridgeService(
            PythonWorkerProperties properties,
            ObjectMapper objectMapper,
            ImportTaskMetadataService metadataService,
            ImportQuestionSyncService importQuestionSyncService,
            JavaFileStorageService fileStorageService
    ) {
        this.properties = properties;
        this.objectMapper = objectMapper;
        this.metadataService = metadataService;
        this.importQuestionSyncService = importQuestionSyncService;
        this.fileStorageService = fileStorageService;
    }

    /**
     * 返回 Java 侧导入任务快照列表。
     *
     * <p>列表页只需要任务摘要，不能同步等待 Python worker。worker 在开发 reload、OCR
     * 正忙或临时不可达时，阻塞这里会导致前端“任务记录”长时间停在加载态；任务创建和任务详情
     * 查询仍会负责同步最新 OCR 状态。</p>
     *
     * @return items/total 结构
     */
    public Map<String, Object> list() {
        List<Map<String, Object>> items = metadataService.listEntities()
                .stream()
                .map(this::javaSnapshot)
                .toList();
        return Map.of("items", items, "total", items.size());
    }

    /**
     * 创建导入任务。
     *
     * <p>上传文件会先保存到 Java 文件存储中，worker 创建成功后再把业务 ID 从临时 ID 改为
     * 真实任务 ID；若 worker 创建失败，会删除已保存文件，避免出现悬挂文件记录。</p>
     *
     * @param stage 学段
     * @param subject 学科
     * @param grade 年级
     * @param region 地区
     * @param year 年份
     * @param title 标题
     * @param paperFile 试卷文件
     * @param answerFile 答案文件，可为空
     * @return 创建后的任务响应
     */
    public Map<String, Object> create(
            String stage,
            String subject,
            String grade,
            String region,
            String year,
            String title,
            MultipartFile paperFile,
            MultipartFile answerFile
    ) {
        ensureOcrProviderReadyForUploads(paperFile, answerFile);
        String pendingBusinessId = Ids.next("pending_import_upload");
        List<StorageFileEntity> storedFiles = storeImportUploads(pendingBusinessId, paperFile, answerFile);
        Map<String, Object> response;
        try {
            response = postMultipartToPython(
                    "/api/import-tasks",
                    buildCreateBody(stage, subject, grade, region, year, title, paperFile, answerFile)
            );
        } catch (RuntimeException ex) {
            fileStorageService.deleteAll(storedFiles);
            throw ex;
        }
        fileStorageService.reassignBusinessId(storedFiles, text(response.get("id")));
        response.put("javaStorageFileIds", storedFiles.stream().map(StorageFileEntity::getId).toList());
        metadataService.syncOne(response);
        applyJavaStatus(response);
        return response;
    }

    /**
     * 在保存原文件和创建任务前确认 OCR provider 可处理上传文件。
     *
     * <p>Markdown 文件不需要 OCR provider；PDF、图片、Office 等需要 provider 的文件如果缺少
     * MinerU，应在创建任务前失败，避免生成一个马上进入 OCR failed 的导入任务。</p>
     *
     * @param files 上传文件列表
     */
    private void ensureOcrProviderReadyForUploads(MultipartFile... files) {
        boolean providerRequired = false;
        for (MultipartFile file : files) {
            if (requiresOcrProvider(file)) {
                providerRequired = true;
                break;
            }
        }
        if (!providerRequired) {
            return;
        }

        Map<String, Object> runtime = getPython("/worker/ocr-flow");
        Map<String, Object> providerStatus = asMap(runtime.get("providerStatus"));
        if (Boolean.TRUE.equals(providerStatus.get("installed"))) {
            return;
        }
        String error = text(providerStatus.get("error"));
        throw new ResponseStatusException(
                HttpStatus.SERVICE_UNAVAILABLE,
                "OCR provider is unavailable. Run ./scripts/deploy_local.sh --with-mineru or configure MINERU_COMMAND."
                        + (error.isBlank() ? "" : " " + error)
        );
    }

    /**
     * 判断上传文件是否需要 OCR provider。
     *
     * @param file 上传文件
     * @return true 表示需要 OCR provider
     */
    private boolean requiresOcrProvider(MultipartFile file) {
        if (file == null || file.isEmpty()) {
            return false;
        }
        String filename = safeFilename(file);
        String suffix = "";
        int dot = filename.lastIndexOf('.');
        if (dot >= 0) {
            suffix = filename.substring(dot).toLowerCase(Locale.ROOT);
        }
        return !suffix.equals(".md") && !suffix.equals(".markdown");
    }

    /**
     * 查询单个导入任务并同步 Java 状态。
     *
     * @param taskId 任务 ID
     * @return 任务响应
     */
    public Map<String, Object> get(String taskId) {
        try {
            Map<String, Object> response = getPython("/api/import-tasks/" + taskId);
            metadataService.syncOne(response);
            applyJavaStatus(response);
            return response;
        } catch (ResponseStatusException ex) {
            if (canFallbackToJavaSnapshot(ex)) {
                Map<String, Object> recovered = recoverFromOcrSnapshot(taskId);
                if (recovered != null) {
                    return recovered;
                }
                return javaSnapshot(taskId);
            }
            throw ex;
        }
    }

    /**
     * 获取任务原文件预览。
     *
     * <p>优先读取 Java 保存的上传文件；如果历史任务没有 Java 文件记录，则回退到 Python
     * worker 的 source 接口。</p>
     *
     * @param taskId 任务 ID
     * @param kind 原文件类型，paper 或 answer
     * @return 文件响应
     */
    public ResponseEntity<?> source(String taskId, String kind) {
        String fieldName = sourceFieldName(kind);
        StorageFileEntity file = fileStorageService.findImportUpload(taskId, fieldName);
        if (file != null) {
            return fileStorageService.inlineResponse(file);
        }
        return getPythonFile("/api/import-tasks/" + taskId + "/source/" + kind);
    }

    /**
     * 获取试卷单页预览图。
     *
     * <p>布局解析框依赖 worker 的 OCR 输出和 PDF 渲染尺寸，因此页图固定从 worker 获取，
     * 不走 Java 原文件回退。</p>
     *
     * @param taskId 任务 ID
     * @param pageIndex 从 0 开始的页码
     * @return 文件响应
     */
    public ResponseEntity<?> sourcePaperPage(String taskId, int pageIndex) {
        if (pageIndex < 0) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Page not found");
        }
        return getPythonFile("/api/import-tasks/" + taskId + "/source/paper/pages/" + pageIndex);
    }

    /**
     * 更新导入任务并同步 Java 快照。
     *
     * @param taskId 任务 ID
     * @param payload 更新载荷
     * @return 更新后的任务响应
     */
    public Map<String, Object> update(String taskId, Map<String, Object> payload) {
        Map<String, Object> response = jsonToPython("PUT", "/api/import-tasks/" + taskId, payload);
        metadataService.syncOne(response);
        applyJavaStatus(response);
        return response;
    }

    /**
     * 删除导入任务。
     *
     * @param taskId 任务 ID
     * @return 删除响应
     */
    public Map<String, Object> delete(String taskId) {
        Map<String, Object> response = jsonToPython("DELETE", "/api/import-tasks/" + taskId, null);
        if (Boolean.TRUE.equals(response.get("deleted"))) {
            metadataService.delete(taskId);
        }
        return response;
    }

    /**
     * 批量删除导入任务。
     *
     * @param payload 批量删除载荷
     * @return 批量删除响应
     */
    public Map<String, Object> batchDelete(Map<String, Object> payload) {
        Map<String, Object> response = jsonToPython("POST", "/api/import-tasks/batch-delete", payload);
        if (Boolean.TRUE.equals(response.get("deleted"))) {
            metadataService.deleteMany(response.get("deletedIds"));
        }
        return response;
    }

    /**
     * 向 Python worker 发起 GET JSON 请求。
     *
     * @param path worker API 路径
     * @return JSON Map 响应
     */
    private Map<String, Object> getPython(String path) {
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
        Request request = new Request.Builder().url(targetUri.toString()).get().build();
        try (Response response = client.newCall(request).execute()) {
            String body = readBody(response);
            if (!response.isSuccessful()) {
                throw new ResponseStatusException(HttpStatus.valueOf(response.code()), body);
            }
            return readMap(body);
        } catch (ResponseStatusException ex) {
            throw ex;
        } catch (IOException ex) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Python worker import task bridge failed: " + ex.getMessage());
        }
    }

    /**
     * 向 Python worker 获取二进制文件并保留关键响应头。
     *
     * @param path worker 文件接口路径
     * @return 文件字节响应
     */
    private ResponseEntity<byte[]> getPythonFile(String path) {
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
        Request request = new Request.Builder().url(targetUri.toString()).get().build();
        try (Response response = client.newCall(request).execute()) {
            if (!response.isSuccessful()) {
                throw new ResponseStatusException(HttpStatus.valueOf(response.code()), readBody(response));
            }
            ResponseBody body = response.body();
            byte[] bytes = body == null ? new byte[0] : body.bytes();
            ResponseEntity.BodyBuilder builder = ResponseEntity.status(response.code());
            copyHeader(response, builder, HttpHeaders.CONTENT_TYPE);
            copyHeader(response, builder, HttpHeaders.CONTENT_DISPOSITION);
            copyHeader(response, builder, HttpHeaders.CONTENT_LENGTH);
            return builder.body(bytes);
        } catch (ResponseStatusException ex) {
            throw ex;
        } catch (IOException ex) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Python worker source bridge failed: " + ex.getMessage());
        }
    }

    /**
     * 向 Python worker 发起 JSON 请求。
     *
     * @param method HTTP 方法
     * @param path worker API 路径
     * @param payload JSON 请求体，可为空
     * @return JSON Map 响应
     */
    private Map<String, Object> jsonToPython(String method, String path, Object payload) {
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
        RequestBody requestBody = payload == null ? null : jsonBody(payload);
        Request request = new Request.Builder().url(targetUri.toString()).method(method, requestBody).build();
        try (Response response = client.newCall(request).execute()) {
            String body = readBody(response);
            if (!response.isSuccessful()) {
                throw new ResponseStatusException(HttpStatus.valueOf(response.code()), body);
            }
            return readMap(body);
        } catch (ResponseStatusException ex) {
            throw ex;
        } catch (IOException ex) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Python worker import task bridge failed: " + ex.getMessage());
        }
    }

    /**
     * 向 Python worker 提交 multipart 创建请求。
     *
     * @param path worker API 路径
     * @param requestBody multipart 请求体
     * @return JSON Map 响应
     */
    private Map<String, Object> postMultipartToPython(String path, RequestBody requestBody) {
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
        Request request = new Request.Builder().url(targetUri.toString()).post(requestBody).build();
        try (Response response = client.newCall(request).execute()) {
            String body = readBody(response);
            if (!response.isSuccessful()) {
                throw new ResponseStatusException(HttpStatus.valueOf(response.code()), body);
            }
            return readMap(body);
        } catch (ResponseStatusException ex) {
            throw ex;
        } catch (IOException ex) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Python worker import task create failed: " + ex.getMessage());
        }
    }

    /**
     * 将 Java 对象序列化为 JSON 请求体。
     *
     * @param payload 请求载荷
     * @return OkHttp JSON 请求体
     */
    private RequestBody jsonBody(Object payload) {
        try {
            return RequestBody.create(
                    objectMapper.writeValueAsBytes(payload),
                    MediaType.parse("application/json; charset=utf-8")
            );
        } catch (JsonProcessingException ex) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid import task payload");
        }
    }

    /**
     * 构造导入任务创建所需的 multipart 请求体。
     *
     * @param stage 学段
     * @param subject 学科
     * @param grade 年级
     * @param region 地区
     * @param year 年份
     * @param title 标题
     * @param paperFile 试卷文件
     * @param answerFile 答案文件，可为空
     * @return multipart 请求体
     */
    private RequestBody buildCreateBody(
            String stage,
            String subject,
            String grade,
            String region,
            String year,
            String title,
            MultipartFile paperFile,
            MultipartFile answerFile
    ) {
        MultipartBody.Builder builder = new MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart("stage", safeText(stage))
                .addFormDataPart("subject", safeText(subject))
                .addFormDataPart("grade", safeText(grade))
                .addFormDataPart("region", safeText(region))
                .addFormDataPart("year", safeText(year))
                .addFormDataPart("title", safeText(title))
                .addFormDataPart("paperFile", safeFilename(paperFile), fileBody(paperFile));
        if (answerFile != null && !answerFile.isEmpty()) {
            builder.addFormDataPart("answerFile", safeFilename(answerFile), fileBody(answerFile));
        }
        return builder.build();
    }

    /**
     * 保存导入任务上传的原文件。
     *
     * @param businessId 临时或真实业务 ID
     * @param paperFile 试卷文件
     * @param answerFile 答案文件，可为空
     * @return 已保存文件实体列表
     */
    private List<StorageFileEntity> storeImportUploads(
            String businessId,
            MultipartFile paperFile,
            MultipartFile answerFile
    ) {
        List<StorageFileEntity> storedFiles = new ArrayList<>();
        storedFiles.add(fileStorageService.storeImportUpload(businessId, "paperFile", paperFile));
        if (answerFile != null && !answerFile.isEmpty()) {
            storedFiles.add(fileStorageService.storeImportUpload(businessId, "answerFile", answerFile));
        }
        return storedFiles;
    }

    /**
     * 返回非 null 文本。
     *
     * @param value 原始文本
     * @return 文本；null 返回空字符串
     */
    private String safeText(String value) {
        return value == null ? "" : value;
    }

    /**
     * 将 source kind 映射为上传文件字段名。
     *
     * @param kind paper 或 answer
     * @return 文件字段名
     */
    private String sourceFieldName(String kind) {
        if ("paper".equals(kind)) {
            return "paperFile";
        }
        if ("answer".equals(kind)) {
            return "answerFile";
        }
        throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid source kind");
    }

    /**
     * 从 worker 响应复制指定响应头。
     *
     * @param response worker 响应
     * @param builder Java 响应构造器
     * @param name 响应头名称
     */
    private void copyHeader(Response response, ResponseEntity.BodyBuilder builder, String name) {
        String value = response.header(name);
        if (value != null && !value.isBlank()) {
            builder.header(name, value);
        }
    }

    /**
     * 将对象转换为去首尾空白文本。
     *
     * @param value 原始值
     * @return 文本；null 返回空字符串
     */
    private String text(Object value) {
        return value == null ? "" : String.valueOf(value).trim();
    }

    /**
     * 获取安全的上传文件名。
     *
     * @param file 上传文件
     * @return 文件名；缺失时返回 upload
     */
    private String safeFilename(MultipartFile file) {
        String filename = file == null ? "" : file.getOriginalFilename();
        return filename == null || filename.isBlank() ? "upload" : filename;
    }

    /**
     * 将 MultipartFile 转换为 OkHttp 文件请求体。
     *
     * @param file 上传文件
     * @return 文件请求体
     */
    private RequestBody fileBody(MultipartFile file) {
        try {
            String contentType = file.getContentType();
            MediaType mediaType = contentType == null || contentType.isBlank() ? null : MediaType.parse(contentType);
            return RequestBody.create(file.getBytes(), mediaType);
        } catch (IOException ex) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Cannot read uploaded file: " + ex.getMessage());
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
     * 将 worker JSON 文本解析为 Map。
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

    /**
     * 使用 Java 侧快照覆盖 worker 响应中的状态字段。
     *
     * @param task worker 返回的任务 Map
     */
    private void applyJavaStatus(Map<String, Object> task) {
        String id = task.get("id") == null ? "" : String.valueOf(task.get("id"));
        if (id.isBlank()) {
            return;
        }
        ImportTaskEntity entity = metadataService.getEntity(id);
        if (entity == null) {
            return;
        }
        task.put("status", entity.getStatus());
        task.put("paperOcrStatus", entity.getPaperOcrStatus());
        task.put("answerOcrStatus", entity.getAnswerOcrStatus());
        task.put("failureReason", entity.getFailureReason());
    }

    /**
     * 判断 worker 查询失败时是否允许退回 Java 持久化快照。
     *
     * @param ex worker 调用异常
     * @return true 表示可以退回 Java 快照
     */
    private boolean canFallbackToJavaSnapshot(ResponseStatusException ex) {
        int status = ex.getStatusCode().value();
        return status == HttpStatus.NOT_FOUND.value()
                || status == HttpStatus.BAD_GATEWAY.value()
                || status == HttpStatus.SERVICE_UNAVAILABLE.value()
                || status >= 500;
    }

    /**
     * 根据任务 ID 构造 Java 持久化快照。
     *
     * @param taskId 任务 ID
     * @return 任务详情 Map
     */
    private Map<String, Object> javaSnapshot(String taskId) {
        ImportTaskEntity entity = metadataService.getEntity(taskId);
        if (entity == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Import task not found");
        }
        return javaSnapshot(entity);
    }

    /**
     * 将 Java 任务实体和题目表重建为前端兼容的任务详情结构。
     *
     * @param entity Java 任务实体
     * @return 任务详情 Map
     */
    private Map<String, Object> javaSnapshot(ImportTaskEntity entity) {
        Map<String, Object> task = readMapOrEmpty(entity.getRawJson());
        task.put("id", entity.getId());
        task.put("stage", entity.getStage());
        task.put("subject", entity.getSubject());
        task.put("grade", entity.getGrade());
        task.put("region", entity.getRegion());
        task.put("year", entity.getYear());
        task.put("title", entity.getTitle());
        task.put("status", entity.getStatus());
        task.put("paperFile", readMapOrNull(entity.getPaperFileJson()));
        task.put("answerFile", readMapOrNull(entity.getAnswerFileJson()));
        task.put("paperOcrJobId", entity.getPaperOcrJobId());
        task.put("answerOcrJobId", entity.getAnswerOcrJobId());
        task.put("paperOcrJob", readMapOrNull(entity.getPaperOcrJobJson()));
        task.put("answerOcrJob", readMapOrNull(entity.getAnswerOcrJobJson()));
        task.put("paperOcrStatus", entity.getPaperOcrStatus());
        task.put("answerOcrStatus", entity.getAnswerOcrStatus());
        task.put("failureReason", entity.getFailureReason());
        task.put("questionCount", entity.getQuestionCount());
        task.put("questions", importQuestionSyncService.listByTask(entity.getId())
                .stream()
                .map(importQuestionSyncService::toMap)
                .toList());
        task.put("createdAt", entity.getCreatedAt());
        task.put("updatedAt", entity.getUpdatedAt());
        task.put("snapshotSource", "java");
        return task;
    }

    /**
     * worker 任务临时状态丢失时，尝试用 Java 快照中的 OCR job 恢复任务题目。
     *
     * @param taskId 任务 ID
     * @return 恢复后的任务；无法恢复时返回 null
     */
    private Map<String, Object> recoverFromOcrSnapshot(String taskId) {
        Object lock = recoveryLocks.computeIfAbsent(taskId, ignored -> new Object());
        try {
            synchronized (lock) {
                ImportTaskEntity entity = metadataService.getEntity(taskId);
                if (!shouldAttemptOcrRecovery(entity)) {
                    return null;
                }
                try {
                    Map<String, Object> response = jsonToPython("POST", "/worker/import-tasks/recover", javaSnapshot(entity));
                    metadataService.syncOne(response);
                    applyJavaStatus(response);
                    response.put("snapshotSource", "worker-recovered");
                    return response;
                } catch (RuntimeException ex) {
                    return null;
                }
            }
        } finally {
            recoveryLocks.remove(taskId, lock);
        }
    }

    /**
     * 判断当前 Java 快照是否需要尝试 OCR 恢复。
     *
     * @param entity Java 任务实体
     * @return true 表示应尝试恢复
     */
    private boolean shouldAttemptOcrRecovery(ImportTaskEntity entity) {
        if (entity == null || text(entity.getPaperOcrJobId()).isBlank()) {
            return false;
        }
        boolean processing = "处理中".equals(entity.getStatus())
                || "pending".equals(entity.getPaperOcrStatus())
                || "running".equals(entity.getPaperOcrStatus());
        int questionCount = entity.getQuestionCount() == null ? 0 : entity.getQuestionCount();
        return processing || questionCount == 0;
    }

    /**
     * 从 JSON 字符串读取 Map；读取失败或非 Map 时返回空 Map。
     *
     * @param json JSON 字符串
     * @return Map 数据
     */
    private Map<String, Object> readMapOrEmpty(String json) {
        Object value = readJsonValue(json);
        return asMap(value);
    }

    /**
     * 将任意对象转换为字符串键 Map；非 Map 时返回空 Map。
     *
     * @param value 原始对象
     * @return Map 数据
     */
    private Map<String, Object> asMap(Object value) {
        if (value instanceof Map<?, ?> map) {
            Map<String, Object> result = new LinkedHashMap<>();
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                result.put(String.valueOf(entry.getKey()), entry.getValue());
            }
            return result;
        }
        return new LinkedHashMap<>();
    }

    /**
     * 从 JSON 字符串读取 Map；读取失败或非 Map 时返回 null。
     *
     * @param json JSON 字符串
     * @return Map 数据或 null
     */
    private Map<String, Object> readMapOrNull(String json) {
        Map<String, Object> value = readMapOrEmpty(json);
        return value.isEmpty() ? null : value;
    }

    /**
     * 从 JSON 字符串读取任意对象。
     *
     * @param json JSON 字符串
     * @return 解析后的对象；失败时返回 null
     */
    private Object readJsonValue(String json) {
        if (json == null || json.isBlank()) {
            return null;
        }
        try {
            return objectMapper.readValue(json, OBJECT_TYPE);
        } catch (JsonProcessingException ex) {
            return null;
        }
    }
}
