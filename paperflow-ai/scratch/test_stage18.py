"""Comprehensive test suite for Stage 18: Google Drive Connector.

Validates:
1. Google OAuth authorization URL generation with minimum required scopes
2. Code exchange and user account association
3. Token secrecy (access and refresh tokens NEVER exposed in public API models)
4. Drive file search with metadata mapping
5. Expired token automatic refresh
6. Revoked access handling (invalid_grant -> status: revoked)
7. Disconnect endpoint (token revocation & record deletion)
8. User isolation (user B cannot access user A's Drive)
9. Error handling (rate limits, quota, unconfigured OAuth)
"""

import asyncio
import datetime
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure backend directory is in sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
if os.getcwd() not in sys.path:
    sys.path.insert(0, os.getcwd())

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.authorization import require_user
from connectors import google_drive, google_oauth
from connectors.google_drive import GoogleDriveAPIError
from connectors.google_oauth import TokenRevokedError
from models.connector import (
    ConnectAuthorizeResponse,
    ConnectorStatusResponse,
    DriveFileItem,
    DriveSearchResponse,
)
from models.user import AuthenticatedUser
from routes.connectors import router as connectors_router
from storage import connector_repository


# Setup test FastAPI application with mocked authentication
app = FastAPI()
app.include_router(connectors_router)

# Simulated authenticated users
USER_A = AuthenticatedUser(user_id="11111111-1111-1111-1111-111111111111", email="alice@example.com")
USER_B = AuthenticatedUser(user_id="22222222-2222-2222-2222-222222222222", email="bob@example.com")

current_user = USER_A


async def override_require_user():
    return current_user


app.dependency_overrides[require_user] = override_require_user
client = TestClient(app)


