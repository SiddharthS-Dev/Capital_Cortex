# Inspironics Capital Cortex™ — Complete Platform Walkthrough

Narration script · English · 45 min 6 s · 52 scenes · 36 chapters

Voice: neural TTS (Kokoro, af_heart). Subtitles: burned in, plus `.srt` / `.vtt` sidecars. Chapters are embedded in the MP4.

## Introduction  [00:00]

### Capital Cortex™  [00:00]

Welcome to the complete platform walkthrough of Inspironics Capital Cortex, the autonomous capital intelligence and fundraising engine.

Over the next forty-five minutes, we will open every module, look inside each one, and follow exactly how a funding opportunity travels from first discovery to a human-approved submission.

Everything you will see comes straight from the platform's code, its configuration and its live screens.

### What we will cover  [00:28]

Here is our route. We start with the vision and the seven invariants that govern every design decision, then the OCIF architecture, the technology stack and the security model.

Next, we tour the operator cockpit, and then go layer by layer: perception, representation and the knowledge graph, reasoning and scoring, memory and relationships, and strategy and forecasting.

Then the thirteen-agent council, governance and trust, and the actuation layer with proposals, the data room, board reports and alerts.

We finish with administration, the platform core, one complete end-to-end journey, and the evidence of quality behind it all. Use the chapter markers in your player to jump to any section.

## Vision  [01:15]

### What Capital Cortex does  [01:15]

Raising capital is a full-time job hidden inside every growing company. Opportunities are scattered across grant portals, investor networks, inboxes and spreadsheets, and the best ones are easy to miss.

Capital Cortex continuously discovers these opportunities, classifies them, scores them against your organisation's profile, and helps your team pursue the strongest fits.

It covers eleven capital instrument classes: venture equity, private equity, strategic corporate venture, grants, government programs, university programs, and foundation and ESG funding.

Plus debt facilities, convertibles, equipment finance and revenue-based financing.

And one rule sits above everything else: nothing leaves the system without explicit human approval.

### Seven non-negotiable invariants  [02:05]

The whole platform is anchored on seven invariants. They are not guidelines in a prompt; wherever possible, they are enforced in code and in the database itself.

I1, no fabrication. Nothing is asserted without a traceable source. Every knowledge table has a database check that requires either a source reference or a declared inference. Missing data is shown as a gap, never guessed.

I2, explainability everywhere. Every recommendation stores its evidence, confidence and reasoning trail at the moment it is created. I3, governed actuation. Anything outbound goes through an outbox, with a signed approval bound to the exact content.

I4, zero trust. Every service re-checks authentication and authorisation at its own boundary. I5, provenance continuity. Provenance captured at intake survives unbroken all the way to the dashboard.

I6, the system learns only from realised outcomes, never from its own predictions. And I7, large language models never compute numbers. Scores, forecasts, runway and pipeline come from deterministic code; language models may only narrate them, with citations.

## OCIF Architecture  [03:23]

### OCIF — eight cognitive layers, one knowledge graph  [03:23]

The architecture is called OCIF, the Octagonal Cognitive Intelligence Framework. Eight cognitive layers sit around one shared Capital Knowledge Graph.

L1 Perception brings signals in. L2 Representation classifies them and writes them into the graph. L3 Memory keeps relationships and context over time.

L4 Reasoning computes the explainable score. L5 Strategic Intelligence handles the pipeline, runway forecasting and the Copilot. L6 Agency runs the thirteen-agent council.

L7 Governance and Trust is the gatekeeper: citations, policies, approvals and audit. And L8 Actuation and Experience delivers the API, the cockpit, proposals, the data room, board packs and alerts.

Crucially, realised outcomes flow back along the L8 to L1 edge, so every won or lost deal makes the next ranking smarter.

## Technology Stack  [04:24]

### Technology stack — a modular monolith  [04:24]

Technically, Capital Cortex is a modular monolith. One Python codebase runs both the FastAPI server and the background workers, with module boundaries enforced by import rules, so any module can be split out later without a rewrite.

Storage is a single Postgres 16 database, extended with Apache AGE for the graph and pgvector for embeddings. Redis Streams carries events between layers, and MinIO stores documents and cold data.

Keycloak provides login with multi-factor authentication, Open Policy Agent decides every authorisation request, and Vault holds the secrets.

OpenTelemetry sends traces, logs and metrics to Tempo, Loki, Prometheus and Grafana. The cockpit itself is React 18 with TypeScript, Vite and Tailwind, plus ECharts, Cytoscape and FullCalendar.

