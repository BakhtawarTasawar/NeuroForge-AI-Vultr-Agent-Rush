import io
import json
import pytest
from unittest.mock import patch
from fastapi import status

from app.core.security import get_password_hash, create_access_token
from app.db.models import User, UserRole, Project, Dataset, Experiment, ExperimentStatus
from app.services.sandbox import SandboxExecutionService, ExecutionResult, sanitize_output
from app.services.storage import get_artifact_dir


def test_experiment_successful_execution_and_artifacts(client, db_session):
    # Setup researcher and project
    user = User(
        email="bio_scientist@neuroforge.org",
        hashed_password=get_password_hash("ValidPass123"),
        full_name="Bio Scientist",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    token = create_access_token(user.id, user.role)

    project = Project(
        title="Gene Expression Screening",
        description="Testing PCA and plotting in sandbox",
        domain="Cancer Gene-Expression",
        status="Active",
        owner_id=user.id,
    )
    db_session.add(project)
    db_session.commit()

    # Valid Python script that performs calculation and generates a plot
    script = """
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# Simulate gene matrix
genes = ['BRCA1', 'TP53', 'EGFR', 'MYC']
data = np.random.rand(4, 5)
df = pd.DataFrame(data, index=genes)
print("Gene expression matrix computed successfully.")
print(df.describe())

# Save an artifact
plt.figure()
plt.bar(genes, [1.2, 3.4, 0.8, 2.1])
plt.title("Simulated Expression")
plt.savefig("/workspace/differential_plot.png")
plt.close()

# Save a CSV artifact
df.to_csv("/workspace/results.csv")
"""

    res = client.post(
        f"/projects/{project.id}/experiments",
        json={
            "title": "PCA and Differential Expression",
            "description": "Calculates matrix summary and saves plot",
            "code": script,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    if data["status"] != "Completed":
        print("\nDEBUG TEST FAILED WITH:", data.get("status"), data.get("exit_code"), repr(data.get("stderr")), repr(data.get("failure_reason")))
    assert data["title"] == "PCA and Differential Expression"
    assert data["status"] == "Completed"
    assert data["exit_code"] == 0
    assert "Gene expression matrix computed successfully" in data["stdout"]
    assert data["duration_seconds"] is not None
    assert data["duration_seconds"] > 0

    # Verify artifacts were cataloged
    artifacts = data["artifacts"]
    assert len(artifacts) >= 2
    filenames = [a["filename"] for a in artifacts]
    assert "differential_plot.png" in filenames
    assert "results.csv" in filenames

    # Test artifact download
    exp_id = data["id"]
    download_res = client.get(
        f"/experiments/{exp_id}/artifacts/differential_plot.png",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert download_res.status_code == status.HTTP_200_OK
    assert download_res.headers["content-type"] in ["image/png", "application/octet-stream"]
    assert len(download_res.content) > 0


def test_experiment_syntax_error_failure(client, db_session):
    user = User(
        email="syntax_tester@neuroforge.org",
        hashed_password=get_password_hash("ValidPass123"),
        full_name="Syntax Tester",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    token = create_access_token(user.id, user.role)

    project = Project(
        title="Syntax Test Project",
        owner_id=user.id,
    )
    db_session.add(project)
    db_session.commit()

    bad_script = "def invalid_python(:\n  return 'broken'"

    res = client.post(
        f"/projects/{project.id}/experiments",
        json={
            "title": "Invalid Code Run",
            "code": bad_script,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    assert data["status"] == "Failed"
    assert data["exit_code"] != 0
    assert "SyntaxError" in data["stderr"]
    assert "syntax error" in data["failure_reason"].lower()


def test_experiment_timeout_enforcement(client, db_session):
    user = User(
        email="timeout_tester@neuroforge.org",
        hashed_password=get_password_hash("ValidPass123"),
        full_name="Timeout Tester",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    token = create_access_token(user.id, user.role)

    project = Project(title="Timeout Test Project", owner_id=user.id)
    db_session.add(project)
    db_session.commit()

    # Create experiment directly using SandboxExecutionService with 2s timeout
    infinite_script = "import time\ntime.sleep(10)\nprint('Done sleeping')"
    result = SandboxExecutionService.execute(
        experiment_id="test_timeout_exp",
        code=infinite_script,
        timeout_seconds=2,
    )

    assert result.status == ExperimentStatus.TIMED_OUT
    assert "exceeded maximum execution time boundary" in result.failure_reason


def test_experiment_network_isolation_in_sandbox(client, db_session):
    # Verify that python inside the sandbox cannot open internet sockets
    network_script = """
import urllib.request
try:
    urllib.request.urlopen("http://1.1.1.1", timeout=2)
    print("NETWORK_ACCESSIBLE")
except Exception as e:
    print(f"NETWORK_BLOCKED: {type(e).__name__}")
"""
    result = SandboxExecutionService.execute(
        experiment_id="test_net_exp",
        code=network_script,
    )
    assert result.status == ExperimentStatus.COMPLETED
    assert "NETWORK_BLOCKED" in result.stdout
    assert "NETWORK_ACCESSIBLE" not in result.stdout


def test_output_truncation_safety():
    huge_text = "A" * 100000
    truncated = sanitize_output(huge_text, max_bytes=1000)
    assert len(truncated.encode("utf-8")) <= 1500
    assert "[Output truncated:" in truncated


def test_viewer_cannot_execute_experiment(client, db_session):
    viewer = User(
        email="viewer@neuroforge.org",
        hashed_password=get_password_hash("ValidPass123"),
        full_name="Read Only Viewer",
        role=UserRole.VIEWER.value,
        is_active=True,
    )
    owner = User(
        email="owner@neuroforge.org",
        hashed_password=get_password_hash("ValidPass123"),
        full_name="Project Owner",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add_all([viewer, owner])
    db_session.commit()

    project = Project(title="Owner Project", owner_id=owner.id)
    db_session.add(project)
    db_session.commit()

    viewer_token = create_access_token(viewer.id, viewer.role)

    res = client.post(
        f"/projects/{project.id}/experiments",
        json={"title": "Viewer Experiment", "code": "print('hello')"},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res.status_code == status.HTTP_403_FORBIDDEN


def test_researcher_cannot_execute_in_other_project(client, db_session):
    res1 = User(
        email="res1@neuroforge.org",
        hashed_password=get_password_hash("ValidPass123"),
        full_name="Researcher One",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    res2 = User(
        email="res2@neuroforge.org",
        hashed_password=get_password_hash("ValidPass123"),
        full_name="Researcher Two",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add_all([res1, res2])
    db_session.commit()

    p1 = Project(title="R1 Project", owner_id=res1.id)
    db_session.add(p1)
    db_session.commit()

    r2_token = create_access_token(res2.id, res2.role)

    res = client.post(
        f"/projects/{p1.id}/experiments",
        json={"title": "R2 intrusion", "code": "print('hello')"},
        headers={"Authorization": f"Bearer {r2_token}"},
    )
    assert res.status_code == status.HTTP_403_FORBIDDEN
    assert "permission" in res.json()["detail"].lower()


def test_artifact_path_traversal_blocked(client, db_session):
    user = User(
        email="sec_tester@neuroforge.org",
        hashed_password=get_password_hash("ValidPass123"),
        full_name="Security Tester",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    token = create_access_token(user.id, user.role)

    project = Project(title="Sec Project", owner_id=user.id)
    db_session.add(project)
    db_session.commit()

    exp = Experiment(
        project_id=project.id,
        owner_id=user.id,
        title="Exp with artifact",
        code="print('done')",
        status=ExperimentStatus.COMPLETED.value,
    )
    db_session.add(exp)
    db_session.commit()

    # Attempt path traversal
    bad_traversal = client.get(
        f"/experiments/{exp.id}/artifacts/..%2F..%2F..%2Fetc%2Fpasswd",
        headers={"Authorization": f"Bearer {token}"},
    )
    # Should be 403 Forbidden or 404 Not Found, never 200
    assert bad_traversal.status_code in [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND]


def test_docker_unavailable_handling():
    with patch("app.services.sandbox.check_docker_available", return_value=False):
        res = SandboxExecutionService.execute(
            experiment_id="docker_down_exp",
            code="print('hello')",
        )
        assert res.status == ExperimentStatus.FAILED
        assert "unavailable" in res.failure_reason.lower()

