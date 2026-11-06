import json
import logging
import pytest
from unittest.mock import patch, MagicMock
import httpx
from pydantic import BaseModel

from app.db.models import (
    ApprovalState,
    Dataset,
    Project,
    ResearchEvent,
    ResearchSession,
    SessionStatus,
    User,
    UserRole,
)
from app.core.security import get_password_hash
from app.services.research_graph import (
    AutonomousResearchRunner,
    ResearchPlanSchema,
    ResearchState,
    compute_canonical_plan_hash,
)
from app.services.vultr_inference import (
    InferenceResponse,
    VultrInferenceAuthError,
    VultrInferenceError,
    VultrInferenceFormatError,
    VultrInferenceModelNotFoundError,
    VultrInferenceRateLimitError,
    VultrInferenceService,
    VultrInferenceUnavailableError,
)


class DummySchema(BaseModel):
    title: str
    score: float


# =============================================================================
# 1. Provider Failure Unit Tests (Mocked HTTPX Responses)
# =============================================================================

def test_missing_api_key_raises_auth_error():
    service = VultrInferenceService(api_key="")
    with pytest.raises(VultrInferenceAuthError) as exc_info:
        service.chat_completion(messages=[{"role": "user", "content": "Hello"}])
    assert "API key is not configured" in str(exc_info.value)


def test_invalid_api_key_401_and_403_no_retry():
    secret_key = "secret-vultr-key-12345"
    service = VultrInferenceService(api_key=secret_key, max_retries=3)

    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = '{"error": "Unauthorized"}'

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        with pytest.raises(VultrInferenceAuthError) as exc_info:
            service.chat_completion(messages=[{"role": "user", "content": "test"}])
        assert "Authentication failed" in str(exc_info.value)
        # Authentication error must fail immediately without burning retries
        assert mock_post.call_count == 1
        # Secret key must not leak in error message
        assert secret_key not in str(exc_info.value)


def test_unsupported_model_404():
    service = VultrInferenceService(api_key="vultr-test-key", model="nonexistent-model-xyz", max_retries=2)
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = '{"error": "Model not found"}'

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        with pytest.raises(VultrInferenceModelNotFoundError) as exc_info:
            service.chat_completion(messages=[{"role": "user", "content": "test"}])
        assert "not found" in str(exc_info.value)
        assert mock_post.call_count == 1


def test_connection_timeout_retries_and_exhausts():
    service = VultrInferenceService(api_key="vultr-test-key", timeout=1, max_retries=3)

    with patch("httpx.Client.post", side_effect=httpx.TimeoutException("Read timed out")) as mock_post:
        with patch("time.sleep", return_value=None):
            with pytest.raises(VultrInferenceUnavailableError) as exc_info:
                service.chat_completion(messages=[{"role": "user", "content": "test"}])
            assert "timeout connecting to Vultr" in str(exc_info.value)
            assert mock_post.call_count == 3


