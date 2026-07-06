import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Command, CommandGroup, CommandItem, CommandList } from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import { useToast } from "@/hooks/use-toast";
import { Check, ChevronsUpDown, Plus, Search, X } from "lucide-react";

export function KnowledgePointSelect({
  value,
  onChange,
}: {
  value: string[];
  onChange: (ids: string[]) => void;
}) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const { data } = useQuery({
    queryKey: ["knowledgePoints"],
    queryFn: api.getKnowledgePoints,
  });
  const points: any[] = data?.items || [];

  const ids = value.map(String);
  const selectedSet = new Set(ids);
  const selectedPoints = points.filter((p) => selectedSet.has(String(p.id)));

  const q = query.trim().toLowerCase();
  const filtered = q
    ? points.filter((p) =>
        [p.name, p.subject, p.grade]
          .filter(Boolean)
          .some((v: string) => String(v).toLowerCase().includes(q))
      )
    : points;
  const exactExists = points.some((p) => String(p.name).trim().toLowerCase() === q);
  const showCreate = q.length > 0 && !exactExists;

  const createMutation = useMutation({
    mutationFn: api.createKnowledgePoint,
    onSuccess: (point: any) => {
      toast({ title: "知识点已创建", description: point.name });
      queryClient.setQueryData(["knowledgePoints"], (old: any) => {
        const items = old?.items || [];
        if (items.some((p: any) => String(p.id) === String(point.id))) return old;
        return { ...(old || {}), items: [...items, point] };
      });
      queryClient.invalidateQueries({ queryKey: ["knowledgePoints"] });
      onChange([...ids, String(point.id)]);
      setQuery("");
    },
    onError: (err: Error) => toast({ title: "创建失败", description: err.message, variant: "destructive" }),
  });

  const toggle = (id: string) => {
    const sid = String(id);
    onChange(selectedSet.has(sid) ? ids.filter((v) => v !== sid) : [...ids, sid]);
  };

  const remove = (id: string) => onChange(ids.filter((v) => v !== String(id)));

  const handleCreate = () => {
    const name = query.trim();
    if (!name || createMutation.isPending) return;
    createMutation.mutate({ name });
  };

  return (
    <div className="space-y-2">
      {selectedPoints.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {selectedPoints.map((p) => (
            <Badge key={p.id} variant="secondary" className="gap-1 pr-1 font-normal">
              {p.name}
              <button
                type="button"
                onClick={() => remove(p.id)}
                className="rounded-sm hover:bg-muted-foreground/20 transition-colors"
                aria-label={`移除 ${p.name}`}
              >
                <X className="w-3 h-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}

      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            role="combobox"
            aria-expanded={open}
            className="w-full justify-between font-normal"
          >
            <span className={selectedPoints.length > 0 ? "" : "text-muted-foreground"}>
              {selectedPoints.length > 0 ? `已选 ${selectedPoints.length} 个知识点` : "选择或搜索知识点"}
            </span>
            <ChevronsUpDown className="w-4 h-4 opacity-50 shrink-0" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0" align="start">
          <Command shouldFilter={false}>
            <div className="p-2">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  placeholder="搜索知识点..."
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  className="pl-9 bg-card w-full"
                />
              </div>
            </div>
            <CommandList>
              <CommandGroup>
                {filtered.map((p) => {
                  const checked = selectedSet.has(String(p.id));
                  return (
                    <CommandItem key={p.id} value={String(p.id)} onSelect={() => toggle(p.id)} className="gap-2">
                      <Check className={`w-4 h-4 shrink-0 ${checked ? "opacity-100" : "opacity-0"}`} />
                      <span className="flex-1 truncate">{p.name}</span>
                      {(p.subject || p.grade) && (
                        <span className="text-xs text-muted-foreground shrink-0">
                          {[p.subject, p.grade].filter(Boolean).join(" · ")}
                        </span>
                      )}
                    </CommandItem>
                  );
                })}
              </CommandGroup>
              {showCreate && (
                <CommandGroup>
                  <CommandItem
                    value={`__create__${query}`}
                    onSelect={handleCreate}
                    disabled={createMutation.isPending}
                    className="gap-2 text-primary"
                  >
                    <Plus className="w-4 h-4 shrink-0" />
                    <span className="truncate">新建知识点 “{query.trim()}”</span>
                  </CommandItem>
                </CommandGroup>
              )}
              {filtered.length === 0 && !showCreate && (
                <div className="py-6 text-center text-sm text-muted-foreground">
                  {q ? "没有匹配的知识点" : "暂无知识点"}
                </div>
              )}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
}
