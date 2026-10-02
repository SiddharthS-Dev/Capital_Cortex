# Capital Cortex — Project Explanation Video: Narration Script

## 01. Inspironics Capital Cortex™  [00:00]

Welcome. This video is a complete walkthrough of Inspironics Capital Cortex. We will cover what the system does, how it is built, every major module, the types of data it uses, the exact formulas implemented in the code, and how a funding opportunity travels from discovery all the way to a human-approved submission.

## 02. What Capital Cortex is  [00:19]

Capital Cortex is an autonomous capital intelligence and fundraising engine. It continuously discovers funding opportunities, classifies them, scores them against your organisation's profile, and helps your team pursue the best ones. It covers eleven capital instrument classes: venture equity, private equity, strategic corporate venture, grants, government programs, university programs, foundation and E S G funding, debt facilities, convertibles, equipment finance, and revenue based financing. And one rule sits above everything: nothing leaves the system without human approval.

## 03. Seven non-negotiable invariants  [00:55]

The whole design is anchored on seven invariants, enforced in code and in S Q L wherever possible. I one, no fabrication: missing data is shown as a gap, never guessed. I two, explainability everywhere. I three, governed actuation: anything outbound goes through an outbox with signed approvals bound to the exact content. I four, zero trust. I five, provenance continuity: every derived record links back to the signal it came from. I six, the system learns only from real, realised outcomes. And I seven, large language models never compute numbers. They may narrate, but every figure comes from deterministic code.

## 04. OCIF: eight cognitive layers around one knowledge graph  [01:35]

The architecture is called O C I F, the Octagonal Cognitive Intelligence Framework. It has eight layers arranged around a shared Capital Knowledge Graph. Layer one, perception, brings data in. Layer two, representation, classifies it and writes it into the graph. Layer three is memory and relationships. Layer four is reasoning, where scoring happens. Layer five is strategy: pipeline, forecasting and the copilot. Layer six is agency, the council of thirteen agents. Layer seven is governance. And layer eight is actuation and experience: the A P I, proposals, data room, board reports and alerts. Realised outcomes feed back from layer eight to layer one, so the system keeps learning.

## 05. Technology stack: a modular monolith  [02:18]

Technically, it is a modular monolith. One Python codebase runs both the Fast A P I server and the background workers. Storage is a single Postgres sixteen database, extended with Apache A G E for the graph and P G vector for embeddings. Redis Streams carries events between layers. Min I O stores documents. Keycloak handles login with multi factor authentication, O P A evaluates policies, and Vault holds secrets. Open Telemetry sends traces, logs and metrics to Tempo, Loki, Prometheus and Grafana. The cockpit is React eighteen with Vite and Tailwind. In the code, platform core holds the domain-free plumbing, and the cortex package holds one sub-package per O C I F layer.

## 06. End-to-end flow of one opportunity  [03:00]

Here is the full journey of one opportunity. A source adapter fetches raw items. Each item is normalised into a signal, with provenance recorded for every field. It is de-duplicated by a content hash, so re-fetching the same content inserts nothing. The signal is published to the signals dot raw stream. A worker consumes it, classifies the capital class, resolves the counterparty organisation, writes everything into the knowledge graph, scores it on twelve factors, assigns a band, and pushes a live event to the user interface. From there, high-fit opportunities can go to the agent council, which can produce a draft, which waits for human approval before the outbox may send it.

## 07. L1 Perception: bringing data in  [03:39]

Layer one is perception. Each source is an adapter configured declaratively in YAML. The supported sources include the Grants dot gov public A P I, E U Funding and Tenders, C S V and Excel uploads, manual entry, R S S feeds, H T M L pages, an IMAP mailbox, Microsoft Graph mail and calendar, I C S calendars, and a data room folder watcher. The ingestion worker fetches, normalises, de-duplicates by content hash, records provenance and publishes the signal. It is idempotent, and items that fail to normalise are counted on the run without stopping it. The Sources screen shows every adapter and its run history.

