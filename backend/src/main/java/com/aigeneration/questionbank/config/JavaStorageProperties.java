package com.aigeneration.questionbank.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Java 文件存储配置。
 *
 * <p>本地开发默认把导入原文件、题图和导出文件写入 backend/storage 下的本地目录；
 * 企业部署启用对象存储时，该配置仍作为本地 fallback 或临时文件根目录使用。</p>
 */
@ConfigurationProperties(prefix = "java-storage")
public class JavaStorageProperties {
    /** 本地文件存储根目录，相对路径会按后端进程工作目录解析。 */
    private String localRoot = "storage/java_files";

    /**
     * 获取本地文件存储根目录。
     *
     * @return 本地存储根目录
     */
    public String getLocalRoot() {
        return localRoot;
    }

    /**
     * 设置本地文件存储根目录。
     *
     * @param localRoot 本地存储根目录
     */
    public void setLocalRoot(String localRoot) {
        this.localRoot = localRoot;
    }
}