The whole stack starts with a single make up command, in about two minutes on a warm machine.

### Repository layout mirrors the architecture  [05:26]

The repository mirrors the architecture. Platform core holds the shared, domain-free plumbing: authentication, policy, audit, the event bus, the LLM router, the database helpers and observability.

The cortex package holds one sub-package per OCIF layer, from L1 perception to L8 actuation, plus the worker and the phase registry.

Apps web is the operator cockpit. Config holds the business rules as data: roles, Rego policies, the taxonomy, retention, adapters, agents, scoring profiles and document templates.

Alongside sit the Alembic migrations, the infrastructure definitions, four test suites, the evaluation gates and the documentation set, including a traceability matrix that links every requirement to code, screens and tests.

## Identity & Security  [06:20]

### Identity, roles & zero trust  [06:20]

Security starts with identity. Keycloak issues short-lived OpenID Connect tokens, and multi-factor authentication with time-based one-time passwords is required for administrators, approvers and auditors.

There are six roles. Admin, for the founder. Analyst, who works the pipeline, drafts collateral and runs agents. Approver, the human in the loop for anything outbound.

Auditor, with read-only oversight of every decision and the audit chain. Executive, for dashboards and board reports. And Service, for the platform's own workers.

On top of role-based access, attribute-based rules check ownership, document classification and capital class. Open Policy Agent decides on every request and fails closed, and approvals demand a fresh step-up MFA.

External content is always treated as data, never as instructions, which defends the agents against prompt injection.

## Operator Cockpit  [07:21]

### Live screen — Operator Cockpit  [07:21]

Let's open the operator cockpit. This is the app shell that frames every screen.

On the left, navigation is grouped by the cognitive loop: overview, perceive and represent, remember and reason, act, and govern.

Across the top: global search, with a Control K command palette to jump to any opportunity, investor, contact or action.

Then the LLM budget meter, showing today's spend against the daily cap, the approval inbox badge, the alerts bell, the Copilot button and the user and role menu.

The amber ribbon across the top marks demo data. Every synthetic record is flagged, so it can never be mistaken for real investors or programs.

Every page also carries a badge naming its OCIF layer and requirement, like L5 slash L8, FR-07 here, so you always know which part of the architecture you are looking at.

## L1 Perception  [08:18]

### L1 Perception — the ingestion pipeline  [08:18]

Now layer by layer, starting with L1, perception. Its job is to bring capital signals in, continuously, safely and with full provenance.

Each source is an adapter declared in a YAML file. Adding a source is configuration, not code: a key, a kind, a schedule, a rate limit, a field mapping and a terms-of-use note.

The ingestion worker fetches raw items and normalises each one into a standard Signal. Provenance is recorded for every item: the source, the URL, the fetch time, the adapter version and the raw object key.

Each signal is de-duplicated by a content hash, so fetching the same content twice inserts nothing. It is then published to the signals.raw stream for the next layer.

The worker is idempotent. It retries with exponential backoff and jitter, and poison messages go to a dead-letter queue that operators can inspect and replay.

Adapters honour robots.txt and rate limits, and the platform never scrapes networks whose terms forbid it. Only official APIs, user-authorised exports or manual entry.

### Twelve source adapters ship with the platform  [09:28]

Twelve adapter configurations ship with the platform. The Grants.gov public API is enabled out of the box, and templates exist for the EU Funding and Tenders portal and UKRI opportunities.

Files and people are covered too: CSV and Excel upload for investor lists, CRM exports and financials, plus manual entry. Generic RSS and HTML adapters handle feeds and listing pages.

For relationship data, there are read-only, opt-in adapters for an IMAP mailbox, Microsoft Graph mail and calendar, and ICS calendar feeds.

And a data-room folder watcher registers new documents from object storage as unapproved, because approving a document for packages is always a human decision.

### Live screen — L1 Perception  [10:20]

This is the Sources and Ingestion screen: the adapter registry and its health.

Each row shows the source, its kind, and the terms-of-use note that explains what the platform is allowed to do with that source.

Health, schedule, last run and items per run come next. Grants.gov is healthy, runs every six hours, and its last run fetched one hundred twenty-four items: thirty-three new and ninety-one duplicates.

Operators can run any adapter now, enable or disable it, or upload a file. Errors are counted on the run without stopping it, and a dead-letter queue viewer lets a failed message be replayed.

