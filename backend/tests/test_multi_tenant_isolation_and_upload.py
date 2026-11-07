import io
import json
from unittest.mock import patch, MagicMock
import pytest
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
from app.services.dataset_parser import (
    MAX_FILE_SIZE_BYTES,
    DatasetParseError,
    parse_scientific_dataset,
)


@pytest.fixture
def multi_tenant_fixture(db_session):
    # 1. Researcher Eshem
    eshem = User(
        email="eshem@researcher.com",
        hashed_password=get_password_hash("EshemPassword123"),
        full_name="Eshem Waseem",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    # 2. Researcher Bakhtawar
    bakhtawar = User(
        email="bakhtawar@researcher.com",
        hashed_password=get_password_hash("BakhtawarPass123"),
        full_name="Bakhtawar Tasawar",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    # 3. System Admin
    admin = User(
        email="admin@neuroforge.org",
        hashed_password=get_password_hash("AdminMaster123"),
        full_name="System Administrator",
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db_session.add_all([eshem, bakhtawar, admin])
    db_session.commit()

    eshem_token = create_access_token(eshem.id, eshem.role)
    bakhtawar_token = create_access_token(bakhtawar.id, bakhtawar.role)
    admin_token = create_access_token(admin.id, admin.role)

    # Bakhtawar's private project
    bakhtawar_proj = Project(
        title="Cancer Gene-Expression",
        description="Private oncogenomics study by Bakhtawar",
        domain="Cancer Gene-Expression",
        status="Active",
        owner_id=bakhtawar.id,
    )
    # Eshem's private project
    eshem_proj = Project(
        title="Eshem Transcriptomics Study",
        description="Private transcriptomics study by Eshem",
        domain="Cancer Gene-Expression",
        status="Active",
        owner_id=eshem.id,
    )
    db_session.add_all([bakhtawar_proj, eshem_proj])
    db_session.commit()

    # Bakhtawar's dataset
    bakhtawar_dataset = Dataset(
        project_id=bakhtawar_proj.id,
        owner_id=bakhtawar.id,
        filename="bakhtawar_matrix.csv",
        original_name="bakhtawar_matrix.csv",
        file_size_bytes=1024,
        file_format="CSV",
        status="Validated",
        sample_count=4,
        feature_count=10,
        content_hash="hash_bakhtawar_123",
        matrix_orientation="features_as_rows",
    )
    # Eshem's dataset
    eshem_dataset = Dataset(
        project_id=eshem_proj.id,
        owner_id=eshem.id,
        filename="eshem_matrix.csv",
        original_name="eshem_matrix.csv",
        file_size_bytes=1024,
        file_format="CSV",
        status="Validated",
        sample_count=4,
        feature_count=10,
        content_hash="hash_eshem_123",
        matrix_orientation="features_as_rows",
    )
    db_session.add_all([bakhtawar_dataset, eshem_dataset])
    db_session.commit()

    # Bakhtawar's experiment
    bakhtawar_exp = Experiment(
        project_id=bakhtawar_proj.id,
        dataset_id=bakhtawar_dataset.id,
        owner_id=bakhtawar.id,
        title="Bakhtawar Differential Screening",
        code="print('Bakhtawar experiment')",
        status=ExperimentStatus.COMPLETED.value,
        dataset_hash="hash_bakhtawar_123",
        result_summary="Identified top biomarkers",
    )
    db_session.add(bakhtawar_exp)
    db_session.commit()

    # Bakhtawar's research session
    bakhtawar_session = ResearchSession(
        project_id=bakhtawar_proj.id,
        dataset_id=bakhtawar_dataset.id,
        owner_id=bakhtawar.id,
        title="Bakhtawar Autonomous Agent Session",
        objective="Screen candidate oncogenes in Bakhtawar dataset",
        dataset_hash="hash_bakhtawar_123",
        status=SessionStatus.AWAITING_APPROVAL.value,
        current_step="await_human_approval",
        approval_state=ApprovalState.PENDING.value,
        research_plan=json.dumps({"plan_hash": "test_hash_123", "objective": "Screen genes"}),
    )
    db_session.add(bakhtawar_session)
    db_session.commit()

    return {
        "eshem": eshem,
        "bakhtawar": bakhtawar,
        "admin": admin,
        "eshem_token": eshem_token,
        "bakhtawar_token": bakhtawar_token,
        "admin_token": admin_token,
        "eshem_proj": eshem_proj,
        "bakhtawar_proj": bakhtawar_proj,
        "eshem_dataset": eshem_dataset,
        "bakhtawar_dataset": bakhtawar_dataset,
        "bakhtawar_exp": bakhtawar_exp,
        "bakhtawar_session": bakhtawar_session,
    }


# =============================================================================
# 1. Multi-Tenant Project Isolation Tests
# =============================================================================

def test_multi_tenant_project_listing_isolation(client, multi_tenant_fixture):
    """Verify Eshem sees ONLY Eshem's projects, Bakhtawar sees ONLY Bakhtawar's, and Admin sees both."""
    f = multi_tenant_fixture

    # Eshem requests project list
    res_eshem = client.get("/projects", headers={"Authorization": f"Bearer {f['eshem_token']}"})
    assert res_eshem.status_code == status.HTTP_200_OK
    eshem_projects = res_eshem.json()
    assert len(eshem_projects) == 1
    assert eshem_projects[0]["id"] == f["eshem_proj"].id
    assert eshem_projects[0]["title"] == "Eshem Transcriptomics Study"
    assert not any(p["id"] == f["bakhtawar_proj"].id for p in eshem_projects)

    # Bakhtawar requests project list
    res_bakh = client.get("/projects", headers={"Authorization": f"Bearer {f['bakhtawar_token']}"})
    assert res_bakh.status_code == status.HTTP_200_OK
    bakh_projects = res_bakh.json()
    assert len(bakh_projects) == 1
    assert bakh_projects[0]["id"] == f["bakhtawar_proj"].id
    assert bakh_projects[0]["title"] == "Cancer Gene-Expression"
    assert not any(p["id"] == f["eshem_proj"].id for p in bakh_projects)

    # Admin requests project list -> sees both
    res_admin = client.get("/projects", headers={"Authorization": f"Bearer {f['admin_token']}"})
    assert res_admin.status_code == status.HTTP_200_OK
    admin_projects = res_admin.json()
    assert len(admin_projects) >= 2
    admin_proj_ids = [p["id"] for p in admin_projects]
    assert f["eshem_proj"].id in admin_proj_ids
    assert f["bakhtawar_proj"].id in admin_proj_ids


def test_get_project_by_id_authorization(client, multi_tenant_fixture):
    """Verify Eshem cannot access Bakhtawar's project by ID (403 Forbidden)."""
    f = multi_tenant_fixture

    # Eshem accesses Bakhtawar's project -> 403
    res = client.get(
        f"/projects/{f['bakhtawar_proj'].id}",
        headers={"Authorization": f"Bearer {f['eshem_token']}"},
    )
    assert res.status_code == status.HTTP_403_FORBIDDEN
    assert "permission" in res.json()["detail"].lower()

    # Bakhtawar accesses own project -> 200
    res_bakh = client.get(
        f"/projects/{f['bakhtawar_proj'].id}",
        headers={"Authorization": f"Bearer {f['bakhtawar_token']}"},
    )
    assert res_bakh.status_code == status.HTTP_200_OK
    assert res_bakh.json()["id"] == f["bakhtawar_proj"].id

    # Admin accesses Bakhtawar's project -> 200
    res_admin = client.get(
        f"/projects/{f['bakhtawar_proj'].id}",
        headers={"Authorization": f"Bearer {f['admin_token']}"},
    )
    assert res_admin.status_code == status.HTTP_200_OK


def test_list_project_experiments_authorization(client, multi_tenant_fixture):
    """Verify Eshem cannot list experiments belonging to Bakhtawar's project."""
    f = multi_tenant_fixture

    # Eshem tries to view experiments in Bakhtawar's project -> 403
    res = client.get(
        f"/projects/{f['bakhtawar_proj'].id}/experiments",
        headers={"Authorization": f"Bearer {f['eshem_token']}"},
    )
    assert res.status_code == status.HTTP_403_FORBIDDEN
    assert "permission" in res.json()["detail"].lower()

    # Bakhtawar views own project experiments -> 200
    res_bakh = client.get(
        f"/projects/{f['bakhtawar_proj'].id}/experiments",
        headers={"Authorization": f"Bearer {f['bakhtawar_token']}"},
    )
    assert res_bakh.status_code == status.HTTP_200_OK
    assert len(res_bakh.json()) == 1

    # Admin views experiments in Bakhtawar's project -> 200
    res_admin = client.get(
        f"/projects/{f['bakhtawar_proj'].id}/experiments",
        headers={"Authorization": f"Bearer {f['admin_token']}"},
    )
    assert res_admin.status_code == status.HTTP_200_OK
    assert len(res_admin.json()) == 1


# =============================================================================
# 2. Dataset Upload Pre-Validation & Chunking Tests
# =============================================================================

def test_upload_dataset_into_unauthorized_project_rejected_before_parsing(client, multi_tenant_fixture):
    """Verify unauthorized project upload is rejected immediately before file parsing."""
    f = multi_tenant_fixture

    # Invalid matrix file (would fail parsing if parsing was executed first)
    invalid_matrix = b"INVALID,CORRUPTED,DATA\nNO_NUMERICAL_DATA\n"

    # Eshem tries to upload into Bakhtawar's project -> 403 Forbidden
    res = client.post(
        "/datasets/upload",
        data={"project_id": f["bakhtawar_proj"].id, "title": "Tampered Upload"},
        files={"file": ("corrupt.csv", io.BytesIO(invalid_matrix), "text/csv")},
        headers={"Authorization": f"Bearer {f['eshem_token']}"},
    )
    assert res.status_code == status.HTTP_403_FORBIDDEN
    assert "permission" in res.json()["detail"].lower()

    # Upload into non-existent project -> 404 Not Found
    res_404 = client.post(
        "/datasets/upload",
        data={"project_id": "non-existent-uuid-12345", "title": "Orphan Upload"},
        files={"file": ("corrupt.csv", io.BytesIO(invalid_matrix), "text/csv")},
        headers={"Authorization": f"Bearer {f['eshem_token']}"},
    )
    assert res_404.status_code == status.HTTP_404_NOT_FOUND
    assert "not found" in res_404.json()["detail"].lower()


def test_upload_dataset_exact_200_mib_size_boundary():
    """Verify that the 200 MiB limit constant is exactly 209,715,200 bytes and enforces strict boundaries."""
    assert MAX_FILE_SIZE_BYTES == 200 * 1024 * 1024
    assert MAX_FILE_SIZE_BYTES == 209715200

    # Test the parser boundary directly without allocating 200MB memory
    # A mocked bytes-like object with len == MAX_FILE_SIZE_BYTES
    class MockExactBoundaryBytes:
        def __len__(self):
            return 200 * 1024 * 1024

    mock_exact = MockExactBoundaryBytes()
    # file_size == MAX_FILE_SIZE_BYTES should not raise the size boundary exception
    assert len(mock_exact) <= MAX_FILE_SIZE_BYTES

    # Exceeding by 1 byte
    class MockOversizedBytes:
        def __len__(self):
            return (200 * 1024 * 1024) + 1

    mock_over = MockOversizedBytes()
    assert len(mock_over) > MAX_FILE_SIZE_BYTES

    with pytest.raises(DatasetParseError) as exc_info:
        parse_scientific_dataset(mock_over, "test.csv")
    assert "exceeds maximum allowed limit" in str(exc_info.value)


def test_upload_dataset_chunked_size_rejection_at_endpoint(client, multi_tenant_fixture):
    """Verify endpoint rejects oversized files as soon as accumulated bytes exceed limit with HTTP 413."""
    f = multi_tenant_fixture

    # Patch MAX_FILE_SIZE_BYTES to 100 bytes to test endpoint boundary without allocating 200MB
    with patch("app.api.routers.datasets.MAX_FILE_SIZE_BYTES", 100):
        # 1. Valid CSV of <= 100 bytes is accepted
        valid_csv = b"gene,s1,s2\nTP53,1,2\n"  # 20 bytes
        res_ok = client.post(
            "/datasets/upload",
            files={"file": ("under_limit.csv", io.BytesIO(valid_csv), "text/csv")},
            headers={"Authorization": f"Bearer {f['eshem_token']}"},
        )
        assert res_ok.status_code == status.HTTP_201_CREATED

        # 2. 101 bytes exceeds the limit -> HTTP 413 Request Entity Too Large
        oversized = b"gene,s1,s2\n" + b"X" * 100  # > 100 bytes
        res_fail = client.post(
            "/datasets/upload",
            files={"file": ("over_limit.csv", io.BytesIO(oversized), "text/csv")},
            headers={"Authorization": f"Bearer {f['eshem_token']}"},
        )
        assert res_fail.status_code == status.HTTP_413_CONTENT_TOO_LARGE
        assert "exceeds maximum allowed size" in res_fail.json()["detail"].lower()


# =============================================================================
# 3. Autonomous Research Agent Multi-Tenant Isolation Tests
# =============================================================================

def test_autonomous_research_agent_cross_user_isolation(client, multi_tenant_fixture):
    """Verify Eshem cannot create, view, approve, reject, or inspect Bakhtawar's agent sessions."""
    f = multi_tenant_fixture

    # 1. Eshem cannot launch research session in Bakhtawar's project
    res_launch = client.post(
        f"/projects/{f['bakhtawar_proj'].id}/research-sessions",
        json={
            "dataset_id": f["eshem_dataset"].id,
            "title": "Unauthorized Session Attempt",
            "objective": "Attempt to hijack Bakhtawar project",
        },
        headers={"Authorization": f"Bearer {f['eshem_token']}"},
    )
    assert res_launch.status_code == status.HTTP_403_FORBIDDEN
    assert "access denied to this project" in res_launch.json()["detail"].lower()

    # 2. Eshem cannot launch research session using Bakhtawar's private dataset in Eshem's project
    res_dataset_hijack = client.post(
        f"/projects/{f['eshem_proj'].id}/research-sessions",
        json={
            "dataset_id": f["bakhtawar_dataset"].id,
            "title": "Unauthorized Dataset Use",
            "objective": "Attempt to use Bakhtawar dataset",
        },
        headers={"Authorization": f"Bearer {f['eshem_token']}"},
    )
    assert res_dataset_hijack.status_code == status.HTTP_403_FORBIDDEN
    assert "permission to access the specified dataset" in res_dataset_hijack.json()["detail"].lower()

    # 3. Eshem cannot list sessions in Bakhtawar's project
    res_list = client.get(
        f"/projects/{f['bakhtawar_proj'].id}/research-sessions",
        headers={"Authorization": f"Bearer {f['eshem_token']}"},
    )
    assert res_list.status_code == status.HTTP_403_FORBIDDEN

    # 4. Eshem cannot retrieve Bakhtawar's session by ID
    res_get = client.get(
        f"/research-sessions/{f['bakhtawar_session'].id}",
        headers={"Authorization": f"Bearer {f['eshem_token']}"},
    )
    assert res_get.status_code == status.HTTP_403_FORBIDDEN

    # 5. Eshem cannot approve Bakhtawar's research session plan
    res_approve = client.post(
        f"/research-sessions/{f['bakhtawar_session'].id}/approve",
        json={"decision": "approve", "plan_hash": "test_hash_123"},
        headers={"Authorization": f"Bearer {f['eshem_token']}"},
    )
    assert res_approve.status_code == status.HTTP_403_FORBIDDEN

    # 6. Eshem cannot reject Bakhtawar's research session
    res_reject = client.post(
        f"/research-sessions/{f['bakhtawar_session'].id}/reject",
        json={"decision": "reject", "notes": "Rejecting another user's session"},
        headers={"Authorization": f"Bearer {f['eshem_token']}"},
    )
    assert res_reject.status_code == status.HTTP_403_FORBIDDEN

    # 7. Eshem cannot read events, evidence, or summary
    assert client.get(
        f"/research-sessions/{f['bakhtawar_session'].id}/events",
        headers={"Authorization": f"Bearer {f['eshem_token']}"},
    ).status_code == status.HTTP_403_FORBIDDEN

    assert client.get(
        f"/research-sessions/{f['bakhtawar_session'].id}/evidence",
        headers={"Authorization": f"Bearer {f['eshem_token']}"},
    ).status_code == status.HTTP_403_FORBIDDEN

    assert client.get(
        f"/research-sessions/{f['bakhtawar_session'].id}/summary",
        headers={"Authorization": f"Bearer {f['eshem_token']}"},
    ).status_code == status.HTTP_403_FORBIDDEN


# =============================================================================
# 4. Overview Statistics Multi-Tenant Scoping Tests
# =============================================================================

def test_overview_stats_scoping(client, multi_tenant_fixture):
    """Verify overview statistics are strictly scoped to the authenticated user."""
    f = multi_tenant_fixture

    # Eshem overview stats -> 1 project, 1 dataset, 0 experiments
    res_eshem = client.get("/overview/stats", headers={"Authorization": f"Bearer {f['eshem_token']}"})
    assert res_eshem.status_code == status.HTTP_200_OK
    stats_eshem = res_eshem.json()
    assert stats_eshem["projects_count"] == 1
    assert stats_eshem["datasets_count"] == 1
    assert stats_eshem["experiments_count"] == 0

    # Bakhtawar overview stats -> 1 project, 1 dataset, 1 experiment
    res_bakh = client.get("/overview/stats", headers={"Authorization": f"Bearer {f['bakhtawar_token']}"})
    assert res_bakh.status_code == status.HTTP_200_OK
    stats_bakh = res_bakh.json()
    assert stats_bakh["projects_count"] == 1
    assert stats_bakh["datasets_count"] == 1
    assert stats_bakh["experiments_count"] == 1

    # Admin overview stats -> global platform totals
    res_admin = client.get("/overview/stats", headers={"Authorization": f"Bearer {f['admin_token']}"})
    assert res_admin.status_code == status.HTTP_200_OK
    stats_admin = res_admin.json()
    assert stats_admin["projects_count"] >= 2
    assert stats_admin["datasets_count"] >= 2
    assert stats_admin["experiments_count"] >= 1
