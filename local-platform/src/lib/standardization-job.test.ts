import { expect, it } from "vitest";
import { formatStandardizationProgress } from "./standardization-job";

it("formats canonical-question progress and execution paths", () => {
  expect(formatStandardizationProgress({
    completedQuestions: 38,
    totalQuestions: 51,
    rulesCount: 12,
    ocrFallbackCount: 3,
    cacheHitCount: 8,
    llmQuestionCount: 15,
    reviewRequiredCount: 2,
    failedCount: 0,
    currentLlmConcurrency: 5,
    maximumLlmConcurrency: 8,
  })).toBe("已完成 38/51 道题 · 规则 12 · OCR 3 · 缓存 8 · AI 15 · 待复核 2 · 失败 0 · 模型并发 5/8");
});
