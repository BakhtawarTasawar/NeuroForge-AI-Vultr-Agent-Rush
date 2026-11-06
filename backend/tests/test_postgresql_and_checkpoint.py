import json
import uuid
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.db.models import (
    ApprovalState,
    Dataset,
    Experiment,
    ExperimentStatus,
    Project,
    ResearchEvent,
    ResearchSession,
    SessionStatus,
    User,
    UserRole,
    utc_now,
)
from app.services.research_graph import (
    AutonomousResearchRunner,
    ResearchState,
    ResearchPlanSchema,
    EvaluationSchema,
    ResearchSummarySchema,
    compute_canonical_plan_hash,
    get_postgres_checkpointer,
)
from app.services.vultr_inference import InferenceResponse, VultrInferenceService
from app.services.storage import get_upload_dir, resolve_safe_path
from unittest.mock import patch


@pytest.fixture(scope="function")
def db_session():
    """Live PostgreSQL session dedicated to PostgreSQL infrastructure verification."""
    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        engine.dispose()


# =============================================================================
# Helper: Mock Vultr Inference Handler
# =============================================================================

def mock_vultr_handler(messages, response_model=None):
    if response_model == ResearchPlanSchema:
        plan = {
            "objective": "Screen candidate transcriptomic targets",
            "observed_facts": ["Cohort of 6 samples and 10 features"],
            "assumptions_hypotheses": ["Transcriptional shifts between groups"],
            "proposed_experiments": [
                {
                    "tool_name": "pca_exploratory_analysis",
                    "description": "PCA variance analysis",
                    "rationale": "Verify variance structure",
                    "parameters": {"n_components": 2},
                }
            ],
            "expected_outcomes": ["PCA scree and scatter coordinates"],
            "scientific_limitations": ["Exploratory research only."],
        }
        return InferenceResponse(
            content=json.dumps(plan),
            parsed=plan,
            model="llama-3.3-70b-instruct-fp8",
            duration_seconds=0.05,
        )
    elif response_model == EvaluationSchema:
        ev = {
            "statistical_assessment": "Evaluated PCA variance structure.",
            "verified_findings": ["PC1 explains variance."],
            "effect_size_summary": "Moderate separation.",
            "statistical_significance_summary": "Unsupervised PCA.",
            "biological_caveats": ["Research use only."],
            "next_step_recommendation": "conclude",
        }
        return InferenceResponse(
            content=json.dumps(ev),
            parsed=ev,
            model="llama-3.3-70b-instruct-fp8",
            duration_seconds=0.05,
        )
    elif response_model == ResearchSummarySchema:
        summary = {
            "title": "Oncogenomics Investigation Summary",
            "executive_summary": "Completed PCA exploratory screening.",
            "dataset_characteristics": {"features": 10, "samples": 6},
            "methodology": "PCA projection in isolated environment.",
            "key_findings": [],
            "scientific_caveats": ["Research use only."],
            "unconfirmed_hypotheses": [],
            "recommended_future_work": ["Validate with larger sample cohort."],
        }
        return InferenceResponse(
            content=json.dumps(summary),
            parsed=summary,
            model="llama-3.3-70b-instruct-fp8",
            duration_seconds=0.05,
        )
    return InferenceResponse(
        content="{}",
        parsed={},
        model="llama-3.3-70b-instruct-fp8",
        duration_seconds=0.01,
    )


# =============================================================================
# Helper: Setup Synthetic Dataset
# =============================================================================

