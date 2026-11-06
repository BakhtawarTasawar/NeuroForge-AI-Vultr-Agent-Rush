from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_check_returns_200():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "NeuroForge AI"
    assert "version" in data
    assert "environment" in data


def test_root_endpoint_returns_200():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "NeuroForge AI"
