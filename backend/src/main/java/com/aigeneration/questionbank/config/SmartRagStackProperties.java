package com.aigeneration.questionbank.config;

import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * SmartRAG 技术栈版本对齐配置。
 *
 * <p>用于把参考工程的公开依赖版本暴露给系统诊断接口。该配置只记录版本映射，
 * 不引入 SmartRAG 的私有父 POM 或内部模块依赖。</p>
 */
@ConfigurationProperties(prefix = "smart-rag-stack")
public class SmartRagStackProperties {

    /** 公开依赖名称到版本号的有序映射，顺序按配置文件声明保留。 */
    private final Map<String, String> versions = new LinkedHashMap<>();

    /**
     * 获取 SmartRAG 公开依赖版本映射。
     *
     * @return 可变版本映射，由 Spring Boot 配置绑定填充
     */
    public Map<String, String> getVersions() {
        return versions;
    }
}
