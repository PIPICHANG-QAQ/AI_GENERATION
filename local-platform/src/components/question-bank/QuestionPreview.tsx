import React from "react";
import { StatusTag } from "@/components/ui/StatusTag";
import { MarkdownRenderer } from "@/components/ui/MarkdownRenderer";
import { getImageKey, getQuestionImages, getSubQuestions, type QuestionImage } from "@/lib/question";
import { buildQuestionVisualModel, type QuestionVisualIssue } from "@/lib/question-visual-model";

const metaPill = "text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded-md border border-border";

function mergeImages(...groups: QuestionImage[][]): QuestionImage[] {
  const seen = new Set<string>();
  const merged: QuestionImage[] = [];
  groups.flat().forEach((img, index) => {
    const key = getImageKey(img) || `${img.url || ""}|${img.path || ""}|${img.name || ""}|${index}`;
    if (seen.has(key)) return;
    seen.add(key);
    merged.push(img);
  });
  return merged;
}

function VisualIssues({ issues }: { issues: QuestionVisualIssue[] }) {
  if (issues.length === 0) return null;
  return (
    <div className="mt-2 space-y-1">
      {issues.map((issue, index) => (
        <div
          key={`${issue.code}-${issue.imageId || issue.optionLabel || index}`}
          className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-2 py-1"
        >
          {issue.message}
        </div>
      ))}
    </div>
  );
}

export function QuestionPreview({
  question,
  showAnswers = true,
  showMeta = false,
}: {
  question: any;
  showAnswers?: boolean;
  showMeta?: boolean;
}) {
  const q = question || {};
  const visual = buildQuestionVisualModel(q);
  const questionImages = visual.images;
  const subQuestions = getSubQuestions(q);

  return (
    <div>
      {showMeta && (
        <div className="flex gap-2 flex-wrap items-center mb-3">
          <StatusTag status={q.difficulty || "medium"} type="difficulty" />
          {q.subject && <span className={metaPill}>{q.subject}</span>}
          {q.grade && <span className={metaPill}>{q.grade}</span>}
          {q.region && <span className={metaPill}>{q.region}</span>}
          {q.year && <span className={metaPill}>{q.year}年</span>}
          {q.knowledgePoints?.map((kp: string) => (
            <span key={kp} className={metaPill}>{kp}</span>
          ))}
        </div>
      )}

      <div className="mb-4">
        <MarkdownRenderer
          content={visual.stemMarkdown}
          images={questionImages}
          questionType={q.type}
          options={visual.options}
          siblingContent={[q.answer, q.analysis]}
          preferStructuredOptions
        />
        <VisualIssues issues={visual.issues} />
      </div>

      {subQuestions.length > 0 ? (
        <div className="space-y-3 rounded-md border border-primary/15 bg-primary/5 p-3">
          {subQuestions.map((sub: any, subIndex: number) => {
            const subImages = mergeImages(questionImages, getQuestionImages(sub));
            const subVisual = buildQuestionVisualModel({ ...sub, images: subImages });
            return (
              <div key={sub.id || subIndex} className="rounded-md border border-border bg-card p-3">
                <div className="flex flex-wrap items-center gap-2 mb-2">
                  <span className="text-xs font-semibold text-foreground">
                    {sub.label || `(${subIndex + 1})`}
                  </span>
                  <StatusTag status={sub.type || q.type || "unknown"} type="qtype" />
                  <StatusTag status={sub.difficulty || q.difficulty || "medium"} type="difficulty" />
                  <span className="text-xs text-muted-foreground">{Number(sub.score) || 0} 分</span>
                </div>
                <div className="text-sm text-foreground/80">
                  <MarkdownRenderer
                    content={subVisual.stemMarkdown}
                    images={subVisual.images}
                    questionType={sub.type || q.type}
                    options={subVisual.options}
                    siblingContent={[sub.answer, sub.analysis]}
                    preferStructuredOptions
                  />
                  <VisualIssues issues={subVisual.issues} />
                </div>
                {showAnswers && (
                  <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
                    <div className="bg-muted/50 p-3 rounded-md text-foreground/80 min-w-0">
                      <span className="font-medium text-foreground block mb-1">答案：</span>
                      <div className="line-clamp-2">
                        {sub.answer ? (
                          <MarkdownRenderer content={sub.answer} images={subImages} showUnreferenced={false} />
                        ) : (
                          "暂无"
                        )}
                      </div>
                    </div>
                    <div className="bg-muted/50 p-3 rounded-md text-foreground/80 min-w-0">
                      <span className="font-medium text-foreground block mb-1">解析：</span>
                      <div className="line-clamp-2">
                        {sub.analysis ? (
                          <MarkdownRenderer content={sub.analysis} images={subImages} showUnreferenced={false} />
                        ) : (
                          "暂无"
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        showAnswers && (
          <div className="flex flex-col sm:flex-row gap-4 text-sm">
            <div className="flex-1 bg-muted/50 p-3 rounded-md text-foreground/80 min-w-0">
              <span className="font-medium text-foreground block mb-1">答案：</span>
              <div className="line-clamp-2">
                {q.answer ? <MarkdownRenderer content={q.answer} images={questionImages} showUnreferenced={false} /> : "暂无"}
              </div>
            </div>
            <div className="flex-1 bg-muted/50 p-3 rounded-md text-foreground/80 min-w-0">
              <span className="font-medium text-foreground block mb-1">解析：</span>
              <div className="line-clamp-2">
                {q.analysis ? <MarkdownRenderer content={q.analysis} images={questionImages} showUnreferenced={false} /> : "暂无"}
              </div>
            </div>
          </div>
        )
      )}
    </div>
  );
}
