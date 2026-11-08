import json
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.models import Dataset, Experiment, ExperimentStatus, Project, User, UserRole
from app.services.dataset_parser import parse_scientific_dataset
from app.services.dataset_quality import compute_dataset_quality, evaluate_scale, validate_group_mappings
from app.services.sandbox import SandboxExecutionService
from app.services.statistical_engine import (
    compute_pca_projection,
    generate_sandbox_script,
    validate_differential_expression_design,
)
from app.services.storage import get_artifact_dir, get_upload_dir, resolve_safe_path

logger = logging.getLogger("neuroforge.scientific_tools")


def _load_parsed_dataset(dataset: Dataset):
    """Safely resolve and parse dataset directly from storage path without memory duplication."""
    upload_dir = get_upload_dir()
    file_path = resolve_safe_path(upload_dir, dataset.filename)
    return parse_scientific_dataset(file_path, original_filename=dataset.original_name, content_hash=dataset.content_hash)



# =============================================================================
# Typed Schemas for Scientific Tool Registry
# =============================================================================

class ToolEvidence(BaseModel):
    tool_name: str
    dataset_id: str
    dataset_hash: Optional[str] = None
    experiment_id: Optional[str] = None
    metric_summary: Dict[str, Any] = Field(default_factory=dict)
    summary_text: str


# Tool 1: Dataset Inspection
class DatasetInspectInput(BaseModel):
    dataset_id: str


class DatasetInspectOutput(BaseModel):
    dataset_id: str
    filename: str
    content_hash: Optional[str]
    sample_count: int
    feature_count: int
    matrix_orientation: str
    scale_inference: str
    is_log2: bool
    sample_ids: List[str]
    evidence: ToolEvidence


# Tool 2: Dataset Quality Assessment
class DatasetQualityInput(BaseModel):
    dataset_id: str
    group_a_name: Optional[str] = None
    group_b_name: Optional[str] = None
    group_mappings: Optional[Dict[str, str]] = None


class DatasetQualityOutput(BaseModel):
    dataset_id: str
    readiness_state: str
    is_ready_for_welch_t: bool
    sample_size_adequate: bool
    missing_cells_count: int
    constant_features_count: int
    assigned_samples_count: int
    unassigned_samples_count: int
    warnings: List[str]
    caveats: List[str]
    evidence: ToolEvidence


# Tool 3: Dataset Preview
class DatasetPreviewInput(BaseModel):
    dataset_id: str
    max_features: int = 10
    max_samples: int = 10


class DatasetPreviewOutput(BaseModel):
    dataset_id: str
    preview_features: List[str]
    preview_samples: List[str]
    data_preview: List[Dict[str, Any]]
    evidence: ToolEvidence


# Tool 4: PCA Exploratory Analysis
class PCAAnalysisInput(BaseModel):
    dataset_id: str
    sample_ids: Optional[List[str]] = None
    n_components: int = 2


class PCAAnalysisOutput(BaseModel):
    dataset_id: str
    n_components: int
    explained_variance_ratio: List[float]
    total_variance_explained: float
    sample_ids: List[str]
    coordinates: List[List[float]]
    preprocessing_notes: List[str]
    evidence: ToolEvidence


# Tool 5: Differential Expression Screening (Welch's t-test in Docker Sandbox)
class DifferentialExpressionInput(BaseModel):
    project_id: str
    dataset_id: str
    group_a_name: str
    group_b_name: str
    group_mappings: Dict[str, str]
    fdr_threshold: float = 0.05
    alpha: float = 0.05


class DifferentialExpressionOutput(BaseModel):
    experiment_id: str
    status: str
    dataset_id: str
    dataset_hash: Optional[str]
    total_features_tested: int
    significant_features_count: int
    upregulated_count: int
    downregulated_count: int
    top_significant_features: List[Dict[str, Any]]
    volcano_plot_url: Optional[str] = None
    pca_plot_url: Optional[str] = None
    heatmap_plot_url: Optional[str] = None
    evidence: ToolEvidence


# Tool 6: Experiment Results Retrieval
class ExperimentResultsRetrieveInput(BaseModel):
    experiment_id: str


