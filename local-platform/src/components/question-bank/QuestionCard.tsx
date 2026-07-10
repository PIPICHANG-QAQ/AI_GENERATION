import React, { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { StatusTag } from "@/components/ui/StatusTag";
import { MarkdownRenderer } from "@/components/ui/MarkdownRenderer";
import { QuestionImageUploader } from "@/components/question-bank/QuestionImageUploader";
import { MarkdownChipEditor } from "@/components/question-bank/MarkdownChipEditor";
import {
  AiStandardizeJobStatus,
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
  ensureQuestionImageLabels,
  filterRemovedQuestionImages,
  getRemovedQuestionImages,
  getQuestionImages,
  getQuestionMarkdown,
  getQuestionMarkdownParts,
  getSubQuestions,
  mergeSubQuestionSuggestions,
  normalizeQuestionOptions,
  removeQuestionImageRefsFromOptions,
  removeQuestionImageRefsFromMarkdown,
  serializeQuestionOptions,
  removeSubQuestionForm,
  subQuestionEditorForm,
  type QuestionImage,
} from "@/lib/question";
import {
  aiAnalysisFallbackMessage,
  buildSubQuestionAnalysisPayload,
  subAnalysisPatch,
  subStandardizePatch,
  uniqueQuestionImages,
} from "@/lib/sub-question-ai";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/hooks/use-toast";
import { Wand2, Code, Save, Eye, Pencil, Database, CheckCircle2, ImageIcon, Plus, Trash2 } from "lucide-react";
import { QuestionPreview } from "./QuestionPreview";

const selectClass =
  "w-full h-9 rounded-md border border-input bg-card px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-60 disabled:cursor-not-allowed";

export function QuestionCard({ index, question, taskId }: { index: number; question: any; taskId: string }) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const qid = question.id;

  const isBanked = question.status === "已入库";
  const isVerified = question.status === "已校验";
  const initialImages = ensureQuestionImageLabels(getQuestionImages(question));
  const initialMarkdown = getQuestionMarkdown(question);

  const [mode, setMode] = useState<"preview" | "edit">("preview");
  const [dirty, setDirty] = useState(false);
  const [formData, setFormData] = useState({
    markdown: isBanked
      ? initialMarkdown
      : appendMissingImageRefs(initialMarkdown, initialImages, [question.answer || "", question.analysis || ""]),
    type: question.type || "unknown",
    difficulty: question.difficulty || "medium",
    score: question.score ?? 0,
    answer: question.answer || "",
    analysis: question.analysis || "",
    knowledgePoints: question.knowledgePoints?.join("，") || "",
    options: normalizeQuestionOptions(question.options, initialImages),
  });
  const [subForms, setSubForms] = useState(() =>
    getSubQuestions(question).map((sub: any, subIndex: number) => {
      const form = subQuestionEditorForm(sub, subIndex, question);
      return isBanked
        ? form
        : {
            ...form,
            markdown: appendMissingImageRefs(form.markdown, form.images, [form.answer, form.analysis]),
          };
    }),
  );

  const [images, setImages] = useState<QuestionImage[]>(initialImages);
  const [standardizeCandidate, setStandardizeCandidate] = useState<StandardizeCandidate | null>(null);
  const [subStandardizeCandidate, setSubStandardizeCandidate] = useState<{
    subIndex: number;
    candidate: StandardizeCandidate;
  } | null>(null);
  const [activeSubStandardizeIndex, setActiveSubStandardizeIndex] = useState<number | null>(null);
  const [activeSubAnalysisIndex, setActiveSubAnalysisIndex] = useState<number | null>(null);
  const [confirmDeleteIndex, setConfirmDeleteIndex] = useState<number | null>(null);
  const readOnly = false;
  const hasSubQuestions = subForms.length > 0;
  const canBank = isVerified || isBanked;

  const { data: imageLibraryData } = useQuery({
    queryKey: ["importTaskImageLibrary", taskId],
    queryFn: () => api.getImportTaskImageLibrary(taskId),
    enabled: !readOnly,
  });
  const taskImageLibrary: QuestionImage[] = imageLibraryData?.items || [];

  const subKnowledgePointNames = (sub: any) =>
    String(sub.knowledgePoints || "")
      .split(/[,，]/)
      .map((s: string) => s.trim())
      .filter(Boolean);

  const patch = (p: Partial<typeof formData>) => {
    setFormData(f => ({ ...f, ...p }));
    if (Object.prototype.hasOwnProperty.call(p, "markdown")) {
      setStandardizeCandidate(null);
    }
    setDirty(true);
  };

  const handleImagesChange = (next: QuestionImage[]) => {
    const previousImages = ensureQuestionImageLabels(images);
    const nextImages = ensureQuestionImageLabels(next, previousImages);
    const removedImages = getRemovedQuestionImages(previousImages, nextImages);
    const cleanedSubForms = subForms.map((sub) => ({
      ...sub,
      markdown: removeQuestionImageRefsFromMarkdown(sub.markdown, removedImages),
      answer: removeQuestionImageRefsFromMarkdown(sub.answer, removedImages),
      analysis: removeQuestionImageRefsFromMarkdown(sub.analysis, removedImages),
      options: removeQuestionImageRefsFromOptions(sub.options, removedImages),
      images: filterRemovedQuestionImages(sub.images, removedImages),
    }));
    setFormData((f) => ({
      ...f,
      markdown: appendNewImageRefs(
        removeQuestionImageRefsFromMarkdown(f.markdown, removedImages),
        previousImages,
        nextImages,
        [
          removeQuestionImageRefsFromMarkdown(f.answer, removedImages),
          removeQuestionImageRefsFromMarkdown(f.analysis, removedImages),
          ...removeQuestionImageRefsFromOptions(f.options, removedImages).map((option) => option.content),
          ...cleanedSubForms.flatMap((sub) => [
            sub.markdown,
            sub.answer,
            sub.analysis,
            ...normalizeQuestionOptions(sub.options, sub.images).map((option) => option.content),
          ]),
        ],
      ),
      answer: removeQuestionImageRefsFromMarkdown(f.answer, removedImages),
      analysis: removeQuestionImageRefsFromMarkdown(f.analysis, removedImages),
      options: removeQuestionImageRefsFromOptions(f.options, removedImages),
    }));
    setSubForms(cleanedSubForms);
    setImages(nextImages);
    setStandardizeCandidate(null);
    setSubStandardizeCandidate(null);
    setDirty(true);
  };

  const withSubImageRefs = (subs: typeof subForms) =>
    subs.map((sub) => ({
      ...sub,
      markdown: sub.markdown,
    }));

  const updateMutation = useMutation({
    mutationFn: (data: any) => api.updateImportQuestion(taskId, qid, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["importTask", taskId] });
    },
    onError: (err: any) => toast({ title: "保存失败", description: err.message, variant: "destructive" }),
  });

  const standardizedQuestionDraft = (candidate: StandardizeCandidate) => {
    const res = candidate.payload || {};
    const updatedQuestion = res?.question || {};
    const suggestedAnswer = String(res?.answer ?? res?.suggestedAnswer ?? updatedQuestion.answer ?? "").trim();
    const suggestedAnalysis = String(res?.analysis ?? updatedQuestion.analysis ?? "").trim();
    const updatedOptions = normalizeQuestionOptions(res?.options ?? updatedQuestion.options, images);
    const nextSubForms = withSubImageRefs(
      mergeSubQuestionSuggestions(
        subForms,
        res?.subQuestions ?? updatedQuestion.subQuestions ?? updatedQuestion.children,
        question,
      ),
    );
    const nextHasSubQuestions = nextSubForms.length > 0;
    const nextFormData = {
      ...formData,
      markdown: candidate.markdown,
      answer: nextHasSubQuestions ? "" : suggestedAnswer || formData.answer,
      analysis: nextHasSubQuestions ? "" : suggestedAnalysis || formData.analysis,
      options: updatedOptions.length > 0 ? updatedOptions : formData.options,
    };
    return { nextFormData, nextSubForms };
  };

  const saveStandardizedDraft = (
    nextFormData: typeof formData,
    nextSubForms: typeof subForms,
    successTitle: string,
  ) => {
    setFormData(nextFormData);
    setSubForms(nextSubForms);
    setStandardizeCandidate(null);
    setSubStandardizeCandidate(null);
    setDirty(true);
    updateMutation.mutate(prepareData(nextFormData, nextSubForms), {
      onSuccess: () => {
        setDirty(false);
        toast({ title: successTitle });
      },
    });
  };

  const bankMutation = useMutation({
    mutationFn: () => api.bankImportQuestion(taskId, qid),
    onSuccess: () => {
      toast({ title: isBanked ? "题目已覆盖入库" : "单题入库成功" });
      queryClient.invalidateQueries({ queryKey: ["importTask", taskId] });
      queryClient.invalidateQueries({ queryKey: ["questions"] });
    },
    onError: (err: any) => toast({ title: "入库失败", description: err.message, variant: "destructive" }),
  });

  const localStdMutation = useMutation({
    mutationFn: (md: string) => api.standardizeImportQuestionAi(taskId, qid, md),
    onSuccess: (res: any, md) => {
      const result = standardizeCandidateFromPayload(md, res);
      if (result.candidate?.applyBlocked) {
        setStandardizeCandidate(result.candidate);
        toast({ title: "AI 标准化候选需人工复核", description: result.message });
        return;
      }
      if (result.candidate) {
        const { nextFormData, nextSubForms } = standardizedQuestionDraft(result.candidate);
        saveStandardizedDraft(nextFormData, nextSubForms, "AI 标准化已应用并保存");
        return;
      }
      setStandardizeCandidate(null);
      toast({ title: "AI 标准化完成", description: result.message });
    },
    onError: (err: any) => toast({ title: "标准化失败", description: err.message, variant: "destructive" }),
  });

  const applyStandardizeCandidate = () => {
    if (!standardizeCandidate) return;
    const { nextFormData, nextSubForms } = standardizedQuestionDraft(standardizeCandidate);
    saveStandardizedDraft(nextFormData, nextSubForms, "AI 标准化候选已应用并保存");
  };

  const aiAnalysisMutation = useMutation({
    mutationFn: () => {
      const draft = prepareData();
      return api.generateImportQuestionAnalysis(taskId, qid, {
        manualMarkdown: draft.manualMarkdown,
        type: draft.type,
        answer: draft.answer,
        knowledgePoints: draft.knowledgePoints,
        images: draft.images,
        subQuestions: draft.subQuestions,
      });
    },
    onSuccess: (res: any) => {
      const fallbackMessage = aiAnalysisFallbackMessage(res);
      if (fallbackMessage) {
        toast({ title: "AI 解析暂时不可用", description: fallbackMessage });
        return;
      }
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
      setDirty(true);
      toast({ title: "AI 解析生成完成" });
    },
    onError: (err: any) => toast({ title: "AI 解析生成失败", description: err.message, variant: "destructive" }),
  });

  const subStdMutation = useMutation({
    mutationFn: ({ markdown }: { subIndex: number; markdown: string }) => api.standardizeAi(markdown),
    onMutate: ({ subIndex }) => setActiveSubStandardizeIndex(subIndex),
    onSuccess: (res: any, { subIndex, markdown }) => {
      const result = standardizeCandidateFromPayload(markdown, res);
      if (result.candidate?.applyBlocked) {
        setSubStandardizeCandidate({ subIndex, candidate: result.candidate });
        toast({ title: "小问 AI 标准化候选需人工复核", description: result.message });
      } else {
        const patch = result.candidate
          ? subStandardizePatch(result.candidate.markdown, result.candidate.payload || {})
          : subStandardizePatch(markdown, res);
        if (!Object.keys(patch).length) {
          toast({ title: "小问 AI 标准化完成", description: result.message });
          return;
        }
        const nextSubForms = subForms.map((sub, index) => (index === subIndex ? { ...sub, ...patch } : sub));
        saveStandardizedDraft(formData, nextSubForms, "小问 AI 标准化已应用并保存");
      }
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
          parentImages: images,
          sub,
          knowledgePoints: subKnowledgePointNames(sub),
        }),
      );
    },
    onMutate: ({ subIndex }) => setActiveSubAnalysisIndex(subIndex),
    onSuccess: (res: any, { subIndex }) => {
      const fallbackMessage = aiAnalysisFallbackMessage(res);
      if (fallbackMessage) {
        toast({ title: "小问 AI 解析暂时不可用", description: fallbackMessage });
        return;
      }
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
    const patch = subStandardizePatch(candidate.markdown, candidate.payload || {});
    const nextSubForms = subForms.map((sub, index) => (index === subIndex ? { ...sub, ...patch } : sub));
    saveStandardizedDraft(formData, nextSubForms, "小问 AI 标准化候选已应用并保存");
  };

  const prepareData = (
    draftFormData: typeof formData = formData,
    draftSubForms: typeof subForms = subForms,
  ) => {
    const { markdown, ...rest } = draftFormData;
    const questionParts = getQuestionMarkdownParts(markdown, draftFormData.type, draftFormData.options, images);
    const draftHasSubQuestions = draftSubForms.length > 0;
    const subQuestions = draftSubForms.map((sub) => {
      const subParts = getQuestionMarkdownParts(sub.markdown, sub.type, sub.options, sub.images);
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
        knowledgePoints: sub.knowledgePoints.split(/[,，]/).map((s: string) => s.trim()).filter(Boolean),
        options: serializeQuestionOptions(subParts.options, sub.images),
        images: sub.images,
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
      score: Number(draftFormData.score) || 0,
      answer: draftHasSubQuestions ? "" : draftFormData.answer,
      analysis: draftHasSubQuestions ? "" : draftFormData.analysis,
      knowledgePointIds: question.knowledgePointIds || [],
      knowledgePoints: draftFormData.knowledgePoints.split(/[,，]/).map((s: string) => s.trim()).filter(Boolean),
      options: serializeQuestionOptions(questionParts.options, images),
      images,
      subQuestions,
      children: subQuestions,
    };
  };

  const patchSub = (subIndex: number, patchValue: Partial<(typeof subForms)[number]>) => {
    setSubForms((prev) => prev.map((sub, i) => (i === subIndex ? { ...sub, ...patchValue } : sub)));
    if (Object.prototype.hasOwnProperty.call(patchValue, "markdown")) {
      setSubStandardizeCandidate((current) => (current?.subIndex === subIndex ? null : current));
    }
    setDirty(true);
  };

  const handleAddSubQuestion = () => {
    if (readOnly) return;
    const wasPlainQuestion = subForms.length === 0;
    setSubForms((prev) => addSubQuestionForm(prev, formData));
    if (wasPlainQuestion && (formData.answer || formData.analysis)) {
      setFormData((f) => ({ ...f, answer: "", analysis: "" }));
    }
    setStandardizeCandidate(null);
    setSubStandardizeCandidate(null);
    setDirty(true);
  };

  const handleDeleteSubQuestion = (subIndex: number) => {
    if (readOnly) return;
    setSubForms((prev) => removeSubQuestionForm(prev, subIndex));
    setStandardizeCandidate(null);
    setSubStandardizeCandidate(null);
    setDirty(true);
  };

  const handleSave = () => {
    updateMutation.mutate(prepareData(), {
      onSuccess: () => {
        setDirty(false);
        toast({ title: "保存成功" });
      },
    });
  };

  const handleVerified = () => {
    updateMutation.mutate({ ...prepareData(), status: "已校验" }, {
      onSuccess: () => {
        setDirty(false);
        toast({ title: "题目已标记为已校验" });
      },
    });
  };

  const handleBank = () => {
    if (dirty) {
      updateMutation.mutate(prepareData(), {
        onSuccess: () => {
          setDirty(false);
          bankMutation.mutate();
        },
      });
    } else {
      bankMutation.mutate();
    }
  };

  const cardTone = isBanked
    ? "border-success/40"
    : isVerified
      ? "border-info/40"
      : "border-border";

  return (
    <div id={`import-q-${qid}`} className={`@container border ${cardTone} bg-card rounded-lg elevation-1 transition-all`}>
      {/* Header */}
      <div className="px-4 py-2.5 border-b border-border flex flex-wrap gap-y-2 justify-between items-center bg-muted/40 rounded-t-lg">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className="text-sm font-bold text-foreground whitespace-nowrap">第 {index} 题</span>
          <StatusTag status={formData.type || "unknown"} type="qtype" />
          <StatusTag status={question.status || "待校验"} type="question" />
          {hasSubQuestions && (
            <span className="text-xs text-primary bg-primary/10 border border-primary/20 px-2 py-0.5 rounded-md">
              含 {subForms.length} 小问
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {!readOnly && (
            <>
              <Button
                size="sm"
                variant="outline"
                onClick={handleSave}
                disabled={updateMutation.isPending}
                className="h-8 gap-1.5 text-xs"
              >
                <Save className="w-3.5 h-3.5" /> 保存
              </Button>
              {!isBanked && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleVerified}
                  disabled={updateMutation.isPending}
                  className="h-8 gap-1.5 text-xs text-info border-info/40 hover:bg-info/10 hover:text-info"
                >
                  <CheckCircle2 className="w-3.5 h-3.5" /> 已校验
                </Button>
              )}
            </>
          )}
          <Button
            size="sm"
            onClick={handleBank}
            disabled={!canBank || bankMutation.isPending || updateMutation.isPending}
            className={`h-8 gap-1.5 text-xs ${canBank ? "bg-success text-success-foreground hover:bg-success/90" : ""}`}
          >
            <Database className="w-3.5 h-3.5" /> {bankMutation.isPending ? "入库中" : isBanked ? "重新入库" : "入库"}
          </Button>
          <button
            onClick={() => setMode((current) => (current === "edit" ? "preview" : "edit"))}
            className="w-8 h-8 inline-flex items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
            title={mode === "edit" ? "切换到预览模式" : "切换到编辑模式"}
            aria-label={mode === "edit" ? "切换到预览模式" : "切换到编辑模式"}
          >
            {mode === "edit" ? <Eye className="w-3.5 h-3.5" /> : <Pencil className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>

      <div className="p-4">
        {mode === "preview" && (
          <div className="space-y-3">
            {!readOnly && (
              <p className="text-xs text-muted-foreground">预览基于已保存的内容，未保存的修改请先保存再查看。</p>
            )}
            <QuestionPreview question={question} showAnswers showMeta />
          </div>
        )}
        <div className={mode === "preview" ? "hidden" : "space-y-4"}>
          {/* Markdown toolbar */}
          <div className="flex flex-wrap gap-y-2 items-center justify-between">
            <span className="text-sm font-medium text-foreground">Markdown + LaTeX</span>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => localStdMutation.mutate(formData.markdown)}
                disabled={readOnly || localStdMutation.isPending || updateMutation.isPending || !formData.markdown}
                className="h-8 gap-1.5 text-xs"
              >
                <Code className="w-3.5 h-3.5" /> AI 标准化
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => aiAnalysisMutation.mutate()}
                disabled={readOnly || aiAnalysisMutation.isPending || !formData.markdown}
                className="h-8 gap-1.5 text-xs text-warm border-warm/30 hover:bg-warm/10 hover:text-warm"
                title={hasSubQuestions ? "AI 将按小问分别生成答案和解析" : undefined}
              >
                <Wand2 className="w-3.5 h-3.5" /> {aiAnalysisMutation.isPending ? "AI 解析中" : "AI 解析"}
              </Button>
              {!readOnly && (
                <Button size="sm" onClick={handleSave} disabled={updateMutation.isPending} className="h-8 gap-1.5 text-xs">
                  <Save className="w-3.5 h-3.5" /> 保存
                </Button>
              )}
            </div>
          </div>

          {/* Source + live preview */}
          <div className="grid grid-cols-1 @2xl:grid-cols-2 gap-3">
            <div className="flex flex-col">
              <span className="text-xs font-medium text-muted-foreground mb-1.5">题干源码</span>
              <MarkdownChipEditor
                editorId={`import-q-editor-${qid}-stem`}
                value={formData.markdown}
                onChange={(value) => patch({ markdown: value })}
                readOnly={readOnly}
                variant="source"
                className="min-h-[220px] font-mono text-xs leading-relaxed"
                placeholder="在此输入题干 Markdown..."
              />
            </div>
            <div className="flex flex-col">
              <span className="text-xs font-medium text-muted-foreground mb-1.5">题目预览</span>
              <div className="min-h-[220px] flex-1 p-3 rounded-md border border-border bg-card overflow-auto prose-container">
                <MarkdownRenderer
                  content={formData.markdown}
                  images={images}
                  questionType={formData.type}
                  options={formData.options}
                  siblingContent={[formData.answer, formData.analysis]}
                />
              </div>
            </div>
          </div>

          {standardizeCandidate ? (
            <StandardizeCandidatePanel
              candidate={standardizeCandidate}
              disabled={localStdMutation.isPending || updateMutation.isPending}
              images={images}
              onApply={applyStandardizeCandidate}
              onDismiss={() => setStandardizeCandidate(null)}
              options={formData.options}
              questionType={formData.type}
            />
          ) : null}
          {!standardizeCandidate ? (
            <AiStandardizeJobStatus active={localStdMutation.isPending} />
          ) : null}

          {/* Question images */}
          <div className="space-y-1.5">
            <span className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
              <ImageIcon className="w-3.5 h-3.5" /> 题图（关联图片）
            </span>
            {!readOnly && (
              <p className="text-[11px] leading-relaxed text-muted-foreground/80">
                上传或从题图库添加题图后，会自动在题干源码中插入{" "}
                <code className="px-1 py-0.5 rounded bg-muted font-mono">![](图N)</code>{" "}
                引用，并显示为「图N」小标签；标签可整体拖拽到题干、答案或解析，双击可编辑文字。
              </p>
            )}
            <QuestionImageUploader
              images={images}
              onChange={handleImagesChange}
              readOnly={readOnly}
              libraryImages={taskImageLibrary}
              onSelectLibraryImages={async (selected) => {
                const res = await api.selectImportQuestionImages(taskId, qid, selected);
                queryClient.invalidateQueries({ queryKey: ["importTask", taskId] });
                queryClient.invalidateQueries({ queryKey: ["importTaskImageLibrary", taskId] });
                setDirty(false);
                return res.images || [];
              }}
              uploadFiles={async (files) => {
                const res = await api.uploadImportQuestionImages(taskId, qid, files);
                setDirty(true);
                queryClient.invalidateQueries({ queryKey: ["importTaskImageLibrary", taskId] });
                return res.images || [];
              }}
            />
          </div>

          {/* Metadata row */}
          <div className="grid grid-cols-2 @2xl:grid-cols-3 gap-3">
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">题型</Label>
              <select
                value={formData.type}
                onChange={e => patch({ type: e.target.value })}
                disabled={readOnly}
                className={selectClass}
              >
                <option value="choice">选择题</option>
                <option value="fill_blank">填空题</option>
                <option value="solution">解答题</option>
                <option value="unknown">未知</option>
              </select>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">难度</Label>
              <select
                value={formData.difficulty}
                onChange={e => patch({ difficulty: e.target.value })}
                disabled={readOnly}
                className={selectClass}
              >
                <option value="easy">简单</option>
                <option value="medium">中等</option>
                <option value="hard">困难</option>
              </select>
            </div>
            <div className="space-y-1.5 col-span-2 @2xl:col-span-1">
              <Label className="text-xs text-muted-foreground">知识点</Label>
              <Input
                value={formData.knowledgePoints}
                onChange={e => patch({ knowledgePoints: e.target.value })}
                readOnly={readOnly}
                placeholder="输入知识点，逗号分隔"
                className="h-9"
              />
            </div>
          </div>

          {!hasSubQuestions && !readOnly ? (
            <div className="space-y-3 rounded-md border border-border bg-card p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="text-sm font-medium text-foreground">小问编辑（0 个）</div>
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
              <div className="rounded-md border border-dashed border-primary/25 bg-card/70 px-3 py-4 text-center text-xs leading-relaxed text-muted-foreground">
                当前题目暂无小问。点击「添加小问」可将普通题转换为大题带小问；原答案与解析会自动移动到第一个小问。
              </div>
            </div>
          ) : null}

          {hasSubQuestions ? (
            <div className="space-y-3 rounded-md border border-border bg-card p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="text-sm font-medium text-foreground">小问编辑（{subForms.length} 个）</div>
                {!readOnly && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={handleAddSubQuestion}
                    className="h-8 gap-1.5 text-xs bg-card"
                  >
                    <Plus className="w-3.5 h-3.5" /> 添加小问
                  </Button>
                )}
              </div>
              {subForms.map((sub, subIndex) => (
                <div key={sub.id || subIndex} className="space-y-3 rounded-md border border-border bg-card p-3">
                  <div className="flex items-center justify-between gap-2 border-b border-border/70 pb-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="inline-flex min-w-7 h-7 items-center justify-center rounded-md bg-primary/10 px-2 text-sm font-semibold text-primary">
                        {sub.label || subIndex + 1}
                      </span>
                      <span className="text-sm font-medium text-foreground">第 {subIndex + 1} 小问</span>
                      <StatusTag status={sub.type || "unknown"} type="qtype" />
                    </div>
                    {!readOnly && (
                      <div className="flex flex-wrap items-center justify-end gap-2">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => subStdMutation.mutate({ subIndex, markdown: sub.markdown })}
                          disabled={subStdMutation.isPending || updateMutation.isPending || !sub.markdown.trim()}
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
                    )}
                  </div>
                  {subStandardizeCandidate?.subIndex === subIndex ? (
                    <StandardizeCandidatePanel
                      candidate={subStandardizeCandidate.candidate}
                      disabled={subStdMutation.isPending || updateMutation.isPending}
                      images={uniqueQuestionImages(images, sub.images)}
                      onApply={applySubStandardizeCandidate}
                      onDismiss={() => setSubStandardizeCandidate(null)}
                      options={sub.options}
                      questionType={sub.type}
                    />
                  ) : null}
                  {subStandardizeCandidate?.subIndex !== subIndex ? (
                    <AiStandardizeJobStatus
                      active={subStdMutation.isPending && activeSubStandardizeIndex === subIndex}
                      label="小问 AI 标准化"
                    />
                  ) : null}
                  <div className="grid grid-cols-2 @2xl:grid-cols-4 gap-3">
                    <div className="space-y-1.5">
                      <Label className="text-xs text-muted-foreground">标签</Label>
                      <Input value={sub.label} onChange={(e) => patchSub(subIndex, { label: e.target.value, autoLabel: false })} readOnly={readOnly} className="h-9" />
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs text-muted-foreground">分值</Label>
                      <Input
                        type="number"
                        min="0"
                        value={Number.isFinite(Number(sub.score)) ? sub.score : 0}
                        onChange={(e) => patchSub(subIndex, { score: e.target.value })}
                        readOnly={readOnly}
                        className="h-9"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs text-muted-foreground">题型</Label>
                      <select
                        value={sub.type}
                        onChange={(e) => patchSub(subIndex, { type: e.target.value })}
                        disabled={readOnly}
                        className={selectClass}
                      >
                        <option value="choice">选择题</option>
                        <option value="fill_blank">填空题</option>
                        <option value="solution">解答题</option>
                        <option value="short">简答题</option>
                        <option value="unknown">未知</option>
                      </select>
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs text-muted-foreground">难度</Label>
                      <select
                        value={sub.difficulty}
                        onChange={(e) => patchSub(subIndex, { difficulty: e.target.value })}
                        disabled={readOnly}
                        className={selectClass}
                      >
                        <option value="easy">简单</option>
                        <option value="medium">中等</option>
                        <option value="hard">困难</option>
                      </select>
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">知识点</Label>
                    <Input
                      value={sub.knowledgePoints}
                      onChange={(e) => patchSub(subIndex, { knowledgePoints: e.target.value })}
                      readOnly={readOnly}
                      placeholder="输入知识点，逗号分隔"
                      className="h-9"
                    />
                  </div>
                  <div className="grid grid-cols-1 @2xl:grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">小问题干</Label>
                      <MarkdownChipEditor
                        editorId={`import-q-editor-${qid}-sub-${subIndex}-stem`}
                        value={sub.markdown}
                        onChange={(value) => patchSub(subIndex, { markdown: value })}
                        readOnly={readOnly}
                        variant="source"
                        rows={4}
                        className="font-mono text-xs leading-relaxed"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs text-muted-foreground">小问预览</Label>
                      <div className="min-h-[120px] p-3 rounded-md border border-border bg-card overflow-auto prose-container">
                        <MarkdownRenderer
                          content={sub.markdown}
                          images={sub.images}
                          questionType={sub.type}
                          options={sub.options}
                          siblingContent={[sub.answer, sub.analysis]}
                        />
                      </div>
                    </div>
                  </div>
                  <div className="grid grid-cols-1 @2xl:grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <Label className="text-xs text-muted-foreground">答案（支持 LaTeX）</Label>
                      <MarkdownChipEditor
                        editorId={`import-q-editor-${qid}-sub-${subIndex}-answer`}
                        value={sub.answer}
                        onChange={(value) => patchSub(subIndex, { answer: value })}
                        readOnly={readOnly}
                        rows={4}
                        className="font-mono text-xs leading-relaxed"
                      />
                      {sub.answer.trim() && (
                        <div className="rounded-md border border-border bg-card overflow-auto prose-container">
                          <span className="block px-3 py-1.5 border-b border-border text-xs font-medium text-muted-foreground">预览</span>
                          <div className="p-3">
                            <MarkdownRenderer content={sub.answer} images={sub.images} showUnreferenced={false} />
                          </div>
                        </div>
                      )}
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs text-muted-foreground">解析（支持 LaTeX）</Label>
                      <MarkdownChipEditor
                        editorId={`import-q-editor-${qid}-sub-${subIndex}-analysis`}
                        value={sub.analysis}
                        onChange={(value) => patchSub(subIndex, { analysis: value })}
                        readOnly={readOnly}
                        rows={4}
                        className="font-mono text-xs leading-relaxed"
                      />
                      {sub.analysis.trim() && (
                        <div className="rounded-md border border-border bg-card overflow-auto prose-container">
                          <span className="block px-3 py-1.5 border-b border-border text-xs font-medium text-muted-foreground">预览</span>
                          <div className="p-3">
                            <MarkdownRenderer content={sub.analysis} images={sub.images} showUnreferenced={false} />
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-1 @2xl:grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">答案（支持 LaTeX）</Label>
                <MarkdownChipEditor
                  editorId={`import-q-editor-${qid}-answer`}
                  value={formData.answer}
                  onChange={(value) => patch({ answer: value })}
                  readOnly={readOnly}
                  rows={4}
                  className="font-mono text-xs leading-relaxed"
                  placeholder="填写参考答案"
                />
                {formData.answer.trim() && (
                  <div className="rounded-md border border-border bg-card overflow-auto prose-container">
                    <span className="block px-3 py-1.5 border-b border-border text-xs font-medium text-muted-foreground">预览</span>
                    <div className="p-3">
                      <MarkdownRenderer content={formData.answer} images={images} showUnreferenced={false} />
                    </div>
                  </div>
                )}
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">解析（支持 LaTeX）</Label>
                <MarkdownChipEditor
                  editorId={`import-q-editor-${qid}-analysis`}
                  value={formData.analysis}
                  onChange={(value) => patch({ analysis: value })}
                  readOnly={readOnly}
                  rows={4}
                  className="font-mono text-xs leading-relaxed"
                  placeholder="填写题目解析"
                />
                {formData.analysis.trim() && (
                  <div className="rounded-md border border-border bg-card overflow-auto prose-container">
                    <span className="block px-3 py-1.5 border-b border-border text-xs font-medium text-muted-foreground">预览</span>
                    <div className="p-3">
                      <MarkdownRenderer content={formData.analysis} images={images} showUnreferenced={false} />
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
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
