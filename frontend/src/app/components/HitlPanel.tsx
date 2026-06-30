import React, { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, XCircle, Loader2, UserCheck, AlertCircle } from "lucide-react";
import { toast } from "sonner";
import { resumeClaim } from "../../lib/api";
import { fetchHealthz } from "../../lib/api";
import type { Interrupt, Decision } from "../../lib/types";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip";
import { cn } from "./ui/utils";

interface HitlPanelProps {
  interrupt: Interrupt;
  onResolved: (decision: Decision) => void;
}

export function HitlPanel({ interrupt, onResolved }: HitlPanelProps) {
  const [approver, setApprover] = useState("");
  const [note, setNote] = useState("");

  const { data: healthz } = useQuery({
    queryKey: ["healthz"],
    queryFn: fetchHealthz,
    staleTime: 30_000,
  });

  const isBackendMockMode = healthz?.mode === "mock";

  const mutation = useMutation({
    mutationFn: ({ approved }: { approved: boolean }) =>
      resumeClaim({
        claim_id: interrupt.claim_id,
        approved,
        approver,
        note: note || undefined,
      }),
    onSuccess: (data, vars) => {
      if (data.decision) {
        onResolved(data.decision);
        toast.success(
          vars.approved ? "Claim approved successfully" : "Claim rejected"
        );
      } else if ((data as { error?: string }).error) {
        toast.error(`Resume failed: ${(data as { error?: string }).error}`);
      }
    },
    onError: (err: Error) => {
      toast.error(`Resume failed: ${err.message}`);
    },
  });

  const handleAction = (approved: boolean) => {
    if (!approver.trim()) {
      toast.error("Approver name is required");
      return;
    }
    mutation.mutate({ approved });
  };

  const USD = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

  return (
    <div
      className={cn(
        "rounded-xl border-2 shadow-sm overflow-hidden bg-white",
        isBackendMockMode ? "border-line opacity-60" : "border-gate/45"
      )}
      aria-label="Held for manual review"
    >
      {/* Header */}
      <div className="bg-gate/10 border-b border-gate/20 px-5 py-4 flex items-start gap-3">
        <div className="w-8 h-8 rounded-full bg-gate/15 border border-gate/30 flex items-center justify-center shrink-0 mt-0.5">
          <UserCheck size={15} className="text-gate" aria-hidden="true" />
        </div>
        <div>
          <h3 className="font-display text-ink" style={{ fontWeight: 600 }}>Held at the gate</h3>
          <p className="text-sm text-steel mt-0.5">
            This claim needs a <strong className="text-ink">{interrupt.required_approver_role}</strong> to
            approve or reject it before it can clear.
          </p>
        </div>
      </div>

      <div className="p-5 space-y-5">
        {/* Reasons */}
        <div>
          <p className="eyebrow text-steel mb-2">Why it's held</p>
          <ul className="space-y-1.5">
            {interrupt.manual_review_reasons.map((reason, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-ink/80">
                <AlertCircle size={14} className="text-gate shrink-0 mt-0.5" aria-hidden="true" />
                {reason}
              </li>
            ))}
          </ul>
        </div>

        {/* Proposed amount */}
        <div className="rounded-lg bg-paper border border-line px-4 py-3 flex items-center justify-between">
          <span className="text-sm text-steel">Proposed approved amount</span>
          <span className="font-mono font-semibold tabular-nums text-ink">
            {USD.format(interrupt.approved_amount)}
          </span>
        </div>

        <p className="text-xs text-steel">
          Approving finalizes the claim at the proposed amount. Rejecting sets the approved amount to $0.
          Computed amounts can't be changed here.
        </p>

        {isBackendMockMode ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="cursor-not-allowed rounded-lg border border-line bg-paper p-3 text-center text-sm text-steel">
                Resume is unavailable — the backend is running in mock mode
              </div>
            </TooltipTrigger>
            <TooltipContent>
              The connected backend is in mock mode. Switch to live mode to enable human-in-the-loop review.
            </TooltipContent>
          </Tooltip>
        ) : (
          <div className="space-y-4">
            {/* Approver input */}
            <div className="space-y-1.5">
              <Label htmlFor="approver-name">
                Your name / approver ID <span className="text-denied">*</span>
              </Label>
              <Input
                id="approver-name"
                placeholder={`${interrupt.required_approver_role}_name`}
                value={approver}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setApprover(e.target.value)}
                disabled={mutation.isPending}
              />
            </div>

            {/* Note input */}
            <div className="space-y-1.5">
              <Label htmlFor="review-note">
                Note <span className="text-steel font-normal">(optional)</span>
              </Label>
              <Input
                id="review-note"
                placeholder="e.g. Receipt provided offline"
                value={note}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNote(e.target.value)}
                disabled={mutation.isPending}
              />
            </div>

            {/* Action buttons */}
            <div className="flex gap-3">
              <Button
                onClick={() => handleAction(true)}
                disabled={mutation.isPending}
                className="flex-1 gap-2 bg-cleared hover:bg-cleared/90 text-white"
              >
                {mutation.isPending && mutation.variables?.approved ? (
                  <Loader2 size={15} className="animate-spin" />
                ) : (
                  <CheckCircle2 size={15} />
                )}
                Approve
              </Button>
              <Button
                onClick={() => handleAction(false)}
                disabled={mutation.isPending}
                variant="outline"
                className="flex-1 gap-2 text-denied hover:bg-denied/5 hover:text-denied border-denied/30"
              >
                {mutation.isPending && !mutation.variables?.approved ? (
                  <Loader2 size={15} className="animate-spin" />
                ) : (
                  <XCircle size={15} />
                )}
                Reject
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
