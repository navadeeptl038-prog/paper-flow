from __future__ import annotations

import pytest

from agents.document_agent import DocumentAgent, DocumentMatch
from models.document import DocumentResponse
from storage import document_repository, supabase_storage


@pytest.fixture
def document_agent() -> DocumentAgent:
    return DocumentAgent()


@pytest.fixture
def reset_document_state() -> None:
    document_repository._mem_documents.clear()
    supabase_storage._mem_storage_files.clear()


def _seed_document(owner_id: str, filename: str, *, status: str = "ready", file_type: str = "pdf") -> DocumentResponse:
    doc = DocumentResponse(
        id=f"doc-{owner_id}-{filename}",
        owner_id=owner_id,
        original_filename=filename,
        storage_path=f"{owner_id}/documents/{filename}",
        file_type=file_type,
        file_size_bytes=2048,
        processing_status=status,
        source="local_storage",
        metadata={"file_size_bytes": 2048, "mime_type": "application/pdf", "extension": ".pdf"},
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
    )
    document_repository._mem_documents.setdefault(owner_id, {})[doc.id] = dict(doc)
    return doc


def test_user_can_find_own_document(document_agent: DocumentAgent, reset_document_state: None) -> None:
    _seed_document("user-a", "passport.pdf")

    result = document_agent.search_documents(user_id="user-a", query="Find my passport")

    assert result.found is True
    assert len(result.documents) == 1
    assert result.documents[0].filename == "passport.pdf"
    assert result.documents[0].source == "local_storage"


def test_user_cannot_find_another_users_document(document_agent: DocumentAgent, reset_document_state: None) -> None:
    _seed_document("user-a", "passport.pdf")

    result = document_agent.search_documents(user_id="user-b", query="Find my passport")

    assert result.found is False
    assert result.documents == []


def test_user_cannot_view_another_users_document(document_agent: DocumentAgent, reset_document_state: None) -> None:
    doc = _seed_document("user-a", "passport.pdf")

    with pytest.raises(PermissionError):
        document_agent.get_document_access(document_id=doc.id, user_id="user-b")


def test_user_cannot_download_another_users_document(document_agent: DocumentAgent, reset_document_state: None) -> None:
    doc = _seed_document("user-a", "passport.pdf")

    with pytest.raises(PermissionError):
        document_agent.download_document(document_id=doc.id, user_id="user-b")


def test_unknown_document_returns_no_result(document_agent: DocumentAgent, reset_document_state: None) -> None:
    result = document_agent.search_documents(user_id="user-a", query="Find my secret alien file")

    assert result.found is False
    assert result.documents == []


def test_multiple_matching_documents_are_handled_safely(document_agent: DocumentAgent, reset_document_state: None) -> None:
    _seed_document("user-a", "passport.pdf")
    _seed_document("user-a", "passport_old.pdf")

    result = document_agent.search_documents(user_id="user-a", query="Find my passport")

    assert result.found is True
    assert len(result.documents) == 2
    assert {d.filename for d in result.documents} == {"passport.pdf", "passport_old.pdf"}


def test_processing_document_not_falsely_reported_as_ready(document_agent: DocumentAgent, reset_document_state: None) -> None:
    _seed_document("user-a", "passport.pdf", status="processing")

    result = document_agent.search_documents(user_id="user-a", query="Find my passport")

    assert result.found is False
    assert result.documents == []


def test_failed_document_not_falsely_reported_as_ready(document_agent: DocumentAgent, reset_document_state: None) -> None:
    _seed_document("user-a", "passport.pdf", status="failed")

    result = document_agent.search_documents(user_id="user-a", query="Find my passport")

    assert result.found is False
    assert result.documents == []


def test_private_storage_remains_private(document_agent: DocumentAgent, reset_document_state: None) -> None:
    doc = _seed_document("user-a", "passport.pdf")
    supabase_storage._mem_storage_files[doc.storage_path] = b"pdf-bytes"

    access = document_agent.get_document_access(document_id=doc.id, user_id="user-a")

    assert access is not None
    assert "http://" not in access["view_url"]
    assert "http://" not in access["download_url"]
    assert access["view_url"].startswith("/api/documents/")
    assert access["download_url"].startswith("/api/documents/")


def test_client_supplied_user_id_cannot_override_authenticated_identity(document_agent: DocumentAgent, reset_document_state: None) -> None:
    _seed_document("user-a", "passport.pdf")

    result = document_agent.search_documents(user_id="user-a", query="Find my passport", client_user_id="user-b")

    assert result.found is True
    assert result.documents[0].owner_id == "user-a"


def test_view_does_not_expose_permanent_public_storage_url(document_agent: DocumentAgent, reset_document_state: None) -> None:
    doc = _seed_document("user-a", "passport.pdf")
    supabase_storage._mem_storage_files[doc.storage_path] = b"pdf-bytes"

    access = document_agent.get_document_access(document_id=doc.id, user_id="user-a")

    assert access["view_url"].startswith("/api/documents/")
    assert "storage/v1/object/public" not in access["view_url"]


def test_download_returns_original_file_metadata_correctly(document_agent: DocumentAgent, reset_document_state: None) -> None:
    doc = _seed_document("user-a", "passport.pdf")
    supabase_storage._mem_storage_files[doc.storage_path] = b"secure-data"

    payload = document_agent.download_document(document_id=doc.id, user_id="user-a")

    assert payload["filename"] == "passport.pdf"
    assert payload["content_type"] == "application/pdf"
    assert payload["size_bytes"] == 11
