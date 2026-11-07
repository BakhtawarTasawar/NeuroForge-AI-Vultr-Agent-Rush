import io
import json
from unittest.mock import patch, MagicMock
import pytest
from fastapi import status

from app.core.security import get_password_hash, create_access_token
from app.db.models import (
    ApprovalState,
    Dataset,
    Project,
    ResearchSession,
    SessionStatus,
    User,
    UserRole,
)
from app.services.research_graph import (
    AutonomousResearchRunner,
    ResearchState,
    ResearchPlanSchema,
)
from app.services.vultr_inference import InferenceResponse


VALID_CSV = (
    b"gene_id,sample_01,sample_02,sample_03,sample_04\n"
    b"TP53,10.2,10.4,14.5,14.8\n"
    b"BRCA1,8.1,8.3,12.1,12.4\n"
    b"EGFR,11.0,11.2,9.1,9.0\n"
)


@pytest.fixture
def dataset_project_fixture(db_session):
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
    # 3. Admin
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

    # Eshem projects
    eshem_proj_1 = Project(
        title="Eshem Project 1",
        description="First project by Eshem",
        domain="Cancer Gene-Expression",
        status="Active",
        owner_id=eshem.id,
    )
    eshem_proj_2 = Project(
        title="Eshem Project 2",
        description="Second project by Eshem",
        domain="Cancer Gene-Expression",
        status="Active",
        owner_id=eshem.id,
    )

    # Bakhtawar project
    bakhtawar_proj = Project(
        title="Bakhtawar Oncogenomics",
        description="Private project by Bakhtawar",
        domain="Cancer Gene-Expression",
        status="Active",
        owner_id=bakhtawar.id,
    )
    db_session.add_all([eshem_proj_1, eshem_proj_2, bakhtawar_proj])
    db_session.commit()

    # Eshem standalone dataset
    eshem_standalone_ds = Dataset(
        project_id=None,
        owner_id=eshem.id,
        filename="eshem_standalone.csv",
        original_name="eshem_standalone.csv",
        file_size_bytes=len(VALID_CSV),
        file_format="CSV",
        status="Validated",
        sample_count=4,
        feature_count=3,
        content_hash="hash_standalone_eshem",
        matrix_orientation="features_as_rows",
    )
    # Eshem attached dataset (attached to eshem_proj_1)
    eshem_attached_ds = Dataset(
        project_id=eshem_proj_1.id,
        owner_id=eshem.id,
        filename="eshem_attached.csv",
        original_name="eshem_attached.csv",
        file_size_bytes=len(VALID_CSV),
        file_format="CSV",
        status="Validated",
        sample_count=4,
        feature_count=3,
        content_hash="hash_attached_eshem",
        matrix_orientation="features_as_rows",
    )
    # Bakhtawar dataset (attached to bakhtawar_proj)
    bakhtawar_ds = Dataset(
        project_id=bakhtawar_proj.id,
        owner_id=bakhtawar.id,
        filename="bakhtawar_ds.csv",
        original_name="bakhtawar_ds.csv",
        file_size_bytes=len(VALID_CSV),
        file_format="CSV",
        status="Validated",
        sample_count=4,
        feature_count=3,
        content_hash="hash_bakhtawar",
        matrix_orientation="features_as_rows",
    )
    db_session.add_all([eshem_standalone_ds, eshem_attached_ds, bakhtawar_ds])
    db_session.commit()

    return {
        "eshem": eshem,
        "bakhtawar": bakhtawar,
        "admin": admin,
        "eshem_token": eshem_token,
        "bakhtawar_token": bakhtawar_token,
        "admin_token": admin_token,
        "eshem_proj_1": eshem_proj_1,
        "eshem_proj_2": eshem_proj_2,
        "bakhtawar_proj": bakhtawar_proj,
        "eshem_standalone_ds": eshem_standalone_ds,
        "eshem_attached_ds": eshem_attached_ds,
        "bakhtawar_ds": bakhtawar_ds,
    }


