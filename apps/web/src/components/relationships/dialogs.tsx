/** New contact, draft follow-up (outbox) and new milestone dialogs. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, ShieldCheck } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { usePermission } from "@/lib/queries";
import { EntityPicker, type PickedRef } from "./pickers";
import { CONSENT_BASES, invalidateRelationships, type ConsentBasis } from "./types";
import { controlCls, Field, FormError, localDateToIso, Modal, textareaCls, toLocalInput } from "./ui";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function NewContactDialog({ open, onOpenChange, onCreated }: {
  open: boolean; onOpenChange: (o: boolean) => void; onCreated?: (id: string) => void;
}) {
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="New contact"
      description="Contacts hold personal data. Record why you may lawfully process it; every read of full e-mail addresses is audited.">
      <NewContactForm onOpenChange={onOpenChange} onCreated={onCreated} />
    </Modal>
  );
}

function NewContactForm({ onOpenChange, onCreated }: { onOpenChange: (o: boolean) => void; onCreated?: (id: string) => void }) {
  const qc = useQueryClient();
  const uid = useId();
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [org, setOrg] = useState<PickedRef[]>([]);
  const [emails, setEmails] = useState("");
  const [basis, setBasis] = useState<ConsentBasis | "">("");
  const [invalid, setInvalid] = useState<string | null>(null);
  const m = useMutation({
    mutationFn: (body: Record<string, unknown>) => api<{ id: string }>("/v1/contacts", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: (r) => { invalidateRelationships(qc); onCreated?.(r.id); onOpenChange(false); },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const list = emails.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean);
    if (!name.trim()) return setInvalid("Enter the contact's name.");
    if (list.some((x) => !EMAIL_RE.test(x))) return setInvalid("One of the e-mail addresses doesn't look valid.");
    if (list.length > 5) return setInvalid("At most 5 e-mail addresses.");
    if (!basis) return setInvalid("Choose the lawful basis for holding this person's data.");
    setInvalid(null);
    m.mutate({ name: name.trim(), role: role.trim() || undefined, organization_id: org[0]?.id, emails: list, consent_basis: basis });
  };

  return (
    <form onSubmit={submit} className="space-y-3" noValidate>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Name" htmlFor={`${uid}-n`} required>
          <input id={`${uid}-n`} className={`${controlCls} h-9`} maxLength={200} value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
        </Field>
        <Field label="Role" htmlFor={`${uid}-r`}>
          <input id={`${uid}-r`} className={`${controlCls} h-9`} maxLength={200} value={role} onChange={(e) => setRole(e.target.value)} placeholder="e.g. Programme officer" />
        </Field>
      </div>
      <Field label="Organisation" htmlFor={`${uid}-o`}>
        <EntityPicker kind="organization" id={`${uid}-o`} value={org} onChange={setOrg} />
      </Field>
      <Field label="E-mail addresses" htmlFor={`${uid}-e`} hint="Up to 5, separated by commas or new lines. Lists show them masked.">
        <textarea id={`${uid}-e`} className={`${textareaCls} min-h-14`} value={emails} onChange={(e) => setEmails(e.target.value)} />
      </Field>
      <fieldset className="space-y-1.5">
        <legend className="text-xs font-medium">Lawful basis <span className="text-destructive" aria-hidden>*</span><span className="sr-only">(required)</span></legend>
        <p className="text-[11px] text-muted-foreground">Required. Data-protection law (e.g. GDPR Art. 6) needs a basis for storing and contacting a person; outreach is checked against it.</p>
        {CONSENT_BASES.map((b) => (
          <label key={b.value} className="flex cursor-pointer gap-2 rounded-md border p-2 text-sm has-[:checked]:border-primary has-[:checked]:bg-primary/5">
            <input type="radio" name={`${uid}-basis`} value={b.value} checked={basis === b.value} onChange={() => setBasis(b.value)} className="mt-1" />
            <span><span className="font-medium">{b.label}</span><span className="block text-xs text-muted-foreground">{b.help}</span></span>
          </label>
        ))}
      </fieldset>
      <FormError message={invalid} />
      <FormError error={m.error} />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button type="submit" disabled={m.isPending}>{m.isPending && <Loader2 className="animate-spin" />} Create contact</Button>
      </div>
    </form>
  );
}

export function DraftFollowUpDialog({ open, onOpenChange, contactId, contactName, opportunityId }: {
  open: boolean; onOpenChange: (o: boolean) => void; contactId: string; contactName: string; opportunityId?: string;
}) {
  return (
    <Modal open={open} onOpenChange={onOpenChange} wide title={`Draft follow-up to ${contactName}`}
      description="This creates an outbox draft only. Nothing is sent until a person approves it in the Approval Inbox.">
      <DraftForm onOpenChange={onOpenChange} contactId={contactId} opportunityId={opportunityId} />
    </Modal>
  );
}

function DraftForm({ onOpenChange, contactId, opportunityId }: { onOpenChange: (o: boolean) => void; contactId: string; opportunityId?: string }) {
  const qc = useQueryClient();
  const canDraft = usePermission("outbox:draft");
  const uid = useId();
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [invalid, setInvalid] = useState<string | null>(null);
  const m = useMutation({
    mutationFn: (b: Record<string, unknown>) =>
      api<{ id: string; status: string }>(`/v1/contacts/${contactId}/draft-follow-up`, { method: "POST", body: JSON.stringify(b) }),
    onSuccess: () => {
      invalidateRelationships(qc);
      void qc.invalidateQueries({ queryKey: ["approvals"] });
    },
  });

  if (!canDraft) return <p className="text-sm text-muted-foreground">Your role can't draft outbound messages (needs outbox:draft).</p>;
  if (m.isSuccess)
    return (
      <div className="space-y-3" role="status">
        <p className="flex items-start gap-2 text-sm">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-success" aria-hidden />
          <span>Draft saved to the outbox with status <strong>draft</strong>. It has <strong>not</strong> been sent; an approver must release it.</span>
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="outline" asChild><Link to="/approvals?tab=outbox">Open Approval Inbox</Link></Button>
          <Button onClick={() => onOpenChange(false)}>Done</Button>
        </div>
      </div>
    );

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!subject.trim() || !body.trim()) return setInvalid("Subject and message are both required.");
    setInvalid(null);
    m.mutate({ subject: subject.trim(), body, opportunity_id: opportunityId });
  };
  return (
    <form onSubmit={submit} className="space-y-3" noValidate>
      <Field label="Subject" htmlFor={`${uid}-s`} required>
        <input id={`${uid}-s`} className={`${controlCls} h-9`} maxLength={200} value={subject} onChange={(e) => setSubject(e.target.value)} required autoFocus />
      </Field>
      <Field label="Message" htmlFor={`${uid}-b`} required>
        <textarea id={`${uid}-b`} className={`${textareaCls} min-h-40`} maxLength={10000} value={body} onChange={(e) => setBody(e.target.value)} required />
      </Field>
      <p className="rounded-md border border-dashed p-2 text-xs text-muted-foreground">
        Human-in-the-loop: saving puts this in the outbox as a draft. It is reviewed in the{" "}
        <Link to="/approvals?tab=outbox" className="text-primary underline">Approval Inbox</Link> before anything leaves Capital Cortex.
      </p>
      <FormError message={invalid} />
      <FormError error={m.error} />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button type="submit" disabled={m.isPending}>{m.isPending && <Loader2 className="animate-spin" />} Save draft</Button>
      </div>
    </form>
  );
}

export function NewMilestoneDialog({ open, onOpenChange, kind }: {
  open: boolean; onOpenChange: (o: boolean) => void; kind: "follow_up" | "commitment_expiry";
}) {
  const title = kind === "follow_up" ? "New follow-up" : "New commitment";
  return (
    <Modal open={open} onOpenChange={onOpenChange} title={title}
      description={kind === "follow_up" ? "A dated reminder to get back to a contact." : "Something promised by either side, tracked until it expires."}>
      <MilestoneForm kind={kind} onOpenChange={onOpenChange} />
    </Modal>
  );
}

function MilestoneForm({ kind, onOpenChange }: { kind: "follow_up" | "commitment_expiry"; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const uid = useId();
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [contact, setContact] = useState<PickedRef[]>([]);
  const [org, setOrg] = useState<PickedRef[]>([]);
  const [description, setDescription] = useState("");
  const [invalid, setInvalid] = useState<string | null>(null);
  const m = useMutation({
    mutationFn: (b: Record<string, unknown>) => api<{ id: string }>("/v1/milestones", { method: "POST", body: JSON.stringify(b) }),
    onSuccess: () => { invalidateRelationships(qc); onOpenChange(false); },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return setInvalid("Enter a title.");
    if (!due) return setInvalid("Choose a due date.");
    setInvalid(null);
    m.mutate({ kind, title: title.trim(), due_at: localDateToIso(due, kind === "follow_up" ? "09:00" : "23:59"),
      contact_id: contact[0]?.id, organization_id: org[0]?.id, description: description.trim() || undefined });
  };
  return (
    <form onSubmit={submit} className="space-y-3" noValidate>
      <Field label="Title" htmlFor={`${uid}-t`} required>
        <input id={`${uid}-t`} className={`${controlCls} h-9`} maxLength={300} value={title} onChange={(e) => setTitle(e.target.value)} autoFocus />
      </Field>
      <Field label="Due" htmlFor={`${uid}-d`} required className="sm:w-48">
        <input id={`${uid}-d`} type="date" className={`${controlCls} h-9`} value={due} min={toLocalInput(new Date(), false)} onChange={(e) => setDue(e.target.value)} />
      </Field>
      <Field label="Contact" htmlFor={`${uid}-c`}><EntityPicker kind="contact" id={`${uid}-c`} value={contact} onChange={setContact} /></Field>
      <Field label="Organisation" htmlFor={`${uid}-o`}><EntityPicker kind="organization" id={`${uid}-o`} value={org} onChange={setOrg} /></Field>
      <Field label="Description" htmlFor={`${uid}-x`}>
        <textarea id={`${uid}-x`} className={textareaCls} maxLength={2000} value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field>
      <FormError message={invalid} />
      <FormError error={m.error} />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button type="submit" disabled={m.isPending}>{m.isPending && <Loader2 className="animate-spin" />} Create</Button>
      </div>
    </form>
  );
}
