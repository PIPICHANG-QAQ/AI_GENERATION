import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Search, Filter, X } from "lucide-react";

export type Filters = {
  type: string;
  difficulty: string;
  subject: string;
  grade: string;
  region: string;
  year: string;
  knowledgePointId: string;
};

export const emptyFilters: Filters = {
  type: "", difficulty: "", subject: "", grade: "", region: "", year: "", knowledgePointId: ""
};

export const hasActiveFilters = (filters: Filters) => Object.values(filters).some(Boolean);

const TYPE_LABELS: Record<string, string> = {
  choice: "选择题", fill_blank: "填空题", solution: "解答题", unknown: "未知"
};
const DIFF_LABELS: Record<string, string> = { easy: "简单", medium: "中等", hard: "困难" };

export function QuestionFilters({
  search,
  setSearch,
  filters,
  setFilters,
  actions,
}: {
  search: string;
  setSearch: (v: string) => void;
  filters: Filters;
  setFilters: (f: Filters) => void;
  actions?: React.ReactNode;
}) {
  const [showFilters, setShowFilters] = useState(false);

  const { data: kpData } = useQuery({
    queryKey: ["knowledgePoints"],
    queryFn: api.getKnowledgePoints
  });
  const knowledgePoints: any[] = kpData?.items || [];
  const kpName = (id: string) => knowledgePoints.find((p) => String(p.id) === String(id))?.name || id;

  const setFilter = (key: keyof Filters, value: string) => setFilters({ ...filters, [key]: value });
  const clearFilter = (key: keyof Filters) => setFilters({ ...filters, [key]: "" });

  const activeChips = (Object.keys(filters) as (keyof Filters)[])
    .filter((k) => filters[k])
    .map((k) => {
      const labels: Record<keyof Filters, string> = {
        type: "题型", difficulty: "难度", subject: "学科", grade: "年级",
        region: "地区", year: "年份", knowledgePointId: "知识点"
      };
      let value = filters[k];
      if (k === "type") value = TYPE_LABELS[value] || value;
      if (k === "difficulty") value = DIFF_LABELS[value] || value;
      if (k === "knowledgePointId") value = kpName(value);
      return { key: k, label: labels[k], value };
    });

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            placeholder="搜索题干、答案、解析、知识点"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 bg-card w-full"
          />
        </div>
        <Button variant={showFilters ? "default" : "outline"} className="gap-2" onClick={() => setShowFilters((s) => !s)}>
          <Filter className="w-4 h-4" /> 筛选{activeChips.length > 0 ? ` (${activeChips.length})` : ""}
        </Button>
        {actions && <div className="flex-1" />}
        {actions}
      </div>

      {showFilters && (
        <div className="bg-card p-4 rounded-lg border border-border elevation-1 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">题型</Label>
            <select value={filters.type} onChange={e => setFilter("type", e.target.value)} className="w-full h-9 rounded-md border border-input bg-transparent px-3 text-sm">
              <option value="">不限</option>
              <option value="choice">选择题</option>
              <option value="fill_blank">填空题</option>
              <option value="solution">解答题</option>
              <option value="unknown">未知</option>
            </select>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">难度</Label>
            <select value={filters.difficulty} onChange={e => setFilter("difficulty", e.target.value)} className="w-full h-9 rounded-md border border-input bg-transparent px-3 text-sm">
              <option value="">不限</option>
              <option value="easy">简单</option>
              <option value="medium">中等</option>
              <option value="hard">困难</option>
            </select>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">知识点</Label>
            <select value={filters.knowledgePointId} onChange={e => setFilter("knowledgePointId", e.target.value)} className="w-full h-9 rounded-md border border-input bg-transparent px-3 text-sm">
              <option value="">不限</option>
              {knowledgePoints.map((p) => <option key={p.id} value={String(p.id)}>{p.name}</option>)}
            </select>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">学科</Label>
            <Input value={filters.subject} onChange={e => setFilter("subject", e.target.value)} placeholder="例如：数学" className="h-9" />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">年级</Label>
            <Input value={filters.grade} onChange={e => setFilter("grade", e.target.value)} placeholder="例如：高一" className="h-9" />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">地区</Label>
            <Input value={filters.region} onChange={e => setFilter("region", e.target.value)} placeholder="例如：北京" className="h-9" />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">年份</Label>
            <Input value={filters.year} onChange={e => setFilter("year", e.target.value)} placeholder="例如：2026" className="h-9" />
          </div>
          <div className="flex items-end">
            <Button variant="outline" size="sm" className="h-9" onClick={() => setFilters(emptyFilters)} disabled={!hasActiveFilters(filters)}>
              清空筛选
            </Button>
          </div>
        </div>
      )}

      {activeChips.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {activeChips.map((chip) => (
            <span key={chip.key} className="inline-flex items-center gap-1 text-xs bg-primary/10 text-primary px-2 py-1 rounded-md border border-primary/20">
              {chip.label}：{chip.value}
              <button onClick={() => clearFilter(chip.key)} className="hover:text-primary/70">
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
