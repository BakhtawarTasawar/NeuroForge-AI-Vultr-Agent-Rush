import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_roles, verify_csrf
from app.db.models import Dataset, Experiment, ExperimentStatus, Project, User, UserRole
from app.schemas.models import (
    ArtifactInfo,
    ComparisonFeatureItem,
    ExperimentComparisonResponse,
    ExperimentCreateRequest,
    ExperimentResponse,
    ExperimentResultsDetailResponse,
    FeatureResultResponse,
)
from app.services.dataset_parser import parse_scientific_dataset
from app.services.dataset_quality import compute_dataset_quality
from app.services.sandbox import SandboxExecutionService
from app.services.statistical_engine import (
    generate_sandbox_script,
    validate_differential_expression_design,
)
from app.services.storage import get_artifact_dir, get_upload_dir, resolve_safe_path

router = APIRouter(tags=["Experiment Workspace"])


def parse_json_safely(val: Optional[str]) -> Optional[Dict[str, Any]]:
    if not val:
        return None
    try:
        return json.loads(val)
    except Exception:
        return None


def parse_artifacts_json(artifacts_str: str | None, experiment_id: str) -> List[ArtifactInfo]:
    if not artifacts_str:
        return []
    try:
        data = json.loads(artifacts_str)
        result = []
        for item in data:
            result.append(
                ArtifactInfo(
                    filename=item.get("filename", "output"),
                    size_bytes=int(item.get("size_bytes", 0)),
                    content_type=item.get("content_type", "application/octet-stream"),
                    download_url=f"/experiments/{experiment_id}/artifacts/{item.get('filename')}",
                )
            )
        return result
    except Exception:
        return []


def to_experiment_response(exp: Experiment) -> ExperimentResponse:
    owner_name = exp.owner.full_name if exp.owner else "Researcher"
    artifacts_list = parse_artifacts_json(exp.artifacts, exp.id)

    return ExperimentResponse(
        id=exp.id,
        project_id=exp.project_id,
        dataset_id=exp.dataset_id,
        owner_id=exp.owner_id,
        owner_name=owner_name,
        title=exp.title,
        description=exp.description,
        experiment_type=exp.experiment_type or "differential_expression_welch",
        dataset_hash=exp.dataset_hash,
        status=exp.status,
        started_at=exp.started_at,
        completed_at=exp.completed_at,
        duration_seconds=exp.duration_seconds,
        exit_code=exp.exit_code,
        stdout=exp.stdout,
        stderr=exp.stderr,
        result_summary=exp.result_summary,
        artifacts=artifacts_list,
        statistical_summary=parse_json_safely(exp.statistical_summary),
        reproducibility_manifest=parse_json_safely(exp.reproducibility_manifest),
        failure_reason=exp.failure_reason,
        created_at=exp.created_at,
    )