class ExperimentResultsRetrieveOutput(BaseModel):
    experiment_id: str
    status: str
    dataset_id: Optional[str]
    dataset_hash: Optional[str]
    duration_seconds: Optional[float]
    statistical_summary: Optional[Dict[str, Any]]
    artifacts: List[Dict[str, Any]]
    evidence: ToolEvidence


# =============================================================================
# Scientific Tool Registry Implementation
# =============================================================================

class ScientificToolRegistry:
    """
    Controlled registry of validated scientific operations that can be invoked
    by the autonomous agent. All operations enforce:
    - User ownership and project RBAC checks.
    - Zero execution of arbitrary code from LLM responses.
    - Deterministic execution in isolated Docker sandbox where applicable.
    - Cryptographic evidence attribution.
    """

    @staticmethod
    def inspect_dataset(
        payload: DatasetInspectInput,
        current_user: User,
        db: Session,
    ) -> DatasetInspectOutput:
        dataset = db.query(Dataset).filter(Dataset.id == payload.dataset_id).first()
        if not dataset:
            raise ValueError(f"Dataset {payload.dataset_id} not found.")

        # RBAC Check
        if current_user.role != UserRole.ADMIN.value and dataset.owner_id != current_user.id:
            raise PermissionError("Access denied: You do not own this dataset.")

        parsed = _load_parsed_dataset(dataset)
        scale_inference, _ = evaluate_scale(parsed.numeric_matrix.values)
        is_log2 = (scale_inference == "log2_transformed")
        matrix_orientation = parsed.orientation.detected_orientation

        evidence = ToolEvidence(
            tool_name="dataset_inspect",
            dataset_id=dataset.id,
            dataset_hash=dataset.content_hash,
            metric_summary={
                "sample_count": parsed.num_samples,
                "feature_count": parsed.num_features,
                "matrix_orientation": matrix_orientation,
                "scale_inference": scale_inference,
                "is_log2": is_log2,
            },
            summary_text=(
                f"Inspected dataset '{dataset.original_name}': {parsed.num_features} features, "
                f"{parsed.num_samples} samples. Inferred scale: {scale_inference}. "
                f"Orientation: {matrix_orientation}."
            ),
        )

        return DatasetInspectOutput(
            dataset_id=dataset.id,
            filename=dataset.original_name,
            content_hash=dataset.content_hash,
            sample_count=parsed.num_samples,
            feature_count=parsed.num_features,
            matrix_orientation=matrix_orientation,
            scale_inference=scale_inference,
            is_log2=is_log2,
            sample_ids=parsed.sample_ids,
            evidence=evidence,
        )

    @staticmethod
    def assess_dataset_quality(
        payload: DatasetQualityInput,
        current_user: User,
        db: Session,
    ) -> DatasetQualityOutput:
        dataset = db.query(Dataset).filter(Dataset.id == payload.dataset_id).first()
        if not dataset:
            raise ValueError(f"Dataset {payload.dataset_id} not found.")

        if current_user.role != UserRole.ADMIN.value and dataset.owner_id != current_user.id:
            raise PermissionError("Access denied: You do not own this dataset.")

        parsed = _load_parsed_dataset(dataset)

        # Parse stored group mappings if not provided
        group_map = payload.group_mappings
        if not group_map and dataset.group_mappings:
            try:
                group_map = json.loads(dataset.group_mappings)
            except Exception:
                group_map = {}

        grp_a = payload.group_a_name or dataset.control_group or "Control"
        grp_b = payload.group_b_name or dataset.treatment_group or "Treatment"

        quality = compute_dataset_quality(parsed.numeric_matrix, group_map, grp_a, grp_b)
        gv = quality.group_validation
        readiness_state = gv.readiness_state if gv else "metadata_incomplete"
        is_ready = gv.is_ready_for_testing if gv else False
        sample_size_adequate = gv.sample_counts_valid if gv else False
        assigned_samples_count = gv.assigned_samples_count if gv else 0
        unassigned_samples_count = gv.unassigned_samples_count if gv else parsed.num_samples
        warnings = gv.warnings if gv else []
        caveats = gv.caveats if gv else []

        evidence = ToolEvidence(
            tool_name="dataset_quality",
            dataset_id=dataset.id,
            dataset_hash=dataset.content_hash,
            metric_summary={
                "readiness_state": readiness_state,
                "is_ready_for_welch_t": is_ready,
                "missing_cells_count": quality.missing_cells_count,
                "constant_features_count": quality.constant_features_count,
            },
            summary_text=(
                f"Quality assessment for '{dataset.original_name}': Readiness state '{readiness_state}'. "
                f"Ready for Welch t-test: {is_ready}. "
                f"Missing cells: {quality.missing_cells_count}. Zero-variance features: {quality.constant_features_count}."
            ),
        )

        return DatasetQualityOutput(
            dataset_id=dataset.id,
            readiness_state=readiness_state,
            is_ready_for_welch_t=is_ready,
            sample_size_adequate=sample_size_adequate,
            missing_cells_count=quality.missing_cells_count,
            constant_features_count=quality.constant_features_count,
            assigned_samples_count=assigned_samples_count,
            unassigned_samples_count=unassigned_samples_count,
            warnings=warnings,
            caveats=caveats,
            evidence=evidence,
        )

    @staticmethod
    def preview_dataset(
        payload: DatasetPreviewInput,
        current_user: User,
        db: Session,
    ) -> DatasetPreviewOutput:
        dataset = db.query(Dataset).filter(Dataset.id == payload.dataset_id).first()
        if not dataset:
            raise ValueError(f"Dataset {payload.dataset_id} not found.")

        if current_user.role != UserRole.ADMIN.value and dataset.owner_id != current_user.id:
            raise PermissionError("Access denied: You do not own this dataset.")

        parsed = _load_parsed_dataset(dataset)

        preview_df = parsed.numeric_matrix.iloc[:payload.max_features, :payload.max_samples]
        records = preview_df.reset_index().to_dict(orient="records")

        evidence = ToolEvidence(
            tool_name="dataset_preview",
            dataset_id=dataset.id,
            dataset_hash=dataset.content_hash,
            metric_summary={
                "preview_features_count": len(preview_df),
                "preview_samples_count": len(preview_df.columns),
            },
            summary_text=f"Previewed {len(preview_df)} features across {len(preview_df.columns)} samples.",
        )

        return DatasetPreviewOutput(
            dataset_id=dataset.id,
            preview_features=list(preview_df.index.astype(str)),
            preview_samples=list(preview_df.columns.astype(str)),
            data_preview=records,
            evidence=evidence,
        )

    @staticmethod
    def run_pca_analysis(
        payload: PCAAnalysisInput,
        current_user: User,
        db: Session,
    ) -> PCAAnalysisOutput:
        dataset = db.query(Dataset).filter(Dataset.id == payload.dataset_id).first()
        if not dataset:
            raise ValueError(f"Dataset {payload.dataset_id} not found.")

        if current_user.role != UserRole.ADMIN.value and dataset.owner_id != current_user.id:
            raise PermissionError("Access denied: You do not own this dataset.")

        parsed = _load_parsed_dataset(dataset)

        target_samples = payload.sample_ids or parsed.sample_ids
        pca_result = compute_pca_projection(
            df=parsed.numeric_matrix,
            sample_ids=target_samples,
            n_components=payload.n_components,
        )

        evidence = ToolEvidence(
            tool_name="pca_exploratory_analysis",
            dataset_id=dataset.id,
            dataset_hash=dataset.content_hash,
            metric_summary={
                "pc1_variance": pca_result.explained_variance_ratio[0] if pca_result.explained_variance_ratio else 0.0,
                "pc2_variance": pca_result.explained_variance_ratio[1] if len(pca_result.explained_variance_ratio) > 1 else 0.0,
                "total_variance_explained": pca_result.total_variance_explained,
                "samples_projected": len(pca_result.sample_ids),
            },
            summary_text=(
                f"Fitted PCA across {len(pca_result.sample_ids)} samples. "
                f"PC1 explains {pca_result.explained_variance_ratio[0]*100:.1f}% variance; "
                f"PC2 explains {pca_result.explained_variance_ratio[1]*100:.1f}% variance."
            ),
        )

        return PCAAnalysisOutput(
            dataset_id=dataset.id,
            n_components=pca_result.n_components,
            explained_variance_ratio=pca_result.explained_variance_ratio,
            total_variance_explained=pca_result.total_variance_explained,
            sample_ids=pca_result.sample_ids,
            coordinates=pca_result.coordinates,
            preprocessing_notes=pca_result.preprocessing_notes,
            evidence=evidence,
        )

    @staticmethod
    def run_differential_expression(
        payload: DifferentialExpressionInput,
        current_user: User,
        db: Session,
    ) -> DifferentialExpressionOutput:
        # 1. Project & Dataset RBAC verification
        project = db.query(Project).filter(Project.id == payload.project_id).first()
        if not project:
            raise ValueError("Target research project not found.")
        if current_user.role != UserRole.ADMIN.value and project.owner_id != current_user.id:
            raise PermissionError("Access denied: You do not own this project.")

        dataset = db.query(Dataset).filter(Dataset.id == payload.dataset_id).first()
        if not dataset:
            raise ValueError("Target scientific dataset not found.")
        if current_user.role != UserRole.ADMIN.value and dataset.owner_id != current_user.id:
            raise PermissionError("Access denied: You do not own this dataset.")

        # 2. Parse and validate experimental design
        parsed = _load_parsed_dataset(dataset)
        scale_inference, _ = evaluate_scale(parsed.numeric_matrix.values)
        matrix_orientation = parsed.orientation.detected_orientation

        design_valid, design_reason, samples_a, samples_b = validate_differential_expression_design(
            dataset_orientation=matrix_orientation,
            scale_inference=scale_inference,
            group_mappings=payload.group_mappings,
            sample_ids=parsed.sample_ids,
            group_a_name=payload.group_a_name,
            group_b_name=payload.group_b_name,
            min_samples=3,
        )
        if not design_valid:
            raise ValueError(f"Scientific design rejection: {design_reason}")

        # 3. Create database experiment record
        experiment = Experiment(
            project_id=project.id,
            dataset_id=dataset.id,
            owner_id=current_user.id,
            title=f"Autonomous DE: {payload.group_b_name} vs {payload.group_a_name}",
            description=f"Autonomous differential expression screening using Welch's t-test (FDR <= {payload.fdr_threshold}).",
            code="",  # Generated deterministically below
            status=ExperimentStatus.RUNNING.value,
            experiment_type="differential_expression_welch",
            dataset_hash=dataset.content_hash,
        )
        db.add(experiment)
        db.commit()
        db.refresh(experiment)

        # 4. Generate deterministic sandbox script
        script_code = generate_sandbox_script(
            dataset_id=dataset.id,
            dataset_hash=dataset.content_hash or "unverified",
            group_a_name=payload.group_a_name,
            group_b_name=payload.group_b_name,
            group_mappings=payload.group_mappings,
            scale_inference=scale_inference,
            fdr_threshold=payload.fdr_threshold,
            alpha=payload.alpha,
        )
        experiment.code = script_code
        db.commit()

        # 5. Execute inside isolated Docker sandbox container
        exec_result = SandboxExecutionService.execute(
            experiment_id=experiment.id,
            code=script_code,
            dataset_filename=dataset.filename,
            timeout_seconds=60,
        )

        # 6. Read artifacts and summary
        artifact_dir = get_artifact_dir(experiment.id)
        manifest_file = artifact_dir / "reproducibility_manifest.json"
        results_json_file = artifact_dir / "differential_expression_results.json"

        manifest_json = None
        stats_data = {}
        top_features = []

        if manifest_file.exists():
            try:
                manifest_json = manifest_file.read_text(encoding="utf-8")
                stats_data = json.loads(manifest_json)
            except Exception:
                pass

        if results_json_file.exists():
            try:
                res_dict = json.loads(results_json_file.read_text(encoding="utf-8"))
                top_features = res_dict.get("top_features", [])
            except Exception:
                pass

        # Update experiment in DB
        experiment.status = exec_result.status.value
        experiment.started_at = exec_result.started_at
        experiment.completed_at = exec_result.completed_at
        experiment.duration_seconds = exec_result.duration_seconds
        experiment.exit_code = exec_result.exit_code
        experiment.stdout = exec_result.stdout
        experiment.stderr = exec_result.stderr
        experiment.result_summary = exec_result.result_summary
        experiment.artifacts = json.dumps(exec_result.artifacts) if exec_result.artifacts else None
        experiment.reproducibility_manifest = manifest_json
        experiment.statistical_summary = json.dumps(stats_data) if stats_data else None
        experiment.failure_reason = exec_result.failure_reason
        db.commit()

        if exec_result.status != ExperimentStatus.COMPLETED:
            raise RuntimeError(f"Experiment execution failed in sandbox: {exec_result.failure_reason}")

        volcano_url = None
        pca_url = None
        heatmap_url = None
        for art in exec_result.artifacts:
            if art.get("filename") == "volcano_plot.png":
                volcano_url = art.get("download_url")
            elif art.get("filename") == "pca_plot.png":
                pca_url = art.get("download_url")
            elif art.get("filename") == "heatmap_plot.png":
                heatmap_url = art.get("download_url")

        sig_count = int(stats_data.get("significant_features_count", 0))
        up_count = int(stats_data.get("upregulated_count", 0))
        down_count = int(stats_data.get("downregulated_count", 0))
        total_tested = int(stats_data.get("total_features_tested", parsed.num_features))

        evidence = ToolEvidence(
            tool_name="differential_expression_screening",
            dataset_id=dataset.id,
            dataset_hash=dataset.content_hash,
            experiment_id=experiment.id,
            metric_summary={
                "significant_features_count": sig_count,
                "upregulated_count": up_count,
                "downregulated_count": down_count,
                "total_features_tested": total_tested,
                "fdr_threshold": payload.fdr_threshold,
            },
            summary_text=(
                f"Executed differential expression screening (Welch's t-test, FDR <= {payload.fdr_threshold}). "
                f"Screened {total_tested} features: {sig_count} statistically significant "
                f"({up_count} upregulated, {down_count} downregulated in {payload.group_b_name} vs {payload.group_a_name})."
            ),
        )

        return DifferentialExpressionOutput(
            experiment_id=experiment.id,
            status=experiment.status,
            dataset_id=dataset.id,
            dataset_hash=dataset.content_hash,
            total_features_tested=total_tested,
            significant_features_count=sig_count,
            upregulated_count=up_count,
            downregulated_count=down_count,
            top_significant_features=top_features[:20],
            volcano_plot_url=volcano_url,
            pca_plot_url=pca_url,
            heatmap_plot_url=heatmap_url,
            evidence=evidence,
        )

    @staticmethod
    def retrieve_experiment_results(
        payload: ExperimentResultsRetrieveInput,
        current_user: User,
        db: Session,
    ) -> ExperimentResultsRetrieveOutput:
        experiment = db.query(Experiment).filter(Experiment.id == payload.experiment_id).first()
        if not experiment:
            raise ValueError(f"Experiment {payload.experiment_id} not found.")

        if current_user.role != UserRole.ADMIN.value and experiment.owner_id != current_user.id:
            raise PermissionError("Access denied: You do not own this experiment.")

        stats_summary = None
        if experiment.statistical_summary:
            try:
                stats_summary = json.loads(experiment.statistical_summary)
            except Exception:
                pass

        artifacts = []
        if experiment.artifacts:
            try:
                artifacts = json.loads(experiment.artifacts)
            except Exception:
                pass

        evidence = ToolEvidence(
            tool_name="experiment_results_retrieve",
            dataset_id=experiment.dataset_id or "unknown",
            dataset_hash=experiment.dataset_hash,
            experiment_id=experiment.id,
            metric_summary=stats_summary or {},
            summary_text=f"Retrieved experiment '{experiment.title}': status '{experiment.status}'.",
        )

        return ExperimentResultsRetrieveOutput(
            experiment_id=experiment.id,
            status=experiment.status,
            dataset_id=experiment.dataset_id,
            dataset_hash=experiment.dataset_hash,
            duration_seconds=experiment.duration_seconds,
            statistical_summary=stats_summary,
            artifacts=artifacts,
            evidence=evidence,
        )

