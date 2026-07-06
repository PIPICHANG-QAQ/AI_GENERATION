import { apiUrl } from "@/lib/api";

export interface QuestionImage {
  id?: string;
  imageId?: string;
  name?: string;
  path?: string;
  url?: string;
  source?: string;
  size?: number;
  type?: string;
  storageFileId?: string;
  questionId?: string;
}

export const QUESTION_IMAGE_REF_MIME = "application/x-question-image-ref";

export interface QuestionOption {
  label: string;
  content: string;
  contentMarkdown?: string;
  raw?: unknown;
}

export function questionImageSrc(value?: string | null): string {
  const src = String(value || "").trim();
  if (!src) return "";
  if (/^(https?:|data:|blob:)/i.test(src)) return src;
  if (src.startsWith("/api/")) return apiUrl(src);
  return src;
}

export function getImageKey(img: QuestionImage): string {
  return String(img.storageFileId || img.imageId || img.id || img.url || img.path || img.name || "").trim();
}

function safeDecode(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function stripMarkdownImageSrc(value?: string | null): string {
  return String(value || "")
    .trim()
    .replace(/^<|>$/g, "")
    .trim();
}

function imageOutputSrc(img?: QuestionImage): string {
  return questionImageSrc(img?.url || img?.path || "");
}

export function resolveImageSrc(src?: string | null, images: QuestionImage[] = []): string {
  const raw = stripMarkdownImageSrc(src);
  if (!raw) return "";

  const decoded = safeDecode(raw);
  const indexMatch = /^(?:题图|图|#)?\s*([1-9]\d*)$/i.exec(decoded);
  if (indexMatch) {
    const img = images[Number(indexMatch[1]) - 1];
    const resolved = imageOutputSrc(img);
    if (resolved) return resolved;
  }

  if (/^(https?:|data:|blob:)/i.test(raw) || raw.startsWith("/api/") || raw.startsWith("/")) {
    return questionImageSrc(raw);
  }

  const candidates = [raw, decoded].filter(Boolean);
  const matched = images.find((img) => {
    const values = [img.url, img.path, img.name, getImageKey(img)]
      .map((value) => String(value || "").trim())
      .filter(Boolean);
    return values.some((value) =>
      candidates.some((candidate) => value === candidate || safeDecode(value) === candidate || value.endsWith(`/${candidate}`)),
    );
  });
  return imageOutputSrc(matched) || questionImageSrc(raw);
}

function markdownImageSources(text: string): string[] {
  const sources: string[] = [];
  const regex = /!\[[^\]]*]\(\s*<?([^>)\s]+)>?(?:\s+["'][^)]*["'])?\s*\)/g;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text || "")) !== null) {
    if (match[1]) sources.push(stripMarkdownImageSrc(match[1]));
  }
  return sources;
}

function sameResolvedImage(a: string, b: string): boolean {
  const left = safeDecode(questionImageSrc(a));
  const right = safeDecode(questionImageSrc(b));
  return !!left && !!right && left === right;
}

function isImageReferenced(img: QuestionImage, index: number, images: QuestionImage[], texts: string[]): boolean {
  const target = imageOutputSrc(img);
  const rawValues = [img.url, img.path, img.name, getImageKey(img)]
    .map((value) => String(value || "").trim())
    .filter(Boolean);

  return texts.some((text) => {
    const raw = String(text || "");
    const imageRefs = markdownImageSources(raw);
    if (
      imageRefs.some((src) => {
        const indexMatch = /^(?:题图|图|#)?\s*([1-9]\d*)$/i.exec(safeDecode(src));
        if (indexMatch && Number(indexMatch[1]) === index) return true;
        const resolved = resolveImageSrc(src, images);
        return target ? sameResolvedImage(resolved, target) : rawValues.includes(src);
      })
    ) {
      return true;
    }
    return rawValues.some((value) => raw.includes(value));
  });
}

export function getUnreferencedImageRefs(
  images: QuestionImage[] = [],
  texts: string[] = [],
): Array<{ index: number; token: string }> {
  return images
    .map((img, zeroIndex) => ({ img, index: zeroIndex + 1, token: `![](图${zeroIndex + 1})` }))
    .filter(({ img, index }) => !isImageReferenced(img, index, images, texts))
    .map(({ index, token }) => ({ index, token }));
}

function appendImageRefTokens(markdown: string, refs: Array<{ token: string }>): string {
  if (refs.length === 0) return markdown;
  const current = String(markdown || "");
  const separator = current.trim() ? "\n\n" : "";
  return `${current}${separator}${refs.map((ref) => ref.token).join("\n\n")}`;
}

export function appendMissingImageRefs(
  markdown: string,
  images: QuestionImage[] = [],
  siblingTexts: string[] = [],
): string {
  return appendImageRefTokens(markdown, getUnreferencedImageRefs(images, [markdown, ...siblingTexts]));
}

export function appendNewImageRefs(
  markdown: string,
  previousImages: QuestionImage[] = [],
  nextImages: QuestionImage[] = [],
  siblingTexts: string[] = [],
): string {
  const previousKeys = new Set(previousImages.map(getImageKey).filter(Boolean));
  const refs = getUnreferencedImageRefs(nextImages, [markdown, ...siblingTexts]).filter(({ index }) => {
    const img = nextImages[index - 1];
    const key = img ? getImageKey(img) : "";
    return key && !previousKeys.has(key);
  });
  return appendImageRefTokens(markdown, refs);
}

export function getQuestionMarkdown(q: any): string {
  if (!q) return "";
  const markdown = q.manualMarkdown || q.stemMarkdown || q.stem || q.content || "";
  return withEditableChoiceOptions(markdown, q.options);
}

export function getQuestionImages(q: any): QuestionImage[] {
  if (!q || !Array.isArray(q.images)) return [];
  return q.images;
}

export function getSubQuestions(q: any): any[] {
  if (!q) return [];
  if (Array.isArray(q.subQuestions)) return q.subQuestions;
  if (Array.isArray(q.children)) return q.children;
  return [];
}

const GENERATED_SUB_LABEL_RE = /^\(\d+\)$/;

export function isGeneratedSubQuestionLabel(label?: string | null, index?: number): boolean {
  const normalized = String(label || "").trim();
  if (!normalized) return true;
  if (typeof index === "number") return normalized === `(${index + 1})`;
  return GENERATED_SUB_LABEL_RE.test(normalized);
}

export function renumberAutoSubQuestionLabels<T extends { label?: string; autoLabel?: boolean }>(subs: T[]): T[] {
  return subs.map((sub, index) =>
    sub.autoLabel === false ? sub : { ...sub, label: `(${index + 1})`, autoLabel: true },
  );
}

export function createBlankSubQuestionForm(index: number, parent?: any, carryParentAnswer = false): any {
  const idSuffix = `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  return {
    id: `sub_new_${index + 1}_${idSuffix}`,
    label: `(${index + 1})`,
    autoLabel: true,
    markdown: "",
    type: parent?.type || "unknown",
    difficulty: parent?.difficulty || "medium",
    score: 0,
    answer: carryParentAnswer ? String(parent?.answer || "") : "",
    analysis: carryParentAnswer ? String(parent?.analysis || "") : "",
    knowledgePointIds: [],
    knowledgePoints: "",
    images: [],
    options: [],
    contextMatched: false,
    answerEvidence: "",
    analysisEvidence: "",
    warnings: [],
  };
}

export function addSubQuestionForm(current: any[], parent?: any): any[] {
  const carryParentAnswer = current.length === 0;
  return renumberAutoSubQuestionLabels([
    ...current,
    createBlankSubQuestionForm(current.length, parent, carryParentAnswer),
  ]);
}

export function removeSubQuestionForm(current: any[], index: number): any[] {
  return renumberAutoSubQuestionLabels(current.filter((_, itemIndex) => itemIndex !== index));
}

export function subQuestionEditorForm(sub: any, index: number, parent?: any): any {
  const label = sub?.label || `(${index + 1})`;
  return {
    id: String(sub?.id || `sub_${index + 1}`),
    label,
    autoLabel: isGeneratedSubQuestionLabel(label, index),
    markdown: getQuestionMarkdown(sub),
    type: sub?.type || parent?.type || "unknown",
    difficulty: sub?.difficulty || parent?.difficulty || "medium",
    score: sub?.score ?? 0,
    answer: sub?.answer || sub?.suggestedAnswer || "",
    analysis: sub?.analysis || sub?.explanation || "",
    knowledgePointIds: Array.isArray(sub?.knowledgePointIds) ? sub.knowledgePointIds.map(String) : [],
    knowledgePoints: Array.isArray(sub?.knowledgePoints) ? sub.knowledgePoints.join("，") : String(sub?.knowledgePoints || ""),
    images: getQuestionImages(sub),
    options: normalizeQuestionOptions(sub?.options),
    contextMatched: Boolean(sub?.contextMatched ?? sub?.aiMetadata?.contextMatched),
    answerEvidence: String(sub?.answerEvidence ?? sub?.aiMetadata?.answerEvidence ?? ""),
    analysisEvidence: String(sub?.analysisEvidence ?? sub?.aiMetadata?.analysisEvidence ?? ""),
    warnings: Array.isArray(sub?.warnings) ? sub.warnings : Array.isArray(sub?.aiMetadata?.warnings) ? sub.aiMetadata.warnings : [],
    aiMetadata: sub?.aiMetadata,
  };
}

export function mergeSubQuestionSuggestions(current: any[], suggestions: unknown, parent?: any): any[] {
  const rawSuggestions = Array.isArray(suggestions) ? suggestions : getSubQuestions(suggestions);
  if (rawSuggestions.length === 0) return current;
  const incoming = rawSuggestions.map((sub, index) => subQuestionEditorForm(sub, index, parent));
  if (current.length === 0) return incoming;

  const used = new Set<number>();
  const merged = current.map((sub, index) => {
    const matchIndex = findSubQuestionSuggestion(sub, incoming, used, index);
    if (matchIndex < 0) return sub;
    used.add(matchIndex);
    return mergeSubQuestionForm(sub, incoming[matchIndex]);
  });
  incoming.forEach((sub, index) => {
    if (!used.has(index)) merged.push(sub);
  });
  return merged;
}

function findSubQuestionSuggestion(sub: any, incoming: any[], used: Set<number>, fallbackIndex: number): number {
  const id = String(sub?.id || "").trim();
  if (id) {
    const index = incoming.findIndex((item, itemIndex) => !used.has(itemIndex) && String(item?.id || "").trim() === id);
    if (index >= 0) return index;
  }
  const label = String(sub?.label || "").trim();
  if (label) {
    const index = incoming.findIndex((item, itemIndex) => !used.has(itemIndex) && String(item?.label || "").trim() === label);
    if (index >= 0) return index;
  }
  return fallbackIndex < incoming.length && !used.has(fallbackIndex) ? fallbackIndex : -1;
}

function mergeSubQuestionForm(current: any, incoming: any): any {
  const next = { ...current };
  if (String(incoming?.label || "").trim()) {
    next.label = incoming.label;
    next.autoLabel =
      incoming.autoLabel !== undefined ? Boolean(incoming.autoLabel) : isGeneratedSubQuestionLabel(incoming.label);
  }
  ["markdown", "type", "difficulty", "answer", "analysis", "knowledgePoints"].forEach((field) => {
    if (String(incoming?.[field] || "").trim()) {
      next[field] = incoming[field];
    }
  });
  ["answerEvidence", "analysisEvidence"].forEach((field) => {
    if (String(incoming?.[field] || "").trim()) {
      next[field] = incoming[field];
    }
  });
  if (incoming?.contextMatched !== undefined) next.contextMatched = Boolean(incoming.contextMatched);
  if (Array.isArray(incoming?.warnings) && incoming.warnings.length > 0) next.warnings = incoming.warnings;
  if (incoming?.aiMetadata && typeof incoming.aiMetadata === "object") next.aiMetadata = incoming.aiMetadata;
  if (incoming?.score !== undefined && incoming?.score !== null) next.score = incoming.score;
  if (Array.isArray(incoming?.knowledgePointIds) && incoming.knowledgePointIds.length > 0) {
    next.knowledgePointIds = incoming.knowledgePointIds;
  }
  if (Array.isArray(incoming?.images) && incoming.images.length > 0) next.images = incoming.images;
  if (Array.isArray(incoming?.options) && incoming.options.length > 0) next.options = incoming.options;
  return next;
}

export function getSelectedSubQuestions(q: any, subSelections?: Record<string, string[]>): any[] {
  const subs = getSubQuestions(q);
  if (subs.length === 0) return [];
  const selectedIds = subSelections?.[q?.id];
  if (!Array.isArray(selectedIds) || selectedIds.length === 0) return subs;
  const selectedIdSet = new Set(selectedIds);
  const selectedSubs = subs.filter((sub: any) => selectedIdSet.has(String(sub.id)));
  return selectedSubs.length > 0 ? selectedSubs : subs;
}

export function normalizeQuestionOptions(value: unknown): QuestionOption[] {
  if (!Array.isArray(value)) return [];
  const options: QuestionOption[] = [];
  const seen = new Set<string>();
  value.forEach((item, index) => {
    const raw = item as any;
    const fallbackLabel = String.fromCharCode(65 + index);
    const label = String(
      typeof raw === "object" && raw
        ? raw.label ?? raw.key ?? raw.name ?? raw.option ?? fallbackLabel
        : fallbackLabel,
    )
      .trim()
      .toUpperCase();
    const content = String(
      typeof raw === "object" && raw
        ? raw.contentMarkdown ?? raw.markdown ?? raw.text ?? raw.content ?? raw.value ?? ""
        : raw ?? "",
    ).trim();
    if (!label || !content || seen.has(label)) return;
    seen.add(label);
    options.push({ label, content, contentMarkdown: content, raw: item });
  });
  return options;
}

function nextChoiceLabel(label: string) {
  return String.fromCharCode(label.charCodeAt(0) + 1);
}

function normalizeChoiceLabel(value: string) {
  const char = String(value || "")[0] || "";
  const code = char.charCodeAt(0);
  if (code >= 0xff21 && code <= 0xff28) return String.fromCharCode(code - 0xff21 + 65);
  if (code >= 0xff41 && code <= 0xff48) return String.fromCharCode(code - 0xff41 + 65);
  return char.toUpperCase();
}

function cleanOptionText(value: string) {
  return value
    .replace(/^[\s\r\n\-*+]+/, "")
    .replace(/[\s\r\n]+$/, "")
    .trim();
}

function splitTrailingImageBlock(content: string): { content: string; trailingImageBlock: string } {
  const match = /(?:\s*!\[[^\]]*]\([^)]+\)\s*)+$/.exec(String(content || ""));
  if (!match) return { content, trailingImageBlock: "" };
  const before = content.slice(0, match.index).trimEnd();
  const trailingImageBlock = match[0].trim();
  if (!before || !trailingImageBlock) return { content, trailingImageBlock: "" };
  return { content: before, trailingImageBlock };
}

function normalizeTasksEnvironment(markdown: string) {
  return String(markdown || "").replace(/\\(begin|end)\{t+asks\}/gi, (_match, kind) => `\\${kind}{tasks}`);
}

function tasksColumnCount(optionCount: number) {
  if (optionCount >= 4) return 4;
  if (optionCount >= 2) return 2;
  return 1;
}

export function withEditableChoiceOptions(markdown: string, rawOptions: unknown): string {
  const normalizedMarkdown = normalizeTasksEnvironment(markdown).trim();
  const options = normalizeQuestionOptions(rawOptions);
  if (options.length === 0) return normalizedMarkdown;
  if (splitChoiceOptionsFromMarkdown(normalizedMarkdown, "choice").options.length > 0) {
    return normalizedMarkdown;
  }

  const optionBlock = [
    "",
    `\\begin{tasks}(${tasksColumnCount(options.length)})`,
    ...options.map((option) => `\\task ${option.contentMarkdown || option.content}`),
    "\\end{tasks}",
  ].join("\n");
  return `${normalizedMarkdown}${normalizedMarkdown ? "\n" : ""}${optionBlock}`.trim();
}

function splitTasksOptions(markdown: string): { stemMarkdown: string; options: QuestionOption[] } {
  const normalized = normalizeTasksEnvironment(markdown);
  const match = /\\begin\{tasks\}(?:\([^)]+\)|\[[^\]]+\])?([\s\S]*?)\\end\{tasks\}/.exec(normalized);
  const taskMatches: RegExpExecArray[] = [];
  const taskRegex = /\\task\b/g;
  let taskMatch: RegExpExecArray | null;
  while ((taskMatch = taskRegex.exec(normalized)) !== null) {
    taskMatches.push(taskMatch);
  }
  if (!match && taskMatches.length < 2) return { stemMarkdown: normalized.trim(), options: [] };

  const body = match ? match[1] : normalized.slice(taskMatches[0].index || 0);
  const stemMarkdown = match
    ? `${normalized.slice(0, match.index)}\n${normalized.slice(match.index + match[0].length)}`.trim()
    : normalized.slice(0, taskMatches[0].index || 0).trim();
  const options = body
    .split(/\\task\b/)
    .slice(1)
    .map((content, index) => ({
      label: String.fromCharCode(65 + index),
      content: cleanOptionText(content),
      contentMarkdown: cleanOptionText(content),
    }))
    .filter((option) => option.content);
  return { stemMarkdown, options };
}

export function splitChoiceOptionsFromMarkdown(
  markdown: string,
  questionType: string = "choice",
): { stemMarkdown: string; options: QuestionOption[] } {
  const raw = String(markdown || "");
  const taskSplit = splitTasksOptions(raw);
  if (taskSplit.options.length >= 2) return taskSplit;

  if (questionType !== "choice") return { stemMarkdown: raw.trim(), options: [] };

  const labelPattern = "[A-Ha-hＡ-Ｈａ-ｈ]";
  const punctuatedRegex = new RegExp(
    `(^|[\\r\\n]+|[ \\t　]+|[。；;：:，,、?？）)]\\s*)(?:[-*+]\\s*)?(?:[（(]?(${labelPattern})[）)]|(${labelPattern})[\\.．、:：])\\s*`,
    "g",
  );
  const bareLineRegex = new RegExp(`(^|[\\r\\n]+)\\s*(?:[-*+]\\s*)?(${labelPattern})(?=\\s+)`, "g");
  const markers: Array<{ label: string; markerStart: number; contentStart: number }> = [];
  let match: RegExpExecArray | null;
  while ((match = punctuatedRegex.exec(raw)) !== null) {
    const label = normalizeChoiceLabel(String(match[2] || match[3] || ""));
    if (!label) continue;
    const prefixLength = String(match[1] || "").length;
    markers.push({
      label,
      markerStart: match.index + prefixLength,
      contentStart: match.index + match[0].length,
    });
  }
  while ((match = bareLineRegex.exec(raw)) !== null) {
    const label = normalizeChoiceLabel(String(match[2] || ""));
    if (!label) continue;
    const prefixLength = String(match[1] || "").length;
    markers.push({
      label,
      markerStart: match.index + prefixLength,
      contentStart: match.index + match[0].length,
    });
  }
  markers.sort((a, b) => a.markerStart - b.markerStart || a.contentStart - b.contentStart);

  let selected: typeof markers = [];
  for (let start = 0; start < markers.length; start += 1) {
    if (markers[start].label !== "A") continue;
    const current = [markers[start]];
    let expected = "B";
    for (let cursor = start + 1; cursor < markers.length; cursor += 1) {
      if (markers[cursor].label === expected) {
        current.push(markers[cursor]);
        expected = nextChoiceLabel(expected);
        continue;
      }
      if (current.length > 0) break;
    }
    if (current.length >= 2) {
      selected = current;
      break;
    }
  }

  if (selected.length < 2) return { stemMarkdown: raw.trim(), options: [] };

  const stemMarkdown = raw
    .slice(0, selected[0].markerStart)
    .replace(/[-*+]\s*$/, "")
    .trim();
  let trailingImageBlock = "";
  const options = selected
    .map((marker, index) => {
      const nextStart = selected[index + 1]?.markerStart ?? raw.length;
      let content = cleanOptionText(raw.slice(marker.contentStart, nextStart));
      if (index === selected.length - 1) {
        const split = splitTrailingImageBlock(content);
        content = split.content;
        trailingImageBlock = split.trailingImageBlock;
      }
      return { label: marker.label, content, contentMarkdown: content };
    })
    .filter((option) => option.content);

  const stemWithTrailingImages = trailingImageBlock ? `${stemMarkdown}\n\n${trailingImageBlock}`.trim() : stemMarkdown;
  return options.length >= 2 ? { stemMarkdown: stemWithTrailingImages, options } : { stemMarkdown: raw.trim(), options: [] };
}

export function getQuestionMarkdownParts(
  markdown: string,
  questionType: string,
  fallbackOptions: unknown = [],
): { stemMarkdown: string; options: QuestionOption[] } {
  const parsed = splitChoiceOptionsFromMarkdown(markdown, questionType);
  if (parsed.options.length > 0) return parsed;
  return {
    stemMarkdown: String(markdown || "").trim(),
    options: questionType === "choice" ? normalizeQuestionOptions(fallbackOptions) : [],
  };
}

export interface SourceFileInfo {
  name: string;
  ext: string;
  kind: "image" | "pdf" | "office" | "text" | "other";
}

const IMAGE_EXTS = ["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"];
const OFFICE_EXTS = ["doc", "docx", "ppt", "pptx", "xls", "xlsx"];
const TEXT_EXTS = ["md", "markdown", "txt"];

export function getSourceFileInfo(file: any): SourceFileInfo | null {
  if (!file) return null;
  let name = "";
  if (typeof file === "string") name = file;
  else name = file.filename || file.name || file.path || file.url || "";
  if (!name) return { name: "", ext: "", kind: "other" };
  const ext = (name.split(".").pop() || "").toLowerCase();
  let kind: SourceFileInfo["kind"] = "other";
  if (IMAGE_EXTS.includes(ext)) kind = "image";
  else if (ext === "pdf") kind = "pdf";
  else if (OFFICE_EXTS.includes(ext)) kind = "office";
  else if (TEXT_EXTS.includes(ext)) kind = "text";
  return { name, ext, kind };
}