## 08. What types of data the system uses  [04:19]

What kind of data does the system work with? Opportunities, with title, description, amounts, currency, deadline, geography, sectors, stage fit, E S G tags and terms. Organisations, including your own profile, investors, funds and grant programs. Relationship data: contacts, meetings, introductions, calls, emails and commitments. Monthly financial snapshots of cash, revenue, operating expense and net burn. Realised outcomes, which are the labels for machine learning. Data room documents. And governance records. For demonstrations, a synthetic dataset is generated: about three hundred fictional investors, one hundred twenty grant programs, six hundred opportunities across twenty five countries, eighteen months of financials and eighty realised outcomes. Every demo row is flagged, and the interface shows an amber demo data ribbon, so synthetic data is never mistaken for real.

## 09. Capital-class classifier (rules first)  [05:15]

Layer two starts with the classifier, which is rules first. Each class collects points. A class hint from the source gives three points, or two if it is just the source's default. A keyword in the title gives one and a half points, a keyword in the description gives zero point seven five, a matching investor type gives two, and a matching counterparty kind gives one and a half. Share is the top score divided by the top plus the runner up. Coverage is the top score divided by four, capped at one. Confidence equals share times, zero point five plus zero point five times coverage. If confidence is below zero point seven, a small language model may be consulted, but only if one is configured and within budget. A class set by a human is never overwritten.

## 10. Entity resolution and the Capital Knowledge Graph  [05:59]

Next, entity resolution decides whether a counterparty is an organisation we already know. Names are normalised by removing legal suffixes like Inc, L L C or GmbH. Candidates are found by trigram similarity, exact domain, and compatible country. They are scored with Jaro Winkler similarity, an exact domain match scores one, and conflicting countries are penalised. A score of zero point nine two or above merges automatically. Between zero point eight and zero point nine two, a new record is created and the pair is queued for human review. Below that, it is a new organisation. Merges are reversible and audited. The graph writer then creates vertices and edges, and every derived node gets a derived from edge back to its source signal.

## 11. Capital Opportunity Score  [06:44]

Layer four is reasoning, and its core is the Capital Opportunity Score. The score is the sum of each factor's weight times its value, divided by the sum of weights, but only over factors that actually have evidence. Missing factors are not filled in. Completeness is the weight of available factors divided by the total weight. The default weights are: strategic fit zero point one five, probability of success zero point one three, technology alignment, stage and relationship strength zero point one two each, funding size and timing zero point one zero, geography and E S G relevance zero point zero eight. A score of zero point seven or more is high fit and goes to the council. Zero point four five to zero point seven is watchlist. Below that is archive. If completeness is under sixty percent, the result is insufficient evidence, and a hard gate, such as ineligible geography for a grant, forces archive.

## 12. The factor formulas (1 of 2)  [07:38]

Now the individual factors. Strategic fit counts how many of your strategic priorities appear in the opportunity, divided by the smaller of three and the number of priorities. Technology alignment uses a local, deterministic embedding called hash T F ten twenty four: word unigrams and bigrams, hashed into ten twenty four dimensions, log weighted and normalised. The cosine similarity is divided by zero point three five and capped at one. Geography scores one for an eligible country, zero point six for the same region, and zero otherwise, and for grants and government programs ineligibility is a hard gate. Stage uses a distance matrix: same stage one, one step apart zero point six, two steps zero point two, three or more zero.

## 13. The factor formulas (2 of 2)  [08:24]

Funding size compares your raise target with the opportunity's amount on a log ten scale. If the bands overlap, the value is zero point five plus half the overlap divided by the narrower width, capped at one. If they do not overlap, touching bands give zero point five, and one decade apart gives zero. E S G relevance is the Jaccard similarity of tags: the intersection divided by the union. Relationship strength is the maximum warmth you have with the counterparty. Timing is a piecewise curve on days to deadline: a passed deadline is zero, within a week zero point two, two weeks zero point five, a month zero point eight, the sweet spot of up to one hundred twenty days scores one, up to a year zero point seven, and beyond that zero point five. Probability of success comes from a calibrated machine learning model when one exists, otherwise from a class prior, such as eight percent for venture equity or thirty five percent for debt.