### Knowledge check: Grants.gov returns the same program twice in one day. What does the ingestion worker do?  [11:01]

Quick check. Grants.gov returns the same program twice in one day. What does the ingestion worker do? Pause the video if you'd like to think about it.

The answer: it inserts nothing. The content hash already exists, so the duplicate is counted and skipped, and the first signal's provenance stays intact.

## Data Model  [11:26]

### What the platform stores  [11:26]

What does the platform actually store? Every table carries an organisation ID, so the platform is ready for multi-tenancy or federation later. Core knowledge tables include sources, signals, organisations, investors, funds, grant programs, financial instruments and opportunities.

Each opportunity holds its class, counterparty, amount band, deadline, pipeline stage, score, factors and completeness. Relationship tables hold contacts, meetings, relationships and milestones; execution tables hold documents, proposals, approvals, the outbox, alerts, financials, forecasts and outcomes.

The same knowledge lives in the graph, with seventeen node types and edges such as INVESTS IN, KNOWS, INTRODUCED and SUPPORTS. One edge is mandatory on every derived node: DERIVED FROM, the provenance link. Embeddings sit beside it in pgvector.

For demonstrations, a synthetic seed creates about three hundred fictional investors, one hundred twenty grant programs, six hundred opportunities across twenty-five countries, eighteen months of financials and eighty realised outcomes. Every row is flagged as demo, and one command purges it all.

## L2 Representation  [12:43]

### L2 Representation — rules-first classifier  [12:43]

Layer two, representation, turns signals into structured knowledge. It starts with the capital-class classifier, which is rules first, driven by the taxonomy file.

Each of the eleven classes collects points. A class hint from the source gives three points, or two if it is only the source's default. A keyword in the title gives one and a half, and in the description, zero point seven five.

A matching investor type adds two points, and a matching counterparty kind adds one and a half.

Then two ratios. Share is the top score divided by the top plus the runner-up. Coverage is the top score divided by four, capped at one. Confidence equals share times, zero point five plus zero point five times coverage.

Below zero point seven, a small language model may be consulted, but only if one is configured and within budget. On the labelled set, the rules alone reach ninety-seven point six percent accuracy, and a class set by a human is never overwritten.

### Entity resolution & graph writing  [13:49]

Next, the entity resolver decides whether a counterparty is an organisation we already know. Names are normalised by removing legal suffixes such as Inc, LLC or GmbH.

Candidates are blocked by trigram name similarity, exact domain and compatible country, then scored with Jaro-Winkler similarity. An exact domain match scores one, and conflicting countries are penalised.

At zero point nine two or above, records merge automatically. Between zero point eight and zero point nine two, a new record is created and the pair is queued for human review. Below that, it is a new organisation. Every merge is reversible and audited.

The typer then applies sector, ESG, SDG and geography tags, and the graph writer creates vertices, edges and relational mirrors in one transaction, with a DERIVED FROM edge from every node back to its source signal.

Each opportunity is also embedded with a local, deterministic hashing model, so technology similarity works without any external AI service.

### Live screen — L2 Representation  [15:00]

Here is the Capital Knowledge Graph explorer. This demo graph holds two thousand four hundred twenty-two nodes and two thousand five hundred thirty-one edges.

You choose a starting node type and a layout, and filter by node type: organisations, opportunities and signals.

Click a node to inspect its attributes and its provenance chain. Double-click expands its neighbours, and dashed edges are provenance links back to the original signals.

On the right, the path finder searches for warm-introduction paths of up to four hops, through people we know and people who introduced us.

Below sits the entity merge review queue, with side-by-side comparison and merge or unmerge. Administrators also get a read-only Cypher console for direct graph queries.

## Opportunity Radar  [15:49]

### Live screen — Opportunity Radar  [15:49]

Classified opportunities land in the Opportunity Radar: every scored opportunity across the eleven instrument classes. Seven hundred twenty-four in this demo.

Faceted filters on the left narrow by capital class, score band, pipeline stage and geography, each with live counts.

The table shows score, opportunity and counterparty, class, band, evidence completeness and amount. Bands carry both colour and a text label, so colour is never the only signal.

Switch to Kanban, and the same opportunities are arranged by pipeline stage. Dragging a card changes its stage, and the change is audited.

There is also a map view, saved views and a column picker, plus bulk actions to assign, rescore, send to the council, or archive with a reason.

And every screen supports light and dark themes.

## L4 Reasoning  [16:43]

