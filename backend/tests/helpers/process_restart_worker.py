import argparse
import json
import os
import sys

# Ensure backend root is in sys.path
backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

# Force test configuration
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET_KEY"] = "test-cryptographically-secure-key-for-unit-testing-32-chars"

from app.core.config import settings
PG_URL = settings.DATABASE_URL

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    ApprovalState,
    Dataset,
    Project,
    ResearchSession,
    SessionStatus,
    User,
    UserRole,
    utc_now,
)
from app.services.research_graph import (
    AutonomousResearchRunner,
    ResearchPlanSchema,
    EvaluationSchema,
    ResearchSummarySchema,
)
from app.services.vultr_inference import InferenceResponse, VultrInferenceService


def mock_vultr_for_process(messages, response_model=None):
    if response_model == ResearchPlanSchema:
        plan = {
            "objective": "Screen candidate transcriptomic targets across cohort",
            "observed_facts": ["10 features, 6 samples", "Scale: log2_transformed"],
            "assumptions_hypotheses": ["Expression differences exist between groups"],
            "proposed_experiments": [
                {
                    "tool_name": "pca_exploratory_analysis",
                    "description": "Exploratory PCA for cohort",
                    "rationale": "Assess overall variance structure",
                    "parameters": {"n_components": 2},
                }
            ],
            "expected_outcomes": ["PCA scree and coordinates"],
            "scientific_limitations": ["Limited sample size"],
        }
        return InferenceResponse(
            content=json.dumps(plan),
            parsed=plan,
            model="llama-3.3-70b-instruct-fp8",
            duration_seconds=0.05,
        )
    elif response_model == EvaluationSchema:
        ev = {
            "statistical_assessment": "PCA performed deterministically across 6 samples.",
            "verified_findings": ["First 2 principal components capture total cohort variance."],
            "effect_size_summary": "Variance explained calculated.",
            "statistical_significance_summary": "Exploratory dimensionality reduction completed.",
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
        sm = {
            "title": "Autonomous Investigation Summary",
            "executive_summary": "Process restart persistence verification completed successfully.",
            "dataset_characteristics": {"samples": 6, "features": 10},
            "methodology": "Exploratory PCA dimensionality reduction.",
            "key_findings": [
                {
                    "feature_name": "PC1",
                    "log2_fold_change": 1.0,
                    "fdr_q_value": 0.01,
                    "regulation_direction": "Upregulated",
                    "biological_context": "Dominant variance axis",
                }
            ],
            "scientific_caveats": ["Research platform only."],
            "unconfirmed_hypotheses": ["Variance correlates with biological phenotype."],
            "recommended_future_work": ["Validation with orthogonal assays."],
        }
        return InferenceResponse(
            content=json.dumps(sm),
            parsed=sm,
            model="llama-3.3-70b-instruct-fp8",
            duration_seconds=0.05,
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", required=True, choices=["start_and_pause", "approve_and_resume"])
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--plan-hash", default=None)
    args = parser.parse_args()

    engine = create_engine(PG_URL, pool_pre_ping=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()

    try:
        session = db.query(ResearchSession).filter(ResearchSession.id == args.session_id).first()
        if not session:
            print(f"ERROR: Session {args.session_id} not found", file=sys.stderr)
            sys.exit(1)

        user = db.query(User).filter(User.id == session.owner_id).first()
        vultr = VultrInferenceService(mock_handler=mock_vultr_for_process)

        if args.step == "start_and_pause":
            print("WORKER: Loading session state...", flush=True)
            state = AutonomousResearchRunner.load_session_state(db, session.id)
            print("WORKER: Instantiating AutonomousResearchRunner...", flush=True)
            runner = AutonomousResearchRunner(db=db, current_user=user, vultr_service=vultr)
            print("WORKER: Calling runner.run(state)...", flush=True)
            res = runner.run(state)
            print("WORKER: runner.run(state) returned!", flush=True)
            db.refresh(session)
            print(f"STEP1_COMPLETE: status={session.status}, approval_state={session.approval_state}", flush=True)
            if session.status != SessionStatus.AWAITING_APPROVAL.value:
                print(f"ERROR: Expected status Awaiting Approval, got {session.status}", file=sys.stderr, flush=True)
                sys.exit(2)
            sys.exit(0)

        elif args.step == "approve_and_resume":
            if not session.research_plan:
                print("ERROR: No research plan present to approve", file=sys.stderr)
                sys.exit(3)

            plan_dict = json.loads(session.research_plan)
            actual_hash = plan_dict.get("plan_hash")
            if args.plan_hash and args.plan_hash != actual_hash:
                print(f"ERROR: Plan hash mismatch: expected {actual_hash}, got {args.plan_hash}", file=sys.stderr)
                sys.exit(4)

            # Approve plan
            session.approval_state = ApprovalState.APPROVED.value
            session.approval_notes = "Approved by separate process tester"
            session.approved_at = utc_now()
            session.status = SessionStatus.APPROVED.value
            db.commit()
            db.refresh(session)

            # Resume execution
            resumed_state = AutonomousResearchRunner.load_session_state(db, session.id)
            resumed_state["approval_state"] = ApprovalState.APPROVED.value
            resumed_state["approval_notes"] = "Approved by separate process tester"

            runner = AutonomousResearchRunner(db=db, current_user=user, vultr_service=vultr)
            res = runner.run(resumed_state)

            db.refresh(session)
            print(f"STEP2_COMPLETE: status={session.status}")
            if session.status != SessionStatus.COMPLETED.value:
                print(f"ERROR: Expected status Completed, got {session.status}", file=sys.stderr)
                sys.exit(5)
            sys.exit(0)

    finally:
        db.close()


if __name__ == "__main__":
    main()
