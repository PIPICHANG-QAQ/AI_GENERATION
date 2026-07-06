import React, { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { StatusTag } from "@/components/ui/StatusTag";
import { useToast } from "@/hooks/use-toast";
import { RefreshCcw, CheckCircle2, FileText, Database, ExternalLink, Eye, EyeOff, Circle, Clock3, AlertCircle, MinusCircle } from "lucide-react";
import { QuestionCard } from "./QuestionCard";
import { getSourceFileInfo } from "@/lib/question";

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

  return (
    <div className="space-y-4">
      <div className="rounded-md border border-primary/20 bg-primary/5 px-3 py-2.5">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
              <RefreshCcw className="w-4 h-4 animate-spin text-primary" />
              OCR-Flow 正在执行
            </div>
            <p className="mt-1 truncate text-xs text-muted-foreground">
              {runningJob && runningStep ? `${runningJob.title}：${runningStep.label || runningStep.id}` : "等待最新节点状态"}
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

function SourcePreview({ url, file }: { url: string, file: any }) {
  const [failed, setFailed] = useState(false);
  const info = getSourceFileInfo(file);
  const kind = info?.kind ?? "pdf";

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

  const { data: task, isLoading, isError, error, isRefetching } = useQuery({
    queryKey: ["importTask", taskId],
    queryFn: () => api.getImportTask(taskId),
    retry: 1,
    refetchInterval: (query) => {
      const isProcessing = query.state.data?.status === "处理中";
      return isProcessing ? 5000 : false;
    }
  });

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
        <div className="flex gap-2 shrink-0">
          <Button variant="outline" size="sm" onClick={toggleSourceVisible} className="gap-2">
            {sourceVisible ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            {sourceVisible ? "隐藏原文件" : "显示原文件"}
          </Button>
          <Button size="sm" onClick={handleBankAll} disabled={bankAllMutation.isPending} className="gap-2">
            <Database className="w-4 h-4" /> 批量入库
          </Button>
        </div>
      </div>
      
      {isError && !isRefetching && (
        <div className="shrink-0 px-4 py-2 bg-warm/10 border-b border-warm/30 flex items-center justify-between gap-3 text-sm text-foreground/80">
          <span>更新任务状态失败，显示的可能不是最新数据{error instanceof Error && error.message ? `：${error.message}` : ""}</span>
          <Button variant="outline" size="sm" onClick={handleRefresh} className="gap-1.5 h-7 shrink-0">
            <RefreshCcw className="w-3.5 h-3.5" /> 重试
          </Button>
        </div>
      )}

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
          </div>
          <div className="flex-1 overflow-auto p-4 flex flex-col items-center justify-start bg-muted/50">
             <SourcePreview
               url={api.importTaskSourceUrl(taskId, fileType)}
               file={fileType === "paper" ? task.paperFile : task.answerFile}
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
                 <QuestionCard key={q.id} index={idx + 1} question={q} taskId={taskId} />
               ))
             )}
          </div>
        </div>
      </div>
    </div>
  );
}
