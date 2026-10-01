/** Local types and cache helpers for Relationship Intelligence (FR-04). */
import type { QueryClient } from "@tanstack/react-query";

export interface Contact {
  id: string;
  name: string;
  role: string | null;
  emails: string[];
  consent_basis: ConsentBasis;
  organization_id: string | null;
  organization_name: string | null;
  organization_kind: string | null;
  /** 0–1, computed from real interactions; null = no interactions recorded (a gap, never 0). */
  warmth: number | null;
  last_touch_at: string | null;
  is_demo: boolean;
  interactions: number;
  open_milestones: number;
  /** 12 weekly warmth values, oldest first; empty when there are no interactions. */
  sparkline: number[];
}

export interface Page<T> {
  items: T[];
  next_cursor?: string | null;
}

export interface Organization {
  id: string;
  name: string;
  kind: string | null;
  country: string | null;
  is_demo: boolean;
}

export type ConsentBasis = "consent" | "legitimate_interest" | "contract" | "public_professional" | "manual_entry";

export const CONSENT_BASES: { value: ConsentBasis; label: string; help: string }[] = [
  { value: "consent", label: "Consent", help: "The person explicitly agreed to be contacted and to have their details stored." },
  { value: "legitimate_interest", label: "Legitimate interest", help: "An existing business relationship where contact is reasonably expected; balanced against their rights." },
  { value: "contract", label: "Contract", help: "Processing is needed to perform or prepare a contract with this person or their organisation." },
  { value: "public_professional", label: "Public professional", help: "Details published by the person in a professional capacity (e.g. a programme officer listing)." },
  { value: "manual_entry", label: "Manual entry", help: "Entered by hand from your own records; review the basis before any outreach." },
];

export type InteractionKind = "meeting" | "intro" | "email_sent" | "email_reply" | "call" | "note";
export const INTERACTION_KINDS: { value: InteractionKind; label: string }[] = [
  { value: "call", label: "Call" },
  { value: "meeting", label: "Meeting" },
  { value: "email_sent", label: "E-mail sent" },
  { value: "email_reply", label: "E-mail reply received" },
  { value: "intro", label: "Introduction" },
  { value: "note", label: "Note" },
];

export interface Milestone {
  id: string;
  kind: "follow_up" | "commitment_expiry" | "deadline" | "submission";
  title: string;
  description: string | null;
  due_at: string;
  status: "open" | "done" | "cancelled";
  completed_at: string | null;
  owner_id: string | null;
  opportunity_id: string | null;
  contact_id: string | null;
  organization_id: string | null;
  meeting_id: string | null;
  is_demo: boolean;
  contact_name: string | null;
  organization_name: string | null;
  opportunity_title: string | null;
  overdue: boolean;
}

export interface TimelineEvent {
  type: "interaction" | "milestone" | "introduction" | "outbox";
  at: string;
  ref: string;
  kind?: string;
  direction?: string | null;
  summary?: string | null;
  opportunity_id?: string | null;
  recorded_by?: string | null;
  source?: string | null;
  title?: string;
  due_at?: string;
  status?: string;
  introducer?: string | null;
  channel?: string;
  subject?: string;
  [k: string]: unknown;
}

export interface Timeline {
  contact: { id: string; name: string };
  warmth: number | null;
  sparkline: number[];
  events: TimelineEvent[];
}

/** Everything a relationship write can change; warmth feeds scoring, so opportunities are rescored too. */
export function invalidateRelationships(qc: QueryClient) {
  for (const k of ["contacts", "contact-timeline", "milestones", "meetings", "calendar", "opportunity", "opportunities"]) {
    void qc.invalidateQueries({ queryKey: [k] });
  }
}

/** Find a display name for an id in anything already cached under a key prefix (no extra audited reads). */
export function findCachedName(qc: QueryClient, prefix: string, id: string, field: "id" | "organization_id" = "id"): string | null {
  const nameField = field === "id" ? "name" : "organization_name";
  const seen = new Set<unknown>();
  const walk = (v: unknown): string | null => {
    if (!v || typeof v !== "object" || seen.has(v)) return null;
    seen.add(v);
    if (Array.isArray(v)) {
      for (const x of v) {
        const r = walk(x);
        if (r) return r;
      }
      return null;
    }
    const o = v as Record<string, unknown>;
    if (o[field] === id && typeof o[nameField] === "string") return o[nameField] as string;
    for (const x of Object.values(o)) {
      if (x && typeof x === "object") {
        const r = walk(x);
        if (r) return r;
      }
    }
    return null;
  };
  for (const [, data] of qc.getQueriesData({ queryKey: [prefix] })) {
    const r = walk(data);
    if (r) return r;
  }
  return null;
}
