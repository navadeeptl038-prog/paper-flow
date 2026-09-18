"""Health endpoint foundation tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_returns_ok_status(client: TestClient) -> None:
	response = client.get("/health")
	assert response.status_code == 200
	payload = response.json()
	assert payload == {"status": "ok"}


def test_health_content_type_is_json(client: TestClient) -> None:
	response = client.get("/health")
	assert response.status_code == 200
	content_type = response.headers.get("content-type", "")
	assert "application/json" in content_type


def test_unknown_route_returns_404(client: TestClient) -> None:
	response = client.get("/this-route-does-not-exist")
	assert response.status_code == 404
