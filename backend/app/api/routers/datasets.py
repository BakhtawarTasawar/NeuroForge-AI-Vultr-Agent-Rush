import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_roles, verify_csrf
from app.db.models import Dataset, Project, User, UserRole
from app.schemas.models import (
    DatasetAttachRequest,
    DatasetGroupMappingRequest,
    DatasetInspectionResponse,
    DatasetMetadataUpdateRequest,
    DatasetOrientationUpdateRequest,
    DatasetPreviewResponse,
    DatasetResponse,
)
from app.services.dataset_parser import (
    DatasetParseError,
    MAX_FILE_SIZE_BYTES,
    parse_scientific_dataset,
)
from app.services.dataset_quality import (
    compute_dataset_quality,
    validate_group_mappings,
)
from app.services.storage import (
    get_dataset_file_path,
    get_temp_upload_dir,
    get_upload_dir,
    resolve_safe_path,
    save_upload_file,
    save_upload_from_file,
)

router = APIRouter(prefix="/datasets", tags=["Dataset Library"])

ALLOWED_EXTENSIONS = {".csv", ".tsv", ".txt", ".gct"}


def get_user_dataset_or_403(dataset_id: str, current_user: User, db: Session) -> Dataset:
    """Fetch dataset and enforce owner or admin access control."""
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested scientific dataset was not found.",
        )
    if current_user.role != UserRole.ADMIN.value and dataset.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this dataset.",
        )
    return dataset


def get_user_dataset_file_path(dataset: Dataset) -> Path:
    """Safely resolve dataset path in secure storage without loading file into memory."""
    try:
        file_path = get_dataset_file_path(dataset.filename)
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The physical data file could not be located in secure storage.",
        )
    return file_path


def load_dataset_file_content(dataset: Dataset) -> bytes:
    """Safely load dataset bytes from storage directory (backward compatibility)."""
    file_path = get_user_dataset_file_path(dataset)
    try:
        return file_path.read_bytes()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read dataset from storage: {str(e)}",
        )


@router.get(
    "",
    response_model=List[DatasetResponse],
    summary="List scientific datasets (Researchers see own; Admins see all)",
)
def list_datasets(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role == UserRole.ADMIN.value:
        datasets = db.query(Dataset).order_by(Dataset.created_at.desc()).all()
    else:
        datasets = (
            db.query(Dataset)
            .filter(Dataset.owner_id == current_user.id)
            .order_by(Dataset.created_at.desc())
            .all()
        )
    return datasets


@router.get(
    "/{dataset_id}",
    response_model=DatasetResponse,
    summary="Get dataset details",
)
def get_dataset(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_user_dataset_or_403(dataset_id, current_user, db)


@router.post(
    "/upload",
    response_model=DatasetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and ingest a scientific dataset file",
)
async def upload_dataset(
    file: UploadFile = File(...),
    project_id: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
    organism: Optional[str] = Form(None),
    tissue: Optional[str] = Form(None),
    experimental_condition: Optional[str] = Form(None),
    measurement_type: Optional[str] = Form(None),
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.RESEARCHER])),
    db: Session = Depends(get_db),
):
    original_filename = os.path.basename(file.filename or "dataset.csv")
    _, ext = os.path.splitext(original_filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported scientific file format '{ext}'. Accepted formats: {', '.join(sorted(ALLOWED_EXTENSIONS))}.",
        )

    # 1. Validate project_id existence and ownership BEFORE reading or parsing the uploaded file
    if project_id:
        proj = db.query(Project).filter(Project.id == project_id).first()
        if not proj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="The requested scientific research project was not found.",
            )
        if current_user.role != UserRole.ADMIN.value and proj.owner_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to upload datasets into this project.",
            )

    # 2. Stream upload directly to a temporary file while calculating incremental SHA-256
    CHUNK_SIZE = 1024 * 1024  # 1 MiB chunk
    temp_dir = get_temp_upload_dir()
    temp_path = resolve_safe_path(temp_dir, f"upload_{uuid.uuid4().hex}.tmp")

    hasher = hashlib.sha256()
    total_bytes = 0

    try:
        try:
            with open(temp_path, "wb") as f_out:
                while True:
                    chunk = await file.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if total_bytes > MAX_FILE_SIZE_BYTES:
                        raise HTTPException(
                            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                            detail=f"File exceeds maximum allowed size of {MAX_FILE_SIZE_BYTES // (1024*1024)} MB.",
                        )
                    hasher.update(chunk)
                    f_out.write(chunk)
        finally:
            await file.close()

        if total_bytes == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The uploaded file is empty (0 bytes).",
            )

        content_hash = hasher.hexdigest()

        # 3. Scientific parsing and orientation assessment directly from stream/disk
        try:
            parsed = parse_scientific_dataset(temp_path, original_filename, content_hash=content_hash)
        except DatasetParseError as pe:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Scientific dataset parsing error: {str(pe)}",
            )

        # 4. Initial deterministic quality assessment
        try:
            quality_res = compute_dataset_quality(parsed.numeric_matrix)
            quality_json = json.dumps(quality_res.to_dict())
        except Exception:
            quality_json = None

        # 5. Persist file atomically to secure storage directory
        stored_filename, target_path = save_upload_from_file(temp_path, original_filename)

        initial_status = "Needs Orientation Confirmation" if parsed.orientation.detected_orientation == "ambiguous" else "Validated"

        dataset = Dataset(
            project_id=project_id,
            owner_id=current_user.id,
            filename=stored_filename,
            original_name=original_filename,
            file_size_bytes=total_bytes,
            file_format=parsed.file_format,
            status=initial_status,
            sample_count=parsed.num_samples,
            feature_count=parsed.num_features,
            content_hash=parsed.content_hash,
            matrix_orientation=parsed.orientation.detected_orientation,
            feature_id_column=parsed.orientation.feature_id_col,
            sample_id_column=parsed.orientation.sample_id_col,
            quality_assessment=quality_json,
            group_mappings=None,
            title=title or original_filename,
            domain="Cancer Gene-Expression",
            organism=organism or "Homo sapiens",
            tissue=tissue,
            experimental_condition=experimental_condition,
            measurement_type=measurement_type or ("RNA-Seq Expression" if "GCT" in parsed.file_format else "Gene Expression Matrix"),
        )
        try:
            db.add(dataset)
            db.commit()
            db.refresh(dataset)
            return dataset
        except Exception:
            db.rollback()
            if target_path and target_path.exists():
                try:
                    target_path.unlink()
                except Exception:
                    pass
            raise

    finally:
        # Guarantee cleanup of temporary file if it still exists
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass


@router.get(
    "/{dataset_id}/inspection",
    response_model=DatasetInspectionResponse,
    summary="Get deep scientific inspection and orientation evidence",
)
def inspect_dataset(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dataset = get_user_dataset_or_403(dataset_id, current_user, db)
    file_path = get_user_dataset_file_path(dataset)

    try:
        parsed = parse_scientific_dataset(file_path, dataset.original_name, content_hash=dataset.content_hash)
    except DatasetParseError as pe:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Inspection failed to parse dataset: {str(pe)}",
        )

    return DatasetInspectionResponse(
        id=dataset.id,
        filename=dataset.filename,
        original_name=dataset.original_name,
        file_format=parsed.file_format,
        file_size_bytes=dataset.file_size_bytes,
        content_hash=dataset.content_hash or parsed.content_hash,
        matrix_orientation=dataset.matrix_orientation,
        orientation_confidence=parsed.orientation.confidence,
        orientation_reasoning=parsed.orientation.reasoning,
        feature_count=parsed.num_features,
        sample_count=parsed.num_samples,
        feature_id_column=dataset.feature_id_column or parsed.orientation.feature_id_col,
        sample_id_column=dataset.sample_id_column or parsed.orientation.sample_id_col,
        sample_identifiers=parsed.sample_ids,
        feature_identifiers_sample=parsed.feature_ids[:50],
        metadata_columns=parsed.metadata_columns,
        warnings=parsed.warnings,
    )