### L4 Reasoning — the Capital Opportunity Score  [16:43]

Layer four, reasoning, computes the Capital Opportunity Score. It uses no language model at all. Every factor is a deterministic or machine-learned plugin that returns a value between zero and one, its evidence and its method.

The score is the sum of each factor's weight times its value, divided by the sum of the weights, but only over factors that actually have evidence. Missing factors are never imputed.

Completeness is the weight of the available factors divided by the total weight. It tells you how much of the picture is actually supported by evidence.

The default weights: strategic fit zero point one five, probability of success zero point one three, technology alignment, stage and relationship strength zero point one two each, funding size and timing zero point one zero, geography and ESG relevance zero point zero eight.

Bands: zero point seven or above is high fit, sent to the council and human review. Zero point four five to zero point seven is watchlist. Below that, archive, with a reason.

If completeness is under sixty percent, the band is insufficient evidence, and the opportunity cannot be routed above watchlist. A hard gate, such as an ineligible geography for a grant, forces archive.

### Factor formulas (1 of 2)  [18:08]

Now the individual factors. Strategic fit counts how many of your strategic priorities appear in the opportunity, divided by the smaller of three and the number of priorities.

Technology alignment uses a local, deterministic embedding called hash TF ten twenty-four: word unigrams and bigrams, hashed into ten twenty-four dimensions, log weighted and normalised. The cosine similarity is divided by zero point three five and capped at one.

Geography scores one for an eligible country, zero point six for the same region, and zero otherwise. For grants and government programs, ineligibility is a hard gate.

Stage uses a distance matrix: the same stage scores one, one step apart zero point six, two steps zero point two, and three or more zero.

### Factor formulas (2 of 2)  [19:02]

Funding size compares your raise target with the opportunity's amount band on a log ten scale. If the bands overlap, the value is zero point five plus half the overlap divided by the narrower width, capped at one. Touching bands give zero point five, and one decade apart gives zero.

ESG relevance is the Jaccard similarity of tags: the intersection divided by the union. Relationship strength is the maximum warmth across contacts at the counterparty.

Timing is a piecewise curve on days to deadline. A passed deadline scores zero, within a week zero point two, two weeks zero point five, a month zero point eight, the sweet spot of up to one hundred twenty days scores one, up to a year zero point seven, and beyond that zero point five.

Probability of success comes from a calibrated machine-learning model when one exists, otherwise from a class prior, such as eight percent for venture equity or thirty-five percent for debt, clearly labelled as a prior.

### ML scorer — calibrated probability of success  [20:07]

The machine-learning scorer trains only on realised outcomes. Won is one and lost is zero. Withdrawn is excluded, because it says nothing about the counterparty's decision.

Features are the other factor values with explicit missing indicators, the capital class and the log of the amount. Two candidates, logistic regression and histogram gradient boosting, are calibrated and compared by five-fold cross-validated Brier score.

The winner is tested on a temporal holdout of the newest twenty percent of outcomes, and it is promoted only if it beats the current model on AUC or Brier score.

It needs at least thirty outcomes and retrains weekly. And a model trained on demo data never scores real opportunities.

### Knowledge check: An opportunity has evidence for only half of its total factor weight. Which band does it get?  [20:55]

Quick check. An opportunity has evidence for only half of its total factor weight. Which band does it get?

Insufficient evidence. With completeness below sixty percent, the platform refuses to rank it as if the missing half did not matter, and it cannot be routed above watchlist.

## Opportunity Detail  [21:18]

### Live screen — Opportunity Detail  [21:18]

This is how the score looks to a user, on the opportunity detail screen.

The header shows class, band, demo flag and stage, then the counterparty, amount band and a live deadline countdown: one hundred days here.

On the right, the rank gauge, and the evidence completeness ring at seventy-eight percent.

The action bar lets you change stage, override the class manually, rescore, run the council, log a meeting, record an outcome, or generate a package.

The factor breakdown shows a bar for every factor, with its weight and method: rule, matrix, hash embedding, log band, piecewise, or machine learning.

Click a factor to open its evidence. Here, probability of success comes from a calibrated gradient-boosting model, with its model ID.

Factors without evidence appear as dashed bars labelled no evidence, rather than a guessed value. And the radar chart gives the shape of the fit at a glance.

Further down, tabs cover evidence and sources, the graph neighbourhood, relationships and warm-intro paths, agent recommendations with their reasoning trail, proposals, and the activity log.

## Scoring Studio  [22:30]

