import uuid
from datetime import datetime, timezone
from enum import Enum
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer, Float, Text
from sqlalchemy.orm import relationship

from app.db.database import Base


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    RESEARCHER = "RESEARCHER"
    VIEWER = "VIEWER"


class ExperimentStatus(str, Enum):
    QUEUED = "Queued"
    RUNNING = "Running"
    COMPLETED = "Completed"
    FAILED = "Failed"
    TIMED_OUT = "Timed out"


class SessionStatus(str, Enum):
    INITIALIZING = "Initializing"
    PLANNING = "Planning"
    AWAITING_APPROVAL = "Awaiting Approval"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    EXECUTING = "Executing"
    EVALUATING = "Evaluating"
    COMPLETED = "Completed"
    FAILED = "Failed"
    STOPPED = "Stopped"


class ApprovalState(str, Enum):
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(String(32), nullable=False, default=UserRole.RESEARCHER.value)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    refresh_sessions = relationship("RefreshSession", back_populates="user", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="owner", cascade="all, delete-orphan")
    datasets = relationship("Dataset", back_populates="owner", cascade="all, delete-orphan")
    experiments = relationship("Experiment", back_populates="owner", cascade="all, delete-orphan")
    research_sessions = relationship("ResearchSession", back_populates="owner", cascade="all, delete-orphan", foreign_keys="ResearchSession.owner_id")
    knowledge_documents = relationship("KnowledgeDocument", back_populates="owner", cascade="all, delete-orphan")


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), index=True, nullable=False)
    user_agent = Column(String(512), nullable=True)
    ip_address = Column(String(64), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_revoked = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_used_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    user = relationship("User", back_populates="refresh_sessions")


class Project(Base):
    __tablename__ = "projects"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    domain = Column(String(128), nullable=False, default="Cancer Gene-Expression")
    status = Column(String(32), nullable=False, default="Active")
    owner_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    owner = relationship("User", back_populates="projects")
    datasets = relationship("Dataset", back_populates="project", cascade="all, delete-orphan")
    experiments = relationship("Experiment", back_populates="project", cascade="all, delete-orphan")
    research_sessions = relationship("ResearchSession", back_populates="project", cascade="all, delete-orphan")
    knowledge_documents = relationship("KnowledgeDocument", back_populates="project", cascade="all, delete-orphan")


class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    owner_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    original_name = Column(String(255), nullable=False)
    file_size_bytes = Column(Integer, nullable=False)
    file_format = Column(String(32), nullable=False, default="CSV")
    status = Column(String(32), nullable=False, default="Validated")
    sample_count = Column(Integer, nullable=True)
    feature_count = Column(Integer, nullable=True)

    # Scientific metadata and orientation
    content_hash = Column(String(64), nullable=True)
    matrix_orientation = Column(String(32), nullable=False, default="features_as_rows")
    feature_id_column = Column(String(128), nullable=True)
    sample_id_column = Column(String(128), nullable=True)
    quality_assessment = Column(Text, nullable=True)
    group_mappings = Column(Text, nullable=True)

    # Provenance metadata
    title = Column(String(255), nullable=True)
    domain = Column(String(128), nullable=False, default="Cancer Gene-Expression")
    organism = Column(String(128), nullable=True)
    tissue = Column(String(128), nullable=True)
    experimental_condition = Column(String(255), nullable=True)
    control_group = Column(String(128), nullable=True)
    treatment_group = Column(String(128), nullable=True)
    measurement_type = Column(String(128), nullable=True)
    data_source = Column(String(255), nullable=True)
    publication_reference = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    owner = relationship("User", back_populates="datasets")
    project = relationship("Project", back_populates="datasets")
    experiments = relationship("Experiment", back_populates="dataset")
    research_sessions = relationship("ResearchSession", back_populates="dataset")


class Experiment(Base):
    __tablename__ = "experiments"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_id = Column(String(36), ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True, index=True)
    owner_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    code = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default=ExperimentStatus.QUEUED.value)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Float, nullable=True)
    exit_code = Column(Integer, nullable=True)
    stdout = Column(Text, nullable=True)
    stderr = Column(Text, nullable=True)
    result_summary = Column(Text, nullable=True)
    artifacts = Column(Text, nullable=True)
    failure_reason = Column(String(255), nullable=True)

    # Scientific reproducibility metadata
    experiment_type = Column(String(64), nullable=False, default="differential_expression_welch")
    dataset_hash = Column(String(64), nullable=True)
    reproducibility_manifest = Column(Text, nullable=True)
    statistical_summary = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    project = relationship("Project", back_populates="experiments")
    dataset = relationship("Dataset", back_populates="experiments")
    owner = relationship("User", back_populates="experiments")


