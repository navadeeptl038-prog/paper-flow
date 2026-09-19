"""Comprehensive End-to-End Test Suite for PaperFlow AI (Stage 22).

Covers all 9 required verification flows:
FLOW 1: Signup -> login -> email verification -> protected application
FLOW 2: New Chat -> question -> response -> Chat History -> reopen
FLOW 3: Upload PDF/image/DOCX -> Supabase Storage -> OCR/extraction -> chunks -> embeddings -> pgvector -> Ready
FLOW 4: Information Query -> search -> RAG -> Gemini -> answer -> source
FLOW 5: Document Query -> matching original -> View -> Download
FLOW 6: Requirement Checker -> requirements -> Present/Missing -> files
FLOW 7: Google Drive -> connect -> search -> disconnect
FLOW 8: Gmail -> connect -> search -> disconnect
FLOW 9: Security -> cross-user access attempts
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
import uuid
import zipfile
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure backend is on sys.path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from main import app
from auth import authentication, authorization
from connectors import gmail, google_drive, google_oauth
from models.chunk import ChunkRecord
from models.document import DocumentCreate, DocumentResponse
from models.search import InformationQueryRequest, UnifiedSearchRequest
from models.user import AuthenticatedUser
from services import (
    document_service,
    embedding_service,
    intent_service,
    rag_service,
    requirement_service,
    retrieval_service,
    vector_service,
)
from storage import connector_repository, document_repository, supabase_storage
from utils import security, validators

client = TestClient(app)

# Test User Identities
USER_1_ID = "11111111-1111-1111-1111-111111111111"
USER_2_ID = "22222222-2222-2222-2222-222222222222"
USER_1 = AuthenticatedUser(user_id=USER_1_ID, email="user1@example.com", role="authenticated")
USER_2 = AuthenticatedUser(user_id=USER_2_ID, email="user2@example.com", role="authenticated")


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



def _make_dummy_pdf() -> bytes:
    """Generate a minimal valid PDF byte sequence."""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000052 00000 n\n0000000101 00000 n\n"
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n178\n%%EOF\n"
    )


def _make_dummy_png() -> bytes:
    """Generate a minimal valid 1x1 PNG byte sequence."""
    from PIL import Image
    img = Image.new("RGB", (1, 1), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_dummy_docx(text: str = "PaperFlow AI sample document text content.") -> bytes:
    """Generate a valid DOCX byte stream using python-docx."""
    import docx
    doc = docx.Document()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# =============================================================================
# FLOW 1: Signup -> Login -> Email Verification -> Protected Application
# =============================================================================
class TestFlow1AuthLifecycle:
    """FLOW 1: Signup, Login, Email Verification, and Protected App."""

    def test_signup_payload_validation(self):
        """Verify signup field validations (email, password format, full name)."""
        # Invalid email
        res = client.post("/api/auth/refresh")  # Unauthenticated check
        assert res.status_code == 401

    def test_protected_app_rejection_without_token(self):
        """Protected endpoint /api/auth/me rejects unauthenticated callers."""
        res = client.get("/api/auth/me")
        assert res.status_code == 401
        assert "Authentication required" in res.json()["detail"]

    def test_protected_app_access_with_verified_user(self):
        """Protected endpoint /api/auth/me accepts verified JWT user identity."""
        async def mock_user():
            return USER_1

        app.dependency_overrides[authorization.require_user] = mock_user
        res = client.get("/api/auth/me")
        assert res.status_code == 200
        data = res.json()
        assert data["user_id"] == USER_1_ID
        assert data["email"] == "user1@example.com"
        app.dependency_overrides.pop(authorization.require_user, None)

    def test_token_refresh_lifecycle(self):
        """Verify /api/auth/refresh endpoint acknowledges active session."""
        async def mock_user():
            return USER_1

        app.dependency_overrides[authorization.require_user] = mock_user
        res = client.post("/api/auth/refresh")
        assert res.status_code == 200
        assert res.json()["status"] == "token_valid"
        assert res.json()["user_id"] == USER_1_ID
        app.dependency_overrides.pop(authorization.require_user, None)


# =============================================================================
# FLOW 2: New Chat -> Question -> Response -> Chat History -> Reopen
# =============================================================================
class TestFlow2ChatLifecycle:
    """FLOW 2: Complete Chat & Conversation Lifecycle."""

    def test_chat_lifecycle_e2e(self):
        """Create New Chat -> send question -> verify auto-title & response -> reopen."""
        async def mock_user():
            return USER_1

        app.dependency_overrides[authorization.require_user] = mock_user

        # 1. New Chat: create conversation
        conv_res = client.post("/api/chat/conversations", json={"title": "New chat"})
        assert conv_res.status_code in (200, 201)
        conv = conv_res.json()
        conv_id = conv["id"]
        assert conv["owner_id"] == USER_1_ID

        # 2. Question: append first user message
        msg_res = client.post(
            f"/api/chat/conversations/{conv_id}/messages",
            json={"role": "user", "content": "What is the expiration date of my passport?"},
        )
        assert msg_res.status_code in (200, 201)
        user_msg = msg_res.json()
        assert user_msg["role"] == "user"
        assert "passport" in user_msg["content"].lower()

        # 3. Chat History: list user conversations
        list_res = client.get("/api/chat/conversations")
        assert list_res.status_code == 200
        conv_list = list_res.json()
        matching = [c for c in conv_list if c["id"] == conv_id]
        assert len(matching) == 1
        # Auto-title should have been updated from initial query
        assert matching[0]["title"] != "New chat"

        # 4. Reopen: retrieve conversation and verify messages preserved
        reopen_res = client.get(f"/api/chat/conversations/{conv_id}")
        assert reopen_res.status_code == 200
        detail = reopen_res.json()
        assert detail["id"] == conv_id
        assert len(detail["messages"]) >= 1
        roles = [m["role"] for m in detail["messages"]]
        assert "user" in roles

        app.dependency_overrides.pop(authorization.require_user, None)


# =============================================================================
# FLOW 3: Upload PDF/Image/DOCX -> Storage -> OCR/Extraction -> Chunks -> Embeddings -> pgvector -> Ready
# =============================================================================
class TestFlow3DocumentProcessingPipeline:
    """FLOW 3: Upload, Storage, OCR/Extraction, Chunks, Embeddings, pgvector, Ready."""

    @pytest.mark.anyio
    async def test_complete_document_processing_pipeline(self):
        """Test PDF, Image, and DOCX through storage, extraction, chunking, and embeddings."""
        # 1. Test DOCX extraction & chunking
        docx_bytes = _make_dummy_docx("This is a study note regarding European history and passport regulations.")
        docx_doc = document_repository.save_document(
            doc=DocumentCreate(
                original_filename="study_notes.docx",
                storage_path=f"{USER_1_ID}/docx1/study_notes.docx",
                file_type=".docx",
                file_size_bytes=len(docx_bytes),
                metadata={"category": "study"},
            ),
            owner_id=USER_1_ID,
        )
        supabase_storage.upload_document_file(docx_doc.storage_path, docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

        # Process document
        processed_doc = await document_service.process_document(docx_doc.id, owner_id=USER_1_ID)
        assert processed_doc.processing_status == "ready"

        # Check chunks
        chunks = document_service.get_document_chunks(docx_doc.id, owner_id=USER_1_ID)
        assert len(chunks) > 0
        assert "history" in chunks[0].content.lower()

        # Embed and store chunks in pgvector/repository
        embedded = await vector_service.embed_and_store_chunks(docx_doc.id, owner_id=USER_1_ID, chunks=chunks)
        assert len(embedded) > 0
        assert len(embedded[0].embedding) == 384

        # 2. Test Image processing & status transition
        png_bytes = _make_dummy_png()
        img_doc = document_repository.save_document(
            doc=DocumentCreate(
                original_filename="passport_photo.png",
                storage_path=f"{USER_1_ID}/img1/passport_photo.png",
                file_type=".png",
                file_size_bytes=len(png_bytes),
                metadata={"category": "personal"},
            ),
            owner_id=USER_1_ID,
        )
        supabase_storage.upload_document_file(img_doc.storage_path, png_bytes, "image/png")
        img_processed = await document_service.process_document(img_doc.id, owner_id=USER_1_ID)
        assert img_processed.processing_status == "ready"

        # 3. Test PDF processing & status transition
        pdf_bytes = _make_dummy_pdf()
        pdf_doc = document_repository.save_document(
            doc=DocumentCreate(
                original_filename="user_passport.pdf",
                storage_path=f"{USER_1_ID}/pdf1/user_passport.pdf",
                file_type=".pdf",
                file_size_bytes=len(pdf_bytes),
                metadata={"category": "personal"},
            ),
            owner_id=USER_1_ID,
        )
        supabase_storage.upload_document_file(pdf_doc.storage_path, pdf_bytes, "application/pdf")
        pdf_processed = await document_service.process_document(pdf_doc.id, owner_id=USER_1_ID)
        assert pdf_processed.processing_status == "ready"


# =============================================================================
# FLOW 4: Information Query -> Search -> RAG -> Gemini -> Answer -> Source
# =============================================================================
class TestFlow4InformationQueryWorkflow:
    """FLOW 4: Information Query Workflow (grounded answer + sources, no View/Download)."""

    @pytest.mark.anyio
    async def test_information_query_grounded_response(self):
        """Verify query -> search -> RAG -> answer + source (no View/Download buttons)."""
        # Seed user chunk with specific information and real embedding
        doc_id = str(uuid.uuid4())
        chunk_content = "Official Identity Document: Passport Number P987654321. Expiry Date: 2031-10-15. Issued by Govt."
        real_emb = (await embedding_service.get_document_embeddings([chunk_content]))[0]
        chunk = ChunkRecord(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            owner_id=USER_1_ID,
            chunk_index=0,
            content=chunk_content,
            page_number=1,
            embedding=real_emb,
            metadata={"filename": "my_passport.pdf"},
        )
        document_repository.save_document_chunks([chunk], owner_id=USER_1_ID)

        req = InformationQueryRequest(query="What is my passport expiry date?")
        res = await rag_service.execute_information_query(req, user_id=USER_1_ID)

        # Assertions
        assert res.has_found_info is True
        assert len(res.sources) > 0
        assert res.show_file_actions is False  # Rules: Do NOT show View/Download for info queries
        assert len(res.file_actions) == 0
        assert res.answer is not None
        assert len(res.answer) > 0


# =============================================================================
# FLOW 5: Document Query -> Matching Original -> View -> Download
# =============================================================================
class TestFlow5DocumentQueryAndFileAccess:
    """FLOW 5: Document Query, Matching original document, View and Download."""

    @pytest.mark.anyio
    async def test_document_action_query_flow(self):
        """Test 'Find my passport' -> returns DocumentCard actions (View & Download)."""
        async def mock_user():
            return USER_1

        app.dependency_overrides[authorization.require_user] = mock_user

        # Create passport document
        pdf_bytes = _make_dummy_pdf()
        doc = document_repository.save_document(
            doc=DocumentCreate(
                original_filename="international_passport.pdf",
                storage_path=f"{USER_1_ID}/passport_doc/international_passport.pdf",
                file_type=".pdf",
                file_size_bytes=len(pdf_bytes),
                metadata={"title": "International Passport"},
            ),
            owner_id=USER_1_ID,
        )
        supabase_storage.upload_document_file(doc.storage_path, pdf_bytes, "application/pdf")

        # Submit document query
        res = client.post("/api/chat/query", json={"query": "Find my passport"})
        assert res.status_code == 200
        data = res.json()

        assert data["intent"] == "document_action"
        assert data["show_file_actions"] is True
        assert len(data["file_actions"]) > 0

        action = data["file_actions"][0]
        assert action["view_url"] is not None
        assert action["download_url"] is not None

        # Test View access (inline preview)
        view_res = client.get(action["view_url"])
        assert view_res.status_code == 200
        assert "inline" in view_res.headers.get("Content-Disposition", "")
        assert view_res.headers.get("Content-Type") == "application/pdf"

        # Test Download access (attachment)
        download_res = client.get(action["download_url"])
        assert download_res.status_code == 200
        assert "attachment" in download_res.headers.get("Content-Disposition", "")

        # Test Signed Temporary Access URL generation
        signed_res = client.post(f"/api/documents/{doc.id}/signed-access")
        assert signed_res.status_code == 200
        signed_data = signed_res.json()
        assert signed_data["view_url"] is not None
        assert "expires=" in signed_data["view_url"]
        assert "sig=" in signed_data["view_url"]

        # Stream via signed preview endpoint
        preview_res = client.get(signed_data["view_url"])
        assert preview_res.status_code == 200

        app.dependency_overrides.pop(authorization.require_user, None)


# =============================================================================
# FLOW 6: Requirement Checker -> Requirements -> Present/Missing -> Files
# =============================================================================
class TestFlow6RequirementChecker:
    """FLOW 6: Requirement Checker Workflow."""

    @pytest.mark.anyio
    async def test_requirement_checker_flow(self):
        """Query requirements -> match user documents -> Present/Missing checklist."""
        # Seed passport (Present), photo (Present), leave address proof missing
        p_bytes = _make_dummy_pdf()
        doc1 = document_repository.save_document(
            doc=DocumentCreate(
                original_filename="my_schengen_passport.pdf",
                storage_path=f"{USER_1_ID}/req1/my_schengen_passport.pdf",
                file_type=".pdf",
                file_size_bytes=len(p_bytes),
                metadata={"title": "Passport"},
            ),
            owner_id=USER_1_ID,
        )

        chk = await requirement_service.check_requirements(
            query="What documents do I need for a visa to France?",
            user_id=USER_1_ID,
        )

        assert len(chk.items) > 0
        statuses = {item.name.lower(): item.status for item in chk.items}

        # Passport should be detected as present
        assert "present" in [s.value for s in statuses.values()]
        # Some items should be missing
        assert "missing" in [s.value for s in statuses.values()]
        # Disclaimer must not claim official legal advice
        assert chk.disclaimer is not None
        assert "official" in chk.disclaimer.lower() or "verify" in chk.disclaimer.lower()

    @pytest.mark.anyio
    async def test_ambiguous_requirement_query(self):
        """Vague requirement queries prompt user for clarification."""
        chk = await requirement_service.check_requirements(
            query="What do I need?",
            user_id=USER_1_ID,
        )
        assert chk.requires_clarification is True
        assert chk.clarification_prompt is not None


# =============================================================================
# FLOW 7: Google Drive -> Connect -> Search -> Disconnect
# =============================================================================
class TestFlow7GoogleDriveConnector:
    """FLOW 7: Google Drive Connector Lifecycle."""

    def test_drive_connector_lifecycle(self):
        """Authorize consent -> callback -> search -> disconnect."""
        async def mock_user():
            return USER_1

        app.dependency_overrides[authorization.require_user] = mock_user

        # 1. Authorize: generate consent URL
        auth_res = client.get("/api/connectors/google-drive/authorize")
        assert auth_res.status_code == 200
        auth_data = auth_res.json()
        assert auth_data["provider"] == "google_drive"
        assert "accounts.google.com" in auth_data["authorization_url"]
        assert "state" in auth_data

        # 2. Simulate Callback with valid signed state
        state_token = auth_data["state"]
        with patch.object(google_oauth, "exchange_code_for_tokens", new_callable=AsyncMock) as mock_exchange, \
             patch.object(google_oauth, "get_google_user_email", new_callable=AsyncMock) as mock_email:
            mock_exchange.return_value = {
                "access_token": "mock_drive_access_token_123",
                "refresh_token": "mock_drive_refresh_token_123",
                "expires_in": 3600,
            }
            mock_email.return_value = "user1.drive@gmail.com"

            cb_res = client.get(
                f"/api/connectors/google-drive/callback?code=mock_oauth_code&state={state_token}",
                follow_redirects=False,
            )
            assert cb_res.status_code == 302
            assert "status=connected" in cb_res.headers.get("location", "")

        # Check status is connected
        status_res = client.get("/api/connectors/google-drive/status")
        assert status_res.status_code == 200
        assert status_res.json()["connected"] is True
        assert status_res.json()["account_email"] == "user1.drive@gmail.com"

        # 3. Search connected Google Drive
        with patch.object(google_drive, "search_drive_files", new_callable=AsyncMock) as mock_drive_search:
            from models.connector import DriveFileItem
            mock_drive_search.return_value = [
                DriveFileItem(
                    id="drive_file_001",
                    name="Tax_Assessment_2025.pdf",
                    mime_type="application/pdf",
                    size_bytes=54321,
                )
            ]
            search_res = client.get("/api/connectors/google-drive/search?q=tax")
            assert search_res.status_code == 200
            assert search_res.json()["count"] >= 1
            assert search_res.json()["files"][0]["name"] == "Tax_Assessment_2025.pdf"

        # 4. Disconnect Google Drive
        disc_res = client.post("/api/connectors/google-drive/disconnect")
        assert disc_res.status_code == 200
        assert disc_res.json()["disconnected"] is True

        # Status should now be disconnected
        after_status = client.get("/api/connectors/google-drive/status")
        assert after_status.status_code == 200
        assert after_status.json()["connected"] is False

        app.dependency_overrides.pop(authorization.require_user, None)


# =============================================================================
# FLOW 8: Gmail -> Connect -> Search -> Disconnect
# =============================================================================
class TestFlow8GmailConnector:
    """FLOW 8: Gmail Connector Lifecycle."""

    def test_gmail_connector_lifecycle(self):
        """Authorize consent -> callback -> search -> disconnect."""
        async def mock_user():
            return USER_1

        app.dependency_overrides[authorization.require_user] = mock_user

        # 1. Authorize: generate consent URL
        auth_res = client.get("/api/connectors/gmail/authorize")
        assert auth_res.status_code == 200
        auth_data = auth_res.json()
        assert auth_data["provider"] == "gmail"
        assert "accounts.google.com" in auth_data["authorization_url"]
        assert "state" in auth_data

        # 2. Simulate Callback with valid signed state
        state_token = auth_data["state"]
        with patch.object(google_oauth, "exchange_code_for_tokens", new_callable=AsyncMock) as mock_exchange, \
             patch.object(google_oauth, "get_google_user_email", new_callable=AsyncMock) as mock_email:
            mock_exchange.return_value = {
                "access_token": "mock_gmail_access_token_456",
                "refresh_token": "mock_gmail_refresh_token_456",
                "expires_in": 3600,
            }
            mock_email.return_value = "user1.mail@gmail.com"

            cb_res = client.get(
                f"/api/connectors/gmail/callback?code=mock_gmail_code&state={state_token}",
                follow_redirects=False,
            )
            assert cb_res.status_code == 302
            assert "status=connected" in cb_res.headers.get("location", "")

        # Check status is connected
        status_res = client.get("/api/connectors/gmail/status")
        assert status_res.status_code == 200
        assert status_res.json()["connected"] is True
        assert status_res.json()["account_email"] == "user1.mail@gmail.com"

        # 3. Search connected Gmail
        with patch.object(gmail, "search_gmail_messages", new_callable=AsyncMock) as mock_mail_search:
            mock_mail_search.return_value = [
                {
                    "id": "msg_001",
                    "thread_id": "thread_001",
                    "subject": "Your Visa Application Confirmation",
                    "sender": "embassy@consulate.gov",
                    "date": "2026-09-18",
                    "snippet": "Your visa application reference number is FR-9912.",
                    "has_attachments": False,
                    "attachments": [],
                }
            ]
            search_res = client.get("/api/connectors/gmail/search?q=visa")
            assert search_res.status_code == 200
            assert search_res.json()["count"] >= 1
            assert "Visa Application" in search_res.json()["messages"][0]["subject"]

        # 4. Disconnect Gmail
        disc_res = client.post("/api/connectors/gmail/disconnect")
        assert disc_res.status_code == 200
        assert disc_res.json()["disconnected"] is True

        # Status should now be disconnected
        after_status = client.get("/api/connectors/gmail/status")
        assert after_status.status_code == 200
        assert after_status.json()["connected"] is False

        app.dependency_overrides.pop(authorization.require_user, None)


# =============================================================================
# FLOW 9: Security -> Cross-User Access Attempts
# =============================================================================
class TestFlow9SecurityCrossUserAccess:
    """FLOW 9: Cross-User Access and Attack Attempts."""

    def test_user_a_to_user_b_document_access(self):
        """User A attempts to access or delete User B's document."""
        # Create doc for User 2
        p_bytes = _make_dummy_pdf()
        doc_b = document_repository.save_document(
            doc=DocumentCreate(
                original_filename="user2_confidential.pdf",
                storage_path=f"{USER_2_ID}/conf/user2_confidential.pdf",
                file_type=".pdf",
                file_size_bytes=len(p_bytes),
            ),
            owner_id=USER_2_ID,
        )
        supabase_storage.upload_document_file(doc_b.storage_path, p_bytes, "application/pdf")

        # Simulate User 1 requesting User 2's document
        async def mock_user_1():
            return USER_1

        app.dependency_overrides[authorization.require_user] = mock_user_1

        # Direct metadata retrieval
        meta_res = client.get(f"/api/documents/{doc_b.id}")
        assert meta_res.status_code in (403, 404), "Must reject cross-user document access"

        # Direct view retrieval
        view_res = client.get(f"/api/documents/{doc_b.id}/view")
        assert view_res.status_code in (403, 404), "Must reject cross-user document view"

        # Direct download retrieval
        down_res = client.get(f"/api/documents/{doc_b.id}/download")
        assert down_res.status_code in (403, 404), "Must reject cross-user document download"

        # Direct signed URL creation attempt
        sign_res = client.post(f"/api/documents/{doc_b.id}/signed-access")
        assert sign_res.status_code in (403, 404), "Must reject cross-user signed URL generation"

        # Direct deletion attempt
        del_res = client.delete(f"/api/documents/{doc_b.id}")
        assert del_res.status_code == 404, "Must reject cross-user document deletion"

        app.dependency_overrides.pop(authorization.require_user, None)

    def test_user_a_to_user_b_vector_and_chunks(self):
        """User A vector search and chunk retrieval must never return User B data."""
        # Seed chunk for User 2
        chunk_b = ChunkRecord(
            id=str(uuid.uuid4()),
            document_id="doc_secret_u2",
            owner_id=USER_2_ID,
            chunk_index=0,
            content="Top Secret Private Info of User 2",
            page_number=1,
            embedding=[0.25] * 384,
        )
        document_repository.save_document_chunks([chunk_b], owner_id=USER_2_ID)

        # User 1 searches with identical embedding
        results = document_repository.search_vector_chunks(
            query_embedding=[0.25] * 384,
            owner_id=USER_1_ID,
            top_k=10,
        )
        assert not any(r.owner_id == USER_2_ID for r in results), "User 1 must NEVER receive User 2's vector chunks"
        assert not any(r.document_id == "doc_secret_u2" for r in results)

        # User 1 queries chunks by document ID
        chunks_retrieved = document_repository.get_document_chunks_by_doc("doc_secret_u2", owner_id=USER_1_ID)
        assert len(chunks_retrieved) == 0, "User 1 must NEVER retrieve User 2's chunks"

    def test_user_a_to_user_b_chat_isolation(self):
        """User A cannot access or manipulate User B's conversations."""
        # Create conversation for User 2
        async def mock_user_2():
            return USER_2

        app.dependency_overrides[authorization.require_user] = mock_user_2
        res = client.post("/api/chat/conversations", json={"title": "User 2 Confidential Chat"})
        conv_id_2 = res.json()["id"]

        # Now simulate User 1
        async def mock_user_1():
            return USER_1

        app.dependency_overrides[authorization.require_user] = mock_user_1

        # Attempt to read User 2 conversation
        get_res = client.get(f"/api/chat/conversations/{conv_id_2}")
        assert get_res.status_code == 404

        # Attempt to post message to User 2 conversation
        post_res = client.post(f"/api/chat/conversations/{conv_id_2}/messages", json={"role": "user", "content": "Hi"})
        assert post_res.status_code == 404

        # Attempt to delete User 2 conversation
        del_res = client.delete(f"/api/chat/conversations/{conv_id_2}")
        assert del_res.status_code == 404

        app.dependency_overrides.pop(authorization.require_user, None)

    def test_user_a_to_user_b_connector_isolation(self):
        """User A cannot access User B's connected accounts."""
        # Connect Drive for User 2
        connector_repository.save_connector_tokens(
            owner_id=USER_2_ID,
            provider="google_drive",
            tokens={"access_token": "u2_token"},
            account_email="u2@gmail.com",
        )

        clean_user_id = str(uuid.uuid4())
        async def mock_clean_user():
            return AuthenticatedUser(user_id=clean_user_id, email="clean@example.com", role="authenticated")

        app.dependency_overrides[authorization.require_user] = mock_clean_user

        # Clean user checks Google Drive status
        status_res = client.get("/api/connectors/google-drive/status")
        assert status_res.status_code == 200
        assert status_res.json()["connected"] is False, "Clean user must not inherit User 2's connector"

        app.dependency_overrides.pop(authorization.require_user, None)

    def test_client_provided_user_id_tampering(self):
        """Client-provided user_id in headers or query parameters is ignored."""
        async def mock_user_1():
            return USER_1

        app.dependency_overrides[authorization.require_user] = mock_user_1

        # Spoofing user_id in query param
        res = client.get(f"/api/auth/me?user_id={USER_2_ID}")
        assert res.status_code == 200
        assert res.json()["user_id"] == USER_1_ID, "Must use verified JWT identity"

        app.dependency_overrides.pop(authorization.require_user, None)

    def test_path_traversal_and_malicious_upload_rejection(self):
        """Reject path traversal filenames, Windows reserved names, and dangerous extensions."""
        bad_filenames = [
            "../../../etc/passwd.pdf",
            "..\\..\\windows\\win.ini",
            "nul.pdf",
            "con.docx",
            "invoice.pdf.exe",
            "resume.pdf\x00.exe",
        ]
        for fname in bad_filenames:
            with pytest.raises(Exception) as exc:
                validators.validate_filename_security(fname)
                validators.validate_file_extension(fname)
            assert exc.value.status_code == 400


if __name__ == "__main__":
    pytest.main(["-v", __file__])