## 14. Explainable score on every opportunity  [09:17]

This is how it looks to the user. The opportunity detail screen shows the overall score and evidence completeness, then a bar for every factor with its weight and its method. Clicking a factor opens the evidence, here a calibrated gradient boosting model with its model I D. Factors without evidence are clearly shown as no evidence rather than a guessed value. That is invariant I two, explainability, in practice.

## 15. ML scorer: calibrated probability of success  [09:41]

The machine learning scorer predicts probability of success. It trains only on realised outcomes: won is one, lost is zero, and withdrawn is excluded because it says nothing about the counterparty's decision. Features are the other factor values with explicit missing indicators, the capital class, and the log of the amount. Two candidates, logistic regression and histogram gradient boosting, are calibrated with Platt scaling and compared by five fold cross validated Brier score. The winner is tested on a temporal holdout of the newest twenty percent of outcomes, and is promoted only if it beats the current model on A U C or Brier. It needs at least thirty outcomes, retrains weekly, and models trained on demo data never score real opportunities. The Scoring Studio lets users tune weights and thresholds.

## 16. Relationship warmth and memory tiers  [10:27]

Layer three is memory and relationships. Warmth measures how strong a relationship is. Each interaction contributes its weight times e to the power of minus days elapsed over ninety, so it decays over time. A meeting weighs one, an introduction zero point eight, a call zero point seven, an email reply zero point four, a sent email zero point one, and internal notes zero. The sum is then normalised with one minus e to the minus S, giving a value between zero and one. One meeting today gives about zero point six three. When warmth changes, that counterparty's opportunities are rescored. Memory itself is tiered: hot in Redis, warm in Postgres, and cold in Min I O, and a nightly job writes a deterministic reflection for every counterparty.

## 17. Weighted pipeline and runway forecast  [11:11]

Layer five is strategy. The weighted pipeline is the sum of each opportunity's mid amount times its probability, split by class, stage, geography and month, and summed per currency without conversion. The runway forecast is fully deterministic. Burn is the trailing three month average net burn. Each month, cash equals the previous cash, minus burn adjusted by the scenario, minus new hires, plus the expected inflows, which are amount times probability times the scenario multiplier. Runway is the number of months until cash falls below the minimum buffer, interpolated within the month. Inflows arrive after a class specific decision lag, for example six months for grants. Three presets are provided: base, a downside with twenty percent more burn, half the probability and a two month delay, and an upside. With no financial data, it returns insufficient data instead of a placeholder.

## 18. Capital Copilot: grounded Q&A  [12:06]

Also in layer five is the Capital Copilot, a question and answer assistant grounded in the knowledge graph. It retrieves with full text and vector search, routes the question to deterministic tools such as ranking explanation, warm introductions, runway what ifs, pipeline and deadlines, and then answers with citations. Every claim passes the citation checker. If nothing survives, it honestly replies that it does not have sourced evidence, and lists what is missing.

## 19. The 13-agent council  [12:33]

Layer six is agency. There are thirteen specialist agents, from discovery and venture capital to grants, debt, due diligence, relationships, forecasting, proposals and board intelligence. A LangGraph orchestrator plans which agents match the opportunity's class, stage and band, fans them out with at most four running in parallel, collects their positions and converges using a confidence weighted tally. Agent tools are deterministic and read only. Confidence is computed, never generated: it is the share of claims that passed the citation check, times the evidence completeness. If no language model is configured, agents run in deterministic mode and their claims come straight from tool facts, as you can see here.

## 20. Citation checker: the gate on every AI output  [13:16]