### Live screen — Scoring Studio  [22:30]

Scoring is configurable in the Scoring Studio. The organisation profile sets sectors, ESG and SDG tags, target geographies, the raise target, and a description used for technology alignment.

Weight sliders for every factor sit on the left. The three optional factors from the reference design, thesis match, cost and dilution, and strategic value, are available at weight zero.

Move a slider, and the live re-rank preview on the right shows the new order with rank-change arrows, without saving anything.

Profiles are versioned. An administrator can diff and activate a profile, which triggers a batch rescore, and a backtest panel compares score bands with realised outcomes.

## L3 Memory  [23:17]

### L3 Memory — relationship warmth  [23:17]

Layer three is memory and relationships. Its signature metric is warmth: how strong our relationship with a counterparty really is, right now.

Each interaction contributes its weight times e to the power of minus days elapsed over ninety. A meeting weighs one, an introduction zero point eight, a call zero point seven, an email reply zero point four, a sent email zero point one, and internal notes zero.

The total is normalised with one minus e to the minus S, giving a value between zero and one. A single meeting today gives about zero point six three, and it fades as the weeks pass.

When warmth changes, that counterparty's opportunities are rescored automatically, because relationship strength is one of the scoring factors.

Memory itself is tiered: hot in Redis for hours, warm in Postgres for months, cold in object storage. A nightly consolidation job writes a sourced reflection for every counterparty, and commitments become milestones that expire on a timer.

### Live screen — L3 Memory  [24:24]

The Relationships screen brings this to life, with tabs for contacts, the follow-up queue and the commitment tracker.

Each contact shows role, organisation, warmth from zero to one hundred, a twelve-week trend sparkline, last touch, interaction count and open milestones.

Here, Lio Umber at Lumara Beacon Foundation has warmth ninety-two after five interactions, with the last touch one day ago.

Log an interaction, log a meeting or add a contact in one click. Contact emails are masked, and a follow-up email draft goes to the outbox, never directly to the recipient.

## L5 Strategy  [25:04]

### L5 Strategy — weighted pipeline & runway  [25:04]

Layer five is strategic intelligence. First, the weighted pipeline: the sum of each opportunity's mid amount times its probability, split by class, stage, geography and month, and summed per currency without silent conversion.

The probability comes from the calibrated model when available, otherwise from the stage: discovered five percent, qualified ten, engaged twenty, submitted thirty, diligence forty-five, term sheet seventy, and committed ninety.

The runway forecast is fully deterministic. Burn is the trailing three-month average net burn. Each month, cash equals the previous cash, minus burn adjusted by the scenario, minus planned hires, plus expected inflows: amount times probability times the scenario multiplier.

Runway is the number of months until cash falls below the minimum buffer, and inflows land after a class-specific decision lag, for example six months for grants.

Three presets ship: base, a downside with twenty percent more burn, half the probability and a two-month delay, and an upside. With no financial data, the engine returns insufficient data, never a placeholder number.

## Command Center  [26:20]

### Live screen — Command Center  [26:20]

All of this surfaces in the Executive Command Center. A live indicator shows updates streaming in as sources are ingested.

Seven KPI tiles: cash, monthly net burn as a trailing three-month average, runway, the probability-weighted pipeline, expected inflows over ninety days, active opportunities and pending approvals.

Below, the runway chart plots base, downside and upside scenarios, each with a data-table fallback for accessibility.

And the risk rail lists open alerts, such as deadlines two and seven days out. Every tile drills down to its source records.

## Runway & Forecast  [26:59]

### Live screen — Runway & Forecast  [26:59]

In Runway and Forecast, the financial snapshots table shows each month's cash, revenue, opex and net burn, with the source of every row.

Scenario cards compare runway for base, downside, upside and a custom scenario.

The scenario builder adjusts burn change, the inflow probability multiplier, inflow delay, a raise with amount, month and probability, and a hiring plan.

You can even override the probability of individual expected inflows, and the cash curve redraws instantly. Nothing is saved to the server unless you choose to.

## Capital Copilot  [27:37]

### Live screen — Capital Copilot  [27:37]

The Capital Copilot is a drawer available on every page. Here we ask: what is our probability-weighted pipeline?

It retrieves with full-text and vector search, routes the question to deterministic tools, and answers with facts. Each fact carries citation chips pointing to the tool run and the configuration it used.

Suggested prompts adapt to context, like: what happens to runway if the top grant slips three months?