def test_01_upload_with_project_id_to_own_project(client, dataset_project_fixture):
    """1. Upload with project_id to own project returns 201 and associates project."""
    f = dataset_project_fixture
    res = client.post(
        "/datasets/upload",
        data={"project_id": f["eshem_proj_1"].id, "title": "Directly Attached Dataset"},
        files={"file": ("test_upload_1.csv", io.BytesIO(VALID_CSV), "text/csv")},
        headers={"Authorization": f"Bearer {f['eshem_token']}"},
    )
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    assert data["project_id"] == f["eshem_proj_1"].id
    assert data["owner_id"] == f["eshem"].id


def test_02_upload_standalone_dataset(client, dataset_project_fixture):
    """2. Upload standalone (no project_id) returns 201 with project_id as None."""
    f = dataset_project_fixture
    res = client.post(
        "/datasets/upload",
        data={"title": "Standalone Dataset"},
        files={"file": ("test_standalone.csv", io.BytesIO(VALID_CSV), "text/csv")},
        headers={"Authorization": f"Bearer {f['eshem_token']}"},
    )
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    assert data["project_id"] is None
    assert data["owner_id"] == f["eshem"].id


def test_03_upload_to_other_users_project_rejected(client, dataset_project_fixture):
    """3. Upload to another user's project is rejected with 403 Forbidden."""
    f = dataset_project_fixture
    res = client.post(
        "/datasets/upload",
        data={"project_id": f["bakhtawar_proj"].id, "title": "Unauthorized Upload"},
        files={"file": ("test_unauth.csv", io.BytesIO(VALID_CSV), "text/csv")},
        headers={"Authorization": f"Bearer {f['eshem_token']}"},
    )
    assert res.status_code == status.HTTP_403_FORBIDDEN
    assert "permission" in res.json()["detail"].lower()


def test_04_attach_standalone_dataset_to_own_project(client, dataset_project_fixture):
    """4. Attach standalone dataset to own project returns 200 and updates project_id."""
    f = dataset_project_fixture
    res = client.post(
        f"/datasets/{f['eshem_standalone_ds'].id}/attach",
        json={"project_id": f["eshem_proj_1"].id},
        headers={"Authorization": f"Bearer {f['eshem_token']}"},
    )
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["project_id"] == f["eshem_proj_1"].id


def test_05_attach_dataset_to_other_users_project_rejected(client, dataset_project_fixture):
    """5. Attach dataset to another user's project is rejected with 403 Forbidden."""
    f = dataset_project_fixture
    res = client.post(
        f"/datasets/{f['eshem_standalone_ds'].id}/attach",
        json={"project_id": f["bakhtawar_proj"].id},
        headers={"Authorization": f"Bearer {f['eshem_token']}"},
    )
    assert res.status_code == status.HTTP_403_FORBIDDEN
    assert "permission" in res.json()["detail"].lower()


def test_06_already_attached_dataset_cannot_be_moved(client, dataset_project_fixture):
    """6. Already-attached dataset cannot be attached to a different project (409 Conflict)."""
    f = dataset_project_fixture
    # eshem_attached_ds is attached to eshem_proj_1. Trying to attach to eshem_proj_2 fails.
    res = client.post(
        f"/datasets/{f['eshem_attached_ds'].id}/attach",
        json={"project_id": f["eshem_proj_2"].id},
        headers={"Authorization": f"Bearer {f['eshem_token']}"},
    )
    assert res.status_code == status.HTTP_409_CONFLICT
    assert "already attached" in res.json()["detail"].lower()


def test_07_attach_to_same_project_is_idempotent(client, dataset_project_fixture):
    """7. Attaching dataset to the same project it is already attached to is idempotent (200 OK)."""
    f = dataset_project_fixture
    res = client.post(
        f"/datasets/{f['eshem_attached_ds'].id}/attach",
        json={"project_id": f["eshem_proj_1"].id},
        headers={"Authorization": f"Bearer {f['eshem_token']}"},
    )
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["project_id"] == f["eshem_proj_1"].id


def test_08_session_creation_with_matching_attached_dataset(client, dataset_project_fixture):
    """8. Session creation with matching attached dataset succeeds."""
    f = dataset_project_fixture
    with patch.object(AutonomousResearchRunner, "run") as mock_run:
        res = client.post(
            f"/projects/{f['eshem_proj_1'].id}/research-sessions",
            json={
                "dataset_id": f["eshem_attached_ds"].id,
                "title": "Valid Attached Session",
                "objective": "Screen oncogenes in attached dataset",
            },
            headers={"Authorization": f"Bearer {f['eshem_token']}"},
        )
        assert res.status_code == status.HTTP_201_CREATED
        data = res.json()
        assert data["project_id"] == f["eshem_proj_1"].id
        assert data["dataset_id"] == f["eshem_attached_ds"].id
        assert mock_run.called


