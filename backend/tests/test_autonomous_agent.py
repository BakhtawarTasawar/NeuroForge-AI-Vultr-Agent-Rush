import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi import status

from app.core.security import get_password_hash, create_access_token
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
)
from app.services.research_graph import (
    AutonomousResearchRunner,
    ResearchState,
    ResearchPlanSchema,
    EvaluationSchema,
    ResearchSummarySchema,
)
from app.services.scientific_tools import (
    DatasetInspectInput,
    DatasetQualityInput,
    PCAAnalysisInput,
    DifferentialExpressionInput,
    ScientificToolRegistry,
)
from app.services.vultr_inference import (
    InferenceResponse,
    VultrInferenceAuthError,
    VultrInferenceService,
)
from app.services.storage import get_upload_dir, resolve_safe_path


# =============================================================================
# Mock Vultr Inference Handler
# =============================================================================

def mock_vultr_handler(messages, response_model=None):
    """Zero-cost mock handler returning valid schema responses for testing."""
    if response_model == ResearchPlanSchema:
        parsed_plan = {
            "objective": "Screen candidate differentially expressed genes with FDR < 0.05",
            "observed_facts": [
                "Dataset contains 20 features and 6 samples",
                "Scale inferred as log2_transformed",
                "Quality assessment: Ready for differential screening",
            ],
            "assumptions_hypotheses": [
                "Transcriptional profiles will exhibit significant separation between Control and Treatment",
            ],
            "proposed_experiments": [
                {
                    "tool_name": "pca_exploratory_analysis",
                    "description": "Exploratory PCA for sample cohort",
                    "rationale": "Assess overall variance structure",
                    "parameters": {"n_components": 2},
                },
                {
                    "tool_name": "differential_expression_screening",
                    "description": "Welch's t-test with Benjamini-Hochberg FDR correction",
                    "rationale": "Identify significantly dysregulated features",
                    "parameters": {"fdr_threshold": 0.05, "alpha": 0.05},
                },
            ],
            "expected_outcomes": [
                "Principal components accounting for majority variance",
                "Differentially expressed features meeting q < 0.05",
            ],
            "scientific_limitations": [
                "Observational transcriptomic cohort; research use only.",
            ],
        }
        return InferenceResponse(
            content=json.dumps(parsed_plan),
            parsed=parsed_plan,
            model="llama-3.3-70b-instruct-fp8",
            prompt_tokens=150,
            completion_tokens=200,
            total_tokens=350,
            duration_seconds=0.05,
        )

    elif response_model == EvaluationSchema:
        parsed_eval = {
            "statistical_assessment": "Calculated Welch's t-test with FDR correction. Multiple features exhibit significant dysregulation.",
            "verified_findings": [
                "Feature GENE_01 exhibited log2 fold change of 2.15 with FDR q = 0.002",
                "Feature GENE_02 exhibited log2 fold change of -1.80 with FDR q = 0.005",
            ],
            "effect_size_summary": "Substantial effect sizes observed for top candidates.",
            "statistical_significance_summary": "Benjamini-Hochberg FDR controlled at 0.05 threshold.",
            "biological_caveats": [
                "Findings are preliminary and require independent biological assay validation.",
            ],
            "next_step_recommendation": "conclude",
        }
        return InferenceResponse(
            content=json.dumps(parsed_eval),
            parsed=parsed_eval,
            model="llama-3.3-70b-instruct-fp8",
            prompt_tokens=200,
            completion_tokens=150,
            total_tokens=350,
            duration_seconds=0.05,
        )

    elif response_model == ResearchSummarySchema:
        parsed_summary = {
            "title": "Comprehensive Transcriptomic Investigation: Primary Tumor vs Control",
            "executive_summary": "Autonomous scientific research pipeline executed exploratory PCA and Welch's t-test screening.",
            "dataset_characteristics": {
                "feature_count": 20,
                "sample_count": 6,
                "scale": "log2_transformed",
            },
            "methodology": "Two-sample Welch's t-test with Benjamini-Hochberg false discovery rate control executed in isolated Docker sandbox.",
            "key_findings": [
                {
                    "feature_name": "GENE_01",
                    "log2_fold_change": 2.15,
                    "fdr_q_value": 0.002,
                    "regulation_direction": "Upregulated",
                    "biological_context": "Candidate transcriptional activator",
                },
                {
                    "feature_name": "GENE_02",
                    "log2_fold_change": -1.80,
                    "fdr_q_value": 0.005,
                    "regulation_direction": "Downregulated",
                    "biological_context": "Candidate tumor suppressor biomarker",
                },
            ],
            "scientific_caveats": [
                "Research platform only; not intended for clinical diagnostics or therapeutic decisions.",
                "Identified targets require orthogonal verification (e.g. qPCR or western blot).",
            ],
            "unconfirmed_hypotheses": [
                "GENE_01 upregulation may correlate with hyperactivation of proliferation pathways.",
            ],
            "recommended_future_work": [
                "Perform targeted qPCR validation in extended patient cohorts.",
            ],
        }
        return InferenceResponse(
            content=json.dumps(parsed_summary),
            parsed=parsed_summary,
            model="llama-3.3-70b-instruct-fp8",
            prompt_tokens=300,
            completion_tokens=250,
            total_tokens=550,
            duration_seconds=0.08,
        )

    else:
        return InferenceResponse(
            content="Standard inference response",
            parsed={"status": "ok"},
            model="llama-3.3-70b-instruct-fp8",
            prompt_tokens=50,
            completion_tokens=20,
            total_tokens=70,
            duration_seconds=0.02,
        )


