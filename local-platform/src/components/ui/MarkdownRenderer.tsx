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
        <span className="not-prose block max-w-full my-2">
          <img
            {...props}
            src={resolvedSrc}
            alt={alt || "图片"}
            className="max-w-full max-h-[420px] h-auto rounded-md border border-border/60 bg-card cursor-pointer hover:opacity-90 block object-contain"
            onClick={() => resolvedSrc && window.open(resolvedSrc, "_blank")}
            onError={(e) => {
              const target = e.target as HTMLImageElement;
              target.style.display = "none";
              const span = target.nextElementSibling as HTMLSpanElement;
              if (span) span.style.display = "inline-block";
            }}
          />
          <span className="hidden mt-2 text-xs text-destructive bg-destructive/10 px-2 py-1 rounded-md border border-destructive/20">
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
      className="block max-w-full max-h-64 h-auto rounded-md cursor-pointer hover:opacity-90 object-contain border border-border"
      onClick={() => window.open(src, "_blank")}
      onError={() => setFailed(true)}
    />
  );
}

type Segment =
  | { type: "md"; value: string }
  | { type: "html-table"; value: string }
  | { type: "tasks"; options: string[] };

type HtmlTableCell = {
  content: string;
  rowSpan: number;
  colSpan: number;
  header: boolean;
};

type HtmlTableModel = {
  rows: HtmlTableCell[][];
};

function positiveInteger(value: string | null | undefined) {
  const parsed = Number.parseInt(value || "", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
}

function cellText(cell: Element) {
  const clone = cell.cloneNode(true) as HTMLElement;
  clone.querySelectorAll("br").forEach((br) => br.replaceWith("\n"));
  return (clone.textContent || "").replace(/\u00a0/g, " ").trim();
}

function parseHtmlTable(html: string): HtmlTableModel | null {
  if (typeof DOMParser === "undefined") return null;
  const doc = new DOMParser().parseFromString(html, "text/html");
  const table = doc.querySelector("table");
  if (!table) return null;
  const rows = Array.from(table.querySelectorAll("tr"))
    .map((row) =>
      Array.from(row.children)
        .filter((child) => ["TD", "TH"].includes(child.tagName))
        .map((cell) => ({
          content: cellText(cell),
          rowSpan: positiveInteger(cell.getAttribute("rowspan")),
          colSpan: positiveInteger(cell.getAttribute("colspan")),
          header: cell.tagName === "TH",
        }))
    )
    .filter((row) => row.length > 0);
  return rows.length > 0 ? { rows } : null;
}

function splitHtmlTables(raw: string): Segment[] {
  const regex = /<table\b[\s\S]*?<\/table>/gi;
  const segments: Segment[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(raw)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ type: "md", value: raw.slice(lastIndex, match.index) });
    }
    segments.push({ type: "html-table", value: match[0] });
    lastIndex = regex.lastIndex;
  }
  if (lastIndex < raw.length) {
    segments.push({ type: "md", value: raw.slice(lastIndex) });
  }
  return segments.length > 0 ? segments : [{ type: "md", value: raw }];
}

function splitTasks(raw: string): Segment[] {
  const normalized = raw.replace(/\\(begin|end)\{t+asks\}/gi, (_match, kind) => `\\${kind}{tasks}`);
  const regex = /\\begin\{tasks\}(?:\([^)]+\)|\[[^\]]*\])?([\s\S]*?)\\end\{tasks\}/g;
  const segments: Segment[] = [];
  let lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = regex.exec(normalized)) !== null) {
    if (m.index > lastIndex) {
      segments.push(...splitHtmlTables(normalized.slice(lastIndex, m.index)));
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
    segments.push(...splitHtmlTables(normalized.slice(lastIndex)));
  }
  if (segments.length === 0) segments.push({ type: "md", value: normalized });
  return segments;
}

function HtmlTable({ html, images }: { html: string; images?: QuestionImage[] }) {
  const table = React.useMemo(() => parseHtmlTable(html), [html]);
  if (!table) return <Md content={html} images={images} />;
  return (
    <div className="not-prose my-3 max-w-full overflow-x-auto rounded-md border border-border/70 bg-card">
      <table className="w-full min-w-max border-collapse text-sm">
        <tbody>
          {table.rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => {
                const Tag = cell.header ? "th" : "td";
                return (
                  <Tag
                    key={`${rowIndex}-${cellIndex}`}
                    rowSpan={cell.rowSpan}
                    colSpan={cell.colSpan}
                    className="border border-border/80 px-3 py-2 text-center align-middle text-foreground [&_p]:m-0"
                  >
                    {cell.content ? <Md content={cell.content} images={images} /> : <span className="text-muted-foreground">____</span>}
                  </Tag>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
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
  const choiceParts = getQuestionMarkdownParts(raw, questionType || "", options, imageList);
  const shouldUseChoiceParts = choiceParts.options.length > 0 && (questionType === "choice" || raw.includes("\\task"));
  const renderContent = shouldUseChoiceParts ? choiceParts.stemMarkdown : choiceParts.stemMarkdown || raw;
  const segments = splitTasks(renderContent);
  const hasRenderedTaskOptions = segments.some((seg) => seg.type === "tasks" && seg.options.length > 0);
  const unreferenced = showUnreferenced
    ? getUnreferencedImageRefs(imageList, [renderContent, ...choiceParts.options.map((option) => option.content), ...siblingContent])
        .map((ref) => imageList[ref.index - 1])
        .filter(Boolean)
    : [];

  return (
    <div className="prose prose-sm max-w-none break-words [&_.katex-display]:overflow-x-auto [&_.katex-display]:overflow-y-hidden">
      {segments.map((seg, i) =>
        seg.type === "md" ? (
          <Md key={i} content={seg.value} images={imageList} />
        ) : seg.type === "html-table" ? (
          <HtmlTable key={i} html={seg.value} images={imageList} />
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
      {shouldUseChoiceParts && !hasRenderedTaskOptions && <OptionGrid options={choiceParts.options} images={imageList} />}
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