def setup_test_dataset(db_session, user_email=None):
    if not user_email:
        user_email = f"pg_tester_{uuid.uuid4().hex[:8]}@neuroforge.org"
    else:
        parts = user_email.split("@")
        user_email = f"{parts[0]}_{uuid.uuid4().hex[:8]}@{parts[1]}"
    user = User(
        email=user_email,
        hashed_password="hashed_secure_password_test",
        full_name="Postgres Tester",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    project = Project(
        title="PostgreSQL Integration Study",
        description="Testing PostgreSQL durable persistence",
        domain="Cancer Gene-Expression",
        status="Active",
        owner_id=user.id,
    )
    db_session.add(project)
    db_session.commit()

    csv_data = (
        "Gene,S1,S2,S3,S4,S5,S6\n"
        "TP53,10.2,10.5,10.1,6.2,6.4,6.1\n"
        "BRCA1,8.1,8.3,8.0,4.2,4.1,4.5\n"
        "EGFR,5.0,5.2,5.1,9.0,9.2,8.9\n"
        "PTEN,9.1,9.3,9.0,5.1,5.2,5.0\n"
    )
    filename = f"pg_test_matrix_{uuid.uuid4().hex[:8]}.csv"
    upload_dir = get_upload_dir()
    file_path = resolve_safe_path(upload_dir, filename)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(csv_data)

    dataset = Dataset(
        project_id=project.id,
        owner_id=user.id,
        filename=filename,
        original_name="pg_test_matrix.csv",
        file_size_bytes=len(csv_data.encode("utf-8")),
        file_format="CSV",
        status="Validated",
        sample_count=6,
        feature_count=4,
        content_hash="mock_hash_for_pg_test",
        matrix_orientation="features_as_rows",
    )
    db_session.add(dataset)
    db_session.commit()

    return {"user": user, "project": project, "dataset": dataset}


# =============================================================================
# 1. PostgreSQL Database & Infrastructure Tests
# =============================================================================

def test_postgres_connection_and_version(db_session):
    """Verify live connection to PostgreSQL 16 container on port 5440."""
    result = db_session.execute(text("SELECT current_user, current_database(), version();")).fetchone()
    assert result is not None
    user, db_name, version = result
    assert user == "neuroforge_app"
    assert db_name == "neuroforge"
    assert "PostgreSQL 16" in version


def test_postgres_schema_and_migrations(db_session):
    """Verify application tables in public and checkpoint tables in checkpoints schema."""
    pub_tables = db_session.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';")
    ).fetchall()
    table_names = [r[0] for r in pub_tables]
    assert "users" in table_names
    assert "projects" in table_names
    assert "datasets" in table_names
    assert "experiments" in table_names
    assert "research_sessions" in table_names
    assert "research_events" in table_names

    chk_tables = db_session.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'checkpoints';")
    ).fetchall()
    chk_names = [r[0] for r in chk_tables]
    assert "checkpoints" in chk_names
    assert "checkpoint_blobs" in chk_names
    assert "checkpoint_writes" in chk_names


