package com.aigeneration.questionbank.engine.model;

import java.util.List;
import java.util.Map;

/**
 * question-engine 目录模型集合。
 *
 * <p>该类作为 engine catalog 的 record 命名空间，承载模块清单、平台要求、
 * 交付边界和接口清单等平台集成契约。</p>
 */
public final class EngineModels {
    /**
     * 禁止实例化模型命名空间类。
     */
    private EngineModels() {
    }

    /**
     * question-engine 总目录。
     *
     * @param code engine 编码
     * @param name engine 名称
     * @param boundary engine 能力边界
     * @param modules 四个核心模块
     * @param supplementalCapabilities 补充能力目录
     * @param platformRequirements 平台集成要求
     * @param deliveryBoundary 交付边界
     */
    public record EngineCatalog(
            String code,
            String name,
            String boundary,
            List<EngineModuleDescriptor> modules,
            List<Map<String, Object>> supplementalCapabilities,
            List<PlatformRequirement> platformRequirements,
            DeliveryBoundary deliveryBoundary
    ) {
    }

    /**
     * engine 模块描述。
     *
     * @param code 模块编码
     * @param name 模块名称
     * @param responsibility 模块职责
     * @param stateOwner 状态归属说明
     * @param exposedCapabilities 暴露能力
     * @param javaApis Java API 清单
     * @param pythonWorkers 依赖 Python worker
     * @param dependsOn 模块依赖
     * @param platformMustProvide 平台必须提供项
     * @param extensionPoints 扩展点
     * @param dataContracts 数据契约
     */
    public record EngineModuleDescriptor(
            String code,
            String name,
            String responsibility,
            String stateOwner,
            List<String> exposedCapabilities,
            List<String> javaApis,
            List<String> pythonWorkers,
            List<String> dependsOn,
            List<String> platformMustProvide,
            List<String> extensionPoints,
            List<String> dataContracts
    ) {
    }

    /**
     * 平台集成要求。
     *
     * @param area 要求领域
     * @param required 必需能力
     * @param optional 可选说明
     * @param configKeys 相关配置键
     */
    public record PlatformRequirement(
            String area,
            String required,
            String optional,
            List<String> configKeys
    ) {
    }

    /**
     * question-engine 对平台暴露的单个 Java API 清单项。
     *
     * @param groupCode API 所属模块或补充能力编码
     * @param groupName API 所属模块或补充能力名称
     * @param method HTTP 方法；目录中未声明方法的能力端点使用 ANY 表示需查看具体能力说明
     * @param path HTTP 路径模板
     * @param description API 所属能力边界说明
     * @param audience 推荐调用方，当前主要面向平台后端、平台前端和 SDK 生成流程
     * @param source 清单来源，用于区分 engine 目录、核心模块和补充能力目录
     */
    public record EngineInterfaceDescriptor(
            String groupCode,
            String groupName,
            String method,
            String path,
            String description,
            String audience,
            String source
    ) {
    }

    /**
     * question-engine 交付边界。
     *
     * @param includePaths 交付包含路径
     * @param excludePaths 交付排除路径
     * @param javaOwned Java 侧归属能力
     * @param pythonSupplemental Python 补充能力
     * @param localPlatformOnly 仅本地小平台保留项
     */
    public record DeliveryBoundary(
            List<String> includePaths,
            List<String> excludePaths,
            List<String> javaOwned,
            List<String> pythonSupplemental,
            List<String> localPlatformOnly
    ) {
    }
}
