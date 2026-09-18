"""Supabase configuration and connection foundation tests.

These tests verify:
1. Missing Supabase configuration raises clear errors (not misleading success).
2. Supabase client initialises correctly when valid config is present.
3. No credential values are exposed in errors or responses.
4. The /api/status endpoint reports configuration state truthfully.

Tests that need a real Supabase project are marked @pytest.mark.requires_config
and are skipped unless SUPABASE_URL and the key env vars are set.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Configuration validation (no network, no real secrets needed)
# ---------------------------------------------------------------------------


def test_check_supabase_config_raises_when_url_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing SUPABASE_URL must produce a RuntimeError with a helpful message."""
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)

    from services.supabase_client import check_supabase_config, reset_client

    reset_client()
    with pytest.raises(RuntimeError, match="SUPABASE_URL"):
        check_supabase_config()


def test_check_supabase_config_raises_when_no_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid URL with no key must raise a clear error (not succeed silently)."""
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)

    from services.supabase_client import check_supabase_config, reset_client

    reset_client()
    with pytest.raises(RuntimeError, match="SUPABASE_SERVICE_ROLE_KEY|SUPABASE_ANON_KEY"):
        check_supabase_config()


def test_check_supabase_config_succeeds_with_anon_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid URL + anon key should return a dict with expected keys, no secret values."""
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "fake-anon-key-for-test")
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    from services.supabase_client import check_supabase_config, reset_client

    reset_client()
    result = check_supabase_config()

    assert result["url_set"] is True
    assert result["anon_key_set"] is True
    assert result["service_role_set"] is False
    # Ensure no raw secret values appear in the returned dict
    for value in result.values():
        if isinstance(value, str):
            assert "fake-anon-key" not in value


def test_check_supabase_config_requires_https_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SUPABASE_URL without https:// prefix must raise a clear error."""
    monkeypatch.setenv("SUPABASE_URL", "http://insecure.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "fake-anon-key")

    from services.supabase_client import check_supabase_config, reset_client

    reset_client()
    with pytest.raises(RuntimeError, match="https://"):
        check_supabase_config()


# ---------------------------------------------------------------------------
# /api/status endpoint — safe configuration reporting
# ---------------------------------------------------------------------------


def test_api_status_reports_false_when_supabase_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When Supabase env vars are absent /api/status returns configured=false, not an error."""
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    from main import app  # noqa: PLC0415

    with TestClient(app) as tc:
        response = tc.get("/api/status")
    assert response.status_code == 200
    body = response.json()
    assert body["supabase_url_configured"] is False
    assert body["supabase_key_configured"] is False


def test_api_status_does_not_expose_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The /api/status response body must never contain env variable values."""
    monkeypatch.setenv("SUPABASE_URL", "https://secret-project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "super-secret-anon-value")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "ultra-secret-service-role")

    from main import app  # noqa: PLC0415

    with TestClient(app) as tc:
        response = tc.get("/api/status")
    assert response.status_code == 200

    raw = response.text
    assert "super-secret-anon-value" not in raw
    assert "ultra-secret-service-role" not in raw
    # URL should not appear either
    assert "secret-project" not in raw


def test_api_status_reports_true_when_supabase_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both env vars are set /api/status reflects configured=true."""
    monkeypatch.setenv("SUPABASE_URL", "https://myproject.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fake-service-role-key")

    from main import app  # noqa: PLC0415

    with TestClient(app) as tc:
        response = tc.get("/api/status")
    assert response.status_code == 200
    body = response.json()
    assert body["supabase_url_configured"] is True
    assert body["supabase_key_configured"] is True


# ---------------------------------------------------------------------------
# Live Supabase initialisation — only runs when valid config is present
# ---------------------------------------------------------------------------


@pytest.mark.requires_config
def test_supabase_client_initialises_when_configured(
    require_supabase_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Supabase client creation succeeds given valid URL and key env vars.

    Skipped unless SUPABASE_URL is set and non-placeholder.
    Does NOT insert, update, or delete any data.
    """
    # require_supabase_url fixture (from conftest) already validated the URL
    # We need at least one key to be present — if not, skip gracefully.
    key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY") or "").strip()
    if not key:
        pytest.skip("No Supabase key env var is set — cannot initialise client")

    from services.supabase_client import get_supabase_client, reset_client

    reset_client()
    client = get_supabase_client()
    assert client is not None
    # Subsequent calls should return the same singleton
    assert get_supabase_client() is client