@router.get(
    "/{dataset_id}/preview",
    response_model=DatasetPreviewResponse,
    summary="Get bounded, paginated preview of scientific matrix rows and columns",
)
def preview_dataset(
    dataset_id: str,
    row_page: int = Query(1, ge=1),
    row_limit: int = Query(50, ge=1, le=50),
    col_page: int = Query(1, ge=1),
    col_limit: int = Query(50, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dataset = get_user_dataset_or_403(dataset_id, current_user, db)
    file_path = get_user_dataset_file_path(dataset)

    try:
        parsed = parse_scientific_dataset(file_path, dataset.original_name, content_hash=dataset.content_hash)
    except DatasetParseError as pe:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Preview failed: {str(pe)}",
        )

    # Use numeric matrix in confirmed orientation
    matrix_df = parsed.numeric_matrix
    if dataset.matrix_orientation == "samples_as_rows" and parsed.orientation.detected_orientation != "samples_as_rows":
        matrix_df = matrix_df.T
    elif dataset.matrix_orientation == "features_as_rows" and parsed.orientation.detected_orientation == "samples_as_rows":
        matrix_df = matrix_df.T

    total_rows = len(matrix_df)
    total_cols = len(matrix_df.columns)

    # Slice rows
    row_start = (row_page - 1) * row_limit
    row_end = min(row_start + row_limit, total_rows)
    sliced_df = matrix_df.iloc[row_start:row_end]

    # Slice cols
    col_start = (col_page - 1) * col_limit
    col_end = min(col_start + col_limit, total_cols)
    sliced_cols = list(matrix_df.columns[col_start:col_end])

    result_rows = []
    for idx_val, row in sliced_df[sliced_cols].iterrows():
        row_dict: Dict[str, Any] = {"_row_id": str(idx_val)}
        for c in sliced_cols:
            val = row[c]
            row_dict[str(c)] = None if (val is None or (isinstance(val, float) and (val != val or val == float("inf")))) else val
        result_rows.append(row_dict)

    return DatasetPreviewResponse(
        total_rows=total_rows,
        total_cols=total_cols,
        row_page=row_page,
        row_page_size=row_limit,
        col_page=col_page,
        col_page_size=col_limit,
        columns=["_row_id"] + [str(c) for c in sliced_cols],
        rows=result_rows,
    )


@router.get(
    "/{dataset_id}/quality",
    summary="Get deterministic scientific quality assessment and analysis readiness",
)
def get_dataset_quality(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dataset = get_user_dataset_or_403(dataset_id, current_user, db)
    file_path = get_user_dataset_file_path(dataset)

    try:
        parsed = parse_scientific_dataset(file_path, dataset.original_name, content_hash=dataset.content_hash)
    except DatasetParseError as pe:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Quality calculation failed: {str(pe)}",
        )

    matrix_df = parsed.numeric_matrix
    if dataset.matrix_orientation == "samples_as_rows" and parsed.orientation.detected_orientation != "samples_as_rows":
        matrix_df = matrix_df.T
    elif dataset.matrix_orientation == "features_as_rows" and parsed.orientation.detected_orientation == "samples_as_rows":
        matrix_df = matrix_df.T

    # Parse existing group mappings
    group_map = None
    if dataset.group_mappings:
        try:
            group_map = json.loads(dataset.group_mappings)
        except Exception:
            group_map = None

    quality_res = compute_dataset_quality(
        matrix_df=matrix_df,
        group_mappings=group_map,
        control_group=dataset.control_group,
        treatment_group=dataset.treatment_group,
    )

    # Cache back to database
    dataset.quality_assessment = json.dumps(quality_res.to_dict())
    db.commit()

    return quality_res.to_dict()


@router.patch(
    "/{dataset_id}/orientation",
    response_model=DatasetResponse,
    summary="Confirm or override matrix orientation (Researchers and Admins only)",
)
def update_orientation(
    dataset_id: str,
    req: DatasetOrientationUpdateRequest,
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.RESEARCHER])),
    db: Session = Depends(get_db),
):
    dataset = get_user_dataset_or_403(dataset_id, current_user, db)

    dataset.matrix_orientation = req.orientation
    if req.feature_id_column:
        dataset.feature_id_column = req.feature_id_column
    if req.sample_id_column:
        dataset.sample_id_column = req.sample_id_column

    # Recalculate dimensions if orientation changed
    file_path = get_user_dataset_file_path(dataset)
    try:
        parsed = parse_scientific_dataset(file_path, dataset.original_name, content_hash=dataset.content_hash)
        if req.orientation == "samples_as_rows":
            dataset.sample_count = parsed.total_raw_rows
            dataset.feature_count = parsed.total_raw_cols - 1
        else:
            dataset.sample_count = parsed.num_samples
            dataset.feature_count = parsed.num_features
    except Exception:
        pass

    dataset.status = "Validated"
    db.commit()
    db.refresh(dataset)
    return dataset


