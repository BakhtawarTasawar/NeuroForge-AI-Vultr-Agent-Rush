import json
import logging
import threading
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_roles, verify_csrf
from app.db.models import (
    ApprovalState,
    Dataset,
    Project,
    ResearchEvent,
    ResearchSession,
    SessionStatus,
    User,
    UserRole,
    utc_now,
)

require_researcher_or_admin = require_roles([UserRole.ADMIN, UserRole.RESEARCHER])
from app.schemas.models import (
    ApprovalDecisionRequest,
    ResearchEventResponse,
    ResearchEvidenceResponse,
    ResearchPlanResponse,
    ResearchSessionCreateRequest,
    ResearchSessionResponse,
    ResearchSummaryResponse,
)
from app.services.research_graph import AutonomousResearchRunner, ResearchState, record_session_event

logger = logging.getLogger("neuroforge.api.agent_research")

router = APIRouter(tags=["Autonomous Research Agent"])

_session_locks = {}
_session_locks_guard = threading.Lock()

def _get_session_lock(session_id: str) -> threading.Lock:
    with _session_locks_guard:
        if session_id not in _session_locks:
            _session_locks[session_id] = threading.Lock()
        return _session_locks[session_id]


def _serialize_session(session: ResearchSession) -> ResearchSessionResponse:
    """Format DB model into ResearchSessionResponse schema."""
    return ResearchSessionResponse(
        id=session.id,
        project_id=session.project_id,
        dataset_id=session.dataset_id,
        owner_id=session.owner_id,
        owner_name=session.owner.full_name if session.owner else None,
        title=session.title,
        objective=session.objective,
        dataset_hash=session.dataset_hash,
        status=session.status,
        current_step=session.current_step,
        approval_state=session.approval_state,
        approval_notes=session.approval_notes,
        approved_at=session.approved_at,
        research_plan=json.loads(session.research_plan) if session.research_plan else None,
        experiment_ids=json.loads(session.experiment_ids) if session.experiment_ids else [],
        tool_history=json.loads(session.tool_history) if session.tool_history else [],
        evidence_store=json.loads(session.evidence_store) if session.evidence_store else [],
        final_summary=json.loads(session.final_summary) if session.final_summary else None,
        failure_reason=session.failure_reason,
        iteration_count=session.iteration_count,
        max_iterations=session.max_iterations,
        retry_count=session.retry_count,
        max_retries=session.max_retries,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _check_project_access(project_id: str, user: User, db: Session) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    if user.role != UserRole.ADMIN.value and project.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this project.")
    return project


def _check_session_access(session_id: str, user: User, db: Session) -> ResearchSession:
    session = db.query(ResearchSession).filter(ResearchSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research session not found.")
    if user.role != UserRole.ADMIN.value and session.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this research session.")
    return session


@router.post("/projects/{project_id}/research-sessions", response_model=ResearchSessionResponse, status_code=status.HTTP_201_CREATED)
def create_and_start_research_session(
    project_id: str,
    payload: ResearchSessionCreateRequest,
    current_user: User = Depends(require_researcher_or_admin),
    db: Session = Depends(get_db),
):
    """
    Launch an autonomous scientific research session.
    The agent initializes, inspects the dataset, computes initial evidence,
    generates a structured research plan, and enters the 'Awaiting Approval' safety gate.
    """
    project = _check_project_access(project_id, current_user, db)

    dataset = db.query(Dataset).filter(Dataset.id == payload.dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Specified dataset not found.")

    if current_user.role != UserRole.ADMIN.value and dataset.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access the specified dataset.",
        )

    if dataset.project_id != project.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dataset is not attached to this research project.",
        )

    # Create persistent session record
    session = ResearchSession(
        project_id=project.id,
        dataset_id=dataset.id,
        owner_id=current_user.id,
        title=payload.title,
        objective=payload.objective,
        dataset_hash=dataset.content_hash,
        status=SessionStatus.INITIALIZING.value,
        current_step="initialize_research",
        approval_state=ApprovalState.PENDING.value,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    # Initial state
    initial_state: ResearchState = {
        "session_id": session.id,
        "project_id": session.project_id,
        "dataset_id": session.dataset_id,
        "user_id": current_user.id,
        "objective": session.objective,
        "dataset_hash": session.dataset_hash,
        "status": session.status,
        "current_step": session.current_step,
        "approval_state": session.approval_state,
        "group_a_name": payload.group_a_name,
        "group_b_name": payload.group_b_name,
        "group_mappings": payload.group_mappings,
        "iteration_count": 0,
        "max_iterations": 10,
        "retry_count": 0,
        "max_retries": 3,
        "evidence_store": [],
        "tool_history": [],
        "experiment_ids": [],
    }

    # Execute LangGraph until approval pause gate or completion
    runner = AutonomousResearchRunner(db=db, current_user=current_user)
    runner.run(initial_state)

    db.refresh(session)
    return _serialize_session(session)


@router.get("/projects/{project_id}/research-sessions", response_model=List[ResearchSessionResponse])
def list_project_research_sessions(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all autonomous research sessions for a project."""
    _check_project_access(project_id, current_user, db)
    sessions = (
        db.query(ResearchSession)
        .filter(ResearchSession.project_id == project_id)
        .order_by(ResearchSession.created_at.desc())
        .all()
    )
    return [_serialize_session(s) for s in sessions]


@router.get("/research-sessions/{session_id}", response_model=ResearchSessionResponse)
def get_research_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve full details of a specific research session."""
    session = _check_session_access(session_id, current_user, db)
    return _serialize_session(session)


@router.post("/research-sessions/{session_id}/approve", response_model=ResearchSessionResponse)
def approve_research_plan(
    session_id: str,
    decision_payload: Optional[ApprovalDecisionRequest] = None,
    current_user: User = Depends(require_researcher_or_admin),
    db: Session = Depends(get_db),
):
    """
    Approve the research plan.
    Resumes LangGraph execution: selects tools, runs sandbox experiments,
    evaluates findings, and synthesizes the research report.
    Guarded by non-blocking session concurrency lock to prevent duplicate execution.
    """
    lock = _get_session_lock(session_id)
    acquired = lock.acquire(blocking=False)
    if not acquired:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Research session is currently being processed by another operation. Please wait.",
        )

    try:
        session = _check_session_access(session_id, current_user, db)

        # Reject cannot be approved
        if session.status == SessionStatus.REJECTED.value or session.approval_state == ApprovalState.REJECTED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot approve a previously rejected research session.",
            )

        # Idempotent return if already approved/completed
        if session.status not in (SessionStatus.AWAITING_APPROVAL.value, SessionStatus.PLANNING.value):
            if session.approval_state == ApprovalState.APPROVED.value:
                return _serialize_session(session)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot approve session in '{session.status}' state.",
            )

        # Verify research plan exists
        if not session.research_plan:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot approve session before research plan has been generated.",
            )

        # Verify plan hash if provided to prevent approval of mutated/stale plans
        plan_data = json.loads(session.research_plan)
        current_plan_hash = plan_data.get("plan_hash")
        if decision_payload and decision_payload.plan_hash:
            if current_plan_hash and decision_payload.plan_hash != current_plan_hash:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Plan hash mismatch: the research plan has been altered since review.",
                )

        notes = decision_payload.notes if decision_payload else None
        session.approval_state = ApprovalState.APPROVED.value
        session.approval_notes = notes
        session.approved_at = utc_now()
        session.approved_by_id = current_user.id
        session.status = SessionStatus.APPROVED.value
        db.commit()
        db.refresh(session)

        # Resume LangGraph execution
        state = AutonomousResearchRunner.load_session_state(db, session_id)
        state["approval_state"] = ApprovalState.APPROVED.value
        state["approval_notes"] = notes

        runner = AutonomousResearchRunner(db=db, current_user=current_user)
        runner.run(state)

        db.refresh(session)
        return _serialize_session(session)
    finally:
        lock.release()


