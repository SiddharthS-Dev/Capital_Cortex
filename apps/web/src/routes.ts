import {
  Activity,
  BellRing,
  Bot,
  CalendarDays,
  ClipboardCheck,
  FileStack,
  FolderLock,
  Gauge,
  LineChart,
  Network,
  Presentation,
  Radar,
  Rss,
  ScrollText,
  Settings2,
  SlidersHorizontal,
  Users,
  type LucideIcon,
} from "lucide-react";

/** One screen of the operator cockpit (§9). `phaseKey` is looked up in /v1/meta.feature_phases. */
export interface ScreenDef {
  id: string;
  path: string;
  title: string;
  icon: LucideIcon;
  permission: string;
  phaseKey: string;
  group: NavGroup;
  layer: string;
  summary: string;
  capabilities: string[];
  keywords?: string[];
}

/** Navigation follows the OCIF cognitive loop: perceive → represent/remember → reason → act → govern. */
export type NavGroup = "Overview" | "Perceive & Represent" | "Remember & Reason" | "Act" | "Govern";
export const NAV_GROUPS: NavGroup[] = ["Overview", "Perceive & Represent", "Remember & Reason", "Act", "Govern"];

export const SCREENS: ScreenDef[] = [
  {
    id: "command-center", path: "/", title: "Command Center", icon: Gauge, permission: "dashboard:read",
    phaseKey: "screen.command_center", group: "Overview", layer: "L5/L8 · FR-07",
    summary: "Executive view of cash, burn, runway, and the probability-weighted pipeline.",
    capabilities: ["KPI tiles: cash, net burn, runway + zero-cash date, weighted pipeline, 90-day inflows",
      "Runway chart with base/downside/upside bands", "Pipeline funnel, class mix, geographic map",
      "Grant calendar strip, top-10 opportunities, risk alerts rail — every number drills to its source"],
    keywords: ["dashboard", "kpi", "home"],
  },
  {
    id: "board-reports", path: "/board", title: "Board Reports", icon: Presentation, permission: "board_report:read",
    phaseKey: "screen.board_reports", group: "Overview", layer: "L8",
    summary: "One-click board pack for a period: runway, pipeline, key opportunities, risks and asks.",
    capabilities: ["Generate pdf/pptx board pack", "Preview", "Approval before distribution", "Distribution log"],
  },
  {
    id: "radar", path: "/radar", title: "Opportunity Radar", icon: Radar, permission: "opportunity:read",
    phaseKey: "screen.radar", group: "Perceive & Represent", layer: "L2/L4 · FR-02/03",
    summary: "Every classified, scored capital opportunity across the 11 instrument classes.",
    capabilities: ["Synced table, Kanban-by-stage and map views", "Facets: class, geography, stage fit, band, deadline, completeness, owner",
      "Bulk assign / rescore / send to council / archive with reason"],
    keywords: ["opportunities", "pipeline", "kanban", "outreach", "first actions", "analyst priority"],
  },
  {
    id: "graph", path: "/graph", title: "Knowledge Graph", icon: Network, permission: "graph:read",
    phaseKey: "screen.graph_explorer", group: "Perceive & Represent", layer: "L2 · CKG",
    summary: "Explore the Capital Knowledge Graph with its provenance chain.",
    capabilities: ["Cytoscape canvas, node-type filters, expand-on-click", "Node inspector with DERIVED_FROM provenance",
      "Warm-intro path finder", "Entity merge review queue", "Admin-only read-only Cypher console"],
    keywords: ["ckg", "cypher", "entities", "merge"],
  },
  {
    id: "sources", path: "/sources", title: "Sources & Ingestion", icon: Rss, permission: "ingestion:read",
    phaseKey: "screen.sources", group: "Perceive & Represent", layer: "L1 · FR-01",
    summary: "Adapter registry, health and the dead-letter queue.",
    capabilities: ["Adapters with health, last run, items/run, errors", "Enable/disable and run now",
      "DLQ viewer with replay", "Terms-of-use note per source"],
    keywords: ["adapters", "dlq", "rss", "csv", "xlsx", "upload", "outreach workbook", "sheet"],
  },
  {
    id: "relationships", path: "/relationships", title: "Relationships", icon: Users, permission: "relationship:read",
    phaseKey: "screen.relationships", group: "Remember & Reason", layer: "L3 · FR-04",
    summary: "Relationship intelligence: warmth, timelines, follow-ups and commitments.",
    capabilities: ["Contacts and investors with warmth sparkline", "Per-contact timeline", "Overdue-first follow-up queue",
      "Commitment tracker with expiry countdown", "Draft follow-ups go to the outbox, never sent directly"],
    keywords: ["contacts", "investors", "warmth", "crm", "outreach", "tracker", "eligibility", "gates", "workbook", "prospects"],
  },
  {
    id: "scoring", path: "/scoring", title: "Scoring Studio", icon: SlidersHorizontal, permission: "scoring:read",
    phaseKey: "screen.scoring_studio", group: "Remember & Reason", layer: "L4 · FR-03",
    summary: "Tune the Capital Opportunity Score with a live re-rank preview.",
    capabilities: ["Weight sliders with before/after rank deltas", "Optional factors and threshold editors",
      "Profile versioning, diff and activate (Admin)", "Backtest vs realised outcomes"],
    keywords: ["weights", "factors", "score"],
  },
  {
    id: "forecast", path: "/forecast", title: "Runway & Forecast", icon: LineChart, permission: "forecast:read",
    phaseKey: "screen.forecast_studio", group: "Remember & Reason", layer: "L5 · FR-07",
    summary: "Deterministic runway forecasting and scenarios. No placeholder numbers, ever.",
    capabilities: ["Import financials (CSV/XLSX) with mapping", "Scenario builder: hiring, burn delta, raise timing",
      "Cash curve, burn, inflows by class, runway comparison", "'Insufficient data' when inputs are missing"],
    keywords: ["runway", "burn", "cash", "scenario"],
  },
  {
    id: "calendar", path: "/calendar", title: "Grant Calendar", icon: CalendarDays, permission: "opportunity:read",
    phaseKey: "screen.grant_calendar", group: "Remember & Reason", layer: "L8 · FR-07",
    summary: "Deadlines, submission milestones and follow-ups on one calendar.",
    capabilities: ["Month, week and timeline views colour-coded by class", "Click through to the opportunity", "iCal export"],
    keywords: ["deadlines", "grants"],
  },
  {
    id: "council", path: "/council", title: "Agent Council", icon: Bot, permission: "agent:read",
    phaseKey: "screen.agent_council", group: "Act", layer: "L6 · SyRS §7",
    summary: "The 13-agent capital council, with live deliberation and citation checks.",
    capabilities: ["Roster: status, tier, runs, cost, success rate", "Run-task composer with budget",
      "Live SSE deliberation with cited claims", "Convergence panel with citation-check results", "Run history and traces"],
    keywords: ["agents", "llm", "deliberation"],
  },
  {
    id: "proposals", path: "/proposals", title: "Proposal Factory", icon: FileStack, permission: "proposal:read",
    phaseKey: "screen.proposal_factory", group: "Act", layer: "L8 · FR-05",
    summary: "Evidence-backed collateral: decks, memos, grant narratives and financial models.",
    capabilities: ["Package wizard", "Split editor with citation chips and an evidence panel",
      "[EVIDENCE REQUIRED] gaps block approval", "Version diff; export docx/pptx/xlsx/pdf"],
    keywords: ["deck", "pitch", "memo", "collateral"],
  },
  {
    id: "dataroom", path: "/dataroom", title: "Data Room", icon: FolderLock, permission: "dataroom:read",
    phaseKey: "screen.data_room", group: "Act", layer: "L8 · FR-06",
    summary: "Versioned documents, DD checklist mapping and package assembly.",
    capabilities: ["Folder tree, upload, versioning, approved-repo flag", "DD checklist with gap flags",
      "Package manifest with checksums", "Access log; approval-gated expiring share links"],
    keywords: ["documents", "diligence", "dd"],
  },
  {
    id: "alerts", path: "/alerts", title: "Alerts Center", icon: BellRing, permission: "alert:read",
    phaseKey: "screen.alerts", group: "Act", layer: "L8 · FR-08",
    summary: "New high-score opportunities, deadlines, follow-ups, runway risk and expiring commitments.",
    capabilities: ["Feed with severity, ack, snooze, assign", "Rule builder (condition + threshold + channel)"],
    keywords: ["notifications"],
  },
  {
    id: "approvals", path: "/approvals", title: "Approval Inbox", icon: ClipboardCheck, permission: "approval:read",
    phaseKey: "screen.approvals", group: "Govern", layer: "L7 · I3",
    summary: "Nothing leaves Capital Cortex without an explicit, MFA-verified human approval.",
    capabilities: ["Pending queue sorted by deadline", "Rendered preview and diff vs last approved",
      "Policy evaluation and citation-check report", "Approve / reject / request changes with step-up MFA",
      "Outbox: draft → pending → approved → sent/blocked"],
    keywords: ["approve", "outbox", "governance"],
  },
  {
    id: "audit", path: "/audit", title: "Audit & Compliance", icon: ScrollText, permission: "audit:read",
    phaseKey: "screen.audit", group: "Govern", layer: "L7 · §11/§12",
    summary: "Hash-chained, append-only record of every decision and sensitive read.",
    capabilities: ["Audit log search", "Hash-chain verification", "AI reasoning records per recommendation",
      "Retention and legal hold (Phase 3)", "Compliance report export (Phase 3)"],
    keywords: ["log", "hash", "verify", "compliance"],
  },
  {
    id: "admin", path: "/admin", title: "Admin", icon: Settings2, permission: "admin:read",
    phaseKey: "screen.admin", group: "Govern", layer: "L7/L8",
    summary: "Users and roles, policies, LLM router, budgets and taxonomy.",
    capabilities: ["Users/roles (Keycloak-synced) and MFA status", "OPA policies with test input",
      "LLM router tiers and providers", "Budgets and cost dashboard", "Taxonomy editor for the 11 classes"],
    keywords: ["users", "roles", "budget", "policy", "llm"],
  },
];

export const OBSERVABILITY_LINK = { title: "Platform health", icon: Activity };
