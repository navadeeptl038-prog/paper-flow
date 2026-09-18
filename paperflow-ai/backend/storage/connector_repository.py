"""Storage repository for external OAuth connectors (Stage 18).

Persists and manages connector tokens, account affiliations,
and connection status in PostgreSQL with RLS and isolated memory fallback.
Never exposes raw tokens in public responses.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from services.supabase_client import get_supabase_client

logger = logging.getLogger("paperflow.storage.connectors")

# User-isolated fallback store for testing or environments without migrations
# Structure: dict[owner_id, dict[provider, connector_dict]]
_mem_connectors: dict[str, dict[str, dict[str, Any]]] = {}


def save_connector_tokens(
    owner_id: str,
    provider: str,
    tokens: dict[str, Any],
    account_email: str | None = None,
    account_id: str | None = None,
    scopes: list[str] | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    """Persist or update OAuth tokens and connection state for a user.

    Args:
        owner_id: Authenticated user UUID
        provider: Provider identifier (e.g. 'google_drive')
        tokens: Token payload containing access_token, refresh_token, expires_in/expires_at
        account_email: User's external account email address
        account_id: User's external account unique identifier
        scopes: Granted OAuth scopes
        token: User's Supabase auth JWT token
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now.isoformat()

    expires_at = tokens.get("expires_at")
    if not expires_at and "expires_in" in tokens:
        exp_seconds = int(tokens["expires_in"])
        expires_at = (now + datetime.timedelta(seconds=exp_seconds)).isoformat()

    row_data = {
        "owner_id": owner_id,
        "provider": provider,
        "account_email": account_email,
        "account_id": account_id,
        "access_token": tokens.get("access_token"),
        "refresh_token": tokens.get("refresh_token"),
        "token_type": tokens.get("token_type", "Bearer"),
        "expires_at": expires_at,
        "scopes": scopes or tokens.get("scopes", []),
        "status": "connected",
        "metadata": tokens.get("metadata", {}),
        "updated_at": now_iso,
    }

    # 1. Attempt PostgreSQL upsert via Supabase client
    try:
        client = get_supabase_client()
        if token:
            try:
                client.postgrest.auth(token)
            except Exception:
                pass

        # Check if record exists
        existing = (
            client.table("user_connectors")
            .select("id, refresh_token")
            .eq("owner_id", owner_id)
            .eq("provider", provider)
            .limit(1)
            .execute()
        )

        if existing.data:
            rec_id = existing.data[0]["id"]
            # Preserve existing refresh token if new response did not include one
            if not row_data["refresh_token"] and existing.data[0].get("refresh_token"):
                row_data["refresh_token"] = existing.data[0]["refresh_token"]

            res = client.table("user_connectors").update(row_data).eq("id", rec_id).execute()
            if res.data:
                return res.data[0]
        else:
            row_data["created_at"] = now_iso
            res = client.table("user_connectors").insert(row_data).execute()
            if res.data:
                return res.data[0]
    except Exception as exc:
        logger.debug("Database write to user_connectors failed: %s. Using isolated memory cache.", exc)

    # 2. In-memory user-isolated fallback
    if owner_id not in _mem_connectors:
        _mem_connectors[owner_id] = {}

    prev_conn = _mem_connectors[owner_id].get(provider, {})
    if not row_data["refresh_token"] and prev_conn.get("refresh_token"):
        row_data["refresh_token"] = prev_conn["refresh_token"]

    if "created_at" not in prev_conn:
        row_data["created_at"] = now_iso
    else:
        row_data["created_at"] = prev_conn["created_at"]

    _mem_connectors[owner_id][provider] = row_data
    return row_data


def get_connector(
    owner_id: str,
    provider: str,
    token: str | None = None,
) -> dict[str, Any] | None:
    """Retrieve connector details for an authenticated user. Strictly scopes to owner_id."""
    try:
        client = get_supabase_client()
        if token:
            try:
                client.postgrest.auth(token)
            except Exception:
                pass

        res = (
            client.table("user_connectors")
            .select("*")
            .eq("owner_id", owner_id)
            .eq("provider", provider)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]
    except Exception:
        pass

    user_conn = _mem_connectors.get(owner_id, {})
    return user_conn.get(provider)


def update_connector_tokens(
    owner_id: str,
    provider: str,
    new_access_token: str,
    expires_at: str | None = None,
    token: str | None = None,
) -> bool:
    """Update access token and expiration timestamp upon token refresh."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    update_data = {
        "access_token": new_access_token,
        "expires_at": expires_at,
        "status": "connected",
        "updated_at": now_iso,
    }

    try:
        client = get_supabase_client()
        if token:
            try:
                client.postgrest.auth(token)
            except Exception:
                pass

        res = (
            client.table("user_connectors")
            .update(update_data)
            .eq("owner_id", owner_id)
            .eq("provider", provider)
            .execute()
        )
        if res.data:
            return True
    except Exception:
        pass

    user_conn = _mem_connectors.get(owner_id, {})
    if provider in user_conn:
        user_conn[provider].update(update_data)
        return True

    return False


def mark_connector_status(
    owner_id: str,
    provider: str,
    status: str,
    token: str | None = None,
) -> bool:
    """Update status of a connector (e.g. 'revoked', 'expired', 'disconnected')."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    update_data = {"status": status, "updated_at": now_iso}

    try:
        client = get_supabase_client()
        if token:
            try:
                client.postgrest.auth(token)
            except Exception:
                pass

        res = (
            client.table("user_connectors")
            .update(update_data)
            .eq("owner_id", owner_id)
            .eq("provider", provider)
            .execute()
        )
        if res.data:
            return True
    except Exception:
        pass

    user_conn = _mem_connectors.get(owner_id, {})
    if provider in user_conn:
        user_conn[provider].update(update_data)
        return True

    return False


def delete_connector(
    owner_id: str,
    provider: str,
    token: str | None = None,
) -> bool:
    """Completely remove connector records and stored tokens for a user."""
    deleted = False
    try:
        client = get_supabase_client()
        if token:
            try:
                client.postgrest.auth(token)
            except Exception:
                pass

        res = (
            client.table("user_connectors")
            .delete()
            .eq("owner_id", owner_id)
            .eq("provider", provider)
            .execute()
        )
        if res.data:
            deleted = True
    except Exception:
        pass

    user_conn = _mem_connectors.get(owner_id, {})
    if provider in user_conn:
        del user_conn[provider]
        deleted = True

    return deleted


def list_user_connectors(
    owner_id: str,
    token: str | None = None,
) -> list[dict[str, Any]]:
    """List all connectors for an owner."""
    db_items = []
    try:
        client = get_supabase_client()
        if token:
            try:
                client.postgrest.auth(token)
            except Exception:
                pass

        res = client.table("user_connectors").select("*").eq("owner_id", owner_id).execute()
        db_items = res.data or []
    except Exception:
        pass

    user_conn = _mem_connectors.get(owner_id, {})
    all_map = {c["provider"]: c for c in db_items}
    for prov, cdata in user_conn.items():
        if prov not in all_map:
            all_map[prov] = cdata

    return list(all_map.values())
