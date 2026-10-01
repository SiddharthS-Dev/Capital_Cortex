#!/bin/sh
# Postgres archive_command (D-031): archive-wal.sh %p %f
# Writes a gzip-compressed copy of a finished WAL segment (or .history/.backup file) to the archive volume.
# The copy is written to a .part file and renamed, so a crash never leaves a truncated segment behind.
# A retry after a crash (file already archived) succeeds only if the archived content is identical.
set -eu
src="$1"
name="$2"
dir="${WAL_ARCHIVE_DIR:-/var/lib/postgresql/wal-archive}"
dst="$dir/$name.gz"

if [ -f "$dst" ]; then
  if gzip -dc "$dst" | cmp -s - "$src"; then
    exit 0
  fi
  echo "archive-wal: $dst already exists with different content" >&2
  exit 1
fi

gzip -1 -c "$src" > "$dst.part"
sync "$dst.part" 2>/dev/null || sync
mv "$dst.part" "$dst"
