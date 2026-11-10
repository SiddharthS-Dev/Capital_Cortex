# Capital Cortex: Performance Audit (PERF-1)

Execution date: **2026-11-03** (evening).
- **Dataset:** `cortex_bench_1m` on `capital-cortex-mysql-test` (MySQL 8.4.13, **512 MB buffer pool**), 111,112 active opportunities in the measured org.
- **Method:** read-only session. Each query runs 4 times: the first is "cold", followed by the median of the next 3. Same script as the 2026-11-03 morning measurement.

**Target:** search below 2 s. **Status: not met with current search semantics.**

## Measurements

| Query | Morning (historical) | **Now: warm median** | Now: cold | Rows |
|---|---|---|---|---|
| F1 Facet counts (GROUP BY class, stage, band; index hint) | 1,133 ms | **1,190 ms** | 2,368 ms | 110 groups |
| C1 Exact total | 303 ms | **264 ms** | 358 ms | 111,112 |
| C2 Capped total (stops at 1,001) | 20 ms | **12 ms** | 85 ms | 1,001 |
| S1 Substring `LIKE` on title + counterparty | 6,683 ms | **8,290 ms** | 17,782 ms | 0 |
| **S2 Search, current router shape (FULLTEXT OR substring)** | **7,629 ms** | **6,110 ms** | **13,424 ms** | 20,000 |
| S3 FULLTEXT word/prefix only | 413 ms | **1,229 ms** | 1,885 ms | 20,000 |
| S4 FULLTEXT only, first page of 50 | 88 ms | **257 ms** | 290 ms | 50 |

Variance between runs is large. This run followed a 15-minute integration suite on the same server, so the buffer pool was colder. The conclusion is unchanged.

## Root cause (execution plan for S2)

```
Aggregate: count(0)
  Filter: (MATCH(title, description) AGAINST (...) OR title LIKE '%..%' OR cp.name LIKE '%..%')
    Nested loop left join (rows ~ 110,674)
      Index lookup on o using ux_opp_external_key (org_id = ...)
      Single-row index lookup on cp using PRIMARY (id = o.counterparty_id)
```

- The `OR` between the FULLTEXT predicate and two leading-wildcard `LIKE`s, one of them on the **joined** counterparty table, stops MySQL from using the FULLTEXT index as an access path.
- Every row in the org is read, joined and evaluated.
- A leading-wildcard `LIKE` can't use a B-tree index. That is inherent, not a missing index.
- The 512 MB buffer pool against about 3 GB of data makes cold runs disk-bound.
- Pagination is not the bottleneck: the page query with the deferred join and m0003 indexes takes about 17 ms (morning).

## Options (nothing was changed)

| Option | Expected search time | Semantics change | Cost |
|---|---|---|---|
| A. FULLTEXT word/prefix only | ~0.3–1.2 s (first page ~0.26 s) | loses mid-word and counterparty-name matches | small |
| B. A + a FULLTEXT index on `organization.name` (union) | likely < 1.5 s (**not measured**) | loses only mid-word substring matches | index + migration |
| C. n-gram FULLTEXT parser | not measured | keeps substring-like matching | larger index, migration |
| D. Keep current semantics | 6–13 s | none | target missed |
| Facets: cached summary table, or loaded on demand | ms / deferred | slight staleness, or a UX change | write-path upkeep |
| Totals: capped ("1,000+") | 12 ms vs 264 ms | UX label | trivial |
| Production buffer pool ≥ working set (≥4 GB) | improves every cold figure | none | INFRA-1 |

## Decision required (Project Lead)

1. Search semantics: A, B or C. B is recommended for discussion, to be measured after implementation.
2. Facet strategy, and exact or capped totals.
3. Production buffer-pool sizing (DevOps).

The end-to-end p95 (historical 2026-11-02: radar 18.7 s, search 28.1 s) must be re-measured after implementation. No improvement is claimed here.
