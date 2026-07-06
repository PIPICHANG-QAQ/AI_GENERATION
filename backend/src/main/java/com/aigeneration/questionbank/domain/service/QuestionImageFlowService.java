package com.aigeneration.questionbank.domain.service;

import com.aigeneration.questionbank.domain.entity.BankQuestionEntity;
import com.aigeneration.questionbank.domain.entity.ImportQuestionEntity;
import com.aigeneration.questionbank.domain.entity.ImportQuestionImageEntity;
import com.aigeneration.questionbank.domain.entity.ImportTaskEntity;
import com.aigeneration.questionbank.domain.entity.StorageFileEntity;
import com.aigeneration.questionbank.domain.support.JsonSupport;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

/**
 * 题图流程服务。
 *
 * <p>负责导入题和题库题的题图上传、任务图库选择、题图预览和响应组装。Java 优先使用
 * 自身文件存储；历史或 worker 产物路径则回退到 Python worker 读取。</p>
 */
@Service
public class QuestionImageFlowService {
    /**
     * 当前允许上传的题图文件后缀。
     */
    private static final List<String> SUPPORTED_IMAGE_EXTENSIONS = List.of("png", "jpg", "jpeg", "webp");

    /**
     * Java 文件存储服务。
     */
    private final JavaFileStorageService fileStorageService;

    /**
     * 导入任务元数据服务。
     */
    private final ImportTaskMetadataService taskService;

    /**
     * 导入题同步服务。
     */
    private final ImportQuestionSyncService importQuestionService;

    /**
     * 题库题服务。
     */
    private final BankQuestionService bankQuestionService;

    /**
     * Python worker 客户端，用于历史题图回退读取。
     */
    private final PythonWorkerClient pythonWorkerClient;

    /**
     * JSON 辅助组件，用于读取任务和题图原始快照。
     */
    private final JsonSupport json;

    /**
     * 注入题图流程需要的服务依赖。
     *
     * @param fileStorageService 文件存储服务
     * @param taskService 导入任务服务
     * @param importQuestionService 导入题服务
     * @param bankQuestionService 题库题服务
     * @param pythonWorkerClient Python worker 客户端
     * @param json JSON 辅助组件
     */
    public QuestionImageFlowService(
            JavaFileStorageService fileStorageService,
            ImportTaskMetadataService taskService,
            ImportQuestionSyncService importQuestionService,
            BankQuestionService bankQuestionService,
            PythonWorkerClient pythonWorkerClient,
            JsonSupport json
    ) {
        this.fileStorageService = fileStorageService;
        this.taskService = taskService;
        this.importQuestionService = importQuestionService;
        this.bankQuestionService = bankQuestionService;
        this.pythonWorkerClient = pythonWorkerClient;
        this.json = json;
    }

    /**
     * 查询导入任务下的题图库。
     *
     * @param taskId 导入任务 ID
     * @return 任务题图库响应
     */
    public Map<String, Object> importTaskImageLibrary(String taskId) {
        requireTask(taskId);
        List<Map<String, Object>> items = new ArrayList<>();
        for (ImportQuestionImageEntity image : importQuestionService.listImagesByTask(taskId)) {
            items.add(importImageToMap(image));
        }
        return Map.of("items", items);
    }

    /**
     * 给导入题上传题图。
     *
     * @param taskId 导入任务 ID
     * @param questionId 导入题 ID
     * @param files 上传文件列表
     * @return 上传结果、题图列表和更新后的题目/任务快照
     */
    public Map<String, Object> uploadImportQuestionImages(String taskId, String questionId, List<MultipartFile> files) {
        requireTask(taskId);
        requireImportQuestion(taskId, questionId);
        List<Map<String, Object>> uploaded = new ArrayList<>();
        for (MultipartFile file : safeFiles(files)) {
            validateImage(file);
            StorageFileEntity stored = fileStorageService.storeImportQuestionImage(questionId, file);
            uploaded.add(imageMap(stored, "/api/import-tasks/" + taskId + "/questions/" + questionId + "/images/" + stored.getId()));
        }
        List<Object> images = importQuestionService.appendImages(taskId, questionId, uploaded);
        Map<String, Object> task = taskMap(taskId);
        return Map.of(
                "images", images,
                "uploaded", uploaded,
                "question", importQuestionService.toMap(requireImportQuestion(taskId, questionId)),
                "task", task
        );
    }