def test_rate_limiting_429_retries_and_recovers():
    service = VultrInferenceService(api_key="vultr-test-key", max_retries=3)

    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.text = '{"error": "Rate limit exceeded"}'

    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = {
        "choices": [{"message": {"content": '{"title": "Recovered", "score": 0.99}'}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
    }

    with patch("httpx.Client.post", side_effect=[resp_429, resp_200]) as mock_post:
        with patch("time.sleep", return_value=None):
            res = service.chat_completion(
                messages=[{"role": "user", "content": "test"}],
                response_model=DummySchema,
            )
            assert res.parsed == {"title": "Recovered", "score": 0.99}
            assert mock_post.call_count == 2


def test_provider_5xx_retries_and_exhausts():
    service = VultrInferenceService(api_key="vultr-test-key", max_retries=3)

    resp_503 = MagicMock()
    resp_503.status_code = 503
    resp_503.text = '{"error": "Backend overloaded"}'

    with patch("httpx.Client.post", return_value=resp_503) as mock_post:
        with patch("time.sleep", return_value=None):
            with pytest.raises(VultrInferenceUnavailableError) as exc_info:
                service.chat_completion(messages=[{"role": "user", "content": "test"}])
            assert "service unavailable (HTTP 503)" in str(exc_info.value)
            assert mock_post.call_count == 3


def test_malformed_llm_response_raises_format_error():
    service = VultrInferenceService(api_key="vultr-test-key", max_retries=1)

    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = {
        "choices": [{"message": {"content": "This is plain prose, not valid JSON output."}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
    }

    with patch("httpx.Client.post", return_value=resp_200):
        with pytest.raises(VultrInferenceFormatError) as exc_info:
            service.chat_completion(
                messages=[{"role": "user", "content": "test"}],
                response_model=DummySchema,
            )
        assert "could not be parsed into expected structured schema" in str(exc_info.value)


def test_empty_llm_response_raises_format_error():
    service = VultrInferenceService(api_key="vultr-test-key", max_retries=1)

    resp_empty_choices = MagicMock()
    resp_empty_choices.status_code = 200
    resp_empty_choices.json.return_value = {"choices": []}

    with patch("httpx.Client.post", return_value=resp_empty_choices):
        with pytest.raises(VultrInferenceFormatError) as exc_info:
            service.chat_completion(messages=[{"role": "user", "content": "test"}])
        assert "Empty completion choices" in str(exc_info.value)

    resp_empty_content = MagicMock()
    resp_empty_content.status_code = 200
    resp_empty_content.json.return_value = {
        "choices": [{"message": {"content": "   "}}],
        "usage": {},
    }

    with patch("httpx.Client.post", return_value=resp_empty_content):
        with pytest.raises(VultrInferenceFormatError) as exc_info:
            service.chat_completion(
                messages=[{"role": "user", "content": "test"}],
                response_model=DummySchema,
            )
        assert "Empty completion text" in str(exc_info.value)


def test_no_credential_leakage_in_logs_and_errors(caplog):
    secret_key = "vultr-super-secret-api-key-998877"
    service = VultrInferenceService(api_key=secret_key, max_retries=1)

    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"

    with caplog.at_level(logging.DEBUG):
        with patch("httpx.Client.post", return_value=mock_resp):
            with pytest.raises(VultrInferenceAuthError):
                service.chat_completion(messages=[{"role": "user", "content": "test"}])

    for record in caplog.records:
        assert secret_key not in record.message
        assert secret_key not in str(record.__dict__)


def test_vultr_list_models():
    service = VultrInferenceService(api_key="vultr-test-key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [
            {"id": "llama-3.3-70b-instruct-fp8", "object": "model"},
            {"id": "deepseek-r1-distill-llama-70b", "object": "model"},
        ]
    }
    with patch("httpx.Client.get", return_value=mock_resp):
        models = service.list_models()
        assert "llama-3.3-70b-instruct-fp8" in models
        assert "deepseek-r1-distill-llama-70b" in models


# =============================================================================
# 2. End-to-End Agent Provider Failure and Non-Fabrication Tests
# =============================================================================

def test_no_arbitrary_tool_execution_after_malformed_plan(db_session, test_dataset_fixture):
    """
    CRITICAL BLAST RADIUS TEST:
    If Vultr Serverless Inference returns a malformed response during plan generation:
    1. Session must fail honestly (status = Failed).
    2. Failure reason must record the inference format error.
    3. NO synthetic plan may be fabricated.
    4. NO Docker sandbox experiments may be run.
    """
    user = test_dataset_fixture["user"]
    project = test_dataset_fixture["project"]
    dataset = test_dataset_fixture["dataset"]

    session = ResearchSession(
        project_id=project.id,
        dataset_id=dataset.id,
        owner_id=user.id,
        title="Failing Inference Investigation",
        objective="Verify system does not hallucinate plans on provider failure",
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

    # Handler returns malformed / unparseable output
    def bad_vultr_handler(messages, response_model=None):
        return InferenceResponse(
            content="I am unable to format this as a JSON plan.",
            parsed=None,
            model="llama-3.3-70b-instruct-fp8",
            duration_seconds=0.1,
        )

    failing_service = VultrInferenceService(mock_handler=bad_vultr_handler)
    runner = AutonomousResearchRunner(db=db_session, current_user=user, vultr_service=failing_service)

    with patch("app.services.scientific_tools.SandboxExecutionService.execute") as mock_sandbox:
        runner.run(initial_state)
        # Sandbox must NEVER be called
        assert mock_sandbox.call_count == 0

    db_session.refresh(session)
    # Session must be marked Failed
    assert session.status == SessionStatus.FAILED.value
    assert "Inference plan generation failed" in (session.failure_reason or "")
    # Plan must NOT be fabricated
    assert session.research_plan is None

    # Error event must be in timeline
    events = db_session.query(ResearchEvent).filter(ResearchEvent.session_id == session.id).all()
    event_types = [e.event_type for e in events]
    assert "ERROR" in event_types


def test_research_session_remains_recoverable_after_provider_failure(db_session, test_dataset_fixture):
    """
    Verify that if inference fails temporarily, the session record remains
    in a recoverable state and can successfully proceed once provider recovers.
    """
    user = test_dataset_fixture["user"]
    project = test_dataset_fixture["project"]
    dataset = test_dataset_fixture["dataset"]

    session = ResearchSession(
        project_id=project.id,
        dataset_id=dataset.id,
        owner_id=user.id,
        title="Recoverable Session",
        objective="Verify recovery after temporary provider failure",
        status=SessionStatus.INITIALIZING.value,
        approval_state=ApprovalState.PENDING.value,
    )
    db_session.add(session)
    db_session.commit()

    initial_state = AutonomousResearchRunner.load_session_state(db_session, session.id)

    # 1. Attempt 1 with failing provider
    def failing_handler(messages, response_model=None):
        raise VultrInferenceUnavailableError("Vultr service unavailable (HTTP 503).")

    runner1 = AutonomousResearchRunner(
        db=db_session,
        current_user=user,
        vultr_service=VultrInferenceService(mock_handler=failing_handler),
    )
    runner1.run(initial_state)

    db_session.refresh(session)
    assert session.status == SessionStatus.FAILED.value

    # 2. Reset status to Initializing to retry
    session.status = SessionStatus.INITIALIZING.value
    session.failure_reason = None
    db_session.commit()

    # 3. Attempt 2 with recovered provider
    def healthy_plan_handler(messages, response_model=None):
        plan = {
            "objective": "Screen candidate genes",
            "observed_facts": ["10 features, 6 samples"],
            "assumptions_hypotheses": ["Group separation"],
            "proposed_experiments": [
                {
                    "tool_name": "pca_exploratory_analysis",
                    "description": "PCA test",
                    "rationale": "Variance check",
                    "parameters": {"n_components": 2},
                }
            ],
            "expected_outcomes": ["PCA scree"],
            "scientific_limitations": ["Small cohort"],
        }
        return InferenceResponse(
            content=json.dumps(plan),
            parsed=plan,
            model="llama-3.3-70b-instruct-fp8",
            duration_seconds=0.1,
        )

    retry_state = AutonomousResearchRunner.load_session_state(db_session, session.id)
    retry_state["status"] = SessionStatus.INITIALIZING.value
    retry_state["failure_reason"] = None

    runner2 = AutonomousResearchRunner(
        db=db_session,
        current_user=user,
        vultr_service=VultrInferenceService(mock_handler=healthy_plan_handler),
    )
    runner2.run(retry_state)

    db_session.refresh(session)
    assert session.status == SessionStatus.AWAITING_APPROVAL.value
    assert session.research_plan is not None
    plan_dict = json.loads(session.research_plan)
    assert "plan_hash" in plan_dict

