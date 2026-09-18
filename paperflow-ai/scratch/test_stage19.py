"""Comprehensive test suite for Stage 19: Gmail Connector.

Validates:
1. Gmail OAuth scopes (gmail.readonly, userinfo.email — no send/delete/modify)
2. Gmail authorization URL generation with correct scopes and redirect
3. Gmail authorize endpoint
4. Token secrecy in status endpoints (tokens never exposed)
5. Gmail search endpoint with metadata and attachment extraction
6. Expired token automatic refresh
7. Revoked token handling (status transitions to 'revoked')
8. Disconnect endpoint (token revocation and record deletion)
9. User isolation (User B cannot access User A's Gmail)
10. OAuth callback flow (code exchange, email association)
11. Unconfigured OAuth error (503)
12. Revoked token during search returns 401
13. Gmail API error handling (rate limits, quota)
14. No-results case
15. Stage 18 Drive regression (Drive endpoints still work)
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
from connectors import gmail, google_drive, google_oauth
from connectors.gmail import GmailAPIError
from connectors.google_drive import GoogleDriveAPIError
from connectors.google_oauth import TokenRevokedError
from models.connector import (
    ConnectAuthorizeResponse,
    ConnectorStatusResponse,
    DriveFileItem,
    GmailAttachmentItem,
    GmailMessageItem,
    GmailSearchResponse,
)
from models.user import AuthenticatedUser
from routes.connectors import router as connectors_router
from storage import connector_repository


# Setup test FastAPI app
app = FastAPI()
app.include_router(connectors_router)

USER_A = AuthenticatedUser(user_id="11111111-1111-1111-1111-111111111111", email="alice@example.com")
USER_B = AuthenticatedUser(user_id="22222222-2222-2222-2222-222222222222", email="bob@example.com")

current_user = USER_A


async def override_require_user():
    return current_user


app.dependency_overrides[require_user] = override_require_user
client = TestClient(app)


class TestStage19GmailConnector(unittest.TestCase):
    def setUp(self):
        global current_user
        current_user = USER_A
        connector_repository._mem_connectors.clear()
        os.environ["GOOGLE_CLIENT_ID"] = "test-client-id.apps.googleusercontent.com"
        os.environ["GOOGLE_CLIENT_SECRET"] = "test-client-secret-12345"
        os.environ["GOOGLE_REDIRECT_URI"] = "http://localhost:8000/api/connectors/google-drive/callback"
        os.environ["GMAIL_REDIRECT_URI"] = "http://localhost:8000/api/connectors/gmail/callback"

    # -----------------------------------------------------------------------
    # 1. Scopes
    # -----------------------------------------------------------------------
    def test_01_gmail_scopes_are_read_only(self):
        """Gmail uses gmail.readonly — no send, delete, or modify scopes."""
        scopes = google_oauth.GMAIL_SCOPES
        self.assertIn("https://www.googleapis.com/auth/gmail.readonly", scopes)
        self.assertIn("https://www.googleapis.com/auth/userinfo.email", scopes)
        # Ensure no write scopes
        for s in scopes:
            self.assertNotIn("gmail.send", s)
            self.assertNotIn("gmail.modify", s)
            self.assertNotIn("gmail.compose", s)
            self.assertNotIn("gmail.insert", s)
            self.assertNotIn("mail.google.com", s)

    # -----------------------------------------------------------------------
    # 2. Authorization URL
    # -----------------------------------------------------------------------
    def test_02_gmail_authorization_url_generation(self):
        """Gmail auth URL uses gmail.readonly scope and correct redirect URI."""
        auth_url = google_oauth.get_authorization_url_for_provider(
            state="user-a:csrf-gmail",
            scopes=google_oauth.GMAIL_SCOPES,
            redirect_uri=google_oauth.get_gmail_redirect_uri(),
        )
        self.assertIn("https://accounts.google.com/o/oauth2/v2/auth", auth_url)
        self.assertIn("gmail.readonly", auth_url)
        self.assertIn("gmail%2Fcallback", auth_url)
        self.assertIn("access_type=offline", auth_url)
        self.assertIn("prompt=consent", auth_url)

    # -----------------------------------------------------------------------
    # 3. Authorize endpoint
    # -----------------------------------------------------------------------
    def test_03_gmail_authorize_endpoint(self):
        """GET /api/connectors/gmail/authorize returns valid consent URL."""
        res = client.get("/api/connectors/gmail/authorize")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["provider"], "gmail")
        self.assertIn("https://accounts.google.com/o/oauth2/v2/auth", data["authorization_url"])
        self.assertIn("gmail.readonly", data["authorization_url"])
        self.assertTrue(data["state"].startswith(USER_A.user_id))

    # -----------------------------------------------------------------------
    # 4. Token secrecy
    # -----------------------------------------------------------------------
    def test_04_token_secrecy_in_gmail_status(self):
        """Tokens must NEVER appear in Gmail status or list responses."""
        connector_repository.save_connector_tokens(
            owner_id=USER_A.user_id,
            provider="gmail",
            tokens={
                "access_token": "gmail_secret_access_abc",
                "refresh_token": "gmail_secret_refresh_xyz",
                "expires_in": 3600,
            },
            account_email="alice.gmail@gmail.com",
            scopes=google_oauth.GMAIL_SCOPES,
        )

        # Single status
        res = client.get("/api/connectors/gmail/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["provider"], "gmail")
        self.assertTrue(data["connected"])
        self.assertEqual(data["account_email"], "alice.gmail@gmail.com")
        self.assertNotIn("access_token", data)
        self.assertNotIn("refresh_token", data)
        self.assertNotIn("gmail_secret_access_abc", str(data))

        # List status
        res_list = client.get("/api/connectors/status")
        list_data = res_list.json()
        gmail_item = next((c for c in list_data if c["provider"] == "gmail"), None)
        self.assertIsNotNone(gmail_item)
        self.assertTrue(gmail_item["connected"])
        self.assertNotIn("access_token", gmail_item)
        self.assertNotIn("refresh_token", gmail_item)

    # -----------------------------------------------------------------------
    # 5. Search endpoint with metadata
    # -----------------------------------------------------------------------
    @patch("connectors.gmail.search_gmail_messages")
    @patch("connectors.gmail.get_valid_access_token")
    def test_05_gmail_search_endpoint(self, mock_get_token, mock_search):
        """Search returns structured GmailMessageItem with attachment info."""
        mock_get_token.return_value = "valid_gmail_token"
        mock_search.return_value = [
            GmailMessageItem(
                id="msg-001",
                thread_id="thread-001",
                subject="Flight Booking Confirmation",
                sender="airline@example.com",
                to="alice@example.com",
                date="Mon, 15 Sep 2026 10:30:00 +0530",
                snippet="Your flight to Delhi is confirmed...",
                labels=["INBOX", "CATEGORY_UPDATES"],
                has_attachments=True,
                attachments=[
                    GmailAttachmentItem(
                        filename="boarding_pass.pdf",
                        mime_type="application/pdf",
                        size_bytes=45000,
                        attachment_id="att-001",
                    )
                ],
                source="Gmail",
            ),
        ]

        res = client.get("/api/connectors/gmail/search?q=flight+booking")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["provider"], "gmail")
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["messages"][0]["subject"], "Flight Booking Confirmation")
        self.assertTrue(data["messages"][0]["has_attachments"])
        self.assertEqual(data["messages"][0]["attachments"][0]["filename"], "boarding_pass.pdf")

    # -----------------------------------------------------------------------
    # 6. Expired token refresh
    # -----------------------------------------------------------------------
    def test_06_gmail_expired_token_auto_refresh(self):
        """Expired Gmail token triggers automatic refresh."""
        async def run_test():
            now = datetime.datetime.now(datetime.timezone.utc)
            past = (now - datetime.timedelta(minutes=10)).isoformat()

            connector_repository.save_connector_tokens(
                owner_id=USER_A.user_id,
                provider="gmail",
                tokens={
                    "access_token": "expired_gmail_111",
                    "refresh_token": "valid_gmail_refresh_222",
                    "expires_at": past,
                },
            )

            with patch("connectors.google_oauth.refresh_access_token") as mock_refresh:
                mock_refresh.return_value = {
                    "access_token": "fresh_gmail_333",
                    "expires_in": 3600,
                }
                valid_token = await gmail.get_valid_access_token(USER_A.user_id)
                self.assertEqual(valid_token, "fresh_gmail_333")
                mock_refresh.assert_called_once_with("valid_gmail_refresh_222")

                stored = connector_repository.get_connector(USER_A.user_id, "gmail")
                self.assertEqual(stored["access_token"], "fresh_gmail_333")
                self.assertEqual(stored["status"], "connected")

        asyncio.run(run_test())

    # -----------------------------------------------------------------------
    # 7. Revoked token handling
    # -----------------------------------------------------------------------
    def test_07_gmail_revoked_token_handling(self):
        """Revoked Gmail access transitions status to 'revoked' and raises TokenRevokedError."""
        async def run_test():
            now = datetime.datetime.now(datetime.timezone.utc)
            past = (now - datetime.timedelta(minutes=10)).isoformat()

            connector_repository.save_connector_tokens(
                owner_id=USER_A.user_id,
                provider="gmail",
                tokens={
                    "access_token": "expired_111",
                    "refresh_token": "revoked_refresh_999",
                    "expires_at": past,
                },
            )

            with patch("connectors.google_oauth.refresh_access_token") as mock_refresh:
                mock_refresh.side_effect = TokenRevokedError("Gmail access was revoked")

                with self.assertRaises(TokenRevokedError):
                    await gmail.get_valid_access_token(USER_A.user_id)

                stored = connector_repository.get_connector(USER_A.user_id, "gmail")
                self.assertEqual(stored["status"], "revoked")

        asyncio.run(run_test())

    # -----------------------------------------------------------------------
    # 8. Disconnect
    # -----------------------------------------------------------------------
    @patch("connectors.google_oauth.revoke_token")
    def test_08_gmail_disconnect_flow(self, mock_revoke):
        """Disconnect revokes Gmail tokens and deletes connector records."""
        mock_revoke.return_value = True

        connector_repository.save_connector_tokens(
            owner_id=USER_A.user_id,
            provider="gmail",
            tokens={
                "access_token": "token_to_disconnect",
                "refresh_token": "refresh_to_disconnect",
                "expires_in": 3600,
            },
            account_email="alice@gmail.com",
        )

        res = client.post("/api/connectors/gmail/disconnect")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["disconnected"])
        self.assertEqual(data["provider"], "gmail")
        mock_revoke.assert_called_once_with("refresh_to_disconnect")

        # Verify status is now not connected
        status_res = client.get("/api/connectors/gmail/status")
        self.assertFalse(status_res.json()["connected"])

    # -----------------------------------------------------------------------
    # 9. User isolation
    # -----------------------------------------------------------------------
    def test_09_gmail_user_isolation(self):
        """User B cannot access User A's connected Gmail."""
        global current_user

        connector_repository.save_connector_tokens(
            owner_id=USER_A.user_id,
            provider="gmail",
            tokens={"access_token": "alice_gmail_token", "expires_in": 3600},
            account_email="alice@gmail.com",
        )

        current_user = USER_B

        res = client.get("/api/connectors/gmail/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["connected"])
        self.assertIsNone(data["account_email"])

        search_res = client.get("/api/connectors/gmail/search?q=test")
        self.assertEqual(search_res.status_code, 400)
        self.assertIn("not connected", search_res.json()["detail"])

    # -----------------------------------------------------------------------
    # 10. OAuth callback
    # -----------------------------------------------------------------------
    @patch("connectors.google_oauth.get_google_user_email")
    @patch("connectors.google_oauth.exchange_code_for_tokens")
    def test_10_gmail_callback_flow(self, mock_exchange, mock_email):
        """Gmail callback exchanges code and saves connector under authenticated user."""
        mock_exchange.return_value = {
            "access_token": "cb_gmail_access",
            "refresh_token": "cb_gmail_refresh",
            "expires_in": 3600,
        }
        mock_email.return_value = "alice.callback@gmail.com"

        from routes.connectors import _oauth_states
        state_key = f"{USER_A.user_id}:gmail_csrf_secret"
        _oauth_states[state_key] = USER_A.user_id

        res = client.get(
            f"/api/connectors/gmail/callback?code=valid_gmail_code&state={state_key}",
            follow_redirects=False,
        )
        self.assertEqual(res.status_code, 302)
        self.assertIn("/connectors?status=connected", res.headers["location"])
        self.assertIn("provider=gmail", res.headers["location"])

        conn = connector_repository.get_connector(USER_A.user_id, "gmail")
        self.assertIsNotNone(conn)
        self.assertEqual(conn["account_email"], "alice.callback@gmail.com")
        self.assertEqual(conn["status"], "connected")

        # Verify exchange was called with Gmail redirect URI
        mock_exchange.assert_called_once()
        call_args = mock_exchange.call_args
        self.assertIn("gmail/callback", call_args.kwargs.get("redirect_uri", call_args[1].get("redirect_uri", "")))

    # -----------------------------------------------------------------------
    # 11. Unconfigured OAuth
    # -----------------------------------------------------------------------
    def test_11_gmail_unconfigured_oauth_error(self):
        """Gmail authorize returns 503 when Google credentials are missing."""
        with patch("connectors.google_oauth.is_google_oauth_configured", return_value=False):
            res = client.get("/api/connectors/gmail/authorize")
            self.assertEqual(res.status_code, 503)
            self.assertIn("not configured", res.json()["detail"])

    # -----------------------------------------------------------------------
    # 12. Revoked token during search
    # -----------------------------------------------------------------------
    @patch("connectors.gmail.get_valid_access_token")
    def test_12_revoked_token_during_search_returns_401(self, mock_token):
        """TokenRevokedError during Gmail search returns 401."""
        mock_token.side_effect = TokenRevokedError("Token revoked")
        res = client.get("/api/connectors/gmail/search?q=invoices")
        self.assertEqual(res.status_code, 401)
        self.assertIn("revoked or expired", res.json()["detail"])

    # -----------------------------------------------------------------------
    # 13. Gmail API error handling
    # -----------------------------------------------------------------------
    @patch("connectors.gmail.get_valid_access_token")
    def test_13_gmail_api_error_handling(self, mock_token):
        """GmailAPIError returns 400 with descriptive detail."""
        mock_token.side_effect = GmailAPIError("Rate limit exceeded")
        res = client.get("/api/connectors/gmail/search?q=notes")
        self.assertEqual(res.status_code, 400)
        self.assertIn("Rate limit exceeded", res.json()["detail"])

    # -----------------------------------------------------------------------
    # 14. No results case
    # -----------------------------------------------------------------------
    @patch("connectors.gmail.search_gmail_messages")
    @patch("connectors.gmail.get_valid_access_token")
    def test_14_gmail_search_no_results(self, mock_get_token, mock_search):
        """Search with no matching results returns empty list."""
        mock_get_token.return_value = "valid_token"
        mock_search.return_value = []

        res = client.get("/api/connectors/gmail/search?q=xyznonexistentquery")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["messages"], [])

    # -----------------------------------------------------------------------
    # 15. Stage 18 regression: Drive endpoints still work
    # -----------------------------------------------------------------------
    def test_15_drive_endpoints_still_work(self):
        """Google Drive authorize and status still function after Gmail additions."""
        # Drive authorize
        res = client.get("/api/connectors/google-drive/authorize")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["provider"], "google_drive")
        self.assertIn("drive.readonly", data["authorization_url"])

        # Drive status
        status_res = client.get("/api/connectors/google-drive/status")
        self.assertEqual(status_res.status_code, 200)
        self.assertEqual(status_res.json()["provider"], "google_drive")

        # Combined status includes both Drive and Gmail
        list_res = client.get("/api/connectors/status")
        providers = [c["provider"] for c in list_res.json()]
        self.assertIn("google_drive", providers)
        self.assertIn("gmail", providers)

    # -----------------------------------------------------------------------
    # 16. Gmail and Drive are independent connectors
    # -----------------------------------------------------------------------
    def test_16_gmail_and_drive_are_independent(self):
        """Connecting Gmail does not affect Drive status, and vice versa."""
        # Connect Drive only
        connector_repository.save_connector_tokens(
            owner_id=USER_A.user_id,
            provider="google_drive",
            tokens={"access_token": "drive_token", "expires_in": 3600},
            account_email="alice.drive@gmail.com",
        )

        # Gmail should still be not connected
        gmail_res = client.get("/api/connectors/gmail/status")
        self.assertFalse(gmail_res.json()["connected"])

        # Drive should be connected
        drive_res = client.get("/api/connectors/google-drive/status")
        self.assertTrue(drive_res.json()["connected"])

        # Now connect Gmail too
        connector_repository.save_connector_tokens(
            owner_id=USER_A.user_id,
            provider="gmail",
            tokens={"access_token": "gmail_token", "expires_in": 3600},
            account_email="alice.gmail@gmail.com",
        )

        # Both should be connected
        list_res = client.get("/api/connectors/status")
        statuses = {c["provider"]: c["connected"] for c in list_res.json()}
        self.assertTrue(statuses["google_drive"])
        self.assertTrue(statuses["gmail"])

        # Disconnect Gmail only
        with patch("connectors.google_oauth.revoke_token", return_value=True):
            client.post("/api/connectors/gmail/disconnect")

        # Drive still connected, Gmail not
        gmail_after = client.get("/api/connectors/gmail/status")
        self.assertFalse(gmail_after.json()["connected"])
        drive_after = client.get("/api/connectors/google-drive/status")
        self.assertTrue(drive_after.json()["connected"])


if __name__ == "__main__":
    unittest.main()
