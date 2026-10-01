"""12-factor settings (§12). Every value comes from the environment; nothing secret has a default."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

# Fixed single-tenant org id (R9). Every table carries org_id so multi-tenancy can be added later.
DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    env: str = Field(default="dev", description="dev | staging | prod | test")
    service_name: str = "capital-cortex-api"
    org_id: str = DEFAULT_ORG_ID
    config_dir: Path = REPO_ROOT / "config"

    # --- data ---
    database_url: str = "postgresql+psycopg://cortex:cortex-dev-pw@localhost:55432/cortex"
    redis_url: str = "redis://localhost:56379/0"
    object_store: str = Field(
        default="http://minio:9000",
        description="S3-compatible endpoint; credentials come from Vault or the environment",
    )
    object_store_access_key: str | None = None
    object_store_secret_key: str | None = None

    # --- identity / policy / secrets ---
    oidc_issuer: str = "http://localhost:8380/realms/cortex"
    # When set, JWKS is fetched from here instead of <issuer>/protocol/openid-connect/certs.
    # Used inside Compose, where the issuer hostname seen by browsers differs from the internal one.
    oidc_jwks_url: str | None = None
    oidc_audience: str = "cortex-api"
    # acr values that count as "MFA performed", in addition to the AMR claim containing "otp"/"mfa".
    oidc_mfa_acr_values: list[str] = ["mfa", "2", "gold"]
    step_up_max_age_seconds: int = 300
    # Defence in depth for R5: the API refuses tokens for MFA-required roles that carry no 2nd factor.
    # Compose sets it from CORTEX_MFA_REQUIRED (D-033). Keep it true outside local development.
    oidc_enforce_mfa: bool = True
    # client-credentials for the worker's own service account (D-016)
    oidc_token_url: str = "http://localhost:8380/realms/cortex/protocol/openid-connect/token"  # noqa: S105 - a URL
    worker_client_id: str = "cortex-worker"
    worker_client_secret: str | None = None
    opa_url: str = "http://localhost:8381"
    opa_timeout_seconds: float = 2.0
    vault_addr: str = "http://localhost:8382"

    # --- LLM (R7) ---
    # JSON, or "@path/to/file.json"; NoDecode stops pydantic-settings pre-parsing so the validator sees raw text.
    llm_router: Annotated[dict[str, Any], NoDecode] = Field(default_factory=dict)
    feature_budgets: Annotated[dict[str, float], NoDecode] = Field(default_factory=dict)
    llm_daily_budget_usd: float = 25.0
    llm_cache_ttl_seconds: int = 7 * 24 * 3600

    # --- governed actuation (I3) ---
    # Secret ref for the HS256 key that signs approval tokens. No default key: approvals fail closed without one.
    approval_signing_key_ref: str = "env:APPROVAL_SIGNING_KEY"
    approval_token_ttl_seconds: int = 24 * 3600
    # Delivery channels used only by the outbox sender (and internal alerts). Empty = channel not configured.
    smtp_url: str | None = None  # smtp://host:port or smtps://user@host:port (password via smtp_password_ref)
    smtp_password_ref: str | None = None
    smtp_from: str = "capital-cortex@localhost"
    export_bucket: str = "cortex-exports"
    # Internal alert e-mail may only go to these domains; external recipients are never alerted (§6 L8).
    internal_email_domains: list[str] = []
    alert_webhook_url: str | None = None

    # Base URL external recipients use for data-room share links (served by the API, /v1/share/{token}).
    public_base_url: str = "http://localhost:8300"
    # Keycloak admin API for the Admin screen (users, roles, MFA status). Password via secret ref.
    keycloak_admin_url: str = "http://localhost:8380"
    keycloak_admin_user: str = "kcadmin"
    keycloak_admin_password_ref: str = "env:KEYCLOAK_ADMIN_PASSWORD"  # noqa: S105 - a secret reference, not a secret
    keycloak_realm: str = "cortex"

    # --- agents (L6) ---
    agent_max_parallel: int = 4

    # --- business ---
    min_cash_buffer: float = 0.0
    runway_alert_months: int = 9
    demo_mode: bool = False

    # --- observability ---
    otel_exporter_otlp_endpoint: str | None = None
    metrics_port: int = 9464
    log_level: str = "INFO"

    # --- web ---
    cors_origins: list[str] = ["http://localhost:5373", "http://localhost:3300"]

    @field_validator("llm_router", "feature_budgets", mode="before")
    @classmethod
    def _parse_json(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return {}
            if v.startswith("@"):
                # "@path/to/file.json" keeps large JSON out of the environment.
                return json.loads(Path(v[1:]).read_text(encoding="utf-8"))
            return json.loads(v)
        return v

    @property
    def jwks_url(self) -> str:
        return self.oidc_jwks_url or f"{self.oidc_issuer.rstrip('/')}/protocol/openid-connect/certs"


@lru_cache
def get_settings() -> Settings:
    return Settings()
