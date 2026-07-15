package com.aigeneration.questionbank.ocrflow.port;

import com.aigeneration.questionbank.ocrflow.contract.WorkerModels;

/** Source/export rendering boundary. */
public interface SourceRenderWorkerPort {
    WorkerModels.BinaryResponse render(WorkerModels.SourceRenderRequest request);
}
