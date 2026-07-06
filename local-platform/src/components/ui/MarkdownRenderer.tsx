import React from "react";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import "katex/dist/katex.min.css";
import {
  getUnreferencedImageRefs,
  getQuestionMarkdownParts,
  questionImageSrc,
  resolveImageSrc,
  type QuestionImage,
  type QuestionOption,
} from "@/lib/question";

function markdownComponents(images: QuestionImage[] = []) {
  return {
    img: ({ node, src, alt, ...props }: any) => {
      const resolvedSrc = questionImageSrc(resolveImageSrc(src, images));
      const label = alt || src?.split("/").pop() || "未知图片";
      return (
        <span className="inline-block max-w-full">
          <img
            {...props}
            src={resolvedSrc}
            alt={alt || "图片"}
            className="max-w-full h-auto rounded-md cursor-pointer hover:opacity-90 inline-block object-contain"
            onClick={() => resolvedSrc && window.open(resolvedSrc, "_blank")}
            onError={(e) => {
              const target = e.target as HTMLImageElement;
              target.style.display = "none";
              const span = target.nextElementSibling as HTMLSpanElement;
              if (span) span.style.display = "inline-block";
            }}
          />
          <span className="hidden text-xs text-destructive bg-destructive/10 px-2 py-1 rounded-md border border-destructive/20">
            图片加载失败: {label}
          </span>
        </span>
      );
    },
  };
}

function Md({ content, images }: { content: string; images?: QuestionImage[] }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkMath, remarkGfm]}
      rehypePlugins={[rehypeKatex]}
      components={markdownComponents(images)}
    >
      {content}
    </ReactMarkdown>
  );
}

function OptionGrid({ options, images }: { options: QuestionOption[]; images?: QuestionImage[] }) {
  if (options.length === 0) return null;
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 my-2 not-prose">
      {options.map((opt, index) => (
        <div
          key={`${opt.label || index}-${index}`}
          className="flex gap-2 items-start border border-border rounded-md px-3 py-2 bg-card"
        >
          <span className="font-semibold text-foreground shrink-0">
            {opt.label || String.fromCharCode(65 + index)}.
          </span>
          <div className="min-w-0 flex-1">
            <Md content={opt.contentMarkdown || opt.content || ""} images={images} />
          </div>
        </div>
      ))}
    </div>
  );
}

function ImageFallback({ img }: { img: QuestionImage }) {
  const [failed, setFailed] = React.useState(false);
  const src = questionImageSrc(img.url || img.path);
  if (failed || !src) {
    return (
      <span className="text-xs text-destructive bg-destructive/10 px-2 py-1 rounded-md border border-destructive/20">
        图片加载失败: {img.name || src || "未知图片"}
      </span>
    );
  }
  return (
    <img
      src={src}
      alt={img.name || "题图"}
      className="max-w-full max-h-64 h-auto rounded-md cursor-pointer hover:opacity-90 object-contain border border-border"
      onClick={() => window.open(src, "_blank")}
      onError={() => setFailed(true)}
    />
  );
}

type Segment =
  | { type: "md"; value: string }
  | { type: "tasks"; options: string[] };

function splitTasks(raw: string): Segment[] {
  const normalized = raw.replace(/\\(begin|end)\{t+asks\}/gi, (_match, kind) => `\\${kind}{tasks}`);
  const regex = /\\begin\{tasks\}(?:\([^)]+\)|\[[^\]]*\])?([\s\S]*?)\\end\{tasks\}/g;
  const segments: Segment[] = [];
  let lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = regex.exec(normalized)) !== null) {
    if (m.index > lastIndex) {
      segments.push({ type: "md", value: normalized.slice(lastIndex, m.index) });
    }
    const inner = m[1] || "";
    const options = inner
      .split("\\task")
      .map((s) => s.trim())
      .filter(Boolean);
    segments.push({ type: "tasks", options });
    lastIndex = regex.lastIndex;
  }
  if (lastIndex < normalized.length) {
    segments.push({ type: "md", value: normalized.slice(lastIndex) });
  }
  if (segments.length === 0) segments.push({ type: "md", value: normalized });
  return segments;
}

export function MarkdownRenderer({
  content,
  images,
  questionType,
  options,
  siblingContent = [],
  showUnreferenced = false,
}: {
  content: string;
  images?: QuestionImage[];
  questionType?: string;
  options?: QuestionOption[] | unknown[];
  siblingContent?: string[];
  showUnreferenced?: boolean;
}) {
  const raw = content || "";
  const imageList = images || [];
  const choiceParts = getQuestionMarkdownParts(raw, questionType || "", options);
  const shouldUseChoiceParts = choiceParts.options.length > 0 && (questionType === "choice" || raw.includes("\\task"));
  const renderContent = shouldUseChoiceParts ? choiceParts.stemMarkdown : raw;
  const segments = splitTasks(renderContent);
  const unreferenced = showUnreferenced
    ? getUnreferencedImageRefs(imageList, [raw, ...siblingContent])
        .map((ref) => imageList[ref.index - 1])
        .filter(Boolean)
    : [];

  return (
    <div className="prose prose-sm max-w-none break-words [&_.katex-display]:overflow-x-auto [&_.katex-display]:overflow-y-hidden">
      {segments.map((seg, i) =>
        seg.type === "md" ? (
          <Md key={i} content={seg.value} images={imageList} />
        ) : (
          <OptionGrid
            key={i}
            images={imageList}
            options={seg.options.map((opt, j) => ({
              label: String.fromCharCode(65 + j),
              content: opt,
              contentMarkdown: opt,
            }))}
          />
        )
      )}
      {shouldUseChoiceParts && <OptionGrid options={choiceParts.options} images={imageList} />}
      {unreferenced.length > 0 && (
        <div className="flex flex-wrap gap-3 mt-3 not-prose">
          {unreferenced.map((img, i) => (
            <ImageFallback key={i} img={img} />
          ))}
        </div>
      )}
    </div>
  );
}
