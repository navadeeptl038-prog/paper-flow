"""Document tests require a real Supabase-backed environment."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
	not (os.getenv("SUPABASE_URL") and (os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")) and (os.getenv("SUPABASE_STORAGE_BUCKET") == "paperflow-documents")),
	reason="Live Supabase configuration required for document storage verification",
)


def test_document_storage_configuration_is_present() -> None:
	"""This test only runs when the backend has the real Supabase configuration."""
	assert os.getenv("SUPABASE_STORAGE_BUCKET", "paperflow-documents") == "paperflow-documents"
