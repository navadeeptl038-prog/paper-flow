"""Pydantic models representing authenticated user identity on the backend.

These models describe the shape of the Supabase JWT payload after verification.
They are used by FastAPI dependencies and route handlers to type the current user.

Security notes:
  - user_id comes from the verified JWT claim 'sub' — never from a client-supplied header
  - email is informational — authorization decisions use user_id (sub)
  - role is the Supabase role claim; 'authenticated' = valid session
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AuthenticatedUser(BaseModel):
    """Represents a verified, authenticated Supabase user.

    Populated from the decoded JWT payload by the authentication dependency.
    All fields come from the cryptographically-signed token — never from
    client-supplied request parameters.
    """

    user_id: str = Field(
        ...,
        description="Supabase user UUID from JWT 'sub' claim. Use this for all DB operations.",
    )
    email: str | None = Field(
        default=None,
        description="User email from JWT. May be None for anonymous sessions.",
    )
    role: str = Field(
        default="authenticated",
        description="Supabase role. 'authenticated' = valid session.",
    )
    aal: str | None = Field(
        default=None,
        description="Authenticator Assurance Level from JWT ('aal1' or 'aal2').",
    )


class UserProfile(BaseModel):
    """Public-facing user profile shape returned by /api/auth/me.

    Never includes secrets, password hashes, or full JWT claims.
    """

    user_id: str
    email: str | None = None
    username: str | None = None
