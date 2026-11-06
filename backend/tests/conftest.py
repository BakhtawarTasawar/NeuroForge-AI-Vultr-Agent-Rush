import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Set test environment
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET_KEY"] = "test-cryptographically-secure-key-for-unit-testing-32-chars"

from app.core.config import settings
from app.db.database import Base, get_db
from app.main import app

# Isolated In-Memory SQLite engine for backend automated tests
# This eliminates hardcoded credentials and strictly protects the production/dev PostgreSQL database from test data truncation
TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Ensure tables exist once per test session."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session():
    """Clean isolated database session for each test."""
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def test_dataset_fixture(db_session):
    import json
    from app.core.security import get_password_hash, create_access_token
    from app.db.models import User, UserRole, Project, Dataset
    from app.services.storage import get_upload_dir, resolve_safe_path

    user = User(
        email="lead_investigator@neuroforge.org",
        hashed_password=get_password_hash("ValidPass123"),
        full_name="Lead Investigator",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    project = Project(
        title="Autonomous Oncogenomics",
        description="Testing autonomous research agent workflows",
        domain="Cancer Gene-Expression",
        status="Active",
        owner_id=user.id,
    )
    db_session.add(project)
    db_session.commit()

    csv_content = (
        "Gene,S1,S2,S3,S4,S5,S6\n"
        "TP53,10.2,10.5,10.1,6.2,6.4,6.1\n"
        "BRCA1,8.1,8.3,8.0,4.2,4.1,4.5\n"
        "EGFR,5.0,5.2,5.1,9.0,9.2,8.9\n"
        "MYC,7.2,7.0,7.1,7.2,7.3,7.1\n"
        "PTEN,9.1,9.3,9.0,5.1,5.2,5.0\n"
        "CDKN2A,4.5,4.7,4.6,8.2,8.4,8.1\n"
        "VEGFA,6.1,6.3,6.2,6.0,6.2,6.1\n"
        "RB1,7.8,7.9,7.7,4.0,4.2,4.1\n"
        "MDM2,5.5,5.4,5.6,5.5,5.6,5.4\n"
        "KRAS,8.8,8.9,8.7,8.6,8.8,8.7\n"
    )
    filename = "test_transcriptomics_matrix.csv"
    upload_dir = get_upload_dir()
    file_path = resolve_safe_path(upload_dir, filename)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(csv_content)

    group_mappings = {
        "S1": "Control",
        "S2": "Control",
        "S3": "Control",
        "S4": "Treatment",
        "S5": "Treatment",
        "S6": "Treatment",
    }

    dataset = Dataset(
        project_id=project.id,
        owner_id=user.id,
        filename=filename,
        original_name="test_transcriptomics_matrix.csv",
        file_size_bytes=len(csv_content.encode("utf-8")),
        file_format="CSV",
        status="Validated",
        sample_count=6,
        feature_count=10,
        content_hash="abc123mockhash",
        matrix_orientation="features_as_rows",
        control_group="Control",
        treatment_group="Treatment",
        group_mappings=json.dumps(group_mappings),
    )
    db_session.add(dataset)
    db_session.commit()

    return {
        "user": user,
        "project": project,
        "dataset": dataset,
        "group_mappings": group_mappings,
        "token": create_access_token(user.id, user.role),
    }

