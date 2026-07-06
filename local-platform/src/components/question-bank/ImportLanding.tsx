import React, { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { StatusTag } from "@/components/ui/StatusTag";
import { useToast } from "@/hooks/use-toast";
import {
  Check,
  ChevronRight,
  FileCheck2,
  FilePlus,
  FileText,
  ListChecks,
  Pencil,
  ScanLine,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";

const OCR_ACCEPT = ".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.md,.markdown,.doc,.docx,.pptx,.xlsx";

function FileDropField({
  label,
  required = false,
  file,
  onSelect,
  accept,
  id,
}: {
  label: string;
  required?: boolean;
  file: File | null;
  onSelect: (file: File | null) => void;
  accept: string;
  id: string;
}) {
  const [dragging, setDragging] = useState(false);

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>
        {label} {required && <span className="text-destructive">*</span>}
      </Label>
      <label
        htmlFor={id}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const dropped = e.dataTransfer.files?.[0];
          if (dropped) onSelect(dropped);
        }}
        className={`group relative flex items-center gap-3 px-3.5 py-3 rounded-xl border border-dashed cursor-pointer transition-colors ${
          dragging
            ? "border-primary bg-primary/5"
            : file
              ? "border-success/50 bg-success/[0.04]"
              : "border-border bg-muted/30 hover:border-primary/50 hover:bg-accent/40"
        }`}
      >
        <div
          className={`w-9 h-9 rounded-lg shrink-0 flex items-center justify-center transition-colors ${
            file
              ? "bg-success/12 text-success"
              : "bg-card text-muted-foreground group-hover:text-primary"
          }`}
        >
          {file ? <FileCheck2 className="w-4 h-4" /> : <UploadCloud className="w-4 h-4" />}
        </div>
        <div className="min-w-0 flex-1">
          {file ? (
            <>
              <div className="text-sm font-medium text-foreground truncate" title={file.name}>
                {file.name}
              </div>
              <div className="text-[11px] text-muted-foreground">
                {(file.size / 1024).toFixed(0)} KB · 点击可重新选择
              </div>
            </>
          ) : (
            <>
              <div className="text-sm text-foreground/80">点击选择或拖拽文件到此处</div>
              <div className="text-[11px] text-muted-foreground">支持 PDF / 图片 / Office / Markdown</div>
            </>
          )}
        </div>
        {file && (
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault();
              onSelect(null);
            }}
            className="shrink-0 p-1.5 rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
            title="移除文件"
            aria-label="移除文件"
          >
            <X className="w-4 h-4" />
          </button>
        )}
        <input
          id={id}
          type="file"
          onChange={(e) => onSelect(e.target.files?.[0] || null)}
          accept={accept}
          className="hidden"
        />
      </label>
    </div>
  );
}

