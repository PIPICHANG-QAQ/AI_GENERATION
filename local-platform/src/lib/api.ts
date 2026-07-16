const BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  import.meta.env.VITE_API_BASE ||
  (import.meta.env.DEV
    ? "http://localhost:8018"
    : window.location.origin);

export function apiUrl(endpoint: string): string {
  return `${BASE_URL}${endpoint}`;
}

async function fetcher(endpoint: string, options: RequestInit = {}) {
  const url = `${BASE_URL}${endpoint}`;
  const isFormData =
    typeof FormData !== "undefined" && options.body instanceof FormData;
  let response: Response;
  try {
    response = await fetch(url, {
      ...options,
      headers: {
        ...(isFormData ? {} : { "Content-Type": "application/json" }),
        ...options.headers,
      },
    });
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(
      `无法连接 API：${url}。请检查服务地址、Nginx 代理、CORS/HTTPS 配置和后端容器日志。${detail}`,
    );
  }
  if (!response.ok) {
    const raw = await response.text();
    let message = raw;
    if (raw) {
      try {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed.detail === "string") message = parsed.detail;
        else if (parsed && typeof parsed.message === "string") message = parsed.message;
        else if (parsed && typeof parsed.error === "string") message = parsed.error;
      } catch {
        // not JSON, keep raw text
      }
    }
    throw new Error(message || `请求失败（${response.status}）`);
  }
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

async function deleteSequentially(
  ids: string[],
  deleteOne: (id: string) => Promise<unknown>,
) {
  let deleted = 0;
  const errors: string[] = [];
  for (const id of ids) {
    try {
      await deleteOne(id);
      deleted += 1;
    } catch (error) {
      errors.push(error instanceof Error ? error.message : String(error));
    }
  }
  if (errors.length > 0) {
    throw new Error(errors[0] || "批量删除失败");
  }
  return { deleted, deletedCount: deleted };
}

function withTotal(result: any) {
  if (!result || !Array.isArray(result.items)) return result;
  return {
    ...result,
    total: Number.isFinite(result.total) ? result.total : result.items.length,
  };
}

function normalizePaperPayload(data: any) {
  const header = data?.header || {};
  return {
    ...data,
    subject: data?.subject ?? header.subject ?? "",
    grade: data?.grade ?? header.grade ?? "",
  };
}