    /**
     * 从任务题图库选择图片并追加到指定导入题。
     *
     * @param taskId 导入任务 ID
     * @param questionId 导入题 ID
     * @param payload 选择载荷
     * @return 选择结果和更新后的题目/任务快照
     */
    public Map<String, Object> selectImportTaskImages(String taskId, String questionId, Map<String, Object> payload) {
        requireTask(taskId);
        requireImportQuestion(taskId, questionId);
        List<Map<String, Object>> selected = selectedTaskImages(taskId, payload);
        if (selected.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "No task images selected");
        }
        List<Object> images = importQuestionService.appendImages(taskId, questionId, selected);
        return Map.of(
                "images", images,
                "selected", selected,
                "question", importQuestionService.toMap(requireImportQuestion(taskId, questionId)),
                "task", taskMap(taskId)
        );
    }

    /**
     * 获取导入题题图文件。
     *
     * @param taskId 导入任务 ID
     * @param questionId 导入题 ID
     * @param imageId 题图 ID
     * @return 文件响应
     */
    public ResponseEntity<?> importQuestionImage(String taskId, String questionId, String imageId) {
        StorageFileEntity file = fileStorageService.findById(imageId);
        if (file != null && questionId.equals(file.getBusinessId())) {
            return fileStorageService.inlineResponse(file);
        }
        return pythonWorkerClient.getFile("/api/import-tasks/" + taskId + "/questions/" + questionId + "/images/" + imageId);
    }

    /**
     * 查询题库题可复用的任务题图库。
     *
     * @param questionId 题库题 ID
     * @return 题图库响应
     */
    public Map<String, Object> bankQuestionImageLibrary(String questionId) {
        BankQuestionEntity question = bankQuestionService.required(questionId);
        String sourceTaskId = question.getSourceImportTaskId();
        if (sourceTaskId == null || sourceTaskId.isBlank()) {
            return Map.of("items", List.of());
        }
        return importTaskImageLibrary(sourceTaskId);
    }

    /**
     * 给题库题上传题图。
     *
     * @param questionId 题库题 ID
     * @param files 上传文件列表
     * @return 上传结果和更新后的题库题快照
     */
    public Map<String, Object> uploadBankQuestionImages(String questionId, List<MultipartFile> files) {
        bankQuestionService.required(questionId);
        List<Map<String, Object>> uploaded = new ArrayList<>();
        for (MultipartFile file : safeFiles(files)) {
            validateImage(file);
            StorageFileEntity stored = fileStorageService.storeBankQuestionImage(questionId, file);
            uploaded.add(imageMap(stored, "/api/question-bank/questions/" + questionId + "/images/" + stored.getId()));
        }
        Map<String, Object> question = bankQuestionService.appendImages(questionId, uploaded);
        return Map.of(
                "images", question.get("images"),
                "uploaded", uploaded,
                "question", question
        );
    }

    /**
     * 获取题库题题图文件。
     *
     * @param questionId 题库题 ID
     * @param imageId 题图 ID
     * @return 文件响应
     */
    public ResponseEntity<?> bankQuestionImage(String questionId, String imageId) {
        StorageFileEntity file = fileStorageService.findById(imageId);
        if (file != null && questionId.equals(file.getBusinessId())) {
            return fileStorageService.inlineResponse(file);
        }
        return pythonWorkerClient.getFile("/api/question-bank/questions/" + questionId + "/images/" + imageId);
    }

    /**
     * 校验并读取导入任务。
     *
     * @param taskId 导入任务 ID
     * @return 导入任务实体
     */
    private ImportTaskEntity requireTask(String taskId) {
        ImportTaskEntity task = taskService.getEntity(taskId);
        if (task == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Import task not found");
        }
        return task;
    }

    /**
     * 校验并读取导入题。
     *
     * @param taskId 导入任务 ID
     * @param questionId 导入题 ID
     * @return 导入题实体
     */
    private ImportQuestionEntity requireImportQuestion(String taskId, String questionId) {
        ImportQuestionEntity question = importQuestionService.getQuestion(questionId);
        if (question == null || !taskId.equals(question.getTaskId())) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Import question not found");
        }
        return question;
    }

    /**
     * 校验上传文件列表非空。
     *
     * @param files 上传文件列表
     * @return 原文件列表
     */
    private List<MultipartFile> safeFiles(List<MultipartFile> files) {
        if (files == null || files.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "No image files uploaded");
        }
        return files;
    }

    /**
     * 校验单个题图文件。
     *
     * @param file 上传文件
     */
    private void validateImage(MultipartFile file) {
        if (file == null || file.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Image file is empty");
        }
        String extension = extension(file.getOriginalFilename());
        if (!SUPPORTED_IMAGE_EXTENSIONS.contains(extension)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Unsupported image type: " + (extension.isBlank() ? "unknown" : extension));
        }
    }

    /**
     * 解析文件后缀。
     *
     * @param filename 文件名
     * @return 小写后缀；无法解析时返回空字符串
     */
    private String extension(String filename) {
        if (filename == null || !filename.contains(".")) {
            return "";
        }
        return filename.substring(filename.lastIndexOf('.') + 1).toLowerCase(Locale.ROOT);
    }

    /**
     * 将存储文件转换为题图响应 Map。
     *
     * @param file 存储文件实体
     * @param url 题图预览 URL
     * @return 题图 Map
     */
    private Map<String, Object> imageMap(StorageFileEntity file, String url) {
        Map<String, Object> image = new LinkedHashMap<>();
        image.put("name", file.getOriginalFilename());
        image.put("path", "java-storage/" + file.getId());
        image.put("url", url);
        image.put("source", "Java 文件存储");
        image.put("size", file.getSizeBytes());
        image.put("type", extension(file.getOriginalFilename()));
        image.put("storageFileId", file.getId());
        return image;
    }

    /**
     * 将导入题图实体转换为任务图库条目。
     *
     * @param image 导入题图实体
     * @return 题图库条目 Map
     */
    private Map<String, Object> importImageToMap(ImportQuestionImageEntity image) {
        Map<String, Object> raw = json.readMap(image.getRawJson());
        Map<String, Object> item = new LinkedHashMap<>(raw);
        item.put("id", image.getId());
        item.put("imageId", image.getId());
        item.putIfAbsent("name", image.getName());
        item.putIfAbsent("path", image.getPath());
        item.putIfAbsent("url", image.getUrl());
        item.put("questionId", image.getQuestionId());
        item.put("imageIndex", image.getImageIndex());
        return item;
    }

    /**
     * 根据请求载荷从任务图库中选择题图。
     *
     * @param taskId 导入任务 ID
     * @param payload 选择载荷
     * @return 去重后的题图列表
     */
    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> selectedTaskImages(String taskId, Map<String, Object> payload) {
        List<Map<String, Object>> library = importQuestionService.listImagesByTask(taskId).stream()
                .map(this::importImageToMap)
                .toList();
        List<Map<String, Object>> selected = new ArrayList<>();
        for (String imageId : stringList(payload == null ? null : payload.get("imageIds"))) {
            Map<String, Object> image = findLibraryImage(library, imageId, "", "");
            if (image != null) {
                selected.add(selectedImageMap(image));
            }
        }
        Object imagesValue = payload == null ? null : payload.get("images");
        if (imagesValue instanceof List<?> images) {
            for (Object item : images) {
                if (!(item instanceof Map<?, ?> raw)) {
                    continue;
                }
                Map<String, Object> image = findLibraryImage(
                        library,
                        firstText(raw.get("imageId"), raw.get("id")),
                        text(raw.get("url")),
                        text(raw.get("path"))
                );
                if (image != null) {
                    selected.add(selectedImageMap(image));
                }
            }
        }
        return dedupeImages(selected);
    }

    /**
     * 在图库中按 imageId、url 或 path 查找题图。
     *
     * @param library 题图库
     * @param imageId 题图 ID
     * @param url 题图 URL
     * @param path 题图路径
     * @return 命中的题图；未命中返回 null
     */
    private Map<String, Object> findLibraryImage(List<Map<String, Object>> library, String imageId, String url, String path) {
        for (Map<String, Object> image : library) {
            if (!imageId.isBlank() && imageId.equals(firstText(image.get("imageId"), image.get("id")))) {
                return image;
            }
            if (!url.isBlank() && url.equals(text(image.get("url")))) {
                return image;
            }
            if (!path.isBlank() && path.equals(text(image.get("path")))) {
                return image;
            }
        }
        return null;
    }

    /**
     * 标记题图来源为任务题图库。
     *
     * @param image 原始图库条目
     * @return 选择后的题图 Map
     */
    private Map<String, Object> selectedImageMap(Map<String, Object> image) {
        Map<String, Object> selected = new LinkedHashMap<>(image);
        selected.put("source", "任务题图库");
        return selected;
    }

    /**
     * 按 storageFileId/url/path/name 对题图去重。
     *
     * @param images 原始题图列表
     * @return 去重后的题图列表
     */
    private List<Map<String, Object>> dedupeImages(List<Map<String, Object>> images) {
        List<Map<String, Object>> result = new ArrayList<>();
        java.util.Set<String> seen = new java.util.LinkedHashSet<>();
        for (Map<String, Object> image : images) {
            String key = firstText(image.get("storageFileId"), image.get("url"), image.get("path"), image.get("name"));
            if (!key.isBlank() && seen.add(key)) {
                result.add(image);
            }
        }
        return result;
    }

    /**
     * 将对象转换为字符串列表。
     *
     * @param value 原始值
     * @return 非空字符串列表
     */
    private List<String> stringList(Object value) {
        if (!(value instanceof List<?> list)) {
            return List.of();
        }
        return list.stream()
                .map(this::text)
                .filter(item -> !item.isBlank())
                .toList();
    }

    /**
     * 返回首个非空文本。
     *
     * @param values 候选值
     * @return 首个非空文本；不存在时返回空字符串
     */
    private String firstText(Object... values) {
        for (Object value : values) {
            String text = text(value);
            if (!text.isBlank()) {
                return text;
            }
        }
        return "";
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
     * 读取任务原始快照并覆盖 Java 状态字段。
     *
     * @param taskId 导入任务 ID
     * @return 任务快照 Map
     */
    private Map<String, Object> taskMap(String taskId) {
        ImportTaskEntity task = taskService.getEntity(taskId);
        if (task == null) {
            return Map.of();
        }
        Map<String, Object> raw = json.readMap(task.getRawJson());
        raw.put("id", task.getId());
        raw.put("status", task.getStatus());
        raw.put("updatedAt", task.getUpdatedAt());
        return raw;
    }
}
