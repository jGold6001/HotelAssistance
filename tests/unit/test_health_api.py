from fastapi.testclient import TestClient
from hotel_assistance.main import app


def test_health_reports_configuration_without_secrets() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["filters"] > 400
    assert "api_key" not in str(body).lower()
