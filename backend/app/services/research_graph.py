import json
import logging
import hashlib
import threading
from typing import Any, Dict, List, Optional, TypedDict
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from psycopg_pool import ConnectionPool

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver

from app.core.config import settings
from app.db.models import (
    ApprovalState,
    Dataset,
    Experiment,
    Project,
    ResearchEvent,
    ResearchSession,
    SessionStatus,
    User,
    UserRole,
    utc_now,
)
from app.services.scientific_tools import (
    DatasetInspectInput,
    DatasetQualityInput,
    DifferentialExpressionInput,
    PCAAnalysisInput,
    ScientificToolRegistry,
)
from app.services.vultr_inference import (
    InferenceResponse,
    VultrInferenceError,
    VultrInferenceFormatError,
    VultrInferenceService,
)

logger = logging.getLogger("neuroforge.research_graph")

_pg_checkpointer: Optional[PostgresSaver] = None
_pg_pool: Optional[ConnectionPool] = None
_pg_lock = threading.Lock()


def get_postgres_checkpointer(conn_string: Optional[str] = None) -> Any:
    """
    Returns an initialized, thread-safe PostgreSQL checkpointer for LangGraph execution.
    Connects to PostgreSQL using a connection pool configured for durable persistence
    in the 'checkpoints' schema.
    Falls back to MemorySaver only in isolated unit tests where no database connection exists.
    """
    global _pg_checkpointer, _pg_pool
    with _pg_lock:
        if _pg_checkpointer is not None:
            return _pg_checkpointer

        target_url = conn_string or settings.CHECKPOINT_DATABASE_URL
        if target_url and "@localhost:" in target_url:
            target_url = target_url.replace("@localhost:", "@127.0.0.1:")

        if target_url and target_url.startswith("postgresql"):
            try:
                _pg_pool = ConnectionPool(
                    conninfo=target_url,
                    min_size=1,
                    max_size=10,
                    kwargs={"autocommit": True, "prepare_threshold": 0},
                )
                _pg_checkpointer = PostgresSaver(_pg_pool)
                _pg_checkpointer.setup()
                logger.info("LangGraph PostgresSaver initialized and setup successfully against PostgreSQL.")
                return _pg_checkpointer
            except Exception as e:
                logger.warning(f"Could not initialize PostgresSaver ({e}), falling back to MemorySaver.")

        from langgraph.checkpoint.memory import MemorySaver
        _pg_checkpointer = MemorySaver()
        return _pg_checkpointer


def compute_canonical_plan_hash(plan_dict: Dict[str, Any]) -> str:
    """Compute deterministic cryptographic SHA-256 hash across all execution-relevant plan fields."""
    relevant_keys = [
        "objective",
        "observed_facts",
        "assumptions_hypotheses",
        "proposed_experiments",
        "expected_outcomes",
        "scientific_limitations",
    ]
    normalized: Dict[str, Any] = {}
    for k in sorted(relevant_keys):
        if k in plan_dict:
            normalized[k] = plan_dict[k]
    for k in sorted(plan_dict.keys()):
        if k not in ["plan_hash", "approved_at", "approved_by", "approval_notes"] and k not in normalized:
            normalized[k] = plan_dict[k]

    canonical_json = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# =============================================================================
# Typed Pydantic Models for Structured Inference
# =============================================================================

class ProposedExperiment(BaseModel):
    tool_name: str
    description: str
    rationale: str
    parameters: Dict[str, Any] = Field(default_factory=dict)


class ResearchPlanSchema(BaseModel):
    objective: str
    observed_facts: List[str]
    assumptions_hypotheses: List[str]
    proposed_experiments: List[ProposedExperiment]
    expected_outcomes: List[str]
    scientific_limitations: List[str]


class EvaluationSchema(BaseModel):
    experiment_id: Optional[str] = None
    statistical_assessment: str
    verified_findings: List[str]
    effect_size_summary: str
    statistical_significance_summary: str
    biological_caveats: List[str]
    next_step_recommendation: str


class KeyFinding(BaseModel):
    feature_name: str
    log2_fold_change: float
    fdr_q_value: float
    regulation_direction: str
    biological_context: Optional[str] = None


class ResearchSummarySchema(BaseModel):
    title: str
    executive_summary: str
    dataset_characteristics: Dict[str, Any] = Field(default_factory=dict)
    methodology: str
    key_findings: List[KeyFinding] = Field(default_factory=list)
    scientific_caveats: List[str] = Field(default_factory=list)
    unconfirmed_hypotheses: List[str] = Field(default_factory=list)
    recommended_future_work: List[str] = Field(default_factory=list)


# =============================================================================
# Typed State for LangGraph
# =============================================================================

