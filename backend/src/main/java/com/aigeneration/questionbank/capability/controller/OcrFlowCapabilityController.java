package com.aigeneration.questionbank.capability.controller;

import com.aigeneration.questionbank.capability.service.OcrFlowCapabilityService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * OCR-Flow 能力目录控制器。
 *
 * <p>该控制器只暴露 OCR provider 的能力描述和运行时诊断信息。试卷加工任务仍应通过
 * question-processing 能力创建，由 Java 后端在内部编排 OCR worker。</p>
 */
@Tag(name = "OCR-Flow 能力", description = "OCR provider 能力描述、替换边界和运行时诊断入口")
@RestController
@RequestMapping("/api/capabilities/ocr-flow")
public class OcrFlowCapabilityController {
    /**
     * OCR-Flow 能力服务，负责生成能力描述和 runtime 信息。
     */
    private final OcrFlowCapabilityService service;

    /**
     * 注入 OCR-Flow 能力服务。
     *
     * @param service OCR-Flow 能力服务
     */
    public OcrFlowCapabilityController(OcrFlowCapabilityService service) {
        this.service = service;
    }

    /**
     * 查询 OCR-Flow 能力描述。
     *
     * @return provider 合约、配置键、Java API、worker API 和替换 provider 时需要保持的输出结构
     */
    @Operation(
            summary = "查询 OCR-Flow 能力描述",
            description = "返回默认 OCR provider、provider 合约、Java/worker 端点和 provider 替换策略。平台集成通常不直接调用 worker，而是通过 question-processing 创建加工任务。"
    )
    @GetMapping
    public Map<String, Object> descriptor() {
        return service.descriptor();
    }

    /**
     * 查询 OCR-Flow 运行时状态。
     *
     * @return Python worker 和当前 OCR provider 的可达性、可用性、文件后缀和超时等运行时信息
     */
    @Operation(
            summary = "查询 OCR-Flow 运行时状态",
            description = "透传并补充 Python worker 的 /worker/ocr-flow 运行时摘要，用于健康检查、运维诊断和 OCR provider 配置确认。"
    )
    @GetMapping("/runtime")
    public Map<String, Object> runtime() {
        return service.runtime();
    }
}
