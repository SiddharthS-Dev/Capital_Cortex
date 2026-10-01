/** "Log meeting" modal (FR-04): attendees, commitments → commitment_expiry milestones, next steps → follow-up. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { useId, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { usePermission } from "@/lib/queries";
import type { RelationshipDialogProps } from "./LogInteractionDialog";
import { EntityPicker, type PickedRef } from "./pickers";
import { findCachedName, invalidateRelationships } from "./types";
import { controlCls, Field, FormError, localDateToIso, Modal, textareaCls, toLocalInput } from "./ui";

interface CommitmentRow {
  key: number;
  text: string;
  due: string;
  by: string;
}

export function LogMeetingDialog(props: RelationshipDialogProps) {
  return (
    <Modal open={props.open} onOpenChange={props.onOpenChange} wide title="Log meeting"
      description="Attendees get a meeting interaction each. Commitments become tracked milestones with expiry dates; next steps become a follow-up.">
      <MeetingForm {...props} />
    </Modal>
  );
}

function MeetingForm({ onOpenChange, defaultContactId, defaultContactName, opportunityId, onSaved }: RelationshipDialogProps) {
  const qc = useQueryClient();
  const canWrite = usePermission("relationship:write");
  const uid = useId();
  const nextKey = useRef(1);
  const [attendees, setAttendees] = useState<PickedRef[]>(() =>
    defaultContactId ? [{ id: defaultContactId, name: defaultContactName ?? findCachedName(qc, "contacts", defaultContactId) ?? "Selected contact" }] : []);
  const [occurredAt, setOccurredAt] = useState(() => toLocalInput(new Date()));
  const [summary, setSummary] = useState("");
  const [rows, setRows] = useState<CommitmentRow[]>([]);
  const [nextSteps, setNextSteps] = useState("");
  const [followUp, setFollowUp] = useState("");
  const [invalid, setInvalid] = useState<string | null>(null);
  const [saved, setSaved] = useState<{ id: string; milestones: string[] } | null>(null);

  const m = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<{ id: string; milestones: string[] }>("/v1/meetings", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: (r) => {
      invalidateRelationships(qc);
      onSaved?.(r.id);
      setSaved(r);
    },
  });

  const update = (key: number, patch: Partial<CommitmentRow>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const when = new Date(occurredAt);
    if (attendees.length === 0) return setInvalid("Add at least one attendee.");
    if (Number.isNaN(when.getTime())) return setInvalid("Enter when the meeting happened.");
    if (when.getTime() > Date.now() + 60_000) return setInvalid("A logged meeting can't be in the future.");
    const incomplete = rows.find((r) => !r.text.trim() && (r.due || r.by.trim()));
    if (incomplete) return setInvalid("Each commitment needs a description (or remove the empty row).");
    setInvalid(null);
    m.mutate({
      contact_ids: attendees.map((a) => a.id),
      occurred_at: when.toISOString(),
      summary: summary.trim() || undefined,
      opportunity_id: opportunityId,
      commitments: rows.filter((r) => r.text.trim()).map((r) => ({
        text: r.text.trim(),
        due_at: r.due ? localDateToIso(r.due) : undefined,
        by: r.by.trim() || undefined,
      })),
      next_steps: nextSteps.trim() || undefined,
      follow_up_at: followUp ? localDateToIso(followUp, "09:00") : undefined,
    });
  };

  if (!canWrite) return <p className="text-sm text-muted-foreground">Your role can't log meetings (needs relationship:write).</p>;

  if (saved)
    return (
      <div className="space-y-3" role="status">
        <p className="text-sm">
          Meeting logged.{" "}
          {saved.milestones.length > 0
            ? `${saved.milestones.length} milestone${saved.milestones.length === 1 ? "" : "s"} created (commitments and follow-ups); they appear in the follow-up queue, commitment tracker and Grant Calendar.`
            : "No milestones were created."}
        </p>
        <div className="flex justify-end"><Button onClick={() => onOpenChange(false)}>Done</Button></div>
      </div>
    );

  return (
    <form onSubmit={submit} className="space-y-3" noValidate>
      <Field label="Attendees" htmlFor={`${uid}-att`} required hint="Everyone from the other side who attended; each gets a meeting interaction.">
        <EntityPicker kind="contact" id={`${uid}-att`} multiple value={attendees} onChange={setAttendees} placeholder="Search contacts to add…" />
      </Field>
      <Field label="When" htmlFor={`${uid}-at`} required className="sm:w-64">
        <input id={`${uid}-at`} type="datetime-local" className={`${controlCls} h-9`} value={occurredAt} max={toLocalInput(new Date())}
          onChange={(e) => setOccurredAt(e.target.value)} required />
      </Field>
      <Field label="Summary" htmlFor={`${uid}-sum`}>
        <textarea id={`${uid}-sum`} className={textareaCls} maxLength={4000} value={summary} onChange={(e) => setSummary(e.target.value)} />
      </Field>

      <fieldset className="space-y-2 rounded-md border p-3">
        <legend className="px-1 text-xs font-medium">Commitments</legend>
        <p className="text-[11px] text-muted-foreground">Promises made by either side. Each becomes a commitment milestone that expires on its due date.</p>
        {rows.length === 0 && <p className="text-xs text-muted-foreground">No commitments added.</p>}
        {rows.map((r, i) => (
          <div key={r.key} className="grid gap-2 sm:grid-cols-[1fr_9.5rem_8rem_auto] sm:items-end">
            <Field label={`Commitment ${i + 1}`} htmlFor={`${uid}-c${r.key}-t`}>
              <input id={`${uid}-c${r.key}-t`} className={`${controlCls} h-9`} maxLength={500} value={r.text}
                onChange={(e) => update(r.key, { text: e.target.value })} placeholder="e.g. Send revised budget" />
            </Field>
            <Field label="Due" htmlFor={`${uid}-c${r.key}-d`}>
              <input id={`${uid}-c${r.key}-d`} type="date" className={`${controlCls} h-9`} value={r.due} onChange={(e) => update(r.key, { due: e.target.value })} />
            </Field>
            <Field label="By" htmlFor={`${uid}-c${r.key}-b`}>
              <input id={`${uid}-c${r.key}-b`} className={`${controlCls} h-9`} maxLength={200} value={r.by}
                onChange={(e) => update(r.key, { by: e.target.value })} placeholder="us / them" />
            </Field>
            <Button type="button" variant="ghost" size="icon" aria-label={`Remove commitment ${i + 1}`}
              onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}>
              <Trash2 />
            </Button>
          </div>
        ))}
        <Button type="button" variant="outline" size="sm" disabled={rows.length >= 20}
          onClick={() => setRows((rs) => [...rs, { key: nextKey.current++, text: "", due: "", by: "" }])}>
          <Plus /> Add commitment
        </Button>
      </fieldset>

      <div className="grid gap-3 sm:grid-cols-[1fr_11rem]">
        <Field label="Next steps" htmlFor={`${uid}-ns`}>
          <textarea id={`${uid}-ns`} className={textareaCls} maxLength={2000} value={nextSteps} onChange={(e) => setNextSteps(e.target.value)} />
        </Field>
        <Field label="Follow up on" htmlFor={`${uid}-fu`} hint="Creates a follow-up in the queue.">
          <input id={`${uid}-fu`} type="date" className={`${controlCls} h-9`} value={followUp} min={toLocalInput(new Date(), false)}
            onChange={(e) => setFollowUp(e.target.value)} />
        </Field>
      </div>
      {opportunityId && <p className="text-xs text-muted-foreground">Linked to this opportunity.</p>}
      <FormError message={invalid} />
      <FormError error={m.error} />
      <div className="flex justify-end gap-2 pt-1">
        <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button type="submit" disabled={m.isPending}>{m.isPending && <Loader2 className="animate-spin" />} Log meeting</Button>
      </div>
    </form>
  );
}