def test_09_session_creation_with_standalone_dataset_rejected(client, dataset_project_fixture):
    """9. Session creation with standalone dataset (project_id is None) returns 400 Bad Request."""
    f = dataset_project_fixture
    res = client.post(
        f"/projects/{f['eshem_proj_1'].id}/research-sessions",
        json={
            "dataset_id": f["eshem_standalone_ds"].id,
            "title": "Invalid Standalone Session",
            "objective": "Attempt to run standalone dataset",
        },
        headers={"Authorization": f"Bearer {f['eshem_token']}"},
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "not attached" in res.json()["detail"].lower()


def test_10_session_creation_with_mismatched_project_dataset_rejected(client, dataset_project_fixture):
    """10. Session creation for project 2 with dataset attached to project 1 returns 400 Bad Request."""
    f = dataset_project_fixture
    # eshem_attached_ds belongs to eshem_proj_1. Trying to launch session in eshem_proj_2 fails.
    res = client.post(
        f"/projects/{f['eshem_proj_2'].id}/research-sessions",
        json={
            "dataset_id": f["eshem_attached_ds"].id,
            "title": "Mismatched Project Session",
            "objective": "Attempt cross-project session",
        },
        headers={"Authorization": f"Bearer {f['eshem_token']}"},
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "not attached" in res.json()["detail"].lower()


def test_11_cross_user_dataset_access_rejected(client, dataset_project_fixture):
    """11. Cross-user dataset operations are strictly rejected with 403 Forbidden."""
    f = dataset_project_fixture

    # Eshem tries to attach Bakhtawar's dataset -> 403
    res_attach = client.post(
        f"/datasets/{f['bakhtawar_ds'].id}/attach",
        json={"project_id": f["eshem_proj_1"].id},
        headers={"Authorization": f"Bearer {f['eshem_token']}"},
    )
    assert res_attach.status_code == status.HTTP_403_FORBIDDEN

    # Eshem tries to inspect Bakhtawar's dataset -> 403
    res_inspect = client.get(
        f"/datasets/{f['bakhtawar_ds'].id}/inspection",
        headers={"Authorization": f"Bearer {f['eshem_token']}"},
    )
    assert res_inspect.status_code == status.HTTP_403_FORBIDDEN

    # Eshem tries to launch a session in Eshem's project using Bakhtawar's dataset -> 403
    res_session = client.post(
        f"/projects/{f['eshem_proj_1'].id}/research-sessions",
        json={
            "dataset_id": f["bakhtawar_ds"].id,
            "title": "Cross User Session Theft",
            "objective": "Steal Bakhtawar data",
        },
        headers={"Authorization": f"Bearer {f['eshem_token']}"},
    )
    assert res_session.status_code == status.HTTP_403_FORBIDDEN


def test_12_admin_access_policy(client, dataset_project_fixture):
    """12. System administrator can attach datasets across projects and initiate sessions."""
    f = dataset_project_fixture

    # Admin attaches Eshem's standalone dataset to Bakhtawar's project -> allowed
    res_attach = client.post(
        f"/datasets/{f['eshem_standalone_ds'].id}/attach",
        json={"project_id": f["bakhtawar_proj"].id},
        headers={"Authorization": f"Bearer {f['admin_token']}"},
    )
    assert res_attach.status_code == status.HTTP_200_OK
    assert res_attach.json()["project_id"] == f["bakhtawar_proj"].id

    # Admin creates research session in Bakhtawar's project with the newly attached dataset
    with patch.object(AutonomousResearchRunner, "run") as mock_run:
        res_session = client.post(
            f"/projects/{f['bakhtawar_proj'].id}/research-sessions",
            json={
                "dataset_id": f["eshem_standalone_ds"].id,
                "title": "Admin Investigation",
                "objective": "Admin platform-wide research oversight",
            },
            headers={"Authorization": f"Bearer {f['admin_token']}"},
        )
        assert res_session.status_code == status.HTTP_201_CREATED
        assert mock_run.called