export function ImportLanding({ onOpenTask }: { onOpenTask: (id: string) => void }) {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const { data: tasks, isLoading: tasksLoading } = useQuery({
    queryKey: ["importTasks"],
    queryFn: () => api.getImportTasks().catch(() => ({ items: [] })),
  });

  const [formData, setFormData] = useState({
    stage: "高中",
    subject: "数学",
    grade: "高一",
    region: "",
    year: "2026",
    title: "",
  });
  const [paperFile, setPaperFile] = useState<File | null>(null);
  const [answerFile, setAnswerFile] = useState<File | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const taskItems: any[] = tasks?.items ?? [];

  const createMutation = useMutation({
    mutationFn: (data: FormData) => api.createImportTask(data),
    onSuccess: (res: any) => {
      toast({ title: "导入任务已创建，OCR 正在处理中" });
      queryClient.invalidateQueries({ queryKey: ["importTasks"] });
      setFormData((prev) => ({ ...prev, title: "" }));
      setPaperFile(null);
      setAnswerFile(null);
      if (res?.id) onOpenTask(res.id);
    },
    onError: (err: any) =>
      toast({ title: "创建失败", description: err.message, variant: "destructive" }),
  });

  const renameMutation = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) => api.renameImportTask(id, title),
    onSuccess: () => {
      toast({ title: "已重命名" });
      queryClient.invalidateQueries({ queryKey: ["importTasks"] });
      setRenamingId(null);
      setRenameValue("");
    },
    onError: (err: any) =>
      toast({ title: "重命名失败", description: err.message, variant: "destructive" }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteImportTask(id),
    onSuccess: (_res, id) => {
      toast({ title: "任务已删除" });
      queryClient.invalidateQueries({ queryKey: ["importTasks"] });
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    },
    onError: (err: any) =>
      toast({ title: "删除失败", description: err.message, variant: "destructive" }),
  });

  const batchDeleteMutation = useMutation({
    mutationFn: (ids: string[]) => api.deleteImportTasks(ids),
    onSuccess: (res: any) => {
      toast({ title: `已删除 ${res?.deleted ?? 0} 个任务` });
      queryClient.invalidateQueries({ queryKey: ["importTasks"] });
      setSelectedIds(new Set());
    },
    onError: (err: any) =>
      toast({ title: "批量删除失败", description: err.message, variant: "destructive" }),
  });

  const toggleSelected = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const startRename = (e: React.MouseEvent, task: any) => {
    e.stopPropagation();
    setRenamingId(task.id);
    setRenameValue(task.title);
  };

  const submitRename = (id: string) => {
    const title = renameValue.trim();
    if (!title) {
      toast({ title: "提示", description: "标题不能为空", variant: "destructive" });
      return;
    }
    renameMutation.mutate({ id, title });
  };

  const handleDelete = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (!window.confirm("确定删除该导入任务？此操作不可撤销。")) return;
    deleteMutation.mutate(id);
  };

  const handleBatchDelete = () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    if (!window.confirm(`确定删除选中的 ${ids.length} 个任务？此操作不可撤销。`)) return;
    batchDeleteMutation.mutate(ids);
  };

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    if (!paperFile) {
      toast({ title: "提示", description: "请先上传试卷文件", variant: "destructive" });
      return;
    }
    if (!formData.title.trim()) {
      toast({ title: "提示", description: "请输入任务标题", variant: "destructive" });
      return;
    }
    const fd = new FormData();
    Object.entries(formData).forEach(([key, value]) => fd.append(key, value));
    fd.append("paperFile", paperFile);
    if (answerFile) fd.append("answerFile", answerFile);
    createMutation.mutate(fd);
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="bg-card border border-border rounded-2xl elevation-2 overflow-hidden">
        <div className="relative px-6 py-5 border-b border-border gradient-card-warm overflow-hidden">
          <div className="relative flex items-center gap-3.5">
            <div className="w-11 h-11 rounded-xl gradient-primary flex items-center justify-center text-primary-foreground shrink-0 shadow-glow-primary ring-gloss">
              <ScanLine className="w-5 h-5" />
            </div>
            <div>
              <div className="text-base font-semibold tracking-tight">新建 OCR 任务</div>
              <div className="text-xs text-muted-foreground mt-0.5">上传试卷与答案，自动识别并生成待校验题目</div>
            </div>
          </div>
        </div>

        <form onSubmit={handleCreate} className="p-6 space-y-6">
          <section className="space-y-4">
            <div className="text-eyebrow text-muted-foreground/80 uppercase">任务信息</div>
            <div className="space-y-1.5">
              <Label htmlFor="task-title">
                标题 <span className="text-destructive">*</span>
              </Label>
              <Input
                id="task-title"
                value={formData.title}
                onChange={(e) => setFormData({ ...formData, title: e.target.value })}
                placeholder="例如：2026年期中考试"
              />
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-4">
              <div className="space-y-1.5">
                <Label>学段</Label>
                <Input value={formData.stage} onChange={(e) => setFormData({ ...formData, stage: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label>学科</Label>
                <Input value={formData.subject} onChange={(e) => setFormData({ ...formData, subject: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label>年级</Label>
                <Input value={formData.grade} onChange={(e) => setFormData({ ...formData, grade: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label>地区</Label>
                <Input
                  value={formData.region}
                  onChange={(e) => setFormData({ ...formData, region: e.target.value })}
                  placeholder="选填，例如：北京"
                />
              </div>
              <div className="space-y-1.5">
                <Label>年份</Label>
                <Input value={formData.year} onChange={(e) => setFormData({ ...formData, year: e.target.value })} />
              </div>
            </div>
          </section>

          <div className="h-px bg-border" />

          <section className="space-y-4">
            <div className="text-eyebrow text-muted-foreground/80 uppercase">上传文件</div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <FileDropField
                id="paper-file"
                label="试卷文件"
                required
                file={paperFile}
                onSelect={setPaperFile}
                accept={OCR_ACCEPT}
              />
              <FileDropField
                id="answer-file"
                label="答案文件 (选填)"
                file={answerFile}
                onSelect={setAnswerFile}
                accept={OCR_ACCEPT}
              />
            </div>
          </section>

          <div className="flex justify-end pt-1">
            <Button type="submit" className="gap-2 min-w-44 ring-gloss shadow-glow-primary" disabled={createMutation.isPending}>
              <ScanLine className="w-4 h-4" />
              {createMutation.isPending ? "处理中..." : "创建并 OCR"}
            </Button>
          </div>
        </form>
      </div>

      <div className="bg-card border border-border rounded-2xl elevation-1 overflow-hidden">
        <div className="px-5 py-4 border-b border-border bg-muted/30 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg gradient-primary-soft flex items-center justify-center text-primary shrink-0">
              <ListChecks className="w-4 h-4" />
            </div>
            <div>
              <div className="font-semibold text-sm tracking-tight">任务记录</div>
              <div className="text-[11px] text-muted-foreground">共 {taskItems.length} 个任务</div>
            </div>
          </div>
          {selectedIds.size > 0 && (
            <div className="flex items-center gap-2">
              <Button type="button" size="sm" variant="destructive" onClick={handleBatchDelete} disabled={batchDeleteMutation.isPending}>
                <Trash2 className="w-3.5 h-3.5 mr-1" />
                删除所选 ({selectedIds.size})
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={() => setSelectedIds(new Set())}>
                全部取消
              </Button>
            </div>
          )}
        </div>

        <div className="p-3 space-y-2">
          {tasksLoading ? (
            <div className="text-center py-6 text-muted-foreground text-sm">加载中...</div>
          ) : taskItems.length > 0 ? (
            taskItems.map((task: any) => (
              <div
                key={task.id}
                onClick={() => (renamingId === task.id ? undefined : onOpenTask(task.id))}
                className={`group p-3 rounded-xl border transition-all ${renamingId === task.id ? "cursor-default" : "cursor-pointer"} bg-card border-border hover:border-primary/40 hover:bg-primary/[0.02] hover:elevation-2`}
              >
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-lg bg-muted/60 text-muted-foreground flex items-center justify-center shrink-0 group-hover:bg-primary/10 group-hover:text-primary transition-colors">
                    <FileText className="w-4 h-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    {renamingId === task.id ? (
                      <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                        <Input
                          autoFocus
                          value={renameValue}
                          onChange={(e) => setRenameValue(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") submitRename(task.id);
                            if (e.key === "Escape") {
                              setRenamingId(null);
                              setRenameValue("");
                            }
                          }}
                          className="h-8 text-sm"
                        />
                        <button
                          type="button"
                          onClick={() => submitRename(task.id)}
                          disabled={renameMutation.isPending}
                          className="shrink-0 p-1 text-success hover:bg-success/10 rounded"
                          title="确认"
                          aria-label="确认重命名"
                        >
                          <Check className="w-4 h-4" />
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setRenamingId(null);
                            setRenameValue("");
                          }}
                          className="shrink-0 p-1 text-muted-foreground hover:bg-muted rounded"
                          title="取消"
                          aria-label="取消重命名"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      </div>
                    ) : (
                      <>
                        <div className="flex items-center gap-1">
                          <div className="font-medium text-foreground truncate" title={task.title}>
                            {task.title}
                          </div>
                          <button
                            type="button"
                            onClick={(e) => startRename(e, task)}
                            className="shrink-0 p-1 text-muted-foreground hover:text-primary hover:bg-primary/10 rounded opacity-0 group-hover:opacity-100 transition-opacity"
                            title="重命名"
                            aria-label="重命名"
                          >
                            <Pencil className="w-3.5 h-3.5" />
                          </button>
                          <button
                            type="button"
                            onClick={(e) => handleDelete(e, task.id)}
                            disabled={deleteMutation.isPending}
                            className="shrink-0 p-1 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded opacity-0 group-hover:opacity-100 transition-opacity"
                            title="删除"
                            aria-label="删除"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                        <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                          <span>{[task.subject, task.grade, task.year].filter(Boolean).join(" ")}</span>
                          {typeof task.questionCount === "number" && (
                            <>
                              <span className="text-border">·</span>
                              <span>{task.questionCount} 题</span>
                            </>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                  {renamingId !== task.id && (
                    <div className="flex items-center gap-2 shrink-0">
                      <StatusTag status={task.status || "处理中"} type="task" />
                      <input
                        type="checkbox"
                        checked={selectedIds.has(task.id)}
                        onClick={(e) => e.stopPropagation()}
                        onChange={() => toggleSelected(task.id)}
                        className={`h-4 w-4 shrink-0 cursor-pointer accent-primary transition-opacity ${selectedIds.has(task.id) ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}
                        aria-label="选择任务"
                      />
                      <ChevronRight className="w-4 h-4 text-muted-foreground/60 group-hover:text-primary transition-colors" />
                    </div>
                  )}
                </div>
              </div>
            ))
          ) : (
            <div className="text-center py-10 text-muted-foreground text-sm">
              <FilePlus className="w-8 h-8 mx-auto mb-2 text-muted-foreground/40" />
              暂无任务记录，请在上方新建 OCR 任务
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
