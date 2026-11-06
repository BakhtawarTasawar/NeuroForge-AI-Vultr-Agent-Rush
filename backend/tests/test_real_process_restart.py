import json
import os
import subprocess
import sys
import uuid
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.security import get_password_hash
from app.db.models import (
    ApprovalState,
    Dataset,
    Project,
    ResearchSession,
    SessionStatus,
    User,
    UserRole,
)
from app.services.storage import get_upload_dir, resolve_safe_path


def test_real_os_process_restart_and_checkpoint_recovery():
    """
    CRITICAL MANDATORY VERIFICATION:
    Proves durable persistence across ACTUAL backend process crashes / restarts.
    1. Initializes research session in PostgreSQL.
    2. Spawns OS Process A via subprocess.run() -> executes until LangGraph approval pause gate.
    3. Confirms OS Process A has fully terminated (PID dead, code 0).
    4. Validates checkpoint row in PostgreSQL `checkpoints.checkpoints` table.
    5. Spawns completely independent OS Process B -> reads session & checkpoint from PostgreSQL.
    6. Validates plan hash, approves plan, resumes execution through to completion.
    7. Confirms OS Process B has fully terminated (PID dead, code 0).
    8. Validates session status is Completed, summary is generated, and tools were not re-executed.
    """
    pg_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    PgSession = sessionmaker(autocommit=False, autoflush=False, bind=pg_engine)
    db = PgSession()

    test_uid = str(uuid.uuid4())
    user_email = f"restart_tester_{test_uid[:8]}@neuroforge.org"
    user = User(
        email=user_email,
        hashed_password=get_password_hash("ValidPass123"),
        full_name="Process Restart Tester",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db.add(user)
    db.commit()

    project = Project(
        title=f"OS Restart Project {test_uid[:8]}",
        description="Testing true OS process independence and PostgreSQL persistence",
        domain="Cancer Gene-Expression",
        status="Active",
        owner_id=user.id,
    )
    db.add(project)
    db.commit()

    csv_content = (
        "Gene,S1,S2,S3,S4,S5,S6\n"
        "TP53,10.2,10.5,10.1,6.2,6.4,6.1\n"
        "BRCA1,8.1,8.3,8.0,4.2,4.1,4.5\n"
        "EGFR,5.0,5.2,5.1,9.0,9.2,8.9\n"
        "MYC,7.2,7.0,7.1,7.2,7.3,7.1\n"
        "PTEN,9.1,9.3,9.0,5.1,5.2,5.0\n"
        "CDKN2A,4.5,4.7,4.6,8.2,8.4,8.1\n"
        "VEGFA,6.1,6.3,6.2,6.0,6.2,6.1\n"
        "RB1,7.8,7.9,7.7,4.0,4.2,4.1\n"
        "MDM2,5.5,5.4,5.6,5.5,5.6,5.4\n"
        "KRAS,8.8,8.9,8.7,8.6,8.8,8.7\n"
    )
    filename = f"test_matrix_{test_uid[:8]}.csv"
    upload_dir = get_upload_dir()
    file_path = resolve_safe_path(upload_dir, filename)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(csv_content)

    group_mappings = {
        "S1": "Control",
        "S2": "Control",
        "S3": "Control",
        "S4": "Treatment",
        "S5": "Treatment",
        "S6": "Treatment",
    }

    dataset = Dataset(
        project_id=project.id,
        owner_id=user.id,
        filename=filename,
        original_name="test_matrix.csv",
        file_size_bytes=len(csv_content.encode("utf-8")),
        file_format="CSV",
        status="Validated",
        sample_count=6,
        feature_count=10,
        content_hash="mockhash_restart",
        matrix_orientation="features_as_rows",
        control_group="Control",
        treatment_group="Treatment",
        group_mappings=json.dumps(group_mappings),
    )
    db.add(dataset)
    db.commit()

    session = ResearchSession(
        project_id=project.id,
        dataset_id=dataset.id,
        owner_id=user.id,
        title="OS Process Crash & Restart Test",
        objective="Verify true OS process independence and PostgreSQL checkpoint recovery",
        status=SessionStatus.INITIALIZING.value,
        approval_state=ApprovalState.PENDING.value,
    )
    db.add(session)
    db.commit()
    session_id = session.id

    worker_script = os.path.join(os.path.dirname(__file__), "helpers", "process_restart_worker.py")

    try:
        # -------------------------------------------------------------------------
        # PHASE A: Execute in Process A (Runs until human approval gate, then terminates)
        # -------------------------------------------------------------------------
        proc_a = subprocess.run(
            [sys.executable, "-u", worker_script, "--step", "start_and_pause", "--session-id", session_id],
            capture_output=True,
            text=True,
            timeout=120,
        )

        print("Process A stdout:", proc_a.stdout)
        if proc_a.returncode != 0:
            print("Process A stderr:", proc_a.stderr)
        assert proc_a.returncode == 0, f"Process A exited with error: {proc_a.stderr}\nStdout: {proc_a.stdout}"

        # Verify session in database is Awaiting Approval with a plan hash
        db.expire_all()
        session_a = db.query(ResearchSession).filter(ResearchSession.id == session_id).first()
        assert session_a.status == SessionStatus.AWAITING_APPROVAL.value
        assert session_a.approval_state == ApprovalState.PENDING.value
        assert session_a.research_plan is not None

        plan_dict = json.loads(session_a.research_plan)
        plan_hash = plan_dict.get("plan_hash")
        assert plan_hash is not None and len(plan_hash) == 64

        # Verify durable checkpoint in PostgreSQL checkpoints schema
        chk_rows = db.execute(
            text("SELECT thread_id, checkpoint_id FROM checkpoints.checkpoints WHERE thread_id = :tid;"),
            {"tid": session_id},
        ).fetchall()
        assert len(chk_rows) > 0, "PostgreSQL checkpoints schema must contain durable checkpoint from Process A"

        # -------------------------------------------------------------------------
        # PHASE B: Execute in Process B (Fresh OS process, resumes from checkpoint)
        # -------------------------------------------------------------------------
        proc_b = subprocess.run(
            [
                sys.executable,
                "-u",
                worker_script,
                "--step",
                "approve_and_resume",
                "--session-id",
                session_id,
                "--plan-hash",
                plan_hash,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        print("Process B stdout:", proc_b.stdout)
        if proc_b.returncode != 0:
            print("Process B stderr:", proc_b.stderr)
        assert proc_b.returncode == 0, f"Process B exited with error: {proc_b.stderr}\nStdout: {proc_b.stdout}"

        # -------------------------------------------------------------------------
        # PHASE C: Verify final state in PostgreSQL
        # -------------------------------------------------------------------------
        db.expire_all()
        session_final = db.query(ResearchSession).filter(ResearchSession.id == session_id).first()
        assert session_final.status == SessionStatus.COMPLETED.value
        assert session_final.approval_state == ApprovalState.APPROVED.value
        assert session_final.final_summary is not None

        # Verify tool execution occurred exactly once (no duplicated work)
        tools = json.loads(session_final.tool_history) if session_final.tool_history else []
        pca_tools = [t for t in tools if t.get("tool_name") == "pca_exploratory_analysis"]
        assert len(pca_tools) == 1, "Scientific experiment must execute exactly once across process restart."

    finally:
        # Clean up test data and checkpoints
        try:
            db.execute(text("DELETE FROM checkpoints.checkpoints WHERE thread_id = :tid;"), {"tid": session_id})
            db.execute(text("DELETE FROM checkpoints.checkpoint_blobs WHERE thread_id = :tid;"), {"tid": session_id})
            db.execute(text("DELETE FROM checkpoints.checkpoint_writes WHERE thread_id = :tid;"), {"tid": session_id})
            db.execute(text("DELETE FROM research_events WHERE session_id = :tid;"), {"tid": session_id})
            db.delete(session)
            db.delete(dataset)
            db.delete(project)
            db.delete(user)
            db.commit()
        except Exception:
            pass
        db.close()
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass
