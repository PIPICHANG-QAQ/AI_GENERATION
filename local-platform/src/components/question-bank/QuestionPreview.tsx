import React from "react";
import { StatusTag } from "@/components/ui/StatusTag";
import { MarkdownRenderer } from "@/components/ui/MarkdownRenderer";
import { getImageKey, getQuestionImages, getQuestionMarkdown, getSubQuestions, type QuestionImage } from "@/lib/question";

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
  const questionImages = getQuestionImages(q);
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
          content={getQuestionMarkdown(q)}
          images={questionImages}
          questionType={q.type}
          options={q.options}
          siblingContent={[q.answer, q.analysis]}
        />
      </div>

      {subQuestions.length > 0 ? (
        <div className="space-y-3 rounded-md border border-primary/15 bg-primary/5 p-3">
          {subQuestions.map((sub: any, subIndex: number) => {
            const subImages = mergeImages(questionImages, getQuestionImages(sub));
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
                    content={getQuestionMarkdown(sub)}
                    images={subImages}
                    questionType={sub.type || q.type}
                    options={sub.options}
                    siblingContent={[sub.answer, sub.analysis]}
                  />
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
