import React, { useState } from "react";
import { Layout } from "@/components/layout/Layout";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Checkbox } from "@/components/ui/checkbox";
import { useToast } from "@/hooks/use-toast";
import { Plus, Trash2, Edit2, FolderTree, Search, GraduationCap } from "lucide-react";

const emptyForm = { name: "", subject: "数学", grade: "高一", description: "" };

export default function KnowledgePointLibrary() {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const [editingId, setEditingId] = useState<string | null>(null);
  const [formData, setFormData] = useState(emptyForm);
  const [modalOpen, setModalOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const { data, isLoading } = useQuery({
    queryKey: ["knowledgePoints"],
    queryFn: api.getKnowledgePoints
  });

  const points: any[] = data?.items || [];

  const q = search.trim().toLowerCase();
  const filteredPoints = q
    ? points.filter((p) =>
        [p.name, p.subject, p.grade, p.description]
          .filter(Boolean)
          .some((v: string) => String(v).toLowerCase().includes(q))
      )
    : points;

  const resetForm = () => {
    setEditingId(null);
    setFormData(emptyForm);
  };

  const closeModal = () => {
    setModalOpen(false);
    resetForm();
  };

  const createMutation = useMutation({
    mutationFn: api.createKnowledgePoint,
    onSuccess: () => {
      toast({ title: "添加成功", description: "知识点已保存" });
      closeModal();
      queryClient.invalidateQueries({ queryKey: ["knowledgePoints"] });
    },
    onError: (err: Error) => toast({ title: "添加失败", description: err.message, variant: "destructive" })
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: any }) => api.updateKnowledgePoint(id, data),
    onSuccess: () => {
      toast({ title: "保存成功", description: "知识点已更新" });
      closeModal();
      queryClient.invalidateQueries({ queryKey: ["knowledgePoints"] });
    },
    onError: (err: Error) => toast({ title: "保存失败", description: err.message, variant: "destructive" })
  });

  const deleteMutation = useMutation({
    mutationFn: api.deleteKnowledgePoint,
    onSuccess: (_res, id) => {
      toast({ title: "删除成功" });
      queryClient.invalidateQueries({ queryKey: ["knowledgePoints"] });
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(id as string);
        return next;
      });
    },
    onError: (err: Error) => toast({ title: "删除失败", description: err.message, variant: "destructive" })
  });

  const batchDeleteMutation = useMutation({
    mutationFn: (ids: string[]) => api.deleteKnowledgePoints(ids),
    onSuccess: (res: any) => {
      toast({ title: `已删除 ${res?.deleted ?? 0} 个知识点` });
      queryClient.invalidateQueries({ queryKey: ["knowledgePoints"] });
      setSelectedIds(new Set());
    },
    onError: (err: Error) => toast({ title: "批量删除失败", description: err.message, variant: "destructive" })
  });

  const toggleSelect = (id: string) =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const handleBatchDelete = () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    if (window.confirm(`确认删除选中的 ${ids.length} 个知识点？此操作不可撤销。`)) {
      batchDeleteMutation.mutate(ids);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.name) {
      toast({ title: "提交失败", description: "知识点名称为必填项", variant: "destructive" });
      return;
    }
    if (editingId) {
      updateMutation.mutate({ id: editingId, data: formData });
    } else {
      createMutation.mutate(formData);
    }
  };

  const openCreate = () => {
    resetForm();
    setModalOpen(true);
  };

  const handleEdit = (kp: any) => {
    setEditingId(kp.id);
    setFormData({
      name: kp.name || "",
      subject: kp.subject || "",
      grade: kp.grade || "",
      description: kp.description || ""
    });
    setModalOpen(true);
  };

  const handleDelete = (id: string) => {
    if (window.confirm("确认删除这个知识点吗？")) {
      deleteMutation.mutate(id);
    }
  };

  const isPending = createMutation.isPending || updateMutation.isPending;

  return (
    <Layout>
      <div className="px-6 pt-6 shrink-0 z-10 relative">
        <div className="max-w-5xl mx-auto bg-card border border-border/60 rounded-2xl elevation-1 px-6 py-5 flex items-center gap-4">
          <div className="w-12 h-12 rounded-[1.35rem] gradient-tech flex items-center justify-center text-primary-foreground shrink-0 shadow-glow-tech ring-gloss">
            <GraduationCap className="w-6 h-6" strokeWidth={1.75} />
          </div>
          <div className="min-w-0">
            <div className="text-eyebrow uppercase text-muted-foreground/70 mb-1">知识点管理</div>
            <h1 className="text-2xl font-bold gradient-text tracking-tight leading-tight">知识点库</h1>
            <p className="text-sm font-light text-muted-foreground mt-1 leading-relaxed">维护题库搜索和规则组卷依赖的知识点。</p>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-auto px-6 pt-4 pb-6 [scrollbar-gutter:stable_both-edges]">
        <div className="max-w-5xl mx-auto">
          <div className="bg-card p-5 rounded-lg border border-border elevation-1 min-h-[500px]">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-5">
              <h2 className="font-semibold text-foreground flex items-center shrink-0">
                <FolderTree className="w-4 h-4 mr-2" /> 知识点列表
              </h2>
              <div className="flex items-center gap-3 sm:ml-auto">
                {selectedIds.size > 0 && (
                  <>
                    <Button
                      variant="destructive"
                      onClick={handleBatchDelete}
                      disabled={batchDeleteMutation.isPending}
                      className="shrink-0"
                    >
                      <Trash2 className="w-4 h-4 mr-1.5" /> 删除所选 ({selectedIds.size})
                    </Button>
                    <Button
                      variant="outline"
                      onClick={() => setSelectedIds(new Set())}
                      className="shrink-0"
                    >
                      全部取消
                    </Button>
                  </>
                )}
                <div className="relative flex-1 sm:flex-initial sm:w-64">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                  <Input
                    placeholder="筛选知识点名称、学科、年级"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    className="pl-9 bg-card w-full"
                  />
                </div>
                <Button onClick={openCreate} className="shrink-0">
                  <Plus className="w-4 h-4 mr-1.5" /> 新建知识点
                </Button>
              </div>
            </div>

            {isLoading ? (
              <div className="text-center py-12 text-muted-foreground">加载中...</div>
            ) : filteredPoints.length > 0 ? (
              <div className="space-y-3">
                {filteredPoints.map((kp: any) => (
                  <div key={kp.id} className="p-4 border rounded-md transition-colors group flex justify-between items-start border-border hover:border-primary/30 bg-muted/30">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 mb-1 flex-wrap">
                        <h3 className="font-medium text-foreground">{kp.name}</h3>
                        {kp.subject && <span className="text-xs px-2 py-0.5 bg-muted text-muted-foreground rounded-md border border-border">{kp.subject}</span>}
                        {kp.grade && <span className="text-xs px-2 py-0.5 bg-muted text-muted-foreground rounded-md border border-border">{kp.grade}</span>}
                      </div>
                      {kp.description && <p className="text-sm text-muted-foreground mt-1">{kp.description}</p>}
                    </div>
                    <div className={`flex items-center space-x-2 transition-opacity shrink-0 ${selectedIds.has(kp.id) ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}>
                      <Button variant="ghost" size="sm" className="h-8 w-8 p-0 text-muted-foreground hover:text-primary" onClick={() => handleEdit(kp)}>
                        <Edit2 className="w-4 h-4" />
                      </Button>
                      <Button variant="ghost" size="sm" className="h-8 w-8 p-0 text-muted-foreground hover:text-destructive" onClick={() => handleDelete(kp.id)}>
                        <Trash2 className="w-4 h-4" />
                      </Button>
                      <div className="h-8 w-8 flex items-center justify-center shrink-0">
                        <Checkbox
                          checked={selectedIds.has(kp.id)}
                          onCheckedChange={() => toggleSelect(kp.id)}
                          className="shrink-0"
                        />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-16 border-2 border-dashed border-border rounded-lg">
                <p className="text-muted-foreground">{q ? "没有符合条件的知识点" : "暂无知识点数据"}</p>
              </div>
            )}
          </div>
        </div>
      </div>

      <Dialog open={modalOpen} onOpenChange={(open) => (open ? setModalOpen(true) : closeModal())}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center">
              {editingId ? <Edit2 className="w-4 h-4 mr-2" /> : <Plus className="w-4 h-4 mr-2" />}
              {editingId ? "编辑知识点" : "新建知识点"}
            </DialogTitle>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <Label>名称 <span className="text-destructive">*</span></Label>
              <Input value={formData.name} onChange={e => setFormData({ ...formData, name: e.target.value })} placeholder="例如：二次函数" />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label>学科</Label>
                <Input value={formData.subject} onChange={e => setFormData({ ...formData, subject: e.target.value })} placeholder="数学" />
              </div>
              <div className="space-y-1.5">
                <Label>年级</Label>
                <Input value={formData.grade} onChange={e => setFormData({ ...formData, grade: e.target.value })} placeholder="高一" />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>说明</Label>
              <Textarea value={formData.description} onChange={e => setFormData({ ...formData, description: e.target.value })} placeholder="选填，知识点详细描述..." rows={3} />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button type="button" variant="outline" onClick={closeModal}>取消</Button>
              <Button type="submit" disabled={isPending}>
                {isPending ? "提交中..." : editingId ? "保存修改" : "新增知识点"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </Layout>
  );
}
