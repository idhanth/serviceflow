from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_reports_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # Dependencies are reported, never fatal to liveness.
    assert set(body["checks"]) == {"database", "redis"}


def test_ready_checks_database_and_redis(client: TestClient) -> None:
    response = client.get("/ready")
    body = response.json()
    assert set(body["checks"]) == {"database", "redis"}
    assert response.status_code == (200 if body["status"] == "ready" else 503)
