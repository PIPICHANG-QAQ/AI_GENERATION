package com.aigeneration.questionbank.domain.support;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.UUID;

/**
 * 业务 ID 生成工具。
 *
 * <p>生成格式为 {@code prefix_yyyyMMdd_HHmmss_random8}，便于本地调试时通过 ID 直接观察创建时间，
 * 同时用 UUID 片段降低同秒并发冲突概率。</p>
 */
public final class Ids {
    /** ID 中时间片段的格式化器。 */
    private static final DateTimeFormatter FORMATTER = DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss");

    /**
     * 禁止实例化工具类。
     */
    private Ids() {
    }

    /**
     * 生成带业务前缀的新 ID。
     *
     * @param prefix 业务前缀，例如 import_task、ai_job、file
     * @return 新业务 ID
     */
    public static String next(String prefix) {
        return prefix + "_" + LocalDateTime.now().format(FORMATTER) + "_" + UUID.randomUUID().toString().replace("-", "").substring(0, 8);
    }
}
