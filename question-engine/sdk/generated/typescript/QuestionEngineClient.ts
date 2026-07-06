// Generated from ../../openapi/question-engine.v1.yaml. Do not edit by hand.

import type {
  AiAnalysisInput,
  AiAnalysisResult,
  AiStandardizeInput,
  AiStandardizeResult,
  CallbackEvent,
  CallbackEventList,
  CapabilitySummary,
  CreateProcessingJobInput,
  DeliveryBoundary,
  EngineCatalog,
  EngineInterfaceDescriptor,
  ProcessingJob,
  QuestionImageLibrary,
  QuestionImageMutationResult,
  QuestionPackage,
  QuestionProcessingDescriptor,
  SelectQuestionImagesInput,
} from "./models";

export type QuestionEngineClientOptions = {
  baseUrl: string;
  headers?: Record<string, string>;
};

export class QuestionEngineClient {
  private readonly baseUrl: string;
  private readonly headers: Record<string, string>;

  constructor(options: QuestionEngineClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, "");
    this.headers = options.headers ?? {};
  }

  listCapabilities(): Promise<CapabilitySummary[]> {
    return this.getJson("/api/capabilities");
  }

  getEngineCatalog(): Promise<EngineCatalog> {
    return this.getJson("/api/engine");
  }

  getEngineInterfaces(): Promise<EngineInterfaceDescriptor[]> {
    return this.getJson("/api/engine/interfaces");
  }

  getDeliveryBoundary(): Promise<DeliveryBoundary> {
    return this.getJson("/api/engine/delivery-boundary");
  }

  getQuestionProcessingCapability(): Promise<QuestionProcessingDescriptor> {
    return this.getJson("/api/capabilities/question-processing");
  }

  listProcessingJobs(): Promise<ProcessingJob[]> {
    return this.getJson("/api/capabilities/question-processing/jobs");
  }

  getProcessingJob(jobId: string): Promise<ProcessingJob> {
    return this.getJson(`/api/capabilities/question-processing/jobs/${encodeURIComponent(jobId)}`);
  }

  getQuestionPackage(jobId: string): Promise<QuestionPackage> {
    return this.getJson(`/api/capabilities/question-processing/jobs/${encodeURIComponent(jobId)}/question-package`);
  }

  getImportTaskImageLibrary(jobId: string): Promise<QuestionImageLibrary> {
    return this.getJson(`/api/import-tasks/${encodeURIComponent(jobId)}/image-library`);
  }

  selectImportQuestionImages(
    jobId: string,
    questionId: string,
    input: SelectQuestionImagesInput,
  ): Promise<QuestionImageMutationResult> {
    return this.requestJson(
      `/api/import-tasks/${encodeURIComponent(jobId)}/questions/${encodeURIComponent(questionId)}/images/select`,
      {
        method: "POST",
        body: JSON.stringify(input),
        headers: { "Content-Type": "application/json" },
      },
    );
  }

  uploadImportQuestionImages(
    jobId: string,
    questionId: string,
    files: Array<File | Blob>,
  ): Promise<QuestionImageMutationResult> {
    const form = new FormData();
    for (const file of files) {
      form.append("files", file);
    }
    return this.requestJson(
      `/api/import-tasks/${encodeURIComponent(jobId)}/questions/${encodeURIComponent(questionId)}/images`,
      {
        method: "POST",
        body: form,
      },
    );
  }

  standardizeImportQuestion(
    jobId: string,
    questionId: string,
    input: AiStandardizeInput,
  ): Promise<AiStandardizeResult> {
    return this.requestJson(
      `/api/import-tasks/${encodeURIComponent(jobId)}/questions/${encodeURIComponent(questionId)}/standardize/ai`,
      {
        method: "POST",
        body: JSON.stringify(input),
        headers: { "Content-Type": "application/json" },
      },
    );
  }

  analyzeImportQuestion(
    jobId: string,
    questionId: string,
    input: AiAnalysisInput,
  ): Promise<AiAnalysisResult> {
    return this.requestJson(
      `/api/import-tasks/${encodeURIComponent(jobId)}/questions/${encodeURIComponent(questionId)}/analysis`,
      {
        method: "POST",
        body: JSON.stringify(input),
        headers: { "Content-Type": "application/json" },
      },
    );
  }

  getBankQuestionImageLibrary(questionId: string): Promise<QuestionImageLibrary> {
    return this.getJson(`/api/question-bank/questions/${encodeURIComponent(questionId)}/image-library`);
  }

  uploadBankQuestionImages(
    questionId: string,
    files: Array<File | Blob>,
  ): Promise<QuestionImageMutationResult> {
    const form = new FormData();
    for (const file of files) {
      form.append("files", file);
    }
    return this.requestJson(`/api/question-bank/questions/${encodeURIComponent(questionId)}/images`, {
      method: "POST",
      body: form,
    });
  }

  standardizeBankQuestion(questionId: string, input: AiStandardizeInput): Promise<AiStandardizeResult> {
    return this.requestJson(`/api/question-bank/questions/${encodeURIComponent(questionId)}/standardize/ai`, {
      method: "POST",
      body: JSON.stringify(input),
      headers: { "Content-Type": "application/json" },
    });
  }

  analyzeBankQuestion(questionId: string, input: AiAnalysisInput): Promise<AiAnalysisResult> {
    return this.requestJson(`/api/question-bank/questions/${encodeURIComponent(questionId)}/analysis`, {
      method: "POST",
      body: JSON.stringify(input),
      headers: { "Content-Type": "application/json" },
    });
  }

  async createProcessingJob(input: CreateProcessingJobInput): Promise<ProcessingJob> {
    const form = new FormData();
    form.append("paperFile", input.paperFile);
    if (input.answerFile) form.append("answerFile", input.answerFile);
    for (const key of ["stage", "subject", "grade", "region", "year", "title"] as const) {
      if (input[key]) form.append(key, input[key] ?? "");
    }
    return this.requestJson("/api/capabilities/question-processing/jobs", {
      method: "POST",
      body: form,
    });
  }

  getOcrFlowRuntime(): Promise<Record<string, unknown>> {
    return this.getJson("/api/capabilities/ocr-flow/runtime");
  }

  getAiFlowRuntime(): Promise<Record<string, unknown>> {
    return this.getJson("/api/capabilities/ai-flow/runtime");
  }

  getExportFlowRuntime(): Promise<Record<string, unknown>> {
    return this.getJson("/api/capabilities/export-flow/runtime");
  }

  getFileFlowRuntime(): Promise<Record<string, unknown>> {
    return this.getJson("/api/capabilities/file-flow/runtime");
  }

  getCallbackFlowRuntime(): Promise<Record<string, unknown>> {
    return this.getJson("/api/capabilities/callback-flow/runtime");
  }

  listCallbackEvents(status?: string): Promise<CallbackEventList> {
    const query = status ? `?status=${encodeURIComponent(status)}` : "";
    return this.getJson(`/api/capabilities/callback-flow/events${query}`);
  }

  retryCallbackEvent(eventId: string, secret?: string): Promise<CallbackEvent> {
    return this.requestJson(`/api/capabilities/callback-flow/events/${encodeURIComponent(eventId)}/retry`, {
      method: "POST",
      body: JSON.stringify({ secret }),
      headers: { "Content-Type": "application/json" },
    });
  }

  retryDueCallbackEvents(secret?: string): Promise<Record<string, unknown>> {
    return this.requestJson("/api/capabilities/callback-flow/events/retry-due", {
      method: "POST",
      body: JSON.stringify({ secret }),
      headers: { "Content-Type": "application/json" },
    });
  }

  private getJson<T>(path: string): Promise<T> {
    return this.requestJson(path, { method: "GET" });
  }

  private async requestJson<T>(path: string, init: RequestInit): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        ...this.headers,
        ...((init.headers as Record<string, string> | undefined) ?? {}),
      },
    });
    const text = await response.text();
    const body = text ? JSON.parse(text) : null;
    if (!response.ok) {
      throw new Error(body?.detail || body?.error || text || `HTTP ${response.status}`);
    }
    return body as T;
  }
}
