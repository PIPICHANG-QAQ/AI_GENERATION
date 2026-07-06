package com.aigeneration.questionbank.engine.controller;

import com.aigeneration.questionbank.engine.model.EngineModels.DeliveryBoundary;
import com.aigeneration.questionbank.engine.model.EngineModels.EngineCatalog;
import com.aigeneration.questionbank.engine.model.EngineModels.EngineInterfaceDescriptor;
import com.aigeneration.questionbank.engine.model.EngineModels.EngineModuleDescriptor;
import com.aigeneration.questionbank.engine.model.EngineModels.PlatformRequirement;
import com.aigeneration.questionbank.engine.service.EngineCatalogService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * question-engine 能力目录控制器。
 *
 * <p>该控制器面向平台集成方暴露 engine 模块、接口清单、平台要求和交付边界；
 * 具体题目加工、题库、组卷和知识点接口由各领域控制器承载。</p>
 */
@Tag(name = "question-engine 目录", description = "question-engine 模块目录、接口清单、平台要求和交付边界")
@RestController
@RequestMapping("/api/engine")
public class EngineCatalogController {
    /**
     * Engine 目录服务，负责聚合模块、能力、平台要求和接口清单。
     */
    private final EngineCatalogService service;

    /**
     * 注入 Engine 目录服务。
     *
     * @param service Engine 目录服务
     */
    public EngineCatalogController(EngineCatalogService service) {
        this.service = service;
    }

    /**
     * 查询 question-engine 总目录。
     *
     * @return engine 基本信息、四个模块、补充能力、平台要求和交付边界
     */
    @Operation(summary = "查询 question-engine 总目录", description = "返回题目导入、题库、组卷、知识点四个模块，以及补充能力、平台要求和交付边界。")
    @GetMapping
    public EngineCatalog catalog() {
        return service.catalog();
    }

    /**
     * 查询 question-engine 模块清单。
     *
     * @return 题目导入、题库、组卷和知识点四个可二次开发模块
     */
    @Operation(summary = "查询 question-engine 模块清单", description = "返回 question-import、question-bank、paper-assembly 和 knowledge-base 模块描述。")
    @GetMapping("/modules")
    public List<EngineModuleDescriptor> modules() {
        return service.modules();
    }

    /**
     * 按模块编码查询模块描述。
     *
     * @param code 模块编码，例如 question-import、question-bank、paper-assembly 或 knowledge-base
     * @return 单个模块的能力、Java API、worker 依赖、平台输入和数据契约
     */
    @Operation(summary = "按编码查询 question-engine 模块", description = "按模块编码返回单个模块的职责、Java API、Python worker 依赖、扩展点和数据契约。")
    @GetMapping("/modules/{code}")
    public EngineModuleDescriptor module(@PathVariable String code) {
        return service.module(code);
    }

    /**
     * 查询 question-engine 对外补充能力。
     *
     * @return review-workbench、ai-flow、export-flow、file-flow、callback-flow 和 sdk-openapi 能力描述
     */
    @Operation(summary = "查询补充能力清单", description = "返回人工校验、AI、导出、文件、回调和 SDK/OpenAPI 等补充能力边界。")
    @GetMapping("/supplemental-capabilities")
    public List<Map<String, Object>> supplementalCapabilities() {
        return service.supplementalCapabilities();
    }

    /**
     * 查询平台集成要求。
     *
     * @return 平台需提供的身份租户、数据库、对象存储、worker、大模型和可观测能力
     */
    @Operation(summary = "查询平台集成要求", description = "返回公司平台接入 question-engine 时需要提供或配置的上下文、存储、worker、LLM 和可观测能力。")
    @GetMapping("/platform-requirements")
    public List<PlatformRequirement> platformRequirements() {
        return service.platformRequirements();
    }

    /**
     * 查询 question-engine 交付边界。
     *
     * @return 交付包含路径、排除路径、Java 归属、Python 补充和本地小平台排除项
     */
    @Operation(summary = "查询交付边界", description = "返回 question-engine 交付应包含和排除的代码、文档、Python worker 和本地小平台范围。")
    @GetMapping("/delivery-boundary")
    public DeliveryBoundary deliveryBoundary() {
        return service.deliveryBoundary();
    }

    /**
     * 查询 question-engine 面向平台的 Java API 扁平清单。
     *
     * @return 按模块和补充能力展开后的 API 方法、路径、说明、调用方和来源
     */
    @Operation(summary = "查询 question-engine 接口清单", description = "返回 question-engine 面向平台集成的 Java API 扁平清单，可用于对接评审、SDK 覆盖检查和接口交付验收。")
    @GetMapping("/interfaces")
    public List<EngineInterfaceDescriptor> interfaces() {
        return service.interfaces();
    }
}
