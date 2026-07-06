export type QuestionEngineClientOptions = {
  baseUrl: string;
  headers?: Record<string, string>;
};

export type ProcessingJobInput = {
  paperFile: File | Blob;
  answerFile?: File | Blob;
  stage?: string;
  subject?: string;
  grade?: string;
  region?: string;
  year?: string;
  title?: string;
};

export class QuestionEngineClient {
  private readonly baseUrl: string;
  private readonly headers: Record<string, string>;

  constructor(options: QuestionEngineClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, "");
    this.headers = options.headers ?? {};
  }

  capabilities() {
    return this.getJson("/api/capabilities");
  }

  engine() {
    return this.getJson("/api/engine");
  }

  processingJob(jobId: string) {
    return this.getJson(`/api/capabilities/question-processing/jobs/${encodeURIComponent(jobId)}`);
  }

  questionPackage(jobId: string) {
    return this.getJson(`/api/capabilities/question-processing/jobs/${encodeURIComponent(jobId)}/question-package`);
  }

  async createProcessingJob(input: ProcessingJobInput) {
    const form = new FormData();
    form.append("paperFile", input.paperFile);
    if (input.answerFile) form.append("answerFile", input.answerFile);
    for (const key of ["stage", "subject", "grade", "region", "year", "title"] as const) {
      if (input[key]) form.append(key, input[key] ?? "");
    }
    const response = await fetch(`${this.baseUrl}/api/capabilities/question-processing/jobs`, {
      method: "POST",
      headers: this.headers,
      body: form,
    });
    return this.parse(response);
  }

  private async getJson(path: string) {
    const response = await fetch(`${this.baseUrl}${path}`, {
      headers: { ...this.headers },
    });
    return this.parse(response);
  }

  private async parse(response: Response) {
    const text = await response.text();
    const body = text ? JSON.parse(text) : null;
    if (!response.ok) {
      throw new Error(body?.detail || body?.error || text || `HTTP ${response.status}`);
    }
    return body;
  }
}
