import {
  getImageKey,
  normalizeQuestionOptions,
  type QuestionImage,
  type QuestionOption,
} from "@/lib/question";

function text(value: unknown): string {
  return String(value ?? "").trim();
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    const normalized = text(value);
    if (normalized) return normalized;
  }
  return "";
}

function firstSubQuestionPayload(payload: any): any {
  const candidates = [
    payload?.subQuestions,
    payload?.children,
    payload?.metadata?.subQuestions,
    payload?.standardizer?.subQuestions,
    payload?.question?.subQuestions,
    payload?.question?.children,
  ];
  for (const candidate of candidates) {
    if (Array.isArray(candidate) && candidate.length > 0 && typeof candidate[0] === "object") {
      return candidate[0];
    }
  }
  return {};
}

function subQuestionHasAiContent(item: any): boolean {
  return Boolean(text(item?.answer) || text(item?.analysis) || text(item?.explanation));
}

export function aiAnalysisFallbackMessage(payload: any): string | null {
  const metadata = payload?.metadata || {};
  const warnings = Array.isArray(metadata?.warnings) ? metadata.warnings.map((item: unknown) => text(item)).filter(Boolean) : [];
  const hasTopLevelContent = Boolean(text(payload?.analysis) || text(payload?.explanation));
  const subQuestions = [payload?.subQuestions, payload?.children, metadata?.subQuestions].find((items) => Array.isArray(items)) || [];
  const hasSubContent = Array.isArray(subQuestions) && subQuestions.some(subQuestionHasAiContent);
  if (!metadata?.fallbackUsed || hasTopLevelContent || hasSubContent) {
    return null;
  }
  return warnings[0] || text(metadata?.error) || "AI 解析暂时不可用，已保留当前内容，可稍后重试";
}

export function uniqueQuestionImages(...groups: Array<QuestionImage[] | undefined>): QuestionImage[] {
  const seen = new Set<string>();
  const result: QuestionImage[] = [];
  groups.flatMap((group) => group || []).forEach((image, index) => {
    const key = getImageKey(image) || text(image.url) || text(image.path) || text(image.name) || `image-${index}`;
    if (!key || seen.has(key)) return;
    seen.add(key);
    result.push(image);
  });
  return result;
}

export function buildSubQuestionAnalysisPayload({
  parentMarkdown,
  parentImages,
  sub,
  knowledgePoints,
}: {
  parentMarkdown: string;
  parentImages?: QuestionImage[];
  sub: any;
  knowledgePoints?: string[];
}) {
  const parent = text(parentMarkdown);
  const subLabel = text(sub?.label);
  const subMarkdown = text(sub?.markdown);
  const manualMarkdown = [
    parent ? `【大题题干/材料】\n${parent}` : "",
    `${subLabel ? `【小问 ${subLabel}】` : "【小问】"}\n${subMarkdown}`,
  ]
    .filter(Boolean)
    .join("\n\n");

  return {
    manualMarkdown,
    type: text(sub?.type) || "unknown",
    answer: text(sub?.answer),
    knowledgePoints: knowledgePoints || [],
    images: uniqueQuestionImages(parentImages, sub?.images),
  };
}

export function subStandardizePatch(markdown: string, payload: any): Partial<any> {
  const sub = firstSubQuestionPayload(payload);
  const question = payload?.question || {};
  const patch: Partial<any> = {};
  const nextMarkdown = firstText(payload?.markdown, payload?.standardizedMarkdown, sub?.markdown, sub?.stemMarkdown, markdown);
  const nextAnswer = firstText(payload?.answer, payload?.suggestedAnswer, sub?.answer, question?.answer);
  const nextAnalysis = firstText(payload?.analysis, payload?.explanation, sub?.analysis, question?.analysis);
  const images = uniqueQuestionImages(payload?.images, question?.images, sub?.images);
  const nextOptions: QuestionOption[] = normalizeQuestionOptions(payload?.options ?? sub?.options ?? question?.options, images);

  if (nextMarkdown) patch.markdown = nextMarkdown;
  if (nextAnswer) patch.answer = nextAnswer;
  if (nextAnalysis) patch.analysis = nextAnalysis;
  if (nextOptions.length > 0) patch.options = nextOptions;
  return patch;
}

export function subAnalysisPatch(payload: any): Partial<any> {
  const sub = firstSubQuestionPayload(payload);
  const patch: Partial<any> = {};
  const nextAnswer = firstText(payload?.answer, payload?.suggestedAnswer, sub?.answer);
  const nextAnalysis = firstText(payload?.analysis, payload?.explanation, sub?.analysis);

  if (nextAnswer) patch.answer = nextAnswer;
  if (nextAnalysis) patch.analysis = nextAnalysis;
  if (Array.isArray(payload?.warnings) && payload.warnings.length > 0) patch.warnings = payload.warnings;
  return patch;
}
