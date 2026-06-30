import { useForm, useFieldArray, Controller, type SubmitHandler } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import { useRef, useState } from "react";
import {
  Plus,
  Trash2,
  ChevronDown,
  Loader2,
  FlaskConical,
  Upload,
} from "lucide-react";
import { claimFormSchema, type ClaimFormValues } from "../../lib/schemas";
import { adjudicate, extractReceipt } from "../../lib/api";
import { useClaimsStore } from "../../lib/store";
import { SAMPLE_CLAIMS, SAMPLE_CLAIM_LABELS } from "../../lib/fixtures";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Checkbox } from "./ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./ui/select";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";
import { Separator } from "./ui/separator";
import { cn } from "./ui/utils";
import type { Claim } from "../../lib/types";

const CATEGORIES = [
  { value: "lodging", label: "Lodging" },
  { value: "meals", label: "Meals" },
  { value: "airfare", label: "Airfare" },
  { value: "ground_transport", label: "Ground Transport" },
  { value: "mileage", label: "Mileage" },
  { value: "other", label: "Other" },
  { value: "personal", label: "Personal" },
] as const;

const ROLES = [
  { value: "employee", label: "Employee" },
  { value: "manager", label: "Manager" },
  { value: "executive", label: "Executive" },
];

const MAX_UPLOAD_MB = 20; // keep in sync with the backend MAX_UPLOAD_MB + nginx client_max_body_size

function generateClaimId() {
  const year = new Date().getFullYear();
  const seq = String(Math.floor(Math.random() * 9000) + 1000);
  return `CLM-${year}-${seq}`;
}

function defaultLineItem(index: number) {
  return {
    id: `L${index + 1}`,
    category: "meals" as const,
    description: "",
    amount: 0,
    date: new Date().toISOString().slice(0, 10),
    vendor: "",
    location: "",
    quantity: undefined,
    has_receipt: false,
  };
}

