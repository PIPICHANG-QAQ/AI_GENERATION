import { describe, expect, it } from "vitest";

import {
  ensureImagePlacements,
  ensureQuestionImageLabels,
  getQuestionMarkdown,
  getQuestionMarkdownParts,
  imagePlacementIssues,
  moveQuestionImageReference,
  splitChoiceOptionsFromMarkdown,
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

  it("can strip text-only tasks while preferring structured image options", () => {
    const result = getQuestionMarkdownParts(
      "题干\n\\begin{tasks}(2)\n\\task 甲\n\\task 乙\n\\end{tasks}",
      "choice",
      [
        { label: "A", contentMarkdown: "![](图1) 甲" },
        { label: "B", contentMarkdown: "![](图2) 乙" },
      ],
      [{ imageId: "a", label: "图1" }, { imageId: "b", label: "图2" }],
      true,
    );

    expect(result.stemMarkdown).toBe("题干");
    expect(result.options.map((option) => option.content)).toEqual(["![](图1) 甲", "![](图2) 乙"]);
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

  it("serializes trusted choice placements as one atomic task per option", () => {
    const images = [
      { imageId: "images/a.png", path: "images/a.png", label: "图1" },
      { imageId: "images/b.png", path: "images/b.png", label: "图2" },
      { imageId: "images/c.png", path: "images/c.png", label: "图3" },
      { imageId: "images/d.png", path: "images/d.png", label: "图4" },
    ];
    const imagePlacements = "ABCD".split("").map((label, index) => ({
      imageId: `images/${label.toLowerCase()}.png`,
      target: { kind: "option", optionLabel: label },
      order: index,
      reviewStatus: "auto",
      inference: { confidence: 0.98 },
    }));

    const result = getQuestionMarkdown({
      type: "choice",
      manualMarkdown: "（2分）如图所示，属于省力杠杆的是（ ）",
      images,
      imagePlacements,
      options: [
        { label: "A", content: "![](图1)\n\n食品夹" },
        { label: "B", content: "![](图2)  \n船桨\n\n![](图3)" },
        { label: "C", content: "修枝剪刀\n\n![](图4)" },
        { label: "D", content: "托盘天平" },
      ],
    });

    expect(result).toBe([
      "（2分）如图所示，属于省力杠杆的是（ ）",
      "",
      "\\begin{tasks}(4)",
      "\\task ![](图1) 食品夹",
      "\\task ![](图2) 船桨",
      "\\task ![](图3) 修枝剪刀",
      "\\task ![](图4) 托盘天平",
      "\\end{tasks}",
    ].join("\n"));
  });

  it("rebuilds an existing malformed tasks block from trusted structured options", () => {
    const images = [
      { imageId: "images/a.png", label: "图1" },
      { imageId: "images/b.png", label: "图2" },
    ];
    const result = getQuestionMarkdown({
      type: "choice",
      manualMarkdown: [
        "题干",
        "",
        "\\begin{tasks}(2)",
        "\\task ![](图1)",
        "甲",
        "\\task 乙",
        "![](图2)",
        "\\end{tasks}",
      ].join("\n"),
      images,
      imagePlacements: [
        {
          imageId: "images/a.png",
          target: { kind: "option", optionLabel: "A" },
          order: 0,
          reviewStatus: "auto",
          inference: { confidence: 0.99 },
        },
        {
          imageId: "images/b.png",
          target: { kind: "option", optionLabel: "B" },
          order: 1,
          reviewStatus: "auto",
          inference: { confidence: 0.99 },
        },
      ],
      options: [
        { label: "A", content: "![](图1) 甲" },
        { label: "B", content: "乙 ![](图2)" },
      ],
    });

    expect(result).toBe([
      "题干",
      "",
      "\\begin{tasks}(2)",
      "\\task ![](图1) 甲",
      "\\task ![](图2) 乙",
      "\\end{tasks}",
    ].join("\n"));
  });

  it("preserves manually edited task text while reconciling trusted images", () => {
    const result = getQuestionMarkdown({
      type: "choice",
      manualMarkdown: [
        "题干",
        "",
        "\\begin{tasks}(2)",
        "\\task ![](图1) 人工甲",
        "\\task ![](图2) 人工乙",
        "\\end{tasks}",
      ].join("\n"),
      images: [
        { imageId: "images/a.png", label: "图1" },
        { imageId: "images/b.png", label: "图2" },
      ],
      imagePlacements: [
        { imageId: "images/a.png", target: { kind: "option", optionLabel: "A" }, reviewStatus: "auto", inference: { confidence: 0.99 } },
        { imageId: "images/b.png", target: { kind: "option", optionLabel: "B" }, reviewStatus: "auto", inference: { confidence: 0.99 } },
      ],
      options: [
        { label: "A", content: "![](图1) 自动甲" },
        { label: "B", content: "![](图2) 自动乙" },
      ],
    });

    expect(result).toContain("\\task ![](图1) 人工甲");
    expect(result).toContain("\\task ![](图2) 人工乙");
    expect(result).not.toContain("自动甲");
  });

  it("preserves an image when a trusted placement points to a missing option", () => {
    const result = getQuestionMarkdown({
      type: "choice",
      manualMarkdown: "题干",
      images: [{ imageId: "images/a.png", label: "图1" }],
      imagePlacements: [
        { imageId: "images/a.png", target: { kind: "option", optionLabel: "D" }, reviewStatus: "auto", inference: { confidence: 0.99 } },
      ],
      options: [
        { label: "A", content: "甲" },
        { label: "B", content: "乙" },
        { label: "C", content: "![](图1) 丙" },
      ],
    });

    expect(result).toContain("\\task ![](图1) 丙");
  });

  it("preserves one image reference when trusted placements have duplicate owners", () => {
    const result = getQuestionMarkdown({
      type: "choice",
      manualMarkdown: "题干",
      images: [{ imageId: "images/a.png", label: "图1" }],
      imagePlacements: [
        { imageId: "images/a.png", target: { kind: "option", optionLabel: "A" }, reviewStatus: "auto", inference: { confidence: 0.99 } },
        { imageId: "images/a.png", target: { kind: "option", optionLabel: "B" }, reviewStatus: "auto", inference: { confidence: 0.99 } },
      ],
      options: [
        { label: "A", content: "甲" },
        { label: "B", content: "乙" },
        { label: "C", content: "![](图1) 丙" },
      ],
    });

    expect(result.match(/!\[\]\(图1\)/g)).toHaveLength(1);
    expect(result).toContain("\\task ![](图1) 丙");
  });
});

describe("choice task recovery", () => {
  function taskOptions(markdown: string) {
    return splitChoiceOptionsFromMarkdown(markdown, "choice").options.map(({ label, content }) => ({ label, content }));
  }

  it("compacts labels for an incomplete tasks sequence after filtering empty tasks", () => {
    const markdown = String.raw`题干
\task 甲
\task
\task 丙`;

    expect(splitChoiceOptionsFromMarkdown(markdown, "choice").stemMarkdown).toBe("题干");
    expect(taskOptions(markdown)).toEqual([
      { label: "A", content: "甲" },
      { label: "B", content: "丙" },
    ]);
  });

  it("recovers the screenshot-shaped C/D chain after B", () => {
    const markdown = String.raw`题干
\begin{tasks}(2)
\task A项
\task B项 C $3$ D．$4$
\end{tasks}`;

    expect(splitChoiceOptionsFromMarkdown(markdown, "choice").stemMarkdown).toBe("题干");
    expect(taskOptions(markdown)).toEqual([
      { label: "A", content: "A项" },
      { label: "B", content: "B项" },
      { label: "C", content: "$3$" },
      { label: "D", content: "$4$" },
    ]);
  });

  it("preserves leading marker-like text in recovered task parts", () => {
    const markdown = String.raw`\begin{tasks}(2)
\task A项
\task B项 C. -保留 D. +保留
\end{tasks}`;

    expect(taskOptions(markdown)).toEqual([
      { label: "A", content: "A项" },
      { label: "B", content: "B项" },
      { label: "C", content: "-保留" },
      { label: "D", content: "+保留" },
    ]);
  });

  it("recovers a glued chain before a later original task", () => {
    const markdown = String.raw`题干
\begin{tasks}(2)
\task A项
\task B项 C $3$ D．$4$
\task E项
\end{tasks}`;

    expect(taskOptions(markdown)).toEqual([
      { label: "A", content: "A项" },
      { label: "B", content: "B项" },
      { label: "C", content: "$3$" },
      { label: "D", content: "$4$" },
      { label: "E", content: "E项" },
    ]);
  });

  it.each([
    ["inline dollar", String.raw`$ C. x D. y $`],
    ["display dollar", String.raw`$$ C. x D. y $$`],
    ["inline parentheses", String.raw`\( C. x D. y \)`],
    ["display brackets", String.raw`\[ C. x D. y \]`],
  ])("does not recover labels inside %s math", (_name, formula) => {
    const markdown = [String.raw`\begin{tasks}(2)`, String.raw`\task A项`, String.raw`\task ${formula}`, String.raw`\end{tasks}`].join("\n");

    expect(taskOptions(markdown)).toEqual([
      { label: "A", content: "A项" },
      { label: "B", content: formula },
    ]);
  });

  it.each([
    ["math variable", String.raw`B项 $C$ $5.5$ D．$6.5$`],
    ["point name", String.raw`B项 C $5.5$ 点 D．$6.5$`],
    ["nonconsecutive labels", String.raw`B项 C $5.5$ E．$6.5$`],
    ["single label", String.raw`B项 C. 文字`],
  ])("does not recover ambiguous %s chains", (_name, content) => {
    const markdown = [String.raw`\begin{tasks}(2)`, String.raw`\task A项`, String.raw`\task ${content}`, String.raw`\end{tasks}`].join("\n");

    expect(taskOptions(markdown)).toEqual([
      { label: "A", content: "A项" },
      { label: "B", content },
    ]);
  });

  it.each([
    ["inline dollar", "B项 $5 C. x D. y"],
    ["display dollar", "B项 $$5 C. x D. y"],
    ["inline parentheses", String.raw`B项 \(5 C. x D. y`],
    ["display brackets", String.raw`B项 \[5 C. x D. y`],
  ])("does not recover a block with an unclosed %s delimiter", (_name, content) => {
    const markdown = [String.raw`\begin{tasks}(2)`, String.raw`\task A项`, String.raw`\task ${content}`, String.raw`\end{tasks}`].join("\n");

    expect(taskOptions(markdown)).toEqual([
      { label: "A", content: "A项" },
      { label: "B", content },
    ]);
  });

  it("does not recover a complete block containing an empty task", () => {
    const markdown = String.raw`\begin{tasks}(2)
\task A项
\task
\task 前缀 D $4$ E．$5$
\end{tasks}`;

    expect(taskOptions(markdown)).toEqual([
      { label: "A", content: "A项" },
      { label: "B", content: "前缀 D $4$ E．$5$" },
    ]);
  });

  it("recovers an external text chain after a formula decoy", () => {
    const markdown = String.raw`\begin{tasks}(2)
\task A项
\task B项 \[ C. x=1 \] C. 外部文本 D．另一文本
\end{tasks}`;

    expect(taskOptions(markdown)).toEqual([
      { label: "A", content: "A项" },
      { label: "B", content: String.raw`B项 \[ C. x=1 \]` },
      { label: "C", content: "外部文本" },
      { label: "D", content: "另一文本" },
    ]);
  });

  it("recovers a bare label only when it precedes a complete image", () => {
    const markdown = String.raw`\begin{tasks}(2)
\task A项
\task B项 C. 文字 D ![](images/(d).png)
\end{tasks}`;

    expect(taskOptions(markdown)).toEqual([
      { label: "A", content: "A项" },
      { label: "B", content: "B项" },
      { label: "C", content: "文字" },
      { label: "D", content: "![](images/(d).png)" },
    ]);
  });

  it.each([
    [
      "alt text",
      String.raw`B项 ![a \] C. decoy D. decoy](images/(x).png) C. real D．real`,
      String.raw`B项 ![a \] C. decoy D. decoy](images/(x).png)`,
    ],
    [
      "destination",
      String.raw`B项 ![alt](foo\) C. decoy D. decoy(thing).png) C. real D. real`,
      String.raw`B项 ![alt](foo\) C. decoy D. decoy(thing).png)`,
    ],
  ])("ignores %s label decoys inside a complete image", (_name, content, originalB) => {
    const markdown = [String.raw`\begin{tasks}(2)`, String.raw`\task A项`, String.raw`\task ${content}`, String.raw`\end{tasks}`].join("\n");

    expect(taskOptions(markdown)).toEqual([
      { label: "A", content: "A项" },
      { label: "B", content: originalB },
      { label: "C", content: "real" },
      { label: "D", content: "real" },
    ]);
  });

  it("uses backslash parity when recognizing math delimiters", () => {
    const evenBackslashes = String.raw`B项 \\$5 C. x D. y\\$`;
    const oddBackslashes = String.raw`B项 \$5 C. x D. y\$`;
    const evenMarkdown = [String.raw`\begin{tasks}(2)`, String.raw`\task A项`, String.raw`\task ${evenBackslashes}`, String.raw`\end{tasks}`].join("\n");
    const oddMarkdown = [String.raw`\begin{tasks}(2)`, String.raw`\task A项`, String.raw`\task ${oddBackslashes}`, String.raw`\end{tasks}`].join("\n");

    expect(taskOptions(evenMarkdown)).toEqual([
      { label: "A", content: "A项" },
      { label: "B", content: evenBackslashes },
    ]);
    expect(taskOptions(oddMarkdown)).toEqual([
      { label: "A", content: "A项" },
      { label: "B", content: String.raw`B项 \$5` },
      { label: "C", content: "x" },
      { label: "D", content: String.raw`y\$` },
    ]);
  });
});