Every claim passes the citation checker. If nothing survives, the Copilot says it does not have sourced evidence, and lists exactly what is missing.

## Grant Calendar  [28:15]

### Live screen — Grant Calendar  [28:15]

The Grant Calendar puts every deadline, submission milestone, follow-up and commitment on one calendar.

Colour shows the capital class; icons and labels show the event type, and overdue items are flagged in red.

Month, week and agenda views are available, and the whole calendar exports to iCal for internal users.

## L6 Agency  [28:38]

### L6 Agency — the 13-agent capital council  [28:38]

Layer six is agency: a council of thirteen specialist agents, each declared in a YAML file with its role, goal, tools, model tier, triggers, token budget and output schema.

Discovery triages new signals. Grant handles eligibility and packaging. Venture Capital matches fund theses. Private Equity covers growth rounds. Debt covers facilities, equipment finance and revenue-based financing. Convertible models SAFEs and notes.

Government Programs and University Programs cover public schemes and research partnerships. Relationship tracks warmth, intro paths and follow-ups.

Proposal drafts collateral. Due Diligence maps the data room against the checklist. Forecasting narrates runway using only forecast engine results. And Board Intelligence produces the board-ready synthesis.

### LangGraph orchestrator & concurrency governor  [29:33]

A LangGraph orchestrator runs each council. It plans which agents match the opportunity's class, stage and band, then fans them out.

The concurrency governor allows at most four agents in parallel, with a per-task token ceiling and a daily dollar budget. When a limit is hit, it degrades gracefully and returns partial results clearly marked incomplete.

Positions are collected and converged with a confidence-weighted tally. Then every claim goes through the citation checker and policy evaluation before anything reaches the approval queue.

Agent tools are deterministic and read-only, or internal-write at most. Confidence is computed, never generated: the share of claims that passed the citation check, times evidence completeness. External actions can only ever create an outbox draft.

And every call writes an agent run record, with tokens, cost, model tier and trace ID.

## Agent Council  [30:33]

### Live screen — Agent Council  [30:33]

In the Agent Council screen, the roster shows all thirteen agents, with status, tier, runs today, cost, success rate, budget and their declared tools.

This environment has no language model key configured, so the banner states clearly that agents run in deterministic mode: every claim comes straight from a tool result.

Switch to Deliberation, choose an opportunity, and run the council. Here, five agents responded for an equipment finance opportunity: Debt, Due Diligence, Forecasting, Proposal and Relationship.

Each agent column streams its position live: the tools it called, the facts and gaps it found, a computed confidence, and the citation-check result.

Where evidence is missing, the agent says so. The Due Diligence agent flags that the data room is empty, as an explicit evidence-required gap.

## L7 Governance  [31:28]

### L7 Governance — the citation checker  [31:28]

Layer seven, governance and trust, is where the platform earns its credibility. Its first gate is the citation checker, applied to every claim from an agent, the Copilot or a proposal.

Rule one: every claim must cite something, and inferences must declare their basis. Rule two: every reference must resolve to a real record that the requesting user is allowed to see.

Rule three: every number in the text must match a number in the cited records within half a percent, and dates must match exactly. Rule four: any organisation-like name, such as something Fund or something Capital, must appear in a cited record, so no investor can ever be invented.

Failures go back for at most two revisions. Anything still failing is stripped and surfaced as a gap, and rejections are metered, so a spike raises a data-quality alert.

### Signed approvals & the outbox  [32:23]

Now governed actuation. When something needs to leave the system, an approval request is bound to the SHA-256 hash of its exact content.

Every decision requires step-up multi-factor authentication, and by default the requester cannot approve their own request.

Rego policies decide when approvals are sufficient. Outbound items need a human approval. Grant submissions need two approvers. Anything with financial terms, like a valuation, a cap or covenants, needs an admin and legal. And exporting personal data is denied.

Only then is a signed, single-use token issued. If anyone edits the content afterwards, the hash changes, and a database trigger invalidates the approval.

The outbox sender is the only path to the outside world. It verifies the token's signature, expiry and single use, re-hashes the payload, re-evaluates policy, and only then delivers, auditing everything in the same transaction.

## Approval Inbox  [33:28]

### Live screen — Approval Inbox  [33:28]

In the Approval Inbox, pending items are sorted by soonest deadline, with content flags like financial terms or personal data, and the citation result.

The detail pane shows a rendered preview of the exact content: here, an outbound email.

Below it, the changes since the last approved version, and the policy evaluation, which states exactly which requirement is still outstanding.

