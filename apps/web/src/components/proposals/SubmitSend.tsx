/** Submit for approval (blocked by open gaps / blocking findings) and Send (approved only; creates an outbox item). */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Loader2, Send, ShieldAlert, Stamp } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Modal } from "@/components/approvals/shared";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { usePermission } from "@/lib/queries";
import { cn } from "@/lib/utils";
import { FindingItem, MutationError, problemOf } from "./shared";
import type { Proposal } from "./types";

const focusRing = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1";

function SendDialog({ p, onClose }: { p: Proposal; onClose: () => void }) {
  const qc = useQueryClient();
  const [channel, setChannel] = useState<"email" | "portal_export">("email");
  const [to, setTo] = useState("");
  const m = useMutation({
    mutationFn: () => api<{ outbox_id: string; approval_id: string; attachments: unknown[] }>(`/v1/proposals/${p.id}/send`, {
      method: "POST", body: JSON.stringify({ channel, ...(to.trim() ? { to: to.trim() } : {}) }),
    }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["approvals"] });
      void qc.invalidateQueries({ queryKey: ["outbox"] });
      void qc.invalidateQueries({ queryKey: ["proposal", p.id] });
    },
  });
  const needsTo = channel === "email";
  return (
    <Modal open onOpenChange={(o) => { if (!o) onClose(); }} title="Send approved package"
      description="Sending creates an outbox item that needs its own approval before anything leaves Capital Cortex.">
      {m.data ? (
        <div className="space-y-3 text-sm" role="status">
          <p>Outbox item created with {m.data.attachments?.length ?? 0} attachment(s). It is waiting for approval.</p>
          <div className="flex gap-2">
            <Button asChild><Link to={`/approvals?id=${m.data.approval_id}`}>Open approval <ExternalLink /></Link></Button>
            <Button variant="ghost" onClick={onClose}>Close</Button>
          </div>
        </div>
      ) : (
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
          <fieldset>
            <legend className="text-sm font-medium">Channel</legend>
            <div className="mt-1 flex gap-4 text-sm">
              {(["email", "portal_export"] as const).map((c) => (
                <label key={c} className="flex items-center gap-1.5">
                  <input type="radio" name="pf-channel" value={c} checked={channel === c} onChange={() => setChannel(c)} />
                  {c === "email" ? "E-mail" : "Portal export"}
                </label>
              ))}
            </div>
          </fieldset>
          <div>
            <label htmlFor="pf-send-to" className="block text-sm font-medium">
              Recipient {needsTo ? "" : <span className="font-normal text-muted-foreground">(optional)</span>}
            </label>
            <Input id="pf-send-to" className="mt-1" type={needsTo ? "email" : "text"} maxLength={300} value={to} onChange={(e) => setTo(e.target.value)}
              placeholder={needsTo ? "name@funder.org" : "portal name or reference"} required={needsTo} />
          </div>
          <MutationError error={m.error} />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={m.isPending || (needsTo && !to.trim())}>{m.isPending ? <Loader2 className="animate-spin" /> : <Send />} Create outbox item</Button>
          </div>
        </form>
      )}
    </Modal>
  );
}

export function SubmitPanel({ p }: { p: Proposal }) {
  const qc = useQueryClient();
  const canRequest = usePermission("approval:request");
  const canDraft = usePermission("outbox:draft");
  const [sendOpen, setSendOpen] = useState(false);
  const openGaps = p.gaps.filter((g) => !g.waived);
  const blocking = p.compliance?.blocking ?? (p.compliance?.findings ?? []).filter((f) => f.severity === "blocker");
  const sectionTitle = (k: string) => p.sections.find((s) => s.key === k)?.title ?? k;
  const submit = useMutation({
    mutationFn: () => api<{ approval_id: string; status: string }>(`/v1/proposals/${p.id}/submit`, { method: "POST" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["approvals"] });
      void qc.invalidateQueries({ queryKey: ["proposal", p.id] });
      void qc.invalidateQueries({ queryKey: ["proposals"] });
    },
  });
  const blocked = openGaps.length > 0 || blocking.length > 0;
  const submittable = ["draft", "rejected", "changes_requested"].includes(p.status);
  const errP = problemOf(submit.error);

  if (!canRequest && !(canDraft && p.status === "approved")) return null;

  return (
    <div className="space-y-2 rounded-lg border bg-card p-3">
      <div className="flex flex-wrap items-center gap-2">
        {canRequest && (
          <Button onClick={() => submit.mutate()} disabled={blocked || !submittable || submit.isPending} aria-describedby="pf-submit-why">
            {submit.isPending ? <Loader2 className="animate-spin" /> : <Stamp />} Submit for approval
          </Button>
        )}
        {canDraft && p.status === "approved" && (
          <Button variant="outline" onClick={() => setSendOpen(true)}><Send /> Send…</Button>
        )}
        <span id="pf-submit-why" className="text-xs text-muted-foreground">
          {!submittable
            ? p.status === "pending_approval" ? "Waiting for an approver decision." : p.status === "approved" ? "Approved. Send it, or edit to start a new review." : `Status: ${p.status}.`
            : blocked
              ? `Blocked: ${openGaps.length} open evidence gap(s) and ${blocking.length} blocking compliance finding(s). Resolve them${openGaps.length ? " or ask an Admin to waive the gaps" : ""}.`
              : "Ready: no open gaps and no blocking findings."}
        </span>
      </div>
      {submittable && blocked && (
        <details className="text-xs">
          <summary className={cn("cursor-pointer text-muted-foreground", focusRing)}>Show what blocks approval</summary>
          <div className="mt-2 grid gap-3 md:grid-cols-2">
            {openGaps.length > 0 && (
              <ul className="space-y-1" aria-label="Open evidence gaps">
                {openGaps.map((g) => (
                  <li key={`${g.section}:${g.id}`} className="rounded border border-band-insufficient/60 bg-band-insufficient/10 p-1.5 text-band-insufficient">
                    <span className="font-medium">{sectionTitle(g.section)}:</span> [EVIDENCE REQUIRED: {g.text}]
                  </li>
                ))}
              </ul>
            )}
            {blocking.length > 0 && <ul className="space-y-1" aria-label="Blocking findings">{blocking.map((f, i) => <FindingItem key={i} f={f} />)}</ul>}
          </div>
        </details>
      )}
      {submit.data && (
        <p role="status" className="text-sm">
          Submitted. <Link className="text-primary underline" to={`/approvals?id=${submit.data.approval_id}`}>Open the approval request</Link>
        </p>
      )}
      {submit.error != null && (
        <div className="space-y-1">
          <MutationError error={submit.error} />
          {errP?.gaps && errP.gaps.length > 0 && (
            <ul className="ml-4 list-disc text-xs text-band-insufficient">{errP.gaps.map((g, i) => <li key={i}>{g.section ? `${sectionTitle(g.section)}: ` : ""}{g.text}</li>)}</ul>
          )}
          {errP?.findings && errP.findings.length > 0 && (
            <ul className="space-y-1"><li className="flex items-center gap-1 text-xs text-destructive"><ShieldAlert className="size-3.5" aria-hidden /> Findings</li>{errP.findings.map((f, i) => <FindingItem key={i} f={f} />)}</ul>
          )}
        </div>
      )}
      {sendOpen && <SendDialog p={p} onClose={() => setSendOpen(false)} />}
    </div>
  );
}