# =============================================================================
# 1. Vultr Inference Service Tests
# =============================================================================

def test_vultr_inference_no_key_raises_auth_error():
    service = VultrInferenceService(api_key="")
    with pytest.raises(VultrInferenceAuthError) as exc_info:
        service.chat_completion(messages=[{"role": "user", "content": "Hello"}])
    assert "API key is not configured" in str(exc_info.value)


def test_vultr_inference_mock_handler_works():
    service = VultrInferenceService(mock_handler=mock_vultr_handler)
    res = service.chat_completion(
        messages=[{"role": "user", "content": "Plan an experiment"}],
        response_model=ResearchPlanSchema,
    )
    assert res.provider == "Vultr Serverless Inference"
    assert res.parsed is not None
    assert "observed_facts" in res.parsed
    assert len(res.parsed["proposed_experiments"]) == 2


# =============================================================================
# 2. Scientific Tool Registry Tests
# =============================================================================

def test_scientific_tool_registry_inspection_and_quality(db_session, test_dataset_fixture):
    user = test_dataset_fixture["user"]
    dataset = test_dataset_fixture["dataset"]

    inspect_out = ScientificToolRegistry.inspect_dataset(
        DatasetInspectInput(dataset_id=dataset.id),
        current_user=user,
        db=db_session,
    )
    assert inspect_out.sample_count == 6
    assert inspect_out.feature_count == 10
    assert inspect_out.scale_inference == "log2_transformed"

    quality_out = ScientificToolRegistry.assess_dataset_quality(
        DatasetQualityInput(
            dataset_id=dataset.id,
            group_a_name="Control",
            group_b_name="Treatment",
            group_mappings=test_dataset_fixture["group_mappings"],
        ),
        current_user=user,
        db=db_session,
    )
    assert quality_out.is_ready_for_welch_t is True
    assert quality_out.missing_cells_count == 0


def test_scientific_tool_registry_pca(db_session, test_dataset_fixture):
    user = test_dataset_fixture["user"]
    dataset = test_dataset_fixture["dataset"]

    pca_out = ScientificToolRegistry.run_pca_analysis(
        PCAAnalysisInput(dataset_id=dataset.id, n_components=2),
        current_user=user,
        db=db_session,
    )
    assert pca_out.n_components == 2
    assert len(pca_out.explained_variance_ratio) == 2
    assert len(pca_out.coordinates) == 6
    assert pca_out.total_variance_explained > 0.0