export function SubmitClaim() {
  const navigate = useNavigate();
  const addClaim = useClaimsStore((s) => s.addClaim);

  const {
    register,
    control,
    handleSubmit,
    reset,
    getValues,
    formState: { errors },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } = useForm<ClaimFormValues>({
    resolver: zodResolver(claimFormSchema) as any,
    defaultValues: {
      claim_id: generateClaimId(),
      employee_id: "",
      employee_role: "employee",
      trip_purpose: "",
      destination: "",
      start_date: "",
      end_date: "",
      currency: "USD",
      line_items: [defaultLineItem(0)],
    },
  });

  const { fields, append, remove, replace } = useFieldArray({ control, name: "line_items" });

  const mutation = useMutation({
    mutationFn: adjudicate,
    onSuccess: (data, claim) => {
      addClaim({
        claim,
        decision: data.decision,
        interrupt: data.interrupt,
        trace: data.trace,
        mode: data.mode,
        submittedAt: new Date().toISOString(),
      });
      toast.success("Claim submitted successfully");
      navigate(`/claims/${claim.claim_id}`);
    },
    onError: (err: Error) => {
      toast.error(`Submission failed: ${err.message}`);
    },
  });

  // @hookform/resolvers v5 + RHF v7 have a known Resolver type mismatch; cast to bypass
  const onSubmit: SubmitHandler<ClaimFormValues> = (values) => {
    const typedValues = values;
    const claim: Claim = {
      ...typedValues,
      employee_role: typedValues.employee_role || "employee",
      currency: typedValues.currency || "USD",
      line_items: typedValues.line_items.map((item: ClaimFormValues["line_items"][number], i: number) => ({
        ...item,
        id: `L${i + 1}`,
        vendor: item.vendor || undefined,
        location: item.location || undefined,
        quantity: item.quantity || undefined,
        has_receipt: item.has_receipt ?? false,
      })),
    };
    mutation.mutate(claim);
  };

  const loadSample = (key: keyof typeof SAMPLE_CLAIMS) => {
    const sample = SAMPLE_CLAIMS[key];
    reset({
      ...sample,
      vendor: undefined,
      line_items: sample.line_items.map((li) => ({
        ...li,
        vendor: li.vendor ?? "",
        location: li.location ?? "",
        quantity: li.quantity ?? undefined,
        has_receipt: li.has_receipt ?? false,
        receipt_text: li.receipt_text ?? "",
      })),
    } as ClaimFormValues);
    toast.info("Sample claim loaded");
  };

  const fileInputRef = useRef<HTMLInputElement>(null);

  const extraction = useMutation({
    mutationFn: extractReceipt,
    onSuccess: (ext) => {
      const item: ClaimFormValues["line_items"][number] = {
        id: `L${getValues("line_items").length + 1}`,
        category: ext.suggested_category ?? "other",
        description: ext.line_items?.[0]?.description || ext.vendor || "Uploaded bill",
        amount: ext.total ?? ext.line_items?.[0]?.amount ?? 0,
        date: ext.date || new Date().toISOString().slice(0, 10),
        vendor: ext.vendor ?? "",
        location: "",
        quantity: undefined,
        has_receipt: true,
        receipt_text: ext.raw_text || "",
      };
      const current = getValues("line_items");
      // Replace the single empty default line item; otherwise append.
      if (current.length === 1 && !current[0].description && !current[0].amount) replace([item]);
      else append(item);
      if (ext.source === "unavailable") {
        toast.warning("Couldn't read the bill automatically — please enter the details manually.");
      } else {
        const via = ext.source === "vlm" ? "vision model (Kimi-K2.6)" : ext.source === "text" ? "text model" : "mock";
        toast.success(`Bill extracted via ${via}`);
      }
    },
    onError: (err: Error) => toast.error(`Bill extraction failed: ${err.message}`),
  });

  const [dragActive, setDragActive] = useState(false);
  const handleFile = (f?: File | null) => {
    if (!f) return;
    if (f.size > MAX_UPLOAD_MB * 1024 * 1024) {
      toast.error(`File exceeds the ${MAX_UPLOAD_MB} MB limit`);
    } else {
      extraction.mutate(f);
    }
  };

  return (
    <div className="max-w-3xl mx-auto space-y-8">
      {/* Page header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="eyebrow text-steel">New claim</p>
          <h1 className="font-display text-ink mt-1" style={{ fontWeight: 600 }}>
            Submit Expense Claim
          </h1>
          <p className="text-steel mt-1">
            The agent adjudicates your claim against company policy.
          </p>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" className="gap-1.5 shrink-0">
              <FlaskConical size={14} />
              Load sample
              <ChevronDown size={12} />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-64">
            {(Object.keys(SAMPLE_CLAIMS) as Array<keyof typeof SAMPLE_CLAIMS>).map((key) => (
              <DropdownMenuItem key={key} onClick={() => loadSample(key)}>
                {SAMPLE_CLAIM_LABELS[key]}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* hidden file input shared by the upload drop zone */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/png,image/jpeg,application/pdf"
        className="hidden"
        onChange={(e) => {
          handleFile(e.target.files?.[0]);
          e.currentTarget.value = "";
        }}
      />

      {/* Manual entry  ──OR──  Scan a bill */}
      <section className="bg-white rounded-xl border border-line shadow-sm p-6">
        <div className="flex flex-col sm:flex-row items-stretch gap-5">
          {/* Left: manual entry prompt */}
          <div className="flex-1 flex flex-col justify-center">
            <p className="eyebrow text-steel">Manual entry</p>
            <h2 className="font-display text-ink mt-1.5" style={{ fontWeight: 600 }}>
              Enter details by hand
            </h2>
            <p className="text-steel text-sm mt-1">Fill out the claim form below.</p>
            <span className="eyebrow text-steel/60 mt-2">↓ the form continues below</span>
          </div>

          {/* Vertical OR separator (horizontal on mobile) */}
          <div className="flex sm:flex-col items-center justify-center gap-2">
            <div className="h-px sm:h-auto sm:w-px flex-1 bg-line" />
            <span className="eyebrow text-steel/60">OR</span>
            <div className="h-px sm:h-auto sm:w-px flex-1 bg-line" />
          </div>

          {/* Right: large scan-a-bill drop zone */}
          <div className="flex-1">
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={extraction.isPending}
              onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
              onDragLeave={(e) => { e.preventDefault(); setDragActive(false); }}
              onDrop={(e) => { e.preventDefault(); setDragActive(false); handleFile(e.dataTransfer.files?.[0]); }}
              className={cn(
                "w-full h-full min-h-[150px] rounded-lg border-2 border-dashed flex flex-col items-center justify-center gap-1.5 px-4 py-6 text-center transition-colors",
                dragActive
                  ? "border-amber bg-amber-soft/40"
                  : "border-line hover:border-amber/60 hover:bg-amber-soft/20",
                extraction.isPending && "cursor-wait opacity-70",
              )}
            >
              {extraction.isPending ? (
                <>
                  <Loader2 size={28} className="animate-spin text-amber" />
                  <span className="text-sm font-medium text-ink">Reading bill…</span>
                </>
              ) : (
                <>
                  <Upload size={28} className="text-amber" />
                  <span className="text-sm font-medium text-ink">Scan your bill</span>
                  <span className="text-xs text-steel">Drag &amp; drop or click — the agent reads it for you</span>
                  <span className="eyebrow text-steel/60">PDF · PNG · JPG · ≤{MAX_UPLOAD_MB} MB</span>
                </>
              )}
            </button>
          </div>
        </div>
      </section>

      <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-8">
        {/* Claim metadata */}
        <section className="bg-white rounded-xl border border-line shadow-sm p-6 space-y-5">
          <h2 className="font-display text-ink border-b border-line pb-3" style={{ fontWeight: 600 }}>
            Claim Details
          </h2>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Claim ID (read-only) */}
            <div className="space-y-1.5">
              <Label htmlFor="claim_id">Claim ID</Label>
              <Input
                id="claim_id"
                {...register("claim_id")}
                readOnly
                className="bg-paper text-steel font-mono"
              />
            </div>

            {/* Employee ID */}
            <div className="space-y-1.5">
              <Label htmlFor="employee_id">
                Employee ID <span className="text-denied">*</span>
              </Label>
              <Input
                id="employee_id"
                placeholder="e.g. EMP-101"
                className="font-mono"
                {...register("employee_id")}
                aria-invalid={!!errors.employee_id}
              />
              {errors.employee_id && (
                <p className="text-xs text-denied">{errors.employee_id.message}</p>
              )}
            </div>

            {/* Employee role */}
            <div className="space-y-1.5">
              <Label>Employee Role</Label>
              <Controller
                control={control}
                name="employee_role"
                render={({ field }) => (
                  <Select value={field.value ?? "employee"} onValueChange={field.onChange}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ROLES.map((r) => (
                        <SelectItem key={r.value} value={r.value}>
                          {r.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
            </div>

            {/* Destination */}
            <div className="space-y-1.5">
              <Label htmlFor="destination">Destination</Label>
              <Input
                id="destination"
                placeholder="e.g. Chicago, IL"
                {...register("destination")}
              />
            </div>

            {/* Dates */}
            <div className="space-y-1.5">
              <Label htmlFor="start_date">Start Date</Label>
              <Input id="start_date" type="date" {...register("start_date")} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="end_date">End Date</Label>
              <Input id="end_date" type="date" {...register("end_date")} />
            </div>
          </div>

          {/* Trip purpose */}
          <div className="space-y-1.5">
            <Label htmlFor="trip_purpose">Trip Purpose / Business Justification</Label>
            <textarea
              id="trip_purpose"
              {...register("trip_purpose")}
              rows={2}
              placeholder="Brief description of the business reason for travel…"
              className="w-full rounded-md border border-line bg-white px-3 py-2 text-sm placeholder:text-steel/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber resize-none"
            />
          </div>
        </section>

        {/* Line items */}
        <section className="bg-white rounded-xl border border-line shadow-sm p-6 space-y-4">
          <div className="flex items-center justify-between border-b border-line pb-3">
            <h2 className="font-display text-ink" style={{ fontWeight: 600 }}>Line Items</h2>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => append(defaultLineItem(fields.length))}
              className="gap-1.5"
            >
              <Plus size={14} />
              Add item
            </Button>
          </div>

          {errors.line_items?.root && (
            <p className="text-sm text-denied">{errors.line_items.root.message}</p>
          )}

          <div className="space-y-4">
            {fields.map((field, index) => (
              <div
                key={field.id}
                className={cn(
                  "rounded-lg border border-line p-4 space-y-4 relative",
                  index % 2 === 0 ? "bg-white" : "bg-paper/60"
                )}
              >
                <div className="flex items-center justify-between">
                  <span className="eyebrow text-steel/70">
                    Line item {index + 1} · ID L{index + 1}
                  </span>
                  {fields.length > 1 && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => remove(index)}
                      className="h-7 w-7 p-0 text-steel/70 hover:text-denied"
                      aria-label={`Remove line item ${index + 1}`}
                    >
                      <Trash2 size={14} />
                    </Button>
                  )}
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {/* Category */}
                  <div className="space-y-1.5">
                    <Label>Category <span className="text-denied">*</span></Label>
                    <Controller
                      control={control}
                      name={`line_items.${index}.category`}
                      render={({ field: f }) => (
                        <Select value={f.value} onValueChange={f.onChange}>
                          <SelectTrigger aria-invalid={!!errors.line_items?.[index]?.category}>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {CATEGORIES.map((c) => (
                              <SelectItem key={c.value} value={c.value}>
                                {c.label}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      )}
                    />
                  </div>

                  {/* Description */}
                  <div className="space-y-1.5">
                    <Label>Description <span className="text-denied">*</span></Label>
                    <Input
                      placeholder="Brief description"
                      {...register(`line_items.${index}.description`)}
                      aria-invalid={!!errors.line_items?.[index]?.description}
                    />
                    {errors.line_items?.[index]?.description && (
                      <p className="text-xs text-denied">
                        {errors.line_items[index]?.description?.message}
                      </p>
                    )}
                  </div>

                  {/* Amount */}
                  <div className="space-y-1.5">
                    <Label>Amount (USD) <span className="text-denied">*</span></Label>
                    <Input
                      type="number"
                      step="0.01"
                      min="0"
                      placeholder="0.00"
                      {...register(`line_items.${index}.amount`)}
                      aria-invalid={!!errors.line_items?.[index]?.amount}
                    />
                    {errors.line_items?.[index]?.amount && (
                      <p className="text-xs text-denied">
                        {errors.line_items[index]?.amount?.message}
                      </p>
                    )}
                  </div>

                  {/* Date */}
                  <div className="space-y-1.5">
                    <Label>Date <span className="text-denied">*</span></Label>
                    <Input
                      type="date"
                      {...register(`line_items.${index}.date`)}
                      aria-invalid={!!errors.line_items?.[index]?.date}
                    />
                  </div>

                  {/* Vendor */}
                  <div className="space-y-1.5">
                    <Label>Vendor <span className="text-steel/70 font-normal">(optional)</span></Label>
                    <Input placeholder="e.g. Marriott" {...register(`line_items.${index}.vendor`)} />
                  </div>

                  {/* Location (relevant for lodging) */}
                  <div className="space-y-1.5">
                    <Label>Location / City <span className="text-steel/70 font-normal">(optional)</span></Label>
                    <Input placeholder="e.g. Chicago" {...register(`line_items.${index}.location`)} />
                  </div>

                  {/* Quantity */}
                  <div className="space-y-1.5">
                    <Label>Quantity <span className="text-steel/70 font-normal">(nights/days/miles)</span></Label>
                    <Input
                      type="number"
                      step="1"
                      min="0"
                      placeholder="—"
                      {...register(`line_items.${index}.quantity`)}
                    />
                  </div>

                  {/* Receipt */}
                  <div className="flex items-center gap-2.5 pt-6">
                    <Controller
                      control={control}
                      name={`line_items.${index}.has_receipt`}
                      render={({ field: f }) => (
                        <Checkbox
                          id={`receipt-${index}`}
                          checked={f.value ?? false}
                          onCheckedChange={f.onChange}
                        />
                      )}
                    />
                    <Label htmlFor={`receipt-${index}`} className="cursor-pointer">
                      Receipt attached
                    </Label>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Totals preview */}
          <Separator />
          <div className="flex justify-end">
            <div className="text-sm text-steel space-y-1">
              <div className="flex justify-between gap-8">
                <span className="text-steel">Total claimed</span>
                <span className="font-mono font-medium text-ink">
                  {new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(
                    fields.reduce((sum, _, i) => {
                      const val = (control._formValues.line_items?.[i]?.amount as number) ?? 0;
                      return sum + Number(val);
                    }, 0)
                  )}
                </span>
              </div>
            </div>
          </div>
        </section>

        {/* Submit */}
        <div className="flex justify-end gap-3">
          <Button
            type="button"
            variant="outline"
            onClick={() => navigate("/")}
            disabled={mutation.isPending}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            disabled={mutation.isPending}
            className="gap-2 min-w-[140px]"
          >
            {mutation.isPending ? (
              <>
                <Loader2 size={15} className="animate-spin" />
                Submitting…
              </>
            ) : (
              "Submit for Adjudication"
            )}
          </Button>
        </div>
      </form>
    </div>
  );
}
