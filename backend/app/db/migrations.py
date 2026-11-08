
import logging

from sqlalchemy import text, inspect

from app.db.database import engine, Base
import app.db.models  # Ensure all models are registered

logger = logging.getLogger("neuroforge.migrations")

DATASET_NEW_COLUMNS = [
    ("content_hash", "VARCHAR(64)"),
    ("matrix_orientation", "VARCHAR(32) DEFAULT 'features_as_rows'"),
    ("feature_id_column", "VARCHAR(128)"),
    ("sample_id_column", "VARCHAR(128)"),
    ("quality_assessment", "TEXT"),
    ("group_mappings", "TEXT"),
    ("title", "VARCHAR(255)"),
    ("domain", "VARCHAR(128) DEFAULT 'Cancer Gene-Expression'"),
    ("organism", "VARCHAR(128)"),
    ("tissue", "VARCHAR(128)"),
    ("experimental_condition", "VARCHAR(255)"),
    ("control_group", "VARCHAR(128)"),
    ("treatment_group", "VARCHAR(128)"),
    ("measurement_type", "VARCHAR(128)"),
    ("data_source", "VARCHAR(255)"),
    ("publication_reference", "VARCHAR(255)"),
]

EXPERIMENT_NEW_COLUMNS = [
    ("experiment_type", "VARCHAR(64) DEFAULT 'differential_expression_welch'"),
    ("dataset_hash", "VARCHAR(64)"),
    ("reproducibility_manifest", "TEXT"),
    ("statistical_summary", "TEXT"),
]

KNOWLEDGE_DOCUMENT_NEW_COLUMNS = [
    ("doi", "VARCHAR(128)"),
    ("authors", "TEXT"),
    ("publication_year", "INTEGER"),
    ("journal", "VARCHAR(255)"),
    ("source_url", "VARCHAR(512)"),
    ("tags", "TEXT"),
    ("custom_metadata", "TEXT"),
]

NEUROFORGE_MIGRATION_ADVISORY_LOCK_ID = 847291048201948271


def run_migrations():
    """
    Serialize PostgreSQL schema initialization across workers using a
    session-level advisory lock.

    Migration failures propagate to the caller so application startup
    cannot silently continue with an incomplete schema.
    """
    is_postgres = engine.dialect.name == "postgresql"
    lock_acquired = False

    with engine.connect() as conn:
        try:
            if is_postgres:
                logger.info(
                    "Acquiring PostgreSQL advisory lock for schema initialization..."
                )

                conn.execute(
                    text("SELECT pg_advisory_lock(:lock_id)"),
                    {"lock_id": NEUROFORGE_MIGRATION_ADVISORY_LOCK_ID},
                )
                lock_acquired = True

                # Session-level advisory locks survive transaction commits.
                conn.commit()

            # 1. Create missing tables.
            Base.metadata.create_all(bind=conn)

            # 2. Inspect and apply idempotent column migrations.
            inspector = inspect(conn)
            existing_tables = inspector.get_table_names()

            if "datasets" in existing_tables:
                columns = {
                    column["name"]
                    for column in inspector.get_columns("datasets")
                }

                for col_name, col_type in DATASET_NEW_COLUMNS:
                    if col_name not in columns:
                        logger.info(
                            f"Adding column '{col_name}' to 'datasets'..."
                        )
                        conn.execute(
                            text(
                                f"ALTER TABLE datasets "
                                f"ADD COLUMN {col_name} {col_type}"
                            )
                        )

            if "experiments" in existing_tables:
                columns = {
                    column["name"]
                    for column in inspector.get_columns("experiments")
                }

                for col_name, col_type in EXPERIMENT_NEW_COLUMNS:
                    if col_name not in columns:
                        logger.info(
                            f"Adding column '{col_name}' to 'experiments'..."
                        )
                        conn.execute(
                            text(
                                f"ALTER TABLE experiments "
                                f"ADD COLUMN {col_name} {col_type}"
                            )
                        )

            if "knowledge_documents" in existing_tables:
                columns = {
                    column["name"]
                    for column in inspector.get_columns("knowledge_documents")
                }

                for col_name, col_type in KNOWLEDGE_DOCUMENT_NEW_COLUMNS:
                    if col_name not in columns:
                        logger.info(
                            f"Adding column '{col_name}' to 'knowledge_documents'..."
                        )
                        conn.execute(
                            text(
                                f"ALTER TABLE knowledge_documents "
                                f"ADD COLUMN {col_name} {col_type}"
                            )
                        )

            conn.commit()

            logger.info(
                "Database schema verification and migrations completed successfully."
            )

        except Exception:
            conn.rollback()
            logger.exception("Database schema initialization failed.")
            raise

        finally:
            if is_postgres and lock_acquired:
                try:
                    # Clear any failed transaction before unlocking.
                    conn.rollback()

                    unlocked = conn.execute(
                        text("SELECT pg_advisory_unlock(:lock_id)"),
                        {"lock_id": NEUROFORGE_MIGRATION_ADVISORY_LOCK_ID},
                    ).scalar_one()

                    conn.commit()

                    if not unlocked:
                        raise RuntimeError(
                            "PostgreSQL advisory lock was not held during unlock."
                        )

                    logger.info("Released PostgreSQL advisory lock.")

                except Exception:
                    # Invalidate the connection to close the PostgreSQL
                    # session and guarantee release of its session-level lock.
                    logger.exception(
                        "Failed to release migration lock; invalidating connection."
                    )
                    conn.invalidate()
                    raise