class ResearchState(TypedDict, total=False):
    session_id: str
    project_id: str
    dataset_id: str
    user_id: str
    objective: str
    dataset_hash: Optional[str]
    status: str
    current_step: str
    approval_state: str
    approval_notes: Optional[str]
    group_a_name: Optional[str]
    group_b_name: Optional[str]
    group_mappings: Optional[Dict[str, str]]
    research_plan: Optional[Dict[str, Any]]
    experiment_ids: List[str]
    tool_history: List[Dict[str, Any]]
    evidence_store: List[Dict[str, Any]]
    final_summary: Optional[Dict[str, Any]]
    iteration_count: int
    max_iterations: int
    retry_count: int
    max_retries: int
    selected_tool: Optional[str]
    tool_input: Optional[Dict[str, Any]]
    last_tool_output: Optional[Dict[str, Any]]
    last_evaluation: Optional[Dict[str, Any]]
    failure_reason: Optional[str]
    next_action: Optional[str]
    should_pause: bool


# =============================================================================
# Helper Event and Persistence Utilities
# =============================================================================

def record_session_event(
    db: Session,
    session_id: str,
    event_type: str,
    step_name: str,
    message: str,
    payload: Optional[Dict[str, Any]] = None,
) -> ResearchEvent:
    event = ResearchEvent(
        session_id=session_id,
        event_type=event_type,
        step_name=step_name,
        message=message,
        payload=json.dumps(payload) if payload else None,
    )
    db.add(event)
    try:
        db.commit()
        db.refresh(event)
    except Exception as exc:
        db.rollback()
        logger.error(f"Failed to record research event: {exc}")
    return event


def sync_state_to_db(db: Session, state: ResearchState) -> None:
    session = db.query(ResearchSession).filter(ResearchSession.id == state["session_id"]).first()
    if not session:
        return

    session.status = state.get("status", session.status)
    session.current_step = state.get("current_step", session.current_step)
    session.approval_state = state.get("approval_state", session.approval_state)
    session.approval_notes = state.get("approval_notes", session.approval_notes)
    session.dataset_hash = state.get("dataset_hash", session.dataset_hash)
    session.iteration_count = state.get("iteration_count", session.iteration_count)
    session.retry_count = state.get("retry_count", session.retry_count)

    if state.get("research_plan"):
        session.research_plan = json.dumps(state["research_plan"])
    if state.get("experiment_ids"):
        session.experiment_ids = json.dumps(state["experiment_ids"])
    if state.get("tool_history"):
        session.tool_history = json.dumps(state["tool_history"])
    if state.get("evidence_store"):
        session.evidence_store = json.dumps(state["evidence_store"])
    if state.get("final_summary"):
        session.final_summary = json.dumps(state["final_summary"])
    if state.get("failure_reason"):
        session.failure_reason = state["failure_reason"]

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error(f"Failed to sync state to database: {exc}")


# =============================================================================
# Graph Node Definitions
# =============================================================================

def initialize_research_node(
    state: ResearchState,
    db: Session,
    current_user: User,
) -> ResearchState:
    """Validate dataset and session existence and setup initial evidence."""
    logger.info(f"Initializing research session {state['session_id']}")
    session_id = state["session_id"]
    dataset = db.query(Dataset).filter(Dataset.id == state["dataset_id"]).first()

    if not dataset:
        state["status"] = SessionStatus.FAILED.value
        state["failure_reason"] = f"Dataset {state['dataset_id']} not found."
        record_session_event(db, session_id, "ERROR", "initialize_research", state["failure_reason"])
        sync_state_to_db(db, state)
        return state

    state["dataset_hash"] = dataset.content_hash
    state["current_step"] = "initialize_research"
    state["status"] = SessionStatus.INITIALIZING.value
    state["iteration_count"] = 0
    state["retry_count"] = 0

    if not state.get("evidence_store"):
        state["evidence_store"] = []
    if not state.get("tool_history"):
        state["tool_history"] = []
    if not state.get("experiment_ids"):
        state["experiment_ids"] = []

    # Read dataset group annotations if not provided directly
    if not state.get("group_mappings") and dataset.group_mappings:
        try:
            state["group_mappings"] = json.loads(dataset.group_mappings)
        except Exception:
            pass
    if not state.get("group_a_name") and dataset.control_group:
        state["group_a_name"] = dataset.control_group
    if not state.get("group_b_name") and dataset.treatment_group:
        state["group_b_name"] = dataset.treatment_group

    record_session_event(
        db,
        session_id,
        "STATUS_UPDATE",
        "initialize_research",
        f"Initialized research session for dataset '{dataset.original_name}' with objective: {state['objective']}",
        {"dataset_id": dataset.id, "dataset_hash": dataset.content_hash},
    )
    sync_state_to_db(db, state)
    return state


