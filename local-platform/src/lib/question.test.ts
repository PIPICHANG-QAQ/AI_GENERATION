import { describe, expect, it } from "vitest";

import {
  ensureImagePlacements,
  ensureQuestionImageLabels,
  getQuestionMarkdownParts,
  imagePlacementIssues,
  moveQuestionImageReference,
  type QuestionImage,
} from "./question";

describe("question image ownership", () => {
  it("preserves labels for retained keys and does not reuse a removed label", () => {
    const previous: QuestionImage[] = [
      { imageId: "a", label: "图1" },
      { imageId: "b", label: "图2" },
    ];

    const next = ensureQuestionImageLabels([{ imageId: "b" }, { imageId: "c" }], previous);

    expect(next.map((image) => image.label)).toEqual(["图2", "图3"]);
  });

  it("does not zip unassigned images into text options by array order", () => {
    const result = getQuestionMarkdownParts(
      "如图，选择正确答案",
      "choice",
      [
        { label: "A", content: "甲" },
        { label: "B", content: "乙" },
      ],
      [{ imageId: "a" }, { imageId: "b" }],
    );

    expect(result.options.map((option) => option.content)).toEqual(["甲", "乙"]);
  });

  it("creates reviewable unassigned placements for new images", () => {
    const placements = ensureImagePlacements([{ imageId: "a" }], []);

    expect(placements[0].target.kind).toBe("unassigned");
    expect(placements[0].reviewStatus).toBe("needs_review");
    expect(imagePlacementIssues(placements)).toContain("存在 1 张未归属题图");
  });

  it("blocks verification when geometry conflicts with an explicit owner", () => {
    const placements = ensureImagePlacements([{ imageId: "a" }], []);
    placements[0] = {
      ...placements[0],
      target: { kind: "option", optionLabel: "C" },
      reviewStatus: "needs_review",
      inference: { ...placements[0].inference, confidence: 0.85, reasons: ["geometry-conflict"] },
    };

    expect(imagePlacementIssues(placements)).toContain("存在 1 张题图归属需复核");
  });

  it("moves an image token atomically from stem to the selected option", () => {
    const moved = moveQuestionImageReference(
      { imageId: "a", label: "图1" },
      { kind: "option", optionLabel: "B" },
      {
        markdown: "题干\n\n![](图1)",
        options: [{ label: "A", content: "甲" }, { label: "B", content: "乙" }],
      },
    );

    expect(moved.markdown).not.toContain("![](图1)");
    expect(moved.options[1].content).toContain("![](图1)");
  });
});
