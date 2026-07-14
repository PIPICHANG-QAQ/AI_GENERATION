package com.aigeneration.questionbank.ocrflow.port;

import com.aigeneration.questionbank.ocrflow.contract.WorkerModels;

/** AI analysis boundary. */
public interface AnalysisWorkerPort {
    WorkerModels.AnalysisResponse analyze(WorkerModels.AnalysisRequest request);
}
