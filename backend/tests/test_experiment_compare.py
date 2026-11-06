import os
import json
import uuid
import pytest
from app.core.security import get_password_hash, create_access_token
from app.db.models import User, UserRole, Project, Dataset, Experiment, ExperimentStatus
from app.services.storage import get_artifact_dir


def test_compare_experiments_success(client, db_session):
    # Setup researcher and project
    user = User(
        email="compare_tester@neuroforge.org",
        hashed_password=get_password_hash("ValidPass123"),
        full_name="Compare Tester",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    token = create_access_token(user.id, user.role)

    project = Project(
        title="Comparative Transcriptomics Project",
        description="Testing cross-experiment reproducibility",
        domain="Cancer Gene-Expression",
        status="Active",
        owner_id=user.id,
    )
    db_session.add(project)
    db_session.commit()

    dataset = Dataset(
        project_id=project.id,
        owner_id=user.id,
        filename="test_dataset.csv",
        original_name="test_dataset.csv",
        file_size_bytes=1024,
        file_format="CSV",
        status="Validated",
        sample_count=10,
        feature_count=100,
        content_hash="abc123sha256hash",
    )
    db_session.add(dataset)
    db_session.commit()

    exp1_id = str(uuid.uuid4())
    exp2_id = str(uuid.uuid4())

    # Write differential expression CSV for experiment 1
    exp1_dir = get_artifact_dir(exp1_id)
    os.makedirs(exp1_dir, exist_ok=True)
    exp1_csv = (
        "feature_id,log2_fc,p_value,adj_p_value,is_significant\n"
        "TP53,2.5,0.001,0.005,True\n"
        "BRCA1,-1.8,0.002,0.008,True\n"
        "EGFR,0.5,0.2,0.4,False\n"
        "MYC,3.1,0.0001,0.001,True\n"
    )
    with open(os.path.join(exp1_dir, "differential_expression_results.csv"), "w", encoding="utf-8") as f:
        f.write(exp1_csv)

    # Write differential expression CSV for experiment 2 (TP53 concordant, BRCA1 concordant, PTEN unique)
    exp2_dir = get_artifact_dir(exp2_id)
    os.makedirs(exp2_dir, exist_ok=True)
    exp2_csv = (
        "feature_id,log2_fc,p_value,adj_p_value,is_significant\n"
        "TP53,2.1,0.002,0.009,True\n"
        "BRCA1,-2.0,0.001,0.006,True\n"
        "PTEN,-1.5,0.005,0.02,True\n"
    )
    with open(os.path.join(exp2_dir, "differential_expression_results.csv"), "w", encoding="utf-8") as f:
        f.write(exp2_csv)

    exp1 = Experiment(
        id=exp1_id,
        project_id=project.id,
        dataset_id=dataset.id,
        owner_id=user.id,
        title="Differential Run A",
        code="# run a",
        status=ExperimentStatus.COMPLETED.value,
        artifacts=json.dumps(["differential_expression_results.csv"]),
        dataset_hash="abc123sha256hash",
    )
    exp2 = Experiment(
        id=exp2_id,
        project_id=project.id,
        dataset_id=dataset.id,
        owner_id=user.id,
        title="Differential Run B",
        code="# run b",
        status=ExperimentStatus.COMPLETED.value,
        artifacts=json.dumps(["differential_expression_results.csv"]),
        dataset_hash="abc123sha256hash",
    )
    db_session.add_all([exp1, exp2])
    db_session.commit()

    headers = {"Authorization": f"Bearer {token}"}
    response = client.get(f"/experiments/compare?exp1_id={exp1_id}&exp2_id={exp2_id}", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["shared_dataset"] is True
    assert data["dataset_hash_match"] is True
    assert data["exp1"]["id"] == exp1_id
    assert data["exp2"]["id"] == exp2_id
    assert data["shared_significant_count"] == 2  # TP53, BRCA1
    assert data["concordance_rate"] == 100.0  # Both TP53 (+/+) and BRCA1 (-/-) match
    shared_features = [item["feature_id"] for item in data["shared_features"]]
    assert "TP53" in shared_features
    assert "BRCA1" in shared_features
    unique1 = [item["feature_id"] for item in data["exp1_unique_features"]]
    unique2 = [item["feature_id"] for item in data["exp2_unique_features"]]
    assert "MYC" in unique1
    assert "PTEN" in unique2


def test_compare_same_experiment_400(client, db_session):
    user = User(
        email="same_exp@neuroforge.org",
        hashed_password=get_password_hash("ValidPass123"),
        full_name="Same Exp",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    token = create_access_token(user.id, user.role)

    exp_id = str(uuid.uuid4())
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get(f"/experiments/compare?exp1_id={exp_id}&exp2_id={exp_id}", headers=headers)
    assert response.status_code == 400
    assert "Cannot compare an experiment to itself" in response.json()["detail"]


def test_compare_nonexistent_experiment_404(client, db_session):
    user = User(
        email="missing_exp@neuroforge.org",
        hashed_password=get_password_hash("ValidPass123"),
        full_name="Missing Exp",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    token = create_access_token(user.id, user.role)

    headers = {"Authorization": f"Bearer {token}"}
    response = client.get(f"/experiments/compare?exp1_id={uuid.uuid4()}&exp2_id={uuid.uuid4()}", headers=headers)
    assert response.status_code == 404


def test_compare_unauthorized_access_403(client, db_session):
    # Owner
    owner = User(
        email="exp_owner@neuroforge.org",
        hashed_password=get_password_hash("ValidPass123"),
        full_name="Exp Owner",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    # Other researcher
    other = User(
        email="other_researcher@neuroforge.org",
        hashed_password=get_password_hash("ValidPass123"),
        full_name="Other Researcher",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add_all([owner, other])
    db_session.commit()

    project = Project(
        title="Private Oncogenomics",
        description="Private Project",
        domain="Cancer Gene-Expression",
        status="Active",
        owner_id=owner.id,
    )
    db_session.add(project)
    db_session.commit()

    exp1_id = str(uuid.uuid4())
    exp2_id = str(uuid.uuid4())
    exp1 = Experiment(
        id=exp1_id,
        project_id=project.id,
        owner_id=owner.id,
        title="Private Run A",
        code="# run",
        status=ExperimentStatus.COMPLETED.value,
    )
    exp2 = Experiment(
        id=exp2_id,
        project_id=project.id,
        owner_id=owner.id,
        title="Private Run B",
        code="# run",
        status=ExperimentStatus.COMPLETED.value,
    )
    db_session.add_all([exp1, exp2])
    db_session.commit()

    # Other researcher attempts access
    other_token = create_access_token(other.id, other.role)
    headers = {"Authorization": f"Bearer {other_token}"}
    response = client.get(f"/experiments/compare?exp1_id={exp1_id}&exp2_id={exp2_id}", headers=headers)
    assert response.status_code == 403
