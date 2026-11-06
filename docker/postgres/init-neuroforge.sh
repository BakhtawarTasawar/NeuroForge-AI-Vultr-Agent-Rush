#!/bin/sh
# =============================================================================
# NeuroForge AI: Dedicated Application Role & Checkpoint Schema Initialization
# Executed automatically on container creation by PostgreSQL entrypoint.
# Obtains credentials securely from environment variables.
# =============================================================================

set -e

APP_USER="${POSTGRES_APP_USER:-neuroforge_app}"
APP_PASSWORD="${POSTGRES_APP_PASSWORD}"

if [ -z "$APP_PASSWORD" ]; then
    echo "ERROR: POSTGRES_APP_PASSWORD environment variable is required for database initialization." >&2
    exit 1
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Create dedicated application user if not exists
    DO \$\$
    BEGIN
       IF NOT EXISTS (
          SELECT FROM pg_catalog.pg_roles
          WHERE  rolname = '$APP_USER') THEN

          EXECUTE format('CREATE ROLE %I WITH LOGIN PASSWORD %L', '$APP_USER', '$APP_PASSWORD');
       END IF;
    END
    \$\$;

    -- Ensure database access
    GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO "$APP_USER";
    GRANT ALL PRIVILEGES ON DATABASE "$POSTGRES_DB" TO "$APP_USER";

    -- Public schema access for primary application tables
    GRANT ALL ON SCHEMA public TO "$APP_USER";
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "$APP_USER";
    GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO "$APP_USER";
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO "$APP_USER";
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO "$APP_USER";
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO "$APP_USER";

    -- Dedicated checkpoint schema for LangGraph durable persistence
    CREATE SCHEMA IF NOT EXISTS checkpoints;
    ALTER SCHEMA checkpoints OWNER TO "$APP_USER";
    GRANT ALL ON SCHEMA checkpoints TO "$APP_USER";
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA checkpoints TO "$APP_USER";
    GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA checkpoints TO "$APP_USER";
    ALTER DEFAULT PRIVILEGES IN SCHEMA checkpoints GRANT ALL ON TABLES TO "$APP_USER";
    ALTER DEFAULT PRIVILEGES IN SCHEMA checkpoints GRANT ALL ON SEQUENCES TO "$APP_USER";
    ALTER DEFAULT PRIVILEGES IN SCHEMA checkpoints GRANT ALL ON FUNCTIONS TO "$APP_USER";
EOSQL

