import React, { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { StatusTag } from "@/components/ui/StatusTag";
import { MarkdownRenderer } from "@/components/ui/MarkdownRenderer";
import { getQuestionMarkdown, getQuestionImages, getSubQuestions } from "@/lib/question";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { useToast } from "@/hooks/use-toast";
import { Edit2, Eye, EyeOff, Trash2, Plus } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { QuestionEditor } from "./QuestionEditor";
import { QuestionFilters, Filters, emptyFilters, hasActiveFilters } from "./QuestionFilters";
import { PaginationBar } from "@/components/common/PaginationBar";

const PAGE_SIZE = 5;

export function QuestionList({ search, setSearch }: { search: string, setSearch: (v: string) => void }) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [editingQuestion, setEditingQuestion] = useState<any | null>(null);
  const [viewingQuestion, setViewingQuestion] = useState<any | null>(null);
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [page, setPage] = useState(1);
  const [showAnswers, setShowAnswers] = useState(true);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const toggleSelect = (id: string) =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const { data: questions, isLoading } = useQuery({
    queryKey: ["questions", search, filters, page],
    queryFn: () =>
      api
        .getQuestions({ keyword: search, ...filters, page, pageSize: PAGE_SIZE })
        .catch(() => ({ items: [], total: 0 })),
  });

  const total = questions?.total ?? 0;
  const questionItems: any[] = Array.isArray(questions?.items) ? questions.items : [];
  const currentPageIds = questionItems.map((question: any) => String(question.id));
  const selectedCurrentPageIds = currentPageIds.filter((id) => selectedIds.has(id));
  const currentPageAllSelected = currentPageIds.length > 0 && selectedCurrentPageIds.length === currentPageIds.length;

  useEffect(() => {
    setPage(1);
  }, [search, filters]);

  useEffect(() => {
    const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
    if (page > pageCount) setPage(pageCount);
  }, [total, page]);

  const createMutation = useMutation({
    mutationFn: api.createQuestion,
    onSuccess: () => {
      toast({ title: "创建成功" });
      setEditingQuestion(null);
      queryClient.invalidateQueries({ queryKey: ["questions"] });
    },
    onError: (err: any) => toast({ title: "创建失败", description: err.message, variant: "destructive" })
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string, data: any }) => api.updateQuestion(id, data),
    onSuccess: () => {
      toast({ title: "保存成功" });
      setEditingQuestion(null);
      queryClient.invalidateQueries({ queryKey: ["questions"] });
    },
    onError: (err: any) => toast({ title: "保存失败", description: err.message, variant: "destructive" })
  });

  const deleteMutation = useMutation({
    mutationFn: api.deleteQuestion,
    onSuccess: (_res, id) => {
      toast({ title: "删除成功", description: "题目已从题库中移除" });
      queryClient.invalidateQueries({ queryKey: ["questions"] });
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    },
    onError: (err: any) => toast({ title: "删除失败", description: err.message, variant: "destructive" })
  });

  const batchDeleteMutation = useMutation({
    mutationFn: (ids: string[]) => api.deleteQuestions(ids),
    onSuccess: (res: any) => {
      toast({ title: `已删除 ${res?.deleted ?? 0} 道题目` });
      queryClient.invalidateQueries({ queryKey: ["questions"] });
      setSelectedIds(new Set());
    },
    onError: (err: any) => toast({ title: "批量删除失败", description: err.message, variant: "destructive" })
  });

  const handleDelete = (id: string) => {
    if (window.confirm("确认删除这道题吗？删除后不会在题库中心显示。")) {
      deleteMutation.mutate(id);
    }
  };

  const handleBatchDelete = () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    if (!window.confirm(`确定删除选中的 ${ids.length} 道题目？此操作不可撤销。`)) return;
    batchDeleteMutation.mutate(ids);
  };

  const selectCurrentPageQuestions = () => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      currentPageIds.forEach((id) => next.add(id));
      return next;
    });
  };

  const metaPill = "text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded-md border border-border";

  return (
    <div className="max-w-6xl mx-auto space-y-4">
      <QuestionFilters
        search={search}
        setSearch={setSearch}
        filters={filters}
        setFilters={setFilters}
        actions={
          <Button onClick={() => setEditingQuestion({})} className="gap-2">
            <Plus className="w-4 h-4" /> 新建题目
          </Button>
        }
      />

      {isLoading ? (
        <div className="text-center py-12 bg-card rounded-lg border border-border">
          <p className="text-muted-foreground">加载中...</p>
        </div>
      ) : questionItems.length > 0 ? (
        <div className="space-y-4">
          <div className="flex items-center justify-between mb-2">
            <div className="text-sm text-muted-foreground">共 {total || questionItems.length} 道题目</div>
            <div className="flex items-center gap-2">
              {currentPageIds.length > 0 && !currentPageAllSelected && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={selectCurrentPageQuestions}
                >
                  全选
                </Button>
              )}
              {selectedIds.size > 0 && (
                <>
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={handleBatchDelete}
                    disabled={batchDeleteMutation.isPending}
                  >
                    <Trash2 className="w-3.5 h-3.5 mr-1.5" /> 删除所选 ({selectedIds.size})
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setSelectedIds(new Set())}
                  >
                    全部取消
                  </Button>
                </>
              )}
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5"
                onClick={() => setShowAnswers((s) => !s)}
              >
                {showAnswers ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                {showAnswers ? "隐藏答案和解析" : "显示答案和解析"}
              </Button>
            </div>
          </div>
          {questionItems.map((q: any) => (
            <div key={q.id} className="bg-card p-5 rounded-lg border border-border elevation-1 hover:border-primary/30 hover:elevation-2 transition-all group">
              {(() => {
                const subQuestions = getSubQuestions(q);
                return (
                  <>
              <div className="flex justify-between items-start mb-3">
                <div className="flex gap-2 flex-wrap items-center">
                  <StatusTag status={q.type || "unknown"} type="qtype" />
                  <StatusTag status={q.difficulty || "medium"} type="difficulty" />
                  {subQuestions.length > 0 && (
                    <span className="text-xs text-primary bg-primary/10 border border-primary/20 px-2 py-0.5 rounded-md">
                      含 {subQuestions.length} 小问
                    </span>
                  )}
                  {q.subject && <span className={metaPill}>{q.subject}</span>}
                  {q.grade && <span className={metaPill}>{q.grade}</span>}
                  {q.region && <span className={metaPill}>{q.region}</span>}
                  {q.year && <span className={metaPill}>{q.year}年</span>}
                  {q.knowledgePoints?.map((kp: string) => (
                    <span key={kp} className={metaPill}>{kp}</span>
                  ))}
                </div>
                <div className={`flex items-center space-x-2 transition-opacity ${selectedIds.has(q.id) ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}>
                  <Button variant="ghost" size="sm" onClick={() => setViewingQuestion(q)} className="h-8 w-8 p-0 text-muted-foreground hover:text-primary">
                    <Eye className="w-4 h-4" />
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => setEditingQuestion(q)} className="h-8 w-8 p-0 text-muted-foreground hover:text-primary">
                    <Edit2 className="w-4 h-4" />
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => handleDelete(q.id)} className="h-8 w-8 p-0 text-muted-foreground hover:text-destructive">
                    <Trash2 className="w-4 h-4" />
                  </Button>
                  <div className="h-8 w-8 flex items-center justify-center shrink-0">
                    <Checkbox
                      checked={selectedIds.has(q.id)}
                      onCheckedChange={() => toggleSelect(q.id)}
                      className="shrink-0"
                    />
                  </div>
                </div>
              </div>
              <div className="mb-4">
                <MarkdownRenderer
                  content={getQuestionMarkdown(q)}
                  images={getQuestionImages(q)}
                  questionType={q.type}
                  options={q.options}
                />
              </div>
              {subQuestions.length > 0 && (
                <div className="mb-4 space-y-3 rounded-md border border-primary/15 bg-primary/5 p-3">
                  {subQuestions.map((sub: any, subIndex: number) => (
                    <div key={sub.id || subIndex} className="rounded-md border border-border bg-card p-3">
                      <div className="flex flex-wrap items-center gap-2 mb-2">
                        <span className="text-xs font-semibold text-foreground">{sub.label || `(${subIndex + 1})`}</span>
                        <StatusTag status={sub.type || q.type || "unknown"} type="qtype" />
                        <StatusTag status={sub.difficulty || q.difficulty || "medium"} type="difficulty" />
                        <span className="text-xs text-muted-foreground">{Number(sub.score) || 0} 分</span>
                      </div>
                      <div className="text-sm text-foreground/80">
                        <MarkdownRenderer
                          content={getQuestionMarkdown(sub)}
                          images={getQuestionImages(sub)}
                          questionType={sub.type || q.type}
                          options={sub.options}
                        />
                      </div>
                      {showAnswers && (sub.answer || sub.analysis) && (
                        <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
                          <div className="bg-muted/50 p-3 rounded-md text-foreground/80 min-w-0">
                            <span className="font-medium text-foreground block mb-1">答案：</span>
                            <div className="line-clamp-2">
                              {sub.answer ? <MarkdownRenderer content={sub.answer} /> : "暂无"}
                            </div>
                          </div>
                          <div className="bg-muted/50 p-3 rounded-md text-foreground/80 min-w-0">
                            <span className="font-medium text-foreground block mb-1">解析：</span>
                            <div className="line-clamp-2">
                              {sub.analysis ? <MarkdownRenderer content={sub.analysis} /> : "暂无"}
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {showAnswers && (
                <div className={`flex flex-col sm:flex-row gap-4 text-sm ${subQuestions.length > 0 ? "hidden" : ""}`}>
                  <div className="flex-1 bg-muted/50 p-3 rounded-md text-foreground/80 min-w-0">
                    <span className="font-medium text-foreground block mb-1">答案：</span>
                    <div className="line-clamp-2">
                      {q.answer ? <MarkdownRenderer content={q.answer} /> : "暂无"}
                    </div>
                  </div>
                  <div className="flex-1 bg-muted/50 p-3 rounded-md text-foreground/80 min-w-0">
                    <span className="font-medium text-foreground block mb-1">解析：</span>
                    <div className="line-clamp-2">
                      {q.analysis ? <MarkdownRenderer content={q.analysis} /> : "暂无"}
                    </div>
                  </div>
                </div>
              )}
                  </>
                );
              })()}
            </div>
          ))}
          <PaginationBar
            page={page}
            pageSize={PAGE_SIZE}
            total={total}
            onPageChange={setPage}
            className="pt-2"
          />
        </div>
      ) : (
        <div className="text-center py-16 bg-card rounded-lg border border-dashed border-border">
          <p className="text-muted-foreground">{hasActiveFilters(filters) || search ? "没有符合条件的题目" : "暂无入库题目"}</p>
        </div>
      )}

      <Dialog open={!!viewingQuestion} onOpenChange={(open) => !open && setViewingQuestion(null)}>
        <DialogContent className="max-w-3xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>查看题目</DialogTitle>
          </DialogHeader>
          {viewingQuestion && (
            <div className="space-y-6 mt-4">
              {(() => {
                const subQuestions = getSubQuestions(viewingQuestion);
                return (
                  <>
              <div className="flex gap-2 flex-wrap items-center">
                <StatusTag status={viewingQuestion.type || "unknown"} type="qtype" />
                <StatusTag status={viewingQuestion.difficulty || "medium"} type="difficulty" />
                {subQuestions.length > 0 && (
                  <span className="text-xs text-primary bg-primary/10 border border-primary/20 px-2 py-0.5 rounded-md">
                    含 {subQuestions.length} 小问
                  </span>
                )}
                {(viewingQuestion.subject || viewingQuestion.grade) && <span className={metaPill}>{[viewingQuestion.subject, viewingQuestion.grade].filter(Boolean).join(" ")}</span>}
                {viewingQuestion.year && <span className={metaPill}>{viewingQuestion.year}年</span>}
                {viewingQuestion.region && <span className={metaPill}>{viewingQuestion.region}</span>}
                {viewingQuestion.source && <span className={metaPill}>来源：{viewingQuestion.source}</span>}
              </div>
              <div>
                <h4 className="font-semibold mb-2">题干</h4>
                <div className="p-4 border border-border rounded-md bg-muted/50">
                  <MarkdownRenderer
                    content={getQuestionMarkdown(viewingQuestion)}
                    images={getQuestionImages(viewingQuestion)}
                    questionType={viewingQuestion.type}
                    options={viewingQuestion.options}
                  />
                </div>
              </div>
              {subQuestions.length > 0 && (
                <div>
                  <h4 className="font-semibold mb-2">小问</h4>
                  <div className="space-y-3">
                    {subQuestions.map((sub: any, subIndex: number) => (
                      <div key={sub.id || subIndex} className="p-4 border border-border rounded-md bg-muted/40 space-y-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium text-foreground">{sub.label || `(${subIndex + 1})`}</span>
                          <StatusTag status={sub.type || viewingQuestion.type || "unknown"} type="qtype" />
                          <StatusTag status={sub.difficulty || viewingQuestion.difficulty || "medium"} type="difficulty" />
                          <span className="text-xs text-muted-foreground">{Number(sub.score) || 0} 分</span>
                        </div>
                        <MarkdownRenderer
                          content={getQuestionMarkdown(sub)}
                          images={getQuestionImages(sub)}
                          questionType={sub.type || viewingQuestion.type}
                          options={sub.options}
                        />
                        <div className="grid gap-3 sm:grid-cols-2">
                          <div className="rounded-md border border-border bg-card p-3">
                            <span className="font-medium text-foreground block mb-1">答案：</span>
                            <MarkdownRenderer content={sub.answer || "暂无"} />
                          </div>
                          <div className="rounded-md border border-border bg-card p-3">
                            <span className="font-medium text-foreground block mb-1">解析：</span>
                            <MarkdownRenderer content={sub.analysis || "暂无"} />
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {viewingQuestion.knowledgePoints?.length > 0 && (
                <div>
                  <h4 className="font-semibold mb-2">知识点</h4>
                  <div className="flex flex-wrap gap-1">
                    {viewingQuestion.knowledgePoints.map((kp: string) => (
                      <span key={kp} className="text-xs bg-card border border-border px-2 py-0.5 rounded-md text-muted-foreground">{kp}</span>
                    ))}
                  </div>
                </div>
              )}
              {subQuestions.length === 0 && (
                <>
                  <div>
                    <h4 className="font-semibold mb-2">答案</h4>
                    <div className="p-4 border border-border rounded-md bg-muted/50">
                      <MarkdownRenderer content={viewingQuestion.answer || "暂无"} />
                    </div>
                  </div>
                  <div>
                    <h4 className="font-semibold mb-2">解析</h4>
                    <div className="p-4 border border-border rounded-md bg-muted/50">
                      <MarkdownRenderer content={viewingQuestion.analysis || "暂无"} />
                    </div>
                  </div>
                </>
              )}
              {viewingQuestion.createdAt && (
                <p className="text-xs text-muted-foreground">创建时间：{new Date(viewingQuestion.createdAt).toLocaleString()}</p>
              )}
                  </>
                );
              })()}
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={!!editingQuestion} onOpenChange={(open) => !open && setEditingQuestion(null)}>
        <DialogContent className="max-w-6xl w-full h-[90vh] flex flex-col p-0 overflow-hidden">
          <DialogHeader className="px-6 py-4 border-b border-border shrink-0">
            <DialogTitle>{editingQuestion?.id ? "编辑题目" : "新建题目"}</DialogTitle>
          </DialogHeader>
          <div className="flex-1 overflow-hidden relative">
            {editingQuestion && (
              <QuestionEditor
                question={editingQuestion}
                onCancel={() => setEditingQuestion(null)}
                onSave={(data) => {
                  if (editingQuestion.id) {
                    updateMutation.mutate({ id: editingQuestion.id, data });
                  } else {
                    createMutation.mutate(data);
                  }
                }}
              />
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
