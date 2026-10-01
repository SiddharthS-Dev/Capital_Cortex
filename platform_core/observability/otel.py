"""OpenTelemetry setup: traces and logs over OTLP/HTTP to the collector (→ Tempo, Loki)."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from platform_core.config import Settings


class JsonFormatter(logging.Formatter):
    _std = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        ctx = trace.get_current_span().get_span_context()
        if ctx.is_valid:
            payload["trace_id"] = format(ctx.trace_id, "032x")
            payload["span_id"] = format(ctx.span_id, "016x")
        for k, v in record.__dict__.items():
            if k not in self._std and not k.startswith("_"):
                payload[k] = v
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root.addHandler(h)
    root.setLevel(level.upper())


def setup_otel(settings: Settings, service_name: str | None = None) -> None:
    setup_logging(settings.log_level)
    name = service_name or settings.service_name
    resource = Resource.create({"service.name": name, "deployment.environment": settings.env})
    provider = TracerProvider(resource=resource)
    endpoint = settings.otel_exporter_otlp_endpoint
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")))
        _setup_otlp_logs(endpoint, resource)
    trace.set_tracer_provider(provider)

    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor

    HTTPXClientInstrumentor().instrument()
    RedisInstrumentor().instrument()


def _setup_otlp_logs(endpoint: str, resource: Resource) -> None:
    try:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    except ImportError:  # pragma: no cover - logs SDK is still marked experimental upstream
        return
    lp = LoggerProvider(resource=resource)
    lp.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{endpoint}/v1/logs")))
    set_logger_provider(lp)
    logging.getLogger().addHandler(LoggingHandler(level=logging.INFO, logger_provider=lp))


def tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)
