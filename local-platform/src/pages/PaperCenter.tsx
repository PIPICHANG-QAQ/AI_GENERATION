import React, { useEffect, useState } from "react";
import { Layout } from "@/components/layout/Layout";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/hooks/use-toast";
import { Checkbox } from "@/components/ui/checkbox";
import { StatusTag } from "@/components/ui/StatusTag";
import { MarkdownRenderer } from "@/components/ui/MarkdownRenderer";
import { getQuestionMarkdown, getQuestionImages, getSubQuestions } from "@/lib/question";
import { BookOpen, Edit2, FileDown, FileText, GraduationCap, Layers, Plus, Search, Trash2, X } from "lucide-react";
import { PaperEditor } from "@/components/paper/PaperEditor";
import { QuestionFilters, Filters, emptyFilters, hasActiveFilters } from "@/components/question-bank/QuestionFilters";
import { PaginationBar } from "@/components/common/PaginationBar";

const SELECT_PAGE_SIZE = 5;
const PAPER_PAGE_SIZE = 6;

export default function PaperCenter() {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const [editingPaperId, setEditingPaperId] = useState<string | null>(null);
  const [draftQuestions, setDraftQuestions] = useState<any[] | null>(null);
  const [isCreating, setIsCreating] = useState(false);

  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [selected, setSelected] = useState<any[]>([]);
  const [selectedSubSelections, setSelectedSubSelections] = useState<Record<string, string[]>>({});
  const [selectPage, setSelectPage] = useState(1);
  const [paperPage, setPaperPage] = useState(1);
  const [selectedPaperIds, setSelectedPaperIds] = useState<Set<string>>(new Set());
  const [paperSubject, setPaperSubject] = useState("");
  const [paperGrade, setPaperGrade] = useState("");
  const [paperKeyword, setPaperKeyword] = useState("");

  const { data: questionsData, isLoading: isLoadingQuestions } = useQuery({
    queryKey: ["questions", "paper-selection", search, filters, selectPage],
    queryFn: () =>
      api
        .getQuestions({ keyword: search, ...filters, page: selectPage, pageSize: SELECT_PAGE_SIZE })
        .catch(() => ({ items: [], total: 0 })),
    enabled: isCreating
  });

  const { data: papersData, isLoading: isLoadingPapers } = useQuery({
    queryKey: ["papers", paperPage, paperSubject, paperGrade, paperKeyword],
    queryFn: () =>
      api.getPapers({
        page: paperPage,
        pageSize: PAPER_PAGE_SIZE,
        subject: paperSubject,
        grade: paperGrade,
        keyword: paperKeyword
      })
  });

  const questionsTotal = questionsData?.total ?? 0;
  const papersTotal = papersData?.total ?? 0;

  useEffect(() => {
    setSelectPage(1);
  }, [search, filters]);

  useEffect(() => {
    const pageCount = Math.max(1, Math.ceil(questionsTotal / SELECT_PAGE_SIZE));
    if (selectPage > pageCount) setSelectPage(pageCount);
  }, [questionsTotal, selectPage]);

  useEffect(() => {
    const pageCount = Math.max(1, Math.ceil(papersTotal / PAPER_PAGE_SIZE));
    if (paperPage > pageCount) setPaperPage(pageCount);
  }, [papersTotal, paperPage]);

  useEffect(() => {
    setPaperPage(1);
  }, [paperSubject, paperGrade, paperKeyword]);

  const deletePaperMutation = useMutation({
    mutationFn: api.deletePaper,
    onSuccess: (_res, id) => {
      toast({ title: "删除成功" });
      queryClient.invalidateQueries({ queryKey: ["papers"] });
      setSelectedPaperIds((prev) => {
        const next = new Set(prev);
        next.delete(id as string);
        return next;
      });
    },
    onError: (err: Error) => toast({ title: "删除失败", description: err.message, variant: "destructive" })
  });

  const batchDeletePapersMutation = useMutation({
    mutationFn: (ids: string[]) => api.deletePapers(ids),
    onSuccess: (res: any) => {
      toast({ title: `已删除 ${res?.deleted ?? 0} 份试卷` });
      queryClient.invalidateQueries({ queryKey: ["papers"] });
      setSelectedPaperIds(new Set());
    },
    onError: (err: Error) => toast({ title: "批量删除失败", description: err.message, variant: "destructive" })
  });

  const togglePaperSelect = (id: string) =>
    setSelectedPaperIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const handleBatchDeletePapers = () => {
    const ids = Array.from(selectedPaperIds);
    if (ids.length === 0) return;
    if (window.confirm(`确认删除选中的 ${ids.length} 份试卷？此操作不可撤销。`)) {
      batchDeletePapersMutation.mutate(ids);
    }
  };

  const selectedIdSet = new Set(selected.map((q) => q.id));
  const toggleSelect = (q: any) => {
    const exists = selected.some((s) => s.id === q.id);
    const subs = getSubQuestions(q);
    setSelected((prev) => exists ? prev.filter((s) => s.id !== q.id) : [...prev, q]);
    setSelectedSubSelections((prev) => {
      const next = { ...prev };
      if (exists) {
        delete next[q.id];
      } else if (subs.length > 0) {
        next[q.id] = subs.map((sub: any) => String(sub.id));
      }
      return next;
    });
  };

  const toggleSelectedSub = (q: any, subId: string) => {
    const subs = getSubQuestions(q);
    if (subs.length === 0) return;
    const allSubIds = subs.map((sub: any) => String(sub.id));
    const current = selectedSubSelections[q.id]?.length ? selectedSubSelections[q.id] : allSubIds;
    const isSelected = current.includes(subId);
    if (isSelected && current.length <= 1) {
      toast({ title: "至少保留一个小问", description: "只要大题在试卷中，就必须纳入至少一个小问。", variant: "destructive" });
      return;
    }
    const nextIds = isSelected ? current.filter((id) => id !== subId) : [...current, subId];
    setSelectedSubSelections((prev) => ({ ...prev, [q.id]: nextIds }));
  };

  const handleGenerate = () => {
    if (selected.length === 0) {
      toast({ title: "提示", description: "请先勾选至少一道题目", variant: "destructive" });
      return;
    }
    setDraftQuestions(selected);
  };

  const resetCreateState = () => {
    setSelected([]);
    setSelectedSubSelections({});
    setSearch("");
    setFilters(emptyFilters);
    setSelectPage(1);
  };

  const handleEditorClose = () => {
    setDraftQuestions(null);
    setEditingPaperId(null);
    setIsCreating(false);
    resetCreateState();
    queryClient.invalidateQueries({ queryKey: ["papers"] });
  };

  const handleCancelCreate = () => {
    setIsCreating(false);
    resetCreateState();
  };

  const handleDeletePaper = (id: string) => {
    if (window.confirm("确认删除这份试卷吗？删除后不会在组卷中心显示。")) {
      deletePaperMutation.mutate(id);
    }
  };

  if (editingPaperId) {
    return <PaperEditor paperId={editingPaperId} onClose={handleEditorClose} />;
  }

  if (draftQuestions) {
    return (
      <PaperEditor
        initialQuestions={draftQuestions}
        initialSubSelections={selectedSubSelections}
        onClose={handleEditorClose}
      />
    );
  }

  const questionsList = questionsData?.items || [];
  const papersList = papersData?.items || [];

  return (
    <Layout>
      <div className="px-6 pt-6 shrink-0 z-10 relative">
        <div className="max-w-6xl mx-auto bg-card border border-border/60 rounded-2xl elevation-1 px-6 py-5 flex items-center gap-4">
          <div className="w-12 h-12 rounded-[1.35rem] gradient-tech flex items-center justify-center text-primary-foreground shrink-0 shadow-glow-tech ring-gloss">
            <FileText className="w-6 h-6" strokeWidth={1.75} />
          </div>
          <div className="min-w-0">
            <div className="text-eyebrow uppercase text-muted-foreground/70 mb-1">试卷管理</div>
            <h1 className="text-2xl font-bold gradient-text tracking-tight leading-tight">组卷中心</h1>
            <p className="text-sm font-light text-muted-foreground mt-1 leading-relaxed">
              {isCreating ? "按条件筛选题库并勾选题目，生成后可继续编辑并导出。" : "管理试卷记录，点击新建试卷开始组卷。"}
            </p>
          </div>
          {!isCreating && (
            <Button onClick={() => setIsCreating(true)} className="ml-auto shrink-0">
              <Plus className="w-4 h-4 mr-1.5" /> 新建试卷
            </Button>
          )}
        </div>
      </div>
      
      <div className="flex-1 overflow-auto px-6 pt-4 pb-6 [scrollbar-gutter:stable_both-edges]">
        <div className="max-w-6xl mx-auto space-y-6">

          {isCreating ? (
          /* 新建试卷 */
          <div className="bg-card p-6 rounded-2xl border border-border elevation-2">
            <div className="mb-6 flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl gradient-primary-soft flex items-center justify-center text-primary shrink-0">
                <Plus className="w-5 h-5" />
              </div>
              <div>
                <h2 className="text-base font-semibold text-foreground tracking-tight">新建试卷</h2>
                <p className="text-xs text-muted-foreground mt-0.5">按条件筛选题库并勾选题目，生成后可继续编辑。</p>
              </div>
            </div>
            
            <div className="space-y-6">
              <QuestionFilters
                search={search}
                setSearch={setSearch}
                filters={filters}
                setFilters={setFilters}
                actions={
                  <div className="flex items-center gap-2">
                    <Button variant="outline" onClick={handleCancelCreate}>取消</Button>
                    <Button onClick={handleGenerate} disabled={isLoadingQuestions}>
                      {isLoadingQuestions ? "加载题目中..." : "生成试卷"}
                    </Button>
                  </div>
                }
              />

              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-medium text-foreground">选择题目</h3>
                  <div className="flex items-center space-x-3 text-sm">
                    <span className="text-muted-foreground">已选 <span className="font-medium text-primary">{selected.length}</span> 题</span>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setSelected([]);
                        setSelectedSubSelections({});
                      }}
                      disabled={selected.length === 0}
                      className="h-8"
                    >
                      清空已选
                    </Button>
                  </div>
                </div>
                
                <div className="border border-border rounded-md bg-card max-h-[500px] overflow-y-auto">
                  {isLoadingQuestions ? (
                    <div className="py-12 text-center text-muted-foreground">加载题目中...</div>
                  ) : questionsList.length > 0 ? (
                    <div className="divide-y divide-border">
                      {questionsList.map((q: any) => {
                        const subs = getSubQuestions(q);
                        const isSelected = selectedIdSet.has(q.id);
                        const selectedSubIds = selectedSubSelections[q.id]?.length
                          ? selectedSubSelections[q.id]
                          : subs.map((sub: any) => String(sub.id));
                        const selectedSubIdSet = new Set(selectedSubIds);
                        const selectedSubScore = subs
                          .filter((sub: any) => selectedSubIdSet.has(String(sub.id)))
                          .reduce((sum: number, sub: any) => sum + (Number(sub.score) || 0), 0);
                        return (
                        <div key={q.id} className={`p-4 flex gap-4 transition-colors hover:bg-muted/40 ${isSelected ? 'bg-primary/5' : ''}`}>
                          <Checkbox 
                            checked={isSelected} 
                            onCheckedChange={() => toggleSelect(q)}
                            className="mt-1"
                          />
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-3">
                              <StatusTag status={q.type} type="qtype" />
                              {subs.length > 0 && (
                                <span className="inline-flex items-center gap-1 text-xs text-primary bg-primary/10 border border-primary/20 px-2 py-0.5 rounded-md">
                                  <Layers className="w-3 h-3" />
                                  含 {subs.length} 小问
                                </span>
                              )}
                              {q.knowledgePoints?.length > 0 && (
                                <span className="text-xs text-muted-foreground px-2 py-0.5 bg-card border border-border rounded-md">
                                  {q.knowledgePoints.join(", ")}
                                </span>
                              )}
                            </div>
                            <div className="text-foreground/80">
                              <MarkdownRenderer
                                content={getQuestionMarkdown(q)}
                                images={getQuestionImages(q)}
                                questionType={q.type}
                                options={q.options}
                              />
                            </div>
                            {isSelected && subs.length > 0 && (
                              <div className="mt-4 rounded-md border border-primary/15 bg-primary/5 p-3 space-y-3">
                                <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                                  <span>选择要纳入试卷的小问 · 已选 {selectedSubIdSet.size}/{subs.length}</span>
                                  <span>所选小问合计 {selectedSubScore} 分</span>
                                </div>
                                <div className="space-y-2">
                                  {subs.map((sub: any, subIndex: number) => {
                                    const subId = String(sub.id);
                                    const checked = selectedSubIdSet.has(subId);
                                    return (
                                      <label
                                        key={subId || subIndex}
                                        className={`flex gap-3 rounded-md border p-3 transition-colors ${
                                          checked ? "border-primary/30 bg-card" : "border-border bg-muted/30 opacity-75"
                                        }`}
                                      >
                                        <Checkbox
                                          checked={checked}
                                          onCheckedChange={() => toggleSelectedSub(q, subId)}
                                          className="mt-1"
                                        />
                                        <div className="min-w-0 flex-1 space-y-1">
                                          <div className="flex flex-wrap items-center gap-2">
                                            <span className="text-xs font-medium text-foreground">{sub.label || `(${subIndex + 1})`}</span>
                                            <StatusTag status={sub.type || q.type} type="qtype" />
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
                                        </div>
                                      </label>
                                    );
                                  })}
                                </div>
                              </div>
                            )}
                          </div>
                        </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="py-12 text-center text-muted-foreground">
                      {search || hasActiveFilters(filters) ? "没有符合条件的题目，试试调整筛选条件" : "暂无题目，请先去题库中心入库题目"}
                    </div>
                  )}
                </div>
                <PaginationBar
                  page={selectPage}
                  pageSize={SELECT_PAGE_SIZE}
                  total={questionsTotal}
                  onPageChange={setSelectPage}
                />
              </div>
            </div>
          </div>
          ) : (
          /* 试卷列表 */
          <div className="bg-card p-6 rounded-2xl border border-border elevation-2">
            <div className="flex items-center justify-between gap-3 mb-6">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl gradient-primary-soft flex items-center justify-center text-primary shrink-0">
                  <FileText className="w-5 h-5" />
                </div>
                <div>
                  <h2 className="text-base font-semibold text-foreground tracking-tight">试卷列表</h2>
                  <p className="text-xs text-muted-foreground mt-0.5">共 {papersTotal} 份试卷，可搜索、导出或编辑。</p>
                </div>
              </div>
              {selectedPaperIds.size > 0 && (
                <div className="flex items-center gap-2">
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={handleBatchDeletePapers}
                    disabled={batchDeletePapersMutation.isPending}
                  >
                    <Trash2 className="w-3.5 h-3.5 mr-1.5" /> 删除所选 ({selectedPaperIds.size})
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setSelectedPaperIds(new Set())}
                  >
                    全部取消
                  </Button>
                </div>
              )}
            </div>

            <div className="mb-6 bg-muted/30 border border-border rounded-xl p-3">
              <div className="flex flex-col sm:flex-row items-stretch gap-3">
                <div className="relative flex-1 min-w-0">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                  <Input
                    value={paperKeyword}
                    onChange={(e) => setPaperKeyword(e.target.value)}
                    placeholder="按试卷名称搜索"
                    className="pl-9 w-full"
                  />
                </div>
                <div className="relative w-full sm:w-48">
                  <BookOpen className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                  <Input
                    value={paperSubject}
                    onChange={(e) => setPaperSubject(e.target.value)}
                    placeholder="学科，如 数学"
                    className="pl-9 w-full"
                  />
                </div>
                <div className="relative w-full sm:w-48">
                  <GraduationCap className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                  <Input
                    value={paperGrade}
                    onChange={(e) => setPaperGrade(e.target.value)}
                    placeholder="年级，如 高一"
                    className="pl-9 w-full"
                  />
                </div>
                {(paperSubject || paperGrade || paperKeyword) && (
                  <Button
                    variant="outline"
                    className="h-11 shrink-0 gap-1.5 text-muted-foreground"
                    onClick={() => {
                      setPaperSubject("");
                      setPaperGrade("");
                      setPaperKeyword("");
                    }}
                  >
                    <X className="w-4 h-4" /> 重置
                  </Button>
                )}
              </div>
            </div>

            {isLoadingPapers ? (
              <div className="py-12 text-center text-muted-foreground">加载试卷中...</div>
            ) : papersList.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {papersList.map((paper: any) => (
                  <div key={paper.id} className="group border border-border rounded-xl p-5 hover:border-primary/30 hover:elevation-2 transition-all bg-card elevation-1 flex flex-col">
                    <div className="flex justify-between items-center mb-4 gap-2">
                      <div className="min-w-0 pr-2">
                        <h3 className="font-medium text-foreground line-clamp-2">{paper.title}</h3>
                        <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
                          {paper.status && (
                            <span className="inline-block text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20">
                              {paper.status}
                            </span>
                          )}
                          {paper.subject && (
                            <span className="inline-block text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground border border-border">
                              {paper.subject}
                            </span>
                          )}
                          {paper.grade && (
                            <span className="inline-block text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground border border-border">
                              {paper.grade}
                            </span>
                          )}
                        </div>
                      </div>
                      <div className={`flex items-center space-x-1 shrink-0 bg-muted/50 rounded-md p-0.5 border border-border transition-opacity ${selectedPaperIds.has(paper.id) ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}>
                        <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-primary hover:bg-card" onClick={() => setEditingPaperId(paper.id)} title="编辑">
                          <Edit2 className="w-3.5 h-3.5" />
                        </Button>
                        <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive hover:bg-card" onClick={() => handleDeletePaper(paper.id)} title="删除">
                          <Trash2 className="w-3.5 h-3.5" />
                        </Button>
                        <Checkbox
                          checked={selectedPaperIds.has(paper.id)}
                          onCheckedChange={() => togglePaperSelect(paper.id)}
                          className="ml-1 shrink-0"
                        />
                      </div>
                    </div>
                    <div className="text-xs text-muted-foreground mb-6 flex flex-wrap items-center gap-x-4 gap-y-1.5 bg-muted/40 p-2 rounded-md border border-border">
                      <span className="flex items-center"><span className="w-1.5 h-1.5 rounded-full bg-primary/40 mr-1.5"></span>题目数量：{paper.questionCount || 0}</span>
                      <span className="flex items-center"><span className="w-1.5 h-1.5 rounded-full bg-warm/50 mr-1.5"></span>满分：{paper.totalScore || 0} 分</span>
                      <span className="flex items-center"><span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/40 mr-1.5"></span>创建时间：{new Date(paper.createdAt || Date.now()).toLocaleDateString()}</span>
                    </div>
                    <div className="mt-auto pt-4 border-t border-border flex space-x-3">
                      <Button variant="outline" size="sm" className="flex-1 text-xs" onClick={() => window.open(api.paperExportUrl(paper.id, 'docx', 'teacher'), '_blank')}>
                        <FileDown className="w-3.5 h-3.5 mr-1.5 text-primary" /> Word 导出
                      </Button>
                      <Button variant="outline" size="sm" className="flex-1 text-xs" onClick={() => window.open(api.paperExportUrl(paper.id, 'pdf', 'teacher'), '_blank')}>
                        <FileDown className="w-3.5 h-3.5 mr-1.5 text-warm" /> PDF 导出
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-16 border-2 border-dashed border-border rounded-lg bg-muted/30">
                <p className="text-muted-foreground">暂无试卷，点击右上角「新建试卷」开始组卷。</p>
              </div>
            )}
            <PaginationBar
              page={paperPage}
              pageSize={PAPER_PAGE_SIZE}
              total={papersTotal}
              onPageChange={setPaperPage}
              className="pt-6"
            />
          </div>
          )}

        </div>
      </div>
    </Layout>
  );
}