The Outbox tab shows the outbound pipeline: draft, pending, approved, sent and blocked. An approved item can be sent; editing it starts a new review.

## Compliance & Audit  [34:05]

### Knowledge check: An approver signs off an email. Then an analyst fixes a typo in it. What happens?  [34:05]

Quick check. An approver signs off an email, and then an analyst fixes a typo in it. What happens?

The approval is invalidated. The content hash no longer matches, so the database trigger clears the approval, and the outbox will refuse to send until a new review is complete.

### Compliance, audit chain & retention  [34:29]

Before any collateral leaves, a compliance check scans it. Guarantees or risk-free claims are blockers. Forward-looking statements require the disclaimer. Superlatives need cited support, return projections need legal review, and personal contact data needs a consent basis.

Every important action is written to a hash-chained audit log. Each entry's hash is the SHA-256 of the previous hash plus the canonical JSON of the entry, and a database trigger blocks updates, deletes and truncation.

Retention is configuration: the audit log is kept seven years and is immutable; signals move to cold storage after two years; hot memory lasts twenty-four hours; drafts expire after a year. And legal hold always wins over retention.

### Live screen — Compliance & Audit  [35:21]

The Audit and Compliance screen puts all of this in the auditor's hands.

Press verify chain, and the platform recomputes every hash across the whole log. Result: chain intact, four hundred seventy-five records.

A compliance report for any period exports to Excel, covering chain status, approvals, external releases, legal holds, retention runs and admin changes. The export itself is audited.

And retention policies can be dry-run or run now, with each policy's retention period, tier, action and immutability on display.

## L8 Actuation  [35:59]

### L8 Actuation — the Proposal Factory  [35:59]

Layer eight, actuation and experience, is where the work turns into deliverables. The Proposal Factory builds evidence-backed collateral from the knowledge graph.

There are four package types: a VC pitch, a grant application, a debt facility and an ESG impact memo. Each package defines its sections and its artefacts.

Eight artefacts in all: pitch deck, executive summary, investment memo, grant narrative, budget, a financial model with live Excel formulas, technical annex and due-diligence checklist, in Word, PowerPoint, Excel and PDF.

Every claim carries a numbered citation, and every artefact ends with an evidence appendix. Anything unsupported is rendered as evidence required, which blocks approval until it is resolved, or waived by an admin with an audit record.

## Proposal Factory  [36:53]

### Live screen — Proposal Factory  [36:53]

The proposal list shows each package with its type, status, version, open gaps, compliance result and generation mode. The drafts with twelve open gaps cannot be submitted yet.

Open a package, and the editor shows status, version, compliance and the content hash, with submit for approval and send.

The section outline on the left tracks completion. The centre shows each claim marked as fact, with its citation chips.

And the evidence panel lists every reference cited in the section, alongside any compliance findings. Versions and exports have their own tabs, with a diff between versions.

## Data Room  [37:33]

### Live screen — Data Room  [37:33]

The Data Room stores versioned documents in object storage, with folders, drag-and-drop upload, DD tags and classification.

The due-diligence checklist maps documents to ten standard items by their tags: incorporation, cap table, financials, financial model, pitch deck, IP, contracts, team, ESG and compliance.

An item counts as covered only when a mapped document is in the approved repository. Here, two of ten are covered, and the rest are flagged as evidence required.

Assemble package builds a package from approved documents only, with a checksum manifest and an access log. Share links expire, and creating one itself requires approval.

## Board Reports  [38:19]

### Live screen — Board Reports  [38:19]

Board Reports generates a one-click board pack for any period, with runway, pipeline, weighted funding, key opportunities, risks and asks.

It is built deterministically from the period's records. Every statement is cited, and anything without evidence is listed as a gap, rather than filled in.

Each pack shows its compliance result and distribution status. Distribution waits for approval, like everything else that leaves the platform.

## Alerts Center  [38:49]

### Live screen — Alerts Center  [38:49]

The Alerts Center is driven by a deterministic rule engine. Here, sixty-seven open alerts: six critical, fifty-seven warnings and four informational.

Five default rules: a new high-score opportunity within twenty-four hours, deadline countdowns at thirty, fourteen, seven and two days, overdue follow-ups, runway below nine months, and commitments expiring within fourteen days.

Each alert can be acknowledged, snoozed, assigned or resolved. Alerts go in-app, to internal email or to a webhook, and never directly to external recipients.

## Administration  [39:27]

