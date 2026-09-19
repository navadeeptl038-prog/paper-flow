"""Shared fixtures for PaperFlow AI tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"

load_dotenv(BACKEND / ".env", override=False)
load_dotenv(ROOT / ".env", override=False)

if str(BACKEND) not in sys.path:
	sys.path.insert(0, str(BACKEND))


@pytest.fixture(scope="session")
def project_root() -> Path:
	return ROOT


@pytest.fixture(scope="session")
def backend_root() -> Path:
	return BACKEND


def _live_supabase_ready() -> bool:
	"""Return True only when a real backend Supabase configuration is available."""
	url = (os.getenv("SUPABASE_URL") or "").strip()
	anon = (os.getenv("SUPABASE_ANON_KEY") or "").strip()
	service = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
	bucket = (os.getenv("SUPABASE_STORAGE_BUCKET") or "").strip()
	return bool(url and (anon or service) and bucket == "paperflow-documents")


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
		pytest.skip("NOT VERIFIED — requires Supabase configuration.")
	if not _live_supabase_ready():
		pytest.skip("NOT VERIFIED — configured Supabase environment is incomplete.")
	if "example" in value.lower() or value.endswith(".invalid"):
		pytest.skip("NOT VERIFIED — placeholder Supabase URL detected.")
	return value


@pytest.fixture(autouse=True)
def ensure_test_ocr():
	"""Ensure OCR operations succeed in test environments when system Tesseract binary is absent."""
	from document_processing import ocr
	if not ocr.is_ocr_available():
		ocr.set_test_ocr_handler(lambda img: "Passport Photo Identification")
		yield
		ocr.set_test_ocr_handler(None)
	else:
		yield