def inspect_dataset_node(
    state: ResearchState,
    db: Session,
    current_user: User,
) -> ResearchState:
    """Inspect dataset orientation, dimensions, scale, and quality."""
    logger.info(f"Inspecting dataset for session {state['session_id']}")
    session_id = state["session_id"]
    state["current_step"] = "inspect_dataset"

    try:
        inspect_out = ScientificToolRegistry.inspect_dataset(
            DatasetInspectInput(dataset_id=state["dataset_id"]),
            current_user=current_user,
            db=db,
        )
        quality_out = ScientificToolRegistry.assess_dataset_quality(
            DatasetQualityInput(
                dataset_id=state["dataset_id"],
                group_a_name=state.get("group_a_name"),
                group_b_name=state.get("group_b_name"),
                group_mappings=state.get("group_mappings"),
            ),
            current_user=current_user,
            db=db,
        )

        state["evidence_store"].append({
            "type": "dataset_inspection",
            "feature_count": inspect_out.feature_count,
            "sample_count": inspect_out.sample_count,
            "matrix_orientation": inspect_out.matrix_orientation,
            "scale_inference": inspect_out.scale_inference,
            "is_log2": inspect_out.is_log2,
            "dataset_hash": inspect_out.content_hash,
            "summary": inspect_out.evidence.summary_text,
        })
        state["evidence_store"].append({
            "type": "quality_assessment",
            "readiness_state": quality_out.readiness_state,
            "is_ready_for_welch_t": quality_out.is_ready_for_welch_t,
            "missing_cells_count": quality_out.missing_cells_count,
            "constant_features_count": quality_out.constant_features_count,
            "warnings": quality_out.warnings,
            "caveats": quality_out.caveats,
            "summary": quality_out.evidence.summary_text,
        })

        record_session_event(
            db,
            session_id,
            "TOOL_COMPLETED",
            "inspect_dataset",
            f"Dataset inspected: {inspect_out.feature_count} features, {inspect_out.sample_count} samples. "
            f"Quality status: {quality_out.readiness_state}.",
            {"inspection": inspect_out.model_dump(), "quality": quality_out.model_dump()},
        )
    except Exception as exc:
        logger.error(f"Dataset inspection failed: {exc}")
        state["status"] = SessionStatus.FAILED.value
        state["failure_reason"] = f"Dataset inspection failed: {str(exc)}"
        record_session_event(db, session_id, "ERROR", "inspect_dataset", state["failure_reason"])

    sync_state_to_db(db, state)
    return state


def generate_research_plan_node(
    state: ResearchState,
    db: Session,
    vultr_service: VultrInferenceService,
) -> ResearchState:
    """Generate structured research plan using Vultr Serverless Inference."""
    if state.get("status") == SessionStatus.FAILED.value:
        return state

    session_id = state["session_id"]
    logger.info(f"Generating research plan for session {session_id}")
    state["current_step"] = "generate_research_plan"
    state["status"] = SessionStatus.PLANNING.value

    # Extract observed facts from evidence store
    facts = []
    for item in state.get("evidence_store", []):
        if "summary" in item:
            facts.append(item["summary"])

    prompt_messages = [
        {
            "role": "system",
            "content": (
                "You are an autonomous senior bioinformatician and statistical scientist planning a research investigation "
                "in cancer transcriptomics.\n"
                "CRITICAL SCIENTIFIC INTEGRITY RULES:\n"
                "1. NEVER fabricate data, sample IDs, p-values, or gene discoveries.\n"
                "2. Base all statements strictly on the verified facts provided.\n"
                "3. You have access ONLY to two scientific execution tools:\n"
                "   - 'pca_exploratory_analysis': Computes 2D/3D PCA projection for sample clustering and batch quality.\n"
                "   - 'differential_expression_screening': Runs Welch's t-test with Benjamini-Hochberg FDR correction in an isolated Docker sandbox.\n"
                "4. Structure your response in valid JSON matching the ResearchPlanSchema:\n"
                "   - objective (string)\n"
                "   - observed_facts (list of strings derived strictly from dataset inspection)\n"
                "   - assumptions_hypotheses (list of explicit, testable assumptions)\n"
                "   - proposed_experiments (list of objects with tool_name, description, rationale, parameters)\n"
                "   - expected_outcomes (list of measurable metrics expected)\n"
                "   - scientific_limitations (list of caveats regarding sample size, observational nature, etc.)\n"
            ),
        },
        {
            "role": "user",
            "content": (
                f"RESEARCH OBJECTIVE: {state['objective']}\n\n"
                f"VERIFIED DATASET FACTS:\n"
                + "\n".join([f"- {f}" for f in facts])
                + f"\n\nGROUP METADATA:\n"
                f"- Group A (Reference/Control): {state.get('group_a_name', 'Not explicitly assigned')}\n"
                f"- Group B (Treatment/Condition): {state.get('group_b_name', 'Not explicitly assigned')}\n"
                f"- Assigned samples: {len(state.get('group_mappings', {})) if state.get('group_mappings') else '0'}\n\n"
                "Generate a rigorous, evidence-grounded scientific research plan."
            ),
        },
    ]

    try:
        response: InferenceResponse = vultr_service.chat_completion(
            messages=prompt_messages,
            response_model=ResearchPlanSchema,
            temperature=0.2,
        )

        plan_data = response.parsed
        if not plan_data:
            raise VultrInferenceFormatError(
                "Vultr Serverless Inference did not produce a valid structured ResearchPlanSchema response."
            )

        # Compute deterministic cryptographic hash of the generated plan
        plan_canonical = {k: v for k, v in plan_data.items() if k != "plan_hash"}
        plan_hash = hashlib.sha256(json.dumps(plan_canonical, sort_keys=True).encode("utf-8")).hexdigest()
        plan_data["plan_hash"] = plan_hash

        state["research_plan"] = plan_data

        record_session_event(
            db,
            session_id,
            "PLAN_GENERATED",
            "generate_research_plan",
            f"Generated structured research plan (SHA-256: {plan_hash[:12]}...) with {len(plan_data.get('proposed_experiments', []))} proposed experiment(s).",
            {"plan": plan_data, "plan_hash": plan_hash, "tokens": response.total_tokens, "duration": response.duration_seconds},
        )
    except Exception as exc:
        logger.error(f"Plan generation failed: {exc}")
        state["status"] = SessionStatus.FAILED.value
        state["failure_reason"] = f"Inference plan generation failed: {str(exc)}"
        record_session_event(db, session_id, "ERROR", "generate_research_plan", state["failure_reason"])

    sync_state_to_db(db, state)
    return state


