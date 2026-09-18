"""Authorization dependencies for PaperFlow AI backend routes.

Import `require_user` as a FastAPI dependency to protect any route.
The dependency validates the JWT and returns the AuthenticatedUser.

Security principle:
  - user_id is ALWAYS sourced from the verified JWT, never from a
    client-supplied query param, header, or request body field.
  - Route handlers must use user.user_id for all database filtering.

Usage:
    from auth.authorization import require_user
    from models.user import AuthenticatedUser

    @router.get("/api/documents")
    async def list_documents(user: AuthenticatedUser = Depends(require_user)):
        # Safe: user.user_id comes from the verified JWT
        return await get_documents_for_user(user.user_id)
"""

from __future__ import annotations

from fastapi import Depends

from auth.authentication import get_current_user
from models.user import AuthenticatedUser


async def require_user(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """Require an authenticated user on a protected route.

    Returns:
        AuthenticatedUser with user_id from the verified JWT.

    Raises:
        HTTPException 401: No valid token provided.
        HTTPException 500: JWT secret not configured.
    """
    return user
