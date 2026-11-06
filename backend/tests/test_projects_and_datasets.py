import io
from fastapi import status
from app.db.models import User, UserRole, Project, Dataset
from app.core.security import get_password_hash, create_access_token


def test_change_password_revokes_sessions(client, db_session):
    # Register a user
    user = User(
        email="pw_test@neuroforge.org",
        hashed_password=get_password_hash("OldPassword123"),
        full_name="Password Tester",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    token = create_access_token(user.id, user.role)

    # Incorrect current password
    bad_res = client.post(
        "/auth/change-password",
        json={"current_password": "WrongPassword999", "new_password": "NewPassword123"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert bad_res.status_code == status.HTTP_400_BAD_REQUEST

    # Valid change
    good_res = client.post(
        "/auth/change-password",
        json={"current_password": "OldPassword123", "new_password": "NewPassword123"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert good_res.status_code == status.HTTP_200_OK
    assert "updated securely" in good_res.json()["message"]


def test_project_crud_lifecycle(client, db_session):
    user = User(
        email="proj_owner@neuroforge.org",
        hashed_password=get_password_hash("ValidPass123"),
        full_name="Project Owner",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    token = create_access_token(user.id, user.role)

    # 1. Create project
    create_res = client.post(
        "/projects",
        json={
            "title": "Oncology RNA-seq Biomarkers",
            "description": "Investigating differential expression in breast carcinoma.",
            "domain": "Cancer Gene-Expression",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_res.status_code == status.HTTP_201_CREATED
    proj_id = create_res.json()["id"]
    assert create_res.json()["title"] == "Oncology RNA-seq Biomarkers"

    # 2. Get project details
    get_res = client.get(f"/projects/{proj_id}", headers={"Authorization": f"Bearer {token}"})
    assert get_res.status_code == status.HTTP_200_OK
    assert get_res.json()["owner_id"] == user.id

    # 3. Update project
    update_res = client.put(
        f"/projects/{proj_id}",
        json={"title": "Updated Biomarkers Title", "status": "Archived"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert update_res.status_code == status.HTTP_200_OK
    assert update_res.json()["title"] == "Updated Biomarkers Title"
    assert update_res.json()["status"] == "Archived"

    # 4. List projects
    list_res = client.get("/projects", headers={"Authorization": f"Bearer {token}"})
    assert list_res.status_code == status.HTTP_200_OK
    assert len(list_res.json()) >= 1

    # 5. Delete project
    del_res = client.delete(f"/projects/{proj_id}", headers={"Authorization": f"Bearer {token}"})
    assert del_res.status_code == status.HTTP_200_OK


def test_dataset_upload_and_validation(client, db_session):
    user = User(
        email="data_lead@neuroforge.org",
        hashed_password=get_password_hash("ValidPass123"),
        full_name="Data Lead",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    token = create_access_token(user.id, user.role)

    # Prepare a valid CSV matrix: 3 genes (rows), 4 samples (cols)
    csv_content = b"gene_id,sample_01,sample_02,sample_03,sample_04\nBRCA1,12.4,14.1,11.9,13.5\nTP53,8.2,9.1,7.8,8.9\nEGFR,15.6,14.8,16.2,15.1\n"

    files = {"file": ("cancer_matrix.csv", io.BytesIO(csv_content), "text/csv")}
    res = client.post(
        "/datasets/upload",
        files=files,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    assert data["original_name"] == "cancer_matrix.csv"
    assert data["file_format"] == "CSV"
    assert data["feature_count"] == 3
    assert data["sample_count"] == 4
    assert data["status"] == "Validated"
    dataset_id = data["id"]

    # List datasets
    list_res = client.get("/datasets", headers={"Authorization": f"Bearer {token}"})
    assert list_res.status_code == status.HTTP_200_OK
    assert len(list_res.json()) == 1

    # Delete dataset
    del_res = client.delete(f"/datasets/{dataset_id}", headers={"Authorization": f"Bearer {token}"})
    assert del_res.status_code == status.HTTP_200_OK