def await_human_approval_node(
    state: ResearchState,
    db: Session,
) -> ResearchState:
    """Human-in-the-loop safety gate. Interrupts execution if not approved."""
    if state.get("status") == SessionStatus.FAILED.value:
        return state

    session_id = state["session_id"]
    state["current_step"] = "await_human_approval"

    if state.get("approval_state") == ApprovalState.APPROVED.value:
        state["status"] = SessionStatus.EXECUTING.value
        state["should_pause"] = False
        record_session_event(
            db,
            session_id,
            "STATUS_UPDATE",
            "await_human_approval",
            f"Research plan approved by researcher. Proceeding to execution.",
            {"approval_notes": state.get("approval_notes")},
        )
    elif state.get("approval_state") == ApprovalState.REJECTED.value:
        state["status"] = SessionStatus.REJECTED.value
        state["failure_reason"] = f"Research plan rejected: {state.get('approval_notes', 'No reason provided')}"
        state["should_pause"] = False
        record_session_event(
            db,
            session_id,
            "STATUS_UPDATE",
            "await_human_approval",
            state["failure_reason"],
        )
    else:
        # Pause state awaiting approval
        state["status"] = SessionStatus.AWAITING_APPROVAL.value
        state["approval_state"] = ApprovalState.PENDING.value
        state["should_pause"] = True
        record_session_event(
            db,
            session_id,
            "AWAITING_APPROVAL",
            "await_human_approval",
            "Research plan ready for review. Awaiting researcher approval before any experiment execution.",
        )

    sync_state_to_db(db, state)
    return state


def approval_gate_node(
    state: ResearchState,
    db: Session,
) -> ResearchState:
    """Approval checkpoint gate node right before tool execution."""
    state["current_step"] = "approval_gate"
    if state.get("approval_state") == ApprovalState.APPROVED.value:
        state["should_pause"] = False
    sync_state_to_db(db, state)
    return state


def select_scientific_tool_node(
    state: ResearchState,
    db: Session,
) -> ResearchState:
    """Select the next validated scientific tool based on plan and evidence history."""
    if state.get("approval_state") == ApprovalState.APPROVED.value:
        state["should_pause"] = False

    if state.get("status") == SessionStatus.FAILED.value or state.get("should_pause"):
        return state

    session_id = state["session_id"]
    state["current_step"] = "select_scientific_tool"
    state["iteration_count"] = state.get("iteration_count", 0) + 1

    if state["iteration_count"] > state.get("max_iterations", 10):
        state["next_action"] = "summarize"
        return state

    # Check executed tools in tool_history
    executed_tools = [h.get("tool_name") for h in state.get("tool_history", [])]

    # Tool selection priority:
    # 1. If PCA hasn't been executed, execute pca_exploratory_analysis first
    if "pca_exploratory_analysis" not in executed_tools:
        state["selected_tool"] = "pca_exploratory_analysis"
        state["tool_input"] = {
            "dataset_id": state["dataset_id"],
            "n_components": 2,
        }
    # 2. If differential expression hasn't been executed, check if group mappings exist
    elif "differential_expression_screening" not in executed_tools:
        if state.get("group_mappings") and state.get("group_a_name") and state.get("group_b_name"):
            state["selected_tool"] = "differential_expression_screening"
            state["tool_input"] = {
                "project_id": state["project_id"],
                "dataset_id": state["dataset_id"],
                "group_a_name": state["group_a_name"],
                "group_b_name": state["group_b_name"],
                "group_mappings": state["group_mappings"],
                "fdr_threshold": 0.05,
                "alpha": 0.05,
            }
        else:
            # Cannot run differential expression without group annotations
            logger.info("No group mappings found; skipping differential expression.")
            state["next_action"] = "summarize"
            return state
    else:
        # All planned tools completed
        state["next_action"] = "summarize"
        return state

    record_session_event(
        db,
        session_id,
        "TOOL_SELECTED",
        "select_scientific_tool",
        f"Selected scientific tool: '{state['selected_tool']}' (Iteration {state['iteration_count']})",
        {"selected_tool": state["selected_tool"], "tool_input": state["tool_input"]},
    )
    sync_state_to_db(db, state)
    return state