@router.post(
    "/projects/{project_id}/experiments",
    response_model=ExperimentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit and execute a scientific experiment inside the isolated sandbox",
)
def create_and_run_experiment(
    project_id: str,
    payload: ExperimentCreateRequest,
    request: Request,
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.RESEARCHER])),
    db: Session = Depends(get_db),
):
    verify_csrf(request)

    # 1. Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested scientific research project was not found.",
        )

    # 2. Enforce project ownership (or Admin)
    if current_user.role != UserRole.ADMIN.value and project.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to execute experiments in this project.",
        )

    # 3. Handle dataset and code generation
    dataset_filename = None
    dataset_hash = None
    experiment_code = payload.code

    if payload.dataset_id:
        dataset = db.query(Dataset).filter(Dataset.id == payload.dataset_id).first()
        if not dataset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="The requested dataset was not found.",
            )
        # Ensure user has access to dataset
        if current_user.role != UserRole.ADMIN.value and dataset.owner_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access the specified dataset.",
            )
        dataset_filename = dataset.filename
        dataset_hash = dataset.content_hash

        # If differential_expression_welch and no custom code provided: generate deterministic scientific script
        if payload.experiment_type == "differential_expression_welch" and not experiment_code:
            upload_dir = get_upload_dir()
            file_path = resolve_safe_path(upload_dir, dataset.filename)
            if not file_path.exists():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Dataset storage file could not be located.",
                )
            parsed = parse_scientific_dataset(file_path, dataset.original_name, content_hash=dataset.content_hash)

            # Determine scale inference from quality assessment
            scale_inference = "log2_transformed"
            if dataset.quality_assessment:
                try:
                    q_data = json.loads(dataset.quality_assessment)
                    scale_inference = q_data.get("distribution", {}).get("scale_inference", "log2_transformed")
                except Exception:
                    pass

            # Resolve comparison groups
            group_a = payload.group_a_name or dataset.control_group or "Control"
            group_b = payload.group_b_name or dataset.treatment_group or "Treatment"

            # Resolve group mappings
            group_map = payload.group_mappings
            if not group_map and dataset.group_mappings:
                try:
                    group_map = json.loads(dataset.group_mappings)
                except Exception:
                    group_map = {}

            if not group_map:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No sample group assignments configured. Assign samples to comparison groups before running analysis.",
                )

            # Validate scientific design
            is_valid, err_msg, _, _ = validate_differential_expression_design(
                dataset_orientation=dataset.matrix_orientation,
                scale_inference=scale_inference,
                group_mappings=group_map,
                sample_ids=parsed.sample_ids,
                group_a_name=group_a,
                group_b_name=group_b,
                min_samples=3,
            )
            if not is_valid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=err_msg,
                )

            experiment_code = generate_sandbox_script(
                group_mappings=group_map,
                group_a_name=group_a,
                group_b_name=group_b,
                dataset_id=dataset.id,
                dataset_hash=dataset.content_hash or "unverified",
                scale_inference=scale_inference,
                fdr_threshold=payload.fdr_threshold or 0.05,
                alpha=payload.alpha or 0.05,
            )

    if not experiment_code or len(experiment_code.strip()) < 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Scientific analysis code or configuration must be provided.",
        )

    # 4. Create initial experiment record
    experiment = Experiment(
        project_id=project.id,
        dataset_id=payload.dataset_id,
        owner_id=current_user.id,
        title=payload.title.strip(),
        description=payload.description.strip() if payload.description else None,
        code=experiment_code,
        experiment_type=payload.experiment_type or "differential_expression_welch",
        dataset_hash=dataset_hash,
        status=ExperimentStatus.RUNNING.value,
    )
    db.add(experiment)
    db.commit()
    db.refresh(experiment)

    # 5. Execute code in isolated Docker sandbox
    exec_result = SandboxExecutionService.execute(
        experiment_id=experiment.id,
        code=experiment_code,
        dataset_filename=dataset_filename,
    )

    # 6. Check for generated scientific manifests in artifact directory
    artifact_dir = get_artifact_dir(experiment.id)
    manifest_file = artifact_dir / "reproducibility_manifest.json"
    results_json_file = artifact_dir / "differential_expression_results.json"

    manifest_json = None
    stats_json = None

    if manifest_file.exists():
        try:
            manifest_json = manifest_file.read_text(encoding="utf-8")
        except Exception:
            pass

    if results_json_file.exists():
        try:
            res_data = json.loads(results_json_file.read_text(encoding="utf-8"))
            stats_json = json.dumps(res_data.get("manifest", {}))
        except Exception:
            pass

    # 7. Update experiment with results
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
    experiment.statistical_summary = stats_json
    experiment.failure_reason = exec_result.failure_reason

    db.commit()
    db.refresh(experiment)

    return to_experiment_response(experiment)


