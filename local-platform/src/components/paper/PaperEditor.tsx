import React, { useState, useEffect } from "react";
import { Layout } from "@/components/layout/Layout";
import { api } from "@/lib/api";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import { ArrowLeft, Trash2, Plus, GripVertical, Send, Eye, Layers } from "lucide-react";
import { StatusTag } from "@/components/ui/StatusTag";
import { MarkdownRenderer } from "@/components/ui/MarkdownRenderer";
import { getQuestionMarkdown, getQuestionImages, getSubQuestions, getSelectedSubQuestions } from "@/lib/question";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  QuestionFilters,
  Filters,
  emptyFilters,
  hasActiveFilters,
} from "@/components/question-bank/QuestionFilters";
import { Reorder, useDragControls } from "framer-motion";

interface PaperEditorProps {
  paperId?: string;
  initialQuestions?: any[];
  initialSubSelections?: Record<string, string[]>;
  initialTitle?: string;
  onClose: () => void;
}

function defaultSubSelections(questions: any[]): Record<string, string[]> {
  const result: Record<string, string[]> = {};
  questions.forEach((q) => {
    const subs = getSubQuestions(q);
    if (subs.length > 0) {
      result[q.id] = subs.map((sub: any) => String(sub.id));
    }
  });
  return result;
}

