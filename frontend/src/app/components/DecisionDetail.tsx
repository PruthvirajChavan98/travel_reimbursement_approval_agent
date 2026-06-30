import { useParams, useNavigate } from "react-router";
import { useClaimsStore } from "../../lib/store";
import { outcomeConfig } from "./OutcomeBadge";
import { HitlPanel } from "./HitlPanel";
import { ReasoningTrace } from "./ReasoningTrace";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { ArrowLeft, AlertTriangle, FileWarning, Info } from "lucide-react";
import { cn } from "./ui/utils";
import type { Decision, LineItem, Outcome } from "../../lib/types";

const USD = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const DATE_FMT = new Intl.DateTimeFormat("en-US", { dateStyle: "medium" });

const STAMP_COLOR: Record<Outcome, string> = {
  APPROVE: "var(--td-cleared)",
  PARTIAL_APPROVE: "var(--td-partial)",
  REJECT: "var(--td-denied)",
  MANUAL_REVIEW: "var(--td-gate)",
};

/** The verdict rendered as a rotated, double-outlined rubber stamp. */
function Stamp({ outcome }: { outcome: Outcome }) {
  const { code, label } = outcomeConfig(outcome);
  const color = STAMP_COLOR[outcome];
  return (
    <div
      className="stamp-in inline-block rounded-md border-[2.5px] p-[3px] select-none"
      style={{ borderColor: color, color }}
      role="img"
      aria-label={`Decision: ${label}`}
    >
      <div className="rounded-[3px] border border-current/30 px-5 py-2 flex flex-col items-center">
        <span
          className="font-mono uppercase"
          style={{ fontSize: "0.5rem", letterSpacing: "0.24em", opacity: 0.8 }}
        >
          Travel Desk
        </span>
        <span
          className="font-display uppercase"
          style={{ fontWeight: 700, fontSize: "1.45rem", lineHeight: 1.05, letterSpacing: "0.03em" }}
        >
          {code}
        </span>
      </div>
    </div>
  );
}

function ConfidenceMeter({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const label = pct >= 90 ? "High" : pct >= 70 ? "Medium" : "Low";
  const bar = pct >= 90 ? "bg-cleared" : pct >= 70 ? "bg-amber" : "bg-denied";
  const text = pct >= 90 ? "text-cleared" : pct >= 70 ? "text-amber" : "text-denied";

  return (
    <div className="flex items-center gap-2.5">
      <div className="flex-1 h-1.5 rounded-full bg-line overflow-hidden">
        <div
          className={cn("h-full rounded-full", bar)}
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`Confidence: ${pct}%`}
        />
      </div>
      <span className="font-mono text-xs tabular-nums text-steel w-9 text-right">{pct}%</span>
      <span className={cn("eyebrow", text)}>{label}</span>
    </div>
  );
}

function MiniField({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <p className="eyebrow text-steel/70 mb-1">{label}</p>
      <p className="font-mono text-sm text-ink truncate">{value}</p>
    </div>
  );
}