@router.get(
    "/experiments/{experiment_id}/results",
    response_model=ExperimentResultsDetailResponse,
    summary="Get structured statistical results, top features, and reproducibility details",
)
def get_experiment_results(
    experiment_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=5, le=200),
    search: Optional[str] = Query(None),
    sort_by: str = Query("adj_p_value"),
    sort_dir: str = Query("asc"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    experiment = db.query(Experiment).filter(Experiment.id == experiment_id).first()
    if not experiment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Experiment not found.",
        )

    if current_user.role != UserRole.ADMIN.value and experiment.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view results for this experiment.",
        )

    # Check for differential_expression_results.csv artifact
    artifact_dir = get_artifact_dir(experiment.id)
    csv_file = artifact_dir / "differential_expression_results.csv"

    features_list: List[FeatureResultResponse] = []
    total_features = 0

    if csv_file.exists():
        try:
            import pandas as pd
            df = pd.read_csv(csv_file)
            
            if search and "feature_id" in df.columns:
                df = df[df["feature_id"].astype(str).str.contains(search, case=False, na=False)]

            total_features = len(df)

            # Sort
            if sort_by in df.columns:
                ascending = (sort_dir.lower() == "asc")
                df = df.sort_values(by=sort_by, ascending=ascending)

            # Pagination
            start_idx = (page - 1) * limit
            end_idx = start_idx + limit
            sliced = df.iloc[start_idx:end_idx]

            for _, row in sliced.iterrows():
                features_list.append(
                    FeatureResultResponse(
                        feature_id=str(row.get("feature_id", "")),
                        n_a=int(row.get("n_a", 0)),
                        n_b=int(row.get("n_b", 0)),
                        mean_a=float(row.get("mean_a", 0.0)),
                        mean_b=float(row.get("mean_b", 0.0)),
                        mean_diff=float(row.get("mean_diff", 0.0)),
                        log2_fc=float(row.get("log2_fc")) if pd.notna(row.get("log2_fc")) else None,
                        t_stat=float(row.get("t_stat")) if pd.notna(row.get("t_stat")) else None,
                        df=float(row.get("df")) if pd.notna(row.get("df")) else None,
                        p_value=float(row.get("p_value")) if pd.notna(row.get("p_value")) else None,
                        adj_p_value=float(row.get("adj_p_value")) if pd.notna(row.get("adj_p_value")) else None,
                        ci_lower=float(row.get("ci_lower")) if pd.notna(row.get("ci_lower")) else None,
                        ci_upper=float(row.get("ci_upper")) if pd.notna(row.get("ci_upper")) else None,
                        hedges_g=float(row.get("hedges_g")) if pd.notna(row.get("hedges_g")) else None,
                        is_significant=bool(row.get("is_significant", False)),
                    )
                )
        except Exception:
            pass

    artifacts_list = parse_artifacts_json(experiment.artifacts, experiment.id)

    return ExperimentResultsDetailResponse(
        experiment_id=experiment.id,
        status=experiment.status,
        dataset_id=experiment.dataset_id,
        dataset_hash=experiment.dataset_hash,
        reproducibility_manifest=parse_json_safely(experiment.reproducibility_manifest),
        statistical_summary=parse_json_safely(experiment.statistical_summary),
        artifacts=artifacts_list,
        features=features_list,
        total_features=total_features,
        page=page,
        limit=limit,
    )


@router.get(
    "/experiments",
    response_model=List[ExperimentResponse],
    summary="List accessible experiment executions",
)
def list_experiments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role == UserRole.ADMIN.value:
        experiments = db.query(Experiment).order_by(Experiment.created_at.desc()).all()
    else:
        experiments = (
            db.query(Experiment)
            .filter(Experiment.owner_id == current_user.id)
            .order_by(Experiment.created_at.desc())
            .all()
        )

    return [to_experiment_response(exp) for exp in experiments]


@router.get(
    "/projects/{project_id}/experiments",
    response_model=List[ExperimentResponse],
    summary="List experiments for a specific project",
)
def list_project_experiments(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested research project was not found.",
        )

    # Enforce ownership or ADMIN access on the parent project
    if current_user.role != UserRole.ADMIN.value and project.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view experiments in this project.",
        )

    experiments = (
        db.query(Experiment)
        .filter(Experiment.project_id == project_id)
        .order_by(Experiment.created_at.desc())
        .all()
    )
    return [to_experiment_response(exp) for exp in experiments]


