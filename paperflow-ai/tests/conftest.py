"""Shared fixtures for PaperFlow AI tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"

if str(BACKEND) not in sys.path:
	sys.path.insert(0, str(BACKEND))


@pytest.fixture(scope="session")
def project_root() -> Path:
	return ROOT


@pytest.fixture(scope="session")
def backend_root() -> Path:
	return BACKEND


@pytest.fixture()
def client() -> TestClient:
	"""In-process FastAPI client — no network and no production secrets required."""
	# Ensure CORS defaults are deterministic for foundation tests.
	os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
	os.environ.setdefault("APP_NAME", "PaperFlow AI")
	os.environ.setdefault("APP_VERSION", "0.1.0")

	from main import app

	with TestClient(app) as test_client:
		yield test_client


@pytest.fixture()
def require_supabase_url() -> str:
	value = (os.getenv("SUPABASE_URL") or "").strip()
	if not value:
		pytest.skip("SUPABASE_URL is not configured — cannot run live Supabase checks")
	if "example" in value.lower() or value.endswith(".invalid"):
		pytest.skip("SUPABASE_URL looks like a placeholder — refusing live call")
	return value
