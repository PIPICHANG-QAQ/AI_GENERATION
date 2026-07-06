package com.aigeneration.questionbank.capability.controller;

import com.aigeneration.questionbank.capability.service.CapabilityCatalogService;
import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 能力总目录控制器。
 *
 * <p>该控制器向平台暴露 question-engine 的能力目录和各补充能力描述。
 * 返回值是面向集成的稳定描述对象，不直接执行业务加工。</p>
 */
@RestController
@RequestMapping("/api/capabilities")
public class CapabilityCatalogController {
    /** 能力目录服务，负责组织 core/supplemental capability 描述和运行时摘要。 */
    private final CapabilityCatalogService service;

    /**
     * 创建能力总目录控制器。
     *
     * @param service 能力目录服务
     */
    public CapabilityCatalogController(CapabilityCatalogService service) {
        this.service = service;
    }

    /**
     * 查询全部能力目录。
     *
     * @return core capability 和 supplemental capability 列表
     */
    @GetMapping
    public List<Map<String, Object>> catalog() {
        return service.catalog();
    }

    /**
     * 查询人工校验工作台能力描述。
     *
     * @return review-workbench 能力边界、端点和平台职责
     */
    @GetMapping("/review-workbench")
    public Map<String, Object> reviewWorkbench() {
        return service.reviewWorkbench();
    }

    /**
     * 查询 AI-Flow 能力描述。
     *
     * @return AI 标准化、AI 解析和答案解析匹配能力边界
     */
    @GetMapping("/ai-flow")
    public Map<String, Object> aiFlow() {
        return service.aiFlow();
    }

    /**
     * 查询 AI-Flow 运行时。
     *
     * @return 大模型配置、worker 可达性和 AI worker 端点摘要
     */
    @GetMapping("/ai-flow/runtime")
    public Map<String, Object> aiFlowRuntime() {
        return service.aiFlowRuntime();
    }

    /**
     * 查询 Export-Flow 能力描述。
     *
     * @return 试卷 Markdown/DOCX/PDF 导出边界和端点说明
     */
    @GetMapping("/export-flow")
    public Map<String, Object> exportFlow() {
        return service.exportFlow();
    }

    /**
     * 查询 Export-Flow 运行时。
     *
     * @return Pandoc/导出 worker 运行时摘要
     */
    @GetMapping("/export-flow/runtime")
    public Map<String, Object> exportFlowRuntime() {
        return service.exportFlowRuntime();
    }

    /**
     * 查询 File-Flow 能力描述。
     *
     * @return 原文件、题图、OCR 产物和导出文件存储协议说明
     */
    @GetMapping("/file-flow")
    public Map<String, Object> fileFlow() {
        return service.fileFlow();
    }

    /**
     * 查询 File-Flow 运行时。
     *
     * @return 当前存储类型、本地根目录、MinIO 配置摘要和业务文件类型
     */
    @GetMapping("/file-flow/runtime")
    public Map<String, Object> fileFlowRuntime() {
        return service.fileFlowRuntime();
    }

    /**
     * 查询 Callback-Flow 能力描述。
     *
     * @return 平台回调、签名、幂等、重试和死信能力说明
     */
    @GetMapping("/callback-flow")
    public Map<String, Object> callbackFlow() {
        return service.callbackFlow();
    }

    /**
     * 查询 SDK/OpenAPI 能力描述。
     *
     * @return OpenAPI、Knife4j 和 SDK 生成边界说明
     */
    @GetMapping("/sdk-openapi")
    public Map<String, Object> sdkOpenapi() {
        return service.sdkOpenapi();
    }
}
