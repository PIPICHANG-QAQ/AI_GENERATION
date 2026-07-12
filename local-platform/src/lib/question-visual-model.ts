import {
  ensureQuestionImageLabels,
  getImageKey,
  getQuestionImageLabel,
  getQuestionImages,
  getQuestionMarkdownParts,
  normalizeQuestionOptions,
  type QuestionImage,
  type QuestionOption,
} from "./question";

export type QuestionVisualIssue = {
  code: string;
  message: string;
  imageId?: string;
  optionLabel?: string;
};

export type QuestionVisualModel = {
  stemMarkdown: string;
  options: QuestionOption[];
  images: QuestionImage[];
  issues: QuestionVisualIssue[];
};

type RawPlacement = {
  imageId?: string;
  target?: string | { kind?: string; optionLabel?: string };
  optionLabel?: string;
};

const IMAGE_REF_RE = /!\[[^\]]*]\s*\(\s*<?([^>)\s]+)>?(?:\s+["'][^)]*["'])?\s*\)/g;

export function buildQuestionVisualModel(question: any): QuestionVisualModel {
  const images = deduplicateImages(ensureQuestionImageLabels(getQuestionImages(question)));
  const rawMarkdown = String(
    question?.manualMarkdown || question?.stemMarkdown || question?.stem || question?.content || "",
  );
  const parsed = getQuestionMarkdownParts(rawMarkdown, question?.type || "", [], images);
  const structured = normalizeQuestionOptions(question?.options, images);
  const options = structured.length > 0
    ? mergeOptionImageRefs(structured, parsed.options)
    : parsed.options;
  const placements = Array.isArray(question?.imagePlacements)
    ? question.imagePlacements.filter((item: unknown): item is RawPlacement => !!item && typeof item === "object")
    : [];
  const issues = visualPlacementIssues(options, images, placements);
  const stemMarkdown = appendConfirmedStemImages(parsed.stemMarkdown, options, images, placements);
  return { stemMarkdown, options, images, issues };
}

export function resolveVisualImage(ref: string, images: QuestionImage[] = []): string {
  const image = findVisualImage(ref, ensureQuestionImageLabels(images));
  return String(image?.url || image?.path || "").trim();
}

function deduplicateImages(images: QuestionImage[]): QuestionImage[] {
  const identities = new Set<string>();
  return images.filter((image) => {
    const values = [
      image.storageFileId,
      image.imageId,
      image.id,
      image.url,
      image.path,
      getImageKey(image),
    ]
      .map(refComparable)
      .filter(Boolean);
    if (values.some((value) => identities.has(value))) return false;
    values.forEach((value) => identities.add(value));
    return true;
  });
}

function mergeOptionImageRefs(structured: QuestionOption[], parsed: QuestionOption[]): QuestionOption[] {
  const parsedByLabel = new Map(parsed.map((option) => [option.label, option]));
  return structured.map((option) => {
    const content = option.contentMarkdown || option.content || "";
    const existingRefs = new Set(imageRefs(content).map(refComparable));
    const parsedContent = parsedByLabel.get(option.label)?.contentMarkdown
      || parsedByLabel.get(option.label)?.content
      || "";
    const missingTokens = imageTokens(parsedContent).filter(
      (token) => !existingRefs.has(refComparable(token.ref)),
    );
    const merged = missingTokens.length > 0
      ? `${missingTokens.map((token) => token.markdown).join(" ")} ${content}`.trim()
      : content;
    return { ...option, content: merged, contentMarkdown: merged };
  });
}

function visualPlacementIssues(
  options: QuestionOption[],
  images: QuestionImage[],
  placements: RawPlacement[],
): QuestionVisualIssue[] {
  const issues: QuestionVisualIssue[] = [];
  const placementByImage = new Map(
    placements.map((placement) => [String(placement.imageId || ""), placement]),
  );
  options.forEach((option) => {
    imageRefs(option.contentMarkdown || option.content).forEach((ref) => {
      const image = findVisualImage(ref, images);
      if (!image) {
        issues.push({
          code: "unresolved-image-ref",
          message: `选项 ${option.label} 的图片引用无法解析：${ref}`,
          optionLabel: option.label,
        });
        return;
      }
      const imageId = String(image.imageId || image.id || getImageKey(image));
      const placement = placementByImage.get(imageId);
      const target = placementTarget(placement);
      if (target.kind === "option" && target.optionLabel && target.optionLabel !== option.label) {
        issues.push({
          code: "placement-conflict",
          message: `图片 ${getQuestionImageLabel(image)} 在选项 ${option.label} 中显示，但归属记录指向选项 ${target.optionLabel}`,
          imageId,
          optionLabel: option.label,
        });
      }
    });
  });
  placements.forEach((placement) => {
    const target = placementTarget(placement);
    if (target.kind === "unassigned") {
      issues.push({
        code: "unassigned-image",
        message: "存在未归属题图，请人工确认属于题干还是选项",
        imageId: String(placement.imageId || ""),
      });
    }
  });
  return issues;
}

function appendConfirmedStemImages(
  stemMarkdown: string,
  options: QuestionOption[],
  images: QuestionImage[],
  placements: RawPlacement[],
): string {
  const allText = [stemMarkdown, ...options.map((option) => option.contentMarkdown || option.content)].join("\n");
  const refs = new Set(imageRefs(allText).map(refComparable));
  const additions: string[] = [];
  placements.forEach((placement) => {
    const target = placementTarget(placement);
    if (!["stem", "shared"].includes(target.kind)) return;
    const image = images.find((item) => String(item.imageId || item.id || getImageKey(item)) === String(placement.imageId || ""));
    if (!image) return;
    const label = getQuestionImageLabel(image, images.indexOf(image));
    if (refs.has(refComparable(label))) return;
    refs.add(refComparable(label));
    additions.push(`![](${label})`);
  });
  return [stemMarkdown, ...additions].filter(Boolean).join("\n\n").trim();
}

function placementTarget(placement?: RawPlacement): { kind: string; optionLabel?: string } {
  if (!placement) return { kind: "" };
  if (typeof placement.target === "object" && placement.target) {
    return {
      kind: String(placement.target.kind || ""),
      optionLabel: String(placement.target.optionLabel || placement.optionLabel || "").toUpperCase() || undefined,
    };
  }
  return {
    kind: String(placement.target || ""),
    optionLabel: String(placement.optionLabel || "").toUpperCase() || undefined,
  };
}

function findVisualImage(ref: string, images: QuestionImage[]): QuestionImage | undefined {
  const target = refComparable(ref);
  return images.find((image, index) => {
    const label = getQuestionImageLabel(image, index);
    const values = [
      label,
      image.label,
      image.refLabel,
      image.url,
      image.path,
      image.name,
      getImageKey(image),
    ]
      .map(refComparable)
      .filter(Boolean);
    return values.some((value) => value === target || value.endsWith(`/${target}`) || target.endsWith(`/${value}`));
  });
}

function imageRefs(markdown: string): string[] {
  return imageTokens(markdown).map((token) => token.ref);
}

function imageTokens(markdown: string): Array<{ ref: string; markdown: string }> {
  const tokens: Array<{ ref: string; markdown: string }> = [];
  const regex = new RegExp(IMAGE_REF_RE.source, "g");
  let match: RegExpExecArray | null;
  while ((match = regex.exec(String(markdown || ""))) !== null) {
    tokens.push({ ref: match[1], markdown: match[0] });
  }
  return tokens;
}

function refComparable(value: unknown): string {
  let text = String(value || "").trim().replace(/^<|>$/g, "");
  try {
    text = decodeURIComponent(text);
  } catch {
    // Keep undecodable OCR paths unchanged.
  }
  return text.replace(/\\/g, "/").replace(/^\.\//, "").replace(/[?#].*$/, "").toLowerCase();
}
