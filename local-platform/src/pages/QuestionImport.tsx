import { useState } from "react";
import { Database, ScanLine, ShieldCheck, UploadCloud } from "lucide-react";
import { Layout } from "@/components/layout/Layout";
import { ImportLanding } from "@/components/question-bank/ImportLanding";
import { ImportWorkbench } from "@/components/question-bank/ImportWorkbench";

const WORKFLOW_STEPS = [
  { icon: UploadCloud, label: "上传", className: "bg-primary/10 text-primary" },
  { icon: ScanLine, label: "识别", className: "bg-info/10 text-info" },
  { icon: ShieldCheck, label: "校验", className: "bg-warm/10 text-warm" },
  { icon: Database, label: "入库", className: "bg-success/10 text-success" },
];

function WorkflowSteps() {
  return (
    <div className="hidden lg:flex items-center gap-1 ml-auto shrink-0">
      {WORKFLOW_STEPS.map((step, index) => (
        <div key={step.label} className="flex items-center gap-1">
          <div className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-full ${step.className}`}>
            <step.icon className="w-3.5 h-3.5" />
            <span className="text-xs font-medium">{step.label}</span>
          </div>
          {index < WORKFLOW_STEPS.length - 1 && <div className="w-3 h-px bg-border" />}
        </div>
      ))}
    </div>
  );
}

export default function QuestionImport() {
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);

  return (
    <Layout>
      {!activeTaskId && (
        <div className="px-6 pt-6 shrink-0 z-10 relative">
          <div className="max-w-4xl mx-auto bg-card border border-border/60 rounded-2xl elevation-1 px-6 py-5 flex items-center gap-4">
            <div className="w-12 h-12 rounded-[1.35rem] gradient-tech flex items-center justify-center text-primary-foreground shrink-0 shadow-glow-tech ring-gloss">
              <ScanLine className="w-6 h-6" strokeWidth={1.75} />
            </div>
            <div className="min-w-0">
              <div className="text-eyebrow uppercase text-muted-foreground/70 mb-1">OCR 工作台</div>
              <h1 className="text-2xl font-bold gradient-text tracking-tight leading-tight">题目导入</h1>
              <p className="text-sm font-light text-muted-foreground mt-1 leading-relaxed">
                通过 OCR 工作台导入、识别并校验题目，确认后入库。
              </p>
            </div>
            <WorkflowSteps />
          </div>
        </div>
      )}

      <div className="flex-1 overflow-auto px-6 pt-4 pb-6 relative [scrollbar-gutter:stable_both-edges]">
        {activeTaskId ? (
          <ImportWorkbench taskId={activeTaskId} onBack={() => setActiveTaskId(null)} />
        ) : (
          <ImportLanding onOpenTask={setActiveTaskId} />
        )}
      </div>
    </Layout>
  );
}
