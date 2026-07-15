// Generated from ../../openapi/question-engine.v1.yaml. Do not edit by hand.

export type JsonObject = Record<string, unknown>;

export type CapabilitySummary = {
  code: string;
  name: string;
  boundary?: string;
  [key: string]: unknown;
};

export type DeliveryBoundary = {
  includePaths?: string[];
  excludePaths?: string[];
  [key: string]: unknown;
};

export type EngineCatalog = {
  code: string;
  modules: JsonObject[];
  supplementalCapabilities: JsonObject[];
  deliveryBoundary?: DeliveryBoundary;
  [key: string]: unknown;
};

export type EngineInterfaceDescriptor = {
  groupCode: string;
  groupName: string;
  method: string;
  path: string;
  description?: string;
  audience: string;
  source: string;
};

export type QuestionProcessingDescriptor = {
  code: string;
  name?: string;
  boundary?: string;
  packageVersion: "question-package.v1" | string;
  endpoints: Record<string, string>;
  [key: string]: unknown;
};

export type OcrFlowDescriptor = {
  code: "ocr-flow" | string;
  name: string;
  boundary: string;
  defaultProvider: string;
  providerContract: JsonObject;
  postProcessContract: JsonObject;
  preprocessors?: JsonObject[];
  configKeys?: Record<string, string>;
  javaEndpoints?: Record<string, string>;
  workerEndpoints?: Record<string, string>;
  replaceProviderStrategy?: string[];
  [key: string]: unknown;
};

export type CreateProcessingJobInput = {
  paperFile: File | Blob;
  answerFile?: File | Blob;
  stage?: string;
  subject?: string;
  grade?: string;
  region?: string;
  year?: string;
  title?: string;
};

export type SourceFile = {
  kind: "paper" | "answer" | string;
  filename?: string;
  previewUrl?: string;
};

export type OcrStatus = {
  kind?: string;
  jobId?: string;
  status?: string;
  raw?: JsonObject;
};

export type ImportTaskRescanResult = {
  taskId: string;
  status: string;
  paperOcrStatus?: string;
  answerOcrStatus?: string;
  rescanInProgress: boolean;
  rescannedJobs: JsonObject;
  [key: string]: unknown;
};

export type ProcessingStatus =
  | "PROCESSING"
  | "WAITING_REVIEW"
  | "PARTIAL_COMPLETED"
  | "COMPLETED"
  | "FAILED"
  | "RETRYABLE"
  | "UNKNOWN";

export type ProcessingJob = {
  jobId: string;
  title?: string;
  stage?: string;
  subject?: string;
  grade?: string;
  region?: string;
  year?: string;
  status: string;
  processingStatus: ProcessingStatus;
  failureReason?: string;
  questionCount?: number;
  sourceFiles?: SourceFile[];
  paperOcr?: OcrStatus;
  answerOcr?: OcrStatus;
  createdAt?: string;
  updatedAt?: string;
};

export type QuestionOption = {
  label?: string;
  contentMarkdown?: string;
  raw?: JsonObject;
};

export type QuestionImage = {
  id?: string;
  imageId?: string;
  index?: number;
  imageIndex?: number;
  name?: string;
  path?: string;
  url?: string;
  source?: string;
  type?: string;
  size?: number;
  storageFileId?: string;
  questionId?: string;
  contentType?: string;
  imageDataUrl?: string;
  aiImageIncluded?: boolean;
  aiImageSkipReason?: string;
  raw?: JsonObject;
};

export type ImagePlacementKind =
  | "stem"
  | "option"
  | "subquestion"
  | "shared"
  | "answer"
  | "analysis"
  | "unassigned"
  | "decoration";

export type QuestionImagePlacement = {
  placementId: string;
  imageId: string;
  target: {
    kind: ImagePlacementKind;
    optionLabel?: string;
    subQuestionId?: string;
  };
  order: number;
  sourceEvidence: {
    markdownStart?: number;
    markdownEnd?: number;
    pageIndex?: number;
    bbox?: number[];
  };
  inference: {
    method: "explicit-offset" | "geometry" | "rule" | "multimodal" | "human";
    confidence: number;
    reasons: string[];
    alternatives?: JsonObject[];
  };
  reviewStatus: "auto" | "needs_review" | "confirmed" | "overridden";
};

export type QuestionImageLibrary = {
  items: QuestionImage[];
};

export type SelectQuestionImagesInput = {
  imageIds?: string[];
  images?: QuestionImage[];
};

export type QuestionImageMutationResult = {
  images: QuestionImage[];
  uploaded?: QuestionImage[];
  selected?: QuestionImage[];
  question?: JsonObject;
  task?: JsonObject;
};

