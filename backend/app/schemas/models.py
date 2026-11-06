from datetime import datetime
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import re

from app.db.models import UserRole


class UserRegisterRequest(BaseModel):
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., min_length=2, max_length=255)

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        v = v.strip().lower()
        pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
        if not re.match(pattern, v):
            raise ValueError("Please provide a valid research email address.")
        return v

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must contain at least 8 characters.")
        if not re.search(r"[A-Za-z]", v):
            raise ValueError("Password must contain at least one letter.")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one number.")
        return v

    @field_validator("full_name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Full name must be at least 2 characters.")
        return v


class UserLoginRequest(BaseModel):
    email: str = Field(..., max_length=255)
    password: str = Field(..., max_length=128)

    @field_validator("email")
    @classmethod
    def clean_email(cls, v: str) -> str:
        return v.strip().lower()


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must contain at least 8 characters.")
        if not re.search(r"[A-Za-z]", v):
            raise ValueError("Password must contain at least one letter.")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one number.")
        return v


class ProfileUpdateRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=255)

    @field_validator("full_name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Full name must be at least 2 characters.")
        return v


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserUpdateRoleRequest(BaseModel):
    role: UserRole


class UserUpdateStatusRequest(BaseModel):
    is_active: bool


class ProjectCreateRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    domain: str = Field("Cancer Gene-Expression", max_length=128)


class ProjectUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=2, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    domain: Optional[str] = Field(None, max_length=128)
    status: Optional[str] = Field(None, max_length=32)


class ProjectResponse(BaseModel):
    id: str
    title: str
    description: Optional[str]
    domain: str
    status: str
    owner_id: str
    owner_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DatasetResponse(BaseModel):
    id: str
    project_id: Optional[str] = None
    owner_id: str
    filename: str
    original_name: str
    file_size_bytes: int
    file_format: str
    status: str
    sample_count: Optional[int] = None
    feature_count: Optional[int] = None
    content_hash: Optional[str] = None
    matrix_orientation: Optional[str] = "features_as_rows"
    feature_id_column: Optional[str] = None
    sample_id_column: Optional[str] = None
    title: Optional[str] = None
    domain: Optional[str] = "Cancer Gene-Expression"
    organism: Optional[str] = None
    tissue: Optional[str] = None
    experimental_condition: Optional[str] = None
    control_group: Optional[str] = None
    treatment_group: Optional[str] = None
    measurement_type: Optional[str] = None
    data_source: Optional[str] = None
    publication_reference: Optional[str] = None
    is_synthetic: bool = False
    cohort_classification: str = "Unverified / Unknown Cohort"
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def compute_synthetic_flag(self) -> "DatasetResponse":
        import re
        text_corpus = f"{self.original_name or ''} {self.title or ''} {self.data_source or ''} {self.measurement_type or ''}".lower()

        # Strict token boundaries avoiding false-positives like 'testis'
        synthetic_pattern = re.compile(r"\b(synthetic|simulated|in[\s_-]?silico|benchmark|mock|dummy)\b")
        empirical_pattern = re.compile(r"\b(tcga|icgc|gtex|geo|gse\d+|cbioportal|clinical|patient|biopsy|tumor|solid[\s_-]?tissue)\b")

        has_synthetic = bool(synthetic_pattern.search(text_corpus))
        has_empirical = bool(empirical_pattern.search(text_corpus))

        if has_synthetic and not has_empirical:
            self.is_synthetic = True
            self.cohort_classification = "Synthetic Benchmark Cohort"
        elif has_empirical and not has_synthetic:
            self.is_synthetic = False
            self.cohort_classification = "Empirical Observational Cohort"
        elif has_synthetic and has_empirical:
            self.is_synthetic = True
            self.cohort_classification = "Synthetic Benchmark (Modeled on Empirical Cohort)"
        else:
            self.is_synthetic = False
            self.cohort_classification = "Unverified / Unknown Cohort"

        return self


class DatasetInspectionResponse(BaseModel):
    id: str
    filename: str
    original_name: str
    file_format: str
    file_size_bytes: int
    content_hash: Optional[str]
    matrix_orientation: str
    orientation_confidence: Optional[float] = None
    orientation_reasoning: Optional[str] = None
    feature_count: int
    sample_count: int
    feature_id_column: Optional[str] = None
    sample_id_column: Optional[str] = None
    sample_identifiers: List[str] = []
    feature_identifiers_sample: List[str] = []
    metadata_columns: List[str] = []
    warnings: List[str] = []


class DatasetPreviewResponse(BaseModel):
    total_rows: int
    total_cols: int
    row_page: int
    row_page_size: int
    col_page: int
    col_page_size: int
    columns: List[str]
    rows: List[Dict[str, Any]]


class DatasetOrientationUpdateRequest(BaseModel):
    orientation: str = Field(..., pattern="^(features_as_rows|samples_as_rows)$")
    feature_id_column: Optional[str] = None
    sample_id_column: Optional[str] = None


class DatasetMetadataUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    domain: Optional[str] = Field(None, max_length=128)
    organism: Optional[str] = Field(None, max_length=128)
    tissue: Optional[str] = Field(None, max_length=128)
    experimental_condition: Optional[str] = Field(None, max_length=255)
    control_group: Optional[str] = Field(None, max_length=128)
    treatment_group: Optional[str] = Field(None, max_length=128)
    measurement_type: Optional[str] = Field(None, max_length=128)
    data_source: Optional[str] = Field(None, max_length=255)
    publication_reference: Optional[str] = Field(None, max_length=255)


