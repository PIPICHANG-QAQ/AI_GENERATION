import { describe, expect, it } from "vitest";

import {
  afterLocalStandardization,
  nextStandardizationStageAfterResult,
  shouldForceAi,
} from "./interactive-standardization";

describe("interactive standardization stage", () => {
  it("forces AI only when the current markdown matches the applied local result", () => {
    const stage = afterLocalStandardization("题干\n\\begin{tasks}(2)\n\\task A\n\\task B\n\\end{tasks}");

    expect(shouldForceAi(stage, "题干\n\\begin{tasks}(2)\n\\task A\n\\task B\n\\end{tasks}")).toBe(true);
  });

  it("does not force AI after manual markdown edits", () => {
    const stage = afterLocalStandardization("题干\n\\task A");

    expect(shouldForceAi(stage, "题干\n\\task A\n人工补充")).toBe(false);
  });

  it("marks local no-candidate results so the next click forces AI", () => {
    const stage = nextStandardizationStageAfterResult({
      forceAi: false,
      markdown: "原稿",
      payload: { markdown: "原稿", executionPath: "local", standardizer: { source: "rules" } },
    });

    expect(shouldForceAi(stage, "原稿")).toBe(true);
  });

  it("marks blocked local candidates against the requested markdown", () => {
    const stage = nextStandardizationStageAfterResult({
      forceAi: false,
      markdown: "原稿",
      payload: {
        markdown: "本地候选",
        executionPath: "local",
        standardizer: { applyBlocked: true },
      },
    });

    expect(shouldForceAi(stage, "原稿")).toBe(true);
    expect(shouldForceAi(stage, "本地候选")).toBe(false);
  });

  it("keeps forcing after a forced AI failure and clears after forced success", () => {
    const failed = nextStandardizationStageAfterResult({
      forceAi: true,
      markdown: "原稿",
      payload: { markdown: "原稿", standardizer: { forceAiFailed: true } },
    });
    const succeeded = nextStandardizationStageAfterResult({
      forceAi: true,
      markdown: "原稿",
      payload: { markdown: "AI 候选", executionPath: "force-ai", standardizer: { source: "ai" } },
    });

    expect(shouldForceAi(failed, "原稿")).toBe(true);
    expect(succeeded).toBeNull();
  });
});
