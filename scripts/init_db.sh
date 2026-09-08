#!/usr/bin/env bash
# Local convenience script: (re)create the dev + test databases and apply the
# schema. Only needed if you're running Postgres outside docker-compose (which
# already applies db/schema.sql via docker-entrypoint-initdb.d on first boot).
set -euo pipefail

HOST="${PGHOST:-localhost}"
USER="${PGUSER:-casework}"
export PGPASSWORD="${PGPASSWORD:-casework}"

for db in casework casework_test; do
    port="5434"
    [ "$db" = "casework_test" ] && port="5433"
    echo "Applying schema to $db on port $port..."
    psql -h "$HOST" -p "$port" -U "$USER" -d "$db" -f "$(dirname "$0")/../db/schema.sql"
done