class DatasetGroupMappingRequest(BaseModel):
    group_mappings: Dict[str, str]
    control_group: Optional[str] = None
    treatment_group: Optional[str] = None


class ArtifactInfo(BaseModel):
    filename: str
    size_bytes: int
    content_type: str
    download_url: str


class ExperimentCreateRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    dataset_id: Optional[str] = None
    code: Optional[str] = Field(None, max_length=50000)
    experiment_type: Optional[str] = Field("differential_expression_welch", max_length=64)
    group_a_name: Optional[str] = Field(None, max_length=128)
    group_b_name: Optional[str] = Field(None, max_length=128)
    group_mappings: Optional[Dict[str, str]] = None
    fdr_threshold: Optional[float] = Field(0.05, ge=0.0001, le=1.0)
    alpha: Optional[float] = Field(0.05, ge=0.0001, le=0.5)


class ExperimentResponse(BaseModel):
    id: str
    project_id: str
    dataset_id: Optional[str]
    owner_id: str
    owner_name: Optional[str] = None
    title: str
    description: Optional[str]
    experiment_type: Optional[str] = "differential_expression_welch"
    dataset_hash: Optional[str] = None
    status: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    duration_seconds: Optional[float]
    exit_code: Optional[int]
    stdout: Optional[str]
    stderr: Optional[str]
    result_summary: Optional[str]
    artifacts: Optional[List[ArtifactInfo]] = None
    statistical_summary: Optional[Dict[str, Any]] = None
    reproducibility_manifest: Optional[Dict[str, Any]] = None
    failure_reason: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FeatureResultResponse(BaseModel):
    feature_id: str
    n_a: int
    n_b: int
    mean_a: float
    mean_b: float
    mean_diff: float
    log2_fc: Optional[float] = None
    t_stat: Optional[float] = None
    df: Optional[float] = None
    p_value: Optional[float] = None
    adj_p_value: Optional[float] = None
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None
    hedges_g: Optional[float] = None
    is_significant: bool = False


class ExperimentResultsDetailResponse(BaseModel):
    experiment_id: str
    status: str
    dataset_id: Optional[str] = None
    dataset_hash: Optional[str] = None
    reproducibility_manifest: Optional[Dict[str, Any]] = None
    statistical_summary: Optional[Dict[str, Any]] = None
    artifacts: List[ArtifactInfo] = []
    features: List[FeatureResultResponse] = []
    total_features: int = 0
    page: int = 1
    limit: int = 50


class OverviewStatsResponse(BaseModel):
    projects_count: int
    datasets_count: int
    experiments_count: int
    reports_count: int
    active_role: str


# =============================================================================
# Milestone 4: Autonomous Scientific Research Session Schemas
# =============================================================================

class ResearchSessionCreateRequest(BaseModel):
    dataset_id: str
    title: str = Field(..., min_length=2, max_length=255)
    objective: str = Field(..., min_length=5, max_length=5000)
    group_a_name: Optional[str] = Field(None, max_length=128)
    group_b_name: Optional[str] = Field(None, max_length=128)
    group_mappings: Optional[Dict[str, str]] = None


class ApprovalDecisionRequest(BaseModel):
    decision: str = Field(..., pattern="^(approve|reject)$")
    notes: Optional[str] = Field(None, max_length=2000)
    plan_hash: Optional[str] = Field(None, max_length=64)


class ResearchEventResponse(BaseModel):
    id: str
    session_id: str
    event_type: str
    step_name: str
    message: str
    payload: Optional[Dict[str, Any]] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ResearchSessionResponse(BaseModel):
    id: str
    project_id: str
    dataset_id: str
    owner_id: str
    owner_name: Optional[str] = None
    title: str
    objective: str
    dataset_hash: Optional[str] = None
    status: str
    current_step: str
    approval_state: str
    approval_notes: Optional[str] = None
    approved_at: Optional[datetime] = None
    research_plan: Optional[Dict[str, Any]] = None
    experiment_ids: List[str] = []
    tool_history: List[Dict[str, Any]] = []
    evidence_store: List[Dict[str, Any]] = []
    final_summary: Optional[Dict[str, Any]] = None
    failure_reason: Optional[str] = None
    iteration_count: int = 0
    max_iterations: int = 10
    retry_count: int = 0
    max_retries: int = 3
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ResearchPlanResponse(BaseModel):
    session_id: str
    approval_state: str
    plan: Optional[Dict[str, Any]] = None


class ResearchEvidenceResponse(BaseModel):
    session_id: str
    evidence_items: List[Dict[str, Any]] = []


class ResearchSummaryResponse(BaseModel):
    session_id: str
    status: str
    final_summary: Optional[Dict[str, Any]] = None


class ComparisonFeatureItem(BaseModel):
    feature_id: str
    log2_fc_1: Optional[float] = None
    log2_fc_2: Optional[float] = None
    adj_p_value_1: Optional[float] = None
    adj_p_value_2: Optional[float] = None
    concordant: Optional[bool] = None


class ExperimentComparisonResponse(BaseModel):
    exp1: ExperimentResponse
    exp2: ExperimentResponse
    shared_dataset: bool
    dataset_hash_match: bool
    exp1_significant_count: int
    exp2_significant_count: int
    shared_significant_count: int
    concordance_rate: Optional[float] = None
    shared_features: List[ComparisonFeatureItem] = []
    exp1_unique_features: List[Dict[str, Any]] = []
    exp2_unique_features: List[Dict[str, Any]] = []


