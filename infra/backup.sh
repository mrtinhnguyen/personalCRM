#!/usr/bin/env sh
set -eu

DATA_ROOT=${DATA_ROOT:-./volumes/data}
BACKUP_ROOT=${BACKUP_ROOT:-$DATA_ROOT/backups}
mkdir -p "$BACKUP_ROOT"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
COMPOSE_FILE=${COMPOSE_FILE:-infra/docker-compose.yml}

docker compose -f "$COMPOSE_FILE" exec -T postgres \
  pg_dump --format=custom --no-owner --no-privileges \
  -U "${POSTGRES_USER:-crm}" -d "${POSTGRES_DB:-crm}" \
  > "$BACKUP_ROOT/postgres-$STAMP.dump"

tar -czf "$BACKUP_ROOT/raw-and-manifests-$STAMP.tar.gz" \
  -C "$DATA_ROOT" raw staging exports

echo "Created backup set $STAMP in $BACKUP_ROOT"
