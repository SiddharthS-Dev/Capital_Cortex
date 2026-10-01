/** Proposal Factory (FR-05) API types, local to this screen. */

export type PackageType = "vc_pitch" | "grant" | "debt_facility" | "esg_memo";
export type ProposalStatus = "draft" | "pending_approval" | "approved" | "rejected" | "changes_requested" | "exported";
export type ExportFormat = "docx" | "pptx" | "xlsx" | "pdf";
export type ComplianceStatus = "clean" | "warnings" | "blocked";

export interface CatalogueArtefact {
  title: string;
  formats: ExportFormat[];
  sections: string[] | "all";
}

export interface Catalogue {
  packages: Record<PackageType, { title: string; sections: string[]; artefacts: string[] }>;
  sections: Record<string, { title: string }>;
  artefacts: Record<string, CatalogueArtefact>;
  template_sets: string[];
}

export interface ProposalRow {
  id: string;
  title: string;
  package_type: PackageType;
  status: ProposalStatus;
  version: number;
  mode: "llm" | "deterministic";
  artefacts: string[];
  opportunity_id: string;
  opportunity_title: string | null;
  created_at: string;
  updated_at: string;
  is_demo: boolean;
  compliance_status: ComplianceStatus | null;
  open_gaps: number;
}

export interface ProposalClaim {
  text: string;
  kind: "fact" | "inference";
  evidence: string[];
  basis: string[];
}

export interface SectionGap { id: string; text: string }

export interface ProposalSection {
  key: string;
  title: string;
  claims: ProposalClaim[];
  gaps: SectionGap[];
}

export interface Waiver { section: string; gap_id: string; reason: string; by: string; at: string }

export interface ComplianceFinding {
  rule: string;
  severity: "warning" | "blocker";
  section: string;
  index: number;
  span: string;
  context: string;
  message: string;
  method: string;
}

export interface Compliance {
  status: ComplianceStatus;
  findings: ComplianceFinding[];
  blocking: ComplianceFinding[];
}

export interface VersionRow { version: number; content_hash: string; reason: string; created_by: string; created_at: string }

export interface ExportRow {
  id: string;
  version: number;
  artefact: string;
  fmt: ExportFormat;
  checksum: string;
  size_bytes: number;
  created_at: string;
}

export interface Proposal extends Omit<ProposalRow, "compliance_status"> {
  content_hash: string;
  sections: ProposalSection[];
  waivers: Waiver[];
  gaps: (SectionGap & { section: string; waived: boolean })[];
  compliance: Compliance | null;
  versions: VersionRow[];
  exports: ExportRow[];
  catalogue: Record<string, CatalogueArtefact>;
}

export interface ProposalVersion {
  version: number;
  sections: ProposalSection[];
  gaps: unknown;
  content_hash: string;
  reason: string;
  created_by: string;
  created_at: string;
}

export interface CreateResult {
  id: string;
  version: number;
  mode: "llm" | "deterministic";
  claims: { passed: number; rejected: number } | Record<string, unknown>;
  gaps: number;
  compliance: ComplianceStatus;
}

export interface OpportunityOption {
  id: string;
  title: string;
  class: string | null;
  score_band: string | null;
  counterparty_name: string | null;
  is_demo: boolean;
}

export const PACKAGE_LABELS: Record<PackageType, string> = {
  vc_pitch: "VC pitch",
  grant: "Grant application",
  debt_facility: "Debt facility",
  esg_memo: "ESG memo",
};