def execute_experiment_node(
    state: ResearchState,
    db: Session,
    current_user: User,
) -> ResearchState:
    """Execute selected scientific tool in sandbox or statistical engine."""
    if state.get("status") == SessionStatus.FAILED.value or state.get("should_pause"):
        return state

    session_id = state["session_id"]
    state["current_step"] = "execute_experiment"
    tool_name = state.get("selected_tool")
    tool_input = state.get("tool_input", {})

    logger.info(f"Executing scientific tool '{tool_name}' for session {session_id}")

    try:
        if tool_name == "pca_exploratory_analysis":
            pca_out = ScientificToolRegistry.run_pca_analysis(
                PCAAnalysisInput(**tool_input),
                current_user=current_user,
                db=db,
            )
            state["last_tool_output"] = pca_out.model_dump()
            state["tool_history"].append({
                "tool_name": tool_name,
                "status": "COMPLETED",
                "output_summary": pca_out.evidence.summary_text,
            })
            state["evidence_store"].append({
                "type": "pca_analysis",
                "n_components": pca_out.n_components,
                "total_variance_explained": pca_out.total_variance_explained,
                "explained_variance_ratio": pca_out.explained_variance_ratio,
                "coordinates": pca_out.coordinates,
                "sample_ids": pca_out.sample_ids,
                "summary": pca_out.evidence.summary_text,
            })
            record_session_event(
                db,
                session_id,
                "TOOL_COMPLETED",
                "execute_experiment",
                pca_out.evidence.summary_text,
                {"pca_summary": pca_out.model_dump()},
            )

        elif tool_name == "differential_expression_screening":
            diff_out = ScientificToolRegistry.run_differential_expression(
                DifferentialExpressionInput(**tool_input),
                current_user=current_user,
                db=db,
            )
            state["last_tool_output"] = diff_out.model_dump()
            state["experiment_ids"].append(diff_out.experiment_id)
            state["tool_history"].append({
                "tool_name": tool_name,
                "experiment_id": diff_out.experiment_id,
                "status": diff_out.status,
                "output_summary": diff_out.evidence.summary_text,
            })
            state["evidence_store"].append({
                "type": "differential_expression",
                "experiment_id": diff_out.experiment_id,
                "status": diff_out.status,
                "total_features_tested": diff_out.total_features_tested,
                "significant_features_count": diff_out.significant_features_count,
                "upregulated_count": diff_out.upregulated_count,
                "downregulated_count": diff_out.downregulated_count,
                "top_significant_features": diff_out.top_significant_features,
                "volcano_plot_url": diff_out.volcano_plot_url,
                "pca_plot_url": diff_out.pca_plot_url,
                "summary": diff_out.evidence.summary_text,
            })
            record_session_event(
                db,
                session_id,
                "EXPERIMENT_COMPLETED",
                "execute_experiment",
                diff_out.evidence.summary_text,
                {"diff_expr": diff_out.model_dump()},
            )
        else:
            raise ValueError(f"Unknown or unpermitted scientific tool: {tool_name}")

    except Exception as exc:
        logger.error(f"Tool execution failed: {exc}")
        state["retry_count"] = state.get("retry_count", 0) + 1
        if state["retry_count"] >= state.get("max_retries", 3):
            state["status"] = SessionStatus.FAILED.value
            state["failure_reason"] = f"Tool execution failed after {state['retry_count']} retries: {str(exc)}"
            record_session_event(db, session_id, "ERROR", "execute_experiment", state["failure_reason"])
        else:
            record_session_event(
                db,
                session_id,
                "WARNING",
                "execute_experiment",
                f"Tool execution attempt failed ({state['retry_count']}/{state.get('max_retries', 3)}): {str(exc)}",
            )

    sync_state_to_db(db, state)
    return state


