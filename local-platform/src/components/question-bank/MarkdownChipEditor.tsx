import React from "react";
import { QUESTION_IMAGE_REF_MIME } from "@/lib/question";
import { cn } from "@/lib/utils";

const CHIP_MOVE_MIME = "application/x-question-image-ref-move";
const TOKEN_RE = /!\[([^\]\n]*)\]\(([^()\n]+)\)/g;
const CHIP_SRC_RE = /^(?:题图|图|#)?\s*\d+\s*$/;
const CHIP_CLASS =
  "inline-flex items-center align-baseline rounded border border-emerald-300 bg-emerald-100 text-emerald-700 px-1.5 mx-0.5 text-[11px] leading-5 font-medium select-none whitespace-nowrap";

type Segment =
  | { type: "text"; text: string }
  | { type: "chip"; alt: string; src: string };

function tokenOf(alt: string, src: string) {
  return `![${alt}](${src})`;
}

function parseSegments(value: string): Segment[] {
  const out: Segment[] = [];
  let last = 0;
  TOKEN_RE.lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = TOKEN_RE.exec(value))) {
    const [full, alt, src] = match;
    if (!CHIP_SRC_RE.test(src.trim())) continue;
    if (match.index > last) out.push({ type: "text", text: value.slice(last, match.index) });
    out.push({ type: "chip", alt, src: src.trim() });
    last = match.index + full.length;
  }

  if (last < value.length) out.push({ type: "text", text: value.slice(last) });
  return out;
}

function serializeNode(node: Node, skipBr: boolean): string {
  if (node.nodeType === Node.TEXT_NODE) return (node as Text).data;
  if (node.nodeType !== Node.ELEMENT_NODE) return "";

  const el = node as HTMLElement;
  if (el.dataset?.chip) {
    return tokenOf(el.dataset.alt ?? "", el.dataset.src ?? "");
  }
  if (el.nodeName === "BR") return skipBr ? "" : "\n";

  let out = "";
  el.childNodes.forEach((child) => {
    out += serializeNode(child, false);
  });
  return out;
}