Layer seven is governance, and its first gate is the citation checker. Every claim from an agent, the copilot or a proposal must pass four rules. First, it must cite something. Second, every reference must resolve to a real record that the user is allowed to see. Third, every number in the text must match a number in the cited records within half a percent, and dates must match exactly. Fourth, any organisation-like name, such as something Fund or something Capital, must appear in a cited record, so no investor can be invented. Failures go back for at most two revisions, and anything still failing is stripped and shown as a gap.

## 21. Signed approvals and the outbox  [13:53]

Now, governed actuation. When something needs to go out, an approval request is bound to the S H A two fifty six hash of its exact content. Any later edit changes the hash, and a database trigger invalidates the approval. Every decision requires step up multi factor authentication, and the requester cannot approve their own request. O P A policies decide when approvals are sufficient, for example two approvers for a grant submission, or admin plus legal when financial terms are present. Only then is a signed token issued. The outbox sender is the only path to the outside world. It verifies the token, re-hashes the payload, re-evaluates policy, and only then delivers, all audited in the same transaction.

## 22. Tamper-evident audit, retention and compliance  [14:37]

Every important action is written to a hash chained audit log. Each entry's hash is the S H A two fifty six of the previous hash plus the canonical J S O N of the entry. A database trigger blocks updates and deletes, and a verify function recomputes the entire chain to detect any tampering. Retention rules keep the audit log for seven years, move signals to cold storage after two years, and expire drafts and caches. Legal hold always wins over retention. A compliance check also reviews outbound collateral for disclosure and forward looking statement issues before submission.

## 23. Proposals, data room, board packs and alerts  [15:11]

Layer eight is actuation and experience. The Proposal Factory builds eight artefacts, including a pitch deck, executive summary, investment memo, financial model with live Excel formulas, and due diligence checklist, in Word, PowerPoint, Excel and P D F. Every claim carries numbered citations and an evidence appendix, and anything unsupported appears as evidence required, which blocks approval. The data room stores versioned documents with a hash manifest and approval gated share links. Board reports build a one click pack of runway, pipeline, risks and asks. And a deterministic alert engine watches deadlines, milestones and runway.

## 24. The operator cockpit  [15:50]

All of this comes together in the operator cockpit: the command center with key metrics, the opportunity radar as a list or kanban board by pipeline stage, the grant calendar, the data room, board reports and the alerts center, alongside relationships, the knowledge graph explorer, the approval inbox, audit and admin screens.

## 25. Platform core: LLM router, event bus, security  [16:11]

Underneath sits platform core. The L L M router is vendor neutral, with small, mid and large tiers. Every call checks the cache, pre-checks the budget, calls the provider and records the actual spend, with daily budgets globally, per feature and per agent. The event bus uses Redis Streams with consumer groups, retries with backoff and jitter, a dead letter queue, and idempotency markers for effectively once processing. Security combines Keycloak, multi factor authentication, role and attribute based access control, O P A policies and Vault.

## 26. Testing, evals and load proof  [16:46]

Quality is backed by more than one hundred seventy five automated tests across unit, integration, contract and load suites, plus evaluation golden sets for classification, grounding and no fabrication. A load test on a one million node knowledge graph passed with zero errors: at team traffic the dashboard's ninety fifth percentile was one point eight seven seconds, against a three second target, and graph queries and rescoring stayed well under their targets. Continuous integration also enforces linting, type checks, layer import rules, policy tests and secret scanning.

## 27. Discover → Score → Deliberate → Approve → Learn  [17:20]

To recap. Capital Cortex discovers opportunities from many sources, classifies and resolves them into a knowledge graph, scores them with transparent formulas, lets a council of agents deliberate with cited evidence, and routes every outbound action through signed human approval. Realised outcomes then retrain the model, closing the loop. Every number is computed, every claim is cited, and nothing leaves without approval. Thank you for watching.
