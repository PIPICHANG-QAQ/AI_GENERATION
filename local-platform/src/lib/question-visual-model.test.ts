import { describe, expect, it } from "vitest";

import { buildQuestionVisualModel, resolveVisualImage } from "./question-visual-model";

describe("question visual model", () => {
  it("prefers structured option images over text-only tasks", () => {
    const model = buildQuestionVisualModel({
      type: "choice",
      manualMarkdown: "题干\n\\begin{tasks}(2)\n\\task 食品夹\n\\task 船桨\n\\end{tasks}",
      images: [
        { imageId: "a", label: "图1", url: "/api/a.jpg" },
        { imageId: "b", label: "图2", url: "/api/b.jpg" },
      ],
      options: [
        { label: "A", contentMarkdown: "![](图1) 食品夹" },
        { label: "B", contentMarkdown: "![](图2) 船桨" },
      ],
    });

    expect(model.options.map((option) => option.contentMarkdown)).toEqual([
      "![](图1) 食品夹",
      "![](图2) 船桨",
    ]);
    expect(model.stemMarkdown).toBe("题干");
    expect(model.issues).toEqual([]);
  });

  it("falls back to markdown tasks when structured options are absent", () => {
    const model = buildQuestionVisualModel({
      type: "choice",
      manualMarkdown: "题干\n\\begin{tasks}(2)\n\\task A1\n\\task B1\n\\end{tasks}",
    });
    expect(model.options.map((item) => item.content)).toEqual(["A1", "B1"]);
  });

  it.each(["图1", "images/a.jpg", "/api/a.jpg"])("resolves %s", (ref) => {
    expect(
      resolveVisualImage(ref, [
        { imageId: "a", label: "图1", path: "root/images/a.jpg", url: "/api/a.jpg" },
      ]),
    ).toBe("/api/a.jpg");
  });

  it("reports placement conflicts without hiding the option image", () => {
    const model = buildQuestionVisualModel({
      type: "choice",
      images: [{ imageId: "a", label: "图1", url: "/api/a.jpg" }],
      options: [{ label: "A", contentMarkdown: "![](图1) A1" }],
      imagePlacements: [{ imageId: "a", target: { kind: "option", optionLabel: "B" } }],
    });
    expect(model.options[0].contentMarkdown).toContain("![](图1)");
    expect(model.issues[0].code).toBe("placement-conflict");
  });

  it("appends confirmed stem images but leaves unassigned images for review", () => {
    const model = buildQuestionVisualModel({
      stemMarkdown: "题干",
      images: [
        { imageId: "stem-image", label: "图1", url: "/api/stem.jpg" },
        { imageId: "unknown-image", label: "图2", url: "/api/unknown.jpg" },
      ],
      imagePlacements: [
        { imageId: "stem-image", target: { kind: "stem" } },
        { imageId: "unknown-image", target: { kind: "unassigned" } },
      ],
    });

    expect(model.stemMarkdown).toContain("![](图1)");
    expect(model.stemMarkdown).not.toContain("![](图2)");
    expect(model.issues.some((issue) => issue.code === "unassigned-image")).toBe(true);
  });
});
