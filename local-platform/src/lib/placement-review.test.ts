import { describe, expect, it } from "vitest";

import { canonicalStructureReview, placementReview } from "./placement-review";

describe("placement review", () => {
  it("maps backend blocker codes to concise Chinese labels", () => {
    const result = placementReview({
      imagePlacementValidation: {
        blocking: true,
        blockingReasons: ["choice_option_sequence_incomplete", "stem_option_geometry_conflict"],
      },
    });

    expect(result.blocking).toBe(true);
    expect(result.labels).toEqual(["选择题选项序列不完整", "题干图与选项图布局冲突"]);
  });

  it("summarizes option count and image target changes", () => {
    const result = canonicalStructureReview({
      structureDiffs: [
        {
          questionId: "q-4",
          optionCountBefore: 3,
          optionCountAfter: 4,
          changed: true,
          placements: [
            {
              imageId: "images/d.png",
              oldTarget: { kind: "option", optionLabel: "C" },
              newTarget: { kind: "option", optionLabel: "D" },
              confidence: 0.97,
            },
          ],
        },
      ],
      blockingIssues: [],
    });

    expect(result.changed).toBe(true);
    expect(result.blocking).toBe(false);
    expect(result.lines).toContain("第 4 题：选项 3 → 4；images/d.png：C → D（97%）");
  });
});