export function MarkdownChipEditor({
  value,
  onChange,
  readOnly = false,
  placeholder,
  rows = 6,
  className,
  variant = "plain",
}: {
  editorId?: string;
  value: string;
  onChange: (next: string) => void;
  readOnly?: boolean;
  placeholder?: string;
  rows?: number;
  className?: string;
  variant?: "plain" | "source";
  onChipMove?: (token: string, fromChipIndex: number, fromEditorId: string) => void;
  onChipRemove?: (token: string, chipIndex: number, editorId: string) => void;
}) {
  const rootRef = React.useRef<HTMLDivElement | null>(null);
  const lastEmitted = React.useRef<string | null>(null);
  const composingRef = React.useRef(false);
  const editingRef = React.useRef(false);
  const draggingChipRef = React.useRef<HTMLElement | null>(null);
  const [dropActive, setDropActive] = React.useState(false);

  const buildChip = React.useCallback(
    (alt: string, src: string) => {
      const chip = document.createElement("span");
      chip.className = cn(CHIP_CLASS, readOnly ? "cursor-default" : "cursor-grab");
      chip.setAttribute("contenteditable", "false");
      chip.draggable = !readOnly;
      chip.dataset.chip = "1";
      chip.dataset.alt = alt;
      chip.dataset.src = src;
      chip.title = readOnly ? tokenOf(alt, src) : `${tokenOf(alt, src)} - 拖拽移动，双击编辑`;
      chip.textContent = src;
      return chip;
    },
    [readOnly],
  );

  const syncTrailingBreak = React.useCallback((endsWithNewline: boolean) => {
    const root = rootRef.current;
    if (!root) return;
    const last = root.lastChild;
    const isSentinel = !!last && last.nodeName === "BR";

    if (endsWithNewline && !isSentinel) {
      root.appendChild(document.createElement("br"));
    } else if (!endsWithNewline && isSentinel) {
      root.removeChild(last);
    }
  }, []);

  const serialize = React.useCallback(() => {
    const root = rootRef.current;
    if (!root) return "";
    let out = "";
    root.childNodes.forEach((node) => {
      out += serializeNode(node, node === root.lastChild);
    });
    return out;
  }, []);

  const render = React.useCallback(
    (next: string) => {
      const root = rootRef.current;
      if (!root) return;
      root.textContent = "";
      for (const segment of parseSegments(next)) {
        if (segment.type === "text") root.appendChild(document.createTextNode(segment.text));
        else root.appendChild(buildChip(segment.alt, segment.src));
      }
      syncTrailingBreak(next.endsWith("\n"));
    },
    [buildChip, syncTrailingBreak],
  );

  const emit = React.useCallback(() => {
    const next = serialize();
    syncTrailingBreak(next.endsWith("\n"));
    lastEmitted.current = next;
    onChange(next);
  }, [onChange, serialize, syncTrailingBreak]);

  React.useEffect(() => {
    if (composingRef.current || editingRef.current) return;
    if (value !== lastEmitted.current) {
      render(value);
      lastEmitted.current = value;
    }
  }, [value, render]);

  React.useEffect(() => {
    render(lastEmitted.current ?? value);
    // readOnly changes chip draggable/cursor state, so the DOM must be rebuilt.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readOnly]);

  const handleInput = () => {
    if (composingRef.current || editingRef.current) return;
    emit();
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (editingRef.current) return;
    if (event.key === "Enter") {
      event.preventDefault();
      document.execCommand("insertText", false, "\n");
    }
  };

  const handlePaste = (event: React.ClipboardEvent<HTMLDivElement>) => {
    if (editingRef.current) return;
    event.preventDefault();
    const text = event.clipboardData.getData("text/plain");
    if (text) document.execCommand("insertText", false, text);
  };

  const handleCopyOrCut = (event: React.ClipboardEvent<HTMLDivElement>, cut: boolean) => {
    if (editingRef.current) return;
    const root = rootRef.current;
    const selection = window.getSelection();
    if (!root || !selection || selection.rangeCount === 0 || selection.isCollapsed) return;

    const range = selection.getRangeAt(0);
    if (!root.contains(range.commonAncestorContainer)) return;

    let text = "";
    range.cloneContents().childNodes.forEach((node) => {
      text += serializeNode(node, false);
    });

    event.preventDefault();
    event.clipboardData.setData("text/plain", text);

    if (cut && !readOnly) {
      document.execCommand("delete");
    }
  };

  const handleBlur = (event: React.FocusEvent<HTMLDivElement>) => {
    const root = rootRef.current;
    if (!root || composingRef.current || editingRef.current) return;
    if (event.relatedTarget && root.contains(event.relatedTarget as Node)) return;

    const next = serialize();
    if (next !== lastEmitted.current) {
      lastEmitted.current = next;
      onChange(next);
    }

    const chipSegmentCount = parseSegments(next).filter((segment) => segment.type === "chip").length;
    const domChipCount = root.querySelectorAll("[data-chip]").length;
    if (chipSegmentCount !== domChipCount) render(next);
  };

  const startChipEdit = (chip: HTMLElement) => {
    if (readOnly || editingRef.current) return;
    editingRef.current = true;

    const originalSrc = chip.dataset.src ?? "";
    const alt = chip.dataset.alt ?? "";
    chip.textContent = "";
    chip.classList.remove("cursor-grab");
    chip.draggable = false;

    const input = document.createElement("input");
    input.value = originalSrc;
    input.size = Math.max(2, originalSrc.length);
    input.className =
      "bg-transparent outline-none border-none p-0 m-0 font-mono text-[11px] leading-5 text-emerald-700 w-auto";
    input.setAttribute("aria-label", "编辑图片引用");

    let done = false;
    const finish = (commit: boolean) => {
      if (done) return;
      done = true;
      editingRef.current = false;
      const nextSrc = commit ? input.value.trim().replace(/[()[\]\n\r!]/g, "") : originalSrc;

      if (commit && nextSrc === "") {
        chip.remove();
      } else {
        chip.dataset.src = nextSrc;
        chip.textContent = nextSrc;
        chip.title = `${tokenOf(alt, nextSrc)} - 拖拽移动，双击编辑`;
        chip.classList.add("cursor-grab");
        chip.draggable = true;
      }

      emit();
      rootRef.current?.focus();
    };

    input.addEventListener("keydown", (event) => {
      event.stopPropagation();
      if (event.key === "Enter") {
        event.preventDefault();
        finish(true);
      } else if (event.key === "Escape") {
        event.preventDefault();
        finish(false);
      }
    });
    input.addEventListener("input", (event) => {
      event.stopPropagation();
      input.size = Math.max(2, input.value.length);
    });
    input.addEventListener("blur", () => finish(true));
    chip.appendChild(input);
    input.focus();
    input.select();
  };

  const handleDoubleClick = (event: React.MouseEvent<HTMLDivElement>) => {
    const chip = (event.target as HTMLElement).closest?.("[data-chip]") as HTMLElement | null;
    if (!chip || !rootRef.current?.contains(chip)) return;
    event.preventDefault();
    startChipEdit(chip);
  };

  const handleDragStart = (event: React.DragEvent<HTMLDivElement>) => {
    const chip = (event.target as HTMLElement).closest?.("[data-chip]") as HTMLElement | null;
    if (!chip) return;
    if (readOnly || editingRef.current) {
      event.preventDefault();
      return;
    }

    const token = tokenOf(chip.dataset.alt ?? "", chip.dataset.src ?? "");
    event.dataTransfer.setData(QUESTION_IMAGE_REF_MIME, token);
    event.dataTransfer.setData(CHIP_MOVE_MIME, "1");
    event.dataTransfer.setData("text/plain", token);
    event.dataTransfer.effectAllowed = "copyMove";
    draggingChipRef.current = chip;
  };

  const handleDragEnd = (event: React.DragEvent<HTMLDivElement>) => {
    const chip = draggingChipRef.current;
    draggingChipRef.current = null;
    setDropActive(false);
    if (chip && event.dataTransfer.dropEffect === "move" && chip.isConnected) {
      chip.remove();
      emit();
    }
  };

  const handleDragOver = (event: React.DragEvent<HTMLDivElement>) => {
    if (readOnly) return;
    if (!event.dataTransfer.types.includes(QUESTION_IMAGE_REF_MIME)) return;

    const overChip = (event.target as HTMLElement).closest?.("[data-chip]");
    if (draggingChipRef.current && overChip === draggingChipRef.current) {
      setDropActive(false);
      return;
    }

    event.preventDefault();
    event.dataTransfer.dropEffect = event.dataTransfer.types.includes(CHIP_MOVE_MIME)
      ? "move"
      : "copy";
    if (!dropActive) setDropActive(true);
  };

  const handleDragLeave = (event: React.DragEvent<HTMLDivElement>) => {
    if (event.currentTarget.contains(event.relatedTarget as Node)) return;
    setDropActive(false);
  };

  const caretRangeAt = (x: number, y: number): Range | null => {
    const doc = document as Document & {
      caretRangeFromPoint?: (x: number, y: number) => Range | null;
      caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
    };
    if (doc.caretRangeFromPoint) return doc.caretRangeFromPoint(x, y);
    const pos = doc.caretPositionFromPoint?.(x, y);
    if (!pos) return null;
    const range = document.createRange();
    range.setStart(pos.offsetNode, pos.offset);
    range.collapse(true);
    return range;
  };

  const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
    const token = event.dataTransfer.getData(QUESTION_IMAGE_REF_MIME);
    if (!token) return;

    event.preventDefault();
    setDropActive(false);
    if (readOnly) return;

    const root = rootRef.current;
    if (!root) return;

    TOKEN_RE.lastIndex = 0;
    const match = TOKEN_RE.exec(token);
    const alt = match ? match[1] : "";
    const src = match && CHIP_SRC_RE.test(match[2].trim()) ? match[2].trim() : null;
    const node: Node = src ? buildChip(alt, src) : document.createTextNode(token);

    let range = caretRangeAt(event.clientX, event.clientY);
    if (!range || !root.contains(range.startContainer)) {
      range = document.createRange();
      range.selectNodeContents(root);
      range.collapse(false);
    }

    const container =
      range.startContainer.nodeType === Node.TEXT_NODE
        ? range.startContainer.parentElement
        : (range.startContainer as HTMLElement);
    const hostChip = container?.closest?.("[data-chip]") as HTMLElement | null;
    if (hostChip && root.contains(hostChip)) {
      if (draggingChipRef.current === hostChip) return;
      const rect = hostChip.getBoundingClientRect();
      range = document.createRange();
      if (event.clientX < rect.left + rect.width / 2) range.setStartBefore(hostChip);
      else range.setStartAfter(hostChip);
      range.collapse(true);
    }

    range.insertNode(node);
    const selection = window.getSelection();
    if (selection) {
      const after = document.createRange();
      after.setStartAfter(node);
      after.collapse(true);
      selection.removeAllRanges();
      selection.addRange(after);
    }
    emit();
  };

  const isSourceVariant = variant === "source";

  return (
    <div
      className={cn(
        "relative rounded-md border border-input font-mono text-xs leading-relaxed overflow-auto transition-colors focus-within:ring-1 focus-within:ring-ring",
        isSourceVariant ? "bg-secondary text-secondary-foreground caret-white" : "bg-card text-foreground",
        dropActive && "ring-1 ring-primary border-primary",
        readOnly && "opacity-70",
        className,
      )}
      style={{ minHeight: `${Math.max(rows, 1) * 1.5}rem` }}
    >
      <div
        ref={rootRef}
        role="textbox"
        aria-label={placeholder || "Markdown 输入"}
        aria-multiline="true"
        aria-readonly={readOnly || undefined}
        contentEditable={!readOnly}
        suppressContentEditableWarning
        spellCheck={false}
        className="block w-full min-h-full p-3 outline-none whitespace-pre-wrap break-words"
        onInput={handleInput}
        onKeyDown={handleKeyDown}
        onPaste={handlePaste}
        onCopy={(event) => handleCopyOrCut(event, false)}
        onCut={(event) => handleCopyOrCut(event, true)}
        onBlur={handleBlur}
        onCompositionStart={() => {
          composingRef.current = true;
        }}
        onCompositionEnd={() => {
          composingRef.current = false;
          if (!editingRef.current) emit();
        }}
        onDoubleClick={handleDoubleClick}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      />
      {value === "" && placeholder ? (
        <span className={cn(
          "pointer-events-none absolute left-3 top-3 select-none",
          isSourceVariant ? "text-secondary-foreground/60" : "text-muted-foreground/60",
        )}>
          {placeholder}
        </span>
      ) : null}
    </div>
  );
}
