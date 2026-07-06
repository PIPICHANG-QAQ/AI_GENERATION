package com.aigeneration.questionbank.config;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

/**
 * Python worker 调用和代理配置。
 *
 * <p>Java 是主业务后端，Python 只作为 OCR、AI、公式和导出等必要 worker。
 * 这些属性控制 Java 是否调用 worker、是否代理旧 API、worker base URL、健康检查路径和请求超时。</p>
 */
@Validated
@ConfigurationProperties(prefix = "python-worker")
public class PythonWorkerProperties {

    /** 是否允许 Java 调用 Python worker。关闭时相关运行时接口会返回不可用或 disabled。 */
    private boolean enabled = true;

    /** 是否允许 Java 通过 proxy filter 转发尚未迁移到 Java 的旧 /api/* 请求。 */
    private boolean apiProxyEnabled = true;

    /** Python worker 基础地址。 */
    @NotBlank
    private String baseUrl = "http://127.0.0.1:8000";

    /** Python worker 健康检查路径。 */
    @NotBlank
    private String healthPath = "/api/health";

    /** Java 连接 Python worker 的连接超时，单位毫秒。 */
    @Min(100)
    private int connectTimeoutMs = 2000;

    /** Java 读取 Python worker 响应的超时，单位毫秒。 */
    @Min(100)
    private int readTimeoutMs = 5000;

    /**
     * 判断 Python worker 是否启用。
     *
     * @return true 表示 Java 可以调用 worker
     */
    public boolean isEnabled() {
        return enabled;
    }

    /**
     * 设置 Python worker 是否启用。
     *
     * @param enabled true 表示启用 worker 调用
     */
    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    /**
     * 判断旧 API 代理是否启用。
     *
     * @return true 表示未迁移的 /api/* 请求可被代理到 Python worker
     */
    public boolean isApiProxyEnabled() {
        return apiProxyEnabled;
    }

    /**
     * 设置旧 API 代理开关。
     *
     * @param apiProxyEnabled true 表示启用代理
     */
    public void setApiProxyEnabled(boolean apiProxyEnabled) {
        this.apiProxyEnabled = apiProxyEnabled;
    }

    /**
     * 获取 Python worker 基础地址。
     *
     * @return worker base URL
     */
    public String getBaseUrl() {
        return baseUrl;
    }

    /**
     * 设置 Python worker 基础地址。
     *
     * @param baseUrl worker base URL
     */
    public void setBaseUrl(String baseUrl) {
        this.baseUrl = baseUrl;
    }

    /**
     * 获取 Python worker 健康检查路径。
     *
     * @return health path
     */
    public String getHealthPath() {
        return healthPath;
    }

    /**
     * 设置 Python worker 健康检查路径。
     *
     * @param healthPath health path
     */
    public void setHealthPath(String healthPath) {
        this.healthPath = healthPath;
    }

    /**
     * 获取连接超时。
     *
     * @return 连接超时毫秒数
     */
    public int getConnectTimeoutMs() {
        return connectTimeoutMs;
    }

    /**
     * 设置连接超时。
     *
     * @param connectTimeoutMs 连接超时毫秒数
     */
    public void setConnectTimeoutMs(int connectTimeoutMs) {
        this.connectTimeoutMs = connectTimeoutMs;
    }

    /**
     * 获取读取超时。
     *
     * @return 读取超时毫秒数
     */
    public int getReadTimeoutMs() {
        return readTimeoutMs;
    }

    /**
     * 设置读取超时。
     *
     * @param readTimeoutMs 读取超时毫秒数
     */
    public void setReadTimeoutMs(int readTimeoutMs) {
        this.readTimeoutMs = readTimeoutMs;
    }
}
