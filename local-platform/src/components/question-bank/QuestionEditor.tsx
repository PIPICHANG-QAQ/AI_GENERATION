import React, { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { MarkdownRenderer } from "@/components/ui/MarkdownRenderer";
import { KnowledgePointSelect } from "@/components/question-bank/KnowledgePointSelect";
import { QuestionImageUploader } from "@/components/question-bank/QuestionImageUploader";
import {
  StandardizeCandidatePanel,
  standardizeCandidateFromPayload,
  type StandardizeCandidate,
} from "@/components/question-bank/StandardizeCandidatePanel";
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
  addSubQuestionForm,
  appendMissingImageRefs,
  appendNewImageRefs,
  getQuestionImages,
  getQuestionMarkdown,
  getQuestionMarkdownParts,
  getSubQuestions,
  mergeSubQuestionSuggestions,
  normalizeQuestionOptions,
  removeSubQuestionForm,
  subQuestionEditorForm,
  type QuestionImage,
} from "@/lib/question";
import {
  buildSubQuestionAnalysisPayload,
  subAnalysisPatch,
  subStandardizePatch,
  uniqueQuestionImages,
} from "@/lib/sub-question-ai";
import { api } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Wand2, Code, Plus, Trash2 } from "lucide-react";

function LatexPreviewField({
  label,
  value,
  onChange,
  placeholder,
  images,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  images?: QuestionImage[];
}) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      <Textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={4}
        className="font-mono text-sm"
        placeholder={placeholder}
      />
      {value.trim() ? (
        <div className="rounded-md border border-border bg-muted/30">
          <div className="px-3 py-1.5 border-b border-border text-xs font-medium text-muted-foreground">
            实时预览
          </div>
          <div className="p-3 prose-container">
            <MarkdownRenderer content={value} images={images} showUnreferenced={false} />
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function QuestionEditor({ 
  question, 
  onCancel, 
  onSave,
  extraActions,
  onVerified
}: { 
  question: any, 
  onCancel: () => void, 
  onSave: (data: any) => void,
  extraActions?: React.ReactNode,
  onVerified?: (data: any) => void
}) {
  const { toast } = useToast();
  const initialImages = getQuestionImages(question);
  const initialMarkdown = getQuestionMarkdown(question);
  const [formData, setFormData] = useState({
    markdown: appendMissingImageRefs(initialMarkdown, initialImages, [question.answer || "", question.analysis || ""]),
    type: question.type || "unknown",
    difficulty: question.difficulty || "medium",
    score: question.score || 0,
    answer: question.answer || "",
    analysis: question.analysis || "",
    knowledgePointIds: (question.knowledgePointIds || []).map(String),
    subject: question.subject || "",
    grade: question.grade || "",
    region: question.region || "",
    year: question.year || "",
    source: question.source || "",
    images: initialImages,
    options: normalizeQuestionOptions(question.options),
  });
  const [subForms, setSubForms] = useState(() =>
    getSubQuestions(question).map((sub: any, index: number) => {
      const form = subQuestionEditorForm(sub, index, question);
      return {
        ...form,
        markdown: appendMissingImageRefs(form.markdown, form.images, [form.answer, form.analysis]),
      };
    }),
  );
  const [standardizeCandidate, setStandardizeCandidate] = useState<StandardizeCandidate | null>(null);
  const [subStandardizeCandidate, setSubStandardizeCandidate] = useState<{
    subIndex: number;
    candidate: StandardizeCandidate;
  } | null>(null);
  const [activeSubStandardizeIndex, setActiveSubStandardizeIndex] = useState<number | null>(null);
  const [activeSubAnalysisIndex, setActiveSubAnalysisIndex] = useState<number | null>(null);
  const [confirmDeleteIndex, setConfirmDeleteIndex] = useState<number | null>(null);
  const hasSubQuestions = subForms.length > 0;

  const { data: kpData } = useQuery({
    queryKey: ["knowledgePoints"],
    queryFn: api.getKnowledgePoints,
  });
  const { data: imageLibraryData } = useQuery({
    queryKey: ["questionImageLibrary", question.id],
    queryFn: () => api.getQuestionImageLibrary(question.id),
    enabled: !!question.id,
  });
  const allPoints: any[] = kpData?.items || [];
  const taskImageLibrary: QuestionImage[] = imageLibraryData?.items || [];

  const subKnowledgePointNames = (sub: any) =>
    (sub.knowledgePointIds || [])
      .map((id: string) => allPoints.find((p) => String(p.id) === String(id))?.name)
      .filter(Boolean);

  // Resolve legacy questions that carry knowledge-point names but no ids.
  useEffect(() => {
    if (
      formData.knowledgePointIds.length === 0 &&
      question.knowledgePoints?.length > 0 &&
      allPoints.length > 0
    ) {
      const resolved = question.knowledgePoints
        .map((name: string) => allPoints.find((p) => p.name === name)?.id)
        .filter(Boolean)
        .map(String);
      if (resolved.length > 0) {
        setFormData((f) => ({ ...f, knowledgePointIds: resolved }));
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allPoints.length]);

  const handleImagesChange = (nextImages: QuestionImage[]) => {
    setFormData((f) => ({
      ...f,
      images: nextImages,
      markdown: appendNewImageRefs(f.markdown, f.images, nextImages, [f.answer, f.analysis]),
    }));
    setStandardizeCandidate(null);
  };

  const withSubImageRefs = (subs: typeof subForms) =>
    subs.map((sub) => ({
      ...sub,
      markdown: sub.markdown,
    }));

  const localStdMutation = useMutation({
    mutationFn: (md: string) =>
      question.id ? api.standardizeQuestionAi(question.id, md) : api.standardizeAi(md),
    onSuccess: (res: any, md) => {
      const result = standardizeCandidateFromPayload(md, res);
      setStandardizeCandidate(result.candidate);
      toast({ title: result.candidate ? "AI 标准化候选已生成" : "AI 标准化完成", description: result.message });
    },
    onError: (err: any) => toast({ title: "标准化失败", description: err.message, variant: "destructive" })
  });

  const applyStandardizeCandidate = () => {
    if (!standardizeCandidate) return;
    const res = standardizeCandidate.payload || {};
    const updatedQuestion = res?.question || {};
    const suggestedAnswer = String(res?.answer ?? res?.suggestedAnswer ?? updatedQuestion.answer ?? "").trim();
    const suggestedAnalysis = String(res?.analysis ?? updatedQuestion.analysis ?? "").trim();
    const updatedOptions = normalizeQuestionOptions(res?.options ?? updatedQuestion.options);
    const nextSubForms = withSubImageRefs(
      mergeSubQuestionSuggestions(
        subForms,
        res?.subQuestions ?? updatedQuestion.subQuestions ?? updatedQuestion.children,
        question,
      ),
    );
    const nextHasSubQuestions = nextSubForms.length > 0;
    setSubForms(nextSubForms);
    setFormData((f) => ({
      ...f,
      markdown: standardizeCandidate.markdown,
      answer: nextHasSubQuestions ? "" : suggestedAnswer || f.answer,
      analysis: nextHasSubQuestions ? "" : suggestedAnalysis || f.analysis,
      options: updatedOptions.length > 0 ? updatedOptions : f.options,
    }));
    setStandardizeCandidate(null);
    toast({ title: "已应用 AI 标准化候选", description: "请复核后保存" });
  };

  const aiAnalysisMutation = useMutation({
    mutationFn: () => {
      const draft = prepareData();
      const payload = {
        manualMarkdown: draft.manualMarkdown,
        type: draft.type,
        answer: draft.answer,
        knowledgePoints: draft.knowledgePoints,
        images: draft.images,
        subQuestions: draft.subQuestions,
      };
      return question.id
        ? api.generateQuestionAnalysis(question.id, payload)
        : api.generateAnalysisAi(payload);
    },
    onSuccess: (res: any) => {
      const suggestedAnswer = String(res?.answer ?? res?.suggestedAnswer ?? "").trim();
      const nextSubForms = withSubImageRefs(
        mergeSubQuestionSuggestions(subForms, res?.subQuestions ?? res?.metadata?.subQuestions, question),
      );
      const nextHasSubQuestions = nextSubForms.length > 0;
      setSubForms(nextSubForms);
      setFormData(f => ({
        ...f,
        analysis: nextHasSubQuestions ? "" : res.analysis || "",
        answer: nextHasSubQuestions ? "" : suggestedAnswer || f.answer,
      }));
      toast({ title: "AI 解析生成完成" });
    },
    onError: (err: any) => toast({ title: "AI 解析生成失败", description: err.message, variant: "destructive" })
  });

  const subStdMutation = useMutation({
    mutationFn: ({ markdown }: { subIndex: number; markdown: string }) => api.standardizeAi(markdown),
    onMutate: ({ subIndex }) => setActiveSubStandardizeIndex(subIndex),
    onSuccess: (res: any, { subIndex, markdown }) => {
      const result = standardizeCandidateFromPayload(markdown, res);
      if (result.candidate) {
        setSubStandardizeCandidate({ subIndex, candidate: result.candidate });
      } else {
        patchSub(subIndex, subStandardizePatch(markdown, res));
      }
      toast({ title: result.candidate ? "小问 AI 标准化候选已生成" : "小问 AI 标准化完成", description: result.message });
    },
    onError: (err: any) => toast({ title: "小问标准化失败", description: err.message, variant: "destructive" }),
    onSettled: () => setActiveSubStandardizeIndex(null),
  });

  const subAnalysisMutation = useMutation({
    mutationFn: ({ subIndex }: { subIndex: number }) => {
      const sub = subForms[subIndex];
      return api.generateAnalysisAi(
        buildSubQuestionAnalysisPayload({
          parentMarkdown: formData.markdown,
          parentImages: formData.images,
          sub,
          knowledgePoints: subKnowledgePointNames(sub),
        }),
      );
    },
    onMutate: ({ subIndex }) => setActiveSubAnalysisIndex(subIndex),
    onSuccess: (res: any, { subIndex }) => {
      const patch = subAnalysisPatch(res);
      if (!patch.answer && !patch.analysis) {
        toast({ title: "小问 AI 解析未返回可应用内容", description: "请检查题干、答案或题图是否完整" });
        return;
      }
      patchSub(subIndex, patch);
      toast({ title: "小问 AI 解析生成完成" });
    },
    onError: (err: any) => toast({ title: "小问 AI 解析生成失败", description: err.message, variant: "destructive" }),
    onSettled: () => setActiveSubAnalysisIndex(null),
  });

  const applySubStandardizeCandidate = () => {
    if (!subStandardizeCandidate) return;
    const { subIndex, candidate } = subStandardizeCandidate;
    patchSub(subIndex, subStandardizePatch(candidate.markdown, candidate.payload || {}));
    setSubStandardizeCandidate(null);
    toast({ title: "已应用小问 AI 标准化候选", description: "请复核后保存" });
  };

  const prepareData = () => {
    const { markdown, ...rest } = formData;
    const questionParts = getQuestionMarkdownParts(markdown, formData.type, formData.options);
    const subQuestions = subForms.map((sub) => {
      const subParts = getQuestionMarkdownParts(sub.markdown, sub.type, sub.options);
      const knowledgePointNames = sub.knowledgePointIds
        .map((id: string) => allPoints.find((p) => String(p.id) === String(id))?.name)
        .filter(Boolean);
      return {
        id: sub.id,
        label: sub.label,
        type: sub.type,
        difficulty: sub.difficulty,
        score: Number(sub.score) || 0,
        stem: subParts.stemMarkdown || sub.markdown,
        stemMarkdown: subParts.stemMarkdown || sub.markdown,
        manualMarkdown: sub.markdown,
        answer: sub.answer,
        analysis: sub.analysis,
        knowledgePointIds: sub.knowledgePointIds,
        knowledgePoints: knowledgePointNames,
        images: sub.images,
        options: subParts.options,
        contextMatched: sub.contextMatched,
        answerEvidence: sub.answerEvidence,
        analysisEvidence: sub.analysisEvidence,
        warnings: sub.warnings,
        aiMetadata: sub.aiMetadata,
      };
    });
    return {
      ...rest,
      stemMarkdown: questionParts.stemMarkdown || markdown,
      manualMarkdown: markdown,
      score: Number(formData.score) || 0,
      answer: hasSubQuestions ? "" : formData.answer,
      analysis: hasSubQuestions ? "" : formData.analysis,
      knowledgePointIds: formData.knowledgePointIds,
      knowledgePoints: formData.knowledgePointIds
        .map((id: string) => allPoints.find((p) => String(p.id) === String(id))?.name)
        .filter(Boolean),
      options: questionParts.options,
      images: formData.images,
      subQuestions,
      children: subQuestions,
    };
  };

  const patchSub = (index: number, patch: Partial<(typeof subForms)[number]>) => {
    setSubForms((prev) => prev.map((sub, i) => (i === index ? { ...sub, ...patch } : sub)));
    if (Object.prototype.hasOwnProperty.call(patch, "markdown")) {
      setSubStandardizeCandidate((current) => (current?.subIndex === index ? null : current));
    }
  };

  const handleAddSubQuestion = () => {
    const wasPlainQuestion = subForms.length === 0;
    setSubForms((prev) => addSubQuestionForm(prev, formData));
    if (wasPlainQuestion && (formData.answer || formData.analysis)) {
      setFormData((f) => ({ ...f, answer: "", analysis: "" }));
    }
    setStandardizeCandidate(null);
    setSubStandardizeCandidate(null);
  };

  const handleDeleteSubQuestion = (index: number) => {
    setSubForms((prev) => removeSubQuestionForm(prev, index));
    setStandardizeCandidate(null);
    setSubStandardizeCandidate(null);
  };

  const handleSave = () => {
    onSave(prepareData());
  };

  const handleVerifiedSubmit = () => {
    if (onVerified) onVerified(prepareData());
  };

  return (
    <div className="flex flex-col md:flex-row h-full">
      {/* Left: Markdown Editor */}
      <div className="flex-1 border-r border-border flex flex-col min-w-0 bg-muted/40 overflow-auto">
        <div className="h-12 px-6 border-b border-border flex justify-between items-center bg-card shrink-0">
          <span className="font-medium text-sm">题干编辑 (Markdown + LaTeX)</span>
          <div className="flex gap-2">
            <Button 
              variant="outline" 
              size="sm" 
              onClick={() => localStdMutation.mutate(formData.markdown)}
              disabled={localStdMutation.isPending || !formData.markdown}
              className="h-8 gap-1 text-xs"
            >
              <Code className="w-3 h-3" /> AI 标准化
            </Button>
            <Button 
              variant="outline" 
              size="sm" 
              onClick={() => aiAnalysisMutation.mutate()}
              disabled={aiAnalysisMutation.isPending || !formData.markdown}
              className="h-8 gap-1 text-xs text-warm border-warm/30 hover:bg-warm/10"
              title={hasSubQuestions ? "AI 将按小问分别生成答案和解析" : undefined}
            >
              <Wand2 className="w-3 h-3" /> {aiAnalysisMutation.isPending ? "AI 解析中" : "AI 解析"}
            </Button>
          </div>
        </div>
        <div className="flex-1 flex flex-col min-h-[300px]">
          <textarea
            value={formData.markdown}
            onChange={e => {
              setFormData(f => ({ ...f, markdown: e.target.value }));
              setStandardizeCandidate(null);
            }}
            className="flex-1 p-4 bg-secondary text-secondary-foreground font-mono text-sm resize-none focus:outline-none"
            placeholder="在此输入题干 Markdown..."
          />
        </div>
        <div className="h-1/2 border-t border-border bg-card flex flex-col min-h-[200px]">
          <div className="p-2 border-b border-border bg-muted/50 text-xs font-medium text-muted-foreground shrink-0">实时预览</div>
          <div className="flex-1 overflow-auto p-4 prose-container">
            <MarkdownRenderer
              content={formData.markdown}
              images={formData.images}
              questionType={formData.type}
              options={formData.options}
              siblingContent={[formData.answer, formData.analysis]}
            />
          </div>
        </div>
        {standardizeCandidate ? (
          <div className="p-4 shrink-0">
            <StandardizeCandidatePanel
              candidate={standardizeCandidate}
              disabled={localStdMutation.isPending}
              images={formData.images}
              onApply={applyStandardizeCandidate}
              onDismiss={() => setStandardizeCandidate(null)}
              options={formData.options}
              questionType={formData.type}
            />
          </div>
        ) : null}
      </div>

      {/* Right: Metadata */}
      <div className="w-full md:w-96 shrink-0 bg-card flex flex-col">
        <div className="h-12 px-6 border-b border-border flex justify-between items-center bg-card shrink-0">
          <span className="font-medium text-foreground">题目属性</span>
        </div>
        <div className="flex-1 overflow-auto p-4 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label>题型</Label>
              <select 
                value={formData.type} 
                onChange={e => setFormData(f => ({ ...f, type: e.target.value }))}
                className="w-full h-9 rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <option value="choice">选择题</option>
                <option value="fill_blank">填空题</option>
                <option value="solution">解答题</option>
                <option value="unknown">未知</option>
              </select>
            </div>
            <div className="space-y-1.5">
              <Label>难度</Label>
              <select 
                value={formData.difficulty} 
                onChange={e => setFormData(f => ({ ...f, difficulty: e.target.value }))}
                className="w-full h-9 rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <option value="easy">简单</option>
                <option value="medium">中等</option>
                <option value="hard">困难</option>
              </select>
            </div>
          </div>
          
          <div className="space-y-1.5">
            <Label>知识点</Label>
            <KnowledgePointSelect
              value={formData.knowledgePointIds}
              onChange={(knowledgePointIds) => setFormData(f => ({ ...f, knowledgePointIds }))}
            />
          </div>

          <div className="space-y-1.5">
            <Label>题图（关联图片）</Label>
            <p className="text-[11px] leading-relaxed text-muted-foreground/80">
              新增题图后会自动追加 <code className="px-1 py-0.5 rounded bg-muted font-mono">![](图N)</code> 到题干源码；也可拖拽题图或复制引用到指定位置。
            </p>
            <QuestionImageUploader
              images={formData.images}
              onChange={handleImagesChange}
              libraryImages={taskImageLibrary}
              uploadFiles={question.id ? async (files) => {
                const res = await api.uploadQuestionImages(question.id, files);
                return res.images || [];
              } : undefined}
            />
          </div>

          <div className="space-y-3 rounded-md border border-primary/15 bg-primary/5 p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="text-sm font-medium text-foreground">小问编辑（{subForms.length} 个）</div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleAddSubQuestion}
                className="h-8 gap-1.5 text-xs bg-card"
              >
                <Plus className="w-3.5 h-3.5" /> 添加小问
              </Button>
            </div>
            {!hasSubQuestions ? (
              <div className="rounded-md border border-dashed border-primary/25 bg-card/70 px-3 py-4 text-center text-xs leading-relaxed text-muted-foreground">
                当前题目暂无小问。点击「添加小问」可将普通题转换为大题带小问；原答案与解析会自动移动到第一个小问。
              </div>
            ) : (
              <>
                {subForms.map((sub, subIndex) => (
                <div key={sub.id || subIndex} className="space-y-3 rounded-md border border-border bg-card p-3">
                  <div className="flex items-center justify-between gap-2 border-b border-border/70 pb-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="inline-flex min-w-7 h-7 items-center justify-center rounded-md bg-primary/10 px-2 text-sm font-semibold text-primary">
                        {sub.label || subIndex + 1}
                      </span>
                      <span className="text-sm font-medium text-foreground">第 {subIndex + 1} 小问</span>
                    </div>
                    <div className="flex flex-wrap items-center justify-end gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => subStdMutation.mutate({ subIndex, markdown: sub.markdown })}
                        disabled={subStdMutation.isPending || !sub.markdown.trim()}
                        className="h-8 gap-1.5 text-xs"
                        title="仅标准化当前小问"
                      >
                        <Code className="w-3.5 h-3.5" />
                        {subStdMutation.isPending && activeSubStandardizeIndex === subIndex ? "标准化中" : "AI 标准化"}
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => subAnalysisMutation.mutate({ subIndex })}
                        disabled={subAnalysisMutation.isPending || !sub.markdown.trim()}
                        className="h-8 gap-1.5 text-xs text-warm border-warm/30 hover:bg-warm/10 hover:text-warm"
                        title="仅生成当前小问的答案和解析"
                      >
                        <Wand2 className="w-3.5 h-3.5" />
                        {subAnalysisMutation.isPending && activeSubAnalysisIndex === subIndex ? "解析中" : "AI 解析"}
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => setConfirmDeleteIndex(subIndex)}
                        className="h-8 gap-1.5 text-xs text-destructive hover:bg-destructive/10 hover:text-destructive"
                      >
                        <Trash2 className="w-3.5 h-3.5" /> 删除
                      </Button>
                    </div>
                  </div>
                  {subStandardizeCandidate?.subIndex === subIndex ? (
                    <StandardizeCandidatePanel
                      candidate={subStandardizeCandidate.candidate}
                      disabled={subStdMutation.isPending}
                      images={uniqueQuestionImages(formData.images, sub.images)}
                      onApply={applySubStandardizeCandidate}
                      onDismiss={() => setSubStandardizeCandidate(null)}
                      options={sub.options}
                      questionType={sub.type}
                    />
                  ) : null}
                  <div className="grid grid-cols-2 gap-2">
                    <div className="space-y-1.5">
                      <Label>标签</Label>
                      <Input value={sub.label} onChange={(e) => patchSub(subIndex, { label: e.target.value, autoLabel: false })} />
                    </div>
                    <div className="space-y-1.5">
                      <Label>分值</Label>
                      <Input
                        type="number"
                        min="0"
                        value={Number.isFinite(Number(sub.score)) ? sub.score : 0}
                        onChange={(e) => patchSub(subIndex, { score: e.target.value })}
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label>题型</Label>
                      <select
                        value={sub.type}
                        onChange={(e) => patchSub(subIndex, { type: e.target.value })}
                        className="w-full h-9 rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                      >
                        <option value="choice">选择题</option>
                        <option value="fill_blank">填空题</option>
                        <option value="solution">解答题</option>
                        <option value="short">简答题</option>
                        <option value="unknown">未知</option>
                      </select>
                    </div>
                    <div className="space-y-1.5">
                      <Label>难度</Label>
                      <select
                        value={sub.difficulty}
                        onChange={(e) => patchSub(subIndex, { difficulty: e.target.value })}
                        className="w-full h-9 rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                      >
                        <option value="easy">简单</option>
                        <option value="medium">中等</option>
                        <option value="hard">困难</option>
                      </select>
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    <Label>知识点</Label>
                    <KnowledgePointSelect
                      value={sub.knowledgePointIds}
                      onChange={(knowledgePointIds) => patchSub(subIndex, { knowledgePointIds })}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label>小问题干 (Markdown + LaTeX)</Label>
                    <Textarea
                      value={sub.markdown}
                      onChange={(e) => patchSub(subIndex, { markdown: e.target.value })}
                      rows={4}
                      className="font-mono text-sm"
                    />
                    {sub.markdown.trim() && (
                      <div className="rounded-md border border-border bg-muted/30">
                        <div className="px-3 py-1.5 border-b border-border text-xs font-medium text-muted-foreground">
                          实时预览
                        </div>
                        <div className="p-3 prose-container">
                          <MarkdownRenderer
                            content={sub.markdown}
                            images={sub.images}
                            questionType={sub.type}
                            options={sub.options}
                            siblingContent={[sub.answer, sub.analysis]}
                          />
                        </div>
                      </div>
                    )}
                  </div>
                  <LatexPreviewField
                    label="小问答案 (支持 LaTeX)"
                    value={sub.answer}
                    onChange={(answer) => patchSub(subIndex, { answer })}
                    placeholder="填写该小问的参考答案"
                    images={sub.images}
                  />
                  <LatexPreviewField
                    label="小问解析 (支持 LaTeX)"
                    value={sub.analysis}
                    onChange={(analysis) => patchSub(subIndex, { analysis })}
                    placeholder="填写该小问的解析"
                    images={sub.images}
                  />
                </div>
                ))}
              </>
            )}
          </div>

          {!hasSubQuestions && (
            <>
              <LatexPreviewField
                label="答案 (支持 LaTeX)"
                value={formData.answer}
                onChange={(answer) => setFormData(f => ({ ...f, answer }))}
                placeholder="支持 Markdown 与 LaTeX，例如：$x=\\frac{-b\\pm\\sqrt{b^2-4ac}}{2a}$"
                images={formData.images}
              />

              <LatexPreviewField
                label="解析 (支持 LaTeX)"
                value={formData.analysis}
                onChange={(analysis) => setFormData(f => ({ ...f, analysis }))}
                placeholder="支持 Markdown 与 LaTeX 公式渲染..."
                images={formData.images}
              />
            </>
          )}

          <details className="text-sm">
            <summary className="font-medium text-muted-foreground cursor-pointer">其他信息 (学科/年级/地区/年份/来源)</summary>
            <div className="grid grid-cols-2 gap-2 mt-2">
              <Input placeholder="学科" value={formData.subject} onChange={e => setFormData(f => ({ ...f, subject: e.target.value }))} />
              <Input placeholder="年级" value={formData.grade} onChange={e => setFormData(f => ({ ...f, grade: e.target.value }))} />
              <Input placeholder="地区" value={formData.region} onChange={e => setFormData(f => ({ ...f, region: e.target.value }))} />
              <Input placeholder="年份" value={formData.year} onChange={e => setFormData(f => ({ ...f, year: e.target.value }))} />
              <Input placeholder="来源" value={formData.source} onChange={e => setFormData(f => ({ ...f, source: e.target.value }))} className="col-span-2" />
            </div>
          </details>
        </div>
        <div className="p-4 border-t border-border bg-muted/40 shrink-0 flex gap-2 justify-end">
          <Button variant="outline" onClick={onCancel}>取消</Button>
          <Button onClick={handleSave}>保存</Button>
          {onVerified && (
            <Button className="bg-info text-info-foreground hover:bg-info/90" onClick={handleVerifiedSubmit}>已校验</Button>
          )}
          {extraActions}
        </div>
      </div>
      <AlertDialog
        open={confirmDeleteIndex !== null}
        onOpenChange={(open) => {
          if (!open) setConfirmDeleteIndex(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除该小问？</AlertDialogTitle>
            <AlertDialogDescription>
              {confirmDeleteIndex !== null
                ? `将删除「第 ${confirmDeleteIndex + 1} 小问」及其题干、答案、解析等内容。该操作保存后生效。`
                : ""}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (confirmDeleteIndex !== null) handleDeleteSubQuestion(confirmDeleteIndex);
                setConfirmDeleteIndex(null);
              }}
            >
              删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