function ItineraryTable({ items }: { items: LineItem[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line bg-paper">
            {["ID", "Category", "Description", "Date", "Amount", "Receipt"].map((h, i) => (
              <th
                key={h}
                className={cn(
                  "eyebrow text-steel px-4 py-2.5 text-left",
                  i === 3 && "hidden sm:table-cell",
                  i === 4 && "text-right",
                  i === 5 && "text-center"
                )}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {items.map((item) => (
            <tr key={item.id} className="hover:bg-paper/60">
              <td className="px-4 py-3 font-mono text-xs text-steel">{item.id}</td>
              <td className="px-4 py-3 capitalize text-ink">{item.category.replace("_", " ")}</td>
              <td className="px-4 py-3 text-ink/80">{item.description}</td>
              <td className="px-4 py-3 text-steel hidden sm:table-cell">
                {new Date(item.date).toLocaleDateString("en-US", { dateStyle: "medium" })}
              </td>
              <td className="px-4 py-3 text-right font-mono tabular-nums text-ink">{USD.format(item.amount)}</td>
              <td className="px-4 py-3 text-center">
                <span
                  className={cn("inline-block w-2 h-2 rounded-full", item.has_receipt ? "bg-cleared" : "bg-line")}
                  aria-label={item.has_receipt ? "Receipt present" : "No receipt"}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DecisionDetail() {
  const { claimId } = useParams<{ claimId: string }>();
  const navigate = useNavigate();
  const getClaimById = useClaimsStore((s) => s.getClaimById);
  const updateClaim = useClaimsStore((s) => s.updateClaim);

  const record = claimId ? getClaimById(claimId) : undefined;

  if (!record) {
    return (
      <div className="flex flex-col items-center justify-center py-24 gap-4 text-center">
        <FileWarning size={40} className="text-steel/50" />
        <div>
          <h2 className="font-display text-ink" style={{ fontWeight: 600 }}>Claim not found</h2>
          <p className="text-steel mt-1">No claim found with ID {claimId}.</p>
        </div>
        <Button variant="outline" onClick={() => navigate("/")} className="gap-2">
          <ArrowLeft size={15} />
          Back to queue
        </Button>
      </div>
    );
  }

  const { claim, decision, interrupt, trace } = record;
  const isAwaiting = interrupt !== null;
  const outcome: Outcome = isAwaiting ? "MANUAL_REVIEW" : (decision?.decision ?? "MANUAL_REVIEW");
  const approvedAmount = decision?.approved_amount ?? interrupt?.approved_amount ?? 0;

  const handleResolved = (resolved: Decision) => {
    updateClaim(claim.claim_id, { decision: resolved, interrupt: null });
  };

  const hasBreakdown =
    !!decision &&
    (decision.deductions.length > 0 ||
      decision.missing_documents.length > 0 ||
      decision.policy_references.length > 0);

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Back nav */}
      <button
        onClick={() => navigate("/")}
        className="eyebrow flex items-center gap-1.5 text-steel hover:text-ink transition-colors"
      >
        <ArrowLeft size={13} />
        Claims Queue
      </button>

      {/* Boarding pass */}
      <div className="relative flex flex-col sm:flex-row rounded-xl border border-line bg-ticket shadow-sm overflow-hidden">
        {/* Main panel */}
        <div className="flex-1 p-6 space-y-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="eyebrow text-amber">Boarding pass</p>
              <h1 className="font-mono text-ink mt-1" style={{ fontSize: "1.15rem" }}>
                {claim.claim_id}
              </h1>
            </div>
            <p className="text-xs text-steel text-right leading-relaxed">
              Submitted
              <br />
              {new Date(record.submittedAt).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" })}
            </p>
          </div>

          {/* Destination hero */}
          <div>
            <p className="eyebrow text-steel/70 mb-1">Destination</p>
            <p
              className="font-display text-ink leading-none"
              style={{ fontWeight: 600, fontSize: "2rem" }}
            >
              {claim.destination ?? "—"}
            </p>
          </div>

          {/* Field row */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-5 gap-y-3 border-t border-line pt-4">
            <MiniField label="Passenger" value={claim.employee_id} />
            <MiniField label="Role" value={<span className="capitalize">{claim.employee_role ?? "employee"}</span>} />
            <MiniField label="Depart" value={claim.start_date ? DATE_FMT.format(new Date(claim.start_date)) : "—"} />
            <MiniField label="Return" value={claim.end_date ? DATE_FMT.format(new Date(claim.end_date)) : "—"} />
          </div>

          {claim.trip_purpose && (
            <div>
              <p className="eyebrow text-steel/70 mb-1">Purpose</p>
              <p className="text-sm text-ink/80">{claim.trip_purpose}</p>
            </div>
          )}

          {decision?.explanation && (
            <div className="rounded-md bg-paper border border-line px-4 py-3 flex gap-2.5">
              <Info size={15} className="text-steel shrink-0 mt-0.5" aria-hidden="true" />
              <p className="text-sm text-ink/80">{decision.explanation}</p>
            </div>
          )}
        </div>

        {/* Mobile tear */}
        <div className="perforation sm:hidden mx-6" />

        {/* Stub */}
        <div className="relative sm:w-60 shrink-0 p-6 flex flex-col gap-5 sm:border-l-2 sm:border-dashed sm:border-[color:var(--td-line)]">
          {/* Punched notches on the tear (desktop) */}
          <span className="hidden sm:block absolute -left-2.5 -top-2.5 w-5 h-5 rounded-full bg-paper" aria-hidden="true" />
          <span className="hidden sm:block absolute -left-2.5 -bottom-2.5 w-5 h-5 rounded-full bg-paper" aria-hidden="true" />

          <div className="flex items-center justify-between">
            <span className="eyebrow text-steel">Decision</span>
            <Badge variant="outline" className="eyebrow text-steel/70 border-line">{record.mode}</Badge>
          </div>

          <div className="flex justify-center py-1">
            <Stamp outcome={outcome} />
          </div>

          <div className="text-center">
            <p className="eyebrow text-steel/70 mb-1">{decision ? "Approved" : "Proposed approved"}</p>
            <p className="font-mono tabular-nums text-ink" style={{ fontWeight: 600, fontSize: "1.6rem" }}>
              {USD.format(approvedAmount)}
            </p>
            {decision && (
              <p className="font-mono text-xs text-steel mt-1.5">
                claimed {USD.format(decision.claimed_amount)} · deducted {USD.format(decision.rejected_amount)}
              </p>
            )}
          </div>

          {decision && (
            <div className="mt-auto">
              <p className="eyebrow text-steel/70 mb-2">Confidence</p>
              <ConfidenceMeter value={decision.confidence} />
            </div>
          )}
        </div>
      </div>

      {/* HITL — when the claim is held at the gate */}
      {isAwaiting && interrupt && <HitlPanel interrupt={interrupt} onResolved={handleResolved} />}

      {/* Adjustments & policy */}
      {hasBreakdown && decision && (
        <div className="bg-white rounded-xl border border-line shadow-sm p-6 space-y-5">
          <h2 className="font-display text-ink" style={{ fontWeight: 600 }}>Adjustments & policy</h2>

          {decision.deductions.length > 0 && (
            <div>
              <p className="eyebrow text-steel mb-3">Fare adjustments ({decision.deductions.length})</p>
              <div className="overflow-x-auto rounded-lg border border-partial/30 overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-partial/10 border-b border-partial/25">
                      {["Line item", "Reason", "Policy", "Amount"].map((h, i) => (
                        <th
                          key={h}
                          className={cn("eyebrow text-partial px-4 py-2.5 text-left", i === 3 && "text-right")}
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-line">
                    {decision.deductions.map((d, i) => (
                      <tr key={i}>
                        <td className="px-4 py-3 font-mono text-xs text-steel">{d.line_item_id}</td>
                        <td className="px-4 py-3 text-ink/80">{d.reason}</td>
                        <td className="px-4 py-3">
                          {d.policy_ref && (
                            <Badge variant="outline" className="font-mono text-xs border-partial/40 text-partial bg-partial/5">
                              {d.policy_ref}
                            </Badge>
                          )}
                        </td>
                        <td className="px-4 py-3 text-right font-mono tabular-nums text-denied">
                          −{USD.format(d.amount)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {decision.missing_documents.length > 0 && (
            <div>
              <p className="eyebrow text-steel mb-2">Missing documents</p>
              <ul className="space-y-1.5">
                {decision.missing_documents.map((doc, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-partial">
                    <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                    {doc}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {decision.policy_references.length > 0 && (
            <div>
              <p className="eyebrow text-steel mb-2">Policy references</p>
              <div className="flex gap-2 flex-wrap">
                {decision.policy_references.map((ref) => (
                  <Badge key={ref} variant="outline" className="font-mono text-xs border-line text-steel">
                    {ref}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Itinerary */}
      <div className="bg-white rounded-xl border border-line shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b border-line">
          <h2 className="font-display text-ink" style={{ fontWeight: 600 }}>Itinerary</h2>
          <p className="text-sm text-steel mt-0.5">
            {claim.line_items.length} item{claim.line_items.length !== 1 ? "s" : ""} ·{" "}
            {USD.format(claim.line_items.reduce((s, i) => s + i.amount, 0))} total claimed
          </p>
        </div>
        <ItineraryTable items={claim.line_items} />
      </div>

      {/* Reasoning trace */}
      {trace && <ReasoningTrace trace={trace} />}
    </div>
  );
}