def evaluate_results_node(
    state: ResearchState,
    db: Session,
    vultr_service: VultrInferenceService,
) -> ResearchState:
    """Evaluate experimental findings strictly against computed metrics using Vultr Inference."""
    if state.get("status") == SessionStatus.FAILED.value or state.get("should_pause"):
        return state

    session_id = state["session_id"]
    state["current_step"] = "evaluate_results"
    state["status"] = SessionStatus.EVALUATING.value

    last_tool = state.get("selected_tool")
    last_output = state.get("last_tool_output", {})

    prompt_messages = [
        {
            "role": "system",
            "content": (
                "You are an expert computational biologist evaluating experimental outputs.\n"
                "STRICT SCIENTIFIC ACCURACY RULES:\n"
                "1. Quote EXACT numerical figures: variance ratios, p-values, FDR q-values, and log2 fold changes.\n"
                "2. DO NOT claim biological discovery or statistical significance if computed results do not substantiate it.\n"
                "3. If significant_features_count is 0, explicitly report zero features met the threshold.\n"
                "4. Structure your response as JSON matching the EvaluationSchema:\n"
                "   - experiment_id (optional string)\n"
                "   - statistical_assessment (detailed analysis of the exact metrics)\n"
                "   - verified_findings (list of factual findings quoting numbers)\n"
                "   - effect_size_summary (summary of fold change / variance magnitude)\n"
                "   - statistical_significance_summary (FDR / p-value rigor statement)\n"
                "   - biological_caveats (methodological limitations, research use only)\n"
                "   - next_step_recommendation ('conclude' or 'additional_analysis')\n"
            ),
        },
        {
            "role": "user",
            "content": (
                f"OBJECTIVE: {state['objective']}\n"
                f"TOOL EVALUATED: {last_tool}\n"
                f"COMPUTED OUTPUT DATA:\n"
                f"{json.dumps(last_output, indent=2)}\n\n"
                "Evaluate the validity and implications of these experimental results."
            ),
        },
    ]

    try:
        response: InferenceResponse = vultr_service.chat_completion(
            messages=prompt_messages,
            response_model=EvaluationSchema,
            temperature=0.2,
        )
        eval_data = response.parsed
        if not eval_data:
            raise VultrInferenceFormatError(f"LLM output for {last_tool} did not match EvaluationSchema.")

        state["last_evaluation"] = eval_data
        state["evidence_store"].append({
            "type": "statistical_evaluation",
            "tool_name": last_tool,
            "evaluation": eval_data,
        })

        record_session_event(
            db,
            session_id,
            "EVALUATION_COMPLETED",
            "evaluate_results",
            f"Evaluated results for {last_tool}: {eval_data.get('statistical_assessment', '')[:200]}...",
            {"evaluation": eval_data, "tokens": response.total_tokens},
        )
    except Exception as exc:
        logger.error(f"Result evaluation failed: {exc}")
        # Non-fatal error: record warning and proceed
        record_session_event(
            db,
            session_id,
            "WARNING",
            "evaluate_results",
            f"Result evaluation inference warning: {str(exc)}",
        )

    sync_state_to_db(db, state)
    return state


def decide_next_step_node(
    state: ResearchState,
    db: Session,
) -> ResearchState:
    """Determine whether to execute another tool or conclude with final summary."""
    if state.get("status") == SessionStatus.FAILED.value or state.get("should_pause"):
        return state

    state["current_step"] = "decide_next_step"
    executed_tools = [h.get("tool_name") for h in state.get("tool_history", [])]

    # If PCA ran and differential expression hasn't run yet, and group mappings exist, run differential expression
    if (
        "pca_exploratory_analysis" in executed_tools
        and "differential_expression_screening" not in executed_tools
        and state.get("group_mappings")
        and state.get("group_a_name")
        and state.get("group_b_name")
    ):
        state["next_action"] = "execute_more"
    else:
        state["next_action"] = "summarize"

    return state


