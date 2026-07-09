import { Button } from "@/components/ui/button";
import { MarkdownRenderer } from "@/components/ui/MarkdownRenderer";
import { type QuestionImage, type QuestionOption } from "@/lib/question";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { useEffect, useState } from "react";

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
  fallbackUsed?: boolean;
  retryable?: boolean;
  confidence?: string;
  source?: string;
  applyBlocked?: boolean;
  renderValidation?: {
    valid?: boolean;
    issues?: string[];
  };
};

export type StandardizeCandidate = {
  markdown: string;
  message: string;
  sourceLabel: string;
  applyBlocked: boolean;
  blockReasons: string[];
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
  if (standardizer?.fallbackUsed) {
    return warnings[0] || "AI 标准化暂时不可用，已返回本地兜底候选";
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

function sourceLabel(standardizer: StandardizerResult | undefined) {
  if (standardizer?.source === "rules") return "本地修复";
  if (standardizer?.source === "rules-fallback") return "本地兜底";
  if (standardizer?.source === "ocr-fallback") return "原始 OCR 兜底";
  if (standardizer?.rawOcrFallbackUsed) return "原始 OCR 兜底";
  if (standardizer?.source === "ai") return "AI 修复";
  return "标准化候选";
}

function hasSubQuestionCandidate(payload: any): boolean {
  const candidates = [
    payload?.subQuestions,
    payload?.children,
    payload?.metadata?.subQuestions,
    payload?.standardizer?.subQuestions,
    payload?.question?.subQuestions,
    payload?.question?.children,
  ];
  return candidates.some((candidate) => Array.isArray(candidate) && candidate.length > 0);
}

export function standardizeCandidateFromPayload(currentMarkdown: string, payload: { markdown?: unknown; standardizer?: StandardizerResult }) {
  const markdown = String(payload?.markdown ?? currentMarkdown);
  const message = standardizeNotice(payload?.standardizer, "AI 标准化完成");
  const candidateSevereIssues = stringList(payload?.standardizer?.candidateSevereIssues);
  const renderIssues = stringList(payload?.standardizer?.renderValidation?.issues);
  const blockReasons = [...candidateSevereIssues, ...renderIssues];
  const applyBlocked = Boolean(payload?.standardizer?.applyBlocked) || blockReasons.length > 0 || payload?.standardizer?.renderValidation?.valid === false;
  if (markdown === currentMarkdown && !hasSubQuestionCandidate(payload)) {
    return { candidate: null as StandardizeCandidate | null, message: `${message}，未产生可应用改动` };
  }
  return {
    candidate: {
      markdown,
      message,
      sourceLabel: sourceLabel(payload?.standardizer),
      applyBlocked,
      blockReasons,
      payload,
    },
    message: applyBlocked ? `${message}，候选不可直接应用` : `${message}，请预览后应用`,
  };
}

export function AiStandardizeJobStatus({
  active,
  label = "AI 标准化",
}: {
  active: boolean;
  label?: string;
}) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (!active) {
      setVisible(false);
      return;
    }
    const timer = window.setTimeout(() => setVisible(true), 1500);
    return () => window.clearTimeout(timer);
  }, [active]);

  if (!active || !visible) return null;

  return (
    <div className="rounded-md border border-info/30 bg-card px-3 py-2 text-xs leading-relaxed text-muted-foreground">
      {label} job 执行中，正在生成标准化候选；完成后会显示候选来源和可应用状态。
    </div>
  );
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
    <section className="rounded-md border border-border bg-card p-3 space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-medium text-foreground">AI 修复候选</h3>
          <p className="mt-1 text-xs text-muted-foreground break-words">
            {candidate.sourceLabel}：{candidate.message}
          </p>
          {candidate.applyBlocked ? (
            <p className="mt-1 inline-flex items-center gap-1 text-xs text-destructive">
              <AlertTriangle className="h-3.5 w-3.5" />
              {candidate.blockReasons[0] || "候选未通过渲染安全校验，不能直接应用"}
            </p>
          ) : null}
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" type="button" onClick={onDismiss} disabled={disabled} className="h-8 text-xs">
            丢弃
          </Button>
          <Button size="sm" type="button" onClick={onApply} disabled={disabled || candidate.applyBlocked} className="h-8 gap-1.5 text-xs">
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
            className="min-h-[180px] flex-1 p-3 rounded-md border border-input bg-card text-foreground font-mono text-xs leading-relaxed resize-y"
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