@router.post("/research-sessions/{session_id}/reject", response_model=ResearchSessionResponse)
def reject_research_plan(
    session_id: str,
    decision_payload: ApprovalDecisionRequest,
    current_user: User = Depends(require_researcher_or_admin),
    db: Session = Depends(get_db),
):
    """
    Reject the research plan.
    Transitions session to REJECTED and records rejection notes.
    """
    lock = _get_session_lock(session_id)
    acquired = lock.acquire(blocking=False)
    if not acquired:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Research session is currently being processed by another operation.",
        )

    try:
        session = _check_session_access(session_id, current_user, db)

        if session.status == SessionStatus.COMPLETED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot reject an already completed research session.",
            )

        session.approval_state = ApprovalState.REJECTED.value
        session.approval_notes = decision_payload.notes
        session.status = SessionStatus.REJECTED.value
        session.failure_reason = f"Plan rejected by researcher: {decision_payload.notes or 'No reason specified'}"
        db.commit()

        record_session_event(
            db,
            session.id,
            "PLAN_REJECTED",
            "await_human_approval",
            f"Research plan rejected: {decision_payload.notes}",
            {"rejection_notes": decision_payload.notes},
        )

        db.refresh(session)
        return _serialize_session(session)
    finally:
        lock.release()


@router.post("/research-sessions/{session_id}/continue", response_model=ResearchSessionResponse)
def continue_research_session(
    session_id: str,
    current_user: User = Depends(require_researcher_or_admin),
    db: Session = Depends(get_db),
):
    """Resume execution of an approved or paused research session."""
    lock = _get_session_lock(session_id)
    acquired = lock.acquire(blocking=False)
    if not acquired:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Research session is currently being processed by another operation.",
        )

    try:
        session = _check_session_access(session_id, current_user, db)

        if session.status == SessionStatus.COMPLETED.value:
            return _serialize_session(session)
        if session.status == SessionStatus.REJECTED.value or session.approval_state == ApprovalState.REJECTED.value:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot continue a rejected session.")
        if session.status == SessionStatus.AWAITING_APPROVAL.value and session.approval_state != ApprovalState.APPROVED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot continue session awaiting human approval without explicit plan approval.",
            )

        state = AutonomousResearchRunner.load_session_state(db, session_id)
        runner = AutonomousResearchRunner(db=db, current_user=current_user)
        runner.run(state)

        db.refresh(session)
        return _serialize_session(session)
    finally:
        lock.release()


