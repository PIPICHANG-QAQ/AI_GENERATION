package com.aigeneration.questionbank.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 企业化基础设施配置。
 *
 * <p>这些开关用于描述 MySQL、Redis、MinIO 和 MQ 在当前部署中的启用状态。
 * 默认值偏向本地开发可启动：外部依赖即使未启动，也不会阻止 H2 + Python worker 的本地闭环。</p>
 */
@ConfigurationProperties(prefix = "enterprise")
public class EnterpriseProperties {
    /** MySQL 企业数据库开关。 */
    private final Feature mysql = new Feature();
    /** Redis 缓存和限流能力配置。 */
    private final Redis redis = new Redis();
    /** MinIO 或兼容对象存储配置。 */
    private final Minio minio = new Minio();
    /** MQ provider 配置，当前默认 RocketMQ。 */
    private final Mq mq = new Mq();

    /**
     * 获取 MySQL 开关配置。
     *
     * @return MySQL feature 配置
     */
    public Feature getMysql() { return mysql; }

    /**
     * 获取 Redis 连接配置。
     *
     * @return Redis 配置
     */
    public Redis getRedis() { return redis; }

    /**
     * 获取对象存储配置。
     *
     * @return MinIO 配置
     */
    public Minio getMinio() { return minio; }

    /**
     * 获取消息队列配置。
     *
     * @return MQ 配置
     */
    public Mq getMq() { return mq; }

    /**
     * 通用企业化特性开关。
     *
     * <p>子类复用 enabled 字段，表示该外部能力是否参与当前部署。</p>
     */
    public static class Feature {
        /** 是否启用当前企业化能力。 */
        private boolean enabled;

        /**
         * 判断当前能力是否启用。
         *
         * @return true 表示启用
         */
        public boolean isEnabled() { return enabled; }

        /**
         * 设置当前能力是否启用。
         *
         * @param enabled true 表示启用
         */
        public void setEnabled(boolean enabled) { this.enabled = enabled; }
    }

    /**
     * Redis 连接摘要配置。
     *
     * <p>当前只在诊断接口暴露配置值，实际 Redis 客户端是否使用由后续企业 profile 决定。</p>
     */
    public static class Redis extends Feature {
        /** Redis 主机地址。 */
        private String host = "127.0.0.1";
        /** Redis 端口。 */
        private int port = 6379;

        /**
         * 获取 Redis 主机地址。
         *
         * @return Redis host
         */
        public String getHost() { return host; }

        /**
         * 设置 Redis 主机地址。
         *
         * @param host Redis host
         */
        public void setHost(String host) { this.host = host; }

        /**
         * 获取 Redis 端口。
         *
         * @return Redis port
         */
        public int getPort() { return port; }

        /**
         * 设置 Redis 端口。
         *
         * @param port Redis port
         */
        public void setPort(int port) { this.port = port; }
    }

    /**
     * MinIO 或兼容对象存储配置。
     *
     * <p>启用后 Java 文件存储服务会优先使用对象存储保存原文件、题图和导出文件。</p>
     */
    public static class Minio extends Feature {
        /** MinIO endpoint，例如 http://127.0.0.1:9000。 */
        private String endpoint = "http://127.0.0.1:9000";
        /** 默认 bucket 名称。 */
        private String bucket = "ai-generation";
        /** 对象存储 access key。 */
        private String accessKey = "minioadmin";
        /** 对象存储 secret key。 */
        private String secretKey = "minioadmin";

        /**
         * 获取对象存储 endpoint。
         *
         * @return endpoint URL
         */
        public String getEndpoint() { return endpoint; }

        /**
         * 设置对象存储 endpoint。
         *
         * @param endpoint endpoint URL
         */
        public void setEndpoint(String endpoint) { this.endpoint = endpoint; }

        /**
         * 获取 bucket 名称。
         *
         * @return bucket 名称
         */
        public String getBucket() { return bucket; }

        /**
         * 设置 bucket 名称。
         *
         * @param bucket bucket 名称
         */
        public void setBucket(String bucket) { this.bucket = bucket; }

        /**
         * 获取 access key。
         *
         * @return access key
         */
        public String getAccessKey() { return accessKey; }

        /**
         * 设置 access key。
         *
         * @param accessKey access key
         */
        public void setAccessKey(String accessKey) { this.accessKey = accessKey; }

        /**
         * 获取 secret key。
         *
         * @return secret key
         */
        public String getSecretKey() { return secretKey; }

        /**
         * 设置 secret key。
         *
         * @param secretKey secret key
         */
        public void setSecretKey(String secretKey) { this.secretKey = secretKey; }
    }

    /**
     * 消息队列配置。
     *
     * <p>当前 Java 侧以配置契约和本地表 fallback 为主，后续可用该配置接入 RocketMQ 等真实 MQ。</p>
     */
    public static class Mq extends Feature {
        /** MQ provider 名称，默认 rocketmq。 */
        private String provider = "rocketmq";
        /** MQ nameserver 或 broker 地址。 */
        private String nameServer = "127.0.0.1:9876";

        /**
         * 获取 MQ provider。
         *
         * @return provider 名称
         */
        public String getProvider() { return provider; }

        /**
         * 设置 MQ provider。
         *
         * @param provider provider 名称
         */
        public void setProvider(String provider) { this.provider = provider; }

        /**
         * 获取 MQ nameserver。
         *
         * @return nameserver 地址
         */
        public String getNameServer() { return nameServer; }

        /**
         * 设置 MQ nameserver。
         *
         * @param nameServer nameserver 地址
         */
        public void setNameServer(String nameServer) { this.nameServer = nameServer; }
    }
}
