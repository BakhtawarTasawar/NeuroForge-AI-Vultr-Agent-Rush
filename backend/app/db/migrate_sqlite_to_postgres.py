"""
Data Migration Tool: SQLite to PostgreSQL for NeuroForge AI
Safely migrates legacy records from SQLite neuroforge.db to PostgreSQL,
maintaining referential integrity and creating an immutable SQLite backup.
"""
import logging
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.database import SessionLocal, engine
from app.db import models

logger = logging.getLogger("neuroforge.migration")
logging.basicConfig(level=logging.INFO)


def parse_dt(val: Any) -> Any:
    if val is None or isinstance(val, datetime):
        return val
    try:
        dt = datetime.fromisoformat(val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return val


def migrate_data(sqlite_path: str = "neuroforge.db") -> Dict[str, int]:
    sqlite_file = Path(sqlite_path)
    if not sqlite_file.exists():
        logger.info(f"SQLite file '{sqlite_path}' does not exist. Nothing to migrate.")
        return {}

    # 1. Create durable backup
    backup_path = sqlite_file.with_suffix(f".backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(sqlite_file, backup_path)
    logger.info(f"Durable SQLite backup created at: {backup_path}")

    sqlite_conn = sqlite3.connect(str(sqlite_file))
    sqlite_conn.row_factory = sqlite3.Row
    cur = sqlite_conn.cursor()

    pg_session: Session = SessionLocal()
    migrated_counts: Dict[str, int] = {}

    try:
        # Migrate users
        cur.execute("SELECT * FROM users")
        user_rows = cur.fetchall()
        migrated_counts["users"] = 0
        for row in user_rows:
            d = dict(row)
            existing = pg_session.get(models.User, d["id"])
            if not existing:
                u = models.User(
                    id=d["id"],
                    email=d["email"],
                    hashed_password=d["hashed_password"],
                    full_name=d["full_name"],
                    role=d["role"],
                    is_active=bool(d["is_active"]),
                    created_at=parse_dt(d.get("created_at")),
                    updated_at=parse_dt(d.get("updated_at")),
                )
                pg_session.add(u)
                migrated_counts["users"] += 1
        pg_session.commit()

        # Migrate projects
        cur.execute("SELECT * FROM projects")
        project_rows = cur.fetchall()
        migrated_counts["projects"] = 0
        for row in project_rows:
            d = dict(row)
            existing = pg_session.get(models.Project, d["id"])
            if not existing:
                p = models.Project(
                    id=d["id"],
                    title=d["title"],
                    description=d.get("description"),
                    domain=d.get("domain", "Cancer Gene-Expression"),
                    status=d.get("status", "Active"),
                    owner_id=d["owner_id"],
                    created_at=parse_dt(d.get("created_at")),
                    updated_at=parse_dt(d.get("updated_at")),
                )
                pg_session.add(p)
                migrated_counts["projects"] += 1
        pg_session.commit()

        # Migrate datasets
        cur.execute("SELECT * FROM datasets")
        dataset_rows = cur.fetchall()
        migrated_counts["datasets"] = 0
        for row in dataset_rows:
            d = dict(row)
            existing = pg_session.get(models.Dataset, d["id"])
            if not existing:
                ds = models.Dataset(
                    id=d["id"],
                    project_id=d["project_id"],
                    owner_id=d["owner_id"],
                    filename=d["filename"],
                    original_name=d["original_name"],
                    file_size_bytes=d["file_size_bytes"],
                    file_format=d["file_format"],
                    status=d.get("status", "Uploaded"),
                    sample_count=d.get("sample_count"),
                    feature_count=d.get("feature_count"),
                    content_hash=d.get("content_hash"),
                    matrix_orientation=d.get("matrix_orientation", "features_as_rows"),
                    feature_id_column=d.get("feature_id_column"),
                    sample_id_column=d.get("sample_id_column"),
                    quality_assessment=d.get("quality_assessment"),
                    group_mappings=d.get("group_mappings"),
                    title=d.get("title"),
                    domain=d.get("domain", "Cancer Gene-Expression"),
                    organism=d.get("organism"),
                    tissue=d.get("tissue"),
                    experimental_condition=d.get("experimental_condition"),
                    control_group=d.get("control_group"),
                    treatment_group=d.get("treatment_group"),
                    measurement_type=d.get("measurement_type"),
                    data_source=d.get("data_source"),
                    publication_reference=d.get("publication_reference"),
                    created_at=parse_dt(d.get("created_at")),
                )
                pg_session.add(ds)
                migrated_counts["datasets"] += 1
        pg_session.commit()

        # Migrate experiments
        cur.execute("SELECT * FROM experiments")
        exp_rows = cur.fetchall()
        migrated_counts["experiments"] = 0
        for row in exp_rows:
            d = dict(row)
            existing = pg_session.get(models.Experiment, d["id"])
            if not existing:
                e = models.Experiment(
                    id=d["id"],
                    project_id=d["project_id"],
                    dataset_id=d.get("dataset_id"),
                    owner_id=d["owner_id"],
                    title=d["title"],
                    description=d.get("description"),
                    code=d.get("code"),
                    status=d.get("status", models.ExperimentStatus.QUEUED.value),
                    started_at=parse_dt(d.get("started_at")),
                    completed_at=parse_dt(d.get("completed_at")),
                    duration_seconds=d.get("duration_seconds"),
                    exit_code=d.get("exit_code"),
                    stdout=d.get("stdout"),
                    stderr=d.get("stderr"),
                    result_summary=d.get("result_summary"),
                    artifacts=d.get("artifacts"),
                    failure_reason=d.get("failure_reason"),
                    experiment_type=d.get("experiment_type", "differential_expression_welch"),
                    dataset_hash=d.get("dataset_hash"),
                    reproducibility_manifest=d.get("reproducibility_manifest"),
                    statistical_summary=d.get("statistical_summary"),
                    created_at=parse_dt(d.get("created_at")),
                    updated_at=parse_dt(d.get("updated_at")),
                )
                pg_session.add(e)
                migrated_counts["experiments"] += 1
        pg_session.commit()

        logger.info(f"Migration completed successfully. Record counts: {migrated_counts}")
        return migrated_counts
    except Exception as exc:
        pg_session.rollback()
        logger.error(f"Migration error: {exc}")
        raise
    finally:
        sqlite_conn.close()
        pg_session.close()


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    migrate_data()

