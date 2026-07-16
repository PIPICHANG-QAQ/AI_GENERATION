import { describe, expect, it } from "vitest";

import { standardizeCandidateFromPayload } from "./StandardizeCandidatePanel";

describe("standardizeCandidateFromPayload", () => {
  it("does not expose an applyable candidate when forced AI standardization failed", () => {
    const result = standardizeCandidateFromPayload("原始题干", {
      markdown: "本地兜底题干",
      standardizer: {
        forceAiFailed: true,
        warnings: ["AI 服务超时"],
        error: "fallback should not win",
      },
    });

    expect(result.candidate).toBeNull();
    expect(result.message).toContain("强制 AI 标准化失败");
    expect(result.message).toContain("AI 服务超时");
  });
});
