import React, { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, apiUrl } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { StatusTag } from "@/components/ui/StatusTag";
import { Checkbox } from "@/components/ui/checkbox";
import { Progress } from "@/components/ui/progress";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/hooks/use-toast";
import { RefreshCcw, CheckCircle2, FileText, Database, ExternalLink, Eye, EyeOff, Circle, Clock3, AlertCircle, MinusCircle, Wand2, ScanSearch, Sparkles } from "lucide-react";
import { QuestionCard } from "./QuestionCard";
import { getQuestionImages, getQuestionMarkdown, getSourceFileInfo, getSubQuestions } from "@/lib/question";
import { aiAnalysisFallbackMessage, buildSubQuestionAnalysisPayload, subAnalysisPatch } from "@/lib/sub-question-ai";
import { formatStandardizationProgress } from "@/lib/standardization-job";
import { canonicalStructureReview } from "@/lib/placement-review";

type OcrFlowStepStatus = "pending" | "running" | "success" | "failed" | "skipped" | string;

type OcrFlowStep = {
  id?: string;
  label?: string;
  description?: string;
  status?: OcrFlowStepStatus;
  startedAt?: string | null;
  finishedAt?: string | null;
  durationMs?: number | null;
  message?: string | null;
};

type OcrFlow = {
  status?: string;
  currentStep?: string | null;
  completedCount?: number;
  totalCount?: number;
  elapsedMs?: number | null;
  steps?: OcrFlowStep[];
};

type OcrJobSummary = {
  jobId?: string;
  filename?: string;
  status?: string;
  error?: string | null;
  parser?: string | null;
  ocrFlowProvider?: string | null;
  ocrProvider?: string | null;
  ocrFlow?: OcrFlow | null;
};

type OcrFlowJobView = {
  title: string;
  status?: string;
  job?: OcrJobSummary | null;
};

type PaperLayoutPage = {
  pageIndex: number;
  width: number;
  height: number;
  previewUrl: string;
};

type PaperLayoutRegion = {
  questionId: string;
  index: number;
  pageIndex: number;
  x: number;
  y: number;
  w: number;
  h: number;
  confidence?: number;
  source?: string;
  type?: string;
  text?: string;
};

type PaperLayout = {
  version?: string;
  sourceVersion?: string;
  pages?: PaperLayoutPage[];
  regions?: PaperLayoutRegion[];
  warnings?: string[];
};

type BatchAiProgress = {
  kind: "analysis" | "standardize";
  done: number;
  total: number;
  ok: number;
  fail: number;
  status: "running" | "saving" | "completed" | "failed";
  currentLabel: string;
  message?: string;
};

type StandardizationJob = {
  id: string;
  status: string;
  totalQuestions: number;
  completedQuestions: number;
  totalItems: number;
  completedItems: number;
  successItems: number;
  failedItems: number;
  maxConcurrency: number;
  rulesCount?: number;
  ocrFallbackCount?: number;
  cacheHitCount?: number;
  llmQuestionCount?: number;
  reviewRequiredCount?: number;
  failedCount?: number;
  currentLlmConcurrency?: number;
  maximumLlmConcurrency?: number;
};

const FLOW_STATUS_LABELS: Record<string, string> = {
  pending: "未进行",
  running: "进行中",
  success: "已完成",
  failed: "失败",
  skipped: "已跳过",
};

