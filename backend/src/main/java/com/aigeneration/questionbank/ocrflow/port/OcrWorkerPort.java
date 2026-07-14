package com.aigeneration.questionbank.ocrflow.port;

import com.aigeneration.questionbank.ocrflow.contract.WorkerModels;

/** OCR job boundary. Implementations may use HTTP, but callers do not depend on transport details. */
public interface OcrWorkerPort {
    WorkerModels.OcrJobAccepted create(WorkerModels.OcrCreateRequest request);
    WorkerModels.OcrJobSnapshot get(String jobId);
    WorkerModels.OcrResult getResult(String jobId);
    WorkerModels.OcrJobSnapshot retry(String jobId, WorkerModels.RetryRequest request);
}
