package com.aigeneration.questionbank.ocrflow.port;

import com.aigeneration.questionbank.ocrflow.contract.WorkerModels;

/** AI standardization boundary. */
public interface StandardizationWorkerPort {
    WorkerModels.StandardizationResponse standardize(WorkerModels.StandardizationRequest request);
}