function formatDuration(durationMs?: number | null) {
  if (typeof durationMs !== "number" || !Number.isFinite(durationMs)) return "未开始";
  const ms = Math.max(0, Math.round(durationMs));
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60000) {
    const seconds = ms / 1000;
    return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} 秒`;
  }
  if (ms < 3600000) {
    const minutes = Math.floor(ms / 60000);
    const seconds = Math.round((ms % 60000) / 1000);
    return `${minutes} 分 ${seconds} 秒`;
  }
  const hours = Math.floor(ms / 3600000);
  const minutes = Math.round((ms % 3600000) / 60000);
  return `${hours} 小时 ${minutes} 分`;
}

function flowStatusLabel(status?: OcrFlowStepStatus) {
  return FLOW_STATUS_LABELS[String(status || "pending")] || String(status || "未进行");
}

function flowStatusClasses(status?: OcrFlowStepStatus) {
  switch (status) {
    case "success":
      return "border-success/30 bg-success/10 text-success";
    case "running":
      return "border-primary/30 bg-primary/10 text-primary";
    case "failed":
      return "border-destructive/30 bg-destructive/10 text-destructive";
    case "skipped":
      return "border-muted-foreground/25 bg-muted text-muted-foreground";
    default:
      return "border-border bg-muted/40 text-muted-foreground";
  }
}

function FlowStepIcon({ status }: { status?: OcrFlowStepStatus }) {
  if (status === "success") return <CheckCircle2 className="w-4 h-4 text-success" />;
  if (status === "running") return <RefreshCcw className="w-4 h-4 text-primary animate-spin" />;
  if (status === "failed") return <AlertCircle className="w-4 h-4 text-destructive" />;
  if (status === "skipped") return <MinusCircle className="w-4 h-4 text-muted-foreground" />;
  return <Circle className="w-4 h-4 text-muted-foreground/60" />;
}

function activeOcrJobs(task: any): OcrFlowJobView[] {
  const jobs: OcrFlowJobView[] = [
    {
      title: "试卷 OCR",
      status: task.paperOcrStatus,
      job: task.paperOcrJob,
    },
  ];
  if (task.answerFile || task.answerOcrJob) {
    jobs.push({
      title: "答案 OCR",
      status: task.answerOcrStatus,
      job: task.answerOcrJob,
    });
  }
  return jobs;
}

function OcrFlowJob({ view }: { view: OcrFlowJobView }) {
  const job = view.job;
  const flow = job?.ocrFlow;
  const steps = Array.isArray(flow?.steps) ? flow.steps : [];
  const currentStep = steps.find((step) => step.id && step.id === flow?.currentStep);
  const completedCount = Number.isFinite(flow?.completedCount) ? flow?.completedCount : steps.filter((step) => step.status === "success" || step.status === "skipped").length;
  const totalCount = Number.isFinite(flow?.totalCount) ? flow?.totalCount : steps.length;
  const provider = job?.ocrFlowProvider || job?.ocrProvider || job?.parser || "OCR";
  const currentLabel = flow?.status === "success" ? "全部完成" : currentStep?.label || (job?.status === "failed" ? "任务失败" : "等待状态");

  return (
    <section className="rounded-md border border-border bg-muted/20 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-sm font-semibold text-foreground">{view.title}</h4>
            <span className="rounded-full border border-border bg-card px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
              {provider}
            </span>
          </div>
          <p className="mt-1 truncate text-xs text-muted-foreground" title={job?.filename || ""}>
            {job?.filename || view.status || "等待 OCR job 创建"}
          </p>
        </div>
        <div className="shrink-0 rounded-md border border-primary/20 bg-primary/5 px-2.5 py-1 text-right">
          <div className="text-xs font-semibold text-primary">{completedCount || 0}/{totalCount || 0}</div>
          <div className="text-[11px] text-muted-foreground">节点</div>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
        <div className="rounded-md border border-border bg-card px-3 py-2">
          <span className="text-muted-foreground">当前节点</span>
          <div className="mt-0.5 font-medium text-foreground">{currentLabel}</div>
        </div>
        <div className="rounded-md border border-border bg-card px-3 py-2">
          <span className="text-muted-foreground">累计耗时</span>
          <div className="mt-0.5 flex items-center gap-1.5 font-medium text-foreground">
            <Clock3 className="w-3.5 h-3.5 text-muted-foreground" />
            {formatDuration(flow?.elapsedMs)}
          </div>
        </div>
      </div>

      {steps.length > 0 ? (
        <div className="mt-3 space-y-2">
          {steps.map((step, index) => {
            const status = step.status || "pending";
            const duration = status === "pending" ? "未开始" : formatDuration(step.durationMs);
            return (
              <div
                key={step.id || index}
                className={`grid grid-cols-[1.5rem_minmax(0,1fr)_5.5rem] items-start gap-2 rounded-md border px-2.5 py-2 ${flowStatusClasses(status)}`}
              >
                <div className="flex h-5 items-center justify-center">
                  <FlowStepIcon status={status} />
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-foreground">{step.label || step.id || "未命名节点"}</span>
                    <span className="text-[11px] font-medium">{flowStatusLabel(status)}</span>
                  </div>
                  {(step.message || step.description) && (
                    <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                      {step.message || step.description}
                    </p>
                  )}
                </div>
                <div className="whitespace-nowrap text-right text-xs font-medium text-foreground/80">
                  {duration}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="mt-3 rounded-md border border-dashed border-border px-3 py-6 text-center text-sm text-muted-foreground">
          OCR job 状态同步中
        </div>
      )}

      {job?.error && (
        <div className="mt-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {job.error}
        </div>
      )}
    </section>
  );
}

function OcrFlowProgress({ task, onRefresh }: { task: any; onRefresh: () => void }) {
  const jobs = activeOcrJobs(task);
  const runningJob = jobs.find((view) => view.job?.ocrFlow?.status === "running");
  const runningStep = runningJob?.job?.ocrFlow?.steps?.find((step) => step.id === runningJob.job?.ocrFlow?.currentStep);
  const hasRunningJob = Boolean(runningJob);
  const finishedJobs = jobs.filter((view) => view.job?.ocrFlow?.status === "success" || view.job?.status === "success").length;

  return (
    <div className="space-y-4">
      <div className="rounded-md border border-primary/20 bg-primary/5 px-3 py-2.5">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
              {hasRunningJob ? (
                <RefreshCcw className="w-4 h-4 animate-spin text-primary" />
              ) : (
                <Clock3 className="w-4 h-4 text-primary" />
              )}
              {hasRunningJob ? "OCR-Flow 正在执行" : "OCR-Flow 节点流程"}
            </div>
            <p className="mt-1 truncate text-xs text-muted-foreground">
              {runningJob && runningStep
                ? `${runningJob.title}：${runningStep.label || runningStep.id}`
                : finishedJobs > 0
                  ? `已完成 ${finishedJobs}/${jobs.length} 个 OCR job`
                  : "等待最新节点状态"}
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={onRefresh} className="h-8 shrink-0 gap-1.5">
            <RefreshCcw className="w-3.5 h-3.5" /> 刷新
          </Button>
        </div>
      </div>
      {jobs.map((view) => (
        <OcrFlowJob key={view.title} view={view} />
      ))}
    </div>
  );
}

function BatchAiProgressPanel({ progress }: { progress: BatchAiProgress }) {
  const percent = progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0;
  const isFinished = progress.status === "completed" || progress.status === "failed";
  const isStandardize = progress.kind === "standardize";
  const title =
    progress.status === "saving"
      ? isStandardize ? "正在保存标准化结果" : "正在保存 AI 解析结果"
      : progress.status === "completed"
        ? isStandardize ? "全局标准化处理完成" : "AI 解析处理完成"
        : progress.status === "failed"
          ? isStandardize ? "全局标准化处理失败" : "AI 解析处理失败"
          : isStandardize ? "全局标准化处理中" : "AI 解析全部处理中";

  return (
    <div className="shrink-0 border-b border-primary/20 bg-primary/5 px-4 py-3">
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            {!isFinished && <RefreshCcw className="h-4 w-4 animate-spin text-primary" />}
            {isFinished && <CheckCircle2 className="h-4 w-4 text-success" />}
            <span>{title}</span>
          </div>
          <p className="mt-1 truncate text-xs text-muted-foreground">
            {progress.currentLabel}
            {progress.message ? ` · ${progress.message}` : ""}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-3 text-xs text-muted-foreground">
          <span>{progress.done}/{progress.total}</span>
          <span>成功 {progress.ok}</span>
          <span>失败 {progress.fail}</span>
          <span className="font-medium text-foreground">{percent}%</span>
        </div>
      </div>
      <Progress value={percent} className="mt-2 h-2" />
    </div>
  );
}

function layoutPreviewUrl(value: string) {
  if (/^https?:\/\//i.test(value)) return value;
  return apiUrl(value.startsWith("/") ? value : `/${value}`);
}

function SourcePreview({
  url,
  file,
  layout,
  showRegions,
  onRegionClick,
}: {
  url: string;
  file: any;
  layout?: PaperLayout | null;
  showRegions?: boolean;
  onRegionClick?: (questionId: string) => void;
}) {
  const [failed, setFailed] = useState(false);
  const info = getSourceFileInfo(file);
  const kind = info?.kind ?? "pdf";
  const pages = Array.isArray(layout?.pages) ? layout.pages : [];
  const regions = Array.isArray(layout?.regions) ? layout.regions : [];
  const hasLayoutPreview = pages.length > 0;

  useEffect(() => {
    setFailed(false);
  }, [url]);

  if (failed) {
    return (
      <div className="w-full h-full flex flex-col items-center justify-center text-center gap-3 text-muted-foreground p-6">
        <FileText className="w-10 h-10 text-muted-foreground/50" />
        <p className="text-sm">原文件无法在此预览{info?.name ? `（${info.name}）` : ""}</p>
        <a href={url} target="_blank" rel="noreferrer">
          <Button variant="outline" size="sm" className="gap-2">
            <ExternalLink className="w-4 h-4" /> 打开原文件
          </Button>
        </a>
      </div>
    );
  }

  if (hasLayoutPreview) {
    return (
      <div className="w-full max-w-[900px] space-y-4">
        {pages.map((page) => {
          const pageRegions = regions.filter((region) => region.pageIndex === page.pageIndex);
          return (
            <div
              key={page.pageIndex}
              className="relative w-full overflow-hidden rounded-md border border-border bg-card elevation-1"
            >
              <img
                src={layoutPreviewUrl(page.previewUrl)}
                alt={`${info?.name || "试卷"} 第 ${page.pageIndex + 1} 页`}
                className="block w-full h-auto"
                onError={() => setFailed(true)}
              />
              {showRegions && pageRegions.length > 0 && (
                <div className="absolute inset-0">
                  {pageRegions.map((region) => {
                    const isRawMineruRegion = region.source === "mineru_raw" || !region.questionId;
                    const title = isRawMineruRegion
                      ? `MinerU ${region.type || "bbox"} #${region.index}${region.text ? `：${region.text}` : ""}`
                      : `定位到第 ${region.index} 题`;
                    return (
                      <button
                        key={`${region.questionId || region.source || "region"}-${region.pageIndex}-${region.index}-${region.x}-${region.y}`}
                        type="button"
                        aria-label={title}
                        title={title}
                        onClick={() => {
                          if (!isRawMineruRegion) onRegionClick?.(region.questionId);
                        }}
                        className={`absolute rounded-sm border-2 shadow-[0_0_0_1px_rgba(255,255,255,0.75)] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 ${
                          isRawMineruRegion
                            ? "cursor-default border-amber-500/80 bg-amber-400/10 text-amber-700 focus-visible:ring-amber-500"
                            : "border-primary/80 bg-primary/10 text-primary hover:bg-primary/20 focus-visible:ring-primary"
                        }`}
                        style={{
                          left: `${region.x * 100}%`,
                          top: `${region.y * 100}%`,
                          width: `${region.w * 100}%`,
                          height: `${region.h * 100}%`,
                        }}
                      >
                        <span className={`absolute left-1 top-1 flex h-5 min-w-5 items-center justify-center rounded-sm px-1 text-[11px] font-semibold leading-none ${
                          isRawMineruRegion ? "bg-amber-500 text-white" : "bg-primary text-primary-foreground"
                        }`}>
                          {region.index}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    );
  }

  if (kind === "image") {
    return (
      <img
        src={url}
        alt={info?.name || "原文件"}
        className="max-w-full max-h-full object-contain bg-card elevation-1 border border-border rounded-md"
        onError={() => setFailed(true)}
      />
    );
  }

  if (kind === "office" || kind === "other") {
    return (
      <div className="w-full h-full flex flex-col items-center justify-center text-center gap-3 text-muted-foreground p-6">
        <FileText className="w-10 h-10 text-muted-foreground/50" />
        <p className="text-sm">该文件类型不支持在线预览{info?.name ? `（${info.name}）` : ""}</p>
        <a href={url} target="_blank" rel="noreferrer">
          <Button variant="outline" size="sm" className="gap-2">
            <ExternalLink className="w-4 h-4" /> 打开原文件
          </Button>
        </a>
      </div>
    );
  }

  return (
    <iframe
      src={url}
      className="w-full h-[800px] max-h-full bg-card elevation-1 border border-border rounded-md"
      title="Preview"
      onError={() => setFailed(true)}
    />
  );
}

