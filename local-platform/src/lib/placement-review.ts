const REASON_LABELS: Record<string, string> = {
  choice_option_sequence_incomplete: "选择题选项序列不完整",
  embedded_option_label_candidate: "存在粘连的选项标签候选",
  image_before_first_option: "图片位于首个选项标签之前",
  option_image_one_to_one_violation: "选项题图不是一对一归属",
  stem_option_geometry_conflict: "题干图与选项图布局冲突",
  missing_image_geometry: "题图缺少页码或坐标证据",
  image_asset_conservation_failed: "题图资源与归属记录不一致",
  manual_placement_conflict: "自动归属与人工确认结果冲突",
  layout_assignment_ambiguous: "二维归属存在多个接近候选",
};

export function placementReview(question: any): { blocking: boolean; reasons: string[]; labels: string[] } {
  const validation = question?.imagePlacementValidation || {};
  const reasons = Array.isArray(validation.blockingReasons)
    ? validation.blockingReasons.map(String).filter(Boolean)
    : [];
  return {
    blocking: Boolean(validation.blocking || reasons.length > 0),
    reasons,
    labels: reasons.map((reason: string) => REASON_LABELS[reason] || reason),
  };
}

export function canonicalStructureReview(preview: any): {
  changed: boolean;
  blocking: boolean;
  reviewRequired: boolean;
  lines: string[];
} {
  const diffs = Array.isArray(preview?.structureDiffs)
    ? preview.structureDiffs.filter((item: any) => item?.changed)
    : [];
  const blockingIssues = Array.isArray(preview?.blockingIssues) ? preview.blockingIssues : [];
  const applyBlockingIssues = Array.isArray(preview?.applyBlockingIssues)
    ? preview.applyBlockingIssues
    : blockingIssues;
  return {
    changed: diffs.length > 0,
    blocking: applyBlockingIssues.length > 0,
    reviewRequired: blockingIssues.length > 0,
    lines: diffs.map((diff: any) => formatStructureDiff(diff)),
  };
}

function formatStructureDiff(diff: any) {
  const questionNumber = diff?.number || trailingNumber(diff?.questionId) || "?";
  const parts: string[] = [];
  const before = Number(diff?.optionCountBefore || 0);
  const after = Number(diff?.optionCountAfter || 0);
  if (before !== after) parts.push(`选项 ${before} → ${after}`);
  for (const placement of Array.isArray(diff?.placements) ? diff.placements : []) {
    if (targetLabel(placement?.oldTarget) === targetLabel(placement?.newTarget)) continue;
    const confidence = Math.round(Number(placement?.confidence || 0) * 100);
    parts.push(
      `${placement?.imageId || "题图"}：${targetLabel(placement?.oldTarget)} → ${targetLabel(placement?.newTarget)}（${confidence}%）`,
    );
  }
  return `第 ${questionNumber} 题：${parts.join("；") || "结构校验状态变化"}`;
}

function targetLabel(target: any) {
  if (target?.kind === "option") return String(target?.optionLabel || "选项");
  if (target?.kind === "stem") return "题干";
  if (target?.kind === "subquestion") return "小问";
  return "未归属";
}

function trailingNumber(value: unknown) {
  const match = String(value || "").match(/(\d+)$/);
  return match?.[1] || "";
}
