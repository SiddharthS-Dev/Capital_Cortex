"""Prometheus metrics shared across services. SLO alert rules live in infra/prometheus/rules.yml."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, start_http_server

HTTP_LATENCY = Histogram(
    "cortex_http_request_seconds",
    "API request latency",
    ["method", "route", "status"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 10),
)
POLICY_DECISIONS = Counter("cortex_policy_decisions_total", "OPA decisions", ["package", "outcome"])
BUS_PUBLISHED = Counter("cortex_bus_published_total", "Messages published", ["stream"])
BUS_PROCESSED = Counter("cortex_bus_processed_total", "Messages processed", ["stream", "outcome"])
BUS_DLQ_DEPTH = Gauge("cortex_bus_dlq_depth", "Messages in dead-letter streams", ["stream"])
LLM_TOKENS = Counter("cortex_llm_tokens_total", "LLM tokens", ["tier", "feature", "direction"])
LLM_COST = Counter("cortex_llm_cost_usd_total", "LLM spend in USD", ["tier", "feature"])
LLM_CACHE = Counter("cortex_llm_cache_total", "LLM cache lookups", ["result"])
LLM_BUDGET_REJECTIONS = Counter("cortex_llm_budget_rejections_total", "Calls refused by budget", ["scope"])
LLM_DAILY_SPEND = Gauge("cortex_llm_daily_spend_usd", "Today's LLM spend", [])
LLM_DAILY_CAP = Gauge("cortex_llm_daily_cap_usd", "Daily LLM cap", [])
CITATION_REJECTIONS = Counter(
    "cortex_citation_rejections_total", "Unsourced claims rejected by citation_checker", ["agent"]
)
AUDIT_APPENDS = Counter("cortex_audit_appends_total", "Audit records appended", ["action"])


_started = False


def start_metrics_server(port: int) -> None:
    """Metrics are served on a separate internal port and never through the public API."""
    global _started
    if not _started:
        start_http_server(port)
        _started = True
