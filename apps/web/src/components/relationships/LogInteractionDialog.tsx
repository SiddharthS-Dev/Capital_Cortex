/** Quick "Log interaction" modal (FR-04). Reused by Relationships and Opportunity Detail. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { usePermission } from "@/lib/queries";
import { EntityPicker, type PickedRef } from "./pickers";
import { findCachedName, INTERACTION_KINDS, invalidateRelationships, type InteractionKind } from "./types";
import { Field, FormError, Modal, selectCls, textareaCls, toLocalInput, controlCls } from "./ui";

export interface RelationshipDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultContactId?: string;
  defaultOrganizationId?: string;
  opportunityId?: string;
  /** Optional display names for the defaults; otherwise looked up in the query cache. */
  defaultContactName?: string;
  defaultOrganizationName?: string;
  onSaved?: (id: string) => void;
}

export function LogInteractionDialog(props: RelationshipDialogProps) {
  return (
    <Modal open={props.open} onOpenChange={props.onOpenChange} title="Log interaction"
      description="Record a real touchpoint. Warmth is recomputed from logged interactions and linked opportunities are rescored.">
      <InteractionForm {...props} />
    </Modal>
  );
}

function InteractionForm({ onOpenChange, defaultContactId, defaultOrganizationId, opportunityId, defaultContactName, defaultOrganizationName, onSaved }: RelationshipDialogProps) {
  const qc = useQueryClient();
  const canWrite = usePermission("relationship:write");
  const uid = useId();
  const [kind, setKind] = useState<InteractionKind>("call");
  const [occurredAt, setOccurredAt] = useState(() => toLocalInput(new Date()));
  const [contact, setContact] = useState<PickedRef[]>(() =>
    defaultContactId ? [{ id: defaultContactId, name: defaultContactName ?? findCachedName(qc, "contacts", defaultContactId) ?? "Selected contact" }] : []);
  const [org, setOrg] = useState<PickedRef[]>(() =>
    defaultOrganizationId
      ? [{ id: defaultOrganizationId, name: defaultOrganizationName ?? findCachedName(qc, "organizations", defaultOrganizationId)
          ?? findCachedName(qc, "contacts", defaultOrganizationId, "organization_id") ?? "Selected organisation" }]
      : []);
  const [summary, setSummary] = useState("");
  const [direction, setDirection] = useState("");
  const [introducer, setIntroducer] = useState<PickedRef[]>([]);
  const [invalid, setInvalid] = useState<string | null>(null);

  const m = useMutation({
    mutationFn: (body: Record<string, unknown>) => api<{ id: string }>("/v1/interactions", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: (r) => {
      invalidateRelationships(qc);
      onSaved?.(r.id);
      onOpenChange(false);
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const when = new Date(occurredAt);
    if (Number.isNaN(when.getTime())) return setInvalid("Enter when the interaction happened.");
    if (when.getTime() > Date.now() + 60_000) return setInvalid("An interaction can't be in the future. Schedule a follow-up instead.");
    if (contact.length === 0 && org.length === 0) return setInvalid("Choose a contact or an organisation.");
    if (kind === "intro" && introducer.length === 0) return setInvalid("Choose who made the introduction.");
    setInvalid(null);
    m.mutate({
      kind,
      occurred_at: when.toISOString(),
      contact_id: contact[0]?.id,
      organization_id: org[0]?.id,
      opportunity_id: opportunityId,
      summary: summary.trim() || undefined,
      direction: direction || undefined,
      introduced_by: kind === "intro" ? introducer[0]?.id : undefined,
    });
  };

  if (!canWrite) return <p className="text-sm text-muted-foreground">Your role can't log interactions (needs relationship:write).</p>;

  return (
    <form onSubmit={submit} className="space-y-3" noValidate>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Kind" htmlFor={`${uid}-kind`} required>
          <select id={`${uid}-kind`} className={selectCls} value={kind} onChange={(e) => setKind(e.target.value as InteractionKind)}>
            {INTERACTION_KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
          </select>
        </Field>
        <Field label="When" htmlFor={`${uid}-at`} required hint="Local time; can't be in the future.">
          <input id={`${uid}-at`} type="datetime-local" className={`${controlCls} h-9`} value={occurredAt} max={toLocalInput(new Date())}
            onChange={(e) => setOccurredAt(e.target.value)} required />
        </Field>
      </div>
      <Field label="Contact" htmlFor={`${uid}-contact`} hint="Search by name, or pick an organisation below instead.">
        <EntityPicker kind="contact" id={`${uid}-contact`} value={contact} onChange={setContact} />
      </Field>
      <Field label="Organisation" htmlFor={`${uid}-org`} hint="Optional when a contact is chosen.">
        <EntityPicker kind="organization" id={`${uid}-org`} value={org} onChange={setOrg} />
      </Field>
      {kind === "intro" && (
        <Field label="Introduced by" htmlFor={`${uid}-intro`} required hint="The contact who made the introduction; this builds a warm-intro path.">
          <EntityPicker kind="contact" id={`${uid}-intro`} value={introducer} onChange={setIntroducer} exclude={contact.map((c) => c.id)} />
        </Field>
      )}
      <Field label="Direction" htmlFor={`${uid}-dir`}>
        <select id={`${uid}-dir`} className={selectCls} value={direction} onChange={(e) => setDirection(e.target.value)}>
          <option value="">Not specified</option>
          <option value="outbound">Outbound (we reached out)</option>
          <option value="inbound">Inbound (they reached out)</option>
          <option value="internal">Internal</option>
        </select>
      </Field>
      <Field label="Summary" htmlFor={`${uid}-sum`}>
        <textarea id={`${uid}-sum`} className={textareaCls} maxLength={4000} value={summary} onChange={(e) => setSummary(e.target.value)}
          placeholder="What was discussed?" />
      </Field>
      {opportunityId && <p className="text-xs text-muted-foreground">Linked to this opportunity.</p>}
      <FormError message={invalid} />
      <FormError error={m.error} />
      <div className="flex justify-end gap-2 pt-1">
        <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button type="submit" disabled={m.isPending}>{m.isPending && <Loader2 className="animate-spin" />} Log interaction</Button>
      </div>
    </form>
  );
}
