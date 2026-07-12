import { expect, it } from "vitest";
import { formatStandardizationProgress } from "./standardization-job";

it("formats durable question and content-item progress", () => {
  expect(formatStandardizationProgress({
    completedQuestions: 12,
    totalQuestions: 36,
    completedItems: 38,
    totalItems: 95,
    maxConcurrency: 2,
  })).toBe("已完成 12/36 道题 · 38/95 个内容项 · 并发 2");
});
