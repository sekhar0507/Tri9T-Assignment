from fastapi.testclient import TestClient
from app.main import app

def test_frontend_assets_and_health_are_served():
    client = TestClient(app)
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/health").json()["status"] == "ok"

def test_version_compare_endpoint_returns_change_summary():
    client = TestClient(app)
    a = client.post("/documents/test_compare/ingest/sample-v1")
    b = client.post("/documents/test_compare/ingest/sample-v2")
    assert a.status_code == 200
    assert b.status_code == 200
    result = client.get("/documents/test_compare/compare?from_version=1&to_version=2")
    assert result.status_code == 200
    summary = result.json()["summary"]
    assert summary["changed"] >= 1
    assert summary["added"] >= 1
