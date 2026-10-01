-- Runs once on first cluster init. Schema itself is owned by Alembic (make migrate).
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS age;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
-- Keycloak gets its own database on the same server in dev/staging (separate cluster in prod).
CREATE DATABASE keycloak;
