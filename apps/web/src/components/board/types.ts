/** Board Reports (screen 14) API types, local to this screen. */
import type { Compliance, ProposalClaim, SectionGap } from "@/components/proposals/types";

export type BoardStatus = "draft" | "pending_approval" | "approved" | "rejected" | "distributed";

export interface BoardReportRow {
  id: string;
  title: string;
  period_start: string;
  period_end: string;
  status: BoardStatus;
  recipients: string[];
  created_at: string;
  is_demo: boolean;
  compliance_status: Compliance["status"] | null;
  distributed: number | null;
}

export interface BoardSection {
  key: string;
  title: string;
  claims: ProposalClaim[];
  gaps: (SectionGap | string)[];
}

export interface DistributionEntry {
  to: string;
  outbox_id: string;
  approval: string | null;
  at: string;
  sha256: string | null;
  outbox_status: string | null;
  sent_at: string | null;
}

export interface BoardReport extends Omit<BoardReportRow, "compliance_status" | "distributed"> {
  content: { sections: BoardSection[]; include_demo: boolean };
  compliance: Compliance | null;
  distribution: DistributionEntry[];
  content_hash?: string;
}

export const EMAIL_RE = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/;