### Live screen — Administration  [39:27]

Administration lives in one place. Users and roles are synced from Keycloak, with MFA status for each user.

Tabs cover OPA policies, which can be viewed and tested with sample input, the LLM router tiers and providers, budgets and cost, the taxonomy editor and extension flags.

Budgets and cost shows today's spend against the daily cap, here twenty-five dollars, with per-feature caps for classification, compliance, the Copilot, council deliberation and convergence, extraction, narration and proposals.

When a cap is reached, agents fall back to deterministic mode instead of spending more. And every admin change is audited.

## Platform Core  [40:12]

### Platform core — shared, domain-free foundations  [40:12]

Underneath every layer sits platform core: shared foundations, free of domain logic.

The LLM router is vendor neutral, with small, mid and large tiers mapped to Anthropic, Azure OpenAI or self-hosted vLLM. Every call checks a content-hash cache, pre-checks the budget, calls the provider and records the actual spend.

Cost discipline is built in: scoring uses no LLM at all; extraction and classification use the small tier; deliberation small to mid; and only convergence uses the large tier.

The event bus uses Redis Streams with consumer groups, retries with backoff and jitter, a dead-letter queue, idempotency markers, and a signed actor token on every envelope.

Observability ties it together: OpenTelemetry traces across the API, bus, workers and agents, with SLO alerts for latency, queue depth, budget breaches and spikes in unsourced-claim rejections.

## End-to-End Journey  [41:15]

### One opportunity, end to end  [41:15]

Let's put it all together, and follow one opportunity from start to finish.

A Grants.gov run fetches a new program. It is normalised into a signal, tagged with provenance, de-duplicated and published to the stream.

The worker classifies it as a grant, resolves the agency, writes it into the graph and scores it. It lands in the high band, the Radar updates live, and an alert is raised.

The council convenes. The Grant, Relationship and Forecasting agents respond, every claim is checked against its citations, and a recommendation lands in the approval queue.

An analyst generates the grant package. Evidence gaps are resolved, compliance is clean, and two approvers sign off with step-up MFA, as policy requires for grants.

The outbox verifies the token and the hash, and releases the submission. Months later, the outcome is recorded as won, and that realised outcome retrains the model. The loop is closed.

## Quality & Proof  [42:18]

### Quality gates & load proof  [42:18]

How do we know it works? Quality is enforced by a pipeline of gates. The closing run passed one hundred eighty-nine unit tests, twenty-one integration tests on the real database image, twenty-four of twenty-four policy tests, and seven end-to-end browser tests.

Contract testing generated over two thousand one hundred API cases from the OpenAPI spec, and six evaluation gates guard no fabrication, grounding, classification accuracy and scoring sanity.

A load test on a one-million-node knowledge graph passed at team traffic with zero errors: dashboard ninety-fifth percentile one point eight seven seconds against a three-second target, the list at one point zero eight seconds, graph neighbourhood one hundred forty-three milliseconds, paths ninety-one milliseconds, and rescoring one hundred forty-eight milliseconds.

Security scans with Trivy and OWASP ZAP closed every critical and high finding, an authorisation matrix tests every role against every endpoint, and the backup drill achieved a recovery point under fifteen minutes and a recovery time of seconds.

## Delivery & Roadmap  [43:30]

### Delivered in four phases  [43:30]

The platform was delivered in four phases, each ending in a working demo and a green pipeline.

Phase zero, platform core: the full stack, authentication with MFA, the audit chain, the bus, the LLM router, the schema and the React shell.

Phase one: discovery, the knowledge graph and explainable scoring, with live Grants.gov data and real-time updates. Phase two: memory, relationships, the agent council and governed actuation.

Phase three: the Proposal Factory, data room, board reports, Copilot, compliance, retention and administration, plus the hardening work on load, security and recovery.

Six extension points are already defined as interfaces behind feature flags: a negotiation assistant, a portfolio optimiser, a scenario planner, a finance digital twin, an ecosystem mapper, and Cortex federation for exchanging events with other Inspironics cortexes.

## Recap  [44:32]

### outro  [44:32]

To recap. Capital Cortex discovers opportunities from many sources, classifies and resolves them into a knowledge graph, and scores them with transparent formulas.

A council of agents deliberates with cited evidence, every outbound action goes through signed human approval, and realised outcomes retrain the model.

Every number is computed. Every claim is cited. And nothing leaves without approval. Thank you for watching Inspironics Capital Cortex.
