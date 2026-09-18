"""Authentication and authorization tests for PaperFlow AI Stage 9."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from auth.authorization import require_user
from models.user import AuthenticatedUser


def test_auth_router_registered(client: TestClient) -> None:
    """Verify that /api/auth routes are registered in the FastAPI app."""
    openapi_schema = client.app.openapi()  # type: ignore[attr-defined]
    paths = openapi_schema.get("paths", {})
    assert "/api/auth/me" in paths
    assert "/api/auth/refresh" in paths


def test_me_endpoint_rejects_missing_token(client: TestClient) -> None:
    """GET /api/auth/me without an Authorization header must return 401."""
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert "detail" in response.json()
    assert "Authentication required" in response.json()["detail"]


def test_me_endpoint_rejects_invalid_token(client: TestClient) -> None:
    """GET /api/auth/me with an invalid Bearer token must return 401."""
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer invalid.fake.token"},
    )
    assert response.status_code == 401
    assert "detail" in response.json()


def test_refresh_endpoint_rejects_missing_token(client: TestClient) -> None:
    """POST /api/auth/refresh without token must return 401."""
    response = client.post("/api/auth/refresh")
    assert response.status_code == 401


def test_refresh_endpoint_rejects_invalid_token(client: TestClient) -> None:
    """POST /api/auth/refresh with an invalid Bearer token must return 401."""
    response = client.post(
        "/api/auth/refresh",
        headers={"Authorization": "Bearer invalid.fake.token"},
    )
    assert response.status_code == 401


def test_protected_route_with_authenticated_user(client: TestClient) -> None:
    """A verified user can access /api/auth/me and receives safe profile data."""
    test_user = AuthenticatedUser(
        user_id="test-uuid-12345",
        email="testuser@example.com",
        role="authenticated",
    )

    # Override dependency to simulate a successfully validated user
    client.app.dependency_overrides[require_user] = lambda: test_user  # type: ignore[attr-defined]
    try:
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer valid-mock-token"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "test-uuid-12345"
        assert data["email"] == "testuser@example.com"
        assert "password" not in data
        assert "secret" not in data
    finally:
        client.app.dependency_overrides.clear()  # type: ignore[attr-defined]


def test_refresh_endpoint_with_authenticated_user(client: TestClient) -> None:
    """A verified user can call /api/auth/refresh and receives token validation confirmation."""
    test_user = AuthenticatedUser(
        user_id="test-uuid-67890",
        email="refresh@example.com",
        role="authenticated",
    )

    client.app.dependency_overrides[require_user] = lambda: test_user  # type: ignore[attr-defined]
    try:
        response = client.post(
            "/api/auth/refresh",
            headers={"Authorization": "Bearer valid-mock-token"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "test-uuid-67890"
        assert data["status"] == "token_valid"
    finally:
        client.app.dependency_overrides.clear()  # type: ignore[attr-defined]
