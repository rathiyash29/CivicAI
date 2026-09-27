"""
Request-level authorization for the CivicAI API.

This module exists so that authentication dependencies do not have to live in
`backend/main.py`. `backend/router.py` (the intelligence router) needs to
require an officer, and importing `main` from `router` would be circular:
`main` mounts `router` at import time. Importing only `backend.auth` here keeps
the dependency graph one-directional.

Nothing about the JWT itself is re-implemented or changed: tokens are still
issued by `auth.create_access_token` and validated by
`auth.decode_access_token`, and `/auth/*` responses are untouched.
"""
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from backend import auth as auth_module
from backend.auth import UserResponse, UserRole, decode_access_token

# auto_error=False so a missing Authorization header reaches the dependency
# below and becomes a clean 401 instead of FastAPI's own error shape.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

OFFICER_ROLE = UserRole.OFFICER


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> UserResponse:
    """
    The authenticated user, or 401.

    A token with no matching account is a 401 even if it is a validly signed
    JWT: the in-memory account store is empty after a restart, and treating
    that as "anonymous" would silently drop the identity.
    """
    # With auto_error=False a request with no Authorization header arrives here
    # with token=None. Passing None into jose raises AttributeError, which
    # surfaced as a 500 instead of a 401.
    if not token:
        raise _unauthorized()
    token_data = decode_access_token(token)
    if token_data is None:
        raise _unauthorized()
    # Read the account store through the module, not a name bound at import
    # time, so the store is always the live one.
    if token_data.email.isdigit():
        user = auth_module.get_user_by_id(int(token_data.email))
    else:
        user = None
    if user is None:
        user = next((u for u in auth_module.MOCK_USERS_DB.values()
                     if u.email == token_data.email), None)
    if user is None:
        raise _unauthorized()
    return UserResponse(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        created_at=user.created_at,
    )


async def get_current_user_optional(
    token: Optional[str] = Depends(oauth2_scheme),
) -> Optional[UserResponse]:
    """The authenticated user, or None. Used by endpoints with a legacy
    anonymous path that must keep working."""
    if not token:
        return None
    try:
        return await get_current_user(token)
    except HTTPException:
        return None


async def require_officer(
    current_user: UserResponse = Depends(get_current_user),
) -> UserResponse:
    """
    Require the `officer` role. 401 without a usable token, 403 for a citizen.

    Applied as a router-level dependency on the intelligence router so that
    every endpoint under it -- including the mutating ones -- is protected by
    default and a newly added endpoint cannot accidentally be public.
    """
    if (current_user.role or "").strip().lower() != OFFICER_ROLE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is restricted to officers",
        )
    return current_user
