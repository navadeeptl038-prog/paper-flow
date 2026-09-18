"""CORS and frontend–backend connection tests."""

from __future__ import annotations

import os

import httpx
import pytest
from fastapi.testclient import TestClient


def test_health_allows_configured_frontend_origin(client: TestClient) -> None:
	origin = "http://localhost:5173"
	response = client.get("/health", headers={"Origin": origin})
	assert response.status_code == 200
	assert response.json() == {"status": "ok"}
	assert response.headers.get("access-control-allow-origin") == origin


def test_cors_preflight_for_health(client: TestClient) -> None:
	origin = "http://localhost:5173"
	response = client.options(
		"/health",
		headers={
			"Origin": origin,
			"Access-Control-Request-Method": "GET",
			"Access-Control-Request-Headers": "content-type",
		},
	)
	assert response.status_code in {200, 204}
	assert response.headers.get("access-control-allow-origin") == origin
	allow_methods = response.headers.get("access-control-allow-methods", "")
	assert "GET" in allow_methods.upper()


def test_cors_origins_respect_env_list(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com, https://admin.example.com")
	from main import _configured_origins

	assert _configured_origins() == [
		"https://app.example.com",
		"https://admin.example.com",
	]


@pytest.mark.integration
def test_live_health_endpoint_when_backend_url_set() -> None:
	"""Optional live check. Set PAPERFLOW_LIVE_API_URL to exercise a running server."""
	base = (os.getenv("PAPERFLOW_LIVE_API_URL") or "").strip().rstrip("/")
	if not base:
		pytest.skip("PAPERFLOW_LIVE_API_URL not set — start the API and export it to run this check")

	response = httpx.get(f"{base}/health", timeout=5.0)
	assert response.status_code == 200
	assert response.json() == {"status": "ok"}
