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
  const nextMarkdown = firstText(markdown, payload?.markdown, payload?.standardizedMarkdown, sub?.markdown, sub?.stemMarkdown);
  const nextAnswer = firstText(payload?.answer, payload?.suggestedAnswer, sub?.answer, question?.answer);
  const nextAnalysis = firstText(payload?.analysis, payload?.explanation, sub?.analysis, question?.analysis);
  const nextOptions: QuestionOption[] = normalizeQuestionOptions(payload?.options ?? sub?.options ?? question?.options);

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