function EditorQuestionRow({
  q,
  index,
  score,
  strategy,
  selectedSubIds,
  onScore,
  onToggleSub,
  onRemove,
}: {
  q: any;
  index: number;
  score: number;
  strategy: string;
  selectedSubIds: string[];
  onScore: (id: string, value: string) => void;
  onToggleSub: (question: any, subId: string) => void;
  onRemove: () => void;
}) {
  const controls = useDragControls();
  const subQuestions = getSubQuestions(q);
  const selectedSubIdSet = new Set(selectedSubIds);
  const selectedSubScore = subQuestions
    .filter((sub: any) => selectedSubIdSet.has(String(sub.id)))
    .reduce((sum: number, sub: any) => sum + (Number(sub.score) || 0), 0);

  return (
    <Reorder.Item
      value={q}
      dragListener={false}
      dragControls={controls}
      className="group p-4 border border-border rounded-lg flex gap-4 hover:border-primary/30 hover:elevation-2 transition-all bg-card"
    >
      <div className="flex flex-col items-center justify-start gap-2 pt-1 shrink-0">
        <button
          type="button"
          onPointerDown={(e) => controls.start(e)}
          className="cursor-grab active:cursor-grabbing text-muted-foreground hover:text-primary touch-none"
          title="按住拖拽调整顺序"
        >
          <GripVertical className="w-5 h-5" />
        </button>
        <span className="text-xs font-medium text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
          {index + 1}
        </span>
      </div>

      <div className="flex-1 min-w-0 py-1">
        <div className="flex flex-wrap items-center gap-2 mb-2">
          <StatusTag status={q.type} type="qtype" />
          <StatusTag status={q.difficulty} type="difficulty" />
          {subQuestions.length > 0 && (
            <span className="inline-flex items-center gap-1 text-xs text-primary bg-primary/10 border border-primary/20 px-2 py-0.5 rounded-md">
              <Layers className="w-3 h-3" />
              含 {subQuestions.length} 小问
            </span>
          )}
          {q.knowledgePoints?.length > 0 && (
            <span className="text-xs text-muted-foreground px-2 py-0.5 bg-muted rounded-md">
              {q.knowledgePoints.join(", ")}
            </span>
          )}
        </div>
        <MarkdownRenderer
          content={getQuestionMarkdown(q)}
          images={getQuestionImages(q)}
          questionType={q.type}
          options={q.options}
        />

        {subQuestions.length > 0 && (
          <div className="mt-4 rounded-md border border-primary/15 bg-primary/5 p-3 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
              <span>小问（勾选纳入试卷）· 已选 {selectedSubIdSet.size}/{subQuestions.length}</span>
              <span>所选小问合计 {selectedSubScore} 分</span>
            </div>
            <div className="space-y-2">
              {subQuestions.map((sub: any, subIndex: number) => {
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
                      onCheckedChange={() => onToggleSub(q, subId)}
                      className="mt-1"
                    />
                    <div className="min-w-0 flex-1 space-y-2">
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
                      {strategy === "teacher" && checked && (sub.answer || sub.analysis) && (
                        <div className="grid gap-2 text-xs sm:grid-cols-2">
                          {sub.answer && (
                            <div className="rounded border border-border bg-muted/40 p-2">
                              <span className="font-medium text-foreground block mb-1">答案：</span>
                              <MarkdownRenderer content={sub.answer} />
                            </div>
                          )}
                          {sub.analysis && (
                            <div className="rounded border border-border bg-muted/40 p-2">
                              <span className="font-medium text-foreground block mb-1">解析：</span>
                              <MarkdownRenderer content={sub.analysis} />
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </label>
                );
              })}
            </div>
          </div>
        )}

        {strategy === "teacher" && subQuestions.length === 0 && (
          <div className="mt-4 pt-3 border-t border-border space-y-3">
            {q.answer && (
              <div className="text-sm">
                <span className="font-medium text-foreground/90 block mb-1">答案：</span>
                <div className="text-muted-foreground bg-muted/40 p-2 rounded-md border border-border">
                  <MarkdownRenderer content={q.answer} />
                </div>
              </div>
            )}
            {q.analysis && (
              <div className="text-sm">
                <span className="font-medium text-foreground/90 block mb-1">解析：</span>
                <div className="text-muted-foreground bg-muted/40 p-2 rounded-md border border-border">
                  <MarkdownRenderer content={q.analysis} />
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="shrink-0 flex flex-col items-end gap-3">
        <div className="flex items-center gap-1.5">
          <Label className="text-xs text-muted-foreground whitespace-nowrap">赋分</Label>
          <Input
            type="number"
            min="0"
            value={Number.isFinite(score) ? score : 0}
            onChange={(e) => onScore(q.id, e.target.value)}
            className="w-20 h-8 text-right"
          />
          <span className="text-sm text-muted-foreground">分</span>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 text-muted-foreground hover:text-destructive bg-muted/50 rounded-md"
          onClick={onRemove}
          title="移除题目"
        >
          <Trash2 className="w-4 h-4" />
        </Button>
      </div>
    </Reorder.Item>
  );
}

export function PaperEditor({ paperId, initialQuestions, initialSubSelections, initialTitle, onClose }: PaperEditorProps) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const isNew = !paperId;

  const [title, setTitle] = useState(() => initialTitle || (isNew ? "新建试卷" : ""));
  const [subtitle, setSubtitle] = useState("");
  const [subject, setSubject] = useState("");
  const [grade, setGrade] = useState("");
  const [school, setSchool] = useState("");
  const [duration, setDuration] = useState("");
  const [instructions, setInstructions] = useState("");
  const [strategy, setStrategy] = useState("teacher");
  const [questions, setQuestions] = useState<any[]>(() => (isNew ? initialQuestions || [] : []));
  const [subSelections, setSubSelections] = useState<Record<string, string[]>>(() =>
    isNew ? initialSubSelections || defaultSubSelections(initialQuestions || []) : {},
  );
  const [scores, setScores] = useState<Record<string, number>>(() => {
    const m: Record<string, number> = {};
    if (isNew) {
      (initialQuestions || []).forEach((q: any) => {
        m[q.id] = Number(q.score) || 0;
      });
    }
    return m;
  });
  const [isAppending, setIsAppending] = useState(false);
  const [appendSelected, setAppendSelected] = useState<Record<string, any>>({});
  const [appendSearch, setAppendSearch] = useState("");
  const [appendFilters, setAppendFilters] = useState<Filters>(emptyFilters);
  const [previewOpen, setPreviewOpen] = useState(false);

  const { data: paper, isLoading: isLoadingPaper } = useQuery({
    queryKey: ["papers", paperId],
    queryFn: () => api.getPaper(paperId as string),
    enabled: !!paperId,
  });

  const { data: allQuestionsData, isLoading: isLoadingAllQuestions } = useQuery({
    queryKey: ["questions", "append-selection", appendSearch, appendFilters],
    queryFn: () =>
      api
        .getQuestions({ keyword: appendSearch, ...appendFilters, pageSize: 100 })
        .catch(() => ({ items: [], total: 0 })),
    enabled: isAppending,
  });

  useEffect(() => {
    if (paper) {
      setTitle(paper.title || "未命名试卷");
      setQuestions(paper.questions || []);
      const m: Record<string, number> = {};
      (paper.questions || []).forEach((q: any) => {
        m[q.id] = Number(q.score) || 0;
      });
      setScores(m);
      setSubSelections(paper.subSelections || defaultSubSelections(paper.questions || []));
      setSubtitle(paper.header?.subtitle || "");
      setSubject(paper.header?.subject || "");
      setGrade(paper.header?.grade || "");
      setSchool(paper.header?.school || "");
      setDuration(paper.header?.duration || "");
      setInstructions(paper.header?.instructions || "");
      if (paper.answerDisplay) setStrategy(paper.answerDisplay);
    }
  }, [paper]);

  const totalScore = questions.reduce((sum, q) => sum + (Number(scores[q.id]) || 0), 0);

  const saveMutation = useMutation({
    mutationFn: (data: any) => (isNew ? api.createPaper(data) : api.updatePaper(paperId as string, data)),
    onSuccess: () => {
      toast({ title: "发布成功", description: isNew ? "试卷已生成并发布" : "试卷已更新并发布" });
      queryClient.invalidateQueries({ queryKey: ["papers"] });
      onClose();
    },
    onError: (err: Error) => toast({ title: "发布失败", description: err.message, variant: "destructive" }),
  });

  const handlePreview = () => {
    if (!title.trim()) {
      toast({ title: "提示", description: "试卷标题为必填项", variant: "destructive" });
      return;
    }
    if (questions.length === 0) {
      toast({ title: "提示", description: "请至少保留一道题目", variant: "destructive" });
      return;
    }
    setPreviewOpen(true);
  };

  const handlePublish = () => {
    if (!title.trim()) {
      toast({ title: "提示", description: "试卷标题为必填项", variant: "destructive" });
      return;
    }
    if (questions.length === 0) {
      toast({ title: "提示", description: "请至少保留一道题目", variant: "destructive" });
      return;
    }
    const scoreMap: Record<string, number> = {};
    const subSelectionMap: Record<string, string[]> = {};
    questions.forEach((q) => {
      scoreMap[q.id] = Number(scores[q.id]) || 0;
      const subs = getSubQuestions(q);
      if (subs.length > 0) {
        subSelectionMap[q.id] = subSelections[q.id]?.length
          ? subSelections[q.id]
          : subs.map((sub: any) => String(sub.id));
      }
    });
    saveMutation.mutate({
      title,
      answerDisplay: strategy,
      questionIds: questions.map((q) => q.id),
      scores: scoreMap,
      subSelections: subSelectionMap,
      header: { subtitle, subject, grade, school, duration, instructions },
      status: "已发布",
    });
  };

  const handleScoreChange = (id: string, value: string) => {
    const n = value === "" ? 0 : Number(value);
    setScores((prev) => ({ ...prev, [id]: Number.isNaN(n) ? 0 : Math.max(0, n) }));
  };

  const handleRemove = (id: string) => {
    setQuestions((prev) => prev.filter((q) => q.id !== id));
    setSubSelections((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  };

  const handleToggleSub = (question: any, subId: string) => {
    const subs = getSubQuestions(question);
    if (subs.length === 0) return;
    const allSubIds = subs.map((sub: any) => String(sub.id));
    const current = subSelections[question.id]?.length ? subSelections[question.id] : allSubIds;
    const isSelected = current.includes(subId);
    if (isSelected && current.length <= 1) {
      toast({ title: "至少保留一个小问", description: "只要大题在试卷中，就必须纳入至少一个小问。", variant: "destructive" });
      return;
    }
    const nextIds = isSelected ? current.filter((id) => id !== subId) : [...current, subId];
    setSubSelections((prev) => ({ ...prev, [question.id]: nextIds }));
  };

  const handleAppendConfirm = () => {
    const toAppend = Object.values(appendSelected);
    const currentIds = new Set(questions.map((q) => q.id));
    const uniqueToAppend = toAppend.filter((q: any) => !currentIds.has(q.id));

    setQuestions([...questions, ...uniqueToAppend]);
    setScores((prev) => {
      const next = { ...prev };
      uniqueToAppend.forEach((q: any) => {
        next[q.id] = Number(q.score) || 0;
      });
      return next;
    });
    setSubSelections((prev) => ({ ...prev, ...defaultSubSelections(uniqueToAppend) }));
    setIsAppending(false);
    setAppendSelected({});
    setAppendSearch("");
    setAppendFilters(emptyFilters);
    toast({ title: "已追加", description: `成功追加 ${uniqueToAppend.length} 道题目` });
  };

  if (paperId && isLoadingPaper) {
    return (
      <Layout>
        <div className="flex items-center justify-center h-full text-muted-foreground">加载试卷中...</div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="glass-nav border-b border-border px-6 py-4 md:py-0 md:h-16 flex flex-col md:flex-row md:items-center justify-between shrink-0 z-10 gap-4">
        <div className="flex items-center space-x-4">
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            className="h-8 w-8 shrink-0 text-muted-foreground hover:text-foreground border border-border"
          >
            <ArrowLeft className="w-4 h-4" />
          </Button>
          <div>
            <h1 className="text-2xl font-bold gradient-text tracking-tight">
              {isNew ? "编辑新试卷" : "试卷编辑"}
            </h1>
            <p className="text-sm font-light text-muted-foreground mt-1">
              设置试卷头、拖拽调整题目顺序并为每题赋分，确认后发布。
            </p>
          </div>
        </div>
        <div className="flex items-center space-x-3 self-end md:self-auto">
          <span className="text-sm text-muted-foreground">
            共 <span className="font-medium text-foreground">{questions.length}</span> 题 · 满分{" "}
            <span className="font-medium text-primary">{totalScore}</span> 分
          </span>
          <Button variant="outline" onClick={onClose} disabled={saveMutation.isPending}>
            取消
          </Button>
          <Button onClick={handlePreview} disabled={saveMutation.isPending}>
            <Eye className="w-4 h-4 mr-1.5" />
            预览并发布
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-auto p-6">
        <div className="max-w-5xl mx-auto space-y-6">
          {/* 试卷头设置 */}
          <div className="bg-card p-6 rounded-lg border border-border elevation-1">
            <h2 className="text-lg font-semibold text-foreground mb-6">试卷头信息</h2>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="space-y-4">
                <div className="space-y-2">
                  <Label>
                    试卷标题 <span className="text-destructive">*</span>
                  </Label>
                  <Input
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="例如：2026届高一数学期中考试"
                  />
                </div>
                <div className="space-y-2">
                  <Label>副标题 / 考试名称</Label>
                  <Input
                    value={subtitle}
                    onChange={(e) => setSubtitle(e.target.value)}
                    placeholder="例如：2026届高一上学期期中模拟"
                  />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>学科</Label>
                    <Input
                      value={subject}
                      onChange={(e) => setSubject(e.target.value)}
                      placeholder="例如：数学"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>年级</Label>
                    <Input
                      value={grade}
                      onChange={(e) => setGrade(e.target.value)}
                      placeholder="例如：高一"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>学校</Label>
                    <Input
                      value={school}
                      onChange={(e) => setSchool(e.target.value)}
                      placeholder="例如：实验中学"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>考试时长</Label>
                    <Input
                      value={duration}
                      onChange={(e) => setDuration(e.target.value)}
                      placeholder="例如：120分钟"
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label>答案解析显示策略</Label>
                  <Select value={strategy} onValueChange={setStrategy}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="teacher">教师版 (显示全部内容)</SelectItem>
                      <SelectItem value="student">学生版 (占位，后端支持后生效)</SelectItem>
                      <SelectItem value="answer">答案版 (占位，后端支持后生效)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>考生须知</Label>
                  <Textarea
                    value={instructions}
                    onChange={(e) => setInstructions(e.target.value)}
                    placeholder="例如：1. 本卷满分150分，考试时间120分钟。&#10;2. 请将答案写在答题卡指定区域。"
                    rows={4}
                  />
                </div>
              </div>

              {/* 实时预览 */}
              <div className="space-y-2">
                <Label className="text-muted-foreground">试卷头预览</Label>
                <div className="border border-border rounded-lg bg-muted/30 p-6 min-h-[260px]">
                  <div className="text-center space-y-1.5 pb-4 border-b border-dashed border-border">
                    <h3 className="text-xl font-bold text-foreground">{title || "（未填写标题）"}</h3>
                    {subtitle && <p className="text-sm text-foreground/80">{subtitle}</p>}
                    <div className="flex items-center justify-center gap-4 text-xs text-muted-foreground pt-1">
                      {subject && <span>学科：{subject}</span>}
                      {grade && <span>年级：{grade}</span>}
                      {school && <span>学校：{school}</span>}
                      {duration && <span>考试时间：{duration}</span>}
                      <span>满分：{totalScore} 分</span>
                    </div>
                  </div>
                  <div className="flex items-center justify-between text-xs text-muted-foreground mt-3">
                    <span>姓名：____________</span>
                    <span>班级：____________</span>
                    <span>考号：____________</span>
                  </div>
                  {instructions && (
                    <div className="mt-4 text-xs text-muted-foreground whitespace-pre-line leading-relaxed">
                      {instructions}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* 题目列表 */}
          <div className="bg-card p-6 rounded-lg border border-border elevation-1">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h2 className="text-lg font-semibold text-foreground">题目列表 ({questions.length}题)</h2>
                <p className="text-xs text-muted-foreground mt-1">按住左侧手柄可拖拽调整题目顺序。</p>
              </div>
              <Button size="sm" variant="secondary" onClick={() => setIsAppending(!isAppending)}>
                <Plus className="w-4 h-4 mr-1.5" /> 追加题目
              </Button>
            </div>

            {isAppending && (
              <div className="mb-6 p-4 border border-primary/20 bg-primary/5 rounded-lg">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-medium text-primary">从题库选择追加</h3>
                  <div className="space-x-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setIsAppending(false);
                        setAppendSelected({});
                        setAppendSearch("");
                        setAppendFilters(emptyFilters);
                      }}
                    >
                      取消
                    </Button>
                    <Button size="sm" onClick={handleAppendConfirm} disabled={Object.keys(appendSelected).length === 0}>
                      确认追加 ({Object.keys(appendSelected).length})
                    </Button>
                  </div>
                </div>
                <div className="mb-4">
                  <QuestionFilters
                    search={appendSearch}
                    setSearch={setAppendSearch}
                    filters={appendFilters}
                    setFilters={setAppendFilters}
                  />
                </div>
                <div className="max-h-64 overflow-y-auto border border-primary/10 bg-card rounded-md">
                  {isLoadingAllQuestions ? (
                    <div className="py-8 text-center text-muted-foreground">加载中...</div>
                  ) : (allQuestionsData?.items?.length ?? 0) > 0 ? (
                    <div className="divide-y divide-border">
                      {allQuestionsData.items.map((q: any) => (
                        <div key={q.id} className="p-3 flex gap-3 hover:bg-muted/40 transition-colors">
                          <Checkbox
                            checked={!!appendSelected[q.id]}
                            onCheckedChange={() => {
                              setAppendSelected((prev) => {
                                const next = { ...prev };
                                if (next[q.id]) {
                                  delete next[q.id];
                                } else {
                                  next[q.id] = q;
                                }
                                return next;
                              });
                            }}
                            className="mt-1"
                          />
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1 flex-wrap">
                              <StatusTag status={q.type} type="qtype" />
                              <StatusTag status={q.difficulty || "medium"} type="difficulty" />
                              {getSubQuestions(q).length > 0 && (
                                <span className="inline-flex items-center gap-1 text-xs text-primary bg-primary/10 border border-primary/20 px-2 py-0.5 rounded-md">
                                  <Layers className="w-3 h-3" />
                                  含 {getSubQuestions(q).length} 小问
                                </span>
                              )}
                            </div>
                            <div className="text-sm line-clamp-2 text-muted-foreground prose prose-sm max-w-none">
                              <MarkdownRenderer
                                content={getQuestionMarkdown(q)}
                                images={getQuestionImages(q)}
                                questionType={q.type}
                                options={q.options}
                              />
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="py-8 text-center text-muted-foreground">
                      {hasActiveFilters(appendFilters) || appendSearch ? "没有符合条件的题目" : "题库暂无可追加的题目"}
                    </div>
                  )}
                </div>
              </div>
            )}

            {questions.length > 0 ? (
              <Reorder.Group axis="y" values={questions} onReorder={setQuestions} className="space-y-3">
                {questions.map((q, index) => (
                  <EditorQuestionRow
                    key={q.id}
                    q={q}
                    index={index}
                    score={Number(scores[q.id]) || 0}
                    strategy={strategy}
                    selectedSubIds={getSelectedSubQuestions(q, subSelections).map((sub: any) => String(sub.id))}
                    onScore={handleScoreChange}
                    onToggleSub={handleToggleSub}
                    onRemove={() => handleRemove(q.id)}
                  />
                ))}
              </Reorder.Group>
            ) : (
              !isAppending && (
                <div className="py-12 text-center border-2 border-dashed border-border rounded-lg bg-muted/30">
                  <p className="text-muted-foreground">试卷中暂无题目，请点击「追加题目」从题库添加。</p>
                </div>
              )
            )}
          </div>
        </div>
      </div>

      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="max-w-4xl max-h-[90vh] flex flex-col p-0 gap-0">
          <DialogHeader className="px-6 py-4 border-b border-border text-left">
            <DialogTitle>试卷预览</DialogTitle>
            <DialogDescription>
              请确认试卷内容无误后再发布。共 {questions.length} 题 · 满分 {totalScore} 分。
            </DialogDescription>
          </DialogHeader>

          <div className="flex-1 overflow-auto px-6 py-6 bg-muted/20">
            <div className="bg-card mx-auto max-w-3xl p-8 rounded-lg border border-border elevation-1">
              {/* 试卷头 */}
              <div className="text-center space-y-2 pb-5 border-b-2 border-foreground/70">
                <h1 className="text-2xl font-bold text-foreground">{title || "（未填写标题）"}</h1>
                {subtitle && <p className="text-base text-foreground/80">{subtitle}</p>}
                <div className="flex items-center justify-center gap-5 text-sm text-muted-foreground pt-1 flex-wrap">
                  {subject && <span>学科：{subject}</span>}
                  {grade && <span>年级：{grade}</span>}
                  {school && <span>学校：{school}</span>}
                  {duration && <span>考试时间：{duration}</span>}
                  <span>满分：{totalScore} 分</span>
                </div>
                <div className="flex items-center justify-center gap-8 text-sm text-muted-foreground pt-2 flex-wrap">
                  <span>姓名：____________</span>
                  <span>班级：____________</span>
                  <span>考号：____________</span>
                </div>
              </div>

              {instructions && (
                <div className="mt-4 text-sm text-muted-foreground whitespace-pre-line leading-relaxed border-b border-dashed border-border pb-4">
                  {instructions}
                </div>
              )}

              {/* 题目 */}
              <div className="mt-6 space-y-6">
                {questions.map((q, index) => {
                  const previewSubs = getSelectedSubQuestions(q, subSelections);
                  return (
                    <div key={q.id} className="flex items-start gap-2">
                      <span className="font-semibold text-foreground shrink-0">{index + 1}.</span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                          <StatusTag status={q.type} type="qtype" />
                          {previewSubs.length > 0 && (
                            <span className="inline-flex items-center gap-1 text-xs text-primary bg-primary/10 border border-primary/20 px-2 py-0.5 rounded-md">
                              <Layers className="w-3 h-3" />
                              已选 {previewSubs.length}/{getSubQuestions(q).length} 小问
                            </span>
                          )}
                          <span className="text-xs text-muted-foreground">（{Number(scores[q.id]) || 0} 分）</span>
                        </div>
                        <MarkdownRenderer
                          content={getQuestionMarkdown(q)}
                          images={getQuestionImages(q)}
                          questionType={q.type}
                          options={q.options}
                        />
                        {previewSubs.length > 0 ? (
                          <div className="mt-4 space-y-4">
                            {previewSubs.map((sub: any, subIndex: number) => (
                              <div key={sub.id || subIndex} className="rounded-md border border-border bg-muted/30 p-3">
                                <div className="flex flex-wrap items-center gap-2 mb-2">
                                  <span className="text-sm font-semibold text-foreground">{sub.label || `(${subIndex + 1})`}</span>
                                  <StatusTag status={sub.type || q.type} type="qtype" />
                                  <span className="text-xs text-muted-foreground">{Number(sub.score) || 0} 分</span>
                                </div>
                                <MarkdownRenderer
                                  content={getQuestionMarkdown(sub)}
                                  images={getQuestionImages(sub)}
                                  questionType={sub.type || q.type}
                                  options={sub.options}
                                />
                                {strategy === "teacher" && (sub.answer || sub.analysis) && (
                                  <div className="mt-3 pt-2 border-t border-dashed border-border space-y-2">
                                    {sub.answer && (
                                      <div className="text-sm">
                                        <span className="font-medium text-foreground/90 block mb-1">答案：</span>
                                        <div className="text-muted-foreground">
                                          <MarkdownRenderer content={sub.answer} />
                                        </div>
                                      </div>
                                    )}
                                    {sub.analysis && (
                                      <div className="text-sm">
                                        <span className="font-medium text-foreground/90 block mb-1">解析：</span>
                                        <div className="text-muted-foreground">
                                          <MarkdownRenderer content={sub.analysis} />
                                        </div>
                                      </div>
                                    )}
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        ) : (
                          strategy === "teacher" && (q.answer || q.analysis) && (
                            <div className="mt-3 pt-2 border-t border-dashed border-border space-y-2">
                              {q.answer && (
                                <div className="text-sm">
                                  <span className="font-medium text-foreground/90 block mb-1">答案：</span>
                                  <div className="text-muted-foreground">
                                    <MarkdownRenderer content={q.answer} />
                                  </div>
                                </div>
                              )}
                              {q.analysis && (
                                <div className="text-sm">
                                  <span className="font-medium text-foreground/90 block mb-1">解析：</span>
                                  <div className="text-muted-foreground">
                                    <MarkdownRenderer content={q.analysis} />
                                  </div>
                                </div>
                              )}
                            </div>
                          )
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          <DialogFooter className="px-6 py-4 border-t border-border">
            <Button variant="outline" onClick={() => setPreviewOpen(false)} disabled={saveMutation.isPending}>
              返回编辑
            </Button>
            <Button onClick={handlePublish} disabled={saveMutation.isPending}>
              <Send className="w-4 h-4 mr-1.5" />
              {saveMutation.isPending ? "发布中..." : "确认发布"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Layout>
  );
}
