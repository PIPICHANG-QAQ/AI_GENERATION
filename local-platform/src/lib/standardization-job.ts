export type StandardizationProgress = {
  totalQuestions?: number;
  completedQuestions?: number;
  totalItems?: number;
  completedItems?: number;
  maxConcurrency?: number;
  rulesCount?: number;
  ocrFallbackCount?: number;
  cacheHitCount?: number;
  llmQuestionCount?: number;
  reviewRequiredCount?: number;
  failedCount?: number;
  currentLlmConcurrency?: number;
  maximumLlmConcurrency?: number;
};

export function formatStandardizationProgress(job: StandardizationProgress): string {
  return [
    `已完成 ${job.completedQuestions || 0}/${job.totalQuestions || 0} 道题`,
    `规则 ${job.rulesCount || 0}`,
    `OCR ${job.ocrFallbackCount || 0}`,
    `缓存 ${job.cacheHitCount || 0}`,
    `AI ${job.llmQuestionCount || 0}`,
    `待复核 ${job.reviewRequiredCount || 0}`,
    `失败 ${job.failedCount || 0}`,
    `模型并发 ${job.currentLlmConcurrency || 0}/${job.maximumLlmConcurrency || 8}`,
  ].join(" · ");
}
