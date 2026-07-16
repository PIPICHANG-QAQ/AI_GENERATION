import { apiUrl } from "@/lib/api";

export interface QuestionImage {
  id?: string;
  imageId?: string;
  index?: number;
  label?: string;
  refLabel?: string;
  imageLabel?: string;
  name?: string;
  path?: string;
  url?: string;
  source?: string;
  size?: number;
  type?: string;
  storageFileId?: string;
  questionId?: string;
  ownerKind?: string;
  ownerQuestionId?: string;
  ownerId?: string;
  ownerLabel?: string;
  ownerPath?: string;
  owners?: Array<{
    kind?: string;
    questionId?: string;
    id?: string;
    label?: string;
    path?: string;
  }>;
  raw?: Record<string, unknown>;
}

export type ImagePlacementKind =
  | "stem"
  | "option"
  | "subquestion"
  | "shared"
  | "answer"
  | "analysis"
  | "unassigned"
  | "decoration";

export interface QuestionImagePlacement {
  placementId: string;
  imageId: string;
  target: {
    kind: ImagePlacementKind;
    optionLabel?: string;
    subQuestionId?: string;
  };
  order: number;
  sourceEvidence?: {
    markdownStart?: number;
    markdownEnd?: number;
    pageIndex?: number;
    bbox?: number[];
  };
  inference: {
    method: "explicit-offset" | "geometry" | "rule" | "multimodal" | "human";
    confidence: number;
    reasons: string[];
    alternatives?: unknown[];
  };
  reviewStatus: "auto" | "needs_review" | "confirmed" | "overridden";
}

export const QUESTION_IMAGE_REF_MIME = "application/x-question-image-ref";

export interface QuestionOption {
  label: string;
  content: string;
  contentMarkdown?: string;
  raw?: unknown;
}

function encodeUrlPath(value: string): string {
  const [pathWithQuery, hash = ""] = value.split("#", 2);
  const [path, query = ""] = pathWithQuery.split("?", 2);
  const encodedPath = path
    .split("/")
    .map((segment) => {
      try {
        return encodeURIComponent(decodeURIComponent(segment));
      } catch {
        return encodeURIComponent(segment);
      }
    })
    .join("/");
  return `${encodedPath}${query ? `?${query}` : ""}${hash ? `#${encodeURIComponent(hash)}` : ""}`;
}

function encodeBrowserUrl(value: string): string {
  try {
    const url = new URL(value);
    url.pathname = encodeUrlPath(url.pathname);
    return url.toString();
  } catch {
    return encodeUrlPath(value);
  }
}

export function questionImageSrc(value?: string | null): string {
  const src = String(value || "").trim();
  if (!src) return "";
  if (/^(data:|blob:)/i.test(src)) return src;
  if (/^https?:/i.test(src)) return encodeBrowserUrl(src);
  if (src.startsWith("/api/")) return apiUrl(encodeUrlPath(src));
  return encodeBrowserUrl(src);
}

export function getImageKey(img: QuestionImage): string {
  return String(img.storageFileId || img.url || img.path || img.imageId || img.id || img.name || "").trim();
}

