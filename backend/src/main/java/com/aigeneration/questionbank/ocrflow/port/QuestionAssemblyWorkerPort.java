package com.aigeneration.questionbank.ocrflow.port;

import com.aigeneration.questionbank.ocrflow.contract.WorkerModels;

/** Reserved question assembly boundary; not wired into the production call chain yet. */
public interface QuestionAssemblyWorkerPort {
    WorkerModels.QuestionAssemblyResponse assemble(WorkerModels.QuestionAssemblyRequest request);
}
