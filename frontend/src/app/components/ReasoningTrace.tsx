import { useState } from "react";
import { ChevronDown, ChevronRight, Shield, Wrench, Cpu, Lock, Zap } from "lucide-react";
import { cn } from "./ui/utils";
import type { Trace, TraceStep } from "../../lib/types";

const KIND_CONFIG: Record<
  string,
  { icon: React.ElementType; label: string; colorClass: string }
> = {
  policy: { icon: Shield, label: "Policy", colorClass: "text-gate bg-gate/10 border-gate/25" },
  tool_call: { icon: Wrench, label: "Tool call", colorClass: "text-steel bg-paper border-line" },
  llm: { icon: Cpu, label: "LLM", colorClass: "text-partial bg-partial/10 border-partial/25" },
  guardrail: { icon: Lock, label: "Guardrail", colorClass: "text-cleared bg-cleared/10 border-cleared/25" },
  fallback: { icon: Zap, label: "Escalation", colorClass: "text-denied bg-denied/10 border-denied/25" },
};

function getKindConfig(kind: string) {
  return KIND_CONFIG[kind] ?? { icon: Zap, label: kind, colorClass: "text-steel bg-paper border-line" };
}

function StepDetail({ detail }: { detail: Record<string, unknown> }) {
  return (
    <div className="mt-3 rounded-md bg-board p-3 overflow-x-auto">
      <pre className="font-mono text-xs text-board-fg/80 whitespace-pre-wrap leading-relaxed">
        {JSON.stringify(detail, null, 2)}
      </pre>
    </div>
  );
}

function TraceStepRow({ step }: { step: TraceStep }) {
  const [expanded, setExpanded] = useState<boolean>(false);
  const { icon: Icon, label, colorClass } = getKindConfig(step.kind);
  const hasDetail = step.detail && Object.keys(step.detail).length > 0;

  return (
    <div className="flex gap-3">
      {/* Timeline connector */}
      <div className="flex flex-col items-center">
        <div
          className={cn("w-7 h-7 rounded-full border flex items-center justify-center shrink-0", colorClass)}
          aria-hidden="true"
        >
          <Icon size={13} />
        </div>
        <div className="w-px flex-1 bg-line mt-1" aria-hidden="true" />
      </div>

      {/* Step content */}
      <div className="pb-4 flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2 pt-0.5">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={cn("eyebrow px-1.5 py-0.5 rounded border", colorClass)}>{label}</span>
            <span className="text-sm text-ink/80">{step.summary}</span>
          </div>
          {hasDetail && (
            <button
              type="button"
              onClick={() => setExpanded((v: boolean) => !v)}
              className="flex items-center gap-1 text-xs text-steel hover:text-ink shrink-0 transition-colors"
              aria-expanded={expanded}
              aria-label={expanded ? "Collapse details" : "Expand details"}
            >
              {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
              {expanded ? "Hide" : "Details"}
            </button>
          )}
        </div>

        {expanded && step.detail && <StepDetail detail={step.detail} />}
      </div>
    </div>
  );
}

interface ReasoningTraceProps {
  trace: Trace;
}

export function ReasoningTrace({ trace }: ReasoningTraceProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="bg-white rounded-xl border border-line shadow-sm overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v: boolean) => !v)}
        className="w-full flex items-center justify-between px-5 py-4 hover:bg-paper transition-colors"
        aria-expanded={open}
      >
        <div className="flex items-center gap-2">
          <Cpu size={15} className="text-amber" aria-hidden="true" />
          <span className="font-display text-ink" style={{ fontWeight: 600 }}>Reasoning trace</span>
          <span className="eyebrow text-steel">
            · {trace.steps.length} step{trace.steps.length !== 1 ? "s" : ""} · {trace.mode}
          </span>
        </div>
        {open ? (
          <ChevronDown size={16} className="text-steel" />
        ) : (
          <ChevronRight size={16} className="text-steel" />
        )}
      </button>

      {open && (
        <div className="px-5 pt-2 pb-5 border-t border-line">
          <div className="mt-3 space-y-0">
            {trace.steps.map((step, i) => (
              <TraceStepRow key={i} step={step} />
            ))}
            {/* Terminal dot */}
            <div className="flex gap-3">
              <div className="flex flex-col items-center">
                <div className="w-2.5 h-2.5 rounded-full bg-amber ml-2" aria-hidden="true" />
              </div>
              <span className="eyebrow text-steel pb-1 pt-0.5">End of trace</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