function safeDecode(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function rawImageValue(img: QuestionImage, key: string): string {
  const raw = img.raw || {};
  return String(raw[key] ?? "").trim();
}

function normalizeImageLabel(value?: string | null): string {
  const normalized = String(value || "").trim();
  const match = /^(?:题图|图|#)?\s*([1-9]\d*)$/i.exec(safeDecode(normalized));
  return match ? `图${Number(match[1])}` : "";
}

function explicitQuestionImageLabel(img: QuestionImage): string {
  return [
    img.label,
    img.refLabel,
    img.imageLabel,
    rawImageValue(img, "label"),
    rawImageValue(img, "refLabel"),
    rawImageValue(img, "imageLabel"),
    img.name,
  ]
    .map((value) => normalizeImageLabel(value))
    .find(Boolean) || "";
}

export function getQuestionImageLabel(img: QuestionImage, zeroIndex = 0): string {
  const explicit = explicitQuestionImageLabel(img);
  if (explicit) return explicit;

  if (typeof img.index === "number" && Number.isFinite(img.index) && img.index >= 0) {
    return `图${img.index + 1}`;
  }
  return `图${zeroIndex + 1}`;
}

function labelNumber(label: string): number {
  const match = /^图([1-9]\d*)$/.exec(label);
  return match ? Number(match[1]) : 0;
}

export function ensureQuestionImageLabels(images: QuestionImage[] = [], previousImages: QuestionImage[] = []): QuestionImage[] {
  const previousByKey = new Map<string, string>();
  const nextKeys = new Set(images.map(getImageKey).filter(Boolean));
  const reserved = new Set<string>();
  let maxLabel = 0;

  previousImages.forEach((img, index) => {
    const label = getQuestionImageLabel(img, index);
    const key = getImageKey(img);
    if (key && label) previousByKey.set(key, label);
    if (label) {
      if (!key || !nextKeys.has(key)) reserved.add(label);
      maxLabel = Math.max(maxLabel, labelNumber(label));
    }
  });

  const assigned = new Map<number, string>();
  const used = new Set(reserved);
  images.forEach((img, index) => {
    const key = getImageKey(img);
    const retainedLabel = key ? previousByKey.get(key) : "";
    if (retainedLabel && !used.has(retainedLabel)) {
      assigned.set(index, retainedLabel);
      used.add(retainedLabel);
    }
  });
  images.forEach((img, index) => {
    if (assigned.has(index)) return;
    let label = explicitQuestionImageLabel(img);
    if (!label || used.has(label)) {
      maxLabel += 1;
      while (used.has(`图${maxLabel}`)) maxLabel += 1;
      label = `图${maxLabel}`;
    }
    assigned.set(index, label);
    used.add(label);
    maxLabel = Math.max(maxLabel, labelNumber(label));
  });
  return images.map((img, index) => {
    const label = assigned.get(index) || `图${index + 1}`;
    return { ...img, label, refLabel: label };
  });
}

export function ensureImagePlacements(
  images: QuestionImage[] = [],
  placements: QuestionImagePlacement[] = [],
): QuestionImagePlacement[] {
  const byImageId = new Map(placements.map((placement) => [String(placement.imageId || ""), placement]));
  return images.map((image, order) => {
    const imageId = String(image.imageId || image.path || getImageKey(image));
    const existing = byImageId.get(imageId) || placements.find((placement) => placement.imageId === getImageKey(image));
    if (existing) return { ...existing, order };
    const safeId = imageId.replace(/[^a-z0-9_-]+/gi, "-").replace(/^-|-$/g, "") || String(order + 1);
    return {
      placementId: `placement-${safeId}-${order}`,
      imageId,
      target: { kind: "unassigned" },
      order,
      sourceEvidence: {},
      inference: { method: "rule", confidence: 0, reasons: ["new-image-needs-owner"], alternatives: [] },
      reviewStatus: "needs_review",
    };
  });
}

export function updateImagePlacementTarget(
  placements: QuestionImagePlacement[],
  imageId: string,
  target: QuestionImagePlacement["target"],
): QuestionImagePlacement[] {
  return placements.map((placement) =>
    placement.imageId === imageId
      ? {
          ...placement,
          target,
          inference: { ...placement.inference, method: "human", confidence: 1, reasons: ["human-selection"] },
          reviewStatus: "confirmed",
        }
      : placement,
  );
}

export function imagePlacementIssues(placements: QuestionImagePlacement[] = []): string[] {
  const issues: string[] = [];
  const unassigned = placements.filter((placement) => placement.target.kind === "unassigned").length;
  if (unassigned > 0) issues.push(`存在 ${unassigned} 张未归属题图`);
  const needsReview = placements.filter(
    (placement) => placement.reviewStatus === "needs_review" && placement.target.kind !== "unassigned",
  ).length;
  if (needsReview > 0) issues.push(`存在 ${needsReview} 张题图归属需复核`);
  const highConfidenceOwners = new Map<string, number>();
  placements.forEach((placement) => {
    if (["shared", "unassigned", "decoration"].includes(placement.target.kind)) return;
    if (Number(placement.inference?.confidence || 0) < 0.9) return;
    highConfidenceOwners.set(placement.imageId, (highConfidenceOwners.get(placement.imageId) || 0) + 1);
  });
  const conflicts = Array.from(highConfidenceOwners.values()).filter((count) => count > 1).length;
  if (conflicts > 0) issues.push(`存在 ${conflicts} 张题图归属冲突`);
  return issues;
}

export function moveQuestionImageReference(
  image: QuestionImage,
  target: QuestionImagePlacement["target"],
  value: {
    markdown: string;
    answer?: string;
    analysis?: string;
    options?: unknown;
    subQuestions?: any[];
  },
): {
  markdown: string;
  answer: string;
  analysis: string;
  options: QuestionOption[];
  subQuestions: any[];
} {
  const token = `![](${getQuestionImageLabel(image)})`;
  let markdown = removeQuestionImageRefsFromMarkdown(value.markdown, [image]);
  let answer = removeQuestionImageRefsFromMarkdown(value.answer || "", [image]);
  let analysis = removeQuestionImageRefsFromMarkdown(value.analysis || "", [image]);
  let options = removeQuestionImageRefsFromOptions(value.options, [image]);
  let subQuestions = (value.subQuestions || []).map((sub) => ({
    ...sub,
    markdown: removeQuestionImageRefsFromMarkdown(sub.markdown || sub.manualMarkdown || sub.stemMarkdown || "", [image]),
    answer: removeQuestionImageRefsFromMarkdown(sub.answer || "", [image]),
    analysis: removeQuestionImageRefsFromMarkdown(sub.analysis || "", [image]),
    options: removeQuestionImageRefsFromOptions(sub.options, [image]),
  }));
  const append = (text: string) => appendImageRefTokens(text, [{ token }]);
  if (target.kind === "stem" || target.kind === "shared") markdown = append(markdown);
  if (target.kind === "answer") answer = append(answer);
  if (target.kind === "analysis") analysis = append(analysis);
  if (target.kind === "option" && target.optionLabel) {
    options = options.map((option) =>
      option.label === target.optionLabel
        ? { ...option, content: append(option.content), contentMarkdown: append(option.contentMarkdown || option.content) }
        : option,
    );
  }
  if (target.kind === "subquestion" && target.subQuestionId) {
    subQuestions = subQuestions.map((sub) =>
      String(sub.id) === target.subQuestionId ? { ...sub, markdown: append(sub.markdown) } : sub,
    );
  }
  return { markdown, answer, analysis, options, subQuestions };
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
    const label = `图${Number(indexMatch[1])}`;
    const labeledImages = ensureQuestionImageLabels(images);
    const img = labeledImages.find((item, index) => getQuestionImageLabel(item, index) === label) || labeledImages[Number(indexMatch[1]) - 1];
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
  const regex = /!\[[^\]]*]\s*\(\s*<?([^>)\s]+)>?(?:\s+["'][^)]*["'])?\s*\)/g;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text || "")) !== null) {
    if (match[1]) sources.push(stripMarkdownImageSrc(match[1]));
  }
  return sources;
}

function refComparable(value?: string | null): string {
  return safeDecode(stripMarkdownImageSrc(value))
    .replace(/[?#].*$/, "")
    .replace(/\\/g, "/")
    .replace(/^\.\//, "")
    .trim()
    .toLowerCase();
}

function imageRefCandidates(img: QuestionImage, zeroIndex: number): Set<string> {
  const candidates = new Set<string>();
  const label = getQuestionImageLabel(img, zeroIndex);
  const labelNo = labelNumber(label);
  [label, labelNo ? `题图${labelNo}` : "", labelNo ? `#${labelNo}` : ""]
    .filter(Boolean)
    .forEach((value) => candidates.add(refComparable(value)));
  [img.url, img.path, img.name, getImageKey(img), rawImageValue(img, "url"), rawImageValue(img, "path"), rawImageValue(img, "name")]
    .map((value) => String(value || "").trim())
    .filter(Boolean)
    .forEach((value) => {
      const comparable = refComparable(value);
      candidates.add(comparable);
      const filename = comparable.split("/").pop() || "";
      if (filename) candidates.add(filename);
    });
  return candidates;
}

function imageRefMatches(src: string, img: QuestionImage, zeroIndex: number): boolean {
  const comparable = refComparable(src);
  if (!comparable) return false;
  const candidates = imageRefCandidates(img, zeroIndex);
  return candidates.has(comparable) || Array.from(candidates).some((candidate) => comparable.endsWith(`/${candidate}`));
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
        if (imageRefMatches(src, img, index - 1)) return true;
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
  const labeledImages = ensureQuestionImageLabels(images);
  return labeledImages
    .map((img, zeroIndex) => ({ img, index: zeroIndex + 1, token: `![](${getQuestionImageLabel(img, zeroIndex)})` }))
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
  const normalizedMarkdown = normalizeQuestionImageRefsInMarkdown(markdown, images);
  return appendImageRefTokens(normalizedMarkdown, getUnreferencedImageRefs(images, [normalizedMarkdown, ...siblingTexts]));
}

export function appendNewImageRefs(
  markdown: string,
  previousImages: QuestionImage[] = [],
  nextImages: QuestionImage[] = [],
  siblingTexts: string[] = [],
): string {
  const labeledPrevious = ensureQuestionImageLabels(previousImages);
  const labeledNext = ensureQuestionImageLabels(nextImages, labeledPrevious);
  const normalizedMarkdown = normalizeQuestionImageRefsInMarkdown(markdown, labeledNext);
  const previousKeys = new Set(labeledPrevious.map(getImageKey).filter(Boolean));
  const refs = getUnreferencedImageRefs(labeledNext, [normalizedMarkdown, ...siblingTexts]).filter(({ index }) => {
    const img = labeledNext[index - 1];
    const key = img ? getImageKey(img) : "";
    return key && !previousKeys.has(key);
  });
  return appendImageRefTokens(normalizedMarkdown, refs);
}

export function getRemovedQuestionImages(previousImages: QuestionImage[] = [], nextImages: QuestionImage[] = []): QuestionImage[] {
  const nextKeys = new Set(nextImages.map(getImageKey).filter(Boolean));
  return previousImages.filter((img) => {
    const key = getImageKey(img);
    return key && !nextKeys.has(key);
  });
}

export function filterRemovedQuestionImages(images: QuestionImage[] = [], removedImages: QuestionImage[] = []): QuestionImage[] {
  if (removedImages.length === 0) return images;
  const removedKeys = new Set(removedImages.map(getImageKey).filter(Boolean));
  return images.filter((img) => {
    const key = getImageKey(img);
    return !key || !removedKeys.has(key);
  });
}

export function removeQuestionImageRefsFromMarkdown(markdown: string, removedImages: QuestionImage[] = []): string {
  const text = String(markdown || "");
  if (!text || removedImages.length === 0) return text;
  const removed = ensureQuestionImageLabels(removedImages);
  const imageRegex = /!\[[^\]]*]\s*\(\s*<?([^>)\s]+)>?(?:\s+["'][^)]*["'])?\s*\)/g;
  const cleaned = text.replace(imageRegex, (full, src) =>
    removed.some((img, index) => imageRefMatches(src, img, index)) ? "" : full,
  );
  return cleaned
    .split(/\r?\n/)
    .map((line) => line.replace(/[ \t]+$/g, ""))
    .filter((line, index, lines) => line.trim() || (index > 0 && index < lines.length - 1 && lines[index - 1].trim() && lines[index + 1].trim()))
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function normalizeQuestionImageRefsInMarkdown(markdown: string, images: QuestionImage[] = []): string {
  const text = String(markdown || "");
  if (!text || images.length === 0) return text;
  const labeledImages = ensureQuestionImageLabels(images);
  const imageRegex = /!\[[^\]]*]\s*\(\s*<?([^>)\s]+)>?(?:\s+["'][^)]*["'])?\s*\)/g;
  return text.replace(imageRegex, (full, src) => {
    const imageIndex = labeledImages.findIndex((img, index) => imageRefMatches(src, img, index));
    return imageIndex >= 0 ? `![](${getQuestionImageLabel(labeledImages[imageIndex], imageIndex)})` : full;
  });
}

export function removeQuestionImageRefsFromOptions(options: unknown, removedImages: QuestionImage[] = []): QuestionOption[] {
  if (!Array.isArray(options)) return [];
  const seen = new Set<string>();
  return options
    .map((item, index) => {
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
      const cleaned = removeQuestionImageRefsFromMarkdown(content, removedImages);
      return { label, content: cleaned, contentMarkdown: cleaned, raw: item };
    })
    .filter((option) => {
      if (!option.label || seen.has(option.label)) return false;
      seen.add(option.label);
      return true;
    });
}

export function getQuestionMarkdown(q: any): string {
  if (!q) return "";
  const markdown = q.manualMarkdown || q.stemMarkdown || q.stem || q.content || "";
  const images = ensureQuestionImageLabels(getQuestionImages(q));
  const normalizedMarkdown = normalizeTasksEnvironment(normalizeQuestionImageRefsInMarkdown(markdown, images));
  const parsedManual = splitChoiceOptionsFromMarkdown(normalizedMarkdown, q.type || "");
  const rawOptions = /\\task\b/.test(normalizedMarkdown) && parsedManual.options.length >= 2
    ? parsedManual.options
    : q.options;
  const options = choiceOptionsWithTrustedPlacements(q, images, rawOptions);
  return withEditableChoiceOptions(markdown, options, images);
}

function choiceOptionsWithTrustedPlacements(
  question: any,
  images: QuestionImage[],
  rawOptions: unknown = question?.options,
): QuestionOption[] {
  type TrustedOptionPlacement = {
    image: QuestionImage;
    imageIndex: number;
    optionLabel: string;
    order: number;
  };
  const options = normalizeQuestionOptions(rawOptions, images);
  const placements = Array.isArray(question?.imagePlacements) ? question.imagePlacements : [];
  if (question?.type !== "choice" || options.length < 2 || images.length === 0 || placements.length === 0) {
    return options;
  }

  const candidates: TrustedOptionPlacement[] = placements
    .map((placement: any, fallbackOrder: number): TrustedOptionPlacement | null => {
      const target = placement?.target && typeof placement.target === "object" ? placement.target : {};
      const optionLabel = String(target.optionLabel || "").trim().toUpperCase();
      const confidence = Number(placement?.inference?.confidence || 0);
      const reviewStatus = String(placement?.reviewStatus || "").trim();
      const isTrusted = ["confirmed", "overridden"].includes(reviewStatus)
        || (reviewStatus !== "needs_review" && confidence >= 0.95);
      const imageIndex = images.findIndex((image, index) => imageRefMatches(String(placement?.imageId || ""), image, index));
      if (!isTrusted || target.kind !== "option" || !optionLabel || imageIndex < 0) return null;
      return {
        image: images[imageIndex],
        imageIndex,
        optionLabel,
        order: Number.isInteger(placement?.order) ? Number(placement.order) : fallbackOrder,
      };
    })
    .filter((item: TrustedOptionPlacement | null): item is TrustedOptionPlacement => item !== null);
  const candidatesByImage = new Map<number, TrustedOptionPlacement[]>();
  candidates.forEach((candidate) => {
    const grouped = candidatesByImage.get(candidate.imageIndex) || [];
    grouped.push(candidate);
    candidatesByImage.set(candidate.imageIndex, grouped);
  });
  const optionLabels = new Set(options.map((option) => option.label));
  const trusted = Array.from(candidatesByImage.values())
    .filter((group) => group.length === 1 && optionLabels.has(group[0].optionLabel))
    .map((group) => group[0])
    .sort((left: TrustedOptionPlacement, right: TrustedOptionPlacement) => left.order - right.order);
  if (trusted.length === 0) return options;

  const trustedImages = trusted.map((item) => item.image);
  const tokensByLabel = new Map<string, string[]>();
  trusted.forEach(({ image, imageIndex, optionLabel }) => {
    const tokens = tokensByLabel.get(optionLabel) || [];
    const token = `![](${getQuestionImageLabel(image, imageIndex)})`;
    if (!tokens.includes(token)) tokens.push(token);
    tokensByLabel.set(optionLabel, tokens);
  });

  return options.map((option) => {
    const text = atomicTaskOptionContent(removeQuestionImageRefsFromMarkdown(option.content, trustedImages));
    const content = [...(tokensByLabel.get(option.label) || []), text].filter(Boolean).join(" ");
    return { ...option, content, contentMarkdown: content };
  });
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
  const images = getQuestionImages(sub);
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
    images,
    options: normalizeQuestionOptions(sub?.options, images),
    contextMatched: Boolean(sub?.contextMatched ?? sub?.aiMetadata?.contextMatched),
    answerEvidence: String(sub?.answerEvidence ?? sub?.aiMetadata?.answerEvidence ?? ""),
    analysisEvidence: String(sub?.analysisEvidence ?? sub?.aiMetadata?.analysisEvidence ?? ""),
    warnings: Array.isArray(sub?.warnings) ? sub.warnings : Array.isArray(sub?.aiMetadata?.warnings) ? sub.aiMetadata.warnings : [],
    aiMetadata: sub?.aiMetadata,
    imagePlacements: Array.isArray(sub?.imagePlacements) ? sub.imagePlacements : [],
  };
}

export function updateSubQuestionImages(sub: any, nextImages: QuestionImage[]): any {
  const previousImages = ensureQuestionImageLabels(Array.isArray(sub?.images) ? sub.images : []);
  const labeledNextImages = ensureQuestionImageLabels(nextImages, previousImages);
  const removedImages = getRemovedQuestionImages(previousImages, labeledNextImages);
  const answer = removeQuestionImageRefsFromMarkdown(sub?.answer || "", removedImages);
  const analysis = removeQuestionImageRefsFromMarkdown(sub?.analysis || "", removedImages);
  const options = removeQuestionImageRefsFromOptions(sub?.options, removedImages);
  const markdown = appendNewImageRefs(
    removeQuestionImageRefsFromMarkdown(sub?.markdown || "", removedImages),
    previousImages,
    labeledNextImages,
    [answer, analysis, ...options.map((option) => option.content)],
  );
  const removedKeys = new Set(
    removedImages.flatMap((image, index) =>
      [getImageKey(image), image.url, image.path, image.name, getQuestionImageLabel(image, index)]
        .map((value) => String(value || "").trim())
        .filter(Boolean),
    ),
  );
  const imagePlacements = Array.isArray(sub?.imagePlacements)
    ? sub.imagePlacements.filter((placement: any) => {
        const key = String(
          placement?.imageKey || placement?.storageFileId || placement?.imageId || placement?.url || placement?.path || placement?.name || placement?.label || "",
        ).trim();
        return !key || !removedKeys.has(key);
      })
    : [];

  return {
    ...sub,
    markdown,
    answer,
    analysis,
    options,
    images: labeledNextImages,
    imagePlacements,
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
  if (Array.isArray(incoming?.options) && incoming.options.length > 0) {
    next.options = normalizeQuestionOptions(incoming.options, next.images);
  }
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

export function normalizeQuestionOptions(value: unknown, images: QuestionImage[] = []): QuestionOption[] {
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
    const rawContent = String(
      typeof raw === "object" && raw
        ? raw.contentMarkdown ?? raw.markdown ?? raw.text ?? raw.content ?? raw.value ?? ""
        : raw ?? "",
    ).trim();
    const content = normalizeQuestionImageRefsInMarkdown(rawContent, images).trim();
    if (!label || !content || seen.has(label)) return;
    seen.add(label);
    options.push({ label, content, contentMarkdown: content, raw: item });
  });
  return options;
}

export function serializeQuestionOptions(value: unknown, images: QuestionImage[] = []): QuestionOption[] {
  return normalizeQuestionOptions(value, images).map((option) => ({
    label: option.label,
    content: option.content,
    contentMarkdown: option.contentMarkdown || option.content,
  }));
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
  const match = /(?:\s*!\[[^\]]*]\s*\([^)]+\)\s*)+$/.exec(String(content || ""));
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

function atomicTaskOptionContent(value: string) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

type TextSpan = [start: number, end: number];

type GluedTasksLabelMarker = {
  label: string;
  markerStart: number;
  markerEnd: number;
};

const GLUED_TASKS_IMAGE_ALT_MAX_LENGTH = 256;
const GLUED_TASKS_IMAGE_DESTINATION_MAX_LENGTH = 2048;
const GLUED_TASKS_IMAGE_WHITESPACE_MAX_LENGTH = 256;
const GLUED_TASKS_LABEL_MARKER_PATTERNS: Array<{ pattern: RegExp; requiresImageCheck: boolean }> = [
  { pattern: /(^|\s)([A-H])[.．、:：](?=\s*\S)/g, requiresImageCheck: false },
  { pattern: /(^|\s)([A-H])(?=\s+\$(?=[^$\r\n]*\$))/g, requiresImageCheck: false },
  {
    pattern: new RegExp(`(^|\\s)([A-H])(?=\\s{1,${GLUED_TASKS_IMAGE_WHITESPACE_MAX_LENGTH}}!\\[)`, "g"),
    requiresImageCheck: true,
  },
];

function isEscapedMathDelimiter(content: string, position: number) {
  let backslashes = 0;
  while (position > 0 && content[position - 1] === "\\") {
    backslashes += 1;
    position -= 1;
  }
  return backslashes % 2 === 1;
}

function isSingleDollarDelimiter(content: string, position: number) {
  return (
    content[position] === "$"
    && !isEscapedMathDelimiter(content, position)
    && (position === 0 || content[position - 1] !== "$")
    && (position + 1 === content.length || content[position + 1] !== "$")
  );
}

function nextUnescapedDelimiter(content: string, delimiter: string, position: number) {
  let delimiterPosition = content.indexOf(delimiter, position);
  while (delimiterPosition >= 0) {
    if (!isEscapedMathDelimiter(content, delimiterPosition)) return delimiterPosition;
    delimiterPosition = content.indexOf(delimiter, delimiterPosition + 1);
  }
  return -1;
}

function nextSingleDollarDelimiter(content: string, position: number) {
  for (let delimiterPosition = position; delimiterPosition < content.length; delimiterPosition += 1) {
    if (isSingleDollarDelimiter(content, delimiterPosition)) return delimiterPosition;
  }
  return -1;
}

function mathSpans(content: string): { spans: TextSpan[]; hasUnclosedDelimiter: boolean } {
  const spans: TextSpan[] = [];
  let position = 0;
  while (position < content.length) {
    if (content.startsWith("$$", position) && !isEscapedMathDelimiter(content, position)) {
      const end = nextUnescapedDelimiter(content, "$$", position + 2);
      if (end < 0) return { spans, hasUnclosedDelimiter: true };
      spans.push([position, end + 2]);
      position = end + 2;
      continue;
    }
    if (isSingleDollarDelimiter(content, position)) {
      const end = nextSingleDollarDelimiter(content, position + 1);
      if (end < 0) return { spans, hasUnclosedDelimiter: true };
      spans.push([position, end + 1]);
      position = end + 1;
      continue;
    }
    if (content.startsWith("\\(", position) && !isEscapedMathDelimiter(content, position)) {
      const end = nextUnescapedDelimiter(content, "\\)", position + 2);
      if (end < 0) return { spans, hasUnclosedDelimiter: true };
      spans.push([position, end + 2]);
      position = end + 2;
      continue;
    }
    if (content.startsWith("\\[", position) && !isEscapedMathDelimiter(content, position)) {
      const end = nextUnescapedDelimiter(content, "\\]", position + 2);
      if (end < 0) return { spans, hasUnclosedDelimiter: true };
      spans.push([position, end + 2]);
      position = end + 2;
      continue;
    }
    position += 1;
  }
  return { spans, hasUnclosedDelimiter: false };
}

function skipBoundedGluedTasksImageWhitespace(content: string, start: number) {
  let position = start;
  const limit = Math.min(start + GLUED_TASKS_IMAGE_WHITESPACE_MAX_LENGTH, content.length);
  while (position < limit && /\s/.test(content[position])) position += 1;
  return position;
}

function boundedGluedTasksImageSpan(content: string, start: number): TextSpan | null {
  let position = skipBoundedGluedTasksImageWhitespace(content, start);
  if (!content.startsWith("![", position)) return null;

  const imageStart = position;
  const altStart = position + 2;
  const altLimit = Math.min(content.length, altStart + GLUED_TASKS_IMAGE_ALT_MAX_LENGTH + 1);
  let altEnd = -1;
  for (position = altStart; position < altLimit; position += 1) {
    if (content[position] === "]" && !isEscapedMathDelimiter(content, position)) {
      altEnd = position;
      break;
    }
  }
  if (altEnd < 0) return null;

  position = skipBoundedGluedTasksImageWhitespace(content, altEnd + 1);
  if (content[position] !== "(") return null;

  const destinationStart = skipBoundedGluedTasksImageWhitespace(content, position + 1);
  const destinationLimit = Math.min(content.length, destinationStart + GLUED_TASKS_IMAGE_DESTINATION_MAX_LENGTH + 1);
  let nestedParentheses = 0;
  for (position = destinationStart; position < destinationLimit; position += 1) {
    const char = content[position];
    if (char === "\r" || char === "\n") return null;
    if (char === "(" && !isEscapedMathDelimiter(content, position)) {
      nestedParentheses += 1;
    } else if (char === ")" && !isEscapedMathDelimiter(content, position)) {
      if (nestedParentheses === 0) return position > destinationStart ? [imageStart, position + 1] : null;
      nestedParentheses -= 1;
    }
  }
  return null;
}

function boundedGluedTasksImageSpans(content: string): TextSpan[] {
  const spans: TextSpan[] = [];
  let cursor = 0;
  while (true) {
    const imageStart = content.indexOf("![", cursor);
    if (imageStart < 0) return spans;
    const span = boundedGluedTasksImageSpan(content, imageStart);
    if (span) {
      spans.push(span);
      cursor = span[1];
    } else {
      cursor = imageStart + 2;
    }
  }
}

function isMathPosition(spans: TextSpan[], position: number) {
  return spans.some(([start, end]) => start <= position && position < end);
}

function lowerBound(values: number[], value: number) {
  let start = 0;
  let end = values.length;
  while (start < end) {
    const middle = Math.floor((start + end) / 2);
    if (values[middle] < value) start = middle + 1;
    else end = middle;
  }
  return start;
}

function isImagePosition(spans: TextSpan[], spanStarts: number[], position: number) {
  const spanIndex = lowerBound(spanStarts, position + 1) - 1;
  return spanIndex >= 0 && position < spans[spanIndex][1];
}

function isPointLabelPrefix(content: string, position: number) {
  while (position > 0 && /\s/.test(content[position - 1])) position -= 1;
  return position > 0 && content[position - 1] === "点";
}

function nextGluedTasksLabelMarker(
  content: string,
  start: number,
  expectedLabel: string,
  spans: TextSpan[],
  imageSpans: TextSpan[],
  imageSpanStarts: number[],
): GluedTasksLabelMarker | null {
  const markers: Array<GluedTasksLabelMarker & { requiresImageCheck: boolean }> = [];
  for (const { pattern, requiresImageCheck } of GLUED_TASKS_LABEL_MARKER_PATTERNS) {
    pattern.lastIndex = start;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(content)) !== null) {
      const prefixLength = String(match[1] || "").length;
      markers.push({
        label: String(match[2] || ""),
        markerStart: match.index + prefixLength,
        markerEnd: match.index + match[0].length,
        requiresImageCheck,
      });
    }
  }
  markers.sort((left, right) => left.markerStart - right.markerStart || left.markerEnd - right.markerEnd);

  for (const marker of markers) {
    if (
      isMathPosition(spans, marker.markerStart)
      || isImagePosition(imageSpans, imageSpanStarts, marker.markerStart)
      || isPointLabelPrefix(content, marker.markerStart)
    ) {
      continue;
    }
    if (marker.requiresImageCheck) {
      const imageStart = skipBoundedGluedTasksImageWhitespace(content, marker.markerEnd);
      const imageIndex = lowerBound(imageSpanStarts, imageStart);
      if (imageSpanStarts[imageIndex] !== imageStart) continue;
    }
    if (marker.label < expectedLabel) continue;
    return marker;
  }
  return null;
}

function recoverGluedTaskParts(taskParts: string[]): { taskParts: string[]; didRecover: boolean } {
  if (taskParts.length < 2 || taskParts.some((part) => !part.trim())) return { taskParts, didRecover: false };

  const taskMathSpans = taskParts.map(mathSpans);
  const taskImageSpans = taskParts.map(boundedGluedTasksImageSpans);
  const taskImageSpanStarts = taskImageSpans.map((spans) => spans.map(([start]) => start));
  if (taskMathSpans.some(({ hasUnclosedDelimiter }) => hasUnclosedDelimiter)) return { taskParts, didRecover: false };

  const recovered: string[] = [];
  let didRecover = false;
  taskParts.forEach((content, index) => {
    const expectedLabel = String.fromCharCode("A".charCodeAt(0) + recovered.length + 1);
    if (!content.trim() || expectedLabel > "H") {
      recovered.push(content);
      return;
    }

    const markers: TextSpan[] = [];
    let cursor = 0;
    let nextExpectedLabel = expectedLabel;
    while (nextExpectedLabel <= "H") {
      const marker = nextGluedTasksLabelMarker(
        content,
        cursor,
        nextExpectedLabel,
        taskMathSpans[index].spans,
        taskImageSpans[index],
        taskImageSpanStarts[index],
      );
      if (!marker || marker.label !== nextExpectedLabel) break;
      markers.push([marker.markerStart, marker.markerEnd]);
      cursor = marker.markerEnd;
      nextExpectedLabel = nextChoiceLabel(nextExpectedLabel);
    }

    if (markers.length < 2) {
      recovered.push(content);
      return;
    }

    const splitParts = [content.slice(0, markers[0][0])];
    for (let markerIndex = 0; markerIndex < markers.length - 1; markerIndex += 1) {
      splitParts.push(content.slice(markers[markerIndex][1], markers[markerIndex + 1][0]));
    }
    splitParts.push(content.slice(markers[markers.length - 1][1]));
    if (splitParts.some((part) => !part.trim())) {
      recovered.push(content);
      return;
    }
    recovered.push(...splitParts);
    didRecover = true;
  });
  return { taskParts: recovered, didRecover };
}

export function withEditableChoiceOptions(markdown: string, rawOptions: unknown, images: QuestionImage[] = []): string {
  const normalizedMarkdown = normalizeTasksEnvironment(normalizeQuestionImageRefsInMarkdown(markdown, images)).trim();
  const options = normalizeQuestionOptions(rawOptions, images);
  if (options.length === 0) return normalizedMarkdown;
  const parsed = splitChoiceOptionsFromMarkdown(normalizedMarkdown, "choice");
  const stemMarkdown = parsed.options.length > 0 ? parsed.stemMarkdown : normalizedMarkdown;

  const optionBlock = [
    "",
    `\\begin{tasks}(${tasksColumnCount(options.length)})`,
    ...options.map((option) => `\\task ${atomicTaskOptionContent(option.contentMarkdown || option.content)}`),
    "\\end{tasks}",
  ].join("\n");
  return `${stemMarkdown}${stemMarkdown ? "\n" : ""}${optionBlock}`.trim();
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
  const taskParts = body
    .split(/\\task\b/)
    .slice(1);
  const recovery = match ? recoverGluedTaskParts(taskParts) : { taskParts, didRecover: false };
  const options = recovery.taskParts
    .map((content) => (recovery.didRecover ? content.trim() : cleanOptionText(content)))
    .filter(Boolean)
    .map((content, index) => ({
      label: String.fromCharCode(65 + index),
      content,
      contentMarkdown: content,
    }));
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
  images: QuestionImage[] = [],
  preferFallbackOptions = false,
): { stemMarkdown: string; options: QuestionOption[] } {
  const normalizedMarkdown = normalizeQuestionImageRefsInMarkdown(markdown, images);
  const parsed = splitChoiceOptionsFromMarkdown(normalizedMarkdown, questionType);
  const normalizedFallbackOptions =
    questionType === "choice"
      ? normalizeQuestionOptions(fallbackOptions, images)
      : [];
  if (preferFallbackOptions && normalizedFallbackOptions.length > 0) {
    return {
      stemMarkdown: parsed.options.length > 0 ? parsed.stemMarkdown : String(normalizedMarkdown || "").trim(),
      options: normalizedFallbackOptions,
    };
  }
  if (parsed.options.length > 0) {
    const parsedOptions = normalizeQuestionOptions(parsed.options, images);
    return {
      stemMarkdown: parsed.stemMarkdown,
      options: parsedOptions,
    };
  }
  return {
    stemMarkdown: String(normalizedMarkdown || "").trim(),
    options: normalizedFallbackOptions,
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
