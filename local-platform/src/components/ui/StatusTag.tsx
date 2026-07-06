import React from "react";

const NEUTRAL = "bg-muted text-muted-foreground";
const SUCCESS = "bg-success/15 text-success";
const INFO = "bg-info/15 text-info";
const WARM = "bg-warm/15 text-warm";
const DANGER = "bg-destructive/15 text-destructive";
const BRAND = "bg-accent text-accent-foreground";

export function StatusTag({ status, type }: { status: string, type: "task" | "question" | "qtype" | "difficulty" }) {
  let label = status;
  let color = NEUTRAL;

  if (type === "task") {
    const map: Record<string, { l: string, c: string }> = {
      "处理中": { l: "处理中", c: INFO },
      "待校验": { l: "待校验", c: WARM },
      "部分完成": { l: "部分完成", c: INFO },
      "已完成": { l: "已完成", c: SUCCESS },
    };
    if (map[status]) { label = map[status].l; color = map[status].c; }
  } else if (type === "question") {
    const map: Record<string, { l: string, c: string }> = {
      "待校验": { l: "待校验", c: WARM },
      "已校验": { l: "已校验", c: INFO },
      "已入库": { l: "已入库", c: SUCCESS },
    };
    if (map[status]) { label = map[status].l; color = map[status].c; }
  } else if (type === "qtype") {
    const map: Record<string, string> = {
      "choice": "选择题",
      "fill_blank": "填空题",
      "solution": "解答题",
      "unknown": "未知",
    };
    label = map[status] || status;
    color = BRAND;
  } else if (type === "difficulty") {
    const map: Record<string, { l: string, c: string }> = {
      "easy": { l: "简单", c: SUCCESS },
      "medium": { l: "中等", c: WARM },
      "hard": { l: "困难", c: DANGER },
    };
    if (map[status]) { label = map[status].l; color = map[status].c; }
  }

  return <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${color}`}>{label}</span>;
}
