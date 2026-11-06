-- =============================================================================
-- NeuroForge AI: Dedicated Application Role & Checkpoint Schema Initialization
-- Executed automatically on container creation by PostgreSQL entrypoint
-- =============================================================================

-- Create dedicated application user if not exists
-- NOTE: For automated container initialization, use init-neuroforge.sh with
-- POSTGRES_APP_PASSWORD passed securely via environment variables.
DO
$do$
BEGIN
   IF NOT EXISTS (
      SELECT FROM pg_catalog.pg_roles
      WHERE  rolname = 'neuroforge_app') THEN

      RAISE NOTICE 'Role neuroforge_app should be provisioned via init-neuroforge.sh or with an explicit secure password.';
   END IF;
END
$do$;

-- Ensure database access
GRANT CONNECT ON DATABASE neuroforge TO neuroforge_app;
GRANT ALL PRIVILEGES ON DATABASE neuroforge TO neuroforge_app;

-- Public schema access for primary application tables
GRANT ALL ON SCHEMA public TO neuroforge_app;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO neuroforge_app;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO neuroforge_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO neuroforge_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO neuroforge_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO neuroforge_app;

-- Dedicated checkpoint schema for LangGraph durable persistence
CREATE SCHEMA IF NOT EXISTS checkpoints;
ALTER SCHEMA checkpoints OWNER TO neuroforge_app;
GRANT ALL ON SCHEMA checkpoints TO neuroforge_app;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA checkpoints TO neuroforge_app;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA checkpoints TO neuroforge_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA checkpoints GRANT ALL ON TABLES TO neuroforge_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA checkpoints GRANT ALL ON SEQUENCES TO neuroforge_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA checkpoints GRANT ALL ON FUNCTIONS TO neuroforge_app;

