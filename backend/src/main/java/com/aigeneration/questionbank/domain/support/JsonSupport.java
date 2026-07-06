package com.aigeneration.questionbank.domain.support;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Component;

/**
 * 领域层 JSON 读写辅助组件。
 *
 * <p>Java 表中部分字段以 JSON 字符串保存列表、Map 或 worker 原始响应。该组件集中处理这些
 * 字符串和 Java 集合之间的转换，并在读取失败时返回空集合，避免旧数据或 worker 兼容字段导致接口失败。</p>
 */
@Component
public class JsonSupport {
    /** Jackson 反序列化 List<Object> 的类型引用。 */
    private static final TypeReference<List<Object>> LIST_TYPE = new TypeReference<>() {};
    /** Jackson 反序列化 Map<String, Object> 的类型引用。 */
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    /** Spring 注入的共享 ObjectMapper。 */
    private final ObjectMapper objectMapper;

    /**
     * 创建 JSON 辅助组件。
     *
     * @param objectMapper Jackson 对象映射器
     */
    public JsonSupport(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    /**
     * 把对象序列化为 JSON 字符串。
     *
     * <p>传入 null 时写成空数组，匹配题目列表、题图列表等 JSON 字段的默认语义。</p>
     *
     * @param value 待序列化对象
     * @return JSON 字符串
     */
    public String write(Object value) {
        try {
            return objectMapper.writeValueAsString(value == null ? List.of() : value);
        } catch (JsonProcessingException ex) {
            throw new IllegalArgumentException("JSON serialization failed", ex);
        }
    }

    /**
     * 从 JSON 字符串读取对象列表。
     *
     * @param json JSON 字符串
     * @return 读取成功时返回列表，空字符串或解析失败时返回空列表
     */
    public List<Object> readList(String json) {
        if (json == null || json.isBlank()) {
            return new ArrayList<>();
        }
        try {
            return objectMapper.readValue(json, LIST_TYPE);
        } catch (JsonProcessingException ex) {
            return new ArrayList<>();
        }
    }

    /**
     * 从 JSON 字符串读取对象 Map。
     *
     * @param json JSON 字符串
     * @return 读取成功时返回 Map，空字符串或解析失败时返回空 Map
     */
    public Map<String, Object> readMap(String json) {
        if (json == null || json.isBlank()) {
            return new LinkedHashMap<>();
        }
        try {
            return objectMapper.readValue(json, MAP_TYPE);
        } catch (JsonProcessingException ex) {
            return new LinkedHashMap<>();
        }
    }

    /**
     * 将任意对象安全转换为字符串列表。
     *
     * @param value 期望为 List 的输入对象
     * @return 去掉 null 和空白项后的字符串列表
     */
    @SuppressWarnings("unchecked")
    public List<String> stringList(Object value) {
        if (!(value instanceof List<?> list)) {
            return new ArrayList<>();
        }
        List<String> result = new ArrayList<>();
        for (Object item : list) {
            if (item != null && !String.valueOf(item).isBlank()) {
                result.add(String.valueOf(item));
            }
        }
        return result;
    }

    /**
     * 将任意对象安全转换为字符串到 double 的 Map。
     *
     * <p>非数字值会尝试用字符串解析；解析失败时按 0 处理，用于分值配置等弱类型输入。</p>
     *
     * @param value 期望为 Map 的输入对象
     * @return 以字符串 key 和 double value 表示的 Map
     */
    @SuppressWarnings("unchecked")
    public Map<String, Double> doubleMap(Object value) {
        Map<String, Double> result = new LinkedHashMap<>();
        if (!(value instanceof Map<?, ?> map)) {
            return result;
        }
        for (Map.Entry<?, ?> entry : map.entrySet()) {
            Object rawValue = entry.getValue();
            double numeric = 0;
            if (rawValue instanceof Number number) {
                numeric = number.doubleValue();
            } else if (rawValue != null) {
                try {
                    numeric = Double.parseDouble(String.valueOf(rawValue));
                } catch (NumberFormatException ignored) {
                    numeric = 0;
                }
            }
            result.put(String.valueOf(entry.getKey()), numeric);
        }
        return result;
    }
}
