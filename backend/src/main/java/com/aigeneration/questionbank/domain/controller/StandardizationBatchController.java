package com.aigeneration.questionbank.domain.controller;

import com.aigeneration.questionbank.domain.service.StandardizationBatchService;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/import-tasks/{taskId}/standardization-jobs")
public class StandardizationBatchController {
    private final StandardizationBatchService service;
    public StandardizationBatchController(StandardizationBatchService service) { this.service = service; }

    @PostMapping public Map<String, Object> create(@PathVariable String taskId) { return service.create(taskId); }
    @GetMapping("/{jobId}") public Map<String, Object> get(@PathVariable String taskId, @PathVariable String jobId) { return service.get(taskId, jobId); }
    @PostMapping("/{jobId}/cancel") public Map<String, Object> cancel(@PathVariable String taskId, @PathVariable String jobId) { return service.cancel(taskId, jobId); }
    @PostMapping("/{jobId}/resume") public Map<String, Object> resume(@PathVariable String taskId, @PathVariable String jobId) { return service.resume(taskId, jobId); }
    @PostMapping("/{jobId}/retry-failed") public Map<String, Object> retryFailed(@PathVariable String taskId, @PathVariable String jobId) { return service.retryFailed(taskId, jobId); }
}
