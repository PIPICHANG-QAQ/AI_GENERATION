import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { ArrowLeft } from "lucide-react";
import { ImportWorkbenchTask } from "./ImportWorkbenchTask";

export function ImportWorkbench({ taskId, onBack }: { taskId: string; onBack: () => void }) {
  const { data: selectedTask } = useQuery({
    queryKey: ["importTask", taskId],
    queryFn: () => api.getImportTask(taskId),
    enabled: !!taskId,
    refetchInterval: (query) => (query.state.data?.status === "处理中" ? 5000 : false),
  });

  const navQuestions: any[] = selectedTask?.questions ?? [];
  const selectedProcessing = selectedTask?.status === "处理中";

  const scrollToQuestion = (questionId: string) => {
    const el = document.getElementById(`import-q-${questionId}`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const navButtonClass = (status?: string) => {
    if (status === "已入库") return "bg-primary text-primary-foreground border-primary";
    if (status === "已校验") return "bg-success/10 text-success border-success/40 hover:bg-success/20";
    return "bg-card text-foreground border-border hover:border-primary/50 hover:text-primary";
  };

  return (
    <div className="flex h-full gap-4 relative overflow-hidden">
      <div className="w-80 flex-shrink-0 bg-card border border-border rounded-lg elevation-1 flex flex-col overflow-hidden">
        <div className="p-4 border-b border-border bg-muted/40 font-medium flex items-center justify-between gap-2">
          <span>题目导航</span>
          <Button type="button" size="sm" variant="outline" onClick={onBack} className="gap-1.5">
            <ArrowLeft className="w-3.5 h-3.5" />
            返回
          </Button>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto p-4">
          {selectedProcessing ? (
            <div className="text-sm text-muted-foreground text-center py-4">
              OCR 处理中，完成后将生成题目导航
            </div>
          ) : navQuestions.length === 0 ? (
            <div className="text-sm text-muted-foreground text-center py-4">暂无题目</div>
          ) : (
            <>
              <div className="grid grid-cols-6 gap-2">
                {navQuestions.map((question: any, idx: number) => (
                  <button
                    key={question.id}
                    type="button"
                    onClick={() => scrollToQuestion(question.id)}
                    className={`h-9 rounded-md border text-sm font-medium transition-colors ${navButtonClass(question.status)}`}
                    title={`第 ${idx + 1} 题 · ${question.status || "待校验"}`}
                  >
                    {idx + 1}
                  </button>
                ))}
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded-sm bg-primary" />已入库</span>
                <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded-sm bg-success/20 border border-success/40" />已校验</span>
                <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded-sm bg-card border border-border" />待校验</span>
              </div>
            </>
          )}
        </div>
      </div>

      <div className="flex-1 bg-card border border-border rounded-lg elevation-1 flex flex-col overflow-hidden relative">
        <ImportWorkbenchTask taskId={taskId} />
      </div>
    </div>
  );
}
