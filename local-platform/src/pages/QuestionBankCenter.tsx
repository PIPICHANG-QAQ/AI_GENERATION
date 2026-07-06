import React, { useState } from "react";
import { Link } from "wouter";
import { Layout } from "@/components/layout/Layout";
import { Button } from "@/components/ui/button";
import { Database, Plus } from "lucide-react";
import { QuestionList } from "@/components/question-bank/QuestionList";

export default function QuestionBankCenter() {
  const [search, setSearch] = useState("");

  return (
    <Layout>
      <div className="px-6 pt-6 shrink-0 z-10 relative">
        <div className="max-w-6xl mx-auto bg-card border border-border/60 rounded-2xl elevation-1 px-6 py-5 flex items-center gap-4">
          <div className="w-12 h-12 rounded-[1.35rem] gradient-tech flex items-center justify-center text-primary-foreground shrink-0 shadow-glow-tech ring-gloss">
            <Database className="w-6 h-6" strokeWidth={1.75} />
          </div>
          <div className="min-w-0">
            <div className="text-eyebrow uppercase text-muted-foreground/70 mb-1">题目管理</div>
            <h1 className="text-2xl font-bold gradient-text tracking-tight leading-tight">题库中心</h1>
            <p className="text-sm font-light text-muted-foreground mt-1 leading-relaxed">完成校验、入库和题目增删改查。</p>
          </div>
          <Button asChild className="ml-auto shrink-0">
            <Link href="/import"><Plus className="w-4 h-4 mr-1.5" /> 新建导入</Link>
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-auto px-6 pt-4 pb-6 relative [scrollbar-gutter:stable_both-edges]">
        <QuestionList search={search} setSearch={setSearch} />
      </div>
    </Layout>
  );
}
