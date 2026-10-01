# syntax=docker/dockerfile:1.7
# API + worker image (same codebase, R12). Build context: repo root.
FROM python:3.12-slim-bookworm AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_RETRIES=10 PIP_DEFAULT_TIMEOUT=120
WORKDIR /src
# constraints.txt pins every transitive dependency (regenerate: see RUNBOOK §9)
COPY pyproject.toml constraints.txt ./
COPY platform_core ./platform_core
COPY cortex ./cortex
# BuildKit cache: rebuilds don't re-download wheels (and survive flaky PyPI connectivity).
RUN --mount=type=cache,target=/root/.cache/pip pip install --prefix=/install -c constraints.txt .

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CONFIG_DIR=/app/config XDG_CACHE_HOME=/tmp/cache
# WeasyPrint (PDF collateral, R8) needs Pango/HarfBuzz and fonts at runtime.
RUN apt-get update  && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libfontconfig1 fonts-dejavu-core  && rm -rf /var/lib/apt/lists/*
RUN groupadd --system --gid 10001 cortex && useradd --system --uid 10001 --gid cortex --home /app cortex
COPY --from=build /install /usr/local
WORKDIR /app
COPY alembic.ini ./
COPY migrations ./migrations
COPY config ./config
COPY platform_core ./platform_core
COPY cortex ./cortex
COPY seed ./seed
USER cortex
EXPOSE 8000 9464
CMD ["uvicorn", "cortex.l8_actuation.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