export function ImportWorkbenchTask({ taskId }: { taskId: string }) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [fileType, setFileType] = useState<"paper" | "answer">("paper");
  const [mobileView, setMobileView] = useState<"source" | "questions">("source");
  const [sourceVisible, setSourceVisible] = useState(true);
  const [aiDialogOpen, setAiDialogOpen] = useState(false);
  const [stdDialogOpen, setStdDialogOpen] = useState(false);
  const [overwriteExisting, setOverwriteExisting] = useState(false);
  const [aiProgress, setAiProgress] = useState<BatchAiProgress | null>(null);
  const [standardizationJob, setStandardizationJob] = useState<StandardizationJob | null>(null);
  const [canonicalPreview, setCanonicalPreview] = useState<any>(null);
  const [rescanDialogOpen, setRescanDialogOpen] = useState(false);
  const [ocrFlowOpen, setOcrFlowOpen] = useState(false);
  const [showLayoutBoxes, setShowLayoutBoxes] = useState(true);
  const [highlightQuestionId, setHighlightQuestionId] = useState<string | null>(null);
  const highlightTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const aiProgressResetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const aiRunning = aiProgress !== null;
  const stdRunning = standardizationJob !== null && ["queued", "running", "cancelling"].includes(standardizationJob.status);
  const batchRunning = aiRunning || stdRunning;

  const { data: task, isLoading, isError, error, isRefetching } = useQuery({
    queryKey: ["importTask", taskId],
    queryFn: () => api.getImportTask(taskId),
    retry: 1,
    refetchInterval: (query) => {
      const isProcessing = query.state.data?.status === "处理中";
      return isProcessing ? 5000 : false;
    }
  });

  const { data: polledStandardizationJob } = useQuery({
    queryKey: ["standardizationJob", taskId, standardizationJob?.id],
    queryFn: () => api.getStandardizationJob(taskId, standardizationJob!.id),
    enabled: Boolean(standardizationJob?.id),
    refetchInterval: (query) => {
      const status = String(query.state.data?.status || standardizationJob?.status || "");
      return ["queued", "running", "cancelling"].includes(status) ? 1500 : false;
    },
  });

  useEffect(() => {
    if (polledStandardizationJob?.id) {
      setStandardizationJob(polledStandardizationJob as StandardizationJob);
      if (["completed", "partial_failed", "failed", "cancelled"].includes(polledStandardizationJob.status)) {
        queryClient.invalidateQueries({ queryKey: ["importTask", taskId] });
      }
    }
  }, [polledStandardizationJob, queryClient, taskId]);

  const startDurableStandardization = async () => {
    try {
      const preview: any = await api.previewCanonicalization(taskId);
      setCanonicalPreview(preview);
      const structureReview = canonicalStructureReview(preview);
      if (Array.isArray(preview?.blockingIssues) && preview.blockingIssues.length > 0) {
        toast({ title: "请先整理题目结构", description: "存在重复题或题图归属冲突，需要人工复核", variant: "destructive" });
        return;
      }
      if (structureReview.changed) {
        toast({ title: "请先确认题目结构调整", description: "检测到选项数量或题图归属变化" });
        return;
      }
      const currentQuestionCount = Array.isArray(task?.questions) ? task.questions.length : 0;
      const canonicalQuestionCount = Number(preview?.summary?.afterQuestionCount || 0);
      if (Number(preview?.summary?.mergedQuestionCount || 0) > 0 && currentQuestionCount !== canonicalQuestionCount) {
        toast({
          title: "请先整理题目结构",
          description: `${preview.summary.beforeQuestionCount} 道原题将整理为 ${preview.summary.afterQuestionCount} 道 canonical 题`,
        });
        return;
      }
      setCanonicalPreview(null);
      const created: any = await api.createStandardizationJob(taskId);
      setStandardizationJob(created);
      toast({ title: "已创建全局标准化任务", description: `共 ${created.totalQuestions} 道题，并发 ${created.maxConcurrency}` });
    } catch (err) {
      toast({ title: "全局标准化启动失败", description: err instanceof Error ? err.message : String(err), variant: "destructive" });
    }
  };

  const applyCanonicalPreview = async () => {
    if (!canonicalPreview?.applyToken) return;
    try {
      await api.applyCanonicalization(taskId, canonicalPreview.applyToken);
      setCanonicalPreview(null);
      await queryClient.invalidateQueries({ queryKey: ["importTask", taskId] });
      toast({ title: "题目结构已整理", description: "可重新启动全局标准化" });
    } catch (err) {
      toast({ title: "题目结构应用失败", description: err instanceof Error ? err.message : String(err), variant: "destructive" });
    }
  };

  const updateStandardizationJob = async (action: "cancel" | "resume" | "retry") => {
    if (!standardizationJob?.id) return;
    const result = action === "cancel"
      ? await api.cancelStandardizationJob(taskId, standardizationJob.id)
      : action === "resume"
        ? await api.resumeStandardizationJob(taskId, standardizationJob.id)
        : await api.retryFailedStandardizationJob(taskId, standardizationJob.id);
    setStandardizationJob(result as StandardizationJob);
  };

  useEffect(() => {
    return () => {
      if (highlightTimerRef.current) {
        clearTimeout(highlightTimerRef.current);
      }
      if (aiProgressResetTimerRef.current) {
        clearTimeout(aiProgressResetTimerRef.current);
      }
    };
  }, []);

  const bankAllMutation = useMutation({
    mutationFn: () => api.bankAllImportQuestions(taskId),
    onSuccess: () => {
      toast({ title: "批量入库成功" });
      queryClient.invalidateQueries({ queryKey: ["importTask", taskId] });
      queryClient.invalidateQueries({ queryKey: ["questions"] });
    },
    onError: (err: any) => toast({ title: "入库失败", description: err.message, variant: "destructive" })
  });

  const handleBankAll = () => {
    if (!task?.questions?.some((q: any) => q.status === "已校验")) {
      toast({ title: "提示", description: "暂无已校验题目可入库" });
      return;
    }
    bankAllMutation.mutate();
  };

  const rescanMutation = useMutation({
    mutationFn: () => api.rescanImportTask(taskId),
    onSuccess: () => {
      toast({
        title: "已开始重新 OCR 扫描",
        description: "只重新扫描原始文件，已提取和已编辑的题目不受影响",
      });
      queryClient.invalidateQueries({ queryKey: ["importTask", taskId] });
      queryClient.invalidateQueries({ queryKey: ["importTasks"] });
    },
    onError: (err: any) => toast({ title: "重新扫描失败", description: err.message, variant: "destructive" }),
  });

  const knowledgePointNames = (value: any): string[] => {
    const raw = value?.knowledgePoints;
    if (Array.isArray(raw)) return raw.map((item) => String(item).trim()).filter(Boolean);
    return String(raw || "")
      .split(/[,，]/)
      .map((item) => item.trim())
      .filter(Boolean);
  };

  const runAiAnalyzeAll = async (overwrite: boolean) => {
    if (aiRunning) return;
    if (aiProgressResetTimerRef.current) {
      clearTimeout(aiProgressResetTimerRef.current);
      aiProgressResetTimerRef.current = null;
    }

    const questions = Array.isArray(task?.questions) ? task.questions.filter((q: any) => q.status !== "已入库") : [];
    type BatchUnit = { question: any; sub?: any; subIndex?: number; label: string };
    const units: BatchUnit[] = [];
    questions.forEach((question: any, questionIndex: number) => {
      const questionNumber = String(question.number || question.questionNumber || questionIndex + 1);
      const subs = getSubQuestions(question);
      if (subs.length > 0) {
        subs.forEach((sub, subIndex) => {
          if (getQuestionMarkdown(sub).trim() && (overwrite || !String(sub.analysis || "").trim())) {
            units.push({ question, sub, subIndex, label: `第 ${questionNumber} 题小问 ${subIndex + 1}` });
          }
        });
        return;
      }
      if (getQuestionMarkdown(question).trim() && (overwrite || !String(question.analysis || "").trim())) {
        units.push({ question, label: `第 ${questionNumber} 题` });
      }
    });

    if (units.length === 0) {
      toast({
        title: "没有需要生成解析的题目",
        description: overwrite
          ? "未入库题目中没有可解析的题干"
          : "未入库题目的解析均已填写，可勾选覆盖已有解析重新生成",
      });
      return;
    }

    let ok = 0;
    let fail = 0;
    let done = 0;
    const dirtySubQuestions = new Map<string, any[]>();
    const dirtySubSuccesses = new Map<string, number>();
    const publishProgress = (
      currentLabel: string,
      status: BatchAiProgress["status"] = "running",
      message?: string,
    ) => {
      setAiProgress({
        kind: "analysis",
        done,
        total: units.length,
        ok,
        fail,
        status,
        currentLabel,
        message,
      });
    };

    publishProgress(
      `准备处理 ${units.length} 处解析`,
      "running",
      overwrite ? "覆盖已有解析" : "只补齐缺失解析",
    );
    toast({
      title: "已开始 AI 解析全部",
      description: `将处理 ${units.length} 处解析，期间可以继续浏览题目`,
    });

    for (const unit of units) {
      publishProgress(`正在生成${unit.label}解析`);
      try {
        if (unit.sub) {
          const parentSubs = dirtySubQuestions.get(unit.question.id)
            || getSubQuestions(unit.question).map((sub: any) => ({ ...sub }));
          const currentSub = parentSubs[unit.subIndex ?? -1] || unit.sub;
          const res: any = await api.generateAnalysisAi(
            buildSubQuestionAnalysisPayload({
              parentMarkdown: getQuestionMarkdown(unit.question),
              parentImages: getQuestionImages(unit.question),
              sub: currentSub,
              knowledgePoints: knowledgePointNames(currentSub),
            }),
          );
          const fallbackMessage = aiAnalysisFallbackMessage(res);
          const patch = fallbackMessage ? {} : subAnalysisPatch(res);
          if (patch.analysis && parentSubs[unit.subIndex ?? -1]) {
            parentSubs[unit.subIndex ?? -1] = { ...parentSubs[unit.subIndex ?? -1], analysis: patch.analysis };
            dirtySubQuestions.set(unit.question.id, parentSubs);
            dirtySubSuccesses.set(unit.question.id, (dirtySubSuccesses.get(unit.question.id) || 0) + 1);
            ok++;
          } else {
            fail++;
          }
        } else {
          const res: any = await api.generateImportQuestionAnalysis(taskId, unit.question.id, {
            manualMarkdown: getQuestionMarkdown(unit.question),
            answer: unit.question.answer || "",
            type: unit.question.type || "unknown",
            knowledgePoints: knowledgePointNames(unit.question),
            images: getQuestionImages(unit.question),
            subQuestions: [],
          });
          const fallbackMessage = aiAnalysisFallbackMessage(res);
          const analysis = String(fallbackMessage ? "" : res?.analysis || "").trim();
          if (analysis) {
            ok++;
          } else {
            fail++;
          }
        }
      } catch (error) {
        fail++;
        const message = error instanceof Error ? error.message : String(error);
        publishProgress(`${unit.label}解析失败`, "running", message);
      }
      done++;
      publishProgress(`已处理${unit.label}`);
    }

    for (const [questionId, subQuestions] of dirtySubQuestions) {
      const generatedCount = dirtySubSuccesses.get(questionId) || 0;
      try {
        publishProgress("正在保存复合大题小问解析", "saving");
        await api.updateImportQuestion(taskId, questionId, { subQuestions });
      } catch {
        ok = Math.max(0, ok - generatedCount);
        fail += generatedCount;
        publishProgress("复合大题小问解析保存失败", "saving");
      }
    }

    const finalStatus: BatchAiProgress["status"] = ok > 0 ? "completed" : "failed";
    setAiProgress({
      kind: "analysis",
      done: units.length,
      total: units.length,
      ok,
      fail,
      status: finalStatus,
      currentLabel: fail === 0 ? "全部解析已生成" : ok > 0 ? "部分解析已生成" : "全部解析生成失败",
      message: fail > 0 ? "失败项可稍后重新执行" : undefined,
    });
    aiProgressResetTimerRef.current = setTimeout(() => {
      setAiProgress(null);
      aiProgressResetTimerRef.current = null;
    }, 3000);
    queryClient.invalidateQueries({ queryKey: ["importTask", taskId] });
    if (fail === 0) {
      toast({ title: "AI 解析生成完成", description: `已生成 ${ok} 处解析` });
    } else if (ok > 0) {
      toast({ title: "AI 解析部分完成", description: `成功 ${ok} 处，失败 ${fail} 处，可稍后重试` });
    } else {
      toast({ title: "AI 解析生成失败", description: `${fail} 处均未成功，请稍后重试`, variant: "destructive" });
    }
  };

  // Global standardization is orchestrated by the durable Java batch job above.
  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: ["importTask", taskId] });
  };

  const toggleSourceVisible = () => {
    setSourceVisible((visible) => {
      const nextVisible = !visible;
      setMobileView(nextVisible ? "source" : "questions");
      return nextVisible;
    });
  };

  const handleLocateLayoutQuestion = (questionId: string) => {
    if (!questionId) return;
    setMobileView("questions");
    setHighlightQuestionId(questionId);
    if (highlightTimerRef.current) {
      clearTimeout(highlightTimerRef.current);
    }
    highlightTimerRef.current = setTimeout(() => {
      setHighlightQuestionId((current) => (current === questionId ? null : current));
    }, 2500);
    window.requestAnimationFrame(() => {
      document.getElementById(`import-question-${questionId}`)?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    });
  };

  if (isLoading) return <div className="p-8 text-center text-muted-foreground">加载任务详情...</div>;
  if (!task) return (
    <div className="p-8 text-center text-destructive">
      无法加载任务详情{error instanceof Error && error.message ? `：${error.message}` : ""}
      <div className="mt-3">
        <Button variant="outline" size="sm" onClick={handleRefresh} className="gap-2">
          <RefreshCcw className="w-4 h-4" /> 重试
        </Button>
      </div>
    </div>
  );

  const hasAnswer = !!task.answerFile;
  const isProcessing = task.status === "处理中";
  const hasOcrFlow = activeOcrJobs(task).some((view) => view.job || view.status);
  const paperLayout = (task.paperLayout || null) as PaperLayout | null;
  const hasPaperLayout =
    fileType === "paper"
    && Array.isArray(paperLayout?.pages)
    && paperLayout.pages.length > 0
    && Array.isArray(paperLayout?.regions)
    && paperLayout.regions.length > 0;
  const layoutWarnings = Array.isArray(paperLayout?.warnings) ? paperLayout.warnings.filter(Boolean) : [];
  
  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="shrink-0 px-4 py-3 border-b border-border bg-muted/40 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <h2 className="font-bold text-lg text-foreground truncate" title={task.title}>{task.title}</h2>
            <StatusTag status={task.status} type="task" />
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span>{[task.stage, task.subject, task.grade, task.region, task.year].filter(Boolean).join(" · ")}</span>
            <span className="text-border">·</span>
            <span>试卷 OCR：{task.paperOcrStatus || "处理中"}</span>
            <span>答案 OCR：{hasAnswer ? (task.answerOcrStatus || "处理中") : "未上传答案"}</span>
          </div>
        </div>
        <div className="flex flex-wrap justify-end gap-2 shrink-0">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setOcrFlowOpen(true)}
            disabled={!hasOcrFlow}
            className="gap-2"
          >
            <Clock3 className="w-4 h-4" /> OCR 流程
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setRescanDialogOpen(true)}
            disabled={isProcessing || rescanMutation.isPending || batchRunning || bankAllMutation.isPending}
            className="gap-2"
          >
            <ScanSearch className="w-4 h-4" /> {rescanMutation.isPending ? "启动扫描中" : "重新 OCR 扫描"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setStdDialogOpen(true)}
            disabled={isProcessing || batchRunning || rescanMutation.isPending || bankAllMutation.isPending}
            className="gap-2 text-primary border-primary/30 hover:bg-primary/10 hover:text-primary"
          >
            {stdRunning ? <RefreshCcw className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
            {stdRunning ? `标准化中 ${standardizationJob?.completedQuestions || 0}/${standardizationJob?.totalQuestions || 0}` : "全局标准化"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setAiDialogOpen(true)}
            disabled={isProcessing || batchRunning || rescanMutation.isPending || bankAllMutation.isPending}
            className="gap-2 text-warm border-warm/30 hover:bg-warm/10 hover:text-warm"
          >
            {aiProgress ? <RefreshCcw className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}
            {aiProgress ? `AI 解析中 ${aiProgress.done}/${aiProgress.total}` : "AI 解析全部"}
          </Button>
          <Button variant="outline" size="sm" onClick={toggleSourceVisible} className="gap-2">
            {sourceVisible ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            {sourceVisible ? "隐藏原文件" : "显示原文件"}
          </Button>
          <Button size="sm" onClick={handleBankAll} disabled={bankAllMutation.isPending || isProcessing || rescanMutation.isPending || batchRunning} className="gap-2">
            <Database className="w-4 h-4" /> 批量入库
          </Button>
        </div>
      </div>

      <Dialog open={ocrFlowOpen} onOpenChange={setOcrFlowOpen}>
        <DialogContent className="max-h-[86vh] max-w-4xl overflow-hidden p-0">
          <DialogHeader className="px-5 pt-5">
            <DialogTitle>OCR 节点流程</DialogTitle>
          </DialogHeader>
          <div className="max-h-[70vh] overflow-y-auto px-5 pb-5">
            <OcrFlowProgress task={task} onRefresh={handleRefresh} />
          </div>
        </DialogContent>
      </Dialog>

      <AlertDialog open={aiDialogOpen} onOpenChange={(open) => !batchRunning && setAiDialogOpen(open)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>一键 AI 解析全部题目？</AlertDialogTitle>
            <AlertDialogDescription>
              默认只为未入库且缺少解析的题目补齐解析；已入库题目会跳过。普通题按整题生成，复合大题会按小问逐个生成，生成后仍需人工校验才能入库。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <label className="flex items-center gap-2 rounded-md border border-border bg-muted/30 px-3 py-2 text-sm">
            <Checkbox
              checked={overwriteExisting}
              onCheckedChange={(checked) => setOverwriteExisting(checked === true)}
            />
            覆盖已有解析
          </label>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              disabled={batchRunning}
              onClick={(event) => {
                event.preventDefault();
                setAiDialogOpen(false);
                window.setTimeout(() => {
                  void runAiAnalyzeAll(overwriteExisting);
                }, 0);
              }}
            >
              开始生成
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={stdDialogOpen} onOpenChange={(open) => !batchRunning && setStdDialogOpen(open)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>一键全局标准化全部题目？</AlertDialogTitle>
            <AlertDialogDescription>
              将对当前任务全部题目的题干、答案、解析逐一调用 AI 标准化，复合题会处理每个小问。完成后会自动保存到校验卡片，题目状态保持不变；已入库题目如需同步覆盖题库，请再次点击重新入库。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              disabled={batchRunning}
              onClick={(event) => {
                event.preventDefault();
                setStdDialogOpen(false);
                window.setTimeout(() => {
                  void startDurableStandardization();
                }, 0);
              }}
            >
              开始标准化
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={rescanDialogOpen} onOpenChange={(open) => !rescanMutation.isPending && !batchRunning && setRescanDialogOpen(open)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>重新 OCR 扫描原始文档？</AlertDialogTitle>
            <AlertDialogDescription>
              只会重新扫描原始试卷/答案文件，当前已提取和已编辑的题目不受影响。扫描期间任务和 OCR 状态会显示处理中，页面会自动轮询刷新。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                setRescanDialogOpen(false);
                rescanMutation.mutate();
              }}
            >
              开始扫描
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      
      {isError && !isRefetching && (
        <div className="shrink-0 px-4 py-2 bg-warm/10 border-b border-warm/30 flex items-center justify-between gap-3 text-sm text-foreground/80">
          <span>更新任务状态失败，显示的可能不是最新数据{error instanceof Error && error.message ? `：${error.message}` : ""}</span>
          <Button variant="outline" size="sm" onClick={handleRefresh} className="gap-1.5 h-7 shrink-0">
            <RefreshCcw className="w-3.5 h-3.5" /> 重试
          </Button>
        </div>
      )}

      {canonicalPreview && (
        <div className="shrink-0 px-4 py-2 bg-amber-50 border-b border-amber-200 flex items-center justify-between gap-3 text-sm text-amber-900">
          <div>
            <div>
              整理题目结构：{canonicalPreview.summary?.beforeQuestionCount} → {canonicalPreview.summary?.afterQuestionCount} 道
              {canonicalPreview.summary?.mergedQuestionCount > 0 ? `，将合并 ${canonicalPreview.summary.mergedQuestionCount} 道答案区重复题` : ""}。
            </div>
            {canonicalStructureReview(canonicalPreview).lines.slice(0, 4).map((line) => (
              <div key={line} className="mt-1 text-xs">{line}</div>
            ))}
            {canonicalStructureReview(canonicalPreview).blocking && (
              <div className="mt-1 text-xs font-medium">存在重复题或题目边界冲突，需人工复核后才能应用。</div>
            )}
            {!canonicalStructureReview(canonicalPreview).blocking
              && canonicalStructureReview(canonicalPreview).reviewRequired && (
              <div className="mt-1 text-xs font-medium">题目结构可先应用；题图归属项仍需逐题复核。</div>
            )}
          </div>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => setCanonicalPreview(null)}>暂不处理</Button>
            <Button
              size="sm"
              onClick={() => void applyCanonicalPreview()}
              disabled={canonicalStructureReview(canonicalPreview).blocking}
            >
              应用整理
            </Button>
          </div>
        </div>
      )}

      {standardizationJob && (
        <div className="shrink-0 px-4 py-3 border-b border-primary/20 bg-primary/5 flex items-center justify-between gap-4 text-sm">
          <div>
            <div className="font-medium text-foreground">
              {formatStandardizationProgress(standardizationJob)}
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              状态：{standardizationJob.status}
              {standardizationJob.status === "partial_review" ? " · 存在需要人工复核的候选，原题未被覆盖" : ""}
            </div>
          </div>
          <div className="flex gap-2">
            {["queued", "running"].includes(standardizationJob.status) && <Button size="sm" variant="outline" onClick={() => void updateStandardizationJob("cancel")}>取消</Button>}
            {standardizationJob.status === "cancelled" && <Button size="sm" onClick={() => void updateStandardizationJob("resume")}>继续</Button>}
            {["partial_failed", "failed"].includes(standardizationJob.status) && <Button size="sm" onClick={() => void updateStandardizationJob("retry")}>重试失败项</Button>}
          </div>
        </div>
      )}

      {aiProgress && <BatchAiProgressPanel progress={aiProgress} />}

      {/* Mobile view switch */}
      {sourceVisible && (
      <div className="md:hidden shrink-0 p-2 border-b border-border bg-card flex gap-1">
        <button
          onClick={() => setMobileView("source")}
          className={`flex-1 px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${mobileView === "source" ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent"}`}
        >
          原文件
        </button>
        <button
          onClick={() => setMobileView("questions")}
          className={`flex-1 px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${mobileView === "questions" ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent"}`}
        >
          校验题目
        </button>
      </div>
      )}

      <div className="flex-1 flex flex-col md:flex-row overflow-hidden">
        {/* Left: File Preview */}
        {sourceVisible && (
        <div className={`w-full md:w-1/2 border-b md:border-b-0 md:border-r border-border flex-col bg-muted/30 ${mobileView === "source" ? "flex" : "hidden"} md:flex`}>
          <div className="shrink-0 h-12 px-4 flex gap-2 border-b border-border bg-card justify-between items-center">
             <span className="text-sm font-medium">原文件</span>
             <div className="flex items-center gap-2">
               <div className="flex gap-1 bg-muted p-0.5 rounded-md">
                 <button
                   onClick={() => setFileType("paper")}
                   className={`px-3 py-1 text-xs font-medium rounded-sm transition-colors ${fileType === "paper" ? "bg-card elevation-1 text-foreground" : "text-muted-foreground hover:text-foreground"}`}
                 >
                   试卷
                 </button>
                 <button
                   onClick={() => setFileType("answer")}
                   disabled={!hasAnswer}
                   className={`px-3 py-1 text-xs font-medium rounded-sm transition-colors ${fileType === "answer" ? "bg-card elevation-1 text-foreground" : "text-muted-foreground hover:text-foreground"} ${!hasAnswer ? "opacity-50 cursor-not-allowed" : ""}`}
                 >
                   答案
                 </button>
               </div>
               <Button
                 type="button"
                 variant="ghost"
                 size="icon"
                 disabled={fileType !== "paper" || !hasPaperLayout}
                 onClick={() => setShowLayoutBoxes((visible) => !visible)}
                 title={
                   fileType !== "paper"
                     ? "答案文件暂不支持布局解析框"
                     : hasPaperLayout
                       ? (showLayoutBoxes ? "关闭布局解析框" : "开启布局解析框")
                       : "当前任务暂无可用布局解析框"
                 }
                 className={`h-8 w-8 rounded-md border ${showLayoutBoxes && hasPaperLayout && fileType === "paper" ? "border-primary/40 bg-primary/10 text-primary" : "border-border text-muted-foreground"}`}
               >
                 <ScanSearch className="w-4 h-4" />
               </Button>
             </div>
          </div>
          <div className="flex-1 overflow-auto p-4 flex flex-col items-center justify-start bg-muted/50">
             {fileType === "paper" && layoutWarnings.length > 0 && (
               <div className="mb-3 flex w-full max-w-[900px] items-start gap-2 rounded-md border border-warm/30 bg-warm/10 px-3 py-2 text-xs text-foreground/80">
                 <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warm-foreground" />
                 <span>
                   {layoutWarnings[0]}
                   {layoutWarnings.length > 1 ? `，另有 ${layoutWarnings.length - 1} 条布局提示` : ""}
                 </span>
               </div>
             )}
             <SourcePreview
               url={api.importTaskSourceUrl(taskId, fileType)}
               file={fileType === "paper" ? task.paperFile : task.answerFile}
               layout={fileType === "paper" ? paperLayout : null}
               showRegions={fileType === "paper" && showLayoutBoxes}
               onRegionClick={handleLocateLayoutQuestion}
             />
          </div>
        </div>
        )}
        
        {/* Right: Questions */}
        <div className={`w-full ${sourceVisible ? "md:w-1/2" : "md:w-full"} flex-col bg-card ${sourceVisible && mobileView !== "questions" ? "hidden" : "flex"} md:flex`}>
          <div className="shrink-0 h-12 px-4 border-b border-border flex justify-between items-center bg-card">
             <h3 className="font-medium flex items-center gap-2">
               <CheckCircle2 className="w-4 h-4 text-success" /> 人工校验与入库
             </h3>
             <span className="text-xs text-muted-foreground font-medium">{task.questions?.length || 0} 题</span>
          </div>
          <div className="flex-1 overflow-auto p-4 space-y-4">
             {isProcessing ? (
               <OcrFlowProgress task={task} onRefresh={handleRefresh} />
             ) : task.questions?.length === 0 ? (
               <div className="text-center py-16 text-muted-foreground border-2 border-dashed border-border rounded-lg m-4">
                 <p>暂无题目，请刷新或检查 OCR 任务</p>
               </div>
             ) : (
               task.questions?.map((q: any, idx: number) => (
                 <div
                   key={q.id}
                   id={`import-question-${q.id}`}
                   className={`scroll-mt-4 rounded-lg transition-shadow duration-300 ${highlightQuestionId === q.id ? "ring-2 ring-primary ring-offset-2 ring-offset-card" : ""}`}
                 >
                   <QuestionCard index={idx + 1} question={q} taskId={taskId} />
                 </div>
               ))
             )}
          </div>
        </div>
      </div>
    </div>
  );
}