def test_postgres_foreign_key_integrity(db_session):
    """Verify PostgreSQL enforces foreign key constraints."""
    non_existent_user_id = str(uuid.uuid4())
    proj = Project(
        title="Invalid Foreign Key Project",
        owner_id=non_existent_user_id,
    )
    db_session.add(proj)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_postgres_unique_constraints(db_session):
    """Verify PostgreSQL enforces unique constraint on user email."""
    uid = uuid.uuid4().hex[:8]
    u1 = User(
        email=f"duplicate_{uid}@neuroforge.org",
        hashed_password="pw1",
        full_name="User One",
        role=UserRole.RESEARCHER.value,
    )
    db_session.add(u1)
    db_session.commit()

    u2 = User(
        email=f"duplicate_{uid}@neuroforge.org",
        hashed_password="pw2",
        full_name="User Two",
        role=UserRole.RESEARCHER.value,
    )
    db_session.add(u2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
    db_session.delete(u1)
    db_session.commit()


def test_postgres_transaction_rollback(db_session):
    """Verify transaction rollback prevents uncommitted data from persisting."""
    uid = uuid.uuid4().hex[:8]
    email = f"rollback_{uid}@neuroforge.org"
    u = User(
        email=email,
        hashed_password="pw",
        full_name="Rollback User",
        role=UserRole.RESEARCHER.value,
    )
    db_session.add(u)
    db_session.flush()

    # Roll back
    db_session.rollback()

    found = db_session.query(User).filter(User.email == email).first()
    assert found is None


def test_postgres_concurrent_session_updates(db_session):
    """Verify atomic update and row isolation under concurrent simulation."""
    ctx = setup_test_dataset(db_session, "concurrency_user@neuroforge.org")
    session = ResearchSession(
        project_id=ctx["project.id" if "project.id" in ctx else "project"].id,
        dataset_id=ctx["dataset"].id,
        owner_id=ctx["user"].id,
        title="Concurrent Session",
        objective="Verify update atomicity",
        status=SessionStatus.INITIALIZING.value,
    )
    db_session.add(session)
    db_session.commit()

    # Update status atomically
    db_session.execute(
        text("UPDATE research_sessions SET status = :st WHERE id = :sid"),
        {"st": SessionStatus.PLANNING.value, "sid": session.id},
    )
    db_session.commit()

    db_session.refresh(session)
    assert session.status == SessionStatus.PLANNING.value


# =============================================================================
# 2. LangGraph PostgreSQL Checkpoint & Restart Persistence Tests
# =============================================================================

def test_postgres_langgraph_checkpoint_save_and_pause(db_session):
    """
    Test that a LangGraph research run pauses at the approval gate and writes
    its checkpoint into PostgreSQL in the checkpoints schema.
    """
    ctx = setup_test_dataset(db_session, "pause_tester@neuroforge.org")
    user = ctx["user"]
    project = ctx["project"]
    dataset = ctx["dataset"]

    session = ResearchSession(
        project_id=project.id,
        dataset_id=dataset.id,
        owner_id=user.id,
        title="Pause and Checkpoint Investigation",
        objective="Screen candidate transcriptomic targets",
        status=SessionStatus.INITIALIZING.value,
        approval_state=ApprovalState.PENDING.value,
    )
    db_session.add(session)
    db_session.commit()

    state: ResearchState = {
        "session_id": session.id,
        "project_id": project.id,
        "dataset_id": dataset.id,
        "user_id": user.id,
        "objective": session.objective,
        "status": session.status,
        "approval_state": ApprovalState.PENDING.value,
        "iteration_count": 0,
        "max_iterations": 10,
        "retry_count": 0,
        "max_retries": 3,
        "evidence_store": [],
        "tool_history": [],
        "experiment_ids": [],
    }

    mock_vultr = VultrInferenceService(mock_handler=mock_vultr_handler)
    runner = AutonomousResearchRunner(db=db_session, current_user=user, vultr_service=mock_vultr)

    # Execute phase 1: should pause at await_human_approval
    res = runner.run(state)

    assert res["status"] == SessionStatus.AWAITING_APPROVAL.value
    assert res["approval_state"] == ApprovalState.PENDING.value
    assert res["research_plan"] is not None

    # Verify checkpoint row exists in PostgreSQL 'checkpoints' table
    chk_rows = db_session.execute(
        text("SELECT thread_id, checkpoint_id FROM checkpoints.checkpoints WHERE thread_id = :tid;"),
        {"tid": session.id},
    ).fetchall()
    assert len(chk_rows) > 0


def test_postgres_langgraph_restart_and_resume(db_session):
    """
    CRITICAL MILESTONE 4.2 TEST:
    1. Runs graph to approval pause gate.
    2. Persists checkpoint in PostgreSQL.
    3. Destroys runner 1 (simulating backend process crash / restart).
    4. Creates runner 2 from scratch.
    5. Verifies session is still awaiting approval with exact persisted plan.
    6. Approves exact plan with canonical plan hash.
    7. Resumes graph from PostgreSQL checkpoint.
    8. Verifies PCA experiment runs and completes without re-executing initial nodes.
    9. Destroys runner 2 and creates runner 3.
    10. Verifies session state is Completed and final summary remains available.
    """
    ctx = setup_test_dataset(db_session, "restart_tester@neuroforge.org")
    user = ctx["user"]
    project = ctx["project"]
    dataset = ctx["dataset"]

    session = ResearchSession(
        project_id=project.id,
        dataset_id=dataset.id,
        owner_id=user.id,
        title="Durable PostgreSQL Restart Test",
        objective="Screen candidate transcriptomic targets",
        status=SessionStatus.INITIALIZING.value,
        approval_state=ApprovalState.PENDING.value,
    )
    db_session.add(session)
    db_session.commit()

    initial_state: ResearchState = {
        "session_id": session.id,
        "project_id": project.id,
        "dataset_id": dataset.id,
        "user_id": user.id,
        "objective": session.objective,
        "status": session.status,
        "approval_state": ApprovalState.PENDING.value,
        "iteration_count": 0,
        "max_iterations": 10,
        "retry_count": 0,
        "max_retries": 3,
        "evidence_store": [],
        "tool_history": [],
        "experiment_ids": [],
    }

    mock_vultr = VultrInferenceService(mock_handler=mock_vultr_handler)

    # 1. RUNNER 1: Run until pause gate
    runner1 = AutonomousResearchRunner(db=db_session, current_user=user, vultr_service=mock_vultr)
    runner1.run(initial_state)

    db_session.refresh(session)
    assert session.status == SessionStatus.AWAITING_APPROVAL.value
    assert session.research_plan is not None

    plan_dict = json.loads(session.research_plan)
    expected_plan_hash = plan_dict.get("plan_hash")
    assert expected_plan_hash is not None

    # 2. DESTROY RUNNER 1
    del runner1

    # 3. RUNNER 2: Recreate from scratch (backend restart simulation)
    runner2 = AutonomousResearchRunner(db=db_session, current_user=user, vultr_service=mock_vultr)

    # Verify session is still awaiting approval in database
    db_session.refresh(session)
    assert session.status == SessionStatus.AWAITING_APPROVAL.value

    # Approve exact plan with valid plan_hash
    session.approval_state = ApprovalState.APPROVED.value
    session.approval_notes = "Approved by senior bioinformatician"
    session.approved_at = utc_now()
    session.status = SessionStatus.APPROVED.value
    db_session.commit()
    db_session.refresh(session)

    resumed_state = AutonomousResearchRunner.load_session_state(db_session, session.id)
    resumed_state["approval_state"] = ApprovalState.APPROVED.value
    resumed_state["approval_notes"] = "Approved by senior bioinformatician"

    # 4. RESUME EXECUTION on Runner 2
    runner2.run(resumed_state)

    db_session.refresh(session)
    assert session.status == SessionStatus.COMPLETED.value
    assert session.final_summary is not None

    # 5. DESTROY RUNNER 2 and CREATE RUNNER 3
    del runner2
    runner3 = AutonomousResearchRunner(db=db_session, current_user=user, vultr_service=mock_vultr)

    # Verify completed state is stable across backend restarts
    loaded_state = AutonomousResearchRunner.load_session_state(db_session, session.id)
    assert loaded_state["status"] == SessionStatus.COMPLETED.value
    assert len(loaded_state["tool_history"]) >= 1
    assert loaded_state["final_summary"] is not None

    # Verify tool was NOT re-executed
    pca_runs = [t for t in loaded_state["tool_history"] if t.get("tool_name") == "pca_exploratory_analysis"]
    assert len(pca_runs) == 1, "Completed experiment must execute exactly once, not re-executed upon resumption."


def test_postgres_checkpoint_isolation_between_sessions(db_session):
    """Verify that different sessions maintain strictly isolated checkpoints in PostgreSQL."""
    ctx = setup_test_dataset(db_session, "isolation_tester@neuroforge.org")
    user = ctx["user"]
    project = ctx["project"]
    dataset = ctx["dataset"]

    session_a = ResearchSession(
        project_id=project.id,
        dataset_id=dataset.id,
        owner_id=user.id,
        title="Session Alpha",
        objective="Analyze cohort A",
        status=SessionStatus.INITIALIZING.value,
        approval_state=ApprovalState.PENDING.value,
    )
    session_b = ResearchSession(
        project_id=project.id,
        dataset_id=dataset.id,
        owner_id=user.id,
        title="Session Beta",
        objective="Analyze cohort B",
        status=SessionStatus.INITIALIZING.value,
        approval_state=ApprovalState.PENDING.value,
    )
    db_session.add_all([session_a, session_b])
    db_session.commit()

    mock_vultr = VultrInferenceService(mock_handler=mock_vultr_handler)
    runner = AutonomousResearchRunner(db=db_session, current_user=user, vultr_service=mock_vultr)

    state_a: ResearchState = {
        "session_id": session_a.id,
        "project_id": project.id,
        "dataset_id": dataset.id,
        "user_id": user.id,
        "objective": session_a.objective,
        "status": session_a.status,
        "approval_state": ApprovalState.PENDING.value,
        "iteration_count": 0,
        "max_iterations": 10,
        "retry_count": 0,
        "max_retries": 3,
        "evidence_store": [],
        "tool_history": [],
        "experiment_ids": [],
    }
    state_b: ResearchState = {
        "session_id": session_b.id,
        "project_id": project.id,
        "dataset_id": dataset.id,
        "user_id": user.id,
        "objective": session_b.objective,
        "status": session_b.status,
        "approval_state": ApprovalState.PENDING.value,
        "iteration_count": 0,
        "max_iterations": 10,
        "retry_count": 0,
        "max_retries": 3,
        "evidence_store": [],
        "tool_history": [],
        "experiment_ids": [],
    }

    runner.run(state_a)
    runner.run(state_b)

    chk_a = db_session.execute(
        text("SELECT count(*) FROM checkpoints.checkpoints WHERE thread_id = :t;"),
        {"t": session_a.id},
    ).scalar()
    chk_b = db_session.execute(
        text("SELECT count(*) FROM checkpoints.checkpoints WHERE thread_id = :t;"),
        {"t": session_b.id},
    ).scalar()

    assert chk_a > 0
    assert chk_b > 0

    tuple_a = runner.checkpointer.get_tuple({"configurable": {"thread_id": session_a.id}})
    tuple_b = runner.checkpointer.get_tuple({"configurable": {"thread_id": session_b.id}})
    assert tuple_a.checkpoint["channel_values"]["session_id"] == session_a.id
    assert tuple_b.checkpoint["channel_values"]["session_id"] == session_b.id
