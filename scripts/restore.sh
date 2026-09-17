#!/usr/bin/env bash
#
# NegArchive restore: put a backup archive back (roadmap M3).
#
#   ./scripts/restore.sh                                   # the newest backup
#   ./scripts/restore.sh negarchive-20260917-101500.tar.gz # a specific one
#   ./scripts/restore.sh /path/to/any/backup.tar.gz
#
# This REPLACES the current archive: the database is dropped and reloaded, and
# the managed files are overwritten. It asks first; `FORCE=1` skips the question
# (for a scripted restore into a fresh machine).
#
# Steps, in order:
#   1. the stack must be running, because the database is restored through it
#   2. unpack the archive to a temporary directory
#   3. psql < database.sql   (the dump is --clean --if-exists, so it drops first)
#   4. copy uploads/ and catalog/ back into $DATA_DIR
#   5. clear the preview cache, because its keys reference the old mtimes
#
# Afterwards, check it: `curl -s localhost:8021/api/films | head` should show
# your rolls, and the frame count in the UI should match the manifest.

set -euo pipefail

cd "$(dirname "$0")/.."

# shellcheck disable=SC1091
[ -f .env ] && set -a && . ./.env && set +a

DATA_DIR="${DATA_DIR:-./data}"
BACKUP_DIR="${BACKUP_DIR:-$DATA_DIR/backups}"
POSTGRES_USER="${POSTGRES_USER:-negarchive}"
POSTGRES_DB="${POSTGRES_DB:-negarchive}"
DB_SERVICE="${DB_SERVICE:-db}"
WEB_SERVICE="${WEB_SERVICE:-web}"
COMPOSE="${COMPOSE:-docker compose}"

archive="${1:-}"
if [ -z "$archive" ]; then
  archive="$(ls -t "$BACKUP_DIR"/negarchive-*.tar.gz 2>/dev/null | head -n 1 || true)"
  [ -n "$archive" ] || { echo "error: no backup found in $BACKUP_DIR" >&2; exit 1; }
elif [ ! -f "$archive" ] && [ -f "$BACKUP_DIR/$archive" ]; then
  archive="$BACKUP_DIR/$archive"
fi
[ -f "$archive" ] || { echo "error: no such backup: $archive" >&2; exit 1; }

staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT
tar -xzf "$archive" -C "$staging"
[ -f "$staging/database.sql" ] || { echo "error: $archive has no database.sql" >&2; exit 1; }

echo "==> restoring $archive"
[ -f "$staging/MANIFEST.txt" ] && sed 's/^/    /' "$staging/MANIFEST.txt"
echo

if [ "${FORCE:-0}" != "1" ]; then
  printf 'This replaces the archive in %s and the %s database. Continue? [y/N] ' "$DATA_DIR" "$POSTGRES_DB"
  read -r answer
  case "$answer" in
    y | Y | yes | YES) ;;
    *) echo "aborted."; exit 1 ;;
  esac
fi

if ! $COMPOSE ps --status running --services 2>/dev/null | grep -qx "$DB_SERVICE"; then
  echo "error: the '$DB_SERVICE' service is not running. Run 'docker compose up -d db' first." >&2
  exit 1
fi

echo "==> stopping the app so nothing writes while the database is swapped"
$COMPOSE stop "$WEB_SERVICE" >/dev/null 2>&1 || true

echo "==> loading database.sql"
$COMPOSE exec -T "$DB_SERVICE" psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  < "$staging/database.sql" > /dev/null

echo "==> restoring the managed files"
for part in uploads catalog; do
  if [ -d "$staging/$part" ]; then
    mkdir -p "$DATA_DIR/$part"
    cp -a "$staging/$part/." "$DATA_DIR/$part/"
  fi
done

echo "==> clearing the preview cache"
rm -rf "${DATA_DIR:?}/cache"
mkdir -p "$DATA_DIR/cache"

echo "==> starting the app"
$COMPOSE start "$WEB_SERVICE" >/dev/null 2>&1 || $COMPOSE up -d "$WEB_SERVICE" >/dev/null

echo
echo "done. Check it:  curl -s http://localhost:${UI_PORT:-8021}/api/films | head -c 400"