def test_scientific_tool_registry_rbac_enforcement(db_session, test_dataset_fixture):
    dataset = test_dataset_fixture["dataset"]

    # Other unauthorized user
    other_user = User(
        email="unauthorized@neuroforge.org",
        hashed_password=get_password_hash("ValidPass123"),
        full_name="Other User",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(other_user)
    db_session.commit()

    with pytest.raises(PermissionError):
        ScientificToolRegistry.inspect_dataset(
            DatasetInspectInput(dataset_id=dataset.id),
            current_user=other_user,
            db=db_session,
        )


# =============================================================================
# 3. LangGraph Orchestration & State Transitions Tests
# =============================================================================

def test_langgraph_workflow_pauses_at_human_approval_gate(db_session, test_dataset_fixture):
    user = test_dataset_fixture["user"]
    project = test_dataset_fixture["project"]
    dataset = test_dataset_fixture["dataset"]

    session = ResearchSession(
        project_id=project.id,
        dataset_id=dataset.id,
        owner_id=user.id,
        title="Test Investigation",
        objective="Screen candidate oncogenic drivers with FDR < 0.05",
        status=SessionStatus.INITIALIZING.value,
        current_step="initialize_research",
        approval_state=ApprovalState.PENDING.value,
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)

    initial_state: ResearchState = {
        "session_id": session.id,
        "project_id": project.id,
        "dataset_id": dataset.id,
        "user_id": user.id,
        "objective": session.objective,
        "status": session.status,
        "current_step": session.current_step,
        "approval_state": session.approval_state,
        "group_a_name": "Control",
        "group_b_name": "Treatment",
        "group_mappings": test_dataset_fixture["group_mappings"],
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
    final_state = runner.run(initial_state)

    # Verify session paused at human approval gate
    db_session.refresh(session)
    assert session.status == SessionStatus.AWAITING_APPROVAL.value
    assert session.approval_state == ApprovalState.PENDING.value
    assert session.research_plan is not None

    # Verify research events recorded
    events = db_session.query(ResearchEvent).filter(ResearchEvent.session_id == session.id).all()
    event_types = [e.event_type for e in events]
    assert "PLAN_GENERATED" in event_types
    assert "AWAITING_APPROVAL" in event_types


def test_langgraph_workflow_resumes_and_completes_upon_approval(db_session, test_dataset_fixture):
    user = test_dataset_fixture["user"]
    project = test_dataset_fixture["project"]
    dataset = test_dataset_fixture["dataset"]

    session = ResearchSession(
        project_id=project.id,
        dataset_id=dataset.id,
        owner_id=user.id,
        title="Approved Investigation",
        objective="Screen candidate oncogenic drivers with FDR < 0.05",
        status=SessionStatus.AWAITING_APPROVAL.value,
        current_step="await_human_approval",
        approval_state=ApprovalState.APPROVED.value,
        research_plan=json.dumps({
            "objective": "Screen candidate genes",
            "observed_facts": ["10 features, 6 samples"],
            "assumptions_hypotheses": ["Separation between groups"],
            "proposed_experiments": [{"tool_name": "pca_exploratory_analysis"}],
        }),
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)

    resumed_state: ResearchState = {
        "session_id": session.id,
        "project_id": project.id,
        "dataset_id": dataset.id,
        "user_id": user.id,
        "objective": session.objective,
        "status": session.status,
        "current_step": session.current_step,
        "approval_state": ApprovalState.APPROVED.value,
        "research_plan": json.loads(session.research_plan),
        "group_a_name": "Control",
        "group_b_name": "Treatment",
        "group_mappings": test_dataset_fixture["group_mappings"],
        "iteration_count": 0,
        "max_iterations": 10,
        "retry_count": 0,
        "max_retries": 3,
        "evidence_store": [],
        "tool_history": [],
        "experiment_ids": [],
    }

    from datetime import datetime, timezone
    from app.services.sandbox import ExecutionResult
    now = datetime.now(timezone.utc)
    mock_exec_res = ExecutionResult(
        status=ExperimentStatus.COMPLETED,
        exit_code=0,
        stdout="Differential expression screening completed.",
        stderr="",
        duration_seconds=0.5,
        started_at=now,
        completed_at=now,
        artifacts=[{"filename": "volcano_plot.png", "download_url": "/volcano.png"}],
        result_summary="Completed successfully.",
        failure_reason=None,
    )

    mock_vultr = VultrInferenceService(mock_handler=mock_vultr_handler)
    runner = AutonomousResearchRunner(db=db_session, current_user=user, vultr_service=mock_vultr)
    with patch("app.services.scientific_tools.SandboxExecutionService.execute", return_value=mock_exec_res):
        runner.run(resumed_state)

    db_session.refresh(session)
    assert session.status == SessionStatus.COMPLETED.value
    assert session.final_summary is not None

    summary = json.loads(session.final_summary)
    assert "key_findings" in summary
    assert "scientific_caveats" in summary


# =============================================================================
# 4. API Endpoints Lifecycle Tests
# =============================================================================

def test_api_autonomous_research_lifecycle(client, db_session, test_dataset_fixture):
    token = test_dataset_fixture["token"]
    project = test_dataset_fixture["project"]
    dataset = test_dataset_fixture["dataset"]

    headers = {"Authorization": f"Bearer {token}"}

    from datetime import datetime, timezone
    from app.services.sandbox import ExecutionResult
    now = datetime.now(timezone.utc)
    mock_exec = ExecutionResult(
        status=ExperimentStatus.COMPLETED,
        exit_code=0,
        stdout="Differential expression screening completed.",
        stderr="",
        duration_seconds=0.5,
        started_at=now,
        completed_at=now,
        artifacts=[{"filename": "volcano_plot.png", "download_url": "/volcano.png"}],
        result_summary="Completed successfully.",
        failure_reason=None,
    )

    # Patch VultrInferenceService and Docker sandbox execution for fast reproducible test
    with patch("app.services.research_graph.VultrInferenceService", return_value=VultrInferenceService(mock_handler=mock_vultr_handler)), \
         patch("app.services.scientific_tools.SandboxExecutionService.execute", return_value=mock_exec):

        # 1. Create and initiate research session
        create_payload = {
            "dataset_id": dataset.id,
            "title": "API Driven Autonomous Screening",
            "objective": "Screen candidate differentially expressed genes between primary tumor and normal control",
            "group_a_name": "Control",
            "group_b_name": "Treatment",
            "group_mappings": test_dataset_fixture["group_mappings"],
        }
        res = client.post(
            f"/projects/{project.id}/research-sessions",
            json=create_payload,
            headers=headers,
        )
        assert res.status_code == status.HTTP_201_CREATED
        session_data = res.json()
        session_id = session_data["id"]
        assert session_data["status"] == "Awaiting Approval"
        assert session_data["approval_state"] == "Pending"

        # 2. List sessions
        list_res = client.get(f"/projects/{project.id}/research-sessions", headers=headers)
        assert list_res.status_code == status.HTTP_200_OK
        assert len(list_res.json()) >= 1

        # 3. Retrieve session details
        get_res = client.get(f"/research-sessions/{session_id}", headers=headers)
        assert get_res.status_code == status.HTTP_200_OK
        assert get_res.json()["title"] == "API Driven Autonomous Screening"

        # 4. Check timeline events
        events_res = client.get(f"/research-sessions/{session_id}/events", headers=headers)
        assert events_res.status_code == status.HTTP_200_OK
        assert len(events_res.json()) > 0

        # 5. Check evidence store
        evidence_res = client.get(f"/research-sessions/{session_id}/evidence", headers=headers)
        assert evidence_res.status_code == status.HTTP_200_OK
        assert "evidence_items" in evidence_res.json()

        # 6. Approve the plan to resume execution
        approve_res = client.post(
            f"/research-sessions/{session_id}/approve",
            json={"decision": "approve", "notes": "Approved for exploratory testing"},
            headers=headers,
        )
        assert approve_res.status_code == status.HTTP_200_OK
        approved_data = approve_res.json()
        assert approved_data["approval_state"] == "Approved"
        assert approved_data["status"] == "Completed"

        # 7. Retrieve final summary
        summary_res = client.get(f"/research-sessions/{session_id}/summary", headers=headers)
        assert summary_res.status_code == status.HTTP_200_OK
        assert summary_res.json()["final_summary"] is not None


def test_api_viewer_cannot_create_or_approve_session(client, db_session, test_dataset_fixture):
    project = test_dataset_fixture["project"]
    dataset = test_dataset_fixture["dataset"]

    # Viewer user
    viewer = User(
        email="viewer_auditor@neuroforge.org",
        hashed_password=get_password_hash("ValidPass123"),
        full_name="Viewer Auditor",
        role=UserRole.VIEWER.value,
        is_active=True,
    )
    db_session.add(viewer)
    db_session.commit()
    viewer_token = create_access_token(viewer.id, viewer.role)
    headers = {"Authorization": f"Bearer {viewer_token}"}

    create_payload = {
        "dataset_id": dataset.id,
        "title": "Viewer Unauthorized Launch",
        "objective": "Attempt launch",
    }
    res = client.post(
        f"/projects/{project.id}/research-sessions",
        json=create_payload,
        headers=headers,
    )
    assert res.status_code == status.HTTP_403_FORBIDDEN


def test_user_cannot_approve_another_researchers_session(client, db_session, test_dataset_fixture):
    project = test_dataset_fixture["project"]
    dataset = test_dataset_fixture["dataset"]

    session = ResearchSession(
        project_id=project.id,
        dataset_id=dataset.id,
        owner_id=test_dataset_fixture["user"].id,
        title="Restricted Session",
        objective="Analyze targets",
        status=SessionStatus.AWAITING_APPROVAL.value,
        approval_state=ApprovalState.PENDING.value,
        research_plan=json.dumps({"objective": "Analyze", "plan_hash": "testhash123"}),
    )
    db_session.add(session)
    db_session.commit()

    # Another independent researcher
    other_user = User(
        email="other_researcher@lab.org",
        hashed_password=get_password_hash("ValidPass123"),
        full_name="Other Researcher",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(other_user)
    db_session.commit()
    other_token = create_access_token(other_user.id, other_user.role)

    # Attempt to approve someone else's session
    res = client.post(
        f"/research-sessions/{session.id}/approve",
        json={"decision": "approve"},
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert res.status_code == status.HTTP_403_FORBIDDEN


def test_rejected_session_cannot_be_approved_or_continued(client, db_session, test_dataset_fixture):
    project = test_dataset_fixture["project"]
    dataset = test_dataset_fixture["dataset"]
    user = test_dataset_fixture["user"]
    token = test_dataset_fixture["token"]
    headers = {"Authorization": f"Bearer {token}"}

    session = ResearchSession(
        project_id=project.id,
        dataset_id=dataset.id,
        owner_id=user.id,
        title="Rejected Session",
        objective="Analyze targets",
        status=SessionStatus.REJECTED.value,
        approval_state=ApprovalState.REJECTED.value,
        research_plan=json.dumps({"objective": "Analyze"}),
        failure_reason="Plan rejected by researcher",
    )
    db_session.add(session)
    db_session.commit()

    # Attempt to approve
    app_res = client.post(
        f"/research-sessions/{session.id}/approve",
        json={"decision": "approve"},
        headers=headers,
    )
    assert app_res.status_code == status.HTTP_400_BAD_REQUEST

    # Attempt to continue
    cont_res = client.post(
        f"/research-sessions/{session.id}/continue",
        headers=headers,
    )
    assert cont_res.status_code == status.HTTP_400_BAD_REQUEST


def test_plan_hash_mismatch_blocks_approval(client, db_session, test_dataset_fixture):
    project = test_dataset_fixture["project"]
    dataset = test_dataset_fixture["dataset"]
    user = test_dataset_fixture["user"]
    token = test_dataset_fixture["token"]
    headers = {"Authorization": f"Bearer {token}"}

    session = ResearchSession(
        project_id=project.id,
        dataset_id=dataset.id,
        owner_id=user.id,
        title="Hashed Session",
        objective="Analyze targets",
        status=SessionStatus.AWAITING_APPROVAL.value,
        approval_state=ApprovalState.PENDING.value,
        research_plan=json.dumps({"objective": "Analyze", "plan_hash": "valid_hash_12345"}),
    )
    db_session.add(session)
    db_session.commit()

    # Pass an altered plan hash
    res = client.post(
        f"/research-sessions/{session.id}/approve",
        json={"decision": "approve", "plan_hash": "tampered_or_stale_hash"},
        headers=headers,
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "Plan hash mismatch" in res.json()["detail"]


def test_cannot_continue_session_awaiting_approval_without_approving(client, db_session, test_dataset_fixture):
    project = test_dataset_fixture["project"]
    dataset = test_dataset_fixture["dataset"]
    user = test_dataset_fixture["user"]
    token = test_dataset_fixture["token"]
    headers = {"Authorization": f"Bearer {token}"}

    session = ResearchSession(
        project_id=project.id,
        dataset_id=dataset.id,
        owner_id=user.id,
        title="Pending Session",
        objective="Analyze targets",
        status=SessionStatus.AWAITING_APPROVAL.value,
        approval_state=ApprovalState.PENDING.value,
        research_plan=json.dumps({"objective": "Analyze"}),
    )
    db_session.add(session)
    db_session.commit()

    # Attempting to bypass approval by calling /continue
    res = client.post(
        f"/research-sessions/{session.id}/continue",
        headers=headers,
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "without explicit plan approval" in res.json()["detail"]


def test_concurrent_approval_lock_prevents_duplicate_execution(client, db_session, test_dataset_fixture):
    from app.api.routers.agent_research import _get_session_lock
    project = test_dataset_fixture["project"]
    dataset = test_dataset_fixture["dataset"]
    user = test_dataset_fixture["user"]
    token = test_dataset_fixture["token"]
    headers = {"Authorization": f"Bearer {token}"}

    session = ResearchSession(
        project_id=project.id,
        dataset_id=dataset.id,
        owner_id=user.id,
        title="Concurrent Session",
        objective="Analyze targets",
        status=SessionStatus.AWAITING_APPROVAL.value,
        approval_state=ApprovalState.PENDING.value,
        research_plan=json.dumps({"objective": "Analyze"}),
    )
    db_session.add(session)
    db_session.commit()

    # Simulate lock being held by another thread
    lock = _get_session_lock(session.id)
    lock.acquire()
    try:
        res = client.post(
            f"/research-sessions/{session.id}/approve",
            json={"decision": "approve"},
            headers=headers,
        )
        assert res.status_code == status.HTTP_409_CONFLICT
        assert "currently being processed" in res.json()["detail"]
    finally:
        lock.release()


def test_scientific_tool_differential_expression_rejects_raw_counts(db_session, test_dataset_fixture):
    user = test_dataset_fixture["user"]
    project = test_dataset_fixture["project"]

    # Create raw counts dataset
    raw_counts_csv = (
        "Gene,S1,S2,S3,S4,S5,S6\n"
        "TP53,1050,1200,980,50,60,40\n"
        "BRCA1,800,850,790,30,40,25\n"
        "EGFR,50,60,45,900,950,890\n"
    )
    filename = "raw_counts_matrix.csv"
    upload_dir = get_upload_dir()
    file_path = resolve_safe_path(upload_dir, filename)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(raw_counts_csv)

    dataset = Dataset(
        project_id=project.id,
        owner_id=user.id,
        filename=filename,
        original_name="raw_counts_matrix.csv",
        file_size_bytes=len(raw_counts_csv.encode("utf-8")),
        file_format="CSV",
        status="Validated",
        sample_count=6,
        feature_count=3,
        matrix_orientation="features_as_rows",
    )
    db_session.add(dataset)
    db_session.commit()

    with pytest.raises(ValueError) as exc_info:
        ScientificToolRegistry.run_differential_expression(
            DifferentialExpressionInput(
                project_id=project.id,
                dataset_id=dataset.id,
                group_a_name="Control",
                group_b_name="Treatment",
                group_mappings={"S1": "Control", "S2": "Control", "S3": "Control", "S4": "Treatment", "S5": "Treatment", "S6": "Treatment"},
            ),
            current_user=user,
            db=db_session,
        )
    assert "raw rna-seq counts" in str(exc_info.value).lower()


