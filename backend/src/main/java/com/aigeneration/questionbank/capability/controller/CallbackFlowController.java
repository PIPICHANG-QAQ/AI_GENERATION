package com.aigeneration.questionbank.capability.controller;

import com.aigeneration.questionbank.domain.service.CallbackFlowService;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * callback-flow 能力控制器。
 *
 * <p>该控制器提供平台回调事件的运行时摘要、测试发送、事件列表和重试入口。
 * 回调事件用于把导入、AI、导出等长任务结果通知给外部平台。</p>
 */
@RestController
@RequestMapping("/api/capabilities/callback-flow")
public class CallbackFlowController {
    /** callback-flow 编排服务，负责事件持久化、签名、发送和重试。 */
    private final CallbackFlowService service;

    /**
     * 创建 callback-flow 控制器。
     *
     * @param service 回调事件服务
     */
    public CallbackFlowController(CallbackFlowService service) {
        this.service = service;
    }

    /**
     * 查询 callback-flow 当前运行时。
     *
     * @return 回调配置、MQ 开关、本地事件表和重试能力摘要
     */
    @GetMapping("/runtime")
    public Map<String, Object> runtime() {
        return service.runtime();
    }

    /**
     * 创建并立即发送一条测试回调事件。
     *
     * @param payload 回调 URL、事件类型、聚合对象、幂等键、签名密钥和业务 payload
     * @return 回调事件记录和发送结果
     */
    @PostMapping("/test")
    public Map<String, Object> test(@RequestBody Map<String, Object> payload) {
        return service.send(payload);
    }

    /**
     * 查询回调事件列表。
     *
     * @param status 可选事件状态过滤，空字符串表示不过滤
     * @return 事件列表和总数
     */
    @GetMapping("/events")
    public Map<String, Object> events(@RequestParam(defaultValue = "") String status) {
        return service.list(status);
    }

    /**
     * 手动重试指定回调事件。
     *
     * @param eventId 回调事件 ID
     * @param payload 可选重试参数，例如 secret
     * @return 重试后的事件状态
     */
    @PostMapping("/events/{eventId}/retry")
    public Map<String, Object> retry(@PathVariable String eventId, @RequestBody Map<String, Object> payload) {
        return service.retry(eventId, payload);
    }

    /**
     * 扫描并重试所有到期失败事件。
     *
     * @param payload 可选重试参数；为空时使用默认参数
     * @return 本次扫描、成功、失败和进入 dead_letter 的数量摘要
     */
    @PostMapping("/events/retry-due")
    public Map<String, Object> retryDue(@RequestBody(required = false) Map<String, Object> payload) {
        return service.retryDue(payload == null ? Map.of() : payload);
    }
}
