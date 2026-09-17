#!/usr/bin/env bash
#
# NegArchive backup: the database and the managed files, in one file you can copy
# to a USB disk (roadmap M3).
#
#   ./scripts/backup.sh                 # against the running Compose stack
#   BACKUP_KEEP=30 ./scripts/backup.sh  # keep 30 instead of 7
#
# Produces $DATA_DIR/backups/negarchive-<timestamp>.tar.gz holding
#
#   database.sql          pg_dump --clean --if-exists, plain SQL
#   uploads/              the files NegArchive manages
#   catalog/              camera, lens and film stock pictures
#   MANIFEST.txt          what this is, when it was taken, how to restore it
#
# Deliberately NOT included: data/cache (rendered on demand), data/postgres (the
# cluster itself — copying a live one is how you get a corrupt backup), and files
# imported by reference, which live in a folder you back up yourself.
#
# Restore with scripts/restore.sh.

set -euo pipefail

cd "$(dirname "$0")/.."

# shellcheck disable=SC1091
[ -f .env ] && set -a && . ./.env && set +a

DATA_DIR="${DATA_DIR:-./data}"
BACKUP_DIR="${BACKUP_DIR:-$DATA_DIR/backups}"
BACKUP_KEEP="${BACKUP_KEEP:-7}"
POSTGRES_USER="${POSTGRES_USER:-negarchive}"
POSTGRES_DB="${POSTGRES_DB:-negarchive}"
DB_SERVICE="${DB_SERVICE:-db}"
COMPOSE="${COMPOSE:-docker compose}"

timestamp="$(date +%Y%m%d-%H%M%S)"
archive="$BACKUP_DIR/negarchive-$timestamp.tar.gz"
staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT

mkdir -p "$BACKUP_DIR"

echo "==> dumping the database"
if [ -n "${DATABASE_DUMP_CMD:-}" ]; then
  # Escape hatch for a Postgres that is not this Compose stack.
  eval "$DATABASE_DUMP_CMD" > "$staging/database.sql"
elif $COMPOSE ps --status running --services 2>/dev/null | grep -qx "$DB_SERVICE"; then
  $COMPOSE exec -T "$DB_SERVICE" \
    pg_dump --clean --if-exists --no-owner --no-privileges \
    -U "$POSTGRES_USER" "$POSTGRES_DB" > "$staging/database.sql"
elif command -v pg_dump >/dev/null 2>&1 && [ -n "${DATABASE_URL:-}" ]; then
  pg_dump --clean --if-exists --no-owner --no-privileges \
    "${DATABASE_URL#postgresql+psycopg2://}" > "$staging/database.sql"
  # (psycopg2's URL prefix is a SQLAlchemy thing; pg_dump wants plain postgresql://)
else
  echo "error: no running '$DB_SERVICE' service and no usable pg_dump." >&2
  echo "       Start the stack, or set DATABASE_DUMP_CMD." >&2
  exit 1
fi

echo "==> collecting the managed files"
for part in uploads catalog; do
  if [ -d "$DATA_DIR/$part" ]; then
    mkdir -p "$staging/$part"
    # -a keeps timestamps, which the preview cache key depends on.
    cp -a "$DATA_DIR/$part/." "$staging/$part/"
  fi
done

{
  echo "NegArchive backup"
  echo "taken:      $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "host:       $(hostname)"
  echo "data dir:   $DATA_DIR"
  echo "database:   $POSTGRES_DB as $POSTGRES_USER"
  echo "sql bytes:  $(wc -c < "$staging/database.sql" | tr -d ' ')"
  echo
  echo "Restore:    ./scripts/restore.sh $(basename "$archive")"
  echo
  echo "Files imported by reference (storage_mode = 'linked') are NOT in here."
  echo "They live in your own scan folder; back that up separately."
} > "$staging/MANIFEST.txt"

echo "==> writing $archive"
tar -czf "$archive" -C "$staging" .

echo "==> pruning, keeping the newest $BACKUP_KEEP"
# `ls -t` newest first; everything after the first N goes.
(cd "$BACKUP_DIR" && ls -t negarchive-*.tar.gz 2>/dev/null | tail -n "+$((BACKUP_KEEP + 1))" | while read -r old; do
  echo "    removing $old"
  rm -f -- "$old"
done)

echo
echo "done: $archive ($(du -h "$archive" | cut -f1))"
