#!/bin/bash
# =============================================================================
# NeuroForge AI — PostgreSQL Production Restore Script
# Restores database from a compressed pg_dump file.
# =============================================================================

set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <path_to_backup.sql.gz>"
    exit 1
fi

BACKUP_FILE="$1"
if [ ! -f "${BACKUP_FILE}" ]; then
    echo "Error: Backup file ${BACKUP_FILE} does not exist."
    exit 1
fi

CONTAINER_NAME="neuroforge-db-prod"
DB_NAME="${POSTGRES_DB:-neuroforge}"
DB_USER="${POSTGRES_USER:-postgres}"

read -r -p "WARNING: This will overwrite data in database '${DB_NAME}'. Continue? (y/N) " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Restore cancelled."
    exit 0
fi

echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Restoring database from ${BACKUP_FILE}..."
gunzip -c "${BACKUP_FILE}" | docker exec -i "${CONTAINER_NAME}" psql -U "${DB_USER}" -d "${DB_NAME}"

echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Database restored successfully."

