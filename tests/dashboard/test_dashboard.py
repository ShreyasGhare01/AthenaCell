import pytest
from fastapi.testclient import TestClient
from dashboard.backend.app import app

client = TestClient(app)

def test_dashboard_home():
    response = client.get("/")
    assert response.status_code == 200
    assert "AthenaCell" in response.text

def test_list_runs():
    response = client.get("/api/runs")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_research_library():
    response = client.get("/api/research/library")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
