# Custom PostgreSQL 16 with Apache AGE (graph `ckg`) + pgvector (HNSW). Versions pinned (D-005).
#   AGE      1.5.0 for PG16  (base image apache/age:release_PG16_1.5.0, Debian bookworm, PG 16)
#   pgvector 0.8.0           (built from the tagged source in a builder stage)
ARG AGE_IMAGE=apache/age:release_PG16_1.5.0

FROM ${AGE_IMAGE} AS pgvector-build
ARG PGVECTOR_VERSION=v0.8.0
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends build-essential git ca-certificates postgresql-server-dev-16; \
    git clone --depth 1 --branch "${PGVECTOR_VERSION}" https://github.com/pgvector/pgvector.git /src; \
    cd /src; make OPTFLAGS=""; make install DESTDIR=/out

FROM ${AGE_IMAGE}
COPY --from=pgvector-build /out/usr/lib/postgresql/16/lib/ /usr/lib/postgresql/16/lib/
COPY --from=pgvector-build /out/usr/share/postgresql/16/extension/ /usr/share/postgresql/16/extension/
COPY init/ /docker-entrypoint-initdb.d/

# AGE is NOT preloaded: a preloaded AGE hooks DDL in every database and breaks other databases on the
# same server (e.g. Keycloak's). Sessions run LOAD '$libdir/plugins/age' instead; the plugins/ path also
# lets non-superuser roles load it (least privilege, §10).
RUN mkdir -p /usr/lib/postgresql/16/lib/plugins \
 && ln -sf /usr/lib/postgresql/16/lib/age.so /usr/lib/postgresql/16/lib/plugins/age.so

# WAL archive target (D-031). Compose mounts the named volume `pgwal` here; creating the directory in the
# image makes Docker initialise the volume with postgres ownership. Archiving itself is switched on by the
# compose `command` (RUNBOOK §8), so test containers built from this image don't archive.
COPY archive-wal.sh /usr/local/bin/archive-wal.sh
RUN mkdir -p /var/lib/postgresql/wal-archive && chown postgres:postgres /var/lib/postgresql/wal-archive \
 && chmod 700 /var/lib/postgresql/wal-archive && sed -i 's/\r$//' /usr/local/bin/archive-wal.sh \
 && chmod 755 /usr/local/bin/archive-wal.sh

CMD ["postgres", "-c", "max_connections=200", "-c", "shared_buffers=512MB", "-c", "wal_level=replica"]

HEALTHCHECK --interval=5s --timeout=3s --retries=30 CMD pg_isready -U "${POSTGRES_USER:-postgres}" || exit 1