def generate_research_summary_node(
    state: ResearchState,
    db: Session,
    vultr_service: VultrInferenceService,
) -> ResearchState:
    """Generate final comprehensive evidence-grounded research report."""
    if state.get("status") == SessionStatus.FAILED.value or state.get("should_pause"):
        return state

    session_id = state["session_id"]
    logger.info(f"Generating final research summary for session {session_id}")
    state["current_step"] = "generate_research_summary"

    # Compile all evidence items
    evidence_items = state.get("evidence_store", [])

    prompt_messages = [
        {
            "role": "system",
            "content": (
                "You are an autonomous scientific researcher writing a formal research report on cancer transcriptomics.\n"
                "MANDATORY REPORTING CONVENTIONS:\n"
                "1. Base findings exclusively on the provided empirical evidence.\n"
                "2. Explicitly distinguish:\n"
                "   - Observed facts (sample counts, feature counts, distributions)\n"
                "   - Computed results (exact log2 fold changes, Benjamini-Hochberg FDR q-values)\n"
                "   - Biological interpretations\n"
                "   - Unconfirmed hypotheses for future validation\n"
                "3. In the key_findings list, provide the exact feature name, log2_fold_change, fdr_q_value, "
                "regulation_direction ('Upregulated', 'Downregulated', or 'Unchanged'), and brief context.\n"
                "4. Structure your response as JSON matching ResearchSummarySchema:\n"
                "   - title (string)\n"
                "   - executive_summary (string)\n"
                "   - dataset_characteristics (object)\n"
                "   - methodology (string describing PCA and/or Welch's t-test with FDR correction)\n"
                "   - key_findings (list of KeyFinding objects)\n"
                "   - scientific_caveats (list of strings noting limitations, non-clinical scope)\n"
                "   - unconfirmed_hypotheses (list of testable follow-up hypotheses)\n"
                "   - recommended_future_work (list of concrete next experimental steps)\n"
            ),
        },
        {
            "role": "user",
            "content": (
                f"OBJECTIVE: {state['objective']}\n\n"
                f"ACCUMULATED RESEARCH EVIDENCE:\n"
                f"{json.dumps(evidence_items, indent=2)}\n\n"
                "Produce the comprehensive final scientific research summary."
            ),
        },
    ]

    try:
        response: InferenceResponse = vultr_service.chat_completion(
            messages=prompt_messages,
            response_model=ResearchSummarySchema,
            temperature=0.2,
        )
        summary_data = response.parsed
        if not summary_data:
            raise VultrInferenceFormatError("LLM output did not match ResearchSummarySchema.")

        state["final_summary"] = summary_data
        state["status"] = SessionStatus.COMPLETED.value

        record_session_event(
            db,
            session_id,
            "SESSION_COMPLETED",
            "generate_research_summary",
            f"Autonomous research session completed successfully. Final scientific summary generated.",
            {"summary": summary_data, "tokens": response.total_tokens},
        )
    except Exception as exc:
        logger.error(f"Final summary generation failed: {exc}")
        state["status"] = SessionStatus.FAILED.value
        state["failure_reason"] = f"Final summary generation failed: {str(exc)}"
        record_session_event(
            db,
            session_id,
            "ERROR",
            "generate_research_summary",
            state["failure_reason"],
        )

    sync_state_to_db(db, state)
    return state


def complete_or_fail_node(
    state: ResearchState,
    db: Session,
) -> ResearchState:
    """Final wrap-up node."""
    session_id = state["session_id"]
    state["current_step"] = "complete_or_fail"

    if state.get("status") == SessionStatus.FAILED.value:
        record_session_event(
            db,
            session_id,
            "ERROR",
            "complete_or_fail",
            f"Research session terminated with failure: {state.get('failure_reason', 'Unknown error')}",
        )
    elif state.get("status") == SessionStatus.REJECTED.value:
        record_session_event(
            db,
            session_id,
            "STATUS_UPDATE",
            "complete_or_fail",
            f"Research session halted due to plan rejection.",
        )

    sync_state_to_db(db, state)
    return state


# =============================================================================
# Graph Routing Functions
# =============================================================================

def route_after_tool_selection(state: ResearchState) -> str:
    """Route after tool selection node."""
    if state.get("status") == SessionStatus.FAILED.value:
        return "complete_or_fail"
    if state.get("next_action") == "summarize" or not state.get("selected_tool"):
        return "generate_research_summary"
    return "execute_experiment"


def route_initial_step(state: ResearchState) -> str:
    """Route from START depending on whether plan has been approved or is starting fresh."""
    if state.get("approval_state") == ApprovalState.APPROVED.value and state.get("research_plan"):
        return "select_scientific_tool"
    return "initialize_research"


def route_after_approval(state: ResearchState) -> str:
    """Route after human approval node."""
    if state.get("status") in (SessionStatus.FAILED.value, SessionStatus.REJECTED.value):
        return "complete_or_fail"
    return "approval_gate"


def route_after_decide(state: ResearchState) -> str:
    """Route after deciding next step."""
    if state.get("status") == SessionStatus.FAILED.value:
        return "complete_or_fail"
    action = state.get("next_action")
    if action == "execute_more":
        return "select_scientific_tool"
    elif action == "summarize":
        return "generate_research_summary"
    return "complete_or_fail"


# =============================================================================
# Research Workflow Graph Factory & Runner
# =============================================================================