@router.get("/research-sessions/{session_id}/events", response_model=List[ResearchEventResponse])
def get_session_events(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get chronological timeline of events for a research session."""
    _check_session_access(session_id, current_user, db)
    events = (
        db.query(ResearchEvent)
        .filter(ResearchEvent.session_id == session_id)
        .order_by(ResearchEvent.created_at.asc())
        .all()
    )

    result = []
    for ev in events:
        payload_data = None
        if ev.payload:
            try:
                payload_data = json.loads(ev.payload)
            except Exception:
                payload_data = {"raw": ev.payload}

        result.append(
            ResearchEventResponse(
                id=ev.id,
                session_id=ev.session_id,
                event_type=ev.event_type,
                step_name=ev.step_name,
                message=ev.message,
                payload=payload_data,
                created_at=ev.created_at,
            )
        )
    return result


@router.get("/research-sessions/{session_id}/evidence", response_model=ResearchEvidenceResponse)
def get_session_evidence(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get the accumulated empirical evidence store for a research session."""
    session = _check_session_access(session_id, current_user, db)
    items = json.loads(session.evidence_store) if session.evidence_store else []
    return ResearchEvidenceResponse(session_id=session.id, evidence_items=items)


@router.get("/research-sessions/{session_id}/summary", response_model=ResearchSummaryResponse)
def get_session_summary(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get the structured final scientific research report."""
    session = _check_session_access(session_id, current_user, db)
    summary_data = json.loads(session.final_summary) if session.final_summary else None
    return ResearchSummaryResponse(
        session_id=session.id,
        status=session.status,
        final_summary=summary_data,
    )
