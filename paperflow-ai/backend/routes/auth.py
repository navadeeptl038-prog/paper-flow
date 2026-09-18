"""Authentication routes for PaperFlow AI backend.

Provides:
  GET  /api/auth/me       — return the current authenticated user's profile
  POST /api/auth/refresh  — signal the backend to accept a refreshed token (no-op, Supabase handles refresh)

IMPORTANT — Route registration required:
  These routes must be included in backend/main.py with:
      from routes.auth import router as auth_router
      app.include_router(auth_router)
  This file (main.py) is outside Stage 9 scope. The routes are ready but
  the registration step requires approval to modify main.py.

Security:
  - No password, token, or OTP values are accepted or returned.
  - user_id always comes from the verified JWT (via require_user dependency).
  - No client-supplied user_id in path params or request body is trusted.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from auth.authorization import require_user
from models.user import AuthenticatedUser, UserProfile

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get(
    "/me",
    response_model=UserProfile,
    summary="Get current user profile",
    description=(
        "Returns the profile of the currently authenticated user. "
        "Requires a valid Supabase Bearer token in the Authorization header. "
        "Never returns passwords, tokens, or JWT secrets."
    ),
)
async def get_me(user: AuthenticatedUser = Depends(require_user)) -> UserProfile:
    """Return the current user's safe profile.

    user.user_id is sourced from the verified JWT 'sub' claim.
    username will be populated from the profiles table in a later stage.
    """
    return UserProfile(
        user_id=user.user_id,
        email=user.email,
        username=None,  # Populated from profiles table in Stage 10+
    )


@router.post(
    "/refresh",
    summary="Acknowledge token refresh",
    description=(
        "Called by the frontend after Supabase refreshes the access token. "
        "The backend itself is stateless — Supabase manages token lifecycle. "
        "This endpoint simply confirms the new token is valid."
    ),
)
async def refresh(user: AuthenticatedUser = Depends(require_user)) -> dict:
    """Confirm that the refreshed token is valid on the backend.

    Returns the user_id so the frontend can confirm the refresh was accepted.
    """
    return {"user_id": user.user_id, "status": "token_valid"}
