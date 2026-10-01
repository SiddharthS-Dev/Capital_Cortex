#!/bin/sh
set -e
until mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1; do sleep 1; done
for b in cortex-raw cortex-docs cortex-dataroom cortex-cold cortex-backups cortex-exports; do mc mb --ignore-existing "local/$b"; done
mc version enable local/cortex-docs
mc version enable local/cortex-dataroom
echo "buckets ready"
