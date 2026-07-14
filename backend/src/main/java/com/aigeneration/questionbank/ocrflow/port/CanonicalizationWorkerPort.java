package com.aigeneration.questionbank.ocrflow.port;

import com.aigeneration.questionbank.ocrflow.contract.WorkerModels;

/** Import task canonicalization preview boundary. */
public interface CanonicalizationWorkerPort {
    WorkerModels.CanonicalizationResponse preview(WorkerModels.CanonicalizationRequest request);
}
