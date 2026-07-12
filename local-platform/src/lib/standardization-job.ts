export type StandardizationProgress = {
  totalQuestions?: number;
  completedQuestions?: number;
  totalItems?: number;
  completedItems?: number;
  maxConcurrency?: number;
};

export function formatStandardizationProgress(job: StandardizationProgress): string {
  return `已完成 ${job.completedQuestions || 0}/${job.totalQuestions || 0} 道题 · ${job.completedItems || 0}/${job.totalItems || 0} 个内容项 · 并发 ${job.maxConcurrency || 2}`;
}