class ResearchSession(Base):
    __tablename__ = "research_sessions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_id = Column(String(36), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    objective = Column(Text, nullable=False)
    dataset_hash = Column(String(64), nullable=True)
    status = Column(String(32), nullable=False, default=SessionStatus.INITIALIZING.value)
    current_step = Column(String(64), nullable=False, default="initialize_research")

    # Human-in-the-loop safety gate
    approval_state = Column(String(32), nullable=False, default=ApprovalState.PENDING.value)
    approval_notes = Column(Text, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    approved_by_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Structured research artifacts
    research_plan = Column(Text, nullable=True)
    experiment_ids = Column(Text, nullable=True)  # JSON array of experiment UUIDs
    tool_history = Column(Text, nullable=True)    # JSON array of executed tool calls
    evidence_store = Column(Text, nullable=True)  # JSON store of observed facts & results
    final_summary = Column(Text, nullable=True)   # JSON structured final research report
    failure_reason = Column(String(255), nullable=True)

    # Resource and retry boundaries
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    iteration_count = Column(Integer, nullable=False, default=0)
    max_iterations = Column(Integer, nullable=False, default=10)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    project = relationship("Project", back_populates="research_sessions")
    dataset = relationship("Dataset", back_populates="research_sessions")
    owner = relationship("User", back_populates="research_sessions", foreign_keys=[owner_id])
    events = relationship("ResearchEvent", back_populates="session", cascade="all, delete-orphan", order_by="ResearchEvent.created_at.asc()")


class ResearchEvent(Base):
    __tablename__ = "research_events"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    session_id = Column(String(36), ForeignKey("research_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(64), nullable=False)
    step_name = Column(String(64), nullable=False)
    message = Column(Text, nullable=False)
    payload = Column(Text, nullable=True)  # JSON metadata
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    session = relationship("ResearchSession", back_populates="events")


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    filename = Column(String(255), nullable=False)
    file_format = Column(String(32), nullable=False, default="TXT")
    file_size_bytes = Column(Integer, nullable=False, default=0)
    content_hash = Column(String(64), nullable=True)
    chunk_count = Column(Integer, nullable=False, default=0)
    source_type = Column(String(64), nullable=False, default="upload")  # "upload", "abstract", "pathway", "annotation"
    doi = Column(String(128), nullable=True)
    authors = Column(Text, nullable=True)  # Comma-separated or JSON list of authors
    publication_year = Column(Integer, nullable=True)
    journal = Column(String(255), nullable=True)
    source_url = Column(String(512), nullable=True)
    tags = Column(Text, nullable=True)  # Comma-separated or JSON list of tags
    custom_metadata = Column(Text, nullable=True)  # JSON-serialized dictionary of arbitrary key-value metadata
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    owner = relationship("User", back_populates="knowledge_documents")
    project = relationship("Project", back_populates="knowledge_documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan", order_by="DocumentChunk.chunk_index.asc()")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    document_id = Column(String(36), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=False, default=0)
    embedding_json = Column(Text, nullable=True)  # JSON-serialized vector embedding for database-agnostic portability
    metadata_json = Column(Text, nullable=True)   # JSON-serialized chunk metadata (section, page, source)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    document = relationship("KnowledgeDocument", back_populates="chunks")
