package com.aigeneration.questionbank.capability.controller;

import com.aigeneration.questionbank.capability.model.QuestionProcessingCapabilityModels.CapabilityDescriptor;
import com.aigeneration.questionbank.capability.model.QuestionProcessingCapabilityModels.ProcessingJobView;
import com.aigeneration.questionbank.capability.model.QuestionProcessingCapabilityModels.QuestionPackage;
import com.aigeneration.questionbank.capability.service.QuestionProcessingCapabilityService;
import java.util.List;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

/**
 * question-processing 主能力控制器。
 *
 * <p>该控制器是平台上传试卷/答案并获取标准题目包的推荐入口。Java 负责创建任务、
 * 保存文件、同步 OCR/AI 结果和输出 question-package，Python 只作为 worker 被内部调用。</p>
 */
@RestController
@RequestMapping("/api/capabilities/question-processing")
public class QuestionProcessingCapabilityController {
    /** 题目加工能力服务，负责能力描述、任务视图和标准题目包输出。 */
    private final QuestionProcessingCapabilityService service;

    /**
     * 创建题目加工能力控制器。
     *
     * @param service 题目加工能力服务
     */
    public QuestionProcessingCapabilityController(QuestionProcessingCapabilityService service) {
        this.service = service;
    }

    /**
     * 查询 question-processing 能力描述。
     *
     * @return 能力边界、端点、输入输出和 worker 依赖说明
     */
    @GetMapping
    public CapabilityDescriptor descriptor() {
        return service.descriptor();
    }

    /**
     * 查询题目加工任务列表。
     *
     * @return 所有加工任务的面向平台视图
     */
    @GetMapping("/jobs")
    public List<ProcessingJobView> listJobs() {
        return service.listJobs();
    }

    /**
     * 创建题目加工任务。
     *
     * @param stage 学段，可为空
     * @param subject 学科，可为空
     * @param grade 年级，可为空
     * @param region 地区，可为空
     * @param year 年份，可为空
     * @param title 试卷或任务标题，可为空
     * @param paperFile 必填试卷文件
     * @param answerFile 可选答案/解析文件
     * @return 创建后的加工任务视图
     */
    @PostMapping(value = "/jobs", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ProcessingJobView createJob(
            @RequestParam(defaultValue = "") String stage,
            @RequestParam(defaultValue = "") String subject,
            @RequestParam(defaultValue = "") String grade,
            @RequestParam(defaultValue = "") String region,
            @RequestParam(defaultValue = "") String year,
            @RequestParam(defaultValue = "") String title,
            @RequestParam("paperFile") MultipartFile paperFile,
            @RequestParam(value = "answerFile", required = false) MultipartFile answerFile
    ) {
        return service.createJob(stage, subject, grade, region, year, title, paperFile, answerFile);
    }

    /**
     * 查询单个题目加工任务。
     *
     * @param jobId 加工任务 ID
     * @return 加工任务视图
     */
    @GetMapping("/jobs/{jobId}")
    public ProcessingJobView getJob(@PathVariable String jobId) {
        return service.getJob(jobId);
    }

    /**
     * 获取标准题目包。
     *
     * @param jobId 加工任务 ID
     * @return question-package.v1 标准题目包
     */
    @GetMapping("/jobs/{jobId}/question-package")
    public QuestionPackage questionPackage(@PathVariable String jobId) {
        return service.questionPackage(jobId);
    }
}
