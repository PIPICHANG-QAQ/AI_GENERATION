package com.aigeneration.questionbank.domain.controller;

import com.aigeneration.questionbank.domain.service.ImportTaskCanonicalizationService;
import java.util.Map;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** HTTP endpoints for import-task canonicalization preview, apply, and rollback. */
@RestController
@RequestMapping("/api/import-tasks/{taskId}/canonicalization")
public class ImportTaskCanonicalizationController {
    private final ImportTaskCanonicalizationService service;

    public ImportTaskCanonicalizationController(ImportTaskCanonicalizationService service) {
        this.service = service;
    }

    @PostMapping("/preview")
    public Map<String, Object> preview(@PathVariable String taskId) {
        return service.preview(taskId);
    }

    @PostMapping("/apply")
    public Map<String, Object> apply(
            @PathVariable String taskId,
            @RequestBody Map<String, Object> payload
    ) {
        return service.apply(taskId, payload);
    }

    @PostMapping("/rollback")
    public Map<String, Object> rollback(@PathVariable String taskId) {
        return service.rollbackLatest(taskId);
    }
}
