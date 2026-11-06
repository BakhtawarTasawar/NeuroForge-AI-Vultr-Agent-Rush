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


def run_migrations():
    """Ensure newly added columns and tables exist in SQLite without dropping or recreating tables."""
    try:
        Base.metadata.create_all(bind=engine)
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()
        with engine.connect() as conn:
            if "datasets" in existing_tables:
                columns = [c["name"] for c in inspector.get_columns("datasets")]
                for col_name, col_type in DATASET_NEW_COLUMNS:
                    if col_name not in columns:
                        logger.info(f"Adding column '{col_name}' to 'datasets' table...")
                        conn.execute(text(f"ALTER TABLE datasets ADD COLUMN {col_name} {col_type}"))

            if "experiments" in existing_tables:
                columns = [c["name"] for c in inspector.get_columns("experiments")]
                for col_name, col_type in EXPERIMENT_NEW_COLUMNS:
                    if col_name not in columns:
                        logger.info(f"Adding column '{col_name}' to 'experiments' table...")
                        conn.execute(text(f"ALTER TABLE experiments ADD COLUMN {col_name} {col_type}"))
            conn.commit()
    except Exception as e:
        logger.warning(f"Database migration notice: {e}")