class AutonomousResearchRunner:
    """
    Manages LangGraph compilation and step-by-step stateful execution for
    autonomous scientific research sessions.
    Configured with durable PostgreSQL-backed LangGraph checkpointer and stable thread-id isolation.
    """

    def __init__(
        self,
        db: Session,
        current_user: User,
        vultr_service: Optional[VultrInferenceService] = None,
        checkpointer: Optional[Any] = None,
    ):
        self.db = db
        self.current_user = current_user
        self.vultr_service = vultr_service or VultrInferenceService()
        self.checkpointer = checkpointer if checkpointer is not None else get_postgres_checkpointer()
        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(ResearchState)

        # Wrap nodes with database and service dependencies
        builder.add_node("initialize_research", lambda state: initialize_research_node(state, self.db, self.current_user))
        builder.add_node("inspect_dataset", lambda state: inspect_dataset_node(state, self.db, self.current_user))
        builder.add_node("generate_research_plan", lambda state: generate_research_plan_node(state, self.db, self.vultr_service))
        builder.add_node("await_human_approval", lambda state: await_human_approval_node(state, self.db))
        builder.add_node("approval_gate", lambda state: approval_gate_node(state, self.db))
        builder.add_node("select_scientific_tool", lambda state: select_scientific_tool_node(state, self.db))
        builder.add_node("execute_experiment", lambda state: execute_experiment_node(state, self.db, self.current_user))
        builder.add_node("evaluate_results", lambda state: evaluate_results_node(state, self.db, self.vultr_service))
        builder.add_node("decide_next_step", lambda state: decide_next_step_node(state, self.db))
        builder.add_node("generate_research_summary", lambda state: generate_research_summary_node(state, self.db, self.vultr_service))
        builder.add_node("complete_or_fail", lambda state: complete_or_fail_node(state, self.db))

        # Conditional entry from START
        builder.add_conditional_edges(
            START,
            route_initial_step,
            {
                "initialize_research": "initialize_research",
                "select_scientific_tool": "select_scientific_tool",
            },
        )

        builder.add_edge("initialize_research", "inspect_dataset")
        builder.add_edge("inspect_dataset", "generate_research_plan")
        builder.add_edge("generate_research_plan", "await_human_approval")

        builder.add_conditional_edges(
            "await_human_approval",
            route_after_approval,
            {
                "approval_gate": "approval_gate",
                "complete_or_fail": "complete_or_fail",
            },
        )
        builder.add_edge("approval_gate", "select_scientific_tool")

        builder.add_conditional_edges(
            "select_scientific_tool",
            route_after_tool_selection,
            {
                "execute_experiment": "execute_experiment",
                "generate_research_summary": "generate_research_summary",
                "complete_or_fail": "complete_or_fail",
            },
        )

        builder.add_edge("execute_experiment", "evaluate_results")
        builder.add_edge("evaluate_results", "decide_next_step")

        builder.add_conditional_edges(
            "decide_next_step",
            route_after_decide,
            {
                "select_scientific_tool": "select_scientific_tool",
                "generate_research_summary": "generate_research_summary",
                "complete_or_fail": "complete_or_fail",
            },
        )

        builder.add_edge("generate_research_summary", "complete_or_fail")
        builder.add_edge("complete_or_fail", END)

        return builder.compile(checkpointer=self.checkpointer, interrupt_before=["approval_gate"])

    def run(self, initial_state: ResearchState) -> ResearchState:
        """
        Execute or resume the LangGraph workflow using a stable session-level thread ID.
        If a checkpoint already exists for this thread and is paused, resumes it with the updated state.
        """
        session_id = str(initial_state.get("session_id", "default_thread"))
        config = {"configurable": {"thread_id": session_id}}

        if initial_state.get("approval_state") == ApprovalState.APPROVED.value:
            initial_state["should_pause"] = False

        try:
            curr_state = self.graph.get_state(config)
            if curr_state and curr_state.next:
                # Interrupted / paused checkpoint exists in PostgreSQL - update state and resume
                self.graph.update_state(config, initial_state)
                return self.graph.invoke(None, config=config)
        except Exception as e:
            logger.debug(f"No existing paused checkpoint for {session_id}: {e}")

        return self.graph.invoke(initial_state, config=config)

    @classmethod
    def load_session_state(cls, db: Session, session_id: str) -> ResearchState:
        """Load state dict from a persistent ResearchSession record."""
        session = db.query(ResearchSession).filter(ResearchSession.id == session_id).first()
        if not session:
            raise ValueError(f"Session {session_id} not found.")

        dataset = db.query(Dataset).filter(Dataset.id == session.dataset_id).first() if session.dataset_id else None
        group_mappings = None
        if dataset and dataset.group_mappings:
            try:
                group_mappings = json.loads(dataset.group_mappings)
            except Exception:
                group_mappings = None

        state: ResearchState = {
            "session_id": session.id,
            "project_id": session.project_id,
            "dataset_id": session.dataset_id,
            "user_id": session.owner_id,
            "objective": session.objective,
            "dataset_hash": session.dataset_hash,
            "status": session.status,
            "current_step": session.current_step,
            "approval_state": session.approval_state,
            "approval_notes": session.approval_notes,
            "group_a_name": dataset.control_group if dataset else None,
            "group_b_name": dataset.treatment_group if dataset else None,
            "group_mappings": group_mappings,
            "iteration_count": session.iteration_count,
            "max_iterations": session.max_iterations,
            "retry_count": session.retry_count,
            "max_retries": session.max_retries,
            "failure_reason": session.failure_reason,
            "research_plan": json.loads(session.research_plan) if session.research_plan else None,
            "experiment_ids": json.loads(session.experiment_ids) if session.experiment_ids else [],
            "tool_history": json.loads(session.tool_history) if session.tool_history else [],
            "evidence_store": json.loads(session.evidence_store) if session.evidence_store else [],
            "final_summary": json.loads(session.final_summary) if session.final_summary else None,
            "should_pause": (session.approval_state == ApprovalState.PENDING.value),
        }
        return state