export type AiStandardizeInput = {
  markdown: string;
  rawOcrText?: string;
  rawOcrContext?: string;
  structuredHints?: JsonObject;
  questionType?: string;
  answer?: string;
  analysis?: string;
  images?: QuestionImage[];
  writeResult?: boolean;
  apply?: boolean;
  [key: string]: unknown;
};

export type AiStandardizeResult = {
  aiJobId: string;
  writeResult: boolean;
  writeSkippedReason?: string;
  markdown: string;
  standardizedMarkdown?: string;
  answer?: string;
  suggestedAnswer?: string;
  analysis?: string;
  explanation?: string;
  standardizer?: JsonObject;
  metadata?: JsonObject;
  question?: JsonObject;
  [key: string]: unknown;
};

export type AiAnalysisInput = {
  manualMarkdown?: string;
  answer?: string;
  type?: string;
  knowledgePoints?: string[];
  images?: QuestionImage[];
  [key: string]: unknown;
};

export type AiAnalysisResult = AiStandardizeResult;

export type CanonicalizationApplyInput = { applyToken: string };
export type CanonicalizationPreview = {
  applyToken: string;
  summary: { beforeQuestionCount: number; afterQuestionCount: number; mergedQuestionCount: number };
  questions: JsonObject[];
  blockingIssues: string[];
  canonicalization?: JsonObject;
  paperLayout?: JsonObject;
};
export type StandardizationBatchItem = {
  id: string; questionId: string; status: "queued" | "running" | "success" | "failed" | string;
  attemptCount?: number; totalItems?: number; completedItems?: number; successItems?: number; failedItems?: number;
};
export type StandardizationBatchJob = {
  id: string; taskId: string;
  status: "queued" | "running" | "cancelling" | "cancelled" | "completed" | "partial_failed" | "failed" | string;
  totalQuestions: number; totalItems: number; completedQuestions?: number; completedItems?: number;
  successItems?: number; failedItems?: number; maxConcurrency: number; items?: StandardizationBatchItem[];
};

export type QuestionChild = {
  childId?: string;
  sourceQuestionId?: string;
  number?: number;
  stemMarkdown?: string;
  answer?: string;
  analysis?: string;
  options?: QuestionOption[];
  images?: QuestionImage[];
  imagePlacements?: QuestionImagePlacement[];
  raw?: JsonObject;
};

export type MathValidationIssue = {
  code?: string;
  severity?: string;
  message?: string;
  field?: string;
};

export type MathValidation = {
  status?: string;
  summary?: string;
  issues?: MathValidationIssue[];
  raw?: JsonObject;
};

export type SourceEvidence = {
  processingJobId?: string;
  sourceQuestionId?: string;
  answerEvidence?: unknown;
  analysisEvidence?: unknown;
  rawOcrContextUsed?: boolean | null;
  raw?: JsonObject;
};

export type ProcessingWarning = {
  code?: string;
  message?: string;
  targetId?: string;
};

export type ProcessedQuestion = {
  questionId: string;
  sourceQuestionId?: string;
  number?: number;
  status?: string;
  type?: string;
  stemMarkdown: string;
  originalStemMarkdown?: string;
  answer?: string;
  analysis?: string;
  options: QuestionOption[];
  children: QuestionChild[];
  images: QuestionImage[];
  imagePlacements?: QuestionImagePlacement[];
  knowledgePointIdCandidates?: string[];
  knowledgePointCandidates?: string[];
  difficultyCandidate?: string;
  scoreCandidate?: number;
  mathValidation: MathValidation;
  warnings?: ProcessingWarning[];
  sourceEvidence: SourceEvidence;
  raw?: JsonObject;
};

export type QuestionPackage = {
  packageVersion: "question-package.v1" | string;
  capability: "question-processing" | string;
  job: ProcessingJob;
  questions: ProcessedQuestion[];
  warnings: ProcessingWarning[];
};

export type CallbackEvent = {
  id?: string;
  eventType?: string;
  aggregateType?: string;
  aggregateId?: string;
  status?: "pending" | "sent" | "failed" | "dead_letter" | string;
  callbackUrl?: string;
  idempotencyKey?: string;
  retryCount?: number;
  maxRetryCount?: number;
  nextRetryAt?: string | null;
  failureReason?: string;
  payload?: JsonObject;
  response?: JsonObject;
  createdAt?: string;
  updatedAt?: string;
};

export type CallbackEventList = {
  items: CallbackEvent[];
  total: number;
};