function qs(params: Record<string, unknown> = {}) {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") sp.append(k, String(v));
  });
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export const api = {
  // System
  health: () => fetcher("/api/health"),
  systemMineru: () => fetcher("/api/system/mineru"),
  systemLlm: () => fetcher("/api/system/llm"),

  // Import tasks
  getImportTasks: () => fetcher("/api/import-tasks"),
  getImportTask: (id: string) => fetcher(`/api/import-tasks/${id}`),
  createImportTask: (formData: FormData) =>
    fetcher("/api/import-tasks", { method: "POST", body: formData }),
  renameImportTask: (id: string, title: string) =>
    fetcher(`/api/import-tasks/${id}`, {
      method: "PUT",
      body: JSON.stringify({ title }),
    }),
  deleteImportTask: (id: string) =>
    fetcher(`/api/import-tasks/${id}`, { method: "DELETE" }),
  deleteImportTasks: (ids: string[]) =>
    fetcher("/api/import-tasks/batch-delete", {
      method: "POST",
      body: JSON.stringify({ taskIds: ids }),
    }).then((res: any) => ({
      ...res,
      deleted: res?.deletedCount ?? res?.deletedIds?.length ?? 0,
    })),
  importTaskSourceUrl: (id: string, kind: "paper" | "answer") =>
    apiUrl(`/api/import-tasks/${id}/source/${kind}`),
  getImportTaskImageLibrary: (id: string) =>
    fetcher(`/api/import-tasks/${id}/image-library`),
  updateImportQuestion: (taskId: string, qid: string, data: unknown) =>
    fetcher(`/api/import-tasks/${taskId}/questions/${qid}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  uploadImportQuestionImages: (taskId: string, qid: string, files: File[]) => {
    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));
    return fetcher(`/api/import-tasks/${taskId}/questions/${qid}/images`, {
      method: "POST",
      body: formData,
    });
  },
  selectImportQuestionImages: (taskId: string, qid: string, images: unknown[]) =>
    fetcher(`/api/import-tasks/${taskId}/questions/${qid}/images/select`, {
      method: "POST",
      body: JSON.stringify({ images }),
    }),
  standardizeImportQuestionAi: (taskId: string, qid: string, markdown: string, forceAi = false) =>
    fetcher(`/api/import-tasks/${taskId}/questions/${qid}/standardize/ai`, {
      method: "POST",
      body: JSON.stringify({ markdown, forceAi }),
    }),
  generateImportQuestionAnalysis: (taskId: string, qid: string, data: unknown) =>
    fetcher(`/api/import-tasks/${taskId}/questions/${qid}/analysis`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  bankImportQuestion: (taskId: string, qid: string) =>
    fetcher(`/api/import-tasks/${taskId}/questions/${qid}/bank`, {
      method: "POST",
    }),
  bankAllImportQuestions: (taskId: string) =>
    fetcher(`/api/import-tasks/${taskId}/bank`, { method: "POST" }),
  rescanImportTask: (id: string) =>
    fetcher(`/api/import-tasks/${id}/rescan`, { method: "POST" }),
  previewCanonicalization: (id: string) =>
    fetcher(`/api/import-tasks/${id}/canonicalization/preview`, { method: "POST" }),
  applyCanonicalization: (id: string, applyToken: string) =>
    fetcher(`/api/import-tasks/${id}/canonicalization/apply`, {
      method: "POST",
      body: JSON.stringify({ applyToken }),
    }),
  rollbackCanonicalization: (id: string) =>
    fetcher(`/api/import-tasks/${id}/canonicalization/rollback`, { method: "POST" }),
  createStandardizationJob: (id: string) =>
    fetcher(`/api/import-tasks/${id}/standardization-jobs`, { method: "POST" }),
  getStandardizationJob: (id: string, jobId: string) =>
    fetcher(`/api/import-tasks/${id}/standardization-jobs/${jobId}`),
  cancelStandardizationJob: (id: string, jobId: string) =>
    fetcher(`/api/import-tasks/${id}/standardization-jobs/${jobId}/cancel`, { method: "POST" }),
  resumeStandardizationJob: (id: string, jobId: string) =>
    fetcher(`/api/import-tasks/${id}/standardization-jobs/${jobId}/resume`, { method: "POST" }),
  retryFailedStandardizationJob: (id: string, jobId: string) =>
    fetcher(`/api/import-tasks/${id}/standardization-jobs/${jobId}/retry-failed`, { method: "POST" }),

  // Question bank
  getQuestions: (params: Record<string, unknown> = {}) =>
    fetcher(`/api/question-bank/questions${qs(params)}`).then(withTotal),
  getQuestion: (id: string) => fetcher(`/api/question-bank/questions/${id}`),
  getQuestionImageLibrary: (id: string) =>
    fetcher(`/api/question-bank/questions/${id}/image-library`),
  createQuestion: (data: unknown) =>
    fetcher("/api/question-bank/questions", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateQuestion: (id: string, data: unknown) =>
    fetcher(`/api/question-bank/questions/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  uploadQuestionImages: (id: string, files: File[]) => {
    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));
    return fetcher(`/api/question-bank/questions/${id}/images`, {
      method: "POST",
      body: formData,
    });
  },
  standardizeQuestionAi: (id: string, markdown: string) =>
    fetcher(`/api/question-bank/questions/${id}/standardize/ai`, {
      method: "POST",
      body: JSON.stringify({ markdown }),
    }),
  generateQuestionAnalysis: (id: string, data: unknown) =>
    fetcher(`/api/question-bank/questions/${id}/analysis`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  deleteQuestion: (id: string) =>
    fetcher(`/api/question-bank/questions/${id}`, { method: "DELETE" }),
  deleteQuestions: (ids: string[]) =>
    deleteSequentially(ids, (id) => api.deleteQuestion(id)),

  // Knowledge points
  getKnowledgePoints: () => fetcher("/api/knowledge-points"),
  createKnowledgePoint: (data: unknown) =>
    fetcher("/api/knowledge-points", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateKnowledgePoint: (id: string, data: unknown) =>
    fetcher(`/api/knowledge-points/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  deleteKnowledgePoint: (id: string) =>
    fetcher(`/api/knowledge-points/${id}`, { method: "DELETE" }),
  deleteKnowledgePoints: (ids: string[]) =>
    deleteSequentially(ids, (id) => api.deleteKnowledgePoint(id)),

  // Papers
  getPapers: (params: Record<string, unknown> = {}) =>
    fetcher(`/api/papers${qs(params)}`),
  getPaper: (id: string) => fetcher(`/api/papers/${id}`),
  createPaper: (data: unknown) =>
    fetcher("/api/papers", {
      method: "POST",
      body: JSON.stringify(normalizePaperPayload(data)),
    }),
  updatePaper: (id: string, data: unknown) =>
    fetcher(`/api/papers/${id}`, {
      method: "PUT",
      body: JSON.stringify(normalizePaperPayload(data)),
    }),
  deletePaper: (id: string) =>
    fetcher(`/api/papers/${id}`, { method: "DELETE" }),
  deletePapers: (ids: string[]) =>
    deleteSequentially(ids, (id) => api.deletePaper(id)),
  paperExportUrl: (
    id: string,
    format: "docx" | "pdf",
    variant: string = "teacher",
  ) => apiUrl(`/api/papers/${id}/export${qs({ format, variant })}`),

  // Markdown standardization
  standardizeLocal: (markdown: string) =>
    fetcher("/api/markdown/standardize/local", {
      method: "POST",
      body: JSON.stringify({ markdown }),
    }),
  standardizeAi: (markdown: string) =>
    fetcher("/api/markdown/standardize/ai", {
      method: "POST",
      body: JSON.stringify({ markdown }),
    }),

  // AI-generated analysis
  generateAnalysisAi: (data: {
    manualMarkdown: string;
    answer?: string;
    type?: string;
    knowledgePoints?: string[];
    images?: unknown[];
    subQuestions?: unknown[];
  }) =>
    fetcher("/api/ai/analysis", {
      method: "POST",
      body: JSON.stringify(data),
    }),
};
