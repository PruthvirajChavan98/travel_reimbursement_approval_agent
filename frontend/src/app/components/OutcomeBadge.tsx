import { CheckCircle2, AlertTriangle, XCircle, Clock } from "lucide-react";
import { cn } from "./ui/utils";
import type { Outcome } from "../../lib/types";

interface OutcomeBadgeProps {
  outcome: Outcome;
  size?: "sm" | "md" | "lg";
  /** "light" = on paper/ticket (default); "dark" = on the departures board. */
  tone?: "light" | "dark";
  className?: string;
}

// Each outcome carries a flight-status codename (the visible verdict) plus the full
// label (kept for screen readers) and an icon. Colors come from the --td-* palette.
const CONFIG: Record<
  Outcome,
  { label: string; code: string; icon: React.ElementType; light: string; dark: string }
> = {
  APPROVE: {
    label: "Approved",
    code: "Cleared",
    icon: CheckCircle2,
    light: "bg-cleared/10 text-cleared border-cleared/25",
    dark: "bg-cleared/15 text-cleared border-cleared/40",
  },
  PARTIAL_APPROVE: {
    label: "Partial approval",
    code: "Partial",
    icon: AlertTriangle,
    light: "bg-partial/10 text-partial border-partial/25",
    dark: "bg-amber/15 text-amber border-amber/40",
  },
  REJECT: {
    label: "Rejected",
    code: "Denied",
    icon: XCircle,
    light: "bg-denied/10 text-denied border-denied/25",
    dark: "bg-denied/15 text-denied border-denied/40",
  },
  MANUAL_REVIEW: {
    label: "Manual review",
    code: "At gate",
    icon: Clock,
    light: "bg-gate/10 text-gate border-gate/25",
    dark: "bg-gate/20 text-gate border-gate/45",
  },
};

export function OutcomeBadge({ outcome, size = "md", tone = "light", className }: OutcomeBadgeProps) {
  const { label, code, icon: Icon, light, dark } = CONFIG[outcome];

  const sizeClasses = {
    sm: "text-[0.6875rem] px-2 py-0.5 gap-1",
    md: "text-xs px-2.5 py-1 gap-1.5",
    lg: "text-sm px-3 py-1.5 gap-1.5",
  }[size];

  const iconSize = { sm: 12, md: 13, lg: 15 }[size];

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border font-mono font-medium uppercase tracking-wider whitespace-nowrap",
        tone === "dark" ? dark : light,
        sizeClasses,
        className
      )}
      aria-label={`Outcome: ${label}`}
      title={label}
    >
      <Icon size={iconSize} aria-hidden="true" />
      {code}
    </span>
  );
}

export function outcomeConfig(outcome: Outcome) {
  return CONFIG[outcome];
}
