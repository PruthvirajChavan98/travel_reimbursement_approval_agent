import { useNavigate } from "react-router";
import { useShallow } from "zustand/react/shallow";
import { useClaimsStore, claimsListSelector } from "../../lib/store";
import { OutcomeBadge } from "./OutcomeBadge";
import { Button } from "./ui/button";
import { PlusCircle, Inbox, Trash2 } from "lucide-react";
import { cn } from "./ui/utils";
import type { ClaimRecord, Outcome } from "../../lib/types";
import { useState } from "react";

const USD = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const DATE_FMT = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });

type Filter = "all" | Outcome;

// Shared 6-column grid: CLAIM · EMPLOYEE · DESTINATION · DATE · AMOUNT · STATUS
const COLS = "sm:grid sm:grid-cols-[150px_1.1fr_1fr_84px_104px_120px] sm:items-center sm:gap-3";

function isAwaiting(record: ClaimRecord): boolean {
  return record.interrupt !== null;
}

export function ClaimsList() {
  const navigate = useNavigate();
  // useShallow: claimsListSelector returns a NEW array each call; without shallow
  // equality zustand v5 re-renders every time → infinite loop (React #185).
  const records = useClaimsStore(useShallow(claimsListSelector));
  const clearAll = useClaimsStore((s) => s.clearAll);
  const [filter, setFilter] = useState<Filter>("all");

  const filtered = records.filter((r) => {
    if (filter === "all") return true;
    if (filter === "MANUAL_REVIEW") return r.interrupt !== null;
    return r.decision?.decision === filter;
  });

  if (records.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center gap-6">
        <div className="w-16 h-16 rounded-2xl bg-board flex items-center justify-center">
          <Inbox size={30} className="text-amber" />
        </div>
        <div className="space-y-1.5">
          <h2 className="font-display text-ink" style={{ fontWeight: 600 }}>The board is clear</h2>
          <p className="text-steel max-w-sm">
            No claims in the queue yet. Submit one and the agent will adjudicate it against policy.
          </p>
        </div>
        <Button onClick={() => navigate("/submit")} className="gap-2">
          <PlusCircle size={16} />
          Submit your first claim
        </Button>
      </div>
    );
  }

  const filterOptions: { value: Filter; label: string }[] = [
    { value: "all", label: "All" },
    { value: "APPROVE", label: "Cleared" },
    { value: "PARTIAL_APPROVE", label: "Partial" },
    { value: "REJECT", label: "Denied" },
    { value: "MANUAL_REVIEW", label: "At gate" },
  ];

  const awaitingCount = records.filter(isAwaiting).length;

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <p className="eyebrow text-steel">Approval queue</p>
          <h1 className="font-display text-ink mt-1" style={{ fontWeight: 600 }}>
            Claims Queue
          </h1>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => { if (confirm("Clear all claim history?")) clearAll(); }}
            className="gap-1.5 text-steel hover:text-denied hover:border-denied/40"
          >
            <Trash2 size={14} />
            Clear
          </Button>
          <Button size="sm" onClick={() => navigate("/submit")} className="gap-1.5">
            <PlusCircle size={14} />
            New Claim
          </Button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-2 flex-wrap">
        {filterOptions.map((opt) => (
          <button
            key={opt.value}
            onClick={() => setFilter(opt.value)}
            className={cn(
              "eyebrow px-3 py-1.5 rounded-full border transition-colors",
              filter === opt.value
                ? "bg-ink text-white border-ink"
                : "bg-white border-line text-steel hover:text-ink hover:border-steel"
            )}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* The departures board */}
      <div className="rounded-xl bg-board overflow-hidden shadow-lg shadow-board/20 ring-1 ring-board-line">
        {/* Board header strip */}
        <div className="bg-board-head px-5 py-3 flex items-center justify-between gap-3 border-b border-board-line">
          <div className="flex items-baseline gap-3 min-w-0">
            <span className="eyebrow text-amber">Departures</span>
            <span className="text-sm text-board-fg/55 truncate hidden sm:inline">Claims awaiting a decision</span>
          </div>
          <span className="eyebrow text-board-fg/55 shrink-0">
            {records.length} on board
            {awaitingCount > 0 && <span className="text-amber"> · {awaitingCount} at gate</span>}
          </span>
        </div>

        {/* Column headers (desktop) */}
        <div className={cn(COLS, "hidden px-5 py-2.5 border-b border-board-line")}>
          <span className="eyebrow text-amber/70">Claim</span>
          <span className="eyebrow text-amber/70">Employee</span>
          <span className="eyebrow text-amber/70">Destination</span>
          <span className="eyebrow text-amber/70">Date</span>
          <span className="eyebrow text-amber/70 text-right">Amount</span>
          <span className="eyebrow text-amber/70 text-right">Status</span>
        </div>

        {/* Rows */}
        {filtered.length === 0 ? (
          <div className="py-14 text-center eyebrow text-board-fg/40">
            No claims match this filter
          </div>
        ) : (
          <div style={{ perspective: "1200px" }}>
            {filtered.map((record, i) => {
              const awaiting = isAwaiting(record);
              const amount =
                record.decision?.claimed_amount ??
                record.interrupt?.approved_amount ??
                record.claim.line_items.reduce((s, it) => s + it.amount, 0);
              const outcome: Outcome | undefined = awaiting
                ? "MANUAL_REVIEW"
                : (record.decision?.decision ?? undefined);
              const go = () => navigate(`/claims/${record.claim.claim_id}`);

              return (
                <div
                  key={record.claim.claim_id}
                  role="button"
                  tabIndex={0}
                  onClick={go}
                  onKeyDown={(e) => e.key === "Enter" && go()}
                  aria-label={`View claim ${record.claim.claim_id}, ${record.claim.destination ?? "no destination"}, ${USD.format(amount)}`}
                  style={{ animationDelay: `${i * 45}ms` }}
                  className={cn(
                    COLS,
                    "flap-in group cursor-pointer px-5 py-3.5 border-b border-board-line text-board-fg",
                    "transition-colors hover:bg-board-row focus-visible:outline-none focus-visible:bg-board-row",
                    "space-y-2 sm:space-y-0",
                    awaiting && "border-l-2 border-l-amber"
                  )}
                >
                  {/* Claim ID */}
                  <div className="flex items-center gap-2 font-mono text-sm">
                    {awaiting && (
                      <span className="h-1.5 w-1.5 rounded-full bg-amber board-pulse shrink-0" aria-hidden="true" />
                    )}
                    <span className="text-board-fg/90 truncate">{record.claim.claim_id}</span>
                  </div>

                  {/* Employee */}
                  <Cell label="Employee">
                    <span className="font-mono text-sm text-board-fg/80">{record.claim.employee_id}</span>
                  </Cell>

                  {/* Destination */}
                  <Cell label="Destination">
                    <span className="text-sm text-board-fg/65 truncate">
                      {record.claim.destination ?? "—"}
                    </span>
                  </Cell>

                  {/* Date */}
                  <Cell label="Date">
                    <span className="font-mono text-xs text-board-fg/50">
                      {DATE_FMT.format(new Date(record.submittedAt))}
                    </span>
                  </Cell>

                  {/* Amount */}
                  <Cell label="Amount" align="right">
                    <span className="font-mono text-sm tabular-nums text-board-fg/90">
                      {USD.format(amount)}
                    </span>
                  </Cell>

                  {/* Status */}
                  <Cell label="Status" align="right">
                    {outcome ? <OutcomeBadge outcome={outcome} tone="dark" size="sm" /> : null}
                  </Cell>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

/** A board cell: label:value on mobile, bare value (optionally right-aligned) on desktop. */
function Cell({
  label,
  align = "left",
  children,
}: {
  label: string;
  align?: "left" | "right";
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 sm:block",
        align === "right" && "sm:text-right"
      )}
    >
      <span className="eyebrow text-board-fg/35 sm:hidden">{label}</span>
      {children}
    </div>
  );
}