@router.get(
    "/experiments/compare",
    response_model=ExperimentComparisonResponse,
    summary="Compare two completed experiments side-by-side",
)
def compare_experiments(
    exp1_id: str = Query(..., description="First experiment UUID"),
    exp2_id: str = Query(..., description="Second experiment UUID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Compare two completed statistical experiment executions side-by-side.
    Computes shared biomarkers, discordance, effect size comparisons,
    and concordance rates.
    """
    if exp1_id == exp2_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot compare an experiment to itself. Please select two distinct experiments.",
        )

    exp1 = db.query(Experiment).filter(Experiment.id == exp1_id).first()
    exp2 = db.query(Experiment).filter(Experiment.id == exp2_id).first()

    if not exp1 or not exp2:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or both experiments could not be found.",
        )

    if current_user.role != UserRole.ADMIN.value:
        if exp1.owner_id != current_user.id or exp2.owner_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: you do not have permission to view both experiments.",
            )

    def load_features_dict(experiment_id: str) -> Dict[str, Dict[str, Any]]:
        artifact_dir = get_artifact_dir(experiment_id)
        csv_file = artifact_dir / "differential_expression_results.csv"
        features: Dict[str, Dict[str, Any]] = {}
        if csv_file.exists():
            try:
                import pandas as pd
                df = pd.read_csv(csv_file)
                for _, row in df.iterrows():
                    fid = str(row.get("feature_id") or row.get("gene_id") or row.get("gene") or "")
                    if fid:
                        raw_fc = row.get("log2_fc") if "log2_fc" in row else row.get("log2_fold_change")
                        raw_pval = row.get("p_value") if "p_value" in row else row.get("pval")
                        raw_adj = row.get("adj_p_value") if "adj_p_value" in row else row.get("adjusted_p_value")
                        raw_sig = row.get("is_significant", False)
                        if isinstance(raw_sig, str):
                            raw_sig = raw_sig.lower() in ("true", "1", "yes")

                        features[fid] = {
                            "feature_id": fid,
                            "log2_fc": float(raw_fc) if pd.notna(raw_fc) else None,
                            "p_value": float(raw_pval) if pd.notna(raw_pval) else None,
                            "adj_p_value": float(raw_adj) if pd.notna(raw_adj) else None,
                            "is_significant": bool(raw_sig),
                        }
            except Exception:
                pass
        return features

    f1_map = load_features_dict(exp1.id)
    f2_map = load_features_dict(exp2.id)

    sig1_keys = {k for k, v in f1_map.items() if v.get("is_significant")}
    sig2_keys = {k for k, v in f2_map.items() if v.get("is_significant")}

    shared_keys = sig1_keys.intersection(sig2_keys)
    exp1_unique_keys = sig1_keys - sig2_keys
    exp2_unique_keys = sig2_keys - sig1_keys

    shared_items: List[ComparisonFeatureItem] = []
    concordant_count = 0
    for k in sorted(shared_keys):
        v1 = f1_map[k]
        v2 = f2_map[k]
        fc1 = v1.get("log2_fc")
        fc2 = v2.get("log2_fc")
        concordant = None
        if fc1 is not None and fc2 is not None:
            concordant = (fc1 > 0 and fc2 > 0) or (fc1 < 0 and fc2 < 0) or (fc1 == 0 and fc2 == 0)
            if concordant:
                concordant_count += 1
        shared_items.append(
            ComparisonFeatureItem(
                feature_id=k,
                log2_fc_1=fc1,
                log2_fc_2=fc2,
                adj_p_value_1=v1.get("adj_p_value"),
                adj_p_value_2=v2.get("adj_p_value"),
                concordant=concordant,
            )
        )

    concordance_rate = (concordant_count / len(shared_keys)) if shared_keys else None

    return ExperimentComparisonResponse(
        exp1=to_experiment_response(exp1),
        exp2=to_experiment_response(exp2),
        shared_dataset=(exp1.dataset_id == exp2.dataset_id and exp1.dataset_id is not None),
        dataset_hash_match=(exp1.dataset_hash == exp2.dataset_hash and exp1.dataset_hash is not None),
        exp1_significant_count=len(sig1_keys),
        exp2_significant_count=len(sig2_keys),
        shared_significant_count=len(shared_keys),
        concordance_rate=round(concordance_rate * 100, 1) if concordance_rate is not None else None,
        shared_features=shared_items,
        exp1_unique_features=[f1_map[k] for k in sorted(exp1_unique_keys)],
        exp2_unique_features=[f2_map[k] for k in sorted(exp2_unique_keys)],
    )


@router.get(
    "/experiments/{experiment_id}",
    response_model=ExperimentResponse,
    summary="Get details of a specific experiment execution",
)
def get_experiment(
    experiment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    experiment = db.query(Experiment).filter(Experiment.id == experiment_id).first()
    if not experiment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested experiment execution was not found.",
        )

    if current_user.role != UserRole.ADMIN.value and experiment.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view this experiment.",
        )

    return to_experiment_response(experiment)


@router.get(
    "/experiments/{experiment_id}/artifacts/{filename}",
    summary="Download or view a generated scientific artifact file",
)
def download_artifact(
    experiment_id: str,
    filename: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    experiment = db.query(Experiment).filter(Experiment.id == experiment_id).first()
    if not experiment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Experiment not found.",
        )

    if current_user.role != UserRole.ADMIN.value and experiment.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access artifacts from this experiment.",
        )

    artifact_dir = get_artifact_dir(experiment_id)
    try:
        file_path = resolve_safe_path(artifact_dir, filename)
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: invalid file path.",
        )

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested artifact file was not found.",
        )

    return FileResponse(
        path=str(file_path),
        filename=filename,
    )



@router.delete(
    "/experiments/{experiment_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete an experiment record",
)
def delete_experiment(
    experiment_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_csrf(request)

    experiment = db.query(Experiment).filter(Experiment.id == experiment_id).first()
    if not experiment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Experiment not found.",
        )

    if current_user.role != UserRole.ADMIN.value and experiment.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the experiment creator or an administrator can delete this experiment.",
        )

    # Clean up artifact directory on disk
    try:
        artifact_dir = get_artifact_dir(experiment_id)
        if artifact_dir.exists():
            import shutil
            shutil.rmtree(artifact_dir, ignore_errors=True)
    except Exception:
        pass

    db.delete(experiment)
    db.commit()
    return {"message": "Experiment record has been safely removed."}

