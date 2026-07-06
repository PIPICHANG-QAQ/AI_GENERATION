import { Button } from "@/components/ui/button";
import { MarkdownRenderer } from "@/components/ui/MarkdownRenderer";
import { type QuestionImage, type QuestionOption } from "@/lib/question";
import { CheckCircle2 } from "lucide-react";

type StandardizerCorrection = {
  before?: unknown;
  after?: unknown;
};

export type StandardizerResult = {
  corrections?: StandardizerCorrection[];
  warnings?: string[];
  severeIssues?: string[];
  candidateSevereIssues?: string[];
  rawOcrFallbackUsed?: boolean;
  rawOcrContextUsed?: boolean;
  confidence?: string;
};

export type StandardizeCandidate = {
  markdown: string;
  message: string;
  payload?: any;
};

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
}

function standardizeNotice(standardizer: StandardizerResult | undefined, fallback: string) {
  const corrections = Array.isArray(standardizer?.corrections) ? standardizer.corrections : [];
  const warnings = stringList(standardizer?.warnings);
  const severeIssues = stringList(standardizer?.severeIssues);
  const candidateSevereIssues = stringList(standardizer?.candidateSevereIssues);
  if (candidateSevereIssues.length > 0) {
    return `AI 候选仍存在严重公式风险：${candidateSevereIssues[0]}`;
  }
  if (standardizer?.rawOcrFallbackUsed) {
    return "检测到严重公式损坏，已使用原始 OCR 片段生成候选";
  }
  if (severeIssues.length > 0 && standardizer?.rawOcrContextUsed) {
    return "检测到严重公式损坏，已参考原始 OCR 生成候选";
  }
  if (corrections.length > 0) {
    const first = corrections[0];
    return `AI 已修复：${String(first.before ?? "")} -> ${String(first.after ?? "")}`;
  }
  if (warnings.length > 0) {
    return `AI 标准化完成，仍需复核：${warnings[0]}`;
  }
  if (standardizer?.confidence === "low") {
    return "AI 标准化低置信，请谨慎复核候选";
  }
  if (standardizer?.rawOcrContextUsed) {
    return "AI 标准化完成，已参考原始 OCR";
  }
  return fallback;
}

export function standardizeCandidateFromPayload(currentMarkdown: string, payload: { markdown?: unknown; standardizer?: StandardizerResult }) {
  const markdown = String(payload?.markdown ?? currentMarkdown);
  const message = standardizeNotice(payload?.standardizer, "AI 标准化完成");
  if (markdown === currentMarkdown) {
    return { candidate: null as StandardizeCandidate | null, message: `${message}，未产生可应用改动` };
  }
  return { candidate: { markdown, message, payload }, message: `${message}，请预览后应用` };
}

export function StandardizeCandidatePanel({
  candidate,
  disabled = false,
  images,
  onApply,
  onDismiss,
  options,
  questionType,
}: {
  candidate: StandardizeCandidate;
  disabled?: boolean;
  images?: QuestionImage[];
  onApply: () => void;
  onDismiss: () => void;
  options?: QuestionOption[] | unknown[];
  questionType?: string;
}) {
  return (
    <section className="rounded-md border border-info/30 bg-info/5 p-3 space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-medium text-foreground">AI 修复候选</h3>
          <p className="mt-1 text-xs text-muted-foreground break-words">{candidate.message}</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" type="button" onClick={onDismiss} disabled={disabled} className="h-8 text-xs">
            丢弃
          </Button>
          <Button size="sm" type="button" onClick={onApply} disabled={disabled} className="h-8 gap-1.5 text-xs">
            <CheckCircle2 className="w-3.5 h-3.5" />
            应用
          </Button>
        </div>
      </div>
      <div className="grid grid-cols-1 @2xl:grid-cols-2 gap-3">
        <label className="flex flex-col">
          <span className="text-xs font-medium text-muted-foreground mb-1.5">候选源码</span>
          <textarea
            readOnly
            value={candidate.markdown}
            className="min-h-[180px] flex-1 p-3 rounded-md border border-input bg-secondary text-secondary-foreground font-mono text-xs leading-relaxed resize-y"
          />
        </label>
        <div className="flex flex-col">
          <span className="text-xs font-medium text-muted-foreground mb-1.5">候选预览</span>
          <div className="min-h-[180px] flex-1 p-3 rounded-md border border-border bg-card overflow-auto prose-container">
            <MarkdownRenderer content={candidate.markdown} images={images} questionType={questionType} options={options} />
          </div>
        </div>
      </div>
    </section>
  );
}
