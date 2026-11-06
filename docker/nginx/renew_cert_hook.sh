#!/bin/bash
# =============================================================================
# NeuroForge AI — Certbot SSL Renewal Deploy Hook
#
# Place this script at:
#   /etc/letsencrypt/renewal-hooks/deploy/neuroforge-reload.sh
# Make it executable:
#   chmod +x /etc/letsencrypt/renewal-hooks/deploy/neuroforge-reload.sh
#
# This hook runs automatically after a successful `certbot renew`.
# It copies the renewed certificates to the Docker volume mount path
# and reloads the Nginx container.
#
# USAGE: Set NEUROFORGE_DIR to the absolute path of the project root on the host.
# =============================================================================

set -euo pipefail

NEUROFORGE_DIR="${NEUROFORGE_DIR:-/opt/neuroforge}"
DOMAIN="${CERTBOT_DOMAIN:-yourdomain.com}"
SSL_DIR="${NEUROFORGE_DIR}/docker/nginx/ssl"
CERT_SRC="/etc/letsencrypt/live/${DOMAIN}"

echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Certbot renewal hook triggered for ${DOMAIN}"

# Ensure target directory exists with restricted permissions
mkdir -p "${SSL_DIR}"
chmod 750 "${SSL_DIR}"

# Copy renewed cert files
cp -L "${CERT_SRC}/fullchain.pem" "${SSL_DIR}/fullchain.pem"
cp -L "${CERT_SRC}/privkey.pem"   "${SSL_DIR}/privkey.pem"
chmod 644 "${SSL_DIR}/fullchain.pem"
chmod 640 "${SSL_DIR}/privkey.pem"

echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Certificates updated in ${SSL_DIR}"

# Reload Nginx inside the running frontend container (no restart needed)
docker compose -f "${NEUROFORGE_DIR}/docker-compose.prod.yml" exec -T frontend nginx -s reload

echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Nginx reloaded successfully."

