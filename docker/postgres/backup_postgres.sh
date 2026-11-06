#!/bin/bash
# =============================================================================
# NeuroForge AI — PostgreSQL Production Backup Script
# Performs automated pg_dump with gzip compression and retention management.
# =============================================================================

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/neuroforge}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
TIMESTAMP="$(date +'%Y%m%d_%H%M%S')"
BACKUP_FILE="${BACKUP_DIR}/neuroforge_backup_${TIMESTAMP}.sql.gz"

CONTAINER_NAME="neuroforge-db-prod"
DB_NAME="${POSTGRES_DB:-neuroforge}"
DB_USER="${POSTGRES_USER:-postgres}"

mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Starting PostgreSQL backup..."

# Execute pg_dump within the running container
docker exec "${CONTAINER_NAME}" pg_dump -U "${DB_USER}" -d "${DB_NAME}" --clean --if-exists | gzip -9 > "${BACKUP_FILE}"

chmod 600 "${BACKUP_FILE}"
BACKUP_SIZE="$(du -h "${BACKUP_FILE}" | cut -f1)"

echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Backup completed successfully: ${BACKUP_FILE} (${BACKUP_SIZE})"

# Prune old backups older than retention window
echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Cleaning up backups older than ${RETENTION_DAYS} days..."
find "${BACKUP_DIR}" -type f -name "neuroforge_backup_*.sql.gz" -mtime +"${RETENTION_DAYS}" -delete

echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Backup and maintenance finished."