@router.patch(
    "/{dataset_id}/metadata",
    response_model=DatasetResponse,
    summary="Update scientific provenance metadata (Researchers and Admins only)",
)
def update_metadata(
    dataset_id: str,
    req: DatasetMetadataUpdateRequest,
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.RESEARCHER])),
    db: Session = Depends(get_db),
):
    dataset = get_user_dataset_or_403(dataset_id, current_user, db)

    if req.title is not None:
        dataset.title = req.title
    if req.domain is not None:
        dataset.domain = req.domain
    if req.organism is not None:
        dataset.organism = req.organism
    if req.tissue is not None:
        dataset.tissue = req.tissue
    if req.experimental_condition is not None:
        dataset.experimental_condition = req.experimental_condition
    if req.control_group is not None:
        dataset.control_group = req.control_group
    if req.treatment_group is not None:
        dataset.treatment_group = req.treatment_group
    if req.measurement_type is not None:
        dataset.measurement_type = req.measurement_type
    if req.data_source is not None:
        dataset.data_source = req.data_source
    if req.publication_reference is not None:
        dataset.publication_reference = req.publication_reference

    db.commit()
    db.refresh(dataset)
    return dataset


@router.post(
    "/{dataset_id}/groups",
    summary="Configure sample group mappings and validate experimental readiness",
)
def configure_groups(
    dataset_id: str,
    req: DatasetGroupMappingRequest,
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.RESEARCHER])),
    db: Session = Depends(get_db),
):
    dataset = get_user_dataset_or_403(dataset_id, current_user, db)
    file_path = get_user_dataset_file_path(dataset)

    try:
        parsed = parse_scientific_dataset(file_path, dataset.original_name, content_hash=dataset.content_hash)
    except DatasetParseError as pe:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse dataset for group validation: {str(pe)}",
        )

    # Validate that mapped samples actually exist in dataset
    valid_samples = set(parsed.sample_ids)
    clean_mappings = {k: v for k, v in req.group_mappings.items() if k in valid_samples}

    dataset.group_mappings = json.dumps(clean_mappings)
    if req.control_group:
        dataset.control_group = req.control_group
    if req.treatment_group:
        dataset.treatment_group = req.treatment_group

    db.commit()

    # Re-evaluate quality with groups
    matrix_df = parsed.numeric_matrix
    if dataset.matrix_orientation == "samples_as_rows" and parsed.orientation.detected_orientation != "samples_as_rows":
        matrix_df = matrix_df.T
    elif dataset.matrix_orientation == "features_as_rows" and parsed.orientation.detected_orientation == "samples_as_rows":
        matrix_df = matrix_df.T

    quality_res = compute_dataset_quality(
        matrix_df=matrix_df,
        group_mappings=clean_mappings,
        control_group=dataset.control_group,
        treatment_group=dataset.treatment_group,
    )
    dataset.quality_assessment = json.dumps(quality_res.to_dict())
    db.commit()

    return {
        "message": "Sample groups updated successfully.",
        "group_validation": quality_res.group_validation,
    }


@router.post(
    "/{dataset_id}/attach",
    response_model=DatasetResponse,
    status_code=status.HTTP_200_OK,
    summary="Attach a standalone dataset to a research project (Researchers and Admins only)",
)
def attach_dataset_to_project(
    dataset_id: str,
    req: DatasetAttachRequest,
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.RESEARCHER])),
    db: Session = Depends(get_db),
):
    dataset = get_user_dataset_or_403(dataset_id, current_user, db)

    project = db.query(Project).filter(Project.id == req.project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Research project not found.",
        )

    if current_user.role != UserRole.ADMIN.value and project.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to attach datasets to this project.",
        )

    if dataset.project_id == project.id:
        return dataset

    if dataset.project_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dataset is already attached to another project.",
        )

    dataset.project_id = project.id
    db.commit()
    db.refresh(dataset)
    return dataset


@router.delete(
    "/{dataset_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete uploaded dataset (Researchers delete own; Admins delete any)",
)
def delete_dataset(
    dataset_id: str,
    request: Request,
    current_user: User = Depends(require_roles([UserRole.ADMIN, UserRole.RESEARCHER])),
    db: Session = Depends(get_db),
):
    verify_csrf(request)

    dataset = get_user_dataset_or_403(dataset_id, current_user, db)

    # Safely remove file on disk if it exists
    try:
        upload_dir = get_upload_dir()
        file_path = resolve_safe_path(upload_dir, dataset.filename)
        if file_path.exists():
            file_path.unlink()
    except Exception:
        pass

    db.delete(dataset)
    db.commit()
    return {"message": "Dataset removed successfully."}
