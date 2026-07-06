package com.aigeneration.questionbank.domain.controller;

import com.aigeneration.questionbank.domain.service.QuestionImageFlowService;
import java.util.List;
import java.util.Map;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

/**
 * 题图文件流控制器。
 *
 * <p>该控制器负责导入题和题库题的题图库、题图读取、题图上传和任务题图库选择。
 * 文件元数据和二进制内容由 Java file-flow 管理，旧 OCR 图片可由服务层回退读取。</p>
 */
@RestController
public class QuestionImageFlowController {
    /** 题图文件流服务，负责图片库查询、文件读取、上传和选择写回。 */
    private final QuestionImageFlowService service;

    /**
     * 创建题图文件流控制器。
     *
     * @param service 题图文件流服务
     */
    public QuestionImageFlowController(QuestionImageFlowService service) {
        this.service = service;
    }

    /**
     * 查询导入任务题图库。
     *
     * @param taskId 导入任务 ID
     * @return 当前任务可复用的 OCR/上传题图列表
     */
    @GetMapping("/api/import-tasks/{taskId}/image-library")
    public Map<String, Object> importTaskImageLibrary(@PathVariable String taskId) {
        return service.importTaskImageLibrary(taskId);
    }

    /**
     * 读取导入题题图文件。
     *
     * @param taskId 导入任务 ID
     * @param questionId 导入题 ID
     * @param imageId 题图 ID
     * @return 图片二进制响应
     */
    @GetMapping("/api/import-tasks/{taskId}/questions/{questionId}/images/{imageId}")
    public ResponseEntity<?> importQuestionImage(
            @PathVariable String taskId,
            @PathVariable String questionId,
            @PathVariable String imageId
    ) {
        return service.importQuestionImage(taskId, questionId, imageId);
    }

    /**
     * 为导入题上传题图。
     *
     * @param taskId 导入任务 ID
     * @param questionId 导入题 ID
     * @param files 上传文件列表
     * @return 上传后的题图列表和题目快照
     */
    @PostMapping(value = "/api/import-tasks/{taskId}/questions/{questionId}/images", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public Map<String, Object> uploadImportQuestionImages(
            @PathVariable String taskId,
            @PathVariable String questionId,
            @RequestParam("files") List<MultipartFile> files
    ) {
        return service.uploadImportQuestionImages(taskId, questionId, files);
    }

    /**
     * 从任务题图库选择图片挂载到导入题。
     *
     * @param taskId 导入任务 ID
     * @param questionId 导入题 ID
     * @param payload 包含 imageIds 或 images 的选择请求
     * @return 选择后的题图列表和题目快照
     */
    @PostMapping("/api/import-tasks/{taskId}/questions/{questionId}/images/select")
    public Map<String, Object> selectImportTaskImages(
            @PathVariable String taskId,
            @PathVariable String questionId,
            @RequestBody Map<String, Object> payload
    ) {
        return service.selectImportTaskImages(taskId, questionId, payload);
    }

    /**
     * 查询题库题可复用题图库。
     *
     * @param questionId 题库题 ID
     * @return 题库题相关题图库
     */
    @GetMapping("/api/question-bank/questions/{questionId}/image-library")
    public Map<String, Object> bankQuestionImageLibrary(@PathVariable String questionId) {
        return service.bankQuestionImageLibrary(questionId);
    }

    /**
     * 读取题库题题图文件。
     *
     * @param questionId 题库题 ID
     * @param imageId 题图 ID
     * @return 图片二进制响应
     */
    @GetMapping("/api/question-bank/questions/{questionId}/images/{imageId}")
    public ResponseEntity<?> bankQuestionImage(@PathVariable String questionId, @PathVariable String imageId) {
        return service.bankQuestionImage(questionId, imageId);
    }

    /**
     * 为题库题上传题图。
     *
     * @param questionId 题库题 ID
     * @param files 上传文件列表
     * @return 上传后的题图列表和题库题快照
     */
    @PostMapping(value = "/api/question-bank/questions/{questionId}/images", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public Map<String, Object> uploadBankQuestionImages(
            @PathVariable String questionId,
            @RequestParam("files") List<MultipartFile> files
    ) {
        return service.uploadBankQuestionImages(questionId, files);
    }
}
