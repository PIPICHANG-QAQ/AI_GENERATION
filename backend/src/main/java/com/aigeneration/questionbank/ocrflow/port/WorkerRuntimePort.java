package com.aigeneration.questionbank.ocrflow.port;

import com.aigeneration.questionbank.ocrflow.contract.WorkerModels;

/** Worker runtime metadata boundary. */
public interface WorkerRuntimePort {
    WorkerModels.WorkerCapabilities capabilities();
}
