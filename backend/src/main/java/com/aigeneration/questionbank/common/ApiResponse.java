package com.aigeneration.questionbank.common;

import java.time.Instant;

/**
 * 统一 HTTP 响应包装。
 *
 * <p>所有 Java 主后端系统类接口都通过该 record 返回成功标识、业务数据、错误信息、
 * traceId 和响应时间，方便前端、SDK 和日志系统使用同一套响应约定。</p>
 *
 * @param success 请求是否被业务层视为成功
 * @param data 成功时返回的业务数据
 * @param message 失败或提示信息，成功时通常为空
 * @param traceId 当前请求的链路 ID
 * @param timestamp 服务端生成响应的时间
 * @param <T> 业务数据类型
 */
public record ApiResponse<T>(
        boolean success,
        T data,
        String message,
        String traceId,
        Instant timestamp
) {
    /**
     * 创建成功响应。
     *
     * @param data 业务数据
     * @param traceId 当前请求 traceId
     * @return success=true 的统一响应
     * @param <T> 业务数据类型
     */
    public static <T> ApiResponse<T> ok(T data, String traceId) {
        return new ApiResponse<>(true, data, null, traceId, Instant.now());
    }

    /**
     * 创建失败响应。
     *
     * @param message 失败原因或提示信息
     * @param traceId 当前请求 traceId
     * @return success=false 的统一响应
     * @param <T> 业务数据类型
     */
    public static <T> ApiResponse<T> failed(String message, String traceId) {
        return new ApiResponse<>(false, null, message, traceId, Instant.now());
    }
}