class TestStage18GoogleDriveConnector(unittest.TestCase):
    def setUp(self):
        global current_user
        current_user = USER_A
        # Reset in-memory connectors
        connector_repository._mem_connectors.clear()
        # Set dummy OAuth credentials for test environment
        os.environ["GOOGLE_CLIENT_ID"] = "test-client-id.apps.googleusercontent.com"
        os.environ["GOOGLE_CLIENT_SECRET"] = "test-client-secret-12345"
        os.environ["GOOGLE_REDIRECT_URI"] = "http://localhost:8000/api/connectors/google-drive/callback"

    def test_01_minimum_required_scopes(self):
        """Verify only minimum required read-only scopes are requested."""
        scopes = google_oauth.GOOGLE_DRIVE_SCOPES
        self.assertIn("https://www.googleapis.com/auth/drive.readonly", scopes)
        self.assertIn("https://www.googleapis.com/auth/userinfo.email", scopes)
        # Verify no full drive write/delete scopes are requested
        for s in scopes:
            self.assertNotIn("https://www.googleapis.com/auth/drive.file", s)
            self.assertNotEqual("https://www.googleapis.com/auth/drive", s)

    def test_02_authorization_url_generation(self):
        """Verify OAuth authorization URL has offline access, consent prompt, and valid state."""
        auth_url = google_oauth.get_authorization_url(state="user-a:csrf-token-xyz")
        self.assertIn("https://accounts.google.com/o/oauth2/v2/auth", auth_url)
        self.assertIn("client_id=test-client-id.apps.googleusercontent.com", auth_url)
        self.assertIn("access_type=offline", auth_url)
        self.assertIn("prompt=consent", auth_url)
        self.assertIn("state=user-a%3Acsrf-token-xyz", auth_url)
        self.assertIn("drive.readonly", auth_url)

    def test_03_authorize_endpoint(self):
        """Verify GET /api/connectors/google-drive/authorize generates authorization URL."""
        res = client.get("/api/connectors/google-drive/authorize")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["provider"], "google_drive")
        self.assertIn("https://accounts.google.com/o/oauth2/v2/auth", data["authorization_url"])
        self.assertTrue(data["state"].startswith(USER_A.user_id))

    def test_04_token_secrecy_in_status_endpoints(self):
        """Tokens and secrets must NEVER be exposed to frontend in status responses."""
        connector_repository.save_connector_tokens(
            owner_id=USER_A.user_id,
            provider="google_drive",
            tokens={
                "access_token": "secret_access_token_abc123",
                "refresh_token": "super_secret_refresh_token_xyz789",
                "expires_in": 3600,
            },
            account_email="alice.drive@gmail.com",
            scopes=google_oauth.GOOGLE_DRIVE_SCOPES,
        )

        # Test single status
        res = client.get("/api/connectors/google-drive/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["provider"], "google_drive")
        self.assertTrue(data["connected"])
        self.assertEqual(data["account_email"], "alice.drive@gmail.com")
        self.assertEqual(data["status"], "connected")
        # Ensure tokens are completely absent from response
        self.assertNotIn("access_token", data)
        self.assertNotIn("refresh_token", data)
        self.assertNotIn("secret_access_token_abc123", str(data))
        self.assertNotIn("super_secret_refresh_token_xyz789", str(data))

        # Test list status
        res_list = client.get("/api/connectors/status")
        self.assertEqual(res_list.status_code, 200)
        list_data = res_list.json()
        drive_item = next((c for c in list_data if c["provider"] == "google_drive"), None)
        self.assertIsNotNone(drive_item)
        self.assertTrue(drive_item["connected"])
        self.assertNotIn("access_token", drive_item)
        self.assertNotIn("refresh_token", drive_item)

    @patch("connectors.google_drive.search_drive_files")
    @patch("connectors.google_drive.get_valid_access_token")
    def test_05_drive_search_endpoint(self, mock_get_token, mock_search):
        """Verify search endpoint returns formatted Drive items."""
        mock_get_token.return_value = "valid_token_123"
        mock_search.return_value = [
            DriveFileItem(
                id="file-101",
                name="Passport_Scan.pdf",
                mime_type="application/pdf",
                size_bytes=1048576,
                modified_at="2026-05-10T12:00:00Z",
                view_url="https://drive.google.com/file/d/file-101/view",
                download_url="https://drive.google.com/uc?id=file-101&export=download",
                source="Google Drive",
            )
        ]

        res = client.get("/api/connectors/google-drive/search?q=Passport")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["provider"], "google_drive")
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["files"][0]["name"], "Passport_Scan.pdf")
        self.assertEqual(data["files"][0]["source"], "Google Drive")

    def test_06_expired_token_automatic_refresh(self):
        """Expired access token triggers automatic refresh via refresh_token."""
        async def run_test():
            now = datetime.datetime.now(datetime.timezone.utc)
            past = (now - datetime.timedelta(minutes=10)).isoformat()

            connector_repository.save_connector_tokens(
                owner_id=USER_A.user_id,
                provider="google_drive",
                tokens={
                    "access_token": "expired_token_111",
                    "refresh_token": "valid_refresh_token_222",
                    "expires_at": past,
                },
            )

            with patch("connectors.google_oauth.refresh_access_token") as mock_refresh:
                mock_refresh.return_value = {
                    "access_token": "fresh_access_token_333",
                    "expires_in": 3600,
                }

                valid_token = await google_drive.get_valid_access_token(USER_A.user_id)
                self.assertEqual(valid_token, "fresh_access_token_333")
                mock_refresh.assert_called_once_with("valid_refresh_token_222")

                # Check that storage was updated
                stored = connector_repository.get_connector(USER_A.user_id, "google_drive")
                self.assertEqual(stored["access_token"], "fresh_access_token_333")
                self.assertEqual(stored["status"], "connected")

        asyncio.run(run_test())

    def test_07_revoked_token_handling(self):
        """Revoked access transitions connector status to 'revoked' and raises TokenRevokedError."""
        async def run_test():
            now = datetime.datetime.now(datetime.timezone.utc)
            past = (now - datetime.timedelta(minutes=10)).isoformat()

            connector_repository.save_connector_tokens(
                owner_id=USER_A.user_id,
                provider="google_drive",
                tokens={
                    "access_token": "expired_token_111",
                    "refresh_token": "revoked_refresh_token_999",
                    "expires_at": past,
                },
            )

            with patch("connectors.google_oauth.refresh_access_token") as mock_refresh:
                mock_refresh.side_effect = TokenRevokedError("Access was revoked by user")

                with self.assertRaises(TokenRevokedError):
                    await google_drive.get_valid_access_token(USER_A.user_id)

                # Stored status must transition to 'revoked'
                stored = connector_repository.get_connector(USER_A.user_id, "google_drive")
                self.assertEqual(stored["status"], "revoked")

        asyncio.run(run_test())

    @patch("connectors.google_oauth.revoke_token")
    def test_08_disconnect_flow(self, mock_revoke):
        """Disconnect calls Google revocation endpoint and deletes stored credentials."""
        mock_revoke.return_value = True

        connector_repository.save_connector_tokens(
            owner_id=USER_A.user_id,
            provider="google_drive",
            tokens={
                "access_token": "token_to_disconnect",
                "refresh_token": "refresh_to_disconnect",
                "expires_in": 3600,
            },
            account_email="alice@gmail.com",
        )

        res = client.post("/api/connectors/google-drive/disconnect")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["disconnected"])
        mock_revoke.assert_called_once_with("refresh_to_disconnect")

        # Verify status is now not connected
        status_res = client.get("/api/connectors/google-drive/status")
        self.assertFalse(status_res.json()["connected"])

    def test_09_user_isolation(self):
        """User B cannot access or view User A's connected Google Drive."""
        global current_user

        # Connect User A
        connector_repository.save_connector_tokens(
            owner_id=USER_A.user_id,
            provider="google_drive",
            tokens={"access_token": "alice_token", "expires_in": 3600},
            account_email="alice@gmail.com",
        )

        # Switch context to User B
        current_user = USER_B

        # User B should see Google Drive as not connected
        res = client.get("/api/connectors/google-drive/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["connected"])
        self.assertIsNone(data["account_email"])

        # User B attempting to search Drive gets 400 error
        search_res = client.get("/api/connectors/google-drive/search?q=test")
        self.assertEqual(search_res.status_code, 400)
        self.assertIn("not connected", search_res.json()["detail"])

    @patch("connectors.google_oauth.get_google_user_email")
    @patch("connectors.google_oauth.exchange_code_for_tokens")
    def test_10_oauth_callback_flow(self, mock_exchange, mock_email):
        """Callback exchanges authorization code and saves connector under authenticated user."""
        mock_exchange.return_value = {
            "access_token": "cb_access_123",
            "refresh_token": "cb_refresh_456",
            "expires_in": 3600,
        }
        mock_email.return_value = "newuser@gmail.com"

        # Register active state
        from routes.connectors import _oauth_states
        state_key = f"{USER_A.user_id}:random_csrf_secret"
        _oauth_states[state_key] = USER_A.user_id

        res = client.get(
            f"/api/connectors/google-drive/callback?code=valid_auth_code&state={state_key}",
            follow_redirects=False,
        )
        self.assertEqual(res.status_code, 302)
        self.assertIn("/connectors?status=connected", res.headers["location"])

        # Check that connector was stored for User A
        conn = connector_repository.get_connector(USER_A.user_id, "google_drive")
        self.assertIsNotNone(conn)
        self.assertEqual(conn["account_email"], "newuser@gmail.com")
        self.assertEqual(conn["status"], "connected")

    def test_11_unconfigured_oauth_error(self):
        """Authorize endpoint returns 503 if Google credentials are missing."""
        with patch("connectors.google_oauth.is_google_oauth_configured", return_value=False):
            res = client.get("/api/connectors/google-drive/authorize")
            self.assertEqual(res.status_code, 503)
            self.assertIn("not configured", res.json()["detail"])

    @patch("connectors.google_drive.get_valid_access_token")
    def test_12_revoked_token_during_search_returns_401(self, mock_token):
        """TokenRevokedError during search returns 401 Unauthorized instructing reconnection."""
        mock_token.side_effect = TokenRevokedError("Token revoked")
        res = client.get("/api/connectors/google-drive/search?q=invoices")
        self.assertEqual(res.status_code, 401)
        self.assertIn("revoked or expired", res.json()["detail"])

    @patch("connectors.google_drive.get_valid_access_token")
    def test_13_drive_api_error_handling(self, mock_token):
        """GoogleDriveAPIError returns 400 with descriptive error detail."""
        mock_token.side_effect = GoogleDriveAPIError("Rate limit exceeded")
        res = client.get("/api/connectors/google-drive/search?q=notes")
        self.assertEqual(res.status_code, 400)
        self.assertIn("Rate limit exceeded", res.json()["detail"])


if __name__ == "__main__":
    unittest.main()

